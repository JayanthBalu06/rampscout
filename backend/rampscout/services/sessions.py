"""Demo sessions: per-visitor fixture clock + chaos toggles, and the seeded destination."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rampscout.config import Settings
from rampscout.db.models import DemoSession, Destination
from rampscout.demo import DEMO_DESTINATION_ALIAS, DEMO_OWNER_ID
from rampscout.domain.clock import FixtureClock
from rampscout.providers.fixture import MX_SPEI

CHAOS_FLAGS = frozenset(
    {
        "provider_a_down",
        "provider_a_timeout",
        "provider_b_down",
        "provider_b_timeout",
        "drop_broadcast_response",
        "fail_next_payout",
    }
)


def ensure_demo_destination(db: Session) -> Destination:
    """Idempotently create the demo user's saved Mexican bank destination."""
    db.execute(
        insert(Destination)
        .values(
            id=uuid.uuid4(),
            owner_id=DEMO_OWNER_ID,
            alias=DEMO_DESTINATION_ALIAS,
            bank_name="BBVA México",
            masked_account="CLABE •••• 4821",
            currency="MXN",
            rail=MX_SPEI,
        )
        .on_conflict_do_nothing(index_elements=["owner_id", "alias"])
    )
    dest = db.scalars(
        select(Destination).where(
            Destination.owner_id == DEMO_OWNER_ID, Destination.alias == DEMO_DESTINATION_ALIAS
        )
    ).one()
    return dest


def create_session(db: Session, settings: Settings) -> DemoSession:
    ensure_demo_destination(db)
    s = DemoSession(
        owner_id=DEMO_OWNER_ID, clock_now=settings.demo_clock_start, tick=0, chaos_flags={}
    )
    db.add(s)
    db.flush()
    return s


def clock_for(s: DemoSession) -> FixtureClock:
    return FixtureClock(at=s.clock_now, tick=s.tick)


def advance_clock(db: Session, s: DemoSession, settings: Settings) -> FixtureClock:
    """Advance one tick under a row lock so concurrent clicks can't double-advance."""
    locked = db.scalars(select(DemoSession).where(DemoSession.id == s.id).with_for_update()).one()
    locked.clock_now = locked.clock_now + timedelta(seconds=settings.demo_tick_seconds)
    locked.tick += 1
    db.flush()
    return clock_for(locked)


def set_chaos(db: Session, s: DemoSession, flags: dict[str, bool]) -> dict[str, bool]:
    unknown = set(flags) - CHAOS_FLAGS
    if unknown:
        raise ValueError(f"unknown chaos flags: {sorted(unknown)}")
    merged = {**(s.chaos_flags or {}), **flags}
    s.chaos_flags = {k: v for k, v in merged.items() if v}
    db.flush()
    return dict(s.chaos_flags)
