from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rampscout.config import get_settings
from rampscout.db import session as db_session


@pytest.fixture(scope="session", autouse=True)
def _test_db() -> Iterator[None]:
    db_session.configure(get_settings().test_database_url)
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    from rampscout.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
