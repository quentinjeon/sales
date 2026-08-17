# CLAUDE.md — 인계 문서

> **이 파일을 가장 먼저 읽으세요.** 지금 어디까지 되어 있고, 다음에 무엇을 해야 하는지 적혀 있습니다.

---

## 1. 이 시스템은 무엇인가

**엑셀 3장을 넣으면 그 달의 「제품별 매출」과 「채널별 매출·이익률」을 보여주는 웹 도구**입니다.

```
📦 01_상품정보.xlsx   ─┐
🛒 02_채널정보.xlsx   ─┼─→ 표준화·매핑 → 손익 계산 → 📊 대시보드 + 📗 결과 엑셀
🧾 03_매출_YYYY-MM.xlsx ─┘
```

핵심 개념 하나만 기억하면 됩니다.

> **딜(Deal) = 채널 × 제품 구성 × 가격 티어 × 기간**
> 같은 제품도 어느 몰에서 어떤 구성·가격으로 파느냐에 따라 손익이 다릅니다.
> 이 시스템은 그 단위로 이익을 계산합니다.

이 저장소는 **바이브코딩 수업 교보재**를 겸합니다.
수강생은 [docs/PRD.md](docs/PRD.md)를 AI에게 주고 이 시스템을 직접 만들어 봅니다.

---

## 2. ⚠ 데이터는 전부 목업입니다

회사·브랜드·제품·채널·금액이 **전부 가상**입니다. 실존 기업·제품·판매채널과 무관합니다.
손익 구조(원가율, 채널별 수수료 격차, 특가 구간의 적자)만 실무와 같게 설계했습니다.

가상 설정: 회사 **온담커머스**(오픈마켓 종합 셀러) · 제품 23종 · 채널 14개(운영 5 · 대기 9)

---

## 3. 지금까지 된 것

| 구성요소 | 상태 | 위치 |
|---|:-:|---|
| 데이터 모델 | ✅ | `app/models.py` |
| 손익 계산 엔진 | ✅ | `app/services/calc.py` |
| 상품명 매핑 (정규화·정확일치·제안) | ✅ | `app/services/mapping.py` |
| **엑셀 적재 (인풋 3장)** | ✅ | `app/services/ingest.py` |
| **결과 엑셀 내보내기 (6시트)** | ✅ | `app/services/export.py` |
| 리포트 집계 | ✅ | `app/services/report.py` |
| 웹 화면 6개 + 업로드/내보내기 | ✅ | `app/web.py`, `app/templates/` |
| 마스터 시드 · 데모 생성기 | ✅ | `app/seed/`, `app/demo.py` |
| 수집함 진단 | ✅ | `app/inbox.py` |
| 테스트 60건 | ✅ | `tests/` |
| 반품·쿠폰 · 월말 정산 대사 | ❌ | P1 (§6) |

---

