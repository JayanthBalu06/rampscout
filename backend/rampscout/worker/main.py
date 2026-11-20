"""Worker entrypoint. Phase 2 adds watch evaluation; Phase 3 adds reconciliation."""

from __future__ import annotations

import time

import structlog

from rampscout.config import get_settings

log = structlog.get_logger()


def main() -> None:
    settings = get_settings()
    log.info("worker.start", poll_interval=settings.poll_interval_seconds)
    while True:
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
