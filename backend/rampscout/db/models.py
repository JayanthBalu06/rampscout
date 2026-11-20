"""SQLAlchemy models. All timestamps are timestamptz in UTC; money is NUMERIC."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rampscout.db.session import Base

USDC = Numeric(20, 6)
MXN = Numeric(20, 2)
RATE = Numeric(20, 6)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class DemoSession(Base):
    """One browser/demo run: owns a fixture clock and chaos toggles."""

    __tablename__ = "demo_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    clock_now: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tick: Mapped[int] = mapped_column(Integer, default=0)
    chaos_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Destination(Base):
    """A saved payout destination. The alias maps to server-configured route recipients;
    no client-supplied blockchain address is ever stored or used for signing."""

    __tablename__ = "destinations"
    __table_args__ = (UniqueConstraint("owner_id", "alias"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    alias: Mapped[str] = mapped_column(String(80))
    bank_name: Mapped[str] = mapped_column(String(80))
    masked_account: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    rail: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteSnapshot(Base):
    """Every quote we fetched, eligible or not, for audit and for re-validating a
    quote id the user selected."""

    __tablename__ = "quote_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(String(64), unique=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    provider_id: Mapped[str] = mapped_column(String(32))
    route_id: Mapped[str] = mapped_column(String(8))
    route_name: Mapped[str] = mapped_column(String(80))
    input_usdc: Mapped[Decimal] = mapped_column(USDC)
    rate_mxn_per_usdc: Mapped[Decimal] = mapped_column(RATE)
    usdc_fee: Mapped[Decimal] = mapped_column(USDC)
    gas_cost_usdc: Mapped[Decimal] = mapped_column(USDC)
    mxn_withdrawal_fee: Mapped[Decimal] = mapped_column(MXN)
    net_mxn: Mapped[Decimal] = mapped_column(MXN)
    eta_seconds: Mapped[int] = mapped_column(Integer)
    supported_rails: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    destination_rail: Mapped[str] = mapped_column(String(32))
    excluded_reasons: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    source: Mapped[str] = mapped_column(String(16))
    tick: Mapped[int] = mapped_column(Integer)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
