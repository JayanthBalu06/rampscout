from __future__ import annotations

from rampscout.config import Settings
from rampscout.settlement.base import Settler
from rampscout.settlement.simulated import SimulatedSettler


def get_settler(settings: Settings) -> Settler:
    """Phase 3 returns the Base Sepolia settler when configured."""
    return SimulatedSettler(settings)
