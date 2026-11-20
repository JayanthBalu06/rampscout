"""Crash recovery. Runs on worker start-up, every worker loop, and on /demo/advance.

Finds anything left mid-flight and drives it forward with the *same* idempotent steps:
  * claimed authorizations with no execution -> revalidate and execute (or release)
  * executions never signed whose quote expired -> void and release the claim
  * prepared / broadcast / unknown txs -> query the original hash, or resend identical bytes
  * confirmed transfers whose payout is pending -> retry the payout only
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import or_, select

from rampscout.agent.clocks import check_interval, clock_for_auth
from rampscout.agent.events import record
from rampscout.agent.execute import execute_claimed
from rampscout.config import Settings
from rampscout.db.models import Authorization, Execution, QuoteSnapshot
from rampscout.db.session import SessionLocal
from rampscout.domain.decision import next_check
from rampscout.settlement.factory import get_settler, settler_for_mode

log = structlog.get_logger()


def _void_unsigned(execution_id: uuid.UUID, settings: Settings) -> bool:
    """An execution that was created but never signed, whose quote has since expired,
    must not be signed late. Nothing left this process, so deleting it is safe."""
    with SessionLocal() as db:
        ex = db.scalars(
            select(Execution).where(Execution.id == execution_id).with_for_update(skip_locked=True)
        ).one_or_none()
        if ex is None or ex.chain_status != "not_started":
            return False
        auth = db.scalars(
            select(Authorization).where(Authorization.id == ex.authorization_id).with_for_update()
        ).one()
        now = clock_for_auth(db, auth, settings).now()
        snap = db.scalars(
            select(QuoteSnapshot).where(QuoteSnapshot.quote_id == ex.quote_id)
        ).one_or_none()
        if snap is not None and now < snap.expires_at:
            return False
        db.delete(ex)
        if auth.mode != "immediate" and auth.deadline_utc and now < auth.deadline_utc:
            auth.status = "watching"
            auth.next_check_at = next_check(now + check_interval(settings), auth.deadline_utc)
            reason = (
                "Recovered after a restart: unsigned execution had a stale quote; watching again."
            )
        else:
            auth.status = "requote_required" if auth.mode == "immediate" else "expired"
            auth.closed_at = now
            reason = (
                "Recovered after a restart: unsigned execution had a stale quote; not executed."
            )
        auth.claimed_at = None
        auth.version += 1
        auth.last_reason = reason
        record(db, auth, now, "reconciled", reason)
        db.commit()
        return True


def reconcile(settings: Settings, *, session_id: uuid.UUID | None = None) -> int:
    touched = 0
    with SessionLocal() as db:
        q = select(Execution.id, Execution.settlement_mode, Execution.chain_status).where(
            or_(
                Execution.chain_status.in_(("not_started", "prepared", "broadcast", "unknown")),
                (Execution.chain_status == "confirmed") & (Execution.payout_status != "posted"),
            )
        )
        orphans_q = (
            select(
                Authorization.id,
                Authorization.mode,
                Authorization.last_best_route,
                Authorization.selected_quote_id,
            )
            .outerjoin(Execution, Execution.authorization_id == Authorization.id)
            .where(Authorization.status == "claimed", Execution.id.is_(None))
        )
        if session_id is not None:
            q = q.join(Authorization, Authorization.id == Execution.authorization_id).where(
                Authorization.session_id == session_id
            )
            orphans_q = orphans_q.where(Authorization.session_id == session_id)
        pending = db.execute(q).all()
        orphans = db.execute(orphans_q).all()

    for auth_id, mode, route, quote_id in orphans:
        execute_claimed(
            auth_id,
            settings=settings,
            settler=get_settler(settings),
            route_id=route if mode != "immediate" else None,
            use_quote_id=quote_id if mode == "immediate" else None,
        )
        touched += 1

    for ex_id, mode, chain_status in pending:
        if chain_status == "not_started" and _void_unsigned(ex_id, settings):
            touched += 1
            continue
        settler = settler_for_mode(settings, mode)
        if settler is None:
            log.warning("reconcile.no_settler", execution_id=str(ex_id), mode=mode)
            continue
        try:
            settler.settle(ex_id)
            touched += 1
        except Exception:
            log.exception("reconcile.failed", execution_id=str(ex_id))
    return touched
