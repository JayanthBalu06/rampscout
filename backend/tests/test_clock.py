from datetime import UTC, datetime

import pytest

from rampscout.domain.clock import DeadlineResolutionError, FixtureClock, resolve_local_deadline


def test_friday_5pm_mexico_city_resolves_to_utc():
    utc = resolve_local_deadline(datetime(2026, 11, 27, 17, 0), "America/Mexico_City")
    assert utc == datetime(2026, 11, 27, 23, 0, tzinfo=UTC)


def test_nonexistent_local_time_is_rejected():
    with pytest.raises(DeadlineResolutionError, match="does not exist"):
        resolve_local_deadline(datetime(2026, 3, 8, 2, 30), "America/New_York")


def test_ambiguous_local_time_is_rejected():
    with pytest.raises(DeadlineResolutionError, match="ambiguous"):
        resolve_local_deadline(datetime(2026, 11, 1, 1, 30), "America/New_York")


def test_unknown_zone_rejected():
    with pytest.raises(DeadlineResolutionError):
        resolve_local_deadline(datetime(2026, 11, 27, 17, 0), "Mars/Olympus_Mons")


def test_fixture_clock_requires_aware_and_advances():
    with pytest.raises(ValueError):
        FixtureClock(at=datetime(2026, 11, 27, 17, 0))
    c = FixtureClock(at=datetime(2026, 11, 27, 17, 0, tzinfo=UTC)).advanced(
        __import__("datetime").timedelta(minutes=15)
    )
    assert c.tick == 1 and c.now().minute == 15
