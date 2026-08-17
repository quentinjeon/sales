# -*- coding: utf-8 -*-
"""초기 데이터 적재 — PRD §14"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Channel, ChannelFee, ChannelLogistics, Deal, DealComponent, Sku, SkuCost,
)
from app.seed.data import CHANNELS, EFFECTIVE_FROM, SKUS, TIERS

# 계획 마진율 산출에 쓰는 가상 채널 — 기존 가격표의 13% 고정 가정을 재현한다.
PLAN_CHANNEL_ID = "_PLAN"
PLAN_FEE_RATE = 0.13
PLAN_SHIPPING = 3000


def seed_channels(db: Session) -> int:
    n = 0
    for (cid, name, group, status, rate, rate_src, ship_owner,
         logi_model, logi_amt, logi_est, settle, vat, order, note) in CHANNELS:
        if db.get(Channel, cid):
            continue
        db.add(Channel(
            id=cid, name=name, group_name=group, status=status,
            fee_base="PURCHASE" if ship_owner == "CONSIGNMENT" else "PRICE",
            ship_owner=ship_owner, settle_date_src=settle, vat_basis=vat,
            sort_order=order, note=note,
        ))
        if rate is not None:
            db.add(ChannelFee(channel_id=cid, fee_rate=rate, source=rate_src,
                              effective_from=EFFECTIVE_FROM))
        db.add(ChannelLogistics(channel_id=cid, model=logi_model, flat_amount=logi_amt,
                                is_estimate=logi_est, effective_from=EFFECTIVE_FROM))
        n += 1
    db.flush()
    return n


def seed_plan_channel(db: Session) -> None:
    """가격표의 '계획 마진율'(수수료 13% 고정)을 재현하기 위한 가상 채널."""
    if db.get(Channel, PLAN_CHANNEL_ID):
        return
    db.add(Channel(
        id=PLAN_CHANNEL_ID, name="계획(가격표 가정)", group_name="내부",
        fee_base="PRICE", ship_owner="SELF", settle_date_src="CONFIRM",
        vat_basis="EXCLUDED", status="RETIRED", sort_order=999,
        note="가격표의 수수료 13% 고정 가정을 재현하는 가상 채널. 실적 집계에서 제외.",
    ))
    db.add(ChannelFee(channel_id=PLAN_CHANNEL_ID, fee_rate=PLAN_FEE_RATE,
                      source="CONTRACT", effective_from=EFFECTIVE_FROM))
    db.add(ChannelLogistics(channel_id=PLAN_CHANNEL_ID, model="FLAT",
                            flat_amount=PLAN_SHIPPING, effective_from=EFFECTIVE_FROM))
    db.flush()


def seed_skus(db: Session) -> int:
    n = 0
    for sku_id, name, spec, cost, *_ in SKUS:
        if db.get(Sku, sku_id):
            continue
        db.add(Sku(id=sku_id, name=name, spec=spec, brand="온담식품"))
        db.add(SkuCost(sku_id=sku_id, unit_cost=cost, effective_from=EFFECTIVE_FROM,
                       source="온담식품_제품별가격표.xlsx"))
        n += 1
    db.flush()
    return n


def seed_deals(db: Session, channel_id: str | None = None) -> int:
    """제품 23개 × 티어 3종 = 69개 딜. channel_id=None 이면 전 채널 공통 딜."""
    n = 0
    suffix = f"-{channel_id}" if channel_id else ""
    for row in SKUS:
        sku_id, name, _spec, _cost, pack = row[0], row[1], row[2], row[3], row[4]
        for tier, idx in TIERS:
            price = row[idx]
            deal_id = f"{sku_id}-X{pack}-{tier}{suffix}"
            if db.get(Deal, deal_id):
                continue
            db.add(Deal(
                id=deal_id, channel_id=channel_id, primary_sku_id=sku_id,
                label=f"{name} ×{pack}", tier=tier, price=price,
                effective_from=EFFECTIVE_FROM,
            ))
            db.add(DealComponent(deal_id=deal_id, sku_id=sku_id, qty=pack))
            n += 1
    db.flush()
    return n


def seed_all(db: Session) -> dict[str, int]:
    result = {
        "channels": seed_channels(db),
        "skus": seed_skus(db),
        "deals": seed_deals(db),
    }
    seed_plan_channel(db)
    db.commit()
    return result
