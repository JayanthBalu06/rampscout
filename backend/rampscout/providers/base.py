from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from rampscout.domain.quotes import Quote


@dataclass(frozen=True)
class QuoteRequest:
    amount_usdc: Decimal
    destination_rail: str
    now: datetime
    tick: int


class ProviderUnavailable(Exception):
    """The provider answered, but cannot quote right now (maintenance, outage, ...)."""


class QuoteProvider(Protocol):
    provider_id: str
    route_id: str
    route_name: str

    async def get_quote(self, req: QuoteRequest) -> Quote: ...
