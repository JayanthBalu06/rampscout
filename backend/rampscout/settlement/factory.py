from __future__ import annotations

from rampscout.config import Settings
from rampscout.settlement.chain_settler import ChainSettler
from rampscout.settlement.sim_chain import SIM_ROUTE_RECIPIENTS, SIM_TOKEN, SimulatedChain
from rampscout.settlement.status import missing_config, settlement_status


def simulated_settler(settings: Settings, chain: SimulatedChain | None = None) -> ChainSettler:
    return ChainSettler(
        settings,
        chain or SimulatedChain(),
        mode="simulated",
        token_address=SIM_TOKEN,
        recipients=dict(SIM_ROUTE_RECIPIENTS),
    )


def testnet_settler(settings: Settings) -> ChainSettler:
    from rampscout.settlement.web3_chain import Web3Chain

    return ChainSettler(
        settings,
        Web3Chain(settings),
        mode="testnet",
        token_address=settings.usdc_contract,
        recipients={
            "A": settings.route_a_settlement_address,
            "B": settings.route_b_settlement_address,
        },
        receipt_wait_seconds=settings.receipt_wait_seconds,
    )


def get_settler(settings: Settings) -> ChainSettler:
    """Testnet only when every live check passes; otherwise the labeled simulated ledger."""
    if settlement_status(settings).mode == "testnet":
        return testnet_settler(settings)
    return simulated_settler(settings)


def settler_for_mode(settings: Settings, mode: str) -> ChainSettler | None:
    """Reconciliation must continue on the chain an execution started on, even if live
    verification is failing right now (it only reads receipts and resends signed bytes)."""
    if mode == "simulated":
        return simulated_settler(settings)
    if not missing_config(settings):
        return testnet_settler(settings)
    return None
