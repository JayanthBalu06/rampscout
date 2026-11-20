"""The agent's per-check decision. Pure: same inputs, same decision, in demo or live mode."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from rampscout.domain.eligibility import Exclusion
from rampscout.domain.money import fmt_mxn
from rampscout.domain.quotes import Quote


class DecisionKind(StrEnum):
    NO_ELIGIBLE_ROUTE = "no_eligible_route"
    BELOW_TARGET = "waiting_below_target"
    MATCHED = "matched"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    reason: str
    best: Quote | None


def decide(
    *,
    min_payout_mxn: Decimal,
    ranked: Sequence[Quote],
    excluded: Sequence[Exclusion],
    provider_errors: int,
) -> Decision:
    """Compare the best *eligible* quote with the user's minimum. Never matches below it."""
    if not ranked:
        parts = []
        if excluded:
            parts.append("; ".join(f"Route {e.quote.route_id}: {e.detail}" for e in excluded))
        if provider_errors:
            parts.append(f"{provider_errors} provider(s) did not answer")
        why = ". ".join(parts) if parts else "no provider returned a quote"
        return Decision(DecisionKind.NO_ELIGIBLE_ROUTE, f"No eligible route ({why}).", None)

    best = ranked[0]
    if best.net_mxn < min_payout_mxn:
        gap = min_payout_mxn - best.net_mxn
        return Decision(
            DecisionKind.BELOW_TARGET,
            f"Best is Route {best.route_id} at {fmt_mxn(best.net_mxn)}, "
            f"{fmt_mxn(gap)} short of your {fmt_mxn(min_payout_mxn)} minimum.",
            best,
        )
    return Decision(
        DecisionKind.MATCHED,
        f"Route {best.route_id} pays {fmt_mxn(best.net_mxn)}, "
        f"meeting your {fmt_mxn(min_payout_mxn)} minimum.",
        best,
    )


def next_check(interval_end: datetime, deadline: datetime | None) -> datetime:
    """Next evaluation time, never later than the deadline (where the watch is closed)."""
    if deadline is not None and interval_end > deadline:
        return deadline
    return interval_end
