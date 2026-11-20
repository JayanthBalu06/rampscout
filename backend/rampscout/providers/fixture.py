"""Synthetic providers that follow a deterministic per-tick script.

Every call returns a *fresh* quote id and expiry, like a real RFQ endpoint would.
Chaos behaviours ("down", "timeout") let tests and the demo exercise failure paths.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from rampscout.domain.pricing import compute_payout
from rampscout.domain.quotes import Quote
from rampscout.providers.base import ProviderUnavailable, QuoteRequest

Behavior = Literal["ok", "down", "timeout"]
MX_SPEI = "mx_spei"


@dataclass(frozen=True)
class Terms:
    rate_mxn_per_usdc: Decimal
    usdc_fee: Decimal
    mxn_withdrawal_fee: Decimal
    eta: timedelta


class FixtureProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        route_id: str,
        route_name: str,
        script: dict[int, Terms],
        supported_rails: frozenset[str],
        ttl: timedelta,
        behavior: Behavior = "ok",
    ) -> None:
        if 0 not in script:
            raise ValueError("script must define tick 0")
        self.provider_id = provider_id
        self.route_id = route_id
        self.route_name = route_name
        self._script = script
        self._rails = supported_rails
        self._ttl = ttl
        self._behavior = behavior

    def terms_at(self, tick: int) -> Terms:
        """Latest scripted terms at or before `tick` (terms persist until changed)."""
        return self._script[max(t for t in self._script if t <= tick)]

    async def get_quote(self, req: QuoteRequest) -> Quote:
        if self._behavior == "down":
            raise ProviderUnavailable(f"{self.route_name} is not accepting quotes")
        if self._behavior == "timeout":
            await asyncio.sleep(3600)  # caller's timeout fires first
        terms = self.terms_at(req.tick)
        breakdown = compute_payout(
            input_usdc=req.amount_usdc,
            rate_mxn_per_usdc=terms.rate_mxn_per_usdc,
            usdc_fee=terms.usdc_fee,
            mxn_withdrawal_fee=terms.mxn_withdrawal_fee,
        )
        return Quote(
            quote_id=f"q_{self.route_id.lower()}_{uuid.uuid4().hex[:16]}",
            provider_id=self.provider_id,
            route_id=self.route_id,
            route_name=self.route_name,
            breakdown=breakdown,
            supported_rails=self._rails,
            eta=terms.eta,
            issued_at=req.now,
            expires_at=req.now + self._ttl,
            source="fixture",
        )


# The reproducible hackathon scenario (docs/SPEC.md section 3.2).
ROUTE_A_SCRIPT = {
    0: Terms(Decimal("16.85"), Decimal("2"), Decimal("100"), timedelta(minutes=20)),
}
ROUTE_B_SCRIPT = {
    0: Terms(Decimal("16.75"), Decimal("1"), Decimal("40"), timedelta(minutes=10)),
    1: Terms(Decimal("16.80"), Decimal("1"), Decimal("40"), timedelta(minutes=10)),
}


def fixture_providers(
    ttl: timedelta, chaos: dict[str, bool] | None = None
) -> list[FixtureProvider]:
    chaos = chaos or {}

    def behavior(route: str) -> Behavior:
        if chaos.get(f"provider_{route}_down"):
            return "down"
        if chaos.get(f"provider_{route}_timeout"):
            return "timeout"
        return "ok"

    return [
        FixtureProvider(
            provider_id="fixture-a",
            route_id="A",
            route_name="Route A · high rate, high fees",
            script=ROUTE_A_SCRIPT,
            supported_rails=frozenset({MX_SPEI}),
            ttl=ttl,
            behavior=behavior("a"),
        ),
        FixtureProvider(
            provider_id="fixture-b",
            route_id="B",
            route_name="Route B · lean fees, fast",
            script=ROUTE_B_SCRIPT,
            supported_rails=frozenset({MX_SPEI}),
            ttl=ttl,
            behavior=behavior("b"),
        ),
    ]
