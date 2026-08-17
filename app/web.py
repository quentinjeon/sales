# -*- coding: utf-8 -*-
"""웹 화면 — PRD §9

    uvicorn app.web:app --reload --port 8000
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile as FUpload
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from markupsafe import Markup
from sqlalchemy import func, select

from app.db import UPLOAD_DIR, SessionLocal
from app.models import (
    Channel, ChannelFee, ChannelLogistics, Deal, DealComponent, NameMapping,
    SalesLine, Sku, SkuCost,
    UploadBatch, UploadFile,
)
from app.seed import PLAN_CHANNEL_ID
from app.seed.data import TIERS, UNRESOLVED_ROWS
from app.services import export as ex
from app.services import ingest as ing
from app.services import mapping as mp
from app.services import report as rp
from app.services.calc import (
    CalcError, breakeven_price, compute, cost_for_margin, get_fee_rate, get_sku_cost,
    price_for_margin,
)

BASE = Path(__file__).parent
app = FastAPI(title="온담식품 수익률 관리")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
# 템플릿에 없는 변수를 쓰면 조용히 빈 값으로 렌더된다 — 드롭다운이 통째로 비어도
# 화면은 200으로 뜬다. 이름을 틀리면 즉시 터지도록 바꾼다.
templates.env.undefined = StrictUndefined

TIER_KO = {"NORMAL": "정상가", "EVENT": "일반행사", "SPECIAL": "특가"}
FEE_BASE_KO = {"PRICE": "판매가", "SUPPLY": "공급가", "PURCHASE": "매입가"}
SHIP_KO = {"SELF": "자사발송", "CHANNEL_FULFILL": "채널풀필먼트", "CONSIGNMENT": "위탁매입"}
SETTLE_KO = {"CONFIRM": "구매확정일", "PAYMENT": "결제일", "SHIP": "발송일", "SETTLE_ROUND": "결산차수"}

CHANNEL_FILE_GUIDE = [
    ("한빛홈쇼핑", "결산관리 › <b>거래상세내역</b> 탭 → 엑셀 다운로드"),
    ("스위프트", "정산 › 부가세신고내역 › <b>상세 다운로드</b> (중개 / 풀필먼트 각각)"),
    ("몰이십일", "정산 › <b>정산 상세내역</b> 다운로드"),
    ("굿마켓 · 비드나우", "통합 어드민 › <b>주문/정산 상세</b> (계정별 각각)"),
    ("페이샵", "<b>건별 정산 내역 보기</b> → 다음 확장 대상"),
]


# ── 템플릿 필터 ─────────────────────────────────────────────────────────

def _comma(v):
    if v is None:
        return "—"
    return f"{v:,.0f}"


def _pct(v, digits):
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%"


templates.env.filters["comma"] = _comma
templates.env.filters["pct0"] = lambda v: _pct(v, 0)
templates.env.filters["pct1"] = lambda v: _pct(v, 1)
templates.env.filters["pct2"] = lambda v: _pct(v, 2)


def _mbar(margin, level):
    if margin is None:
        return Markup('<span class="psub">—</span>')
    color = {"neg": "var(--neg)", "warn": "var(--warn)", "pos": "var(--pos)"}.get(level, "var(--text-3)")
    width = min(abs(margin) / 0.40, 1.0) * 100
    side = "right:50%" if margin < 0 else "left:0"
    return Markup(
        f'<div class="mbar"><div class="track">'
        f'<div class="fill" style="{side};width:{width * 0.5 if margin < 0 else width:.0f}%;background:{color}"></div>'
        f'</div><span class="val" style="color:{color}">{margin * 100:.2f}%</span></div>')


def _hclass(v):
    if v is None:
        return "na"
    return "h1" if v < 0 else "h2" if v < 0.05 else "h3" if v < 0.15 else "h4" if v < 0.25 else "h5"


def _mcls(v):
    if v is None:
        return ""
    return "mneg" if v < 0 else ("mwarn" if v < 0.05 else "mpos")


def _delta(cur, prev):
    if not prev:
        return Markup('<span class="psub">전기 데이터 없음</span>')
    d = (cur - prev) / abs(prev)
    cls, arrow = ("up", "▲") if d >= 0 else ("down", "▼")
    return Markup(f'<b class="{cls}">{arrow} {abs(d) * 100:.1f}%</b> 전기 {prev:,.0f}')


def _delta_pp(cur, prev):
    if cur is None or prev is None:
        return Markup('<span class="psub">전기 데이터 없음</span>')
    d = (cur - prev) * 100
    cls, arrow = ("up", "▲") if d >= 0 else ("down", "▼")
    return Markup(f'<b class="{cls}">{arrow} {abs(d):.2f}%p</b> 전기 {prev * 100:.2f}%')


def ctx(request: Request, nav: str, db, **kw):
    unmapped = db.scalar(select(func.count()).select_from(SalesLine)
                         .where(SalesLine.map_status == "UNMAPPED")) or 0
    # 데모 배너는 데모 배치가 실제로 있을 때만 — 실데이터로 바꾼 뒤에도 뜨면 안 된다
    demo = bool(db.scalar(select(func.count()).select_from(UploadBatch)
                          .where(UploadBatch.uploaded_by == "demo")))
    base = dict(request=request, nav=nav, unmapped_badge=unmapped, demo_notice=demo,
                tier_ko=lambda t: TIER_KO.get(t, t),
                fee_base_ko=lambda t: FEE_BASE_KO.get(t, t),
                ship_ko=lambda t: SHIP_KO.get(t, t),
                settle_ko=lambda t: SETTLE_KO.get(t, t),
                mbar=_mbar, hclass=_hclass, mcls=_mcls, delta=_delta, delta_pp=_delta_pp)
    base.update(kw)
    return base


def ref_date(period: str, ptype: str) -> str:
    """기간 키 → 그 기간을 대표하는 날짜 (매입가·요율 시점 조회용).

    주차 키는 'YYYY-Www' 라서 앞 7글자를 잘라 쓰면 '2026-W3-15' 같은 가짜 날짜가 된다.
    날짜를 문자열로 비교하기 때문에 예외 없이 통과하면서 엉뚱한 이력 행이 잡힌다.
    """
    if ptype == "WEEK" and len(period) == 8 and period[5] == "W":
        y, w = int(period[:4]), int(period[6:])
        return (date.fromisocalendar(y, w, 3)).isoformat()      # 그 주의 수요일
    if len(period) == 7 and period[4] == "-":
        return f"{period}-15"
    return date.today().isoformat()


def _periods(db, ptype):
    col = SalesLine.period_month if ptype == "MONTH" else SalesLine.period_week
    return list(db.scalars(select(col).where(SalesLine.map_status == "MAPPED")
                           .group_by(col).order_by(col.desc())).all())


def _default_period(db, ptype, periods):
    """미완결 기간에 착지하지 않는다.

    주차가 월 경계를 걸치면 마지막 달에 며칠치만 남는다(PRD §1.5).
    그 기간을 기본값으로 열면 매출이 급감한 것처럼 보이므로,
    직전 기간의 30% 미만이면 한 칸 뒤로 물러선다.
    """
    if len(periods) < 2:
        return periods[0] if periods else "—"
    col = SalesLine.period_month if ptype == "MONTH" else SalesLine.period_week
    cnt = {p: (db.scalar(select(func.count()).select_from(SalesLine)
                         .where(col == p, SalesLine.map_status == "MAPPED")) or 0)
           for p in periods[:2]}
    latest, prev = periods[0], periods[1]
    return prev if cnt[latest] < cnt[prev] * 0.3 else latest


# ── 화면 ────────────────────────────────────────────────────────────────

@app.get("/")
def dashboard(request: Request, period: str | None = None, type: str = "MONTH"):
    with SessionLocal() as db:
        ptype = "WEEK" if type == "WEEK" else "MONTH"
        periods = _periods(db, ptype) or ["—"]
        period = period if period in periods else _default_period(db, ptype, periods)

        t = rp.totals(db, period, ptype)
        prev = rp.totals(db, rp.prev_period(period, ptype), ptype)
        losses = rp.loss_deals(db, period, ptype)
        month = period if ptype == "MONTH" else period
        trend = rp.weekly_trend(db, month) if ptype == "MONTH" else []
        tiers = rp.by_tier(db, period, ptype)

        note = ""
        sp = next((r for r in tiers if r.name == "SPECIAL"), None)
        ev = next((r for r in tiers if r.name == "EVENT"), None)
        if sp and ev and t.revenue:
            note = (f"매출의 <b>{sp.revenue / t.revenue * 100:.1f}%가 특가</b>이고 특가 평균 마진율은 "
                    f"<b>{sp.margin * 100:.2f}%</b>입니다. 일반행사({ev.margin * 100:.2f}%)와 "
                    f"<b>{(ev.margin - sp.margin) * 100:.0f}%p</b> 차이입니다.")

        share = {}
        if t.revenue:
            share = {"cogs": round(t.cogs / t.revenue * 100, 1),
                     "logi": round(t.logistics / t.revenue * 100, 1),
                     "fee": round(t.fee / t.revenue * 100, 1),
                     "profit": round(t.profit / t.revenue * 100, 1)}

        weeks = _periods(db, "WEEK")
        return templates.TemplateResponse(request, "dashboard.html", ctx(
            request, "dashboard", db,
            period=period, ptype=ptype, periods=periods, month=month,
            default_week=weeks[0] if weeks else "",
            period_label=f"{period} · {'월별' if ptype == 'MONTH' else '주별'}",
            t=t, prev=prev, channels=rp.by_channel(db, period, ptype),
            products=rp.by_product(db, period, ptype, limit=12),
            tiers=tiers, tier_note=Markup(note), trend=trend,
            trend_max=max([w.revenue for w in trend], default=1),
            trend_pmax=max([w.profit for w in trend], default=1),
            losses=losses, loss_sum=sum(r.profit for r in losses),
            loss_orders=sum(r.orders for r in losses),
            share=share, q=rp.quality(db, period, ptype),
            waiting_count=db.scalar(select(func.count()).select_from(Channel)
                                    .where(Channel.status == "WAITING")) or 0,
        ))


@app.get("/deals")
def deals(request: Request, period: str | None = None, type: str = "MONTH",
          channel: str | None = None, tier: str | None = None,
          status: str | None = None, focus: str | None = None):
    with SessionLocal() as db:
        ptype = "WEEK" if type == "WEEK" else "MONTH"
        periods = _periods(db, ptype) or ["—"]
        period = period if period in periods else _default_period(db, ptype, periods)

        rows = rp.by_deal(db, period, ptype, channel_id=channel, tier=tier)
        if status == "loss":
            rows = [r for r in rows if r.level == "neg"]
        elif status == "warn":
            rows = [r for r in rows if r.level in ("neg", "warn")]

        hm_channels, hm_rows = rp.heatmap(db, period, ptype)

        focus_ctx = None
        target = next((r for r in rows if r.key == focus), rows[0] if rows else None)
        if target:
            deal = db.get(Deal, target.extra["deal_id"])
            ch = target.extra["channel_id"]
            on = ref_date(period, ptype)
            try:
                r = compute(db, channel_id=ch, deal=deal, order_date=on,
                            qty=1, gross_amount=deal.price)
                rate = r.fee_rate_used or 0
                unit_cogs = r.cogs
                logi = r.logistics_cost
                bep = []
                for c in db.scalars(select(Channel).where(Channel.status == "ACTIVE")
                                    .order_by(Channel.sort_order)).all():
                    try:
                        cr, _ = get_fee_rate(db, c.id, on)
                    except CalcError:
                        continue
                    p = breakeven_price(unit_cogs, logi, cr)
                    bep.append({"name": c.name, "rate": cr, "price": p, "gap": p - deal.price})
                opts = []
                higher = db.scalar(select(Deal).where(
                    Deal.primary_sku_id == deal.primary_sku_id,
                    Deal.tier == ("EVENT" if deal.tier == "SPECIAL" else "NORMAL"),
                    Deal.channel_id.is_(None)))
                if higher:
                    hr = compute(db, channel_id=ch, deal=higher, order_date=on,
                                 qty=1, gross_amount=higher.price)
                    opts.append({"title": "상위 티어 가격 적용",
                                 "detail": f"{deal.price:,} → {higher.price:,}원. "
                                           f"마진율 {r.margin_rate * 100:.1f}% → {hr.margin_rate * 100:.1f}%"})
                packs = sum(c.qty for c in deal.components)
                opts.append({"title": f"{packs + 1}개 세트로 전환",
                             "detail": f"물류비 {logi:,}원을 {packs + 1}개에 분산. 단품일수록 물류비를 못 견딥니다"})
                try:
                    need = cost_for_margin(deal.price, logi, rate, 0.08)
                    per = round(need / packs)
                    opts.append({"title": "매입가 재협상",
                                 "detail": f"구성 원가 {unit_cogs:,} → {need:,}원(개당 {per:,}원)이면 마진율 8% 달성"})
                except CalcError:
                    pass
                try:
                    tp = price_for_margin(unit_cogs, logi, rate, 0.08)
                    opts.append({"title": "마진율 8% 목표가",
                                 "detail": f"{tp:,}원 이상이어야 합니다 (현재 {deal.price:,}원)"})
                except CalcError:
                    pass
                focus_ctx = {"row": target, "fee": r.channel_fee, "fee_rate": rate,
                             "cogs": unit_cogs, "logi": logi,
                             "unit_profit": r.contribution_profit, "bep": bep, "options": opts}
            except CalcError:
                focus_ctx = None

        tot = rp.Totals(revenue=sum(r.revenue for r in rows), fee=sum(r.fee for r in rows),
                        cogs=sum(r.cogs for r in rows), logistics=sum(r.logistics for r in rows),
                        profit=sum(r.profit for r in rows), qty=sum(r.qty for r in rows),
                        orders=sum(r.orders for r in rows))

        return templates.TemplateResponse(request, "deals.html", ctx(
            request, "deals", db, period=period, ptype=ptype, periods=periods,
            channel=channel, tier=tier, status=status, deals=rows, tot=tot,
            hm_channels=hm_channels, hm_rows=hm_rows,
            gap=rp.biggest_gap(db, period, ptype), focus=focus_ctx,
            all_channels=db.scalars(select(Channel).where(Channel.status == "ACTIVE")
                                    .order_by(Channel.sort_order)).all(),
        ))


@app.get("/products")
def products(request: Request):
    """제품 DB — 마스터는 DB에서 읽는다 (업로드로 들어오므로 시드 상수에 기대지 않는다)."""
    with SessionLocal() as db:
        periods = _periods(db, "MONTH")
        period = _default_period(db, "MONTH", periods) if periods else "—"
        on = ref_date(period, "MONTH")
        actual = {r.key: r for r in rp.by_product(db, period)} if periods else {}

        rows = []
        for sku in db.scalars(select(Sku).order_by(Sku.id)).all():
            deals = db.scalars(
                select(Deal).where(Deal.primary_sku_id == sku.id,
                                   Deal.channel_id.is_(None))).all()
            by_tier = {d.tier: d for d in deals}
            if not by_tier:
                continue
            pack = max((sum(c.qty for c in d.components) for d in deals), default=1)
            try:
                cost = get_sku_cost(db, sku.id, on)
            except CalcError:
                cost = None

            plan, prices = [], []
            for tier, _ in TIERS:
                d = by_tier.get(tier)
                prices.append(d.price if d else None)
                if d is None:
                    plan.append(None)
                    continue
                try:
                    r = compute(db, channel_id=PLAN_CHANNEL_ID, deal=d, order_date=on,
                                qty=1, gross_amount=d.price)
                    plan.append(r.margin_rate)
                except CalcError:
                    plan.append(None)

            a = actual.get(sku.id)
            rows.append({"sku_id": sku.id, "name": sku.name, "spec": sku.spec or "",
                         "cost": cost, "pack": pack, "prices": prices, "plan": plan,
                         "qty": a.qty if a else 0, "profit": a.profit if a else None,
                         "margin": a.margin if a else None})
        rows.sort(key=lambda r: (r["plan"][2] if r["plan"][2] is not None else 9))
        return templates.TemplateResponse(request, "products.html", ctx(
            request, "products", db, rows=rows, period=period, unresolved=UNRESOLVED_ROWS))


@app.get("/channels")
def channels(request: Request):
    """채널 관리 — 매출은 실제 적재된 원장에서 집계한다."""
    with SessionLocal() as db:
        palette = ["#3b5bdb", "#4c6ef5", "#5c7cfa", "#748ffc", "#91a7ff", "#a3b8ff"]

        periods = _periods(db, "MONTH")
        period = _default_period(db, "MONTH", periods) if periods else "—"
        on = ref_date(period, "MONTH")
        rev_by_ch = {r.key: r.revenue for r in rp.by_channel(db, period)} if periods else {}
        total_rev = sum(rev_by_ch.values())

        def enrich(c):
            try:
                fee, _ = get_fee_rate(db, c.id, on)
            except CalcError:
                fee = None
            logi = db.scalar(
                select(ChannelLogistics).where(ChannelLogistics.channel_id == c.id)
                .order_by(ChannelLogistics.effective_from.desc()))
            rev = rev_by_ch.get(c.id, 0)
            return {"id": c.id, "name": c.name, "group_name": c.group_name,
                    "fee_base": c.fee_base, "ship_owner": c.ship_owner,
                    "settle_date_src": c.settle_date_src, "note": c.note or "",
                    "fee_rate": fee, "logi_amount": logi.flat_amount if logi else None,
                    "logi_est": bool(logi.is_estimate) if logi else False,
                    "revenue": rev,
                    "share": round(rev / total_rev * 100, 1) if total_rev else 0.0}

        active = [enrich(c) for c in db.scalars(
            select(Channel).where(Channel.status == "ACTIVE").order_by(Channel.sort_order)).all()]
        waiting = [enrich(c) for c in db.scalars(
            select(Channel).where(Channel.status == "WAITING").order_by(Channel.sort_order)).all()]

        cov = [{"name": c["name"], "pct": c["share"], "color": palette[i % len(palette)], "muted": False}
               for i, c in enumerate(active)]
        wsum = sum(c["revenue"] for c in waiting)
        if waiting:
            cov.append({"name": f"대기 {len(waiting)}개",
                        "pct": round(wsum / total_rev * 100, 1) if total_rev else 0.0,
                        "color": "var(--surface-2)", "muted": True})
        fees = [c["fee_rate"] for c in active + waiting if c["fee_rate"]]

        return templates.TemplateResponse(request, "channels.html", ctx(
            request, "channels", db, active=active, waiting=waiting, coverage=cov,
            cover_pct=round(sum(c["share"] for c in active), 1), waiting_sum=wsum,
            period=period,
            fee_min=round(min(fees) * 100, 1) if fees else None,
            fee_max=round(max(fees) * 100, 1) if fees else None))


@app.get("/mapping")
def mapping_page(request: Request, period: str | None = None):
    with SessionLocal() as db:
        periods = _periods(db, "MONTH") or ["—"]
        period = period if period in periods else _default_period(db, "MONTH", periods)
        q = rp.quality(db, period)

        rows = db.execute(
            select(SalesLine.channel_id, SalesLine.raw_product_name, SalesLine.raw_option_name,
                   func.count(), func.sum(SalesLine.gross_amount), func.min(SalesLine.order_date))
            .where(SalesLine.map_status == "UNMAPPED", SalesLine.period_month == period)
            .group_by(SalesLine.channel_id, SalesLine.raw_product_name, SalesLine.raw_option_name)
            .order_by(func.sum(SalesLine.gross_amount).desc())
        ).all()

        names = {c.id: c.name for c in db.scalars(select(Channel)).all()}
        groups = []
        for ch, prod, opt, cnt, amt, on in rows:
            sug = mp.suggest(db, channel_id=ch, product=prod, option=opt,
                             unit_price=round(amt / cnt) if cnt else None, on=on)
            groups.append({
                "channel_id": ch, "channel_name": names.get(ch, ch),
                "product": prod, "option": opt, "count": cnt, "amount": amt,
                "special": mp.looks_special(prod, opt),
                "suggestions": [{"deal_id": s.deal.id, "label": s.deal.label,
                                 "tier": s.deal.tier, "price": s.deal.price,
                                 "score": s.score} for s in sug if s.score > 0.3],
            })

        # 직접 고르기용 전체 딜 목록 · 조합용 SKU 목록
        all_deals = [{"id": d.id, "label": d.label, "tier": d.tier, "price": d.price}
                     for d in db.scalars(
                         select(Deal).where(Deal.is_active == 1)
                         .order_by(Deal.primary_sku_id, Deal.price.desc())).all()]
        all_skus = [{"id": k.id, "name": k.name}
                    for k in db.scalars(select(Sku).order_by(Sku.name)).all()]

        per_ch = []
        for cid, cname in names.items():
            rules = db.scalar(select(func.count()).select_from(NameMapping)
                              .where(NameMapping.channel_id == cid)) or 0
            if not rules:
                continue
            tot = db.scalar(select(func.count()).select_from(SalesLine)
                            .where(SalesLine.channel_id == cid, SalesLine.period_month == period)) or 0
            un = db.scalar(select(func.count()).select_from(SalesLine)
                           .where(SalesLine.channel_id == cid, SalesLine.period_month == period,
                                  SalesLine.map_status == "UNMAPPED")) or 0
            per_ch.append({"name": cname, "rules": rules, "unmapped": un,
                           "rate": ((tot - un) / tot) if tot else 1.0})

        return templates.TemplateResponse(request, "mapping.html", ctx(
            request, "mapping", db, period=period, q=q, groups=groups, by_channel=per_ch,
            all_deals=all_deals, all_skus=all_skus,
            rule_count=db.scalar(select(func.count()).select_from(NameMapping)) or 0))


@app.post("/mapping/accept")
def mapping_accept(channel_id: str = Form(...), product: str = Form(...),
                   option: str = Form(""), deal_id: str = Form(...), period: str = Form(...)):
    with SessionLocal() as db:
        mp.register(db, channel_id=channel_id, product=product, option=option,
                    deal_id=deal_id, match_type="SUGGESTED_ACCEPTED", actor="web")
        lines = db.scalars(select(SalesLine).where(
            SalesLine.channel_id == channel_id,
            SalesLine.raw_product_name == product,
            SalesLine.raw_option_name == option,
            SalesLine.map_status == "UNMAPPED")).all()
        mp.map_lines(db, lines)
        from app.services.calc import apply_to_line, clear_calc
        for ln in lines:
            if ln.map_status == "MAPPED":
                try:
                    apply_to_line(db, ln, db.get(Deal, ln.deal_id))
                except CalcError as e:
                    ln.map_status, ln.map_note = "UNMAPPED", str(e)
                    clear_calc(ln)
        db.commit()
    return RedirectResponse(f"/mapping?period={period}", status_code=303)


@app.post("/mapping/compose")
def mapping_compose(
    channel_id: str = Form(...), product: str = Form(...), option: str = Form(""),
    period: str = Form(...), label: str = Form(...), price: int = Form(...),
    tier: str = Form("EVENT"),
    sku: list[str] = Form([]), qty: list[str] = Form([]), gift: list[str] = Form([]),
):
    """여러 SKU를 조합해 새 딜을 만들고 그 이름에 연결한다 (PRD §6 · 복합세트·증정품).

    기존 딜에 붙이면 빠진 구성의 원가가 통째로 사라진다.
    구성이 다르면 반드시 새 딜이어야 한다.
    """
    parts = [(s.strip(), int(q or 1), g == "1")
             for s, q, g in zip(sku, qty + [""] * len(sku), gift + ["0"] * len(sku))
             if s and s.strip()]
    if not parts:
        return RedirectResponse(
            f"/mapping?period={period}&error=" + quote("구성 제품을 1개 이상 골라주세요"),
            status_code=303)

    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(Deal)
                      .where(Deal.id.like(f"SET-{channel_id}-%"))) or 0
        deal_id = f"SET-{channel_id}-{n + 1:03d}"
        db.add(Deal(id=deal_id, channel_id=channel_id, primary_sku_id=parts[0][0],
                    label=label.strip() or product[:80], tier=tier, price=price,
                    effective_from="2026-01-01"))
        for sku_id, q, is_gift in parts:
            db.add(DealComponent(deal_id=deal_id, sku_id=sku_id, qty=q,
                                 is_gift=int(is_gift)))
        db.flush()

        mp.register(db, channel_id=channel_id, product=product, option=option,
                    deal_id=deal_id, match_type="COMPOSED", actor="web")
        lines = db.scalars(select(SalesLine).where(
            SalesLine.channel_id == channel_id,
            SalesLine.raw_product_name == product,
            SalesLine.raw_option_name == option,
            SalesLine.map_status == "UNMAPPED")).all()
        mp.map_lines(db, lines)
        from app.services.calc import apply_to_line, clear_calc
        for ln in lines:
            if ln.map_status == "MAPPED":
                try:
                    apply_to_line(db, ln, db.get(Deal, ln.deal_id))
                except CalcError as e:
                    ln.map_status, ln.map_note = "UNMAPPED", str(e)
                    clear_calc(ln)
        db.commit()
    return RedirectResponse(f"/mapping?period={period}", status_code=303)


@app.get("/upload")
def upload_page(request: Request, ok: str = "", error: str = "",
               period: str | None = None):
    with SessionLocal() as db:
        periods = _periods(db, "MONTH") or ["—"]
        period = period if period in periods else _default_period(db, "MONTH", periods)
        # 단계별 완료 여부 — 상품 → 채널 → 매출 순서로 올려야 한다
        steps = {
            "skus": db.scalar(select(func.count()).select_from(Sku)) or 0,
            "deals": db.scalar(select(func.count()).select_from(Deal)) or 0,
            "channels": db.scalar(select(func.count()).select_from(Channel)) or 0,
            "active": db.scalar(select(func.count()).select_from(Channel)
                                .where(Channel.status == "ACTIVE")) or 0,
            "lines": db.scalar(select(func.count()).select_from(SalesLine)) or 0,
        }
        t = rp.totals(db, period)
        q = rp.quality(db, period)
        names = {c.id: c.name for c in db.scalars(select(Channel)).all()}

        files = []
        for f in db.scalars(select(UploadFile)).all():
            tot = db.scalar(select(func.count()).select_from(SalesLine)
                            .where(SalesLine.file_id == f.id)) or 0
            un = db.scalar(select(func.count()).select_from(SalesLine)
                           .where(SalesLine.file_id == f.id,
                                  SalesLine.map_status == "UNMAPPED")) or 0
            files.append({"channel_name": names.get(f.channel_id, f.channel_id),
                          "filename": f.filename, "row_count": f.row_count,
                          "gross_sum": f.gross_sum, "unmapped": un,
                          "rate": ((tot - un) / tot) if tot else 1.0})
        files.sort(key=lambda x: -(x["gross_sum"] or 0))

        guide = [{"name": n, "path": Markup(p), "done": i < 4}
                 for i, (n, p) in enumerate(CHANNEL_FILE_GUIDE)]
        return templates.TemplateResponse(request, "upload.html", ctx(
            request, "upload", db, period=period, t=t, q=q, files=files, guide=guide,
            ok=ok, error=error, steps=steps,
            waiting_count=db.scalar(select(func.count()).select_from(Channel)
                                    .where(Channel.status == "WAITING")) or 0))


async def _save_upload(up: FUpload, kind: str) -> Path:
    """올린 파일을 보관함에 저장한다. 원본을 남겨야 나중에 재적재·대사가 가능하다."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{kind}_{up.filename}"
    dest.write_bytes(await up.read())
    return dest


