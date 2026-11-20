"""Domain -> wire conversions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rampscout.api.schemas import (
    AuthorizationOut,
    ClockOut,
    DestinationOut,
    ExcludedOut,
    FeeBreakdownOut,
    ProviderErrorOut,
    QuoteOut,
    SettlementOut,
)
from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession, Destination
from rampscout.demo import DEMO_DISPLAY_TZ
from rampscout.domain.eligibility import Exclusion
from rampscout.domain.quotes import Quote
from rampscout.providers.registry import ProviderError
from rampscout.settlement.status import settlement_status


def quote_out(q: Quote, now: datetime, rank: int | None) -> QuoteOut:
    b = q.breakdown
    return QuoteOut(
        quote_id=q.quote_id,
        provider_id=q.provider_id,
        route_id=q.route_id,
        route_name=q.route_name,
        rank=rank,
        net_mxn=b.net_mxn,
        breakdown=FeeBreakdownOut(
            input_usdc=b.input_usdc,
            usdc_fee=b.usdc_fee,
            gas_cost_usdc=b.gas_cost_usdc,
            gas_sponsored=True,
            usdc_converted=b.usdc_converted,
            rate_mxn_per_usdc=b.rate_mxn_per_usdc,
            gross_mxn=b.gross_mxn,
            mxn_withdrawal_fee=b.mxn_withdrawal_fee,
            net_mxn=b.net_mxn,
        ),
        eta_seconds=int(q.eta.total_seconds()),
        estimated_arrival=q.arrival_at(now),
        issued_at=q.issued_at,
        expires_at=q.expires_at,
        source=q.source,
    )


def excluded_out(e: Exclusion, now: datetime) -> ExcludedOut:
    return ExcludedOut(
        quote=quote_out(e.quote, now, None), reasons=[r.value for r in e.reasons], detail=e.detail
    )


def error_out(e: ProviderError) -> ProviderErrorOut:
    return ProviderErrorOut(
        provider_id=e.provider_id, route_id=e.route_id, kind=e.kind, message=e.message
    )


def destination_out(d: Destination) -> DestinationOut:
    return DestinationOut(
        id=d.id,
        alias=d.alias,
        bank_name=d.bank_name,
        masked_account=d.masked_account,
        currency=d.currency,
        rail=d.rail,
    )


def clock_out(s: DemoSession) -> ClockOut:
    return ClockOut(now=s.clock_now, tick=s.tick, display_tz=DEMO_DISPLAY_TZ, mode="fixture")


def settlement_out(settings: Settings) -> SettlementOut:
    st = settlement_status(settings)
    return SettlementOut(
        mode=st.mode,
        reason=st.reason,
        chain_id=st.chain_id,
        network=st.network,
        token_contract=st.token_contract,
        transfer_scale=st.transfer_scale,
    )


def rate_vs_payout_insight(quotes: list[Quote]) -> str | None:
    """Explain the core story when the highest headline rate is not the best payout."""
    if len(quotes) < 2:
        return None
    best = quotes[0]
    top_rate = max(quotes, key=lambda q: (q.breakdown.rate_mxn_per_usdc, -q.net_mxn))
    if top_rate is best or top_rate.breakdown.rate_mxn_per_usdc <= best.breakdown.rate_mxn_per_usdc:
        return None
    gap = best.net_mxn - top_rate.net_mxn
    return (
        f"Route {top_rate.route_id} has the higher rate "
        f"({top_rate.breakdown.rate_mxn_per_usdc} vs {best.breakdown.rate_mxn_per_usdc} MXN/USDC) "
        f"but delivers {gap} MXN less after fees."
    )


def authorization_out(db: Session, auth: Authorization, settings: Settings) -> AuthorizationOut:
    from sqlalchemy import select

    from rampscout.agent.intent import format_deadline
    from rampscout.api.schemas import EventOut, ExecutionOut, TermsOut
    from rampscout.db.models import DecisionEvent, Execution, QuoteSnapshot
    from rampscout.services.quoting import snapshot_to_quote

    dest = db.get(Destination, auth.destination_id)
    session = db.get(DemoSession, auth.session_id)
    assert dest is not None and session is not None
    events = db.scalars(
        select(DecisionEvent)
        .where(DecisionEvent.authorization_id == auth.id)
        .order_by(DecisionEvent.seq)
    ).all()
    ex = db.scalars(select(Execution).where(Execution.authorization_id == auth.id)).one_or_none()
    executed_quote = None
    execution = None
    if ex is not None:
        snap = db.scalars(
            select(QuoteSnapshot).where(QuoteSnapshot.quote_id == ex.quote_id)
        ).one_or_none()
        if snap is not None:
            executed_quote = quote_out(snapshot_to_quote(snap), snap.issued_at, None)
        execution = ExecutionOut(
            id=ex.id,
            quote_id=ex.quote_id,
            route_id=ex.route_id,
            input_usdc=ex.input_usdc,
            quoted_net_mxn=ex.quoted_net_mxn,
            onchain_amount_usdc=ex.onchain_amount_usdc,
            transfer_scale=format(settings.demo_transfer_scale, "f"),
            settlement_mode=ex.settlement_mode,
            chain_id=ex.chain_id,
            token_contract=ex.token_contract,
            recipient_address=ex.recipient_address,
            chain_status=ex.chain_status,
            tx_hash=ex.tx_hash,
            explorer_url=(
                settings.explorer_tx_url + ex.tx_hash
                if ex.tx_hash and ex.settlement_mode == "testnet"
                else None
            ),
            block_number=ex.block_number,
            payout_status=ex.payout_status,
            payout_mxn=ex.payout_mxn,
            payout_reference=ex.payout_reference,
            state_label=execution_state_label(ex.chain_status, ex.payout_status),
        )
    return AuthorizationOut(
        id=auth.id,
        mode=auth.mode,
        status=auth.status,
        version=auth.version,
        can_cancel=auth.status == "watching",
        terms=TermsOut(
            amount_usdc=auth.input_usdc,
            currency="USDC",
            min_payout_mxn=auth.min_payout_mxn,
            destination=destination_out(dest),
            deadline_utc=auth.deadline_utc,
            deadline_display=(
                format_deadline(auth.deadline_utc, auth.display_tz) if auth.deadline_utc else None
            ),
            time_zone=auth.display_tz,
            selected_quote_id=auth.selected_quote_id,
        ),
        intent_text=auth.intent_text,
        confirmed_at=auth.confirmed_at,
        closed_at=auth.closed_at,
        last_check_at=auth.last_check_at,
        next_check_at=auth.next_check_at,
        last_reason=auth.last_reason,
        last_best_route=auth.last_best_route,
        last_best_net_mxn=auth.last_best_net_mxn,
        events=[
            EventOut(
                seq=e.seq,
                at=e.at,
                kind=e.kind,
                reason=e.reason,
                best_quote_id=e.best_quote_id,
                best_route=e.best_route,
                best_net_mxn=e.best_net_mxn,
                payload=e.payload or {},
            )
            for e in events
        ],
        execution=execution,
        executed_quote=executed_quote,
        clock=clock_out(session),
    )


def execution_state_label(chain_status: str, payout_status: str) -> str:
    if chain_status == "confirmed" and payout_status == "posted":
        return "completed"
    if chain_status == "confirmed":
        return "transfer confirmed / payout pending"
    if chain_status in ("prepared", "broadcast", "unknown"):
        return "transfer pending verification"
    if chain_status == "reverted":
        return "transfer failed onchain"
    return "not started"
