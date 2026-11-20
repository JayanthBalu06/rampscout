"""Simulated settlement: used when no testnet signer/RPC is configured.

Every artifact it produces is labeled simulated; it never claims an onchain transfer.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import select

from rampscout.agent.clocks import clock_for_auth
from rampscout.agent.events import record
from rampscout.config import Settings
from rampscout.db.models import Authorization, Execution
from rampscout.db.session import SessionLocal
from rampscout.domain.money import fmt_mxn, fmt_usdc


class SimulatedSettler:
    mode = "simulated"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def preflight(self, route_id: str, onchain_amount_usdc: Decimal) -> list[str]:
        if onchain_amount_usdc <= 0:
            return ["transfer amount rounds to zero"]
        return []

    def settle(self, execution_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            ex = db.scalars(
                select(Execution).where(Execution.id == execution_id).with_for_update()
            ).one()
            auth = db.scalars(
                select(Authorization)
                .where(Authorization.id == ex.authorization_id)
                .with_for_update()
            ).one()
            now = clock_for_auth(db, auth, self.settings).now()
            if ex.chain_status == "not_started":
                ex.tx_hash = "0x" + hashlib.sha256(f"sim:{ex.id}".encode()).hexdigest()
                ex.chain_status = "confirmed"
                record(
                    db,
                    auth,
                    now,
                    "transfer_simulated",
                    f"Simulated transfer of {fmt_usdc(ex.onchain_amount_usdc)} to Route "
                    f"{ex.route_id}'s settlement wallet (no testnet signer configured).",
                )
            if ex.chain_status == "confirmed" and ex.payout_status != "posted":
                ex.payout_attempts += 1
                ex.payout_status = "posted"
                ex.payout_mxn = ex.quoted_net_mxn
                ex.payout_reference = f"SIM-SPEI-{str(ex.id)[:8].upper()}"
                auth.status = "completed"
                auth.closed_at = now
                auth.version += 1
                auth.last_reason = (
                    f"Completed: simulated payout of {fmt_mxn(ex.payout_mxn)} posted to the "
                    f"bank after a simulated {fmt_usdc(ex.onchain_amount_usdc)} transfer."
                )
                record(
                    db,
                    auth,
                    now,
                    "payout_posted",
                    f"Simulated SPEI deposit of {fmt_mxn(ex.payout_mxn)} posted "
                    f"(ref {ex.payout_reference}).",
                )
            db.commit()
