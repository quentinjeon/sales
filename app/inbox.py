# -*- coding: utf-8 -*-
"""수집함 점검 — docs/inbox 에 올린 채널 파일이 쓸 수 있는 형태인지 진단한다.

    python -m app.inbox              # 전체 기간 점검
    python -m app.inbox 2026-07      # 특정 기간만

PRD §7.6 의 검증 항목 중 「필수 컬럼 존재」를 파일 파서 없이 미리 확인해 준다.
지금 받고 계신 부가세신고 요약본은 여기서 걸러진다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "docs" / "inbox"

# 채널 코드 → 표시명
CHANNELS = {
    "HANBIT": "한빛홈쇼핑", "SWIFT_FF": "스위프트 풀필먼트", "SWIFT_MED": "스위프트 중개",
    "MALL21": "몰이십일", "GOODMKT": "굿마켓", "BIDNOW": "비드나우",
    "PAYSHOP": "페이샵", "NSTORE": "엔스토어", "GLOBALX": "글로벌엑스",
    "TALKMALL": "톡몰", "DAERIM_HS": "대림홈쇼핑", "DAERIM_ON": "대림온",
    "LIVEON": "라이브온", "BOOKMALL": "북몰",
}
P0 = ["HANBIT", "SWIFT_FF", "MALL21", "GOODMKT", "BIDNOW"]

# 논리 필드 → 컬럼명에 들어갈 법한 키워드 (하나라도 걸리면 존재로 판단)
REQUIRED = {
    "주문일":    ["주문일", "결제일", "구매확정", "정산일", "매출일", "주문번호"],
    "상품명":    ["상품명", "품목", "상품", "product"],
    "옵션명":    ["옵션", "단품", "선택", "option"],
    "수량":      ["수량", "판매수량", "qty", "개수"],
    "판매금액":  ["판매금액", "결제금액", "매출액", "상품금액", "정산금액", "판매가"],
}
OPTIONAL = {
    "수수료":    ["수수료", "이용료", "판매수수료", "매입수수료", "서비스이용료"],
    "취소여부":  ["취소", "반품", "상태"],
}


def _read_header_rows(path: Path, max_rows: int = 12) -> list[list[str]]:
    """상단 몇 행을 문자열로 읽는다. 헤더 위치가 채널마다 달라 여러 행을 본다."""
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        df = pd.read_excel(path, header=None, nrows=max_rows)
    except Exception:
        try:
            df = pd.read_csv(path, header=None, nrows=max_rows, encoding="utf-8-sig")
        except Exception:
            return []
    return [[str(v) for v in row if str(v) != "nan"] for _, row in df.iterrows()]


def diagnose(path: Path) -> dict:
    rows = _read_header_rows(path)
    if not rows:
        return {"ok": False, "reason": "FILE_UNREADABLE", "found": {}, "missing": list(REQUIRED)}

    blob = " ".join(" ".join(r) for r in rows).lower()
    found = {k: any(kw.lower() in blob for kw in kws) for k, kws in REQUIRED.items()}
    extra = {k: any(kw.lower() in blob for kw in kws) for k, kws in OPTIONAL.items()}
    missing = [k for k, v in found.items() if not v]

    # 요약본 판별 — 제품 축(상품명·수량)이 없으면 부가세 신고 요약본이다
    summary = not found["상품명"] and not found["수량"]
    return {"ok": not missing, "reason": "MISSING_COLUMN" if missing else None,
            "found": found, "extra": extra, "missing": missing, "summary": summary}


def scan(period: str | None = None) -> int:
    if not INBOX.exists():
        print(f"수집함이 없습니다: {INBOX}")
        return 1

    periods = sorted(p.name for p in INBOX.iterdir()
                     if p.is_dir() and not p.name.startswith("_"))
    if period:
        periods = [p for p in periods if p == period]
    if not periods:
        print("점검할 기간 폴더가 없습니다. docs/inbox/README.md 를 참고하세요.")
        return 1

    problems = 0
    for per in periods:
        print(f"\n■ {per}")
        base = INBOX / per
        for code in P0 + [c for c in CHANNELS if c not in P0]:
            d = base / code
            if not d.exists():
                continue
            files = [f for f in d.iterdir()
                     if f.is_file() and f.suffix.lower() in (".xls", ".xlsx", ".csv")
                     and not f.name.startswith((".", "~$"))]
            label = f"{CHANNELS.get(code, code)} ({code})"
            if not files:
                mark = "○" if code in P0 else "·"
                print(f"  {mark} {label:<26} 파일 없음")
                if code in P0:
                    problems += 1
                continue
            for f in files:
                r = diagnose(f)
                if r["ok"]:
                    fee = " · 수수료 컬럼 있음" if r["extra"].get("수수료") else ""
                    print(f"  ✓ {label:<26} {f.name}{fee}")
                elif r.get("summary"):
                    print(f"  ✗ {label:<26} {f.name}")
                    print(f"      → 부가세신고 요약본으로 보입니다. 제품 축(상품명·수량)이 없습니다.")
                    print(f"      → 주문건별 상세 파일을 받아주세요 (docs/inbox/README.md 참고)")
                    problems += 1
                else:
                    print(f"  ✗ {label:<26} {f.name}")
                    print(f"      → 누락 컬럼: {', '.join(r['missing'])}")
                    problems += 1

    print()
    if problems:
        print(f"⚠ 처리할 수 없는 항목 {problems}건. 위 안내대로 파일을 교체해 주세요.")
    else:
        print("✓ 모든 파일이 필수 컬럼을 갖추고 있습니다. 어댑터 작성을 진행할 수 있습니다.")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(scan(sys.argv[1] if len(sys.argv) > 1 else None))
