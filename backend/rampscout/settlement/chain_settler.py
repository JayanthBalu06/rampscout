"""Settlement state machine. Same code for Base Sepolia and the local simulated ledger.

Guarantees (each covered by tests):
  * one execution row per authorization (DB unique) -> at most one payment
  * signing is serialized per wallet (advisory lock) and nonces never collide
  * the signed tx and its hash are committed *before* broadcast
  * an unknown broadcast outcome is resolved by querying the original hash or resending
    the identical bytes; it is never re-signed
  * a transfer counts only after a successful receipt with the exact Transfer log
  * transfer confirmed + payout failure -> retry the payout only, same execution id
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from rampscout.agent.clocks import clock_for_auth
from rampscout.agent.events import record
from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession, Execution
from rampscout.db.session import SessionLocal
from rampscout.domain.money import fmt_mxn, fmt_usdc
from rampscout.settlement.chain import (
    BroadcastRejected,
    BroadcastUnknown,
    ChainClient,
    Receipt,
    same_address,
)
from rampscout.settlement.payout import PayoutFailed, post_simulated_payout

log = structlog.get_logger()

PENDING_CHAIN = ("prepared", "broadcast", "unknown")
USDC_UNITS = Decimal(10**6)


def short(h: str | None) -> str:
    return f"{h[:10]}…{h[-6:]}" if h else "?"


class ChainSettler:
    def __init__(
        self,
        settings: Settings,
        chain: ChainClient,
        *,
        mode: str,
        token_address: str,
        recipients: dict[str, str],
        receipt_wait_seconds: float = 0.0,
    ) -> None:
        self.settings = settings
        self.chain = chain
        self.mode = mode
        self.token_address = token_address
        self.recipients = recipients
        self.receipt_wait_seconds = receipt_wait_seconds

    # ------------------------------------------------------------------ preflight

    def recipient_for(self, route_id: str) -> str | None:
        """Server-configured settlement wallet. Clients and the model cannot supply this."""
        return self.recipients.get(route_id)

    def preflight(self, route_id: str, onchain_amount_usdc: Decimal) -> list[str]:
        failures: list[str] = []
        recipient = self.recipient_for(route_id)
        if not recipient:
            failures.append(f"no settlement wallet configured for Route {route_id}")
        elif same_address(recipient, self.chain.signer_address):
            failures.append("route recipient equals the signer wallet")
        if onchain_amount_usdc <= 0:
            failures.append("transfer amount rounds to zero")
        if onchain_amount_usdc > self.settings.max_onchain_transfer_usdc:
            failures.append(
                f"transfer {fmt_usdc(onchain_amount_usdc)} exceeds the "
                f"{fmt_usdc(self.settings.max_onchain_transfer_usdc)} spending limit"
            )
        if failures:
            return failures
        try:
            units = int(onchain_amount_usdc * USDC_UNITS)
            if self.chain.token_balance(self.chain.signer_address) < units:
                failures.append("signer wallet has insufficient test USDC")
            if self.chain.native_balance(self.chain.signer_address) <= 0:
                failures.append("signer wallet has no ETH for gas")
        except Exception as exc:
            failures.append(f"could not read wallet balance ({type(exc).__name__})")
        return failures

    # ------------------------------------------------------------------ helpers

    def _lock(self, db: Session, execution_id: uuid.UUID) -> tuple[Execution, Authorization] | None:
        ex = db.scalars(
            select(Execution).where(Execution.id == execution_id).with_for_update(skip_locked=True)
        ).one_or_none()
        if ex is None:
            return None  # another process is driving this execution right now
        auth = db.scalars(
            select(Authorization).where(Authorization.id == ex.authorization_id).with_for_update()
        ).one()
        return ex, auth

    def _now(self, db: Session, auth: Authorization) -> datetime:
        return clock_for_auth(db, auth, self.settings).now()

    def _consume_chaos(self, db: Session, auth: Authorization, flag: str) -> bool:
        session = db.get(DemoSession, auth.session_id)
        flags = dict(session.chaos_flags or {}) if session else {}
        if not flags.pop(flag, False):
            return False
        assert session is not None
        session.chaos_flags = flags
        return True

    # ------------------------------------------------------------------ steps

    def settle(self, execution_id: uuid.UUID) -> None:
        """Drive an execution as far as it can safely go. Idempotent; call any time."""
        self._prepare(execution_id)
        waited = self._advance_chain(execution_id)
        if waited:
            self._await_receipt(execution_id)
        self._payout(execution_id)

    def _prepare(self, execution_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            locked = self._lock(db, execution_id)
            if locked is None:
                return
            ex, auth = locked
            if ex.chain_status != "not_started":
                return
            recipient = self.recipient_for(ex.route_id)
            if recipient is None:
                raise RuntimeError("preflight should have caught a missing recipient")
            signer = self.chain.signer_address
            # Serialize signing per wallet so two executions can't take the same nonce.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:a))"), {"a": signer.lower()})
            last = db.scalar(
                select(func.max(Execution.nonce)).where(
                    func.lower(Execution.signer_address) == signer.lower()
                )
            )
            nonce = max(self.chain.pending_nonce(signer), (last + 1) if last is not None else 0)
            units = int(ex.onchain_amount_usdc * USDC_UNITS)
            signed = self.chain.sign_transfer(nonce=nonce, to=recipient, amount_units=units)
            ex.signer_address = signer
            ex.recipient_address = recipient
            ex.token_contract = self.token_address
            ex.chain_id = self.chain.chain_id()
            ex.nonce = nonce
            ex.signed_tx = signed.raw
            ex.tx_hash = signed.tx_hash
            ex.chain_status = "prepared"
            record(
                db,
                auth,
                self._now(db, auth),
                "signed",
                f"Signed a {fmt_usdc(ex.onchain_amount_usdc)} transfer to Route {ex.route_id}'s "
                f"settlement wallet on {self.chain.label} (nonce {nonce}, "
                f"tx {short(signed.tx_hash)}). Saved before broadcast.",
            )
            db.commit()  # the hash is durable before any byte leaves this process

    def _send(self, db: Session, ex: Execution, auth: Authorization, *, resend: bool) -> None:
        now = self._now(db, auth)
        assert ex.signed_tx is not None
        ex.broadcast_attempts += 1
        try:
            self.chain.send_raw(ex.signed_tx)
            if self._consume_chaos(db, auth, "drop_broadcast_response"):
                raise BroadcastUnknown("demo chaos: broadcast response lost")
            ex.chain_status = "broadcast"
            record(
                db,
                auth,
                now,
                "rebroadcast" if resend else "broadcast",
                (
                    f"Node had no record of {short(ex.tx_hash)}; resent the identical signed bytes."
                    if resend
                    else f"Broadcast {short(ex.tx_hash)} to {self.chain.label}."
                ),
            )
        except BroadcastUnknown as exc:
            ex.chain_status = "unknown"
            ex.last_error = str(exc)
            record(
                db,
                auth,
                now,
                "broadcast_unknown",
                f"No response from the node ({exc}). Outcome unknown, so nothing will be "
                f"re-signed; the reconciler will query {short(ex.tx_hash)} or resend the "
                "same bytes.",
            )
        except BroadcastRejected as exc:
            ex.chain_status = "rejected"
            ex.last_error = str(exc)
            auth.status = "failed"
            auth.closed_at = now
            auth.version += 1
            auth.last_reason = f"The network rejected the transfer ({exc}). No funds moved."
            record(db, auth, now, "transfer_rejected", auth.last_reason)

    def _advance_chain(self, execution_id: uuid.UUID) -> bool:
        """Send, resend, or check a pending tx. Returns True if a receipt is worth awaiting."""
        with SessionLocal() as db:
            locked = self._lock(db, execution_id)
            if locked is None:
                return False
            ex, auth = locked
            if ex.chain_status == "prepared":
                self._send(db, ex, auth, resend=False)
            elif ex.chain_status in ("broadcast", "unknown"):
                assert ex.tx_hash is not None
                receipt = self.chain.get_receipt(ex.tx_hash)
                if receipt is not None:
                    self._apply_receipt(db, ex, auth, receipt, reconciled=True)
                elif ex.chain_status == "unknown" and not self.chain.is_known(ex.tx_hash):
                    self._send(db, ex, auth, resend=True)
            status = ex.chain_status
            db.commit()
            # After an unknown outcome we stop here: like a process that timed out, we
            # leave resolution to the reconciler instead of guessing.
            return status == "broadcast"

    def _await_receipt(self, execution_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            ex = db.get(Execution, execution_id)
            tx_hash = ex.tx_hash if ex else None
        if tx_hash is None:
            return
        deadline = time.monotonic() + self.receipt_wait_seconds
        receipt = self.chain.get_receipt(tx_hash)
        while receipt is None and time.monotonic() < deadline:
            time.sleep(1.5)
            try:
                receipt = self.chain.get_receipt(tx_hash)
            except Exception:
                receipt = None
        if receipt is None:
            return  # still pending; the reconciler will keep checking
        with SessionLocal() as db:
            locked = self._lock(db, execution_id)
            if locked is None:
                return
            ex, auth = locked
            if ex.chain_status in PENDING_CHAIN:
                self._apply_receipt(db, ex, auth, receipt, reconciled=False)
            db.commit()

    def _apply_receipt(
        self, db: Session, ex: Execution, auth: Authorization, receipt: Receipt, *, reconciled: bool
    ) -> None:
        now = self._now(db, auth)
        units = int(ex.onchain_amount_usdc * USDC_UNITS)
        if receipt.status != 1:
            ex.chain_status = "reverted"
            auth.status = "failed"
            auth.closed_at = now
            auth.version += 1
            auth.last_reason = f"Transfer {short(ex.tx_hash)} reverted onchain. No payout posted."
            record(db, auth, now, "transfer_reverted", auth.last_reason)
            return
        match = any(
            same_address(t.token, ex.token_contract or "")
            and same_address(t.sender, ex.signer_address or "")
            and same_address(t.recipient, ex.recipient_address or "")
            and t.value == units
            for t in receipt.transfers
        )
        if not match:
            ex.chain_status = "mismatch"
            auth.status = "failed"
            auth.closed_at = now
            auth.version += 1
            auth.last_reason = (
                f"Receipt for {short(ex.tx_hash)} lacks the expected USDC Transfer log. "
                "Held for review; no payout posted."
            )
            record(db, auth, now, "verification_failed", auth.last_reason)
            return
        ex.chain_status = "confirmed"
        ex.block_number = receipt.block_number
        record(
            db,
            auth,
            now,
            "transfer_confirmed",
            ("Reconciled by original hash: " if reconciled else "")
            + f"{fmt_usdc(ex.onchain_amount_usdc)} transfer verified in block "
            f"{receipt.block_number} (status 1, matching Transfer log).",
        )

    def _payout(self, execution_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            locked = self._lock(db, execution_id)
            if locked is None:
                return
            ex, auth = locked
            if ex.chain_status != "confirmed" or ex.payout_status == "posted":
                return
            now = self._now(db, auth)
            session = db.get(DemoSession, auth.session_id)
            assert session is not None
            ex.payout_attempts += 1
            try:
                ref = post_simulated_payout(db, ex, session)
            except PayoutFailed as exc:
                ex.payout_status = "pending"
                ex.last_error = str(exc)
                auth.status = "payout_pending"
                auth.last_reason = (
                    "Transfer confirmed / payout pending: the simulated provider failed "
                    f"({exc}). Retrying the payout only, same execution."
                )
                record(db, auth, now, "payout_failed", auth.last_reason)
                db.commit()
                return
            ex.payout_status = "posted"
            ex.payout_mxn = ex.quoted_net_mxn
            ex.payout_reference = ref
            auth.status = "completed"
            auth.closed_at = now
            auth.version += 1
            where = (
                f"verified on {self.chain.label}"
                if self.mode == "testnet"
                else f"settled on the {self.chain.label}"
            )
            auth.last_reason = (
                f"Completed: {fmt_usdc(ex.onchain_amount_usdc)} transfer {where}; "
                f"simulated SPEI payout of {fmt_mxn(ex.quoted_net_mxn)} posted."
            )
            record(
                db,
                auth,
                now,
                "payout_posted",
                f"Simulated SPEI deposit of {fmt_mxn(ex.quoted_net_mxn)} posted to the bank "
                f"(ref {ref}, attempt {ex.payout_attempts}).",
            )
            db.commit()
