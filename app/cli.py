# -*- coding: utf-8 -*-
"""운영 CLI.

    python -m app.cli init          DB 생성 + 마스터 시드 적재
    python -m app.cli status        현재 마스터 현황
    python -m app.cli margins       제품별 계획/채널별 마진율 표
"""
from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import func, select

from app.db import DB_PATH, SessionLocal, init_db
from app.models import Channel, ChannelFee, Deal, Sku, SkuCost
from app.seed import PLAN_CHANNEL_ID, seed_all
from app.seed.data import SKUS, TIERS, UNRESOLVED_ROWS
from app.services.calc import CalcError, compute, get_fee_rate

TIER_KO = {"NORMAL": "정상가", "EVENT": "일반행사", "SPECIAL": "특가"}


def cmd_init() -> None:
    init_db()
    with SessionLocal() as db:
        n = seed_all(db)
    print(f"DB 생성: {DB_PATH}")
    print(f"  채널 {n['channels']}개 · 제품 {n['skus']}개 · 딜 {n['deals']}개 적재")
    if UNRESOLVED_ROWS:
        print(f"  ⚠ 상품명 미확정 {len(UNRESOLVED_ROWS)}건은 보류 (PRD §14.2)")
        for spec, cost in UNRESOLVED_ROWS:
            print(f"      - {spec} · 매입가 {cost:,}원")


def cmd_status() -> None:
    with SessionLocal() as db:
        active = db.scalars(
            select(Channel).where(Channel.status == "ACTIVE").order_by(Channel.sort_order)).all()
        waiting = db.scalars(
            select(Channel).where(Channel.status == "WAITING").order_by(Channel.sort_order)).all()

        print(f"제품 {db.scalar(select(func.count()).select_from(Sku))}개 · "
              f"딜 {db.scalar(select(func.count()).select_from(Deal))}개\n")

        today = date.today().isoformat()

        def rate_of(cid):
            try:
                return get_fee_rate(db, cid, today)[0]
            except CalcError:
                return None

        print(f"활성 채널 {len(active)}개")
        for c in active:
            rate = rate_of(c.id)
            r = f"{rate:.1%}" if rate is not None else "미등록"
            print(f"  {c.name:<16} 수수료 {r:>7}  {c.ship_owner:<16} {c.settle_date_src}")

        print(f"\n대기 채널 {len(waiting)}개")
        for c in waiting:
            rate = rate_of(c.id)
            r = f"{rate:.1%}" if rate is not None else "미확인"
            print(f"  {c.name:<16} 수수료 {r:>7}  {c.note or ''}")


def cmd_margins() -> None:
    """제품별 계획 마진율(13% 가정)과 활성 채널별 특가 마진율."""
    with SessionLocal() as db:
        chans = db.scalars(
            select(Channel).where(Channel.status == "ACTIVE").order_by(Channel.sort_order)).all()

        head = f"{'제품':<24}{'매입가':>7}{'구성':>4}  " + \
               "".join(f"{TIER_KO[t]:>9}" for t, _ in TIERS) + "  │" + \
               "".join(f"{c.name[:8]:>10}" for c in chans)
        print(head)
        print("─" * len(head))

        rows = []
        for row in SKUS:
            sku_id, name, pack = row[0], row[1], row[4]
            plan, actual = [], []
            for tier, _ in TIERS:
                deal = db.get(Deal, f"{sku_id}-X{pack}-{tier}")
                r = compute(db, channel_id=PLAN_CHANNEL_ID, deal=deal,
                            order_date="2026-07-15", qty=1, gross_amount=deal.price)
                plan.append(r.margin_rate)
            special = db.get(Deal, f"{sku_id}-X{pack}-SPECIAL")
            for c in chans:
                try:
                    r = compute(db, channel_id=c.id, deal=special, order_date="2026-07-15",
                                qty=1, gross_amount=special.price)
                    actual.append(r.margin_rate)
                except CalcError:
                    actual.append(None)
            rows.append((name, row[3], pack, plan, actual))

        for name, cost, pack, plan, actual in sorted(rows, key=lambda x: x[3][2]):
            line = f"{name[:23]:<24}{cost:>7,}{('x%d' % pack):>4}  "
            line += "".join(f"{p*100:>8.1f}%" for p in plan)
            line += "  │"
            line += "".join(f"{a*100:>9.1f}%" if a is not None else f"{'—':>10}" for a in actual)
            print(line)

        print("\n계획 = 가격표의 수수료 13% 고정 가정 · 우측 = 특가를 각 채널 실측 요율로 계산")
        print("특가 적자 제품은 채널에 따라 흑자 전환이 가능합니다 — 배치 판단의 근거입니다.")


if __name__ == "__main__":
    cmds = {"init": cmd_init, "status": cmd_status, "margins": cmd_margins}
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg not in cmds:
        print(f"사용법: python -m app.cli [{' | '.join(cmds)}]")
        sys.exit(1)
    cmds[arg]()