def _back(ok: str = "", error: str = "", period: str = "") -> RedirectResponse:
    q = []
    if ok:
        q.append(f"ok={quote(ok)}")
    if error:
        q.append(f"error={quote(error)}")
    if period:
        q.append(f"period={period}")
    return RedirectResponse("/upload" + ("?" + "&".join(q) if q else ""), status_code=303)


@app.post("/upload/products")
async def upload_products(file: FUpload = File(...)):
    """① 상품정보 — 제품·매입가·구성수량·가격 티어. 처음 한 번만."""
    path = await _save_upload(file, "products")
    with SessionLocal() as db:
        try:
            n = ing.load_products(db, path)
            db.commit()
        except (ing.IngestError, KeyError) as e:
            db.rollback()
            return _back(error=f"상품정보를 읽을 수 없습니다 — {e}")
    if not n["skus"] and not n["deals"]:
        return _back(ok="상품정보: 새로 등록할 제품이 없습니다 (이미 전부 등록됨)")
    return _back(ok=f"상품정보: 제품 {n['skus']}종 · 딜 {n['deals']}개 등록")


@app.post("/upload/channels")
async def upload_channels(file: FUpload = File(...)):
    """② 채널정보 — 수수료율·물류비·배송주체. 처음 한 번만."""
    path = await _save_upload(file, "channels")
    with SessionLocal() as db:
        try:
            n = ing.load_channels(db, path)
            db.commit()
        except (ing.IngestError, KeyError) as e:
            db.rollback()
            return _back(error=f"채널정보를 읽을 수 없습니다 — {e}")
    if not n["channels"]:
        return _back(ok="채널정보: 새로 등록할 채널이 없습니다 (이미 전부 등록됨)")
    return _back(ok=f"채널정보: 채널 {n['channels']}개 등록")


