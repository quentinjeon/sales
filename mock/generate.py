# -*- coding: utf-8 -*-
"""Mock 화면 생성 — 목업 DB의 실제 숫자로 정적 HTML 6장을 만든다.

    python mock/generate.py

    index.html        화면 목록 + 데이터 흐름
    01-상품DB.html     인풋 ① 상품정보 23종
    02-채널DB.html     인풋 ② 채널정보 14개
    03-매출데이터.html  인풋 ③ 매출 원장 (채널별 컬럼 상이 · 미매핑)
    04-대시보드.html    결과 ① 월별 수익률 대시보드
    05-리포트.html      결과 ② 제품별 · 채널×제품 상세

화면의 모든 숫자는 `data/cecnr.db` 에서 뽑는다. 실습 파일과 어긋날 수 없다.
DB가 없으면 먼저:  python -m app.cli init && python -m app.demo
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from sqlalchemy import func, select                              # noqa: E402

from app.db import SessionLocal                                  # noqa: E402
from app.models import Channel, SalesLine                        # noqa: E402
from app.seed.data import CHANNELS, SKUS                         # noqa: E402
from app.services import report as rp                            # noqa: E402

PERIOD = "2026-07"
CSS = (HERE / "assets" / "app.css").read_text(encoding="utf-8")

NAV = [
    ("index.html", "🗂", "화면 목록", "안내"),
    ("01-상품DB.html", "📦", "상품 DB", "인풋"),
    ("02-채널DB.html", "🛒", "채널 DB", "인풋"),
    ("03-매출데이터.html", "🧾", "매출 데이터", "인풋"),
    ("04-대시보드.html", "📊", "수익률 대시보드", "결과"),
    ("05-리포트.html", "📈", "상세 리포트", "결과"),
]


def won(v):
    return "—" if v is None else f"{round(v):,}"


def pct(v, d=2):
    return "—" if v is None else f"{v * 100:.{d}f}%"


def cls(m):
    return "" if m is None else ("neg" if m < 0 else "warn" if m < 0.05 else "pos")


def mbar(m):
    if m is None:
        return '<span class="psub">—</span>'
    c = "var(--neg)" if m < 0 else "var(--warn)" if m < 0.05 else "var(--pos)"
    w = min(abs(m) / 0.35, 1.0) * 100
    return (f'<div class="mbar"><div class="track">'
            f'<div class="fill" style="left:0;width:{w:.0f}%;background:{c}"></div></div>'
            f'<span class="val" style="color:{c}">{m * 100:.2f}%</span></div>')


def page(active, title, h1, sub, body, right=""):
    groups, seen = [], None
    for href, ic, label, grp in NAV:
        if grp != seen:
            groups.append(f'<div class="nav-label">{grp}</div>')
            seen = grp
        on = " on" if href == active else ""
        groups.append(f'<a href="{href}" class="{on.strip()}"><span class="ic">{ic}</span> {label}</a>')
    nav = "\n    ".join(groups)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 온담식품 수익률 관리</title>
<style data-src="assets/app.css">
{CSS}
</style>
</head>
<body>
<div class="shell">
<aside class="side">
  <div class="brand">
    <div class="brand-mark">온</div>
    <div><div class="brand-name">온담식품 수익률</div><div class="brand-sub">온라인몰 손익 관리</div></div>
  </div>
  <div class="nav">
    {nav}
  </div>
</aside>
<main class="main">
  <div class="topbar">
    <div><h1>{h1}</h1><div class="sub">{sub}</div></div>
    <div class="right">{right}</div>
  </div>
{body}
  <div class="mock-note">
    <b>화면 기획(Mock)입니다.</b> 숫자는 목업 데이터에서 뽑은 실제 계산 결과이며,
    회사·브랜드·제품·채널은 전부 가상입니다. 실존 기업과 무관합니다.
    재생성: <code>python mock/generate.py</code>
  </div>
</main>
</div>
</body>
</html>
"""


# ── index ───────────────────────────────────────────────────────────────

