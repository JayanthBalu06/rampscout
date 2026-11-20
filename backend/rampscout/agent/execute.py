"""Claim -> refresh -> revalidate -> execute.

Runs immediately before any money moves. Every constraint the user approved is checked
again against a *fresh* quote; any failure releases the claim instead of signing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rampscout.agent.clocks import check_interval, clock_for_auth
from rampscout.agent.events import record
from rampscout.agent.terms import hash_of_authorization
from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession, Destination, Execution, QuoteSnapshot
from rampscout.db.session import SessionLocal
from rampscout.domain.decision import next_check
from rampscout.domain.eligibility import Constraints, exclusion_reasons
from rampscout.domain.money import fmt_mxn, fmt_usdc
from rampscout.domain.quotes import Quote
from rampscout.providers.base import QuoteProvider
from rampscout.services.quoting import compare, providers_for, snapshot_to_quote
from rampscout.settlement.base import Settler, onchain_amount

log = structlog.get_logger()


@dataclass(frozen=True)
class ExecOutcome:
    authorization_id: uuid.UUID
    status: str
    reason: str
    execution_id: uuid.UUID | None = None


def revalidate(
    *,
    auth: Authorization,
    quote: Quote | None,
    now: datetime,
    destination: Destination,
    settings: Settings,
    settler: Settler,
) -> list[str]:
    """Every check that must hold at the instant before signing. Empty list = go."""
    if quote is None:
        return ["the selected route did not return a fresh quote"]
    failures: list[str] = []
    if auth.status != "claimed":
        failures.append(f"authorization is {auth.status}, not claimed")
    if hash_of_authorization(auth) != auth.terms_hash:
        failures.append("authorization terms changed since confirmation")
    if auth.deadline_utc is not None and now >= auth.deadline_utc:
        failures.append("deadline has passed")
    constraints = Constraints(
        budget_usdc=auth.input_usdc,
        destination_rail=destination.rail,
        deadline=auth.deadline_utc,
        safety_margin=timedelta(seconds=settings.safety_margin_seconds),
    )
    failures += [r.value.replace("_", " ") for r in exclusion_reasons(quote, constraints, now)]
    if quote.input_usdc != auth.input_usdc:
        failures.append("quote amount differs from the authorized amount")
    if quote.net_mxn < auth.min_payout_mxn:
        failures.append(
            f"fresh payout {fmt_mxn(quote.net_mxn)} is below your "
            f"{fmt_mxn(auth.min_payout_mxn)} minimum"
        )
    if auth.input_usdc > settings.max_authorization_usdc:
        failures.append("amount exceeds the configured authorization limit")
    failures += settler.preflight(quote.route_id, onchain_amount(auth.input_usdc, settings))
    return failures


def _release_claim(
    db: Session, auth: Authorization, now: datetime, failures: list[str], settings: Settings
) -> ExecOutcome:
    detail = "; ".join(failures)
    if auth.mode == "immediate":
        auth.status = "requote_required"
        auth.closed_at = now
        reason = f"Not executed: {detail}. Get a fresh quote and confirm again."
    elif auth.deadline_utc is not None and now < auth.deadline_utc:
        auth.status = "watching"
        auth.next_check_at = next_check(now + check_interval(settings), auth.deadline_utc)
        reason = f"Re-check before signing failed ({detail}). Claim released; still watching."
    else:
        auth.status = "expired"
        auth.closed_at = now
        auth.next_check_at = None
        reason = f"Re-check before signing failed ({detail}) and no time remains. Closed."
    auth.claimed_at = None
    auth.version += 1
    auth.last_reason = reason
    record(db, auth, now, "claim_released", reason, payload={"failures": failures})
    return ExecOutcome(auth.id, auth.status, reason)


def execute_claimed(
    authorization_id: uuid.UUID,
    *,
    settings: Settings,
    settler: Settler,
    route_id: str | None = None,
    use_quote_id: str | None = None,
    providers: list[QuoteProvider] | None = None,
) -> ExecOutcome:
    """Revalidate and, if everything holds, create the single execution and settle it.

    Auto mode passes `route_id` (refresh that route's quote). Immediate mode passes
    `use_quote_id` (the quote the user confirmed, which must still be valid).
    """
    with SessionLocal() as db:
        auth = db.scalars(
            select(Authorization).where(Authorization.id == authorization_id).with_for_update()
        ).one()
        if auth.status != "claimed":
            return ExecOutcome(auth.id, auth.status, "not claimed; nothing to do")
        session = db.get(DemoSession, auth.session_id)
        destination = db.get(Destination, auth.destination_id)
        assert session is not None and destination is not None
        clock = clock_for_auth(db, auth, settings)
        now = clock.now()

        quote: Quote | None
        if use_quote_id is not None:
            snap = db.scalars(
                select(QuoteSnapshot).where(QuoteSnapshot.quote_id == use_quote_id)
            ).one_or_none()
            quote = snapshot_to_quote(snap) if snap else None
        else:
            pool = (
                providers if providers is not None else providers_for(settings, session.chaos_flags)
            )
            selected = [p for p in pool if p.route_id == route_id]
            cmp = compare(
                db=db,
                session_id=session.id,
                settings=settings,
                clock=clock,
                amount_usdc=auth.input_usdc,
                destination_rail=destination.rail,
                deadline=auth.deadline_utc,
                providers=selected,
                authorization_id=auth.id,
            )
            fresh = [q for q in (*cmp.ranked, *(e.quote for e in cmp.excluded))]
            quote = fresh[0] if fresh else None

        failures = revalidate(
            auth=auth,
            quote=quote,
            now=now,
            destination=destination,
            settings=settings,
            settler=settler,
        )
        if failures or quote is None:
            outcome = _release_claim(db, auth, now, failures, settings)
            db.commit()
            return outcome

        amount = onchain_amount(auth.input_usdc, settings)
        execution = Execution(
            authorization_id=auth.id,
            quote_id=quote.quote_id,
            route_id=quote.route_id,
            input_usdc=auth.input_usdc,
            quoted_net_mxn=quote.net_mxn,
            onchain_amount_usdc=amount,
            settlement_mode=settler.mode,
        )
        db.add(execution)
        try:
            db.flush()
        except IntegrityError:
            # Unique(authorization_id): another worker already created the execution.
            db.rollback()
            return ExecOutcome(authorization_id, "executing", "execution already exists")
        auth.status = "executing"
        auth.version += 1
        reason = (
            f"Revalidated fresh quote {quote.quote_id}: Route {quote.route_id} pays "
            f"{fmt_mxn(quote.net_mxn)} (minimum {fmt_mxn(auth.min_payout_mxn)}), all limits OK. "
            f"Settling {fmt_usdc(amount)} ({settler.mode})."
        )
        auth.last_reason = reason
        record(db, auth, now, "execution_started", reason, best=quote)
        db.commit()
        execution_id = execution.id

    settler.settle(execution_id)
    with SessionLocal() as db:
        final = db.get(Authorization, authorization_id)
        assert final is not None
        return ExecOutcome(authorization_id, final.status, final.last_reason or "", execution_id)
