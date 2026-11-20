"""Which settlement mode is live, and why. Testnet requires every check to pass."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import structlog
from sqlalchemy import func, select
from web3 import Web3

from rampscout.config import Settings

log = structlog.get_logger()

Mode = Literal["testnet", "simulated"]
_CACHE: dict[str, tuple[float, SettlementStatus]] = {}
_TTL = 60.0


@dataclass(frozen=True)
class SettlementStatus:
    mode: Mode
    reason: str
    chain_id: int
    network: str
    token_contract: str
    transfer_scale: str
    signer_address: str | None = None
    signer_usdc: str | None = None
    signer_eth: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)


def _base(settings: Settings, mode: Mode, reason: str, **kw: object) -> SettlementStatus:
    return SettlementStatus(
        mode=mode,
        reason=reason,
        chain_id=settings.expected_chain_id,
        network="Base Sepolia" if mode == "testnet" else "local simulated ledger",
        token_contract=settings.usdc_contract,
        transfer_scale=format(settings.demo_transfer_scale, "f"),
        **kw,  # type: ignore[arg-type]
    )


def missing_config(settings: Settings) -> list[str]:
    return [
        name
        for name, value in (
            ("RPC_URL", settings.rpc_url),
            ("SIGNER_PRIVATE_KEY", settings.signer_private_key.get_secret_value()),
            ("ROUTE_A_SETTLEMENT_ADDRESS", settings.route_a_settlement_address),
            ("ROUTE_B_SETTLEMENT_ADDRESS", settings.route_b_settlement_address),
        )
        if not value
    ]


def verify_testnet(settings: Settings) -> SettlementStatus:
    """Live checks against the RPC. Any failure disables testnet execution with a reason."""
    from rampscout.settlement.web3_chain import Web3Chain

    missing = missing_config(settings)
    if missing:
        return _base(
            settings, "simulated", f"Testnet execution disabled: {', '.join(missing)} not set"
        )
    checks: dict[str, bool] = {}
    try:
        chain = Web3Chain(settings)
    except Exception:
        return _base(
            settings, "simulated", "Testnet execution disabled: invalid SIGNER_PRIVATE_KEY"
        )
    signer = chain.signer_address
    problems: list[str] = []
    checks["signer_matches"] = (
        not settings.signer_address
        or Web3.is_address(settings.signer_address)
        and settings.signer_address.lower() == signer.lower()
    )
    if not checks["signer_matches"]:
        problems.append("SIGNER_ADDRESS does not match the key")
    for route, addr in (
        ("A", settings.route_a_settlement_address),
        ("B", settings.route_b_settlement_address),
    ):
        ok = Web3.is_address(addr) and addr.lower() != signer.lower()
        checks[f"route_{route.lower()}_address"] = ok
        if not ok:
            problems.append(f"ROUTE_{route}_SETTLEMENT_ADDRESS is invalid or equals the signer")
    usdc = eth = None
    try:
        checks["chain_id"] = chain.chain_id() == settings.expected_chain_id
        if not checks["chain_id"]:
            problems.append(f"RPC chain id is not {settings.expected_chain_id}")
        code = chain.w3.eth.get_code(Web3.to_checksum_address(settings.usdc_contract))
        symbol, decimals = chain.token_info()
        checks["token"] = len(code) > 0 and symbol == "USDC" and decimals == 6
        if not checks["token"]:
            problems.append("USDC_CONTRACT is not a 6-decimal USDC token on this chain")
        bal = chain.token_balance(signer)
        native = chain.native_balance(signer)
        usdc = format(bal / 10**6, "f")
        eth = format(native / 10**18, ".6f")
        checks["gas"] = native > 0
        if native <= 0:
            problems.append("signer has no Base Sepolia ETH for gas")
        need = int(settings.min_signer_usdc * 10**6)
        checks["usdc_balance"] = bal >= need and bal > 0
        if not checks["usdc_balance"]:
            problems.append(
                f"signer holds {usdc} test USDC, below the {settings.min_signer_usdc} "
                "needed for a demo transfer (refill at faucet.circle.com)"
            )
    except Exception as exc:
        log.warning("settlement.verify_failed", error=type(exc).__name__)
        problems.append(f"RPC unreachable ({type(exc).__name__})")
    extra = {"signer_address": signer, "signer_usdc": usdc, "signer_eth": eth, "checks": checks}
    if problems:
        return _base(
            settings, "simulated", "Testnet execution disabled: " + "; ".join(problems), **extra
        )
    return _base(settings, "testnet", "Base Sepolia verified: chain, token and wallet OK", **extra)


def daily_cap_reached(settings: Settings) -> bool:
    from rampscout.db.models import Execution
    from rampscout.db.session import SessionLocal

    with SessionLocal() as db:
        n = db.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.settlement_mode == "testnet",
                Execution.created_at > func.now() - func.make_interval(0, 0, 0, 1),
            )
        )
    return int(n or 0) >= settings.daily_onchain_runs


def settlement_status(settings: Settings, *, fresh: bool = False) -> SettlementStatus:
    if missing_config(settings):
        return verify_testnet(settings)  # instant: no network needed
    key = f"{settings.rpc_url}|{settings.usdc_contract}|{settings.route_a_settlement_address}"
    hit = _CACHE.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < _TTL:
        status = hit[1]
    else:
        status = verify_testnet(settings)
        _CACHE[key] = (time.monotonic(), status)
    if status.mode == "testnet" and daily_cap_reached(settings):
        return _base(
            settings,
            "simulated",
            f"Daily testnet cap of {settings.daily_onchain_runs} transfers reached; "
            "using the simulated ledger until it resets",
            signer_address=status.signer_address,
            signer_usdc=status.signer_usdc,
            signer_eth=status.signer_eth,
            checks=status.checks,
        )
    return status
