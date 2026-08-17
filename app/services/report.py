# -*- coding: utf-8 -*-
"""리포트 집계 — PRD §9

sales_line 을 기간·채널·제품·딜 축으로 집계한다.
데이터 규모가 작아 P0 에서는 마트 없이 원장 직접 집계로 충분하다 (§5.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Channel, Deal, SalesLine, Sku

MAPPED = SalesLine.map_status == "MAPPED"


# ── 기간 헬퍼 ───────────────────────────────────────────────────────────

def period_keys(d: date) -> tuple[str, str]:
    """(period_month, period_week) — 주차는 ISO 8601 (월~일)."""
    y, w, _ = d.isocalendar()
    return f"{d:%Y-%m}", f"{y}-W{w:02d}"


def prev_period(period: str, ptype: str) -> str:
    """직전 기간 키. 기간 키 형식이 아니면 빈 문자열 — 데이터가 없는 화면에서도 죽지 않는다."""
    try:
        if ptype == "MONTH":
            y, m = map(int, period.split("-"))
            return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"
        y, w = int(period[:4]), int(period[6:])
        monday = date.fromisocalendar(y, w, 1) - timedelta(days=7)
        return period_keys(monday)[1]
    except (ValueError, IndexError):
        return ""


def weeks_in_month(db: Session, month: str) -> list[str]:
    col = SalesLine.period_week
    rows = db.scalars(
        select(col).where(SalesLine.period_month == month, MAPPED)
        .group_by(col).order_by(col)
    ).all()
    return list(rows)


def _period_filter(period: str, ptype: str):
    col = SalesLine.period_month if ptype == "MONTH" else SalesLine.period_week
    return col == period


# ── 집계 ────────────────────────────────────────────────────────────────

_SUMS = (
    func.coalesce(func.sum(SalesLine.net_revenue), 0),
    func.coalesce(func.sum(SalesLine.channel_fee), 0),
    func.coalesce(func.sum(SalesLine.cogs), 0),
    func.coalesce(func.sum(SalesLine.logistics_cost), 0),
    func.coalesce(func.sum(SalesLine.contribution_profit), 0),
    func.coalesce(func.sum(SalesLine.qty), 0),
    func.count(SalesLine.id),
)


@dataclass
class Totals:
    revenue: int = 0
    fee: int = 0
    cogs: int = 0
    logistics: int = 0
    profit: int = 0
    qty: int = 0
    orders: int = 0

    @property
    def margin(self) -> float | None:
        return self.profit / self.revenue if self.revenue else None

    @property
    def profit_per_order(self) -> int:
        return round(self.profit / self.orders) if self.orders else 0


def totals(db: Session, period: str, ptype: str = "MONTH") -> Totals:
    r = db.execute(select(*_SUMS).where(_period_filter(period, ptype), MAPPED)).one()
    return Totals(*r)


@dataclass
class Row:
    key: str
    name: str
    sub: str = ""
    revenue: int = 0
    fee: int = 0
    cogs: int = 0
    logistics: int = 0
    profit: int = 0
    qty: int = 0
    orders: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def margin(self) -> float | None:
        return self.profit / self.revenue if self.revenue else None

    @property
    def profit_per_order(self) -> int:
        return round(self.profit / self.orders) if self.orders else 0

    @property
    def level(self) -> str:
        """화면 색상 구분 — 적자 / 주의 / 정상."""
        m = self.margin
        if m is None:
            return "none"
        return "neg" if m < 0 else ("warn" if m < 0.05 else "pos")


def _rows(db: Session, stmt: Select) -> list[Row]:
    return [Row(key=str(r[0]), name=str(r[1] or r[0]), sub=str(r[2] or ""),
                revenue=r[3], fee=r[4], cogs=r[5], logistics=r[6],
                profit=r[7], qty=r[8], orders=r[9])
            for r in db.execute(stmt).all()]


def by_channel(db: Session, period: str, ptype: str = "MONTH") -> list[Row]:
    stmt = (
        select(Channel.id, Channel.name, Channel.group_name, *_SUMS)
        .join(SalesLine, SalesLine.channel_id == Channel.id)
        .where(_period_filter(period, ptype), MAPPED)
        .group_by(Channel.id).order_by(func.sum(SalesLine.net_revenue).desc())
    )
    rows = _rows(db, stmt)
    for r in rows:
        fee_rate = db.scalar(
            select(func.avg(SalesLine.fee_rate_used))
            .where(SalesLine.channel_id == r.key, _period_filter(period, ptype), MAPPED))
        est = db.scalar(
            select(func.count()).select_from(SalesLine)
            .where(SalesLine.channel_id == r.key, _period_filter(period, ptype), MAPPED,
                   SalesLine.confidence == "ESTIMATED"))
        r.extra = {"fee_rate": fee_rate, "estimated": bool(est)}
    return rows


def by_product(db: Session, period: str, ptype: str = "MONTH", limit: int | None = None) -> list[Row]:
    stmt = (
        select(Sku.id, Sku.name, Sku.spec, *_SUMS)
        .join(Deal, Deal.primary_sku_id == Sku.id)
        .join(SalesLine, SalesLine.deal_id == Deal.id)
        .where(_period_filter(period, ptype), MAPPED)
        .group_by(Sku.id).order_by(func.sum(SalesLine.contribution_profit).desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return _rows(db, stmt)


def by_deal(db: Session, period: str, ptype: str = "MONTH",
            channel_id: str | None = None, tier: str | None = None,
            order: str = "margin") -> list[Row]:
    stmt = (
        select(Deal.id, Deal.label, Channel.name, *_SUMS,
               Deal.tier, Deal.price, Deal.primary_sku_id, SalesLine.channel_id)
        .join(SalesLine, SalesLine.deal_id == Deal.id)
        .join(Channel, Channel.id == SalesLine.channel_id)
        .where(_period_filter(period, ptype), MAPPED)
        .group_by(Deal.id, SalesLine.channel_id)
    )
    if channel_id:
        stmt = stmt.where(SalesLine.channel_id == channel_id)
    if tier:
        stmt = stmt.where(Deal.tier == tier)

    out = []
    for r in db.execute(stmt).all():
        row = Row(key=f"{r[0]}|{r[13]}", name=str(r[1]), sub=str(r[2]),
                  revenue=r[3], fee=r[4], cogs=r[5], logistics=r[6],
                  profit=r[7], qty=r[8], orders=r[9])
        row.extra = {"tier": r[10], "price": r[11], "sku_id": r[12],
                     "deal_id": r[0], "channel_id": r[13]}
        out.append(row)

    keys = {"margin": lambda x: (x.margin if x.margin is not None else 9),
            "profit": lambda x: -x.profit,
            "revenue": lambda x: -x.revenue}
    out.sort(key=keys.get(order, keys["margin"]))
    return out


def by_tier(db: Session, period: str, ptype: str = "MONTH") -> list[Row]:
    stmt = (
        select(Deal.tier, Deal.tier, Deal.tier, *_SUMS)
        .join(SalesLine, SalesLine.deal_id == Deal.id)
        .where(_period_filter(period, ptype), MAPPED)
        .group_by(Deal.tier).order_by(func.sum(SalesLine.net_revenue).desc())
    )
    return _rows(db, stmt)


def loss_deals(db: Session, period: str, ptype: str = "MONTH") -> list[Row]:
    return [r for r in by_deal(db, period, ptype) if (r.margin or 0) < 0]


def weekly_trend(db: Session, month: str) -> list[Row]:
    stmt = (
        select(SalesLine.period_week, SalesLine.period_week, SalesLine.period_week, *_SUMS)
        .where(SalesLine.period_month == month, MAPPED)
        .group_by(SalesLine.period_week).order_by(SalesLine.period_week)
    )
    return _rows(db, stmt)


def heatmap(db: Session, period: str, ptype: str = "MONTH") -> tuple[list[str], list[dict]]:
    """채널 × 제품 마진율. (채널 목록, 제품별 행)"""
    chans = db.scalars(
        select(Channel.id).where(Channel.status == "ACTIVE").order_by(Channel.sort_order)).all()
    chan_names = {c.id: c.name for c in db.scalars(select(Channel)).all()}

    stmt = (
        select(Sku.id, Sku.name, SalesLine.channel_id,
               func.sum(SalesLine.net_revenue), func.sum(SalesLine.contribution_profit))
        .join(Deal, Deal.primary_sku_id == Sku.id)
        .join(SalesLine, SalesLine.deal_id == Deal.id)
        .where(_period_filter(period, ptype), MAPPED)
        .group_by(Sku.id, SalesLine.channel_id)
    )
    cells: dict[str, dict] = {}
    for sku_id, name, ch, rev, prof in db.execute(stmt).all():
        e = cells.setdefault(sku_id, {"name": name, "cells": {}, "revenue": 0, "profit": 0})
        e["cells"][ch] = (prof / rev) if rev else None
        e["revenue"] += rev
        e["profit"] += prof

    rows = []
    for sku_id, e in cells.items():
        rows.append({
            "sku_id": sku_id, "name": e["name"],
            "cells": [e["cells"].get(c) for c in chans],
            "total": (e["profit"] / e["revenue"]) if e["revenue"] else None,
        })
    rows.sort(key=lambda r: -(r["total"] if r["total"] is not None else -9))
    return [chan_names.get(c, c) for c in chans], rows


def biggest_gap(db: Session, period: str, ptype: str = "MONTH", min_orders: int = 20):
    """같은 제품의 채널 간 최대 마진율 격차 (§9.3.1). 5%p 미만이면 None."""
    best = None
    deals = by_deal(db, period, ptype)
    by_sku: dict[str, list[Row]] = {}
    for r in deals:
        if r.orders >= min_orders:
            by_sku.setdefault(r.extra["sku_id"], []).append(r)
    for sku_id, rows in by_sku.items():
        if len(rows) < 2:
            continue
        hi = max(rows, key=lambda x: x.margin or -9)
        lo = min(rows, key=lambda x: x.margin or 9)
        gap = (hi.margin or 0) - (lo.margin or 0)
        if gap >= 0.05 and (best is None or gap > best["gap"]):
            best = {"sku_id": sku_id, "name": hi.name, "gap": gap, "high": hi, "low": lo}
    return best


# ── 데이터 품질 ─────────────────────────────────────────────────────────

@dataclass
class Quality:
    channels_collected: int = 0
    channels_active: int = 0
    unmapped_count: int = 0
    unmapped_amount: int = 0
    mapping_rate: float = 1.0
    estimated_revenue_share: float = 0.0


def quality(db: Session, period: str, ptype: str = "MONTH") -> Quality:
    pf = _period_filter(period, ptype)
    total_lines = db.scalar(select(func.count()).select_from(SalesLine).where(pf)) or 0
    un_cnt = db.scalar(select(func.count()).select_from(SalesLine)
                       .where(pf, SalesLine.map_status == "UNMAPPED")) or 0
    un_amt = db.scalar(select(func.coalesce(func.sum(SalesLine.gross_amount), 0))
                       .where(pf, SalesLine.map_status == "UNMAPPED")) or 0
    collected = db.scalar(select(func.count(func.distinct(SalesLine.channel_id))).where(pf)) or 0
    active = db.scalar(select(func.count()).select_from(Channel)
                       .where(Channel.status == "ACTIVE")) or 0
    rev = db.scalar(select(func.coalesce(func.sum(SalesLine.net_revenue), 0)).where(pf, MAPPED)) or 0
    est = db.scalar(select(func.coalesce(func.sum(SalesLine.net_revenue), 0))
                    .where(pf, MAPPED, SalesLine.confidence == "ESTIMATED")) or 0
    return Quality(
        channels_collected=collected, channels_active=active,
        unmapped_count=un_cnt, unmapped_amount=un_amt,
        mapping_rate=((total_lines - un_cnt) / total_lines) if total_lines else 1.0,
        estimated_revenue_share=(est / rev) if rev else 0.0,
    )
