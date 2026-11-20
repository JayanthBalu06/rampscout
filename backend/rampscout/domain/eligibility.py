"""Eligibility filtering and ranking. Pure functions over quotes; no I/O."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from rampscout.domain.quotes import Quote


class ExclusionReason(StrEnum):
    UNSUPPORTED_DESTINATION = "unsupported_destination"
    QUOTE_EXPIRED = "quote_expired"
    OVER_BUDGET = "over_budget"
    PAYOUT_NOT_POSITIVE = "payout_not_positive"
    ARRIVES_AFTER_DEADLINE = "arrives_after_deadline"


@dataclass(frozen=True)
class Constraints:
    budget_usdc: Decimal
    destination_rail: str
    deadline: datetime | None
    safety_margin: timedelta


@dataclass(frozen=True)
class Exclusion:
    quote: Quote
    reasons: tuple[ExclusionReason, ...]
    detail: str


def exclusion_reasons(quote: Quote, c: Constraints, now: datetime) -> list[ExclusionReason]:
    reasons: list[ExclusionReason] = []
    if c.destination_rail not in quote.supported_rails:
        reasons.append(ExclusionReason.UNSUPPORTED_DESTINATION)
    if now >= quote.expires_at:
        reasons.append(ExclusionReason.QUOTE_EXPIRED)
    if quote.input_usdc > c.budget_usdc:
        reasons.append(ExclusionReason.OVER_BUDGET)
    if not quote.breakdown.viable:
        reasons.append(ExclusionReason.PAYOUT_NOT_POSITIVE)
    if c.deadline is not None and quote.arrival_at(now) + c.safety_margin > c.deadline:
        reasons.append(ExclusionReason.ARRIVES_AFTER_DEADLINE)
    return reasons


def _detail(quote: Quote, reasons: Sequence[ExclusionReason], c: Constraints, now: datetime) -> str:
    parts: list[str] = []
    for r in reasons:
        if r is ExclusionReason.ARRIVES_AFTER_DEADLINE and c.deadline is not None:
            late_by = quote.arrival_at(now) + c.safety_margin - c.deadline
            parts.append(
                f"arrives in {int(quote.eta.total_seconds() // 60)} min + "
                f"{int(c.safety_margin.total_seconds() // 60)} min safety margin, "
                f"{int(late_by.total_seconds() // 60)} min past the deadline"
            )
        elif r is ExclusionReason.QUOTE_EXPIRED:
            parts.append("quote expired")
        elif r is ExclusionReason.OVER_BUDGET:
            parts.append(f"needs {quote.input_usdc} USDC, budget is {c.budget_usdc}")
        elif r is ExclusionReason.UNSUPPORTED_DESTINATION:
            parts.append(f"does not pay out to {c.destination_rail}")
        else:
            parts.append("fees exceed the amount")
    return "; ".join(parts)


def partition(
    quotes: Iterable[Quote], c: Constraints, now: datetime
) -> tuple[list[Quote], list[Exclusion]]:
    eligible: list[Quote] = []
    excluded: list[Exclusion] = []
    for q in quotes:
        reasons = exclusion_reasons(q, c, now)
        if reasons:
            excluded.append(Exclusion(q, tuple(reasons), _detail(q, reasons, c, now)))
        else:
            eligible.append(q)
    return eligible, excluded


def rank(quotes: Iterable[Quote]) -> list[Quote]:
    """Highest net payout first; ties -> earlier arrival; then stable route id."""
    return sorted(quotes, key=lambda q: (-q.net_mxn, q.eta, q.route_id))
