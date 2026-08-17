# -*- coding: utf-8 -*-
"""계산 엔진 테스트 — PRD §13.1

T-C1 이 가장 중요하다. 시드 가격표(`app/seed/data.py`)의 23개 제품 × 3티어에 대해
계산 엔진이 내는 마진율을 고정해 둔 **회귀 기준선(golden baseline)** 이다.
계산식을 건드리면 여기가 먼저 깨진다 — 깨지면 고치기 전에 왜인지 확인할 것.

기대값 표는 아래 스크립트로 재생성한다 (시드 데이터를 바꾼 뒤에만):

    python - <<'EOF'
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Base, Deal
    from app.seed import seed_all, PLAN_CHANNEL_ID
    from app.seed.data import SKUS, TIERS
    from app.services.calc import compute
    e = create_engine("sqlite://"); Base.metadata.create_all(e)
    with Session(e) as db:
        seed_all(db)
        for row in SKUS:
            sid, pack = row[0], row[4]
            v = [compute(db, channel_id=PLAN_CHANNEL_ID,
                         deal=db.get(Deal, f"{sid}-X{pack}-{t}"), order_date="2026-07-15",
                         qty=1, gross_amount=db.get(Deal, f"{sid}-X{pack}-{t}").price).margin_rate
                 for t, _ in TIERS]
            print(f'    "{sid}": ({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f}),')
    EOF

주의: 시드는 전부 가상(목업) 데이터다. 실존 기업·제품과 무관하다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Deal, DealComponent, Sku, SkuCost
from app.seed import PLAN_CHANNEL_ID, seed_all
from app.seed.data import SKUS, TIERS
from app.services.calc import (
    CalcError, breakeven_price, compute, cost_for_margin, price_for_margin,
)

ON = "2026-07-15"

# 테스트 기준 제품 — 즉석밥 210g 24개입 (매입가 760원 × 24개입)
REF, REF_PACK, REF_COST, REF_PRICE = "RICE24", 24, 760, 29900


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_all(s)
        yield s


def _deal(db: Session, sku_id: str, pack: int, tier: str) -> Deal:
    return db.get(Deal, f"{sku_id}-X{pack}-{tier}")


def _ref(db: Session, tier: str = "NORMAL") -> Deal:
    return _deal(db, REF, REF_PACK, tier)


# ── T-C1 · 가격표 재현 ───────────────────────────────────────────────────

# (정상가, 일반행사, 특가) 계획 마진율 — 수수료 13% 고정 · 물류비 3,000원 가정
EXPECTED = {
    "TISSUE30":   ( 0.1476,  0.0670,  0.0025),
    "WIPE10":     ( 0.2052,  0.0713,  0.0139),
    "SOFT2":      ( 0.2309,  0.0930, -0.0376),
    "DISH3":      ( 0.2191,  0.1254,  0.0003),
    "ZIP3":       ( 0.2851,  0.1491,  0.0168),
    "CUP1000":    ( 0.1873,  0.0937,  0.0157),
    "RICE24":     ( 0.1596,  0.0804,  0.0170),
    "RAMEN20":    ( 0.1668,  0.0552, -0.0986),
    "SOUP15":     ( 0.2120,  0.0971,  0.0231),
    "TUNA12":     ( 0.2075,  0.0864,  0.0077),
    "GIM4":       ( 0.2890,  0.1720,  0.0638),
    "CHICK20":    ( 0.1491,  0.0615, -0.0504),
    "CAPSULE100": ( 0.1823,  0.0673, -0.0222),
    "COLDBREW6":  ( 0.3278,  0.1916,  0.0712),
    "JELLY10":    ( 0.2404,  0.1216,  0.0139),
    "NUTS20":     ( 0.2871,  0.1836,  0.0915),
    "PROTEIN30":  ( 0.3411,  0.2463,  0.1420),
    "PROBIO30":   ( 0.4486,  0.3640,  0.2368),
    "VITD90":     ( 0.3996,  0.2981,  0.1406),
    "MILKT90":    ( 0.3665,  0.2398,  0.0933),
    "OMEGA60":    ( 0.3591,  0.2510,  0.0848),
    "LITTER2":    ( 0.2355,  0.1140, -0.0127),
    "PETSNACK50": ( 0.2345,  0.1069,  0.0024),
}


@pytest.mark.parametrize("row", SKUS, ids=[s[0] for s in SKUS])
def test_c1_plan_margin_matches_pricelist(db, row):
    """T-C1 — 23개 제품 × 3티어의 계획 마진율이 기준선과 일치한다."""
    sku_id, pack = row[0], row[4]
    for (tier, idx), expected in zip(TIERS, EXPECTED[sku_id]):
        deal = _deal(db, sku_id, pack, tier)
        r = compute(db, channel_id=PLAN_CHANNEL_ID, deal=deal, order_date=ON,
                    qty=1, gross_amount=deal.price)
        assert r.margin_rate == pytest.approx(expected, abs=1e-4), (
            f"{sku_id} {tier}: 기대 {expected:.4f} 실제 {r.margin_rate:.4f}")


def test_c1b_supply_price_matches_pricelist(db):
    """공급가 = 판매가 × (1 − 수수료율) 이 가격표 '공급가' 열과 일치."""
    r = compute(db, channel_id=PLAN_CHANNEL_ID, deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE)
    assert REF_PRICE - r.channel_fee == 26013     # 가격표 공급가
    assert r.cogs == 18240                        # 원가 = 760원 × 24개입
    assert r.contribution_profit == 4773          # 가격표 당사마진


def test_c1c_loss_deals_are_negative(db):
    """특가에서 적자인 제품 5개가 실제로 음수로 나온다.

    라면 멀티팩·닭가슴살·섬유유연제·커피캡슐·고양이모래 —
    전부 물량은 많지만 원가율이 높아 특가로 내리면 남지 않는 품목이다.
    """
    for sku_id in ("RAMEN20", "CHICK20", "SOFT2", "CAPSULE100", "LITTER2"):
        row = next(r for r in SKUS if r[0] == sku_id)
        deal = _deal(db, sku_id, row[4], "SPECIAL")
        r = compute(db, channel_id=PLAN_CHANNEL_ID, deal=deal, order_date=ON,
                    qty=1, gross_amount=deal.price)
        assert r.contribution_profit < 0, f"{sku_id} 특가는 적자여야 한다"


# ── T-C2 · 수수료 우선순위 ───────────────────────────────────────────────

def test_c2_actual_fee_wins_over_rate(db):
    r = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE, fee_actual=1500)
    assert r.channel_fee == 1500
    assert r.fee_source == "ACTUAL"
    assert r.fee_rate_used is None
    assert r.confidence == "MEASURED"


def test_c2b_rate_used_when_no_actual(db):
    r = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE)
    assert r.fee_source == "RATE"
    assert r.fee_rate_used == pytest.approx(0.095)
    assert r.channel_fee == round(REF_PRICE * 0.095)
    # 한빛홈쇼핑 요율은 정산서에서 역산한 실측값(MEASURED)이므로 추정이 아니다
    assert r.confidence == "MEASURED"


def test_c2c_estimated_rate_marks_confidence(db):
    """요율 근거가 ESTIMATE인 채널만 '추정'으로 표시된다 — 실측을 추정처럼 보이면 안 된다."""
    r = compute(db, channel_id="MALL21", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE)
    assert r.fee_rate_used == pytest.approx(0.130)
    assert r.confidence == "ESTIMATED"


# ── T-C3 · 원가 시점 조회 ────────────────────────────────────────────────

def test_c3_cost_uses_effective_date(db):
    """매입가를 8월부터 올려도 7월 판매의 원가는 그대로다."""
    db.get(SkuCost, db.scalar(
        select(SkuCost.id).where(SkuCost.sku_id == REF))).effective_to = "2026-08-01"
    db.add(SkuCost(sku_id=REF, unit_cost=920, effective_from="2026-08-01"))
    db.flush()

    jul = compute(db, channel_id="HANBIT", deal=_ref(db), order_date="2026-07-15",
                  qty=1, gross_amount=REF_PRICE)
    aug = compute(db, channel_id="HANBIT", deal=_ref(db), order_date="2026-08-15",
                  qty=1, gross_amount=REF_PRICE)
    assert jul.cogs == REF_COST * REF_PACK
    assert aug.cogs == 920 * REF_PACK


def test_c3b_missing_cost_raises(db):
    """요율은 있고 원가만 비는 구간 — 매입가 미등록으로 실패해야 한다."""
    cost = db.get(SkuCost, db.scalar(select(SkuCost.id).where(SkuCost.sku_id == REF)))
    cost.effective_to = "2026-08-01"          # 후속 원가 없이 마감
    db.flush()

    with pytest.raises(CalcError, match="매입가 미등록"):
        compute(db, channel_id="HANBIT", deal=_ref(db), order_date="2026-08-15",
                qty=1, gross_amount=REF_PRICE)


# ── T-C4 · 딜 구성 (증정품 · 복합세트) ───────────────────────────────────

def test_c4_gift_is_included_in_cogs(db):
    """증정품을 원가에서 빼면 이익이 과대 계상된다 — 반드시 포함.

    화장지 30롤에 물티슈 1팩(890원)을 끼워 주는 흔한 오픈마켓 구성.
    """
    deal = _deal(db, "TISSUE30", 30, "EVENT")
    before = compute(db, channel_id="HANBIT", deal=deal, order_date=ON,
                     qty=1, gross_amount=deal.price)

    db.add(DealComponent(deal_id=deal.id, sku_id="WIPE10", qty=1, is_gift=1))
    db.flush()
    db.refresh(deal)

    after = compute(db, channel_id="HANBIT", deal=deal, order_date=ON,
                    qty=1, gross_amount=deal.price)
    assert after.cogs == before.cogs + 890
    assert after.contribution_profit == before.contribution_profit - 890


def test_c4b_composite_set(db):
    """3종 복합세트 원가 = 3개 SKU 매입가 합 (즉석밥 + 즉석국 + 김자반)"""
    db.add(Deal(id="COMBO3", channel_id=None, primary_sku_id=REF,
                label="홈캉스 3종 세트", tier="EVENT", price=42900,
                effective_from="2026-01-01"))
    for sku in (REF, "SOUP15", "GIM4"):
        db.add(DealComponent(deal_id="COMBO3", sku_id=sku, qty=1))
    db.flush()

    r = compute(db, channel_id="HANBIT", deal=db.get(Deal, "COMBO3"),
                order_date=ON, qty=1, gross_amount=42900)
    assert r.cogs == 760 + 980 + 1850


def test_c4c_qty_multiplies(db):
    one = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                  qty=1, gross_amount=REF_PRICE)
    three = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                    qty=3, gross_amount=REF_PRICE * 3)
    assert three.cogs == one.cogs * 3
    assert three.logistics_cost == one.logistics_cost * 3


# ── T-C5 · 손익분기 판매가 ───────────────────────────────────────────────

@pytest.mark.parametrize("rate,expected", [(0.095, 17017), (0.110, 17303), (0.130, 17701)])
def test_c5_breakeven(rate, expected):
    """얼큰라면 20개입 멀티팩: 원가 12,400(620원 × 20개) + 물류 3,000"""
    assert breakeven_price(12400, 3000, rate) == expected


def test_c5b_price_for_target_margin():
    # 라면 멀티팩을 한빛홈쇼핑(9.5%)에서 마진율 8%로 팔려면
    price = price_for_margin(12400, 3000, 0.095, 0.08)
    assert price == 18667
    # 역검산 — 그 가격으로 실제 마진율이 8%인가
    profit = price - round(price * 0.095) - 12400 - 3000
    assert profit / price == pytest.approx(0.08, abs=1e-4)


def test_c5c_cost_for_target_margin():
    # 특가 15,900원을 유지하며 마진율 5%를 확보하려면 매입가가 얼마여야 하나
    cost = cost_for_margin(15900, 3000, 0.095, 0.05)
    assert cost == 10594
    profit = 15900 - round(15900 * 0.095) - cost - 3000
    assert profit / 15900 == pytest.approx(0.05, abs=1e-3)


def test_c5d_impossible_target_raises():
    with pytest.raises(CalcError, match="달성 불가"):
        price_for_margin(12400, 3000, 0.93, 0.10)


# ── T-C6 · 경계값 ────────────────────────────────────────────────────────

def test_c6_zero_revenue_gives_null_margin(db):
    r = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE, is_cancelled=True)
    assert r.net_revenue == 0
    assert r.margin_rate is None


def test_c6e_cancelled_line_costs_nothing(db):
    """취소 건은 매출도 원가도 물류비도 0이다.

    원가만 남겨 두면 취소 1건마다 원가 전액이 이익에서 사라져,
    취소가 많은 달의 이익이 실제보다 크게 낮아진다.
    """
    r = compute(db, channel_id="HANBIT", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE, own_discount=500, is_cancelled=True)
    assert (r.net_revenue, r.channel_fee, r.cogs, r.logistics_cost) == (0, 0, 0, 0)
    assert r.contribution_profit == 0


def test_c6b_channel_bears_logistics(db):
    """위탁매입 채널(대림홈쇼핑)은 물류비 0"""
    r = compute(db, channel_id="DAERIM_HS", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE)
    assert r.logistics_cost == 0


def test_c6c_identity_holds(db):
    """V2 — net − fee − discount − cogs − logi = profit"""
    deal = _deal(db, "PROBIO30", 30, "EVENT")
    r = compute(db, channel_id="HANBIT", deal=deal, order_date=ON,
                qty=7, gross_amount=deal.price * 7, own_discount=1000)
    assert (r.net_revenue - r.channel_fee - r.own_discount
            - r.cogs - r.logistics_cost) == r.contribution_profit


def test_c6d_missing_fee_rate_raises(db):
    """요율 미등록 채널(페이샵)은 CalcError"""
    with pytest.raises(CalcError, match="채널 요율 미등록"):
        compute(db, channel_id="PAYSHOP", deal=_ref(db), order_date=ON,
                qty=1, gross_amount=REF_PRICE)


# ── 시드 검증 ────────────────────────────────────────────────────────────

def test_seed_loaded(db):
    from sqlalchemy import func
    assert db.scalar(select(func.count()).select_from(Sku)) == 23
    assert db.scalar(select(func.count()).select_from(Deal)) == 69
    # 채널 14개 + 계획용 가상 채널 1개
    from app.models import Channel
    assert db.scalar(select(func.count()).select_from(Channel)) == 15
