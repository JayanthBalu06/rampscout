"""Fetch quotes from every provider concurrently, each under its own timeout.

A slow or failing provider never blocks or poisons the others; its failure is reported
separately from quotes that were merely ineligible or below target.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import structlog

from rampscout.domain.quotes import Quote
from rampscout.providers.base import ProviderUnavailable, QuoteProvider, QuoteRequest

log = structlog.get_logger()

ErrorKind = Literal["timeout", "unavailable", "error"]


@dataclass(frozen=True)
class ProviderError:
    provider_id: str
    route_id: str
    kind: ErrorKind
    message: str


@dataclass(frozen=True)
class FetchResult:
    quotes: tuple[Quote, ...]
    errors: tuple[ProviderError, ...]


async def _one(p: QuoteProvider, req: QuoteRequest, timeout_s: float) -> Quote | ProviderError:
    try:
        return await asyncio.wait_for(p.get_quote(req), timeout=timeout_s)
    except TimeoutError:
        return ProviderError(p.provider_id, p.route_id, "timeout", f"no answer in {timeout_s:g}s")
    except ProviderUnavailable as exc:
        return ProviderError(p.provider_id, p.route_id, "unavailable", str(exc))
    except Exception as exc:  # adapter bug or bad payload: isolate it
        log.warning("provider.error", provider=p.provider_id, error=type(exc).__name__)
        return ProviderError(p.provider_id, p.route_id, "error", type(exc).__name__)


async def fetch_all(
    providers: Sequence[QuoteProvider], req: QuoteRequest, timeout_s: float
) -> FetchResult:
    results = await asyncio.gather(*(_one(p, req, timeout_s) for p in providers))
    return FetchResult(
        quotes=tuple(r for r in results if isinstance(r, Quote)),
        errors=tuple(r for r in results if isinstance(r, ProviderError)),
    )