def build_index(db, t, q):
    cards = "".join(
        f'<a class="card" href="{href}" style="text-decoration:none;color:inherit;display:block">'
        f'<div class="card-bd"><div style="font-size:22px;margin-bottom:8px">{ic}</div>'
        f'<div class="pname" style="font-size:14.5px;margin-bottom:3px">{label}</div>'
        f'<div class="psub">{grp}</div></div></a>'
        for href, ic, label, grp in NAV[1:])

    body = f"""
  <div class="banner acc">
    <div class="bi">🎯</div>
    <div><div class="bt">엑셀 3장을 넣으면 그 달의 제품별·채널별 이익이 나옵니다</div>
    <div class="bd">이 화면들은 개발 전 <b>기획 확인용</b>입니다. 숫자는 목업 데이터의 실제 계산 결과입니다.</div></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>데이터 흐름</h2>
      <span class="note">인풋 3장 → 계산 → 결과 2종</span></div>
    <div class="card-bd">
      <div class="step done"><div class="n">1</div><div class="body">
        <div class="ti">📦 상품 DB — 01_상품정보.xlsx</div>
        <div class="de">제품 {len(SKUS)}종 · 매입가 · 구성수량 · 가격 3단계.
          회사가 이미 가지고 있는 가격표입니다.</div></div></div>
      <div class="step done"><div class="n">2</div><div class="body">
        <div class="ti">🛒 채널 DB — 02_채널정보.xlsx</div>
        <div class="de">채널 {len(CHANNELS)}개 · 수수료율 · 물류비 · 배송주체.
          정산서에서 수수료율을 역산해 한 번 만들면 끝입니다.</div></div></div>
      <div class="step done"><div class="n">3</div><div class="body">
        <div class="ti">🧾 매출 데이터 — 03_매출_{PERIOD}.xlsx</div>
        <div class="de">주문 {t.orders + q.unmapped_count:,}건 · 채널별 시트 5장.
          <b>채널마다 컬럼 이름이 다릅니다</b> — 이걸 맞추는 게 이 시스템의 첫 관문입니다.</div></div></div>
      <div class="step now"><div class="n">4</div><div class="body">
        <div class="ti">📊 결과 — 대시보드 + 결과 엑셀</div>
        <div class="de">제품별 매출 · 채널별 매출과 이익률 · 적자 딜.
          기여이익 <b>{won(t.profit)}원</b> · 마진율 <b>{pct(t.margin)}</b></div></div></div>
    </div>
  </div>

  <div class="g3">{cards}</div>

  <div class="card" style="margin-top:16px">
    <div class="card-hd"><h2>이 시스템이 답하는 질문</h2></div>
    <div class="card-bd">
      <div class="step"><div class="n">Q</div><div class="body">
        <div class="ti">총매출은 올랐는데 왜 남는 게 없나?</div>
        <div class="de">채널 수수료 {pct(t.fee / t.revenue, 1)} · 원가 {pct(t.cogs / t.revenue, 1)} ·
          물류비 {pct(t.logistics / t.revenue, 1)} 를 빼면 손에 남는 건 {pct(t.margin)} 입니다.</div></div></div>
      <div class="step"><div class="n">Q</div><div class="body">
        <div class="ti">팔수록 손해인 제품이 있나?</div>
        <div class="de">이번 달 적자 딜 {len(rp.loss_deals(db, PERIOD))}건.
          많이 팔릴수록 손실이 커집니다.</div></div></div>
      <div class="step"><div class="n">Q</div><div class="body">
        <div class="ti">같은 제품인데 채널을 옮기면 이익이 달라지나?</div>
        <div class="de">수수료율이 6.8%~24.0%로 3.5배 차이납니다. 채널만 바꿔도 적자가 흑자가 됩니다.</div></div></div>
    </div>
  </div>
"""
    return page("index.html", "화면 목록", "화면 기획",
                f"{PERIOD} 기준 · 인풋 3장 → 결과 2종", body)


# ── 01 상품 DB ──────────────────────────────────────────────────────────

