"""Watch evaluation: the agent's decision loop.

The *same* code runs for /demo/advance (fixture clock) and for the background worker
(fixture or system clock). Claims use SELECT ... FOR UPDATE SKIP LOCKED so any number of
workers can run without double-processing a watch.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rampscout.agent.clocks import check_interval, clock_for_auth
from rampscout.agent.events import record
from rampscout.agent.execute import execute_claimed
from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession, Destination, Notification
from rampscout.db.session import SessionLocal
from rampscout.domain.decision import DecisionKind, decide, next_check
from rampscout.domain.money import fmt_mxn, fmt_usdc
from rampscout.providers.base import QuoteProvider
from rampscout.services.quoting import compare, providers_for
from rampscout.settlement.base import Settler
from rampscout.settlement.factory import get_settler

log = structlog.get_logger()

ProvidersFactory = Callable[[Settings, dict[str, bool]], list[QuoteProvider]]


@dataclass(frozen=True)
class Outcome:
    authorization_id: uuid.UUID
    status: str
    reason: str


def claim_next_due(
    db: Session, settings: Settings, session_id: uuid.UUID | None = None
) -> Authorization | None:
    # Fixture watches follow their session's demo clock; send watches (live market) follow
    # the real clock.
    due_by = DemoSession.clock_now if settings.clock_mode == "fixture" else func.now()
    due = or_(
        and_(Authorization.contact_id.is_(None), Authorization.next_check_at <= due_by),
        and_(Authorization.contact_id.is_not(None), Authorization.next_check_at <= func.now()),
    )
    q = (
        select(Authorization)
        .join(DemoSession, DemoSession.id == Authorization.session_id)
        .where(Authorization.status == "watching", due)
        .order_by(Authorization.next_check_at)
        .limit(1)
        .with_for_update(of=Authorization, skip_locked=True)
    )
    if session_id is not None:
        q = q.where(Authorization.session_id == session_id)
    return db.scalars(q).one_or_none()


def evaluate_locked(
    db: Session,
    auth: Authorization,
    settings: Settings,
    providers: list[QuoteProvider],
) -> tuple[Outcome, str | None]:
    """Evaluate one claimed (row-locked) watch. Returns the outcome and, for an auto-mode
    match, the route to execute."""
    clock = clock_for_auth(db, auth, settings)
    now = clock.now()
    deadline = auth.deadline_utc
    assert deadline is not None, "watches always have a deadline"
    assert auth.min_payout_mxn is not None and auth.destination_id is not None

    if now >= deadline:
        auth.status = "expired"
        auth.closed_at = now
        auth.next_check_at = None
        auth.last_check_at = now
        auth.version += 1
        auth.last_reason = (
            f"Deadline reached without a payout of at least {fmt_mxn(auth.min_payout_mxn)}. "
            "Nothing was converted."
        )
        record(db, auth, now, "expired", auth.last_reason)
        return Outcome(auth.id, auth.status, auth.last_reason), None

    destination = db.get(Destination, auth.destination_id)
    assert destination is not None
    cmp = compare(
        db=db,
        session_id=auth.session_id,
        settings=settings,
        clock=clock,
        amount_usdc=auth.input_usdc,
        destination_rail=destination.rail,
        deadline=deadline,
        providers=providers,
        authorization_id=auth.id,
    )
    for err in cmp.errors:
        record(
            db,
            auth,
            now,
            "provider_error",
            f"Route {err.route_id} {'timed out' if err.kind == 'timeout' else err.kind}: "
            f"{err.message}. Other routes still evaluated.",
            payload={"provider_id": err.provider_id, "kind": err.kind},
        )

    min_payout = auth.min_payout_mxn
    decision = decide(
        min_payout_mxn=min_payout,
        ranked=cmp.ranked,
        excluded=cmp.excluded,
        provider_errors=len(cmp.errors),
    )
    auth.last_check_at = now
    auth.last_best_route = decision.best.route_id if decision.best else None
    auth.last_best_net_mxn = decision.best.net_mxn if decision.best else None
    payload = {
        "eligible": [
            {"route_id": q.route_id, "net_mxn": format(q.net_mxn, "f")} for q in cmp.ranked
        ],
        "excluded": [
            {"route_id": e.quote.route_id, "reasons": [r.value for r in e.reasons]}
            for e in cmp.excluded
        ],
        "provider_errors": [e.route_id for e in cmp.errors],
        "tick": clock.tick,
    }

    if decision.kind is not DecisionKind.MATCHED:
        auth.next_check_at = next_check(now + check_interval(settings), deadline)
        auth.last_reason = decision.reason + " Keep watching."
        record(db, auth, now, decision.kind.value, decision.reason, decision.best, payload)
        return Outcome(auth.id, auth.status, auth.last_reason), None

    best = decision.best
    assert best is not None
    record(db, auth, now, "matched", decision.reason, best, payload)
    auth.next_check_at = None
    auth.version += 1

    if auth.mode == "notify":
        db.execute(
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                owner_id=auth.owner_id,
                session_id=auth.session_id,
                authorization_id=auth.id,
                kind="target_reached",
                title=f"Target reached: {fmt_mxn(best.net_mxn)} via Route {best.route_id}",
                body=(
                    f"Route {best.route_id} can deliver {fmt_mxn(best.net_mxn)} for "
                    f"{fmt_usdc(auth.input_usdc)} (your minimum: {fmt_mxn(auth.min_payout_mxn)}). "
                    "Nothing was converted. Open RampScout to convert now."
                ),
                at=now,
            )
            .on_conflict_do_nothing(index_elements=["authorization_id", "kind"])
        )
        auth.status = "notified"
        auth.closed_at = now
        auth.last_reason = decision.reason + " Notified you; nothing was converted."
        record(db, auth, now, "notified", "Sent one in-app notification. Watch closed.")
        return Outcome(auth.id, auth.status, auth.last_reason), None

    auth.status = "claimed"
    auth.claimed_at = now
    auth.last_reason = decision.reason + " Claimed for auto-conversion."
    record(
        db,
        auth,
        now,
        "claimed",
        "Claimed the watch for auto-conversion. Cancellation is now closed; "
        "re-checking a fresh quote before any transfer.",
        best,
    )
    return Outcome(auth.id, auth.status, auth.last_reason), best.route_id


def run_due(
    settings: Settings,
    *,
    session_id: uuid.UUID | None = None,
    providers_factory: ProvidersFactory | None = None,
    settler: Settler | None = None,
    max_items: int = 100,
) -> list[Outcome]:
    """Evaluate every due watch once. Each watch is processed in its own transaction."""
    factory = providers_factory or providers_for
    settler = settler or get_settler(settings)
    outcomes: list[Outcome] = []
    seen: set[uuid.UUID] = set()
    for _ in range(max_items):
        with SessionLocal() as db:
            auth = claim_next_due(db, settings, session_id)
            if auth is None or auth.id in seen:
                db.rollback()
                break
            seen.add(auth.id)
            session = db.get(DemoSession, auth.session_id)
            assert session is not None
            chaos = dict(session.chaos_flags or {})
            if auth.contact_id is not None:
                outcomes.append(_run_send_watch(db, auth, settings, settler))
                continue
            try:
                outcome, route = evaluate_locked(db, auth, settings, factory(settings, chaos))
                db.commit()
            except Exception:
                db.rollback()
                log.exception("watch.evaluate_failed", authorization_id=str(auth.id))
                outcome, route = _defer_after_error(auth.id, settings), None
        if route is not None:
            ex = execute_claimed(
                outcome.authorization_id,
                settings=settings,
                settler=settler,
                route_id=route,
                providers=factory(settings, chaos),
            )
            outcome = Outcome(ex.authorization_id, ex.status, ex.reason)
        outcomes.append(outcome)
    return outcomes


def _run_send_watch(
    db: Session, auth: Authorization, settings: Settings, settler: Settler
) -> Outcome:
    from rampscout.agent.send_watch import evaluate_send_watch_locked
    from rampscout.services.send import execute_send
    from rampscout.settlement.chain_settler import ChainSettler

    chain_settler = settler if isinstance(settler, ChainSettler) else get_settler(settings)
    auth_id = auth.id
    try:
        status, reason, execute = evaluate_send_watch_locked(db, auth, settings, chain_settler.mode)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("send_watch.evaluate_failed", authorization_id=str(auth_id))
        return _defer_after_error(auth_id, settings)
    if execute:
        out = execute_send(auth_id, settings=settings, settler=chain_settler)
        return Outcome(out.authorization_id, out.status, out.reason)
    return Outcome(auth_id, status, reason)


def check_now(authorization_id: uuid.UUID, settings: Settings) -> Outcome | None:
    """Evaluate one watch immediately (the UI's "Check now"); same code as the worker."""
    with SessionLocal() as db:
        auth = db.scalars(
            select(Authorization)
            .where(Authorization.id == authorization_id)
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if auth is None or auth.status != "watching":
            db.rollback()
            return None
        if auth.contact_id is not None:
            return _run_send_watch(db, auth, settings, get_settler(settings))
        session = db.get(DemoSession, auth.session_id)
        assert session is not None
        outcome, route = evaluate_locked(
            db, auth, settings, providers_for(settings, dict(session.chaos_flags or {}))
        )
        db.commit()
    if route is not None:
        ex = execute_claimed(
            authorization_id, settings=settings, settler=get_settler(settings), route_id=route
        )
        return Outcome(ex.authorization_id, ex.status, ex.reason)
    return outcome


def _defer_after_error(authorization_id: uuid.UUID, settings: Settings) -> Outcome:
    """An unexpected error must never stall or silently drop a watch: log it, push the
    next check out one interval, and keep the audit trail honest."""
    with SessionLocal() as db:
        auth = db.scalars(
            select(Authorization).where(Authorization.id == authorization_id).with_for_update()
        ).one()
        if auth.contact_id is not None:
            from rampscout.agent.send_watch import now_utc

            now = now_utc()
            interval = timedelta(seconds=settings.poll_interval_seconds)
        else:
            now = clock_for_auth(db, auth, settings).now()
            interval = check_interval(settings)
        auth.next_check_at = next_check(now + interval, auth.deadline_utc)
        auth.last_reason = "Internal error during this check; will retry next interval."
        record(db, auth, now, "check_failed", auth.last_reason)
        db.commit()
        return Outcome(auth.id, auth.status, auth.last_reason)
