"""Structured logging with secret redaction.

Signing material and signed transaction bytes must never reach logs. Any event key that
looks like one is replaced before rendering, whatever code logged it."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEYS = re.compile(
    r"(private_?key|secret|signed_?tx|raw_?tx|raw_transaction|api_?key|mnemonic|seed)", re.I
)
REDACTED = "[redacted]"


def redact(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        value = event[key]
        if SENSITIVE_KEYS.search(key) or isinstance(value, bytes | bytearray):
            event[key] = REDACTED
    return event


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
