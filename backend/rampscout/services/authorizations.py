"""Creating and cancelling authorizations. The API layer stays thin; rules live here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rampscout.agent.clocks import clock_for_session
from rampscout.agent.events import record
from rampscout.agent.intent import format_deadline
from rampscout.agent.terms import canonical_terms, terms_hash
from rampscout.api.errors import AppError
from rampscout.api.schemas import AuthorizationIn
from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession, Destination, QuoteSnapshot
from rampscout.domain.clock import DeadlineResolutionError, resolve_local_deadline
from rampscout.domain.money import fmt_mxn
from rampscout.services.quoting import compare, providers_for
from rampscout.settlement.base import onchain_amount


@dataclass(frozen=True)
class CreateResult:
    authorization_id: uuid.UUID
    created: bool  # False = idempotent replay


def _resolve_deadline(body: AuthorizationIn) -> datetime | None:
    if body.deadline is not None:
        return body.deadline
    if body.deadline_local is not None:
        try:
            return resolve_local_deadline(body.deadline_local, body.time_zone)
        except DeadlineResolutionError as exc:
            raise AppError(422, "invalid_deadline", str(exc)) from exc
    return None


def _fresh_quote_details(
    db: Session, session: DemoSession, dest: Destination, body: AuthorizationIn, settings: Settings
) -> dict[str, object]:
    from rampscout.api.presenters import quote_out

    clock = clock_for_session(session, settings)
    cmp = compare(
        db=db,
        session_id=session.id,
        settings=settings,
        clock=clock,
        amount_usdc=body.amount_usdc,
        destination_rail=dest.rail,
        deadline=None,
        providers=providers_for(settings, session.chaos_flags),
    )
    best = cmp.best
    db.commit()  # the fresh quote must survive the 409 so the user can confirm it
    return {"fresh_quote": quote_out(best, cmp.now, 1).model_dump(mode="json") if best else None}


def _check_destination_and_tz(
    db: Session, session: DemoSession, body: AuthorizationIn
) -> Destination:
    try:
        ZoneInfo(body.time_zone)
    except (KeyError, ValueError) as exc:
        raise AppError(422, "invalid_time_zone", f"Unknown time zone {body.time_zone}") from exc
    dest = db.get(Destination, body.destination_id)
    if dest is None or dest.owner_id != session.owner_id:
        raise AppError(404, "destination_not_found", "Unknown destination for this user")
    return dest


def _check_limits(
    body: AuthorizationIn, deadline: datetime | None, now: datetime, settings: Settings
) -> None:
    if body.amount_usdc > settings.max_authorization_usdc:
        raise AppError(
            422,
            "over_limit",
            f"Authorizations are limited to {settings.max_authorization_usdc} USDC",
        )
    if deadline is not None:
        if deadline <= now:
            raise AppError(422, "deadline_in_past", "The deadline has already passed")
        if deadline > now + timedelta(days=settings.max_watch_days):
            raise AppError(
                422, "deadline_too_far", f"Watches can run at most {settings.max_watch_days} days"
            )


@dataclass(frozen=True)
class Preview:
    destination: Destination
    deadline: datetime | None
    deadline_display: str | None
    onchain_amount_usdc: Decimal
    best_route: str | None
    best_net_mxn: Decimal | None


def preview_authorization(
    db: Session, *, session: DemoSession, body: AuthorizationIn, settings: Settings
) -> Preview:
    """Validate and resolve terms exactly as confirmation would, without creating anything."""
    dest = _check_destination_and_tz(db, session, body)
    deadline = _resolve_deadline(body)
    clock = clock_for_session(session, settings)
    _check_limits(body, deadline, clock.now(), settings)
    cmp = compare(
        db=db,
        session_id=session.id,
        settings=settings,
        clock=clock,
        amount_usdc=body.amount_usdc,
        destination_rail=dest.rail,
        deadline=deadline,
        providers=providers_for(settings, session.chaos_flags),
    )
    db.commit()
    return Preview(
        destination=dest,
        deadline=deadline,
        deadline_display=format_deadline(deadline, body.time_zone) if deadline else None,
        onchain_amount_usdc=onchain_amount(body.amount_usdc, settings),
        best_route=cmp.best.route_id if cmp.best else None,
        best_net_mxn=cmp.best.net_mxn if cmp.best else None,
    )


def create_authorization(
    db: Session,
    *,
    session: DemoSession,
    body: AuthorizationIn,
    idempotency_key: str,
    settings: Settings,
) -> CreateResult:
    if not idempotency_key or len(idempotency_key) > 100:
        raise AppError(
            422, "idempotency_key_required", "Send an Idempotency-Key header (≤100 chars)"
        )
    dest = _check_destination_and_tz(db, session, body)
    deadline = _resolve_deadline(body)
    terms = canonical_terms(
        mode=body.mode,
        input_usdc=body.amount_usdc,
        min_payout_mxn=body.min_payout_mxn,
        destination_id=dest.id,
        deadline_utc=deadline,
        display_tz=body.time_zone,
        selected_quote_id=body.selected_quote_id,
    )
    digest = terms_hash(terms)

    # Idempotent replay is checked first: a retried confirmation must return the original
    # result even if the quote has since expired.
    existing = db.scalars(
        select(Authorization).where(
            Authorization.owner_id == session.owner_id,
            Authorization.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if existing is not None:
        if existing.terms_hash != digest:
            raise AppError(
                422,
                "idempotency_key_reused",
                "This Idempotency-Key was already used with different terms",
            )
        return CreateResult(existing.id, created=False)

    clock = clock_for_session(session, settings)
    now = clock.now()
    _check_limits(body, deadline, now, settings)

    status = "watching"
    if body.mode == "immediate":
        snap = db.scalars(
            select(QuoteSnapshot).where(
                QuoteSnapshot.quote_id == body.selected_quote_id,
                QuoteSnapshot.session_id == session.id,
            )
        ).one_or_none()
        if snap is None or now >= snap.expires_at:
            raise AppError(
                409,
                "quote_changed",
                "That quote has expired. Review the fresh quote and confirm again.",
                _fresh_quote_details(db, session, dest, body, settings),
            )
        if snap.input_usdc != body.amount_usdc or snap.destination_rail != dest.rail:
            raise AppError(422, "terms_mismatch", "The quote does not match these terms")
        if body.min_payout_mxn > snap.net_mxn:
            raise AppError(
                422,
                "min_above_quote",
                f"Minimum payout exceeds the quoted {fmt_mxn(snap.net_mxn)}",
            )
        status = "claimed"

    row = {
        "id": uuid.uuid4(),
        "owner_id": session.owner_id,
        "session_id": session.id,
        "idempotency_key": idempotency_key,
        "terms_hash": digest,
        "mode": body.mode,
        "status": status,
        "version": 1,
        "input_usdc": body.amount_usdc,
        "min_payout_mxn": body.min_payout_mxn,
        "destination_id": dest.id,
        "deadline_utc": deadline,
        "display_tz": body.time_zone,
        "selected_quote_id": body.selected_quote_id,
        "intent_text": body.intent_text,
        "next_check_at": now if status == "watching" else None,
        "confirmed_at": now,
        "claimed_at": now if status == "claimed" else None,
        "event_count": 0,
    }
    inserted = db.execute(
        insert(Authorization)
        .values(**row)
        .on_conflict_do_nothing(index_elements=["owner_id", "idempotency_key"])
        .returning(Authorization.id)
    ).scalar_one_or_none()
    if inserted is None:
        # Lost a race with a concurrent request using the same key.
        db.rollback()
        winner = db.scalars(
            select(Authorization).where(
                Authorization.owner_id == session.owner_id,
                Authorization.idempotency_key == idempotency_key,
            )
        ).one()
        if winner.terms_hash != digest:
            raise AppError(422, "idempotency_key_reused", "Key already used with different terms")
        return CreateResult(winner.id, created=False)

    auth = db.scalars(
        select(Authorization).where(Authorization.id == inserted).with_for_update()
    ).one()
    when = f" by {format_deadline(deadline, body.time_zone)}" if deadline else ""
    mode_text = {
        "notify": "Notify me (never converts on its own)",
        "auto": "Auto-convert when the target is met",
        "immediate": f"Convert now at quote {body.selected_quote_id}",
    }[body.mode]
    record(
        db,
        auth,
        now,
        "confirmed",
        f"You confirmed: {body.amount_usdc} USDC to {dest.alias}, minimum "
        f"{fmt_mxn(body.min_payout_mxn)}{when}. Mode: {mode_text}.",
        payload={"terms": terms, "terms_hash": digest},
    )
    db.commit()
    return CreateResult(auth.id, created=True)


def cancel_authorization(
    db: Session, *, session: DemoSession, authorization_id: uuid.UUID, settings: Settings
) -> None:
    now = clock_for_session(session, settings).now()
    # Atomic compare-and-set: only a *waiting* watch can be cancelled. If a worker holds
    # the row (evaluating/claiming), this UPDATE waits, then re-checks status.
    cancelled = db.execute(
        update(Authorization)
        .where(
            Authorization.id == authorization_id,
            Authorization.session_id == session.id,
            Authorization.status == "watching",
        )
        .values(
            status="canceled",
            closed_at=now,
            next_check_at=None,
            version=Authorization.version + 1,
            last_reason="Canceled by you. Nothing was converted.",
        )
        .returning(Authorization.id)
    ).scalar_one_or_none()
    if cancelled is None:
        db.rollback()
        auth = db.get(Authorization, authorization_id)
        if auth is None or auth.session_id != session.id:
            raise AppError(404, "not_found", "Authorization not found")
        if auth.status in ("claimed", "executing"):
            raise AppError(
                409, "already_claimed", "Execution has already been claimed; it can't be canceled"
            )
        raise AppError(409, "already_terminal", f"This authorization is already {auth.status}")
    auth = db.scalars(
        select(Authorization).where(Authorization.id == authorization_id).with_for_update()
    ).one()
    record(db, auth, now, "canceled", "Canceled by you. Nothing was converted.")
    db.commit()
