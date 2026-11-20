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
TABLES = ["quote_snapshots", "destinations", "demo_sessions"]


@pytest.fixture(scope="session", autouse=True)
def _test_db() -> Iterator[None]:
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
