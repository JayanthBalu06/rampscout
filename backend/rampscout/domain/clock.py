"""Clocks. The fixture clock makes demos reproducible; the system clock drives live polling.

Both expose `now()` and `tick` so the *same* decision code runs in either mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    @property
    def tick(self) -> int: ...

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class FixtureClock:
    at: datetime
    tick: int = 0

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("FixtureClock requires an aware datetime")

    def now(self) -> datetime:
        return self.at.astimezone(UTC)

    def advanced(self, step: timedelta) -> FixtureClock:
        return FixtureClock(at=self.at + step, tick=self.tick + 1)


@dataclass(frozen=True)
class SystemClock:
    """Wall clock. `tick` counts elapsed tick-lengths since `start` so fixture
    providers follow their script at real-time pace."""

    start: datetime
    tick_length: timedelta

    def now(self) -> datetime:
        return datetime.now(UTC)

    @property
    def tick(self) -> int:
        return max(0, int((self.now() - self.start) / self.tick_length))


class DeadlineResolutionError(ValueError):
    pass


def resolve_local_deadline(local: datetime, time_zone: str) -> datetime:
    """Turn a wall-clock time in an IANA zone into a UTC instant.

    Rejects times that do not exist (spring-forward gaps) or occur twice (fall-back
    overlaps) rather than guessing. The user must disambiguate.
    """
    if local.tzinfo is not None:
        raise DeadlineResolutionError("expected a naive local time plus a time zone")
    try:
        tz = ZoneInfo(time_zone)
    except (KeyError, ValueError) as exc:
        raise DeadlineResolutionError(f"unknown time zone: {time_zone}") from exc

    first = local.replace(tzinfo=tz, fold=0)
    second = local.replace(tzinfo=tz, fold=1)
    if first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != local:
        raise DeadlineResolutionError(f"{local.isoformat()} does not exist in {time_zone}")
    if first.utcoffset() != second.utcoffset():
        raise DeadlineResolutionError(f"{local.isoformat()} is ambiguous in {time_zone}")
    return first.astimezone(UTC)
