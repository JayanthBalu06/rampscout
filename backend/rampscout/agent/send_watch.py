""" "Send when ..." watches: the agent re-checks live routes to a contact until the recipient
would receive at least the user's minimum, then notifies or sends automatically.

Runs on the real clock (it watches a live market). It never acts on the recorded snapshot:
if live data is unavailable, that check is skipped and the watch keeps waiting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rampscout.agent.events import record
from rampscout.config import Settings
from rampscout.db.models import Authorization, Contact, Notification
from rampscout.domain.currencies import fmt_amount
from rampscout.domain.decision import next_check
from rampscout.domain.money import fmt_usdc


def now_utc() -> datetime:
    """Real time. A function so tests can move it."""
    return datetime.now(UTC)


def evaluate_send_watch_locked(
    db: Session, auth: Authorization, settings: Settings, settlement_mode: str
) -> tuple[str, str, bool]:
    """Evaluate one row-locked send watch. Returns (status, reason, should_execute)."""
    from rampscout.services.send import (
        _persist,
        find_send_routes,
        load_market,
    )

    now = now_utc()
    deadline = auth.deadline_utc
    assert deadline is not None and auth.min_out is not None and auth.out_currency
    contact = db.get(Contact, auth.contact_id)
    assert contact is not None
    ccy = auth.out_currency
    target = fmt_amount(ccy, auth.min_out)

    if now >= deadline:
        auth.status = "expired"
        auth.closed_at = now
        auth.next_check_at = None
        auth.last_check_at = now
        auth.version += 1
        auth.last_reason = (
            f"Deadline reached without {contact.name} receiving at least {target}. "
            "Nothing was sent."
        )
        record(db, auth, now, "expired", auth.last_reason)
        return auth.status, auth.last_reason, False

    interval = timedelta(seconds=settings.poll_interval_seconds)
    auth.last_check_at = now
    market, fell_back = load_market(settings, "live")
    if fell_back:
        auth.next_check_at = next_check(now + interval, deadline)
        auth.last_reason = (
            "Live Bitso data unavailable; skipped this check (never acts on stale prices)."
        )
        record(db, auth, now, "provider_error", auth.last_reason)
        return auth.status, auth.last_reason, False

    margin = timedelta(seconds=settings.safety_margin_seconds)
    routes = find_send_routes(contact, auth.input_usdc, market, settings, settlement_mode)
    eligible = [r for r in routes if now + r.eta + margin <= deadline]
    payload = {
        "routes": [{"path": r.path, "amount_out": format(r.amount_out, "f")} for r in routes[:4]],
        "market_as_of": market.as_of.isoformat(),
    }
    if not eligible:
        auth.next_check_at = next_check(now + interval, deadline)
        auth.last_reason = (
            "No route can deliver before the deadline."
            if routes
            else "No route available right now."
        )
        record(db, auth, now, "no_eligible_route", auth.last_reason, payload=payload)
        return auth.status, auth.last_reason, False

    best = eligible[0]
    got = fmt_amount(ccy, best.amount_out)
    if best.amount_out < auth.min_out:
        gap = fmt_amount(ccy, auth.min_out - best.amount_out)
        reason = f"Best is {best.path}: {contact.name} would get {got}, {gap} short of {target}."
        auth.next_check_at = next_check(now + interval, deadline)
        auth.last_reason = reason + " Keep watching."
        record(db, auth, now, "waiting_below_target", reason, payload=payload)
        return auth.status, auth.last_reason, False

    reason = f"{best.path} now delivers {got} to {contact.name}, meeting your {target} minimum."
    record(db, auth, now, "matched", reason, payload=payload)
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
                title=f"Target reached: {contact.name} would receive {got}",
                body=(
                    f"Sending {fmt_usdc(auth.input_usdc)} via {best.path} delivers {got} "
                    f"(your minimum: {target}). Nothing was sent. Open RampScout to send now."
                ),
                at=now,
            )
            .on_conflict_do_nothing(index_elements=["authorization_id", "kind"])
        )
        auth.status = "notified"
        auth.closed_at = now
        auth.last_reason = reason + " Notified you; nothing was sent."
        record(db, auth, now, "notified", "Sent one in-app notification. Watch closed.")
        return auth.status, auth.last_reason, False

    row = _persist(db, auth.session_id, contact.id, best, 1, market, now, settings, auth.id)
    auth.route_quote_id = row.id
    auth.status = "claimed"
    auth.claimed_at = now
    auth.last_reason = reason + " Claimed for auto-send."
    record(
        db,
        auth,
        now,
        "claimed",
        "Claimed for auto-send. Cancellation is now closed; re-pricing this exact route "
        "on fresh data before any transfer.",
    )
    return auth.status, auth.last_reason, True
