"""Multi-hop route search over conversion legs. Pure: no I/O.

A *leg* converts one currency into another at some venue (an exchange order book, an
assumed stablecoin swap, ...). A *route* chains legs from the sender's currency to the
recipient's. Every simple path up to MAX_HOPS is priced exactly with Decimal arithmetic.
With a handful of currencies that is a few dozen paths, so exhaustive search is exact and
instant. (Shortest-path tricks such as Dijkstra over -log(rate) are only valid when every
fee is a pure percentage; fixed fees, order-book depth and per-hop rounding break that.)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Literal, Protocol

from rampscout.domain.currencies import floor_to

Source = Literal["live", "recorded", "assumption", "fixture", "real-onchain", "simulated"]
ZERO = Decimal(0)


@dataclass(frozen=True)
class Hop:
    leg_id: str
    kind: Literal["orderbook", "swap", "transfer", "payout"]
    venue: str
    from_ccy: str
    to_ccy: str
    amount_in: Decimal
    gross_out: Decimal
    fee: Decimal  # charged in to_ccy
    amount_out: Decimal  # after fee, floored to to_ccy precision
    avg_price: Decimal | None  # to_ccy per from_ccy, before fees
    eta: timedelta
    source: Source
    note: str = ""


class Leg(Protocol):
    @property
    def leg_id(self) -> str: ...
    @property
    def from_ccy(self) -> str: ...
    @property
    def to_ccy(self) -> str: ...

    def convert(self, amount: Decimal) -> Hop | None:
        """Price converting `amount` of from_ccy. None if not possible at this size."""
        ...


@dataclass(frozen=True)
class OrderBookLeg:
    """Taker trade against one side of an exchange order book.

    book `base_quote`: selling base walks the bids (best first); buying base spends quote
    currency walking the asks. The taker fee is charged on what you receive."""

    leg_id: str
    venue: str
    base: str
    quote: str
    side: Literal["sell_base", "buy_base"]
    levels: tuple[tuple[Decimal, Decimal], ...]  # (price in quote, amount in base)
    taker_fee: Decimal
    minimum_base: Decimal
    source: Source
    eta: timedelta = timedelta(0)

    @property
    def from_ccy(self) -> str:
        return self.base if self.side == "sell_base" else self.quote

    @property
    def to_ccy(self) -> str:
        return self.quote if self.side == "sell_base" else self.base

    def convert(self, amount: Decimal) -> Hop | None:
        if amount <= 0:
            return None
        remaining = amount
        gross = ZERO
        base_traded = ZERO
        for price, size in self.levels:
            if remaining <= 0:
                break
            if self.side == "sell_base":
                take = min(remaining, size)
                gross += take * price
                base_traded += take
                remaining -= take
            else:  # spend quote to buy base
                affordable = remaining / price
                take = min(affordable, size)
                gross += take
                base_traded += take
                remaining -= take * price
        if remaining > Decimal("1e-12") or base_traded < self.minimum_base:
            return None  # not enough depth, or below the venue minimum
        fee = gross * self.taker_fee
        out = floor_to(self.to_ccy, gross - fee)
        if out <= 0:
            return None
        return Hop(
            leg_id=self.leg_id,
            kind="orderbook",
            venue=self.venue,
            from_ccy=self.from_ccy,
            to_ccy=self.to_ccy,
            amount_in=amount,
            gross_out=gross,
            fee=fee,
            amount_out=out,
            avg_price=gross / amount,
            eta=self.eta,
            source=self.source,
            note=f"{self.base}_{self.quote} {'bids' if self.side == 'sell_base' else 'asks'}, "
            f"taker fee {self.taker_fee * 100:.2f}%",
        )


@dataclass(frozen=True)
class RateLeg:
    """Fixed-rate conversion with a percentage and/or fixed fee (in the output currency)."""

    leg_id: str
    venue: str
    from_ccy: str
    to_ccy: str
    rate: Decimal
    pct_fee: Decimal
    fixed_fee: Decimal
    source: Source
    eta: timedelta = timedelta(0)
    kind: Literal["swap", "transfer", "payout"] = "swap"
    note: str = ""

    def convert(self, amount: Decimal) -> Hop | None:
        if amount <= 0:
            return None
        gross = amount * self.rate
        fee = gross * self.pct_fee + self.fixed_fee
        out = floor_to(self.to_ccy, gross - fee)
        if out <= 0:
            return None
        return Hop(
            leg_id=self.leg_id,
            kind=self.kind,
            venue=self.venue,
            from_ccy=self.from_ccy,
            to_ccy=self.to_ccy,
            amount_in=amount,
            gross_out=gross,
            fee=fee,
            amount_out=out,
            avg_price=self.rate,
            eta=self.eta,
            source=self.source,
            note=self.note,
        )


@dataclass(frozen=True)
class Route:
    hops: tuple[Hop, ...]
    amount_in: Decimal
    from_ccy: str
    to_ccy: str
    amount_out: Decimal
    eta: timedelta
    leg_ids: tuple[str, ...] = field(default=())

    @property
    def path(self) -> str:
        """Currencies visited, e.g. "USDC → USD → MXN" (transfers/payouts don't change
        currency, so they don't appear)."""
        ccys = [self.from_ccy]
        for h in self.hops:
            if h.to_ccy != ccys[-1]:
                ccys.append(h.to_ccy)
        return " → ".join(ccys)

    @property
    def conversion_hops(self) -> int:
        return sum(1 for h in self.hops if h.kind in ("orderbook", "swap"))


def price_path(legs: Sequence[Leg], amount: Decimal, from_ccy: str) -> Route | None:
    """Price a specific chain of legs; None if any hop is not possible at its size."""
    hops: list[Hop] = []
    current = amount
    ccy = from_ccy
    for leg in legs:
        if leg.from_ccy != ccy:
            raise ValueError(f"leg {leg.leg_id} expects {leg.from_ccy}, got {ccy}")
        hop = leg.convert(current)
        if hop is None:
            return None
        hops.append(hop)
        current, ccy = hop.amount_out, hop.to_ccy
    return Route(
        hops=tuple(hops),
        amount_in=amount,
        from_ccy=from_ccy,
        to_ccy=ccy,
        amount_out=current,
        eta=sum((h.eta for h in hops), timedelta(0)),
        leg_ids=tuple(leg.leg_id for leg in legs),
    )


def find_routes(
    legs: Iterable[Leg],
    *,
    from_ccy: str,
    to_ccy: str,
    amount: Decimal,
    max_hops: int = 4,
    prefix: Sequence[Leg] = (),
    suffix: Sequence[Leg] = (),
) -> list[Route]:
    """All viable simple conversion paths from_ccy → to_ccy, ranked best first.

    `prefix` legs run before the search (e.g. the onchain deposit into the exchange) and
    `suffix` legs after it (e.g. the bank payout). Ranking: most received, then faster,
    then fewer conversions, then path name (stable)."""
    by_from: dict[str, list[Leg]] = {}
    for leg in legs:
        by_from.setdefault(leg.from_ccy, []).append(leg)

    found: list[Route] = []

    def dfs(ccy: str, chain: list[Leg], seen: set[str]) -> None:
        if ccy == to_ccy:
            route = price_path(
                [*prefix, *chain, *suffix], amount, prefix[0].from_ccy if prefix else from_ccy
            )
            if route is not None:
                found.append(route)
            return
        if len(chain) >= max_hops:
            return
        for leg in by_from.get(ccy, []):
            if leg.to_ccy in seen:
                continue
            dfs(leg.to_ccy, [*chain, leg], seen | {leg.to_ccy})

    dfs(from_ccy, [], {from_ccy})
    return rank(found)


def rank(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (-r.amount_out, r.eta, r.conversion_hops, r.path))
