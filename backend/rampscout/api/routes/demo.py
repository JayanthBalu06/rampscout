"""Demo-only controls: fixture clock, reset, chaos toggles. 404 unless DEMO_MODE=true."""

from __future__ import annotations

from fastapi import APIRouter, Response

from rampscout.agent.evaluate import run_due
from rampscout.api.deps import DbSession
from rampscout.api.errors import AppError
from rampscout.api.presenters import clock_out, settlement_out
from rampscout.api.schemas import AdvanceOut, ChaosIn, DemoStateOut, EvaluationOut
from rampscout.api.session_dep import CurrentSession, set_session_cookie
from rampscout.config import get_settings
from rampscout.db.models import DemoSession
from rampscout.services.sessions import advance_clock, create_session, set_chaos

router = APIRouter(prefix="/demo", tags=["demo"])


def _require_demo() -> None:
    if not get_settings().demo_mode:
        raise AppError(404, "not_found", "Not found")


def _state(s: DemoSession) -> DemoStateOut:
    return DemoStateOut(
        session_id=s.id,
        clock=clock_out(s),
        chaos=dict(s.chaos_flags or {}),
        settlement=settlement_out(get_settings()),
    )


@router.get("/state", response_model=DemoStateOut)
def demo_state(session: CurrentSession) -> DemoStateOut:
    _require_demo()
    return _state(session)


@router.post("/advance", response_model=AdvanceOut)
def demo_advance(db: DbSession, session: CurrentSession) -> AdvanceOut:
    """Advance the fixture clock one tick, then run one worker evaluation for this session."""
    _require_demo()
    settings = get_settings()
    advance_clock(db, session, settings)
    db.commit()
    outcomes = run_due(settings, session_id=session.id)
    db.refresh(session)
    state = _state(session)
    return AdvanceOut(
        **state.model_dump(),
        evaluations=[
            EvaluationOut(authorization_id=o.authorization_id, status=o.status, reason=o.reason)
            for o in outcomes
        ],
    )


@router.post("/reset", response_model=DemoStateOut)
def demo_reset(db: DbSession, response: Response, _: CurrentSession) -> DemoStateOut:
    _require_demo()
    fresh = create_session(db, get_settings())
    db.commit()
    set_session_cookie(response, fresh.id)
    return _state(fresh)


@router.post("/chaos", response_model=DemoStateOut)
def demo_chaos(body: ChaosIn, db: DbSession, session: CurrentSession) -> DemoStateOut:
    _require_demo()
    try:
        set_chaos(db, session, body.flags)
    except ValueError as exc:
        raise AppError(422, "unknown_chaos_flag", str(exc)) from exc
    db.commit()
    return _state(session)