@app.post("/upload/sales")
async def upload_sales(file: FUpload = File(...), period: str = Form(""),
                       replace: str = Form("")):
    """③ 매출 — 매달 올린다. 적재 → 매핑 → 손익 계산까지 한 번에."""
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(Sku)):
            return _back(error="먼저 ① 상품정보를 올려주세요. 제품이 없으면 원가를 알 수 없습니다.")
        if not db.scalar(select(func.count()).select_from(Channel)):
            return _back(error="먼저 ② 채널정보를 올려주세요. 채널이 없으면 수수료를 알 수 없습니다.")

    path = await _save_upload(file, "sales")
    with SessionLocal() as db:
        try:
            r = ing.load_sales(db, path, period=period or None,
                               uploaded_by="web", replace=bool(replace))
            db.commit()
        except ing.IngestError as e:
            db.rollback()
            return _back(error=str(e))

    msg = []
    if r.replaced_lines:
        msg.append(f"기존 {r.replaced_lines:,}건 삭제(교체)")
    msg.append(f"{r.period} 주문 {r.lines:,}건 적재 · 매핑 {r.mapped:,} "
               f"· 미매핑 {r.unmapped} · 계산 {r.calculated:,}")
    skipped = []
    if r.dup_existing:
        skipped.append(f"이미 적재된 주문 {r.dup_existing:,}건 제외")
    if r.dup_in_file:
        skipped.append(f"파일 내 중복 {r.dup_in_file:,}건 제외")
    skipped += r.skipped_sheets
    if skipped:
        msg.append(" · ".join(skipped))
    return _back(ok=" · ".join(msg), period=r.period)


@app.get("/export")
def export_excel(period: str | None = None, type: str = "MONTH"):
    """결과 엑셀 6시트 내려받기 (PRD §8)."""
    with SessionLocal() as db:
        ptype = "WEEK" if type == "WEEK" else "MONTH"
        periods = _periods(db, ptype)
        period = period if period in periods else _default_period(db, ptype, periods)
        if period == "—":
            return RedirectResponse("/upload?error=" + quote("내보낼 데이터가 없습니다"),
                                    status_code=303)
        data = ex.to_bytes(db, period, ptype)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(f'결과_{period}.xlsx')}"})


@app.get("/healthz")
def healthz():
    with SessionLocal() as db:
        return {"ok": True,
                "skus": db.scalar(select(func.count()).select_from(Sku)),
                "deals": db.scalar(select(func.count()).select_from(Deal)),
                "lines": db.scalar(select(func.count()).select_from(SalesLine))}