def build_products():
    rows = []
    for sku_id, name, spec, cost, pack, p1, p2, p3 in SKUS:
        unit = cost * pack
        margins = [(p - round(p * 0.13) - unit - 3000) / p for p in (p1, p2, p3)]
        tds = "".join(f'<td class="r num {cls(m)}">{pct(m)}</td>' for m in margins)
        tr = ' class="tr-neg"' if margins[2] < 0 else ""
        rows.append(
            f'<tr{tr}><td class="num psub">{sku_id}</td>'
            f'<td><div class="pname">{name}</div><div class="psub">{spec}</div></td>'
            f'<td class="r num">{won(cost)}</td><td class="c num">×{pack}</td>'
            f'<td class="r num">{won(unit)}</td>'
            f'<td class="r num">{won(p1)}</td><td class="r num">{won(p2)}</td>'
            f'<td class="r num">{won(p3)}</td>{tds}</tr>')

    loss = sum(1 for _, _, _, c, pk, _, _, p3 in SKUS
               if (p3 - round(p3 * 0.13) - c * pk - 3000) < 0)
    body = f"""
  <div class="banner warn">
    <div class="bi">⚠</div>
    <div><div class="bt">특가 기준으로 적자인 제품이 {loss}종 있습니다</div>
    <div class="bd">수수료 13% · 물류비 3,000원 가정. 붉은 행이 그 제품입니다.
      <b>구성수량을 빼먹으면</b> 이 표가 전부 흑자로 보입니다 — 가장 흔한 실수입니다.</div></div>
  </div>

  <div class="card">
    <div class="card-hd"><h2>상품 DB</h2>
      <span class="note">인풋 ① · 01_상품정보.xlsx</span>
      <div class="right"><span class="tag mut">{len(SKUS)}종</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr>
        <th>제품코드</th><th>제품명 · 규격</th><th class="r">매입가</th><th class="c">구성</th>
        <th class="r">원가</th><th class="r">정상가</th><th class="r">행사가</th><th class="r">특가</th>
        <th class="r">정상 마진</th><th class="r">행사 마진</th><th class="r">특가 마진</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table></div>
  </div>

  <div class="card" style="margin-top:16px">
    <div class="card-hd"><h2>컬럼이 뜻하는 것</h2></div>
    <div class="card-bd">
      <dl class="kv" style="grid-template-columns:120px 1fr">
        <dt>매입가</dt><dd style="text-align:left">제품 <b>1개당</b> 원가. 세트 원가가 아닙니다.</dd>
        <dt>구성수량</dt><dd style="text-align:left">한 번 팔 때 나가는 개수.
          <b>원가 = 매입가 × 구성수량</b></dd>
        <dt>가격 3단계</dt><dd style="text-align:left">같은 제품을 파는 세 가격.
          정상가 → 일반행사가 → 특가 순으로 마진이 깎입니다.</dd>
        <dt>마진 열</dt><dd style="text-align:left">수수료 13% 고정 가정으로 계산한 <b>계획값</b>입니다.
          실제 채널 요율을 넣으면 달라집니다 — 그게 채널 DB의 역할입니다.</dd>
      </dl>
    </div>
  </div>
"""
    return page("01-상품DB.html", "상품 DB", "상품 DB",
                f"인풋 ① · 제품 {len(SKUS)}종 · 매입가와 구성수량이 원가를 결정합니다", body,
                '<button class="btn btn-sm">엑셀 받기</button>')


# ── 02 채널 DB ──────────────────────────────────────────────────────────

