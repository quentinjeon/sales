# -*- coding: utf-8 -*-
"""데모 데이터 생성 — 실물 채널 파일 확보 전까지 화면을 확인하기 위한 용도.

주의: 판매 수량은 4~5월 실적 규모에 맞춘 가상값이다.
      매입가·판매가·수수료율은 전부 실제 값이므로 손익 구조 자체는 현실적이다.
      실물 파일이 들어오면 이 배치를 삭제하고 재계산한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Deal, SalesLine, UploadBatch, UploadFile
from app.services import mapping as mp
from app.services.calc import CalcError, apply_to_line, clear_calc
from app.services.report import period_keys

DEMO_MONTH = "2026-07"

# (채널, SKU, 티어, 주당 주문건수)
# 오픈마켓 실제 판매 형태를 반영했다 — 생필품·간편식이 물량을 끌고,
# 건강기능식품이 마진을 받친다. 적자 딜은 물량이 많은 쪽에 붙어 손실이 커진다.
DEMO_MIX = [
    ("HANBIT", "TISSUE30", "SPECIAL", 74),  ("HANBIT", "RICE24", "EVENT", 52),
    ("HANBIT", "WIPE10", "EVENT", 63),      ("HANBIT", "RAMEN20", "SPECIAL", 38),
    ("HANBIT", "NUTS20", "EVENT", 31),      ("HANBIT", "PROBIO30", "EVENT", 22),
    ("HANBIT", "CHICK20", "SPECIAL", 27),   ("HANBIT", "GIM4", "EVENT", 19),

    ("SWIFT_FF", "RICE24", "SPECIAL", 66),  ("SWIFT_FF", "TISSUE30", "EVENT", 41),
    ("SWIFT_FF", "CAPSULE100", "SPECIAL", 35), ("SWIFT_FF", "PROTEIN30", "EVENT", 28),
    ("SWIFT_FF", "LITTER2", "SPECIAL", 24), ("SWIFT_FF", "WIPE10", "SPECIAL", 33),
    ("SWIFT_FF", "TUNA12", "EVENT", 17),

    ("MALL21", "TISSUE30", "SPECIAL", 58),  ("MALL21", "COLDBREW6", "SPECIAL", 29),
    ("MALL21", "SOUP15", "EVENT", 34),      ("MALL21", "VITD90", "SPECIAL", 26),
    ("MALL21", "SOFT2", "SPECIAL", 21),     ("MALL21", "JELLY10", "EVENT", 15),
    ("MALL21", "OMEGA60", "EVENT", 11),

    ("GOODMKT", "RICE24", "EVENT", 37),     ("GOODMKT", "DISH3", "SPECIAL", 30),
    ("GOODMKT", "ZIP3", "EVENT", 22),       ("GOODMKT", "PETSNACK50", "SPECIAL", 26),
    ("GOODMKT", "MILKT90", "SPECIAL", 18),  ("GOODMKT", "CUP1000", "EVENT", 14),

    ("BIDNOW", "RICE24", "EVENT", 13),      ("BIDNOW", "WIPE10", "EVENT", 16),
    ("BIDNOW", "TISSUE30", "SPECIAL", 11),
]

# (주 시작일, 전체 배수, 특가 배수) — 행사 주간은 특가 비중이 올라 마진율이 눌린다
WEEKS = [(date(2026, 7, 6), 0.90, 0.72), (date(2026, 7, 13), 1.02, 1.55),
         (date(2026, 7, 20), 0.99, 0.86), (date(2026, 7, 27), 1.06, 1.28)]

# 미매핑 큐를 보여주기 위한 라인 — 실무에서 실제로 자주 나오는 형태
# 오픈마켓 상품명은 검색 키워드를 잔뜩 붙여 등록하기 때문에
# 제품 DB의 이름과 글자가 잘 안 맞는다. 매핑 실습용 샘플이다.
UNMAPPED_SAMPLES = [
    ("SWIFT_FF", "온담 3겹 데코 화장지 30롤 대용량 무형광 천연펄프 두루마리",
     "30롤 x 1팩 + 물티슈 100매 1팩 증정", 26900, 2),
    ("GOODMKT", "[7월 특가] 온담 무균 즉석밥 210g 24개입 햇반 대체 즉석밥",
     "210g x 24개 (박스단위)", 24900, 3),
    ("SWIFT_FF", "온담 홈캉스 세트 (즉석밥 12개 + 즉석국 8개 + 김자반 2봉)",
     "즉석밥12 + 즉석국8 + 김자반2", 42900, 2),
]

CHANNEL_LABEL = {
    "HANBIT": ("한빛홈쇼핑_거래상세내역_202607.xlsx", "HANBIT_TXN_V1"),
    "SWIFT_FF": ("swift_fulfillment_202607.xlsx", "SWIFT_FF_TXN_V1"),
    "MALL21": ("몰이십일_정산상세_202607.xls", "MALL21_TXN_V1"),
    "GOODMKT": ("통합몰_주문내역_굿마켓_202607.xls", "UNIMALL_V1"),
    "BIDNOW": ("통합몰_주문내역_비드나우_202607.xls", "UNIMALL_V1"),
}


def _deal_id(db: Session, sku_id: str, tier: str) -> str:
    return db.scalar(
        select(Deal.id).where(Deal.primary_sku_id == sku_id, Deal.tier == tier,
                              Deal.channel_id.is_(None)))


def wipe(db: Session) -> None:
    """기존 데모 배치를 지운다 (재실행 가능)."""
    ids = db.scalars(select(UploadBatch.id).where(UploadBatch.period_key == DEMO_MONTH)).all()
    if not ids:
        return
    fids = db.scalars(select(UploadFile.id).where(UploadFile.batch_id.in_(ids))).all()
    if fids:
        db.execute(delete(SalesLine).where(SalesLine.file_id.in_(fids)))
        db.execute(delete(UploadFile).where(UploadFile.id.in_(fids)))
    db.execute(delete(UploadBatch).where(UploadBatch.id.in_(ids)))
    db.flush()


def generate(db: Session) -> dict[str, int]:
    wipe(db)
    batch = UploadBatch(period_type="MONTH", period_key=DEMO_MONTH,
                        status="PARSED", uploaded_by="demo")
    db.add(batch)
    db.flush()

    files: dict[str, UploadFile] = {}
    for ch, (fname, fmt) in CHANNEL_LABEL.items():
        f = UploadFile(batch_id=batch.id, channel_id=ch, filename=fname,
                       stored_path=f"(demo)/{fname}", sha256=f"demo-{ch}",
                       format_id=None, status="PARSED")
        db.add(f)
        files[ch] = f
    db.flush()

    # ① 매핑 규칙 등록 — 딜 라벨을 채널 상품명으로 쓴다 (데모)
    seen = set()
    for ch, sku, tier, _ in DEMO_MIX:
        did = _deal_id(db, sku, tier)
        deal = db.get(Deal, did)
        if (ch, deal.label) in seen:
            continue
        mp.register(db, channel_id=ch, product=deal.label, option=deal.tier,
                    deal_id=did, match_type="EXACT", actor="demo")
        seen.add((ch, deal.label))

    # ② 주문 라인 생성
    seq, n_lines = 0, 0
    for week_start, mult, tuk in WEEKS:
        pm, pw = period_keys(week_start)
        for ch, sku, tier, base in DEMO_MIX:
            cnt = max(1, round(base * mult * (tuk if tier == "SPECIAL" else 1.0)))
            did = _deal_id(db, sku, tier)
            deal = db.get(Deal, did)
            for i in range(cnt):
                d = week_start + timedelta(days=i % 7)
                m, w = period_keys(d)
                seq += 1
                db.add(SalesLine(
                    file_id=files[ch].id, channel_id=ch,
                    order_no=f"D{seq:08d}", order_line_no="1",
                    order_date=d.isoformat(),
                    raw_product_name=deal.label, raw_option_name=deal.tier,
                    qty=1, gross_amount=deal.price,
                    period_month=m, period_week=w,
                    map_status="UNMAPPED",
                ))
                n_lines += 1
        db.flush()

    # ③ 미매핑 샘플
    for ch, prod, opt, price, cnt in UNMAPPED_SAMPLES:
        for i in range(cnt):
            seq += 1
            d = date(2026, 7, 22) + timedelta(days=i)
            m, w = period_keys(d)
            db.add(SalesLine(
                file_id=files[ch].id, channel_id=ch,
                order_no=f"U{seq:08d}", order_line_no="1", order_date=d.isoformat(),
                raw_product_name=prod, raw_option_name=opt,
                qty=1, gross_amount=price, period_month=m, period_week=w,
                map_status="UNMAPPED",
            ))
            n_lines += 1
    db.flush()

    # ④ 매핑 → ⑤ 계산
    lines = db.scalars(
        select(SalesLine).where(SalesLine.file_id.in_([f.id for f in files.values()]))).all()
    stat = mp.map_lines(db, lines)

    ok = err = 0
    for ln in lines:
        if ln.map_status != "MAPPED":
            clear_calc(ln)
            continue
        try:
            apply_to_line(db, ln, db.get(Deal, ln.deal_id))
            ok += 1
        except CalcError as e:
            ln.map_status, ln.map_note = "UNMAPPED", str(e)
            clear_calc(ln)
            err += 1

    # 파일별 요약
    for ch, f in files.items():
        rows = [l for l in lines if l.channel_id == ch]
        f.row_count = len(rows)
        f.gross_sum = sum(l.gross_amount for l in rows)

    batch.status = "CALCULATED"
    db.commit()
    return {"lines": n_lines, "mapped": stat["mapped"], "unmapped": stat["unmapped"],
            "calculated": ok, "calc_error": err}


if __name__ == "__main__":
    from app.db import SessionLocal, init_db
    init_db()
    with SessionLocal() as s:
        r = generate(s)
    print(f"데모 데이터 생성 ({DEMO_MONTH})")
    print(f"  주문 라인 {r['lines']:,}건 · 매핑 {r['mapped']:,} · 미매핑 {r['unmapped']}")
    print(f"  계산 완료 {r['calculated']:,}건" + (f" · 오류 {r['calc_error']}" if r["calc_error"] else ""))
