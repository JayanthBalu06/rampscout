from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from rampscout.api.deps import DbSession
from rampscout.api.errors import AppError
from rampscout.api.presenters import (
    clock_out,
    destination_out,
    error_out,
    excluded_out,
    quote_out,
    rate_vs_payout_insight,
    settlement_out,
)
from rampscout.api.schemas import DestinationOut, QuotesIn, QuotesOut
from rampscout.api.session_dep import CurrentSession
from rampscout.config import get_settings
from rampscout.db.models import Destination
from rampscout.domain.clock import DeadlineResolutionError, resolve_local_deadline
from rampscout.services.quoting import compare, providers_for
from rampscout.services.sessions import clock_for

router = APIRouter(tags=["quotes"])


@router.get("/destinations", response_model=list[DestinationOut])
def list_destinations(db: DbSession, session: CurrentSession) -> list[DestinationOut]:
    rows = db.scalars(select(Destination).where(Destination.owner_id == session.owner_id)).all()
    return [destination_out(d) for d in rows]


@router.post("/quotes", response_model=QuotesOut)
def post_quotes(body: QuotesIn, db: DbSession, session: CurrentSession) -> QuotesOut:
    settings = get_settings()
    dest = db.get(Destination, body.destination_id)
    if dest is None or dest.owner_id != session.owner_id:
        raise AppError(404, "destination_not_found", "Unknown destination for this user")

    deadline = body.deadline
    if body.deadline_local is not None and body.time_zone:
        try:
            deadline = resolve_local_deadline(body.deadline_local, body.time_zone)
        except DeadlineResolutionError as exc:
            raise AppError(422, "invalid_deadline", str(exc)) from exc

    clock = clock_for(session)
    if deadline is not None and deadline <= clock.now():
        raise AppError(422, "deadline_in_past", "The deadline has already passed on the demo clock")

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
    return QuotesOut(
        amount_usdc=body.amount_usdc,
        corridor=body.corridor,
        destination=destination_out(dest),
        deadline=deadline,
        clock=clock_out(session),
        quotes=[quote_out(q, cmp.now, i + 1) for i, q in enumerate(cmp.ranked)],
        best_quote_id=cmp.best.quote_id if cmp.best else None,
        excluded=[excluded_out(e, cmp.now) for e in cmp.excluded],
        provider_errors=[error_out(e) for e in cmp.errors],
        insight=rate_vs_payout_insight(cmp.ranked),
        settlement=settlement_out(settings),
    )
