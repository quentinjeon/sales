# -*- coding: utf-8 -*-
"""상품명 매핑 엔진 — PRD §8

채널마다 상품명이 제각각이다. 이 연결이 없으면 그 주문은 손익에서 빠지므로,
미매핑은 조용히 사라지지 않고 항상 노출되어야 한다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deal, NameMapping, SalesLine

# 옵션명에서 구성 배수를 뽑는 패턴 — 'x2개', '×3', '2개세트'
_PACK_RE = re.compile(r"(?:x|×|\*)\s*(\d+)\s*개?|(\d+)\s*개\s*세트")
# 증정품·복합세트 신호 — 기존 딜에 붙이면 원가가 틀어진다 (§8.4)
_SPECIAL_RE = re.compile(r"증정|사은품|\+\s*\d|(\d+)\s*종")


def normalize(s: str | None) -> str:
    """매핑 키 정규화 (§8.1)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)      # [여름특가] (2개세트) 제거
    s = re.sub(r"[^0-9a-z가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_pack(*texts: str | None) -> int | None:
    """옵션명 등에서 구성 배수를 추출한다."""
    for t in texts:
        if not t:
            continue
        m = _PACK_RE.search(t)
        if m:
            return int(m.group(1) or m.group(2))
    return None


def looks_special(*texts: str | None) -> bool:
    """증정품 포함·복합세트로 보이는가 — 새 딜 등록을 권해야 한다."""
    return any(_SPECIAL_RE.search(t) for t in texts if t)


# ── 조회 ────────────────────────────────────────────────────────────────

def lookup(db: Session, channel_id: str, product: str, option: str = "") -> str | None:
    """등록된 규칙에서 deal_id 를 찾는다 (§8.2). 옵션 포함 → 옵션 무시 순."""
    pkey, okey = normalize(product), normalize(option)
    for key in (okey, ""):
        row = db.scalar(
            select(NameMapping).where(
                NameMapping.channel_id == channel_id,
                NameMapping.raw_product_key == pkey,
                NameMapping.raw_option_key == key,
            )
        )
        if row:
            row.hit_count += 1
            return row.deal_id
    return None


def register(db: Session, *, channel_id: str, product: str, option: str,
             deal_id: str, match_type: str = "MANUAL", actor: str | None = None) -> NameMapping:
    pkey, okey = normalize(product), normalize(option)
    row = db.scalar(
        select(NameMapping).where(
            NameMapping.channel_id == channel_id,
            NameMapping.raw_product_key == pkey,
            NameMapping.raw_option_key == okey,
        )
    )
    if row:
        row.deal_id, row.match_type = deal_id, match_type
    else:
        row = NameMapping(channel_id=channel_id, raw_product_key=pkey, raw_option_key=okey,
                          deal_id=deal_id, match_type=match_type, created_by=actor)
        db.add(row)
    db.flush()
    return row


# ── 자동 제안 ───────────────────────────────────────────────────────────

@dataclass
class Suggestion:
    deal: Deal
    score: float
    name_score: float
    price_score: float
    pack_score: float

    @property
    def is_top(self) -> bool:
        return self.score >= 0.85


def active_deals(db: Session, channel_id: str, on: str) -> list[Deal]:
    """판매일 기준 유효한 딜 — 채널 전용 딜 + 전 채널 공통 딜."""
    return list(db.scalars(
        select(Deal).where(
            Deal.is_active == 1,
            Deal.effective_from <= on,
            (Deal.effective_to.is_(None)) | (Deal.effective_to > on),
            (Deal.channel_id.is_(None)) | (Deal.channel_id == channel_id),
        )
    ).all())


def exact_match(db: Session, *, channel_id: str, product: str, option: str,
                on: str) -> str | None:
    """정규화 후 딜 라벨과 '정확히' 같으면 연결한다 (§8.2 · PRD §6-1).

    후보가 여럿이면 옵션명이 티어와 일치하는 것을 고른다.
    그래도 하나로 좁혀지지 않으면 연결하지 않는다 — 틀리게 붙이느니 미매핑이 낫다.
    """
    npro = normalize(product)
    if not npro:
        return None
    cands = [d for d in active_deals(db, channel_id, on) if normalize(d.label) == npro]
    if not cands:
        return None
    nopt = normalize(option)
    if nopt:
        hit = [d for d in cands if normalize(d.tier) == nopt]
        if len(hit) == 1:
            return hit[0].id
    return cands[0].id if len(cands) == 1 else None


def suggest(db: Session, *, channel_id: str, product: str, option: str,
            unit_price: int | None, on: str, limit: int = 3) -> list[Suggestion]:
    """미매핑 라인에 대한 딜 후보 (§8.3).

    score = 0.55×이름유사도 + 0.30×가격일치 + 0.15×구성수량일치
    """
    deals = active_deals(db, channel_id, on)

    npro, nopt = normalize(product), normalize(option)
    want_pack = extract_pack(option, product)
    out: list[Suggestion] = []

    for d in deals:
        nlabel = normalize(d.label)
        nsku = normalize(d.primary_sku_id)
        name = max(
            fuzz.token_set_ratio(npro, nlabel),
            fuzz.token_set_ratio(nopt, nlabel) if nopt else 0,
            fuzz.token_set_ratio(npro, nsku),
        ) / 100.0

        if unit_price is None:
            price = 0.5                                    # 판단 불가 — 중립
        elif abs(unit_price - d.price) <= 100:
            price = 1.0
        else:
            price = max(0.0, 1 - abs(unit_price - d.price) / d.price)

        deal_pack = sum(c.qty for c in d.components)
        pack = 1.0 if (want_pack is not None and want_pack == deal_pack) else 0.0

        out.append(Suggestion(deal=d, score=0.55 * name + 0.30 * price + 0.15 * pack,
                              name_score=name, price_score=price, pack_score=pack))

    out.sort(key=lambda s: -s.score)
    return out[:limit]


# ── 일괄 적용 ───────────────────────────────────────────────────────────

def map_lines(db: Session, lines: list[SalesLine]) -> dict[str, int]:
    """라인들의 deal_id 를 채운다. 실패는 UNMAPPED 로 남긴다 — 조용히 버리지 않는다.

    ① 등록된 규칙 → ② 정규화 정확일치(찾으면 규칙으로 등록) → ③ 미매핑
    """
    stat = {"mapped": 0, "auto": 0, "unmapped": 0}
    for ln in lines:
        if ln.map_status == "EXCLUDED":
            continue
        deal_id = lookup(db, ln.channel_id, ln.raw_product_name, ln.raw_option_name)
        if deal_id is None:
            deal_id = exact_match(db, channel_id=ln.channel_id, product=ln.raw_product_name,
                                  option=ln.raw_option_name, on=ln.order_date)
            if deal_id:
                register(db, channel_id=ln.channel_id, product=ln.raw_product_name,
                         option=ln.raw_option_name, deal_id=deal_id,
                         match_type="EXACT", actor="auto")
                stat["auto"] += 1
        if deal_id:
            ln.deal_id, ln.map_status = deal_id, "MAPPED"
            stat["mapped"] += 1
        else:
            ln.deal_id, ln.map_status = None, "UNMAPPED"
            stat["unmapped"] += 1
    db.flush()
    return stat
