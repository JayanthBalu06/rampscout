"""Domain -> wire conversions."""

from __future__ import annotations

from datetime import datetime

from rampscout.api.schemas import (
    ClockOut,
    DestinationOut,
    ExcludedOut,
    FeeBreakdownOut,
    ProviderErrorOut,
    QuoteOut,
    SettlementOut,
)
from rampscout.config import Settings
from rampscout.db.models import DemoSession, Destination
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
