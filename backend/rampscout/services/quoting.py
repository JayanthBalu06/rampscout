"""Quote comparison: fetch -> snapshot -> filter -> rank. Used by the API and the worker."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from rampscout.config import Settings
from rampscout.db.models import QuoteSnapshot
from rampscout.domain.clock import Clock
from rampscout.domain.eligibility import Constraints, Exclusion, partition, rank
from rampscout.domain.quotes import Quote
from rampscout.providers.base import QuoteProvider, QuoteRequest
from rampscout.providers.fixture import fixture_providers
from rampscout.providers.registry import ProviderError, fetch_all


@dataclass(frozen=True)
class Comparison:
    now: datetime
    tick: int
    ranked: list[Quote]
    excluded: list[Exclusion]
    errors: tuple[ProviderError, ...]

    @property
    def best(self) -> Quote | None:
        return self.ranked[0] if self.ranked else None


def providers_for(settings: Settings, chaos: dict[str, bool] | None) -> list[QuoteProvider]:
    return list(fixture_providers(timedelta(seconds=settings.quote_ttl_seconds), chaos))


def compare(
    *,
    db: Session,
    session_id: uuid.UUID,
    settings: Settings,
    clock: Clock,
    amount_usdc: Decimal,
    destination_rail: str,
    deadline: datetime | None,
    providers: Sequence[QuoteProvider],
    authorization_id: uuid.UUID | None = None,
) -> Comparison:
    now = clock.now()
    req = QuoteRequest(
        amount_usdc=amount_usdc, destination_rail=destination_rail, now=now, tick=clock.tick
    )
    result = asyncio.run(fetch_all(providers, req, settings.provider_timeout_ms / 1000))
    constraints = Constraints(
        budget_usdc=amount_usdc,
        destination_rail=destination_rail,
        deadline=deadline,
        safety_margin=timedelta(seconds=settings.safety_margin_seconds),
    )
    eligible, excluded = partition(result.quotes, constraints, now)
    reasons = {e.quote.quote_id: [r.value for r in e.reasons] for e in excluded}
    for q in result.quotes:
        db.add(snapshot_row(q, session_id, clock.tick, destination_rail, reasons, authorization_id))
    db.flush()
    return Comparison(
        now=now, tick=clock.tick, ranked=rank(eligible), excluded=excluded, errors=result.errors
    )


def snapshot_row(
    q: Quote,
    session_id: uuid.UUID,
    tick: int,
    destination_rail: str,
    reasons: dict[str, list[str]],
    authorization_id: uuid.UUID | None,
) -> QuoteSnapshot:
    b = q.breakdown
    return QuoteSnapshot(
        quote_id=q.quote_id,
        session_id=session_id,
        authorization_id=authorization_id,
        provider_id=q.provider_id,
        route_id=q.route_id,
        route_name=q.route_name,
        input_usdc=b.input_usdc,
        rate_mxn_per_usdc=b.rate_mxn_per_usdc,
        usdc_fee=b.usdc_fee,
        gas_cost_usdc=b.gas_cost_usdc,
        mxn_withdrawal_fee=b.mxn_withdrawal_fee,
        net_mxn=b.net_mxn,
        eta_seconds=int(q.eta.total_seconds()),
        supported_rails=sorted(q.supported_rails),
        destination_rail=destination_rail,
        excluded_reasons=reasons.get(q.quote_id, []),
        source=q.source,
        tick=tick,
        issued_at=q.issued_at,
        expires_at=q.expires_at,
    )


def snapshot_to_quote(s: QuoteSnapshot) -> Quote:
    """Rebuild a domain quote from its snapshot (recomputing the payout from stored terms)."""
    from rampscout.domain.pricing import compute_payout

    breakdown = compute_payout(
        input_usdc=s.input_usdc,
        rate_mxn_per_usdc=s.rate_mxn_per_usdc,
        usdc_fee=s.usdc_fee,
        mxn_withdrawal_fee=s.mxn_withdrawal_fee,
        gas_cost_usdc=s.gas_cost_usdc,
    )
    if breakdown.net_mxn != s.net_mxn:
        raise ValueError(f"snapshot {s.quote_id} payout does not reproduce")
    return Quote(
        quote_id=s.quote_id,
        provider_id=s.provider_id,
        route_id=s.route_id,
        route_name=s.route_name,
        breakdown=breakdown,
        supported_rails=frozenset(s.supported_rails),
        eta=timedelta(seconds=s.eta_seconds),
        issued_at=s.issued_at,
        expires_at=s.expires_at,
        source=s.source,
    )
