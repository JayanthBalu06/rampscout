from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response
from sqlalchemy import select

from rampscout.agent.clocks import clock_for_session
from rampscout.agent.evaluate import run_due
from rampscout.agent.execute import execute_claimed
from rampscout.agent.intent import draft_intent
from rampscout.api.deps import DbSession
from rampscout.api.errors import AppError
from rampscout.api.presenters import authorization_out, destination_out, settlement_out
from rampscout.api.schemas import (
    AuthorizationIn,
    AuthorizationOut,
    IntentDraftOut,
    IntentParseIn,
    IntentParseOut,
    NotificationOut,
    PreviewOut,
)
from rampscout.api.session_dep import CurrentSession
from rampscout.config import get_settings
from rampscout.db.models import Authorization, Destination, Notification
from rampscout.demo import DEMO_DISPLAY_TZ
from rampscout.services.authorizations import (
    cancel_authorization,
    create_authorization,
    preview_authorization,
)
from rampscout.settlement.factory import get_settler

router = APIRouter(tags=["agent"])


@router.post("/intents/parse", response_model=IntentParseOut)
def parse_intent(body: IntentParseIn, db: DbSession, session: CurrentSession) -> IntentParseOut:
    """Draft only: returns editable terms + missing/ambiguous fields. Creates nothing."""
    settings = get_settings()
    destinations = list(
        db.scalars(select(Destination).where(Destination.owner_id == session.owner_id)).all()
    )
    d = draft_intent(
        body.text,
        now_utc=clock_for_session(session, settings).now(),
        user_tz=DEMO_DISPLAY_TZ,
        destinations=destinations,
        settings=settings,
    )
    return IntentParseOut(
        draft=IntentDraftOut(
            amount=d.amount,
            currency=d.currency,
            min_payout_mxn=d.min_payout_mxn,
            destination_id=d.destination_id,
            destination_alias=d.destination_alias,
            deadline_local=d.deadline_local,
            time_zone=d.time_zone,
            mode=d.mode,
        ),
        deadline_utc=d.deadline_utc,
        deadline_display=d.deadline_display,
        missing=d.missing,
        ambiguities=[{"field": a["field"], "question": a["question"]} for a in d.ambiguities],
        assumptions=d.assumptions,
        source=d.source,
        model=d.model,
        model_note=d.model_note,
    )


@router.post("/authorizations/preview", response_model=PreviewOut)
def post_preview(body: AuthorizationIn, db: DbSession, session: CurrentSession) -> PreviewOut:
    """Resolve and validate terms for the review screen. Creates no authorization."""
    settings = get_settings()
    p = preview_authorization(db, session=session, body=body, settings=settings)
    return PreviewOut(
        mode=body.mode,
        amount_usdc=body.amount_usdc,
        min_payout_mxn=body.min_payout_mxn,
        destination=destination_out(p.destination),
        deadline_utc=p.deadline,
        deadline_display=p.deadline_display,
        time_zone=body.time_zone,
        onchain_amount_usdc=p.onchain_amount_usdc,
        transfer_scale=format(settings.demo_transfer_scale, "f"),
        settlement=settlement_out(settings),
        current_best_route=p.best_route,
        current_best_net_mxn=p.best_net_mxn,
        meets_target_now=p.best_net_mxn is not None and p.best_net_mxn >= body.min_payout_mxn,
    )


@router.post("/authorizations", response_model=AuthorizationOut, status_code=201)
def post_authorization(
    body: AuthorizationIn,
    db: DbSession,
    session: CurrentSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthorizationOut:
    settings = get_settings()
    result = create_authorization(
        db, session=session, body=body, idempotency_key=idempotency_key or "", settings=settings
    )
    if result.created:
        if body.mode == "immediate":
            execute_claimed(
                result.authorization_id,
                settings=settings,
                settler=get_settler(settings),
                use_quote_id=body.selected_quote_id,
            )
        else:
            # First decision happens right away, using the same code as the worker.
            run_due(settings, session_id=session.id)
    else:
        response.headers["Idempotent-Replay"] = "true"
    db.expire_all()
    auth = db.get(Authorization, result.authorization_id)
    assert auth is not None
    return authorization_out(db, auth, settings)


@router.get("/authorizations", response_model=list[AuthorizationOut])
def list_authorizations(db: DbSession, session: CurrentSession) -> list[AuthorizationOut]:
    settings = get_settings()
    rows = db.scalars(
        select(Authorization)
        .where(Authorization.session_id == session.id)
        .order_by(Authorization.created_at.desc())
    ).all()
    return [authorization_out(db, a, settings) for a in rows]


@router.get("/authorizations/{authorization_id}", response_model=AuthorizationOut)
def get_authorization(
    authorization_id: uuid.UUID, db: DbSession, session: CurrentSession
) -> AuthorizationOut:
    auth = db.get(Authorization, authorization_id)
    if auth is None or auth.session_id != session.id:
        raise AppError(404, "not_found", "Authorization not found")
    return authorization_out(db, auth, get_settings())


@router.post("/authorizations/{authorization_id}/cancel", response_model=AuthorizationOut)
def post_cancel(
    authorization_id: uuid.UUID, db: DbSession, session: CurrentSession
) -> AuthorizationOut:
    settings = get_settings()
    cancel_authorization(db, session=session, authorization_id=authorization_id, settings=settings)
    db.expire_all()
    auth = db.get(Authorization, authorization_id)
    assert auth is not None
    return authorization_out(db, auth, settings)


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(db: DbSession, session: CurrentSession) -> list[NotificationOut]:
    rows = db.scalars(
        select(Notification)
        .where(Notification.session_id == session.id)
        .order_by(Notification.at.desc())
    ).all()
    return [
        NotificationOut(
            id=n.id,
            authorization_id=n.authorization_id,
            kind=n.kind,
            title=n.title,
            body=n.body,
            at=n.at,
            read=n.read_at is not None,
        )
        for n in rows
    ]


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: uuid.UUID, db: DbSession, session: CurrentSession) -> None:
    n = db.get(Notification, notification_id)
    if n is None or n.session_id != session.id:
        raise AppError(404, "not_found", "Notification not found")
    if n.read_at is None:
        n.read_at = clock_for_session(session, get_settings()).now()
        db.commit()
