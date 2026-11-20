from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from rampscout.domain.pricing import compute_payout
from rampscout.domain.quotes import Quote
from rampscout.providers.fixture import MX_SPEI

NOW = datetime(2026, 11, 27, 17, 0, tzinfo=UTC)


def make_quote(
    route_id: str = "X",
    *,
    rate: str = "16.80",
    usdc_fee: str = "1",
    mxn_fee: str = "40",
    amount: str = "600",
    eta_min: int = 10,
    ttl_s: int = 120,
    rails: frozenset[str] = frozenset({MX_SPEI}),
    now: datetime = NOW,
) -> Quote:
    return Quote(
        quote_id=f"q_{uuid.uuid4().hex[:8]}",
        provider_id=f"test-{route_id.lower()}",
        route_id=route_id,
        route_name=f"Route {route_id}",
        breakdown=compute_payout(
            input_usdc=Decimal(amount),
            rate_mxn_per_usdc=Decimal(rate),
            usdc_fee=Decimal(usdc_fee),
            mxn_withdrawal_fee=Decimal(mxn_fee),
        ),
        supported_rails=rails,
        eta=timedelta(minutes=eta_min),
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_s),
    )