## 4. 실행 방법

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python -m app.cli init && .venv/bin/python -m app.demo
```

```bash
.venv/bin/python -m uvicorn app.web:app --reload --port 8010
```

→ http://127.0.0.1:8010

| 명령 | 설명 |
|---|---|
| `python -m app.cli init` | DB 생성 + 마스터 시드 |
| `python -m app.cli status` | 활성/대기 채널 현황 |
| `python -m app.cli margins` | 제품별 계획 vs 채널별 실측 마진율 |
| `python -m app.demo` | 데모 판매 데이터 생성 (실물 들어오면 삭제) |
| `python -m app.inbox [기간]` | 수집함 파일 진단 |
| `python docs/lecture/실습데이터_생성.py` | 실습 엑셀 3종 + 정답지 2종 생성 |
| `python mock/generate.py` | 화면 기획 HTML 6장 생성 |
| `python -m pytest -q` | 테스트 60건 |

### 엑셀로 데이터 넣기

화면 `/upload` 에서 올리거나, 코드로:

```python
from app.services import ingest as ing
ing.load_products(db, "docs/lecture/실습데이터/01_상품정보.xlsx")
ing.load_channels(db, "docs/lecture/실습데이터/02_채널정보.xlsx")
ing.load_sales(db, "docs/lecture/실습데이터/03_매출_2026-07.xlsx", period="2026-07")
```

**빈 DB에 엑셀 3장만 넣어도 정답지와 같은 숫자가 나옵니다** — `tests/test_ingest.py` 가 이걸 지킵니다.

---

## 5. 검수 기준 — 이 숫자가 맞아야 정상

```
총매출 77,667,300 · 수수료 8,711,768 · 원가 52,072,450 · 물류비 10,928,600
기여이익 5,954,482 · 마진율 7.67% · 주문 3,707건
미매핑 7건 / 214,300원 · 적자 딜 3건
```

계산식이나 시드를 바꾸면 여기가 먼저 깨집니다. 깨지면 고치기 전에 **왜인지 확인하세요.**
기대값 표 재생성 방법은 `tests/test_calc.py` 상단 주석에 있습니다.

---

## 6. 다음 작업 (P1)

- 반품·취소 반영 (현재는 취소 건을 매출·원가·물류비 전부 0으로 처리)
- 쿠폰 자사부담 분리 (`sales_line.own_discount` 는 있으나 아직 채우는 경로가 없음)
- 채널풀필먼트 실물류비 (현재 건당 추정치, `is_estimate=1`)
- 월말 정산 대사 (`reconciliation` 테이블은 있으나 미사용)
- 미사용 모델 정리 — `FileFormat` `FileReject` `ProfitMart` `Reconciliation` `AuditLog`,
  `SalesLine.discount_amount` `shipping_charged`, `report.weeks_in_month()`
- 화면 캡처 재촬영 (`docs/Screenshot/` 은 구 데이터라 삭제함)

---

## 7. 설계에서 반드시 지킬 것

이 규칙들을 어기면 손익이 조용히 틀립니다.

| 규칙 | 이유 |
|---|---|
| **계산 결과는 `sales_line`에 스냅샷으로 저장** | 매입가·요율을 나중에 바꿔도 과거 손익이 변하면 안 됨 |
| **매입가·요율·딜 가격은 UPDATE 금지, 이력 행 추가** | 위와 같은 이유. `effective_from`/`to`로 관리 |
| **시점 조회는 반드시 `effective_from ≤ 판매일 < effective_to`** | 화면에서 날짜 없이 요율을 집으면 이력이 늘어난 순간 틀림 |
| **증정품도 `deal_component`에 포함** | 빼면 원가 누락 → 이익 과대 계상 |
| **증정품·복합세트는 기존 딜에 붙이지 말고 새 딜로** | 구성이 다르면 원가가 다름 |
| **미매핑은 절대 조용히 버리지 않는다** | 화면 4곳 + 결과 엑셀 6번 시트에 상시 노출 |
| **금액은 원 단위 정수** | 부동소수점 금액 금지 |
| **요율 근거가 `ESTIMATE`일 때만 `추정` 배지** | 실측을 추정처럼 보여도, 추정을 실측처럼 보여도 잘못된 판단을 부름 |
| **필수 컬럼이 없으면 예외** | 빈 값으로 채우면 매출이 증발함 |

---

## 8. 계산식

```
순매출   = 판매금액 (취소면 0)
수수료   = 실적값 우선, 없으면 순매출 × 채널 요율
원가     = Σ(딜 구성 SKU × 판매일 기준 매입가) × 판매수량
물류비   = 채널 배송비 모델 × 판매수량
기여이익 = 순매출 − 수수료 − 자사부담할인 − 원가 − 물류비
마진율   = 기여이익 ÷ 순매출
```

**취소 건은 매출·수수료·원가·물류비가 전부 0**입니다.
원가만 남기면 취소 1건마다 원가 전액이 이익에서 사라집니다.

23개 제품 × 3티어의 계획 마진율은 `tests/test_calc.py::test_c1_plan_margin_matches_pricelist`
가 회귀 기준선으로 고정하고 있습니다.

---

## 9. 문서

| 문서 | 내용 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | **개발 명세** — 입력·계산·화면·검수 기준. AI에게 그대로 주는 용도 |
| [docs/목업데이터-소개.md](docs/목업데이터-소개.md) | 상품 DB · 채널 DB · 매출 데이터 · 결과 리포트 설명 |
| [docs/lecture/README.md](docs/lecture/README.md) | 바이브코딩 수업 진행 순서 |
| [docs/lecture/바이브코딩-시작하기.md](docs/lecture/바이브코딩-시작하기.md) | 입문자용 8단계 가이드 |
| [docs/inbox/README.md](docs/inbox/README.md) | 파일 요청·업로드 안내 |
| [mock/index.html](mock/index.html) | 화면 기획 6장 (브라우저로 열기) |

---

## 10. 알아두면 좋은 것

- **월 합계 ≠ 주 합계**입니다. 주차가 월 경계를 걸치기 때문이며 의도된 동작입니다.
  대시보드는 미완결 기간에 착지하지 않도록 직전 기간 대비 30% 미만이면 한 칸 물러섭니다.
- **채널마다 매출 파일 컬럼명이 다릅니다.** `ingest.SALES_COLUMNS` 의 키워드 표로 찾습니다.
  채널이 어드민을 개편하면 키워드만 추가하면 됩니다.
- **수수료 컬럼은 5개 채널 중 2곳만 줍니다.** 나머지는 채널 요율로 계산하며,
  요율 근거가 `ESTIMATE`인 채널만 화면에 `추정` 배지가 붙습니다.
- `_PLAN`은 가격표의 13% 가정을 재현하는 **가상 채널**입니다. 실적 집계에서 제외됩니다.
