"""Settlement mode as seen by the UI. Phase 3 adds live RPC/token verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rampscout.config import Settings


@dataclass(frozen=True)
class SettlementStatus:
    mode: Literal["testnet", "simulated"]
    reason: str
    chain_id: int
    network: str
    token_contract: str
    transfer_scale: str


def settlement_status(settings: Settings) -> SettlementStatus:
    missing = [
        name
        for name, value in (
            ("RPC_URL", settings.rpc_url),
            ("SIGNER_PRIVATE_KEY", settings.signer_private_key.get_secret_value()),
            ("ROUTE_A_SETTLEMENT_ADDRESS", settings.route_a_settlement_address),
            ("ROUTE_B_SETTLEMENT_ADDRESS", settings.route_b_settlement_address),
        )
        if not value
    ]
    if missing:
        mode: Literal["testnet", "simulated"] = "simulated"
        reason = f"Testnet execution disabled: {', '.join(missing)} not set"
    else:
        mode, reason = "testnet", "Configured for Base Sepolia (verified at execution time)"
    return SettlementStatus(
        mode=mode,
        reason=reason,
        chain_id=settings.expected_chain_id,
        network="Base Sepolia",
        token_contract=settings.usdc_contract,
        transfer_scale=format(settings.demo_transfer_scale, "f"),
    )
