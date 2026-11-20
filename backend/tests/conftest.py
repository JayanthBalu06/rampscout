from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from rampscout.config import Settings, get_settings
from rampscout.db import session as db_session

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = [
    "route_quotes",
    "contacts",
    "sim_chain_txs",
    "executions",
    "notifications",
    "decision_events",
    "authorizations",
    "quote_snapshots",
    "destinations",
    "demo_sessions",
]


@pytest.fixture(scope="session", autouse=True)
def _hermetic_settings() -> None:
    """Tests use code defaults for everything except the database, whatever .env says:
    never a real chain, wallet, model API or live market."""
    s = get_settings()
    for name, f in Settings.model_fields.items():
        if name not in ("database_url", "test_database_url"):
            setattr(s, name, f.get_default(call_default_factory=True))
    s.market_source = "recorded"


@pytest.fixture(scope="session", autouse=True)
def _test_db(_hermetic_settings: None) -> Iterator[None]:
    url = get_settings().test_database_url
    os.environ["ALEMBIC_DATABASE_URL"] = url
    command.upgrade(Config(os.path.join(BACKEND, "alembic.ini")), "head")
    db_session.configure(url)
    yield


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    with db_session.engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    yield


@pytest.fixture
def settings() -> Iterator[Settings]:
    """The live settings object; changes are reverted after the test."""
    s = get_settings()
    snapshot = s.model_dump()
    yield s
    for k, v in snapshot.items():
        setattr(s, k, v)


@pytest.fixture
def client() -> Iterator[TestClient]:
    from rampscout.api.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def destination_id(client: TestClient) -> str:
    return str(client.get("/destinations").json()[0]["id"])


DEADLINE_5PM = {"deadline_local": "2026-11-27T17:00:00", "time_zone": "America/Mexico_City"}


@pytest.fixture
def make_watch(client, destination_id):
    """POST an authorization; returns the parsed response (raises on non-2xx)."""
    counter = {"n": 0}

    def _make(mode="notify", min_payout="10000", key=None, expect=201, **overrides):
        counter["n"] += 1
        body = {
            "mode": mode,
            "amount_usdc": "600",
            "min_payout_mxn": min_payout,
            "destination_id": destination_id,
            **DEADLINE_5PM,
            **overrides,
        }
        body = {k: v for k, v in body.items() if v is not None}
        r = client.post(
            "/authorizations",
            json=body,
            headers={"Idempotency-Key": key or f"test-{counter['n']}"},
        )
        assert r.status_code == expect, r.text
        return r.json()

    return _make


@pytest.fixture(autouse=True)
def _no_live_market(monkeypatch):
    """Tests must never reach Bitso over the network (results would depend on live prices)."""
    from rampscout.providers import bitso

    async def refuse(*args, **kwargs):
        raise AssertionError("test tried to fetch live Bitso data; use the recorded snapshot")

    monkeypatch.setattr(bitso, "fetch_market", refuse)
    monkeypatch.setattr(bitso, "_cache", None)
