"""Bind every request to a demo session via an HttpOnly cookie."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request, Response

from rampscout.api.deps import DbSession
from rampscout.config import get_settings
from rampscout.db.models import DemoSession
from rampscout.services.sessions import create_session

COOKIE = "rs_session"


def set_session_cookie(response: Response, session_id: uuid.UUID) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE,
        str(session_id),
        httponly=True,
        samesite="none" if settings.cookie_secure else "lax",
        secure=settings.cookie_secure,
        max_age=7 * 24 * 3600,
    )


def get_demo_session(request: Request, response: Response, db: DbSession) -> DemoSession:
    raw = request.cookies.get(COOKIE)
    session: DemoSession | None = None
    if raw:
        try:
            session = db.get(DemoSession, uuid.UUID(raw))
        except ValueError:
            session = None
    if session is None:
        session = create_session(db, get_settings())
        db.commit()
        set_session_cookie(response, session.id)
    return session


CurrentSession = Annotated[DemoSession, Depends(get_demo_session)]