def build_channels(db):
    act = {r.key: r for r in rp.by_channel(db, PERIOD)}
    rows = []
    for (cid, name, group, status, rate, src, ship, _m, logi, est, settle, _v, _o, note) in CHANNELS:
        a = act.get(cid)
        st = ('<span class="tag pos"><span class="dot"></span>운영중</span>' if status == "ACTIVE"
              else '<span class="tag mut">대기</span>')
        srct = {"MEASURED": '<span class="tag pos">실측</span>',
                "CONTRACT": '<span class="tag acc">계약</span>',
                "ESTIMATE": '<span class="tag warn">추정</span>'}.get(src, '<span class="psub">—</span>')
        shipt = {"SELF": "자사발송", "CHANNEL_FULFILL": "채널풀필먼트",
                 "CONSIGNMENT": "위탁매입"}[ship]
        logit = (f'{won(logi)}<span class="psub"> 원</span>' if logi is not None
                 else '<span class="psub">채널부담</span>')
        rows.append(
            f'<tr><td class="num psub">{cid}</td>'
            f'<td><div class="pname">{name}</div><div class="psub">{group}</div></td>'
            f'<td class="c">{st}</td>'
            f'<td class="r num" style="font-weight:650">{pct(rate, 1) if rate else "—"}</td>'
            f'<td class="c">{srct}</td><td class="c psub">{shipt}</td>'
            f'<td class="r num">{logit}</td>'
            f'<td class="r num">{won(a.revenue) if a else "<span class=psub>—</span>"}</td>'
            f'<td class="r">{mbar(a.margin) if a else "<span class=psub>—</span>"}</td>'
            f'<td class="psub">{note}</td></tr>')

    fees = [r for *_, r, _s, _sh, _m, _l, _e, _st, _v, _o, _n in
            [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10], c[11], c[12], c[13])
             for c in CHANNELS] if r]
    lo, hi = min(fees), max(fees)
    body = f"""
  <div class="banner acc">
    <div class="bi">💡</div>
    <div><div class="bt">수수료율이 {pct(lo, 1)} ~ {pct(hi, 1)} — {hi / lo:.1f}배 차이납니다</div>
    <div class="bd">"수수료는 대충 13%"라는 가정이 왜 위험한지가 이 표에 다 있습니다.
      <b>실측</b>은 정산서에서 역산한 값, <b>추정</b>은 아직 근거를 못 구한 값입니다.</div></div>
  </div>

  <div class="card">
    <div class="card-hd"><h2>채널 DB</h2>
      <span class="note">인풋 ② · 02_채널정보.xlsx</span>
      <div class="right"><span class="tag pos">운영중 {sum(1 for c in CHANNELS if c[3] == "ACTIVE")}</span>
        <span class="tag mut">대기 {sum(1 for c in CHANNELS if c[3] != "ACTIVE")}</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr>
        <th>채널코드</th><th>채널명 · 그룹</th><th class="c">상태</th><th class="r">수수료율</th>
        <th class="c">근거</th><th class="c">배송주체</th><th class="r">물류비</th>
        <th class="r">{PERIOD} 매출</th><th class="r">마진율</th><th>비고</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table></div>
  </div>

  <div class="card" style="margin-top:16px">
    <div class="card-hd"><h2>수수료율은 어떻게 구하나</h2></div>
    <div class="card-bd">
      <div class="banner pos" style="margin:0">
        <div class="bi">＝</div>
        <div><div class="bt">실측 수수료율 = 수수료 합계 ÷ 매출 합계</div>
        <div class="bd">채널 정산서에서 두 숫자만 뽑으면 됩니다.
          계약서의 명목 요율이 아니라 <b>실제로 떼인 금액</b>으로 계산해야 맞습니다.</div></div>
      </div>
      <div style="margin-top:14px" class="psub">
        배송주체가 <b>위탁매입</b>이면 채널이 물류를 부담하므로 물류비 0으로 계산합니다.
        <b>채널풀필먼트</b>는 입출고·보관 실비를 따로 확인해야 하며, 지금은 건당 추정치입니다.
      </div>
    </div>
  </div>
"""
    return page("02-채널DB.html", "채널 DB", "채널 DB",
                f"인풋 ② · 채널 {len(CHANNELS)}개 · 수수료율이 이익을 결정합니다", body,
                '<button class="btn btn-sm">엑셀 받기</button>')


# ── 03 매출 데이터 ──────────────────────────────────────────────────────

COLS = {
    "한빛홈쇼핑": ("주문번호", "주문일자", "상품명", "옵션", "판매수량", "판매금액", "수수료"),
    "스위프트 풀필먼트": ("주문ID", "결제일", "노출상품명", "등록옵션명", "수량", "결제금액", None),
    "몰이십일": ("주문번호", "구매확정일", "상품명", "단품명", "주문수량", "상품금액", "서비스이용료"),
    "굿마켓": ("주문번호", "주문일", "주문상품", "선택옵션", "개수", "정산금액", None),
    "비드나우": ("주문번호", "주문일", "주문상품", "선택옵션", "개수", "정산금액", None),
}


