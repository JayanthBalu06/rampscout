"""Background worker: evaluates due watches for every session, forever.

Safe to run several copies: claims use FOR UPDATE SKIP LOCKED and executions are unique
per authorization. In fixture mode a watch only becomes due when its session's demo clock
advances; in system mode it follows the wall clock. Each loop first reconciles
any settlement left mid-flight.
"""

from __future__ import annotations

import signal
import time
from types import FrameType

import structlog

from rampscout.agent.evaluate import run_due
from rampscout.config import get_settings
from rampscout.logging import configure_logging
from rampscout.settlement.reconcile import reconcile

log = structlog.get_logger()
_running = True


def _stop(signum: int, _frame: FrameType | None) -> None:
    global _running
    log.info("worker.stopping", signal=signum)
    _running = False


def tick_once() -> int:
    settings = get_settings()
    recovered = reconcile(settings)
    if recovered:
        log.info("settlement.reconciled", count=recovered)
    outcomes = run_due(settings)
    for o in outcomes:
        log.info("watch.evaluated", authorization_id=str(o.authorization_id), status=o.status)
    return len(outcomes)


def main() -> None:
    configure_logging()
    settings = get_settings()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker.start", clock_mode=settings.clock_mode, loop_s=settings.worker_loop_seconds)
    # Startup recovery: anything left mid-flight by a crash is resolved before new work.
    log.info("worker.startup_reconcile", count=reconcile(settings))
    while _running:
        try:
            tick_once()
        except Exception:
            log.exception("worker.loop_error")
        time.sleep(settings.worker_loop_seconds)
    log.info("worker.stopped")


if __name__ == "__main__":
    main()
