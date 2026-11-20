"""Simulated provider payout (fee deduction, MXN conversion, SPEI deposit).

Idempotent by execution id: the reference is derived from it, so a retry can never
create a second payout."""

from __future__ import annotations

from sqlalchemy.orm import Session

from rampscout.db.models import DemoSession, Execution


class PayoutFailed(Exception):
    pass


def payout_reference(ex: Execution) -> str:
    return f"SIM-SPEI-{str(ex.id).replace('-', '')[:10].upper()}"


def post_simulated_payout(db: Session, ex: Execution, session: DemoSession) -> str:
    flags = dict(session.chaos_flags or {})
    if flags.pop("fail_next_payout", False):
        session.chaos_flags = flags  # one-shot: the next attempt succeeds
        raise PayoutFailed("simulated provider error: SPEI gateway unavailable")
    return payout_reference(ex)
