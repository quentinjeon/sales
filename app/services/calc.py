# -*- coding: utf-8 -*-
"""손익 계산 엔진 — PRD §6

계산식 (가격표의 '당사마진' 열과 일치함을 검증했다):
    순매출   = 판매금액                     (취소면 0)
    수수료   = 실적값 우선, 없으면 순매출 × 채널요율
    원가     = Σ(component.qty × 판매일 기준 매입가) × 판매수량
    물류비   = 채널 배송비 모델 × 판매수량
    기여이익 = 순매출 − 수수료 − 자사부담할인 − 원가 − 물류비
    마진율   = 기여이익 ÷ 순매출
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Channel, ChannelFee, ChannelLogistics, Deal, SalesLine, Sku, SkuCost,
)

CALC_VERSION = "calc-1.0"


class CalcError(Exception):
    """계산 불가 — 원가/요율 누락 등. 해당 라인만 실패시키고 배치는 진행한다."""


@dataclass(frozen=True)
class LineResult:
    net_revenue: int
    channel_fee: int
    fee_source: str                 # ACTUAL | RATE
    fee_rate_used: float | None
    cogs: int
    logistics_cost: int
    logistics_estimated: bool
    own_discount: int
    contribution_profit: int
    margin_rate: float | None
    confidence: str                 # MEASURED | ESTIMATED


# ── 시점 기준 마스터 조회 ────────────────────────────────────────────────

def _effective(rows, on: str):
    """effective_from <= on < effective_to 인 행 하나를 고른다."""
    for r in rows:
        if r.effective_from <= on and (r.effective_to is None or on < r.effective_to):
            return r
    return None


def get_fee_rate(db: Session, channel_id: str, on: str) -> tuple[float, str]:
    rows = db.scalars(
        select(ChannelFee).where(ChannelFee.channel_id == channel_id)
        .order_by(ChannelFee.effective_from.desc())
    ).all()
    row = _effective(rows, on)
    if row is None:
        raise CalcError(f"채널 요율 미등록: {channel_id} ({on})")
    return row.fee_rate, row.source


def get_sku_cost(db: Session, sku_id: str, on: str) -> int:
    rows = db.scalars(
        select(SkuCost).where(SkuCost.sku_id == sku_id)
        .order_by(SkuCost.effective_from.desc())
    ).all()
    row = _effective(rows, on)
    if row is None:
        raise CalcError(f"매입가 미등록: {sku_id} ({on})")
    return row.unit_cost


def get_logistics(db: Session, channel_id: str, on: str) -> ChannelLogistics:
    rows = db.scalars(
        select(ChannelLogistics).where(ChannelLogistics.channel_id == channel_id)
        .order_by(ChannelLogistics.effective_from.desc())
    ).all()
    row = _effective(rows, on)
    if row is None:
        raise CalcError(f"물류비 모델 미등록: {channel_id} ({on})")
    return row


def deal_unit_cogs(db: Session, deal: Deal, on: str) -> int:
    """딜 1건의 원가. 증정품(is_gift)도 포함한다 — 빼면 이익이 과대 계상된다."""
    if not deal.components:
        raise CalcError(f"딜 구성 미등록: {deal.id}")
    return sum(c.qty * get_sku_cost(db, c.sku_id, on) for c in deal.components)


# ── 계산 ────────────────────────────────────────────────────────────────

def compute(
    db: Session,
    *,
    channel_id: str,
    deal: Deal,
    order_date: str,
    qty: int,
    gross_amount: int,
    fee_actual: int | None = None,
    own_discount: int = 0,
    is_cancelled: bool = False,
) -> LineResult:
    """한 주문 라인의 손익. 순수 계산 — DB 쓰기는 하지 않는다."""
    net = 0 if is_cancelled else gross_amount

    # 수수료: 채널이 준 실적값이 있으면 그것을 쓴다 (§6.3)
    if fee_actual is not None:
        fee, src, rate, fee_estimated = (0 if is_cancelled else fee_actual), "ACTUAL", None, False
    else:
        rate, rate_src = get_fee_rate(db, channel_id, order_date)
        fee, src = round(net * rate), "RATE"
        # 요율 자체가 추정값일 때만 '추정'이다. 정산서에서 역산한 실측 요율은 추정이 아니다.
        fee_estimated = (rate_src == "ESTIMATE")

    # 취소 건은 매출도 원가도 물류비도 발생하지 않는다.
    # 여기서 원가를 빼면 취소 1건마다 원가 전액이 이익에서 사라진다.
    if is_cancelled:
        cogs, logi, logi_estimated = 0, 0, False
    else:
        cogs = deal_unit_cogs(db, deal, order_date) * qty

        logi_model = get_logistics(db, channel_id, order_date)
        if logi_model.model == "FLAT":
            logi = (logi_model.flat_amount or 0) * qty
        elif logi_model.model == "CHANNEL_BEARS":
            logi = 0
        else:                                        # TABLE — P1
            raise CalcError(f"물류비 TABLE 모델 미구현: {channel_id}")
        logi_estimated = bool(logi_model.is_estimate)

    if is_cancelled:
        own_discount = 0
    profit = net - fee - own_discount - cogs - logi
    margin = (profit / net) if net else None
    confidence = "ESTIMATED" if (fee_estimated or logi_estimated) else "MEASURED"

    return LineResult(
        net_revenue=net, channel_fee=fee, fee_source=src, fee_rate_used=rate,
        cogs=cogs, logistics_cost=logi, logistics_estimated=logi_estimated,
        own_discount=own_discount, contribution_profit=profit,
        margin_rate=margin, confidence=confidence,
    )


def apply_to_line(db: Session, line: SalesLine, deal: Deal) -> None:
    """계산 결과를 sales_line 에 스냅샷으로 기록."""
    r = compute(
        db,
        channel_id=line.channel_id, deal=deal, order_date=line.order_date,
        qty=line.qty, gross_amount=line.gross_amount, fee_actual=line.fee_actual,
        own_discount=line.own_discount, is_cancelled=bool(line.is_cancelled),
    )
    line.net_revenue = r.net_revenue
    line.channel_fee = r.channel_fee
    line.fee_source = r.fee_source
    line.fee_rate_used = r.fee_rate_used
    line.cogs = r.cogs
    line.logistics_cost = r.logistics_cost
    line.logistics_estimated = int(r.logistics_estimated)
    line.contribution_profit = r.contribution_profit
    line.margin_rate = r.margin_rate
    line.confidence = r.confidence
    line.calc_version = CALC_VERSION
    line.calculated_at = datetime.now().isoformat(timespec="seconds")


def clear_calc(line: SalesLine) -> None:
    for f in ("net_revenue", "channel_fee", "fee_source", "fee_rate_used", "cogs",
              "logistics_cost", "contribution_profit", "margin_rate", "calc_version",
              "calculated_at"):
        setattr(line, f, None)
    line.logistics_estimated = 0
    line.confidence = "UNMAPPED"


# ── 역산 (화면 03 딜 상세) ───────────────────────────────────────────────

def breakeven_price(unit_cogs: int, logistics: int, fee_rate: float) -> int:
    """손익분기 판매가 = (원가 + 물류비) / (1 − 수수료율)"""
    return round((unit_cogs + logistics) / (1 - fee_rate))


def price_for_margin(unit_cogs: int, logistics: int, fee_rate: float, target: float) -> int:
    """목표 마진율 달성 판매가 = (원가 + 물류비) / (1 − 수수료율 − 목표마진율)"""
    denom = 1 - fee_rate - target
    if denom <= 0:
        raise CalcError(f"목표 마진율 {target:.1%} 은 수수료율 {fee_rate:.1%} 에서 달성 불가")
    return round((unit_cogs + logistics) / denom)


def cost_for_margin(price: int, logistics: int, fee_rate: float, target: float) -> int:
    """목표 마진율 달성에 필요한 원가 (매입가 재협상 옵션)"""
    return round(price * (1 - fee_rate - target) - logistics)
