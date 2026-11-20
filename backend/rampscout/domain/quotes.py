"""Comparable quote model shared by every provider adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from rampscout.domain.pricing import PayoutBreakdown


@dataclass(frozen=True)
class Quote:
    quote_id: str
    provider_id: str
    route_id: str
    route_name: str
    breakdown: PayoutBreakdown
    supported_rails: frozenset[str]
    eta: timedelta
    issued_at: datetime
    expires_at: datetime
    source: str = "fixture"

    @property
    def net_mxn(self) -> Decimal:
        return self.breakdown.net_mxn

    @property
    def input_usdc(self) -> Decimal:
        return self.breakdown.input_usdc

    def arrival_at(self, now: datetime) -> datetime:
        """Estimated bank arrival if executed at `now`."""
        return now + self.eta
