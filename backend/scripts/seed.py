"""Seed the demo user's destination and print a fresh demo session id.

Usage (from backend/):  python -m scripts.seed
"""

from __future__ import annotations

from rampscout.config import get_settings
from rampscout.db.session import SessionLocal
from rampscout.services.sessions import create_session, ensure_demo_destination


def main() -> None:
    with SessionLocal() as db:
        dest = ensure_demo_destination(db)
        session = create_session(db, get_settings())
        db.commit()
        print(f"destination: {dest.alias} ({dest.masked_account}) id={dest.id}")
        print(f"demo session: {session.id} clock={session.clock_now.isoformat()} tick=0")


if __name__ == "__main__":
    main()
