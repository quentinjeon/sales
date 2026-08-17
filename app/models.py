# -*- coding: utf-8 -*-
"""데이터 모델 — PRD-시스템-개발명세.md §5

금액은 모두 원 단위 정수(Integer). 부동소수점 금액을 쓰지 않는다.
날짜는 'YYYY-MM-DD' 문자열로 저장한다 (SQLite/Postgres 양쪽에서 비교 가능).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 3. 마스터 ────────────────────────────────────────────────────────────

class Channel(Base):
    """채널 마스터 (§5.2). 채널 추가 = 이 테이블에 행 하나."""
    __tablename__ = "channel"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    group_name: Mapped[str] = mapped_column(String(20))          # 홈쇼핑/오픈마켓/소셜/라이브/해외/자사몰
    fee_base: Mapped[str] = mapped_column(String(10))            # PRICE | SUPPLY | PURCHASE
    ship_owner: Mapped[str] = mapped_column(String(20))          # SELF | CHANNEL_FULFILL | CONSIGNMENT
    settle_date_src: Mapped[str] = mapped_column(String(20))     # CONFIRM | PAYMENT | SHIP | SETTLE_ROUND
    vat_basis: Mapped[str] = mapped_column(String(10))           # EXCLUDED | INCLUDED
    status: Mapped[str] = mapped_column(String(10), default="WAITING")   # ACTIVE | WAITING | RETIRED
    sort_order: Mapped[int] = mapped_column(Integer, default=999)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)
    updated_at: Mapped[str] = mapped_column(String(25), default=_now, onupdate=_now)

    fees: Mapped[list["ChannelFee"]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    logistics: Mapped[list["ChannelLogistics"]] = relationship(back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','WAITING','RETIRED')", name="ck_channel_status"),
        CheckConstraint("fee_base IN ('PRICE','SUPPLY','PURCHASE')", name="ck_channel_feebase"),
        CheckConstraint("vat_basis IN ('EXCLUDED','INCLUDED')", name="ck_channel_vat"),
    )


class ChannelFee(Base):
    """수수료율 이력. 기간이 겹치면 안 된다 (§11.2 V4)."""
    __tablename__ = "channel_fee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    fee_rate: Mapped[float] = mapped_column(Float)               # 0.093
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(10))              # MEASURED | CONTRACT | ESTIMATE
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel: Mapped[Channel] = relationship(back_populates="fees")

    __table_args__ = (
        UniqueConstraint("channel_id", "effective_from", name="ux_fee_from"),
        CheckConstraint("fee_rate >= 0 AND fee_rate < 1", name="ck_fee_range"),
        CheckConstraint("source IN ('MEASURED','CONTRACT','ESTIMATE')", name="ck_fee_source"),
    )


class ChannelLogistics(Base):
    """물류비 모델 이력."""
    __tablename__ = "channel_logistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    model: Mapped[str] = mapped_column(String(20))               # FLAT | TABLE | CHANNEL_BEARS
    flat_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_estimate: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel: Mapped[Channel] = relationship(back_populates="logistics")

    __table_args__ = (
        UniqueConstraint("channel_id", "effective_from", name="ux_logi_from"),
        CheckConstraint("model IN ('FLAT','TABLE','CHANNEL_BEARS')", name="ck_logi_model"),
    )


class FileFormat(Base):
    """파일 포맷(파서) 마스터 — 채널 화면 개편 대비 버전 관리 (§5.2)."""
    __tablename__ = "file_format"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)     # 'GSSHOP_TXN_V1'
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channel.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    spec_yaml: Mapped[str] = mapped_column(Text)
    sniff_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)


class Sku(Base):
    """제품 마스터. 매입가는 sku_cost 로 분리 — 과거 손익 보존을 위해."""
    __tablename__ = "sku"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    spec: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)

    costs: Mapped[list["SkuCost"]] = relationship(back_populates="sku", cascade="all, delete-orphan")


class SkuCost(Base):
    """매입가 이력. 원가를 바꿔도 과거 월 손익이 소급 변형되지 않는다."""
    __tablename__ = "sku_cost"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("sku.id"))
    unit_cost: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    sku: Mapped[Sku] = relationship(back_populates="costs")

    __table_args__ = (
        UniqueConstraint("sku_id", "effective_from", name="ux_cost_from"),
        CheckConstraint("unit_cost >= 0", name="ck_cost_nonneg"),
    )


class Deal(Base):
    """딜 = 채널 × 구성 × 가격티어 × 기간.

    가격 변경 시 UPDATE 하지 않고 effective_to 를 마감한 뒤 새 행을 추가한다.
    """
    __tablename__ = "deal"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channel.id"), nullable=True)  # NULL=전 채널 공통
    primary_sku_id: Mapped[str] = mapped_column(ForeignKey("sku.id"))
    label: Mapped[str] = mapped_column(String(150))
    tier: Mapped[str] = mapped_column(String(10))                # NORMAL | EVENT | SPECIAL
    price: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)

    components: Mapped[list["DealComponent"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint("tier IN ('NORMAL','EVENT','SPECIAL')", name="ck_deal_tier"),
        CheckConstraint("price > 0", name="ck_deal_price"),
    )


class DealComponent(Base):
    """딜에 포함되는 SKU와 수량.

    단품 x2 도, 증정품 포함도, 3종 복합세트도 전부 이 테이블로 표현한다.
    증정품(is_gift=1)도 원가에는 포함된다 — 빼면 이익이 과대 계상된다.
    """
    __tablename__ = "deal_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deal.id", ondelete="CASCADE"))
    sku_id: Mapped[str] = mapped_column(ForeignKey("sku.id"))
    qty: Mapped[int] = mapped_column(Integer)
    is_gift: Mapped[int] = mapped_column(Integer, default=0)

    deal: Mapped[Deal] = relationship(back_populates="components")

    __table_args__ = (
        UniqueConstraint("deal_id", "sku_id", "is_gift", name="ux_component"),
        CheckConstraint("qty > 0", name="ck_component_qty"),
    )


class NameMapping(Base):
    """채널 상품명·옵션명 → 딜. 없으면 그 주문은 손익에서 빠진다."""
    __tablename__ = "name_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    raw_product_key: Mapped[str] = mapped_column(String(300))    # 정규화된 상품명
    raw_option_key: Mapped[str] = mapped_column(String(300), default="")
    deal_id: Mapped[str] = mapped_column(ForeignKey("deal.id"))
    match_type: Mapped[str] = mapped_column(String(20))          # EXACT | MANUAL | SUGGESTED_ACCEPTED
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)

    __table_args__ = (
        UniqueConstraint("channel_id", "raw_product_key", "raw_option_key", name="ux_mapping"),
    )


# ── 2·4. 원장 ────────────────────────────────────────────────────────────

class UploadBatch(Base):
    __tablename__ = "upload_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_type: Mapped[str] = mapped_column(String(10))         # WEEK | MONTH
    period_key: Mapped[str] = mapped_column(String(10))          # '2026-W30' | '2026-07'
    status: Mapped[str] = mapped_column(String(20), default="UPLOADING")
    uploaded_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)
    calculated_at: Mapped[str | None] = mapped_column(String(25), nullable=True)

    files: Mapped[list["UploadFile"]] = relationship(back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("period_type IN ('WEEK','MONTH')", name="ck_batch_ptype"),
    )


class UploadFile(Base):
    __tablename__ = "upload_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("upload_batch.id"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    format_id: Mapped[str | None] = mapped_column(ForeignKey("file_format.id"), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_sum: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PARSED")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)

    batch: Mapped[UploadBatch] = relationship(back_populates="files")

    __table_args__ = (
        UniqueConstraint("batch_id", "channel_id", name="ux_file_batch_channel"),
        Index("ix_upload_file_sha", "sha256"),
    )


class FileReject(Base):
    """검증 실패 파일 격리 (§7.6). 원본은 버리지 않는다."""
    __tablename__ = "file_reject"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("upload_batch.id"))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channel.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(30))
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[str | None] = mapped_column(String(25), nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)


class SalesLine(Base):
    """표준 판매원장 — 모든 집계의 단일 원천.

    계산 결과는 이 행에 스냅샷으로 저장한다. 마스터가 나중에 바뀌어도
    과거 손익은 변하지 않으며, 재계산은 명시적으로만 실행한다.
    """
    __tablename__ = "sales_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("upload_file.id", ondelete="CASCADE"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))

    # ① 원본
    order_no: Mapped[str] = mapped_column(String(60))
    order_line_no: Mapped[str] = mapped_column(String(20), default="")
    order_date: Mapped[str] = mapped_column(String(10))
    raw_product_name: Mapped[str] = mapped_column(String(300))
    raw_option_name: Mapped[str] = mapped_column(String(300), default="")
    qty: Mapped[int] = mapped_column(Integer)
    gross_amount: Mapped[int] = mapped_column(Integer)
    fee_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)
    shipping_charged: Mapped[int] = mapped_column(Integer, default=0)
    is_cancelled: Mapped[int] = mapped_column(Integer, default=0)

    # ② 기간 파생
    period_month: Mapped[str] = mapped_column(String(7))
    period_week: Mapped[str] = mapped_column(String(8))

    # ③ 매핑
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("deal.id"), nullable=True)
    map_status: Mapped[str] = mapped_column(String(12), default="UNMAPPED")
    map_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ④ 계산 스냅샷
    calc_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    net_revenue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    fee_rate_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    cogs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logistics_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logistics_estimated: Mapped[int] = mapped_column(Integer, default=0)
    own_discount: Mapped[int] = mapped_column(Integer, default=0)
    contribution_profit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    calculated_at: Mapped[str | None] = mapped_column(String(25), nullable=True)

    __table_args__ = (
        UniqueConstraint("file_id", "order_no", "order_line_no", "raw_option_name", name="ux_sl_order"),
        Index("ix_sl_period", "period_month", "channel_id"),
        Index("ix_sl_week", "period_week", "channel_id"),
        Index("ix_sl_deal", "deal_id", "period_month"),
        Index("ix_sl_map", "map_status"),
        CheckConstraint("qty > 0", name="ck_sl_qty"),
        CheckConstraint("map_status IN ('MAPPED','UNMAPPED','EXCLUDED')", name="ck_sl_map"),
    )


class ProfitMart(Base):
    """주차 × 채널 × 딜 사전 집계 (§5.4). 계산 완료 시 삭제 후 재삽입."""
    __tablename__ = "profit_mart"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_week: Mapped[str] = mapped_column(String(8))
    period_month: Mapped[str] = mapped_column(String(7))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    deal_id: Mapped[str] = mapped_column(ForeignKey("deal.id"))
    primary_sku_id: Mapped[str] = mapped_column(ForeignKey("sku.id"))
    tier: Mapped[str] = mapped_column(String(10))

    order_count: Mapped[int] = mapped_column(Integer)
    qty_sum: Mapped[int] = mapped_column(Integer)
    net_revenue: Mapped[int] = mapped_column(Integer)
    channel_fee: Mapped[int] = mapped_column(Integer)
    cogs: Mapped[int] = mapped_column(Integer)
    logistics_cost: Mapped[int] = mapped_column(Integer)
    own_discount: Mapped[int] = mapped_column(Integer, default=0)
    contribution_profit: Mapped[int] = mapped_column(Integer)
    margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence: Mapped[str] = mapped_column(String(10))
    calc_version: Mapped[str] = mapped_column(String(20))
    built_at: Mapped[str] = mapped_column(String(25), default=_now)

    __table_args__ = (
        UniqueConstraint("period_week", "channel_id", "deal_id", name="ux_pm"),
        Index("ix_pm_month", "period_month", "channel_id"),
        Index("ix_pm_sku", "period_month", "primary_sku_id"),
    )


class Reconciliation(Base):
    __tablename__ = "reconciliation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("upload_batch.id"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channel.id"))
    uploaded_sum: Mapped[int] = mapped_column(Integer)
    declared_sum: Mapped[int | None] = mapped_column(Integer, nullable=True)
    declared_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculated_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    unmapped_sum: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="OK")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("batch_id", "channel_id", name="ux_recon"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(30))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(25), default=_now)
