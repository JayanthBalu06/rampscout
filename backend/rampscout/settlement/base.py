from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal
from typing import Protocol

from rampscout.config import Settings
from rampscout.domain.pricing import USDC_QUANTUM


class Settler(Protocol):
    mode: str  # "testnet" | "simulated"

    def preflight(self, route_id: str, onchain_amount_usdc: Decimal) -> list[str]:
        """Settlement-side checks run during revalidation, before an execution exists."""
        ...

    def settle(self, execution_id: uuid.UUID) -> None:
        """Drive an execution forward. Must be safe to call repeatedly (idempotent)."""
        ...


def onchain_amount(input_usdc: Decimal, settings: Settings) -> Decimal:
    """Authorized USDC x DEMO_TRANSFER_SCALE (1:100 by default), floored to USDC precision."""
    return (input_usdc * settings.demo_transfer_scale).quantize(USDC_QUANTUM, rounding=ROUND_DOWN)
