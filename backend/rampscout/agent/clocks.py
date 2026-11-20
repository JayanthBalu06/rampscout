from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from rampscout.config import Settings
from rampscout.db.models import Authorization, DemoSession
from rampscout.domain.clock import Clock, FixtureClock, SystemClock


def clock_for_session(session: DemoSession, settings: Settings) -> Clock:
    if settings.clock_mode == "fixture":
        return FixtureClock(at=session.clock_now, tick=session.tick)
    return SystemClock(
        start=settings.demo_clock_start, tick_length=timedelta(seconds=settings.demo_tick_seconds)
    )


def clock_for_auth(db: Session, auth: Authorization, settings: Settings) -> Clock:
    session = db.get(DemoSession, auth.session_id)
    assert session is not None
    return clock_for_session(session, settings)


def check_interval(settings: Settings) -> timedelta:
    """One check per tick in fixture mode; the poll interval in live mode."""
    seconds = (
        settings.demo_tick_seconds
        if settings.clock_mode == "fixture"
        else settings.poll_interval_seconds
    )
    return timedelta(seconds=seconds)