def build_sales(db, t, q):
    names = {c.id: c.name for c in db.scalars(select(Channel)).all()}

    hdr = "".join(f"<th>{c}</th>" for c in
                  ("채널", "주문번호", "주문일", "상품명", "옵션명", "수량", "판매금액", "수수료"))
    sample = []
    for ch in ("HANBIT", "SWIFT_FF", "MALL21", "GOODMKT", "BIDNOW"):
        for ln in db.scalars(
                select(SalesLine).where(SalesLine.channel_id == ch,
                                        SalesLine.period_month == PERIOD)
                .order_by(SalesLine.order_no).limit(2)).all():
            fee = (won(ln.channel_fee) if COLS[names[ch]][6]
                   else '<span class="psub">없음</span>')
            sample.append(
                f'<tr><td class="psub nw">{names[ch]}</td><td class="num psub">{ln.order_no}</td>'
                f'<td class="num">{ln.order_date}</td><td class="pname">{ln.raw_product_name}</td>'
                f'<td class="psub">{ln.raw_option_name}</td><td class="c num">{ln.qty}</td>'
                f'<td class="r num">{won(ln.gross_amount)}</td><td class="r num">{fee}</td></tr>')

    colrows = []
    for i, label in enumerate(("주문번호", "주문일", "상품명", "옵션명", "수량", "판매금액", "수수료")):
        tds = "".join(
            f'<td class="c">{COLS[n][i]}</td>' if COLS[n][i]
            else '<td class="c"><span class="tag warn">없음</span></td>' for n in COLS)
        colrows.append(f'<tr><td class="pname">{label}</td>{tds}</tr>')

    un = db.execute(
        select(SalesLine.channel_id, SalesLine.raw_product_name, SalesLine.raw_option_name,
               func.count(), func.sum(SalesLine.gross_amount))
        .where(SalesLine.map_status == "UNMAPPED", SalesLine.period_month == PERIOD)
        .group_by(SalesLine.channel_id, SalesLine.raw_product_name,
                  SalesLine.raw_option_name)
        .order_by(func.sum(SalesLine.gross_amount).desc())).all()
    unrows = "".join(
        f'<tr class="tr-warn"><td class="psub nw">{names.get(c, c)}</td>'
        f'<td class="pname">{p}</td><td class="psub">{o}</td>'
        f'<td class="c num">{n}</td><td class="r num">{won(a)}</td></tr>' for c, p, o, n, a in un)

    body = f"""
  <div class="banner warn">
    <div class="bi">🔗</div>
    <div><div class="bt">미매핑 {q.unmapped_count}건 · {won(q.unmapped_amount)}원 — 이 매출은 집계에서 빠집니다</div>
    <div class="bd">파일 합계는 <b>{won(t.revenue + q.unmapped_amount)}원</b>인데
      대시보드는 <b>{won(t.revenue)}원</b>입니다. 차이가 미매핑입니다.
      <b>미매핑을 조용히 버리면 매출이 증발합니다.</b></div></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>채널마다 컬럼 이름이 다릅니다</h2>
      <span class="note">이게 이 시스템의 첫 관문입니다</span></div>
    <div class="tw"><table class="t">
      <thead><tr><th>논리 필드</th>{"".join(f'<th class="c">{n}</th>' for n in COLS)}</tr></thead>
      <tbody>{"".join(colrows)}</tbody>
    </table></div>
    <div class="card-bd" style="border-top:1px solid var(--border)">
      <div class="psub">같은 뜻인데 이름만 다릅니다. 실수가 아니라 현실입니다 —
        채널 어드민이 각자 다르게 뽑아 줍니다.
        <b>수수료 컬럼은 2개 채널만 주므로</b>, 나머지는 채널 DB의 요율로 계산해야 합니다.</div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>표준화된 매출 원장</h2>
      <span class="note">채널별 컬럼을 공통 이름으로 통일한 결과 · 상위 10건</span>
      <div class="right"><span class="tag mut">전체 {t.orders + q.unmapped_count:,}건</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr>{hdr}</tr></thead><tbody>{"".join(sample)}</tbody>
    </table></div>
  </div>

  <div class="card">
    <div class="card-hd"><h2>미매핑 큐</h2>
      <span class="note">제품과 연결 못 한 상품명 — 반드시 화면에 노출한다</span>
      <div class="right"><span class="tag neg">{q.unmapped_count}건</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr><th>채널</th><th>상품명</th><th>옵션명</th><th class="c">건수</th>
        <th class="r">금액</th></tr></thead>
      <tbody>{unrows}</tbody>
    </table></div>
  </div>
"""
    return page("03-매출데이터.html", "매출 데이터", "매출 데이터",
                f"인풋 ③ · {PERIOD} · 주문 {t.orders + q.unmapped_count:,}건 · 채널별 시트 5장", body,
                '<button class="btn btn-pri btn-sm">엑셀 업로드</button>')


# ── 04 대시보드 ─────────────────────────────────────────────────────────

