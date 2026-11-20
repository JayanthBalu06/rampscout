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
    LargeBinary,
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


class Authorization(Base):
    """User-confirmed terms. The only thing that grants the agent authority to act."""

    __tablename__ = "authorizations"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    terms_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))  # immediate | notify | auto
    status: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    input_usdc: Mapped[Decimal] = mapped_column(USDC)
    min_payout_mxn: Mapped[Decimal | None] = mapped_column(MXN)
    destination_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("destinations.id"))
    # Send flow (mode="send"): pay a saved contact via the best route.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    out_currency: Mapped[str | None] = mapped_column(String(8))
    min_out: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    route_quote_id: Mapped[str | None] = mapped_column(String(64))
    deadline_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_tz: Mapped[str] = mapped_column(String(64))
    selected_quote_id: Mapped[str | None] = mapped_column(String(64))
    intent_text: Mapped[str | None] = mapped_column(Text)

    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reason: Mapped[str | None] = mapped_column(Text)
    last_best_route: Mapped[str | None] = mapped_column(String(8))
    last_best_net_mxn: Mapped[Decimal | None] = mapped_column(MXN)
    event_count: Mapped[int] = mapped_column(Integer, default=0)

    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # demo clock
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecisionEvent(Base):
    """Append-only, ordered audit log of everything the agent decided and why."""

    __tablename__ = "decision_events"
    __table_args__ = (UniqueConstraint("authorization_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authorizations.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # demo/system clock time
    kind: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    best_quote_id: Mapped[str | None] = mapped_column(String(64))
    best_route: Mapped[str | None] = mapped_column(String(8))
    best_net_mxn: Mapped[Decimal | None] = mapped_column(MXN)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("authorization_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authorizations.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Execution(Base):
    """Exactly one per authorization (UNIQUE) - the database-level double-pay guard.

    signed_tx is never serialized to the API or logs."""

    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authorizations.id", ondelete="CASCADE"), unique=True
    )
    quote_id: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str] = mapped_column(String(64))
    input_usdc: Mapped[Decimal] = mapped_column(USDC)
    quoted_net_mxn: Mapped[Decimal | None] = mapped_column(MXN)
    # Generic (any currency) quoted/delivered amounts, used by the send flow.
    out_currency: Mapped[str | None] = mapped_column(String(8))
    quoted_out: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    delivered_out: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    recipient_label: Mapped[str | None] = mapped_column(String(120))
    onchain_amount_usdc: Mapped[Decimal] = mapped_column(USDC)
    settlement_mode: Mapped[str] = mapped_column(String(16))  # testnet | simulated
    recipient_address: Mapped[str | None] = mapped_column(String(42))
    chain_id: Mapped[int | None] = mapped_column(Integer)
    token_contract: Mapped[str | None] = mapped_column(String(42))
    signer_address: Mapped[str | None] = mapped_column(String(42))
    nonce: Mapped[int | None] = mapped_column(Integer)
    signed_tx: Mapped[bytes | None] = mapped_column(LargeBinary)
    tx_hash: Mapped[str | None] = mapped_column(String(66), unique=True)
    # not_started | prepared | broadcast | unknown | confirmed | reverted
    chain_status: Mapped[str] = mapped_column(String(16), default="not_started")
    broadcast_attempts: Mapped[int] = mapped_column(Integer, default=0)
    block_number: Mapped[int | None] = mapped_column(Integer)
    # not_started | pending | posted | failed
    payout_status: Mapped[str] = mapped_column(String(16), default="not_started")
    payout_mxn: Mapped[Decimal | None] = mapped_column(MXN)
    payout_reference: Mapped[str | None] = mapped_column(String(64))
    payout_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SimChainTx(Base):
    """Local simulated ledger used when no testnet signer is configured. It mimics a
    node: signed bytes exist before broadcast, broadcast may be lost, receipts by hash."""

    __tablename__ = "sim_chain_txs"

    tx_hash: Mapped[str] = mapped_column(String(66), primary_key=True)
    raw: Mapped[bytes] = mapped_column(LargeBinary)
    signer: Mapped[str] = mapped_column(String(42), index=True)
    token: Mapped[str] = mapped_column(String(42))
    recipient: Mapped[str] = mapped_column(String(42))
    amount_units: Mapped[Decimal] = mapped_column(Numeric(78, 0))
    nonce: Mapped[int] = mapped_column(Integer)
    received: Mapped[bool] = mapped_column(default=False)  # in the "mempool"
    block_number: Mapped[int | None] = mapped_column(Integer)
    send_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """A saved recipient. Wallet addresses and bank accounts are entered once, reviewed and
    confirmed by the user; sends can only target confirmed contacts, by id."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))  # bank | wallet
    currency: Mapped[str] = mapped_column(String(8))  # what they receive
    country: Mapped[str | None] = mapped_column(String(2))
    bank_name: Mapped[str | None] = mapped_column(String(80))
    account_masked: Mapped[str | None] = mapped_column(String(40))
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouteQuote(Base):
    """A priced multi-hop route, as shown to the user (and re-priced before execution)."""

    __tablename__ = "route_quotes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    amount_in: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    from_ccy: Mapped[str] = mapped_column(String(8))
    amount_out: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    to_ccy: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(120))
    leg_ids: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    hops: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    rank: Mapped[int] = mapped_column(Integer)
    eta_seconds: Mapped[int] = mapped_column(Integer)
    market_source: Mapped[str] = mapped_column(String(12))
    market_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
