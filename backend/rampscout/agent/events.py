from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from rampscout.db.models import Authorization, DecisionEvent
from rampscout.domain.quotes import Quote


def record(
    db: Session,
    auth: Authorization,
    at: datetime,
    kind: str,
    reason: str,
    best: Quote | None = None,
    payload: dict[str, Any] | None = None,
) -> DecisionEvent:
    """Append an event. Caller must hold the authorization row lock, which makes the
    per-authorization sequence number race-free."""
    auth.event_count = (auth.event_count or 0) + 1
    ev = DecisionEvent(
        authorization_id=auth.id,
        seq=auth.event_count,
        at=at,
        kind=kind,
        reason=reason,
        best_quote_id=best.quote_id if best else None,
        best_route=best.route_id if best else None,
        best_net_mxn=best.net_mxn if best else None,
        payload=payload or {},
    )
    db.add(ev)
    return ev