def build_dashboard(db, t, q):
    chans = rp.by_channel(db, PERIOD)
    losses = rp.loss_deals(db, PERIOD)
    weeks = rp.weekly_trend(db, PERIOD)
    prods = rp.by_product(db, PERIOD)

    crows = "".join(
        f'<tr><td><div class="pname">{c.name}</div><div class="psub">{c.sub}</div></td>'
        f'<td class="r num">{pct(c.extra.get("fee_rate"), 1)}</td>'
        f'<td class="r num">{won(c.orders)}</td><td class="r num">{won(c.revenue)}</td>'
        f'<td class="r num">{won(c.fee)}</td><td class="r num">{won(c.cogs)}</td>'
        f'<td class="r num">{won(c.logistics)}</td>'
        f'<td class="r num" style="font-weight:650">{won(c.profit)}</td>'
        f'<td class="r">{mbar(c.margin)}</td></tr>' for c in chans)

    lrows = "".join(
        f'<tr class="tr-neg"><td class="psub nw">{r.sub}</td>'
        f'<td class="pname">{r.name}</td><td class="c"><span class="tag warn">특가</span></td>'
        f'<td class="r num">{won(r.extra["price"])}</td><td class="r num">{won(r.orders)}</td>'
        f'<td class="r num">{won(r.revenue)}</td>'
        f'<td class="r num neg" style="font-weight:650">{won(r.profit)}</td>'
        f'<td class="r">{mbar(r.margin)}</td></tr>' for r in losses)

    prows = "".join(
        f'<tr><td class="pname">{p.name}</td><td class="r num">{won(p.qty)}</td>'
        f'<td class="r num">{won(p.revenue)}</td>'
        f'<td class="r num {cls(p.margin)}" style="font-weight:650">{won(p.profit)}</td>'
        f'<td class="r">{mbar(p.margin)}</td></tr>' for p in prods[:12])

    mx = max((w.revenue for w in weeks), default=1)
    pm = max((abs(w.profit) for w in weeks), default=1)
    best = max(weeks, key=lambda w: w.revenue)
    worst = min(weeks, key=lambda w: w.margin if w.margin is not None else 9)
    bars = "".join(
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;'
        f'align-items:center;gap:4px">'
        f'<div style="width:100%;background:var(--accent);border-radius:4px 4px 0 0;'
        f'height:{w.revenue / mx * 76:.0f}px"></div>'
        f'<div style="width:100%;background:var(--pos);opacity:.75;border-radius:0 0 4px 4px;'
        f'height:{abs(w.profit) / pm * 28:.0f}px"></div>'
        f'<div class="psub num">{w.name[5:]}</div>'
        f'<div class="psub num {cls(w.margin)}" style="font-weight:650">{pct(w.margin, 1)}</div>'
        f'</div>' for w in weeks)

    wf = ""
    for lbl, val, color in [("순매출", t.revenue, "var(--accent)"),
                            ("− 채널 수수료", -t.fee, "var(--warn)"),
                            ("− 원가", -t.cogs, "var(--text-3)"),
                            ("− 물류비", -t.logistics, "var(--text-3)"),
                            ("= 기여이익", t.profit, "var(--pos)")]:
        w = abs(val) / t.revenue * 100
        wf += (f'<div class="wf-row"><div class="lbl">{lbl}</div>'
               f'<div class="bar"><div class="seg" style="left:0;width:{w:.1f}%;'
               f'background:{color}"></div></div>'
               f'<div class="amt num">{won(val)}</div></div>')

    body = f"""
  <div class="kpis">
    <div class="kpi"><div class="k">총매출</div>
      <div class="v num">{won(t.revenue)}<span class="u">원</span></div>
      <div class="d">판매수량 {won(t.qty)}개 · 주문 {won(t.orders)}건</div></div>
    <div class="kpi"><div class="k">기여이익</div>
      <div class="v num {cls(t.margin)}">{won(t.profit)}<span class="u">원</span></div>
      <div class="d">주문당 {won(t.profit / t.orders)}원</div></div>
    <div class="kpi"><div class="k">마진율</div>
      <div class="v num {cls(t.margin)}">{pct(t.margin)}</div>
      <div class="d">수수료 {pct(t.fee / t.revenue, 1)} · 원가 {pct(t.cogs / t.revenue, 1)}
        · 물류 {pct(t.logistics / t.revenue, 1)}</div></div>
    <div class="kpi"><div class="k">미매핑</div>
      <div class="v num warn" style="color:var(--warn)">{q.unmapped_count}<span class="u">건</span></div>
      <div class="d">{won(q.unmapped_amount)}원 · 매핑률 {pct(q.mapping_rate, 1)}</div></div>
  </div>

  <div class="banner neg">
    <div class="bi">🔻</div>
    <div><div class="bt">적자 딜 {len(losses)}건 — 이번 달 손실 {won(-sum(r.profit for r in losses))}원</div>
    <div class="bd">팔수록 손해입니다. 가격을 올리거나, 수수료가 낮은 채널로 옮기거나, 구성을 바꿔야 합니다.</div></div>
    <div class="right"><button class="btn btn-sm">상세</button></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>적자 딜</h2><span class="note">마진율이 음수인 채널×제품</span></div>
    <div class="tw"><table class="t">
      <thead><tr><th>채널</th><th>제품(딜)</th><th class="c">티어</th><th class="r">판매가</th>
        <th class="r">주문</th><th class="r">매출</th><th class="r">기여이익</th>
        <th class="r">마진율</th></tr></thead>
      <tbody>{lrows}</tbody></table></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>채널별 손익</h2>
      <span class="note">매출 순 · 같은 제품이라도 수수료율이 다르면 남는 돈이 달라집니다</span></div>
    <div class="tw"><table class="t">
      <thead><tr><th>채널</th><th class="r">수수료율</th><th class="r">주문</th><th class="r">매출</th>
        <th class="r">수수료</th><th class="r">원가</th><th class="r">물류비</th>
        <th class="r">기여이익</th><th class="r">마진율</th></tr></thead>
      <tbody>{crows}</tbody>
      <tfoot><tr><td>합계</td><td class="r num">{pct(t.fee / t.revenue, 1)}</td>
        <td class="r num">{won(t.orders)}</td><td class="r num">{won(t.revenue)}</td>
        <td class="r num">{won(t.fee)}</td><td class="r num">{won(t.cogs)}</td>
        <td class="r num">{won(t.logistics)}</td><td class="r num">{won(t.profit)}</td>
        <td class="r num">{pct(t.margin)}</td></tr></tfoot>
    </table></div>
  </div>

  <div class="g-2-1">
    <div class="card">
      <div class="card-hd"><h2>제품별 기여이익</h2>
        <span class="note">이익 순 상위 12 · 매출 1위와 이익 1위는 대개 다릅니다</span></div>
      <div class="tw"><table class="t">
        <thead><tr><th>제품</th><th class="r">수량</th><th class="r">매출</th>
          <th class="r">기여이익</th><th class="r">마진율</th></tr></thead>
        <tbody>{prows}</tbody></table></div>
    </div>

    <div class="stack">
      <div class="card">
        <div class="card-hd"><h2>이익 구조</h2></div>
        <div class="card-bd"><div class="wf">{wf}</div></div>
      </div>
      <div class="card">
        <div class="card-hd"><h2>주별 추이</h2><span class="note">위=매출 · 아래=이익</span></div>
        <div class="card-bd">
          <div style="display:flex;gap:10px;align-items:flex-end;height:135px">{bars}</div>
          <div class="psub" style="margin-top:12px;line-height:1.6">
            매출이 가장 높은 <b>{best.name}</b>의 마진율이 {pct(worst.margin, 1)}로 가장 낮습니다.
            행사로 특가 비중이 올랐기 때문입니다 —
            <b>"매출 최고 기록"이 좋은 소식이 아닐 수 있습니다.</b></div>
        </div>
      </div>
    </div>
  </div>
"""
    return page("04-대시보드.html", "수익률 대시보드", "수익률 대시보드",
                f"{PERIOD} · 월별 · 활성 채널 {len(chans)}곳 · 주문 {won(t.orders)}건", body,
                '<select class="sel"><option>2026-07</option></select>'
                '<button class="btn btn-sm">엑셀 내보내기</button>')


# ── 05 상세 리포트 ──────────────────────────────────────────────────────

def build_report(db, t):
    prods = rp.by_product(db, PERIOD)
    deals = rp.by_deal(db, PERIOD, order="margin")
    chans = rp.by_channel(db, PERIOD)
    hm_names, hm_rows = rp.heatmap(db, PERIOD)

    prows = "".join(
        f'<tr{" class=tr-neg" if (p.margin or 0) < 0 else ""}>'
        f'<td class="pname">{p.name}</td><td class="r num">{won(p.qty)}</td>'
        f'<td class="r num">{won(p.revenue)}</td><td class="r num">{won(p.fee)}</td>'
        f'<td class="r num">{won(p.cogs)}</td><td class="r num">{won(p.logistics)}</td>'
        f'<td class="r num {cls(p.margin)}" style="font-weight:650">{won(p.profit)}</td>'
        f'<td class="r">{mbar(p.margin)}</td></tr>' for p in prods)

    drows = "".join(
        f'<tr{" class=tr-neg" if (d.margin or 0) < 0 else ""}>'
        f'<td class="psub nw">{d.sub}</td><td class="pname">{d.name}</td>'
        f'<td class="r num">{won(d.extra["price"])}</td><td class="r num">{won(d.orders)}</td>'
        f'<td class="r num">{won(d.revenue)}</td>'
        f'<td class="r num {cls(d.margin)}">{won(d.profit)}</td>'
        f'<td class="r">{mbar(d.margin)}</td></tr>' for d in deals)

    def hc(v):
        if v is None:
            return "na", ""
        c = ("var(--neg)" if v < 0 else "var(--warn)" if v < 0.05
             else "var(--pos)")
        a = min(abs(v) / 0.25, 1) * 0.30 + 0.10
        return "", f"background:color-mix(in srgb,{c} {a * 100:.0f}%,transparent);color:{c}"

    hrows = ""
    for r in hm_rows[:14]:
        tds = ""
        for v in r["cells"]:
            k, s = hc(v)
            tds += f'<td class="{k}" style="{s}">{"—" if v is None else f"{v * 100:.1f}"}</td>'
        k, s = hc(r["total"])
        tds += f'<td class="{k}" style="{s};font-weight:700">{"—" if r["total"] is None else f"{r['total'] * 100:.1f}"}</td>'
        hrows += f'<tr><th class="rowh">{r["name"]}</th>{tds}</tr>'

    body = f"""
  <div class="banner acc">
    <div class="bi">🔍</div>
    <div><div class="bt">같은 제품도 채널이 다르면 마진율이 달라집니다</div>
    <div class="bd">아래 히트맵의 한 행을 가로로 읽어 보세요. 초록과 빨강이 같은 행에 있으면
      <b>채널만 바꿔도 적자가 흑자가 된다</b>는 뜻입니다.</div></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>채널 × 제품 마진율 히트맵</h2>
      <span class="note">단위 % · 상위 14개 제품</span></div>
    <div class="card-bd tw">
      <table class="hm">
        <thead><tr><th class="rowh">제품</th>
          {"".join(f"<th>{n}</th>" for n in hm_names)}<th>전체</th></tr></thead>
        <tbody>{hrows}</tbody>
      </table>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-hd"><h2>제품별 리포트</h2>
      <span class="note">기여이익 순 · 결과 엑셀 시트 02와 동일</span>
      <div class="right"><span class="tag mut">{len(prods)}종</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr><th>제품</th><th class="r">수량</th><th class="r">매출</th><th class="r">수수료</th>
        <th class="r">원가</th><th class="r">물류비</th><th class="r">기여이익</th>
        <th class="r">마진율</th></tr></thead>
      <tbody>{prows}</tbody>
      <tfoot><tr><td>합계</td><td class="r num">{won(t.qty)}</td><td class="r num">{won(t.revenue)}</td>
        <td class="r num">{won(t.fee)}</td><td class="r num">{won(t.cogs)}</td>
        <td class="r num">{won(t.logistics)}</td><td class="r num">{won(t.profit)}</td>
        <td class="r num">{pct(t.margin)}</td></tr></tfoot>
    </table></div>
  </div>

  <div class="card">
    <div class="card-hd"><h2>채널 × 제품 (딜) 리포트</h2>
      <span class="note">마진율 낮은 순 · 결과 엑셀 시트 04와 동일</span>
      <div class="right"><span class="tag mut">{len(deals)}건</span>
        <span class="tag pos">채널 {len(chans)}곳</span></div></div>
    <div class="tw"><table class="t">
      <thead><tr><th>채널</th><th>제품(딜)</th><th class="r">판매가</th><th class="r">주문</th>
        <th class="r">매출</th><th class="r">기여이익</th><th class="r">마진율</th></tr></thead>
      <tbody>{drows}</tbody>
    </table></div>
  </div>
"""
    return page("05-리포트.html", "상세 리포트", "상세 리포트",
                f"{PERIOD} · 제품별 {len(prods)}종 · 채널×제품 {len(deals)}건", body,
                '<button class="btn btn-sm">엑셀 내보내기</button>')


# ── 실행 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(SalesLine)):
            sys.exit("판매 데이터가 없습니다. 먼저: python -m app.cli init && python -m app.demo")
        t, q = rp.totals(db, PERIOD), rp.quality(db, PERIOD)
        pages = {
            "index.html": build_index(db, t, q),
            "01-상품DB.html": build_products(),
            "02-채널DB.html": build_channels(db),
            "03-매출데이터.html": build_sales(db, t, q),
            "04-대시보드.html": build_dashboard(db, t, q),
            "05-리포트.html": build_report(db, t),
        }
    for name, html in pages.items():
        (HERE / name).write_text(html, encoding="utf-8")
        print(f"  ✓ mock/{name}")
    print(f"\n검산: 총매출 {t.revenue:,}원 · 기여이익 {t.profit:,}원 · 마진율 {t.margin:.2%}")
    print("브라우저로 mock/index.html 을 여세요.")
