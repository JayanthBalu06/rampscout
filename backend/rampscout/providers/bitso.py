"""Live market data from Bitso's public API (no key needed).

Fetches every order book the router uses concurrently, each with a bounded timeout, plus the
published taker fees from /available_books. A failed book is reported, not fatal. If the API
is unreachable the recorded snapshot can stand in, labeled "recorded".

Bitso lists no USDC market, so USDC enters through explicitly labeled assumption legs
(USDC→USDT and USDC→USD at 1:1 minus a small swap fee).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx

from rampscout.domain.routing import Leg, OrderBookLeg, RateLeg

API = "https://api.bitso.com/v3"
BOOKS = (
    "usdt_mxn",
    "usd_mxn",
    "usd_usdt",
    "usdt_ars",
    "usd_ars",
    "usdt_cop",
    "usd_cop",
    "usdt_brl",
    "usd_brl",
    "btc_mxn",
    "btc_usdt",
    "eth_mxn",
    "eth_usdt",
)
SNAPSHOT = Path(__file__).parent / "data" / "bitso_snapshot.json"

Level = tuple[Decimal, Decimal]


@dataclass(frozen=True)
class Book:
    name: str
    bids: tuple[Level, ...]  # best (highest) first
    asks: tuple[Level, ...]  # best (lowest) first
    taker_fee: Decimal
    minimum_amount: Decimal

    @property
    def base(self) -> str:
        return self.name.split("_")[0].upper()

    @property
    def quote(self) -> str:
        return self.name.split("_")[1].upper()


@dataclass(frozen=True)
class Market:
    books: dict[str, Book]
    source: Literal["live", "recorded"]
    as_of: datetime
    errors: dict[str, str] = field(default_factory=dict)


def _levels(rows: list[Any]) -> tuple[Level, ...]:
    out = []
    for r in rows:
        price, amount = (r["price"], r["amount"]) if isinstance(r, dict) else (r[0], r[1])
        out.append((Decimal(price), Decimal(amount)))
    return tuple(out)


async def fetch_market(timeout_s: float = 4.0, client: httpx.AsyncClient | None = None) -> Market:
    own = client is None
    c = client or httpx.AsyncClient(base_url=API, timeout=timeout_s)
    errors: dict[str, str] = {}
    try:
        meta_resp = await c.get("/available_books/")
        meta_resp.raise_for_status()
        meta = {b["book"]: b for b in meta_resp.json()["payload"]}

        async def one(name: str) -> Book | None:
            if name not in meta:
                errors[name] = "not listed"
                return None
            try:
                r = await asyncio.wait_for(
                    c.get("/order_book/", params={"book": name, "aggregate": "true"}), timeout_s
                )
                r.raise_for_status()
                p = r.json()["payload"]
                return Book(
                    name=name,
                    bids=_levels(p["bids"]),
                    asks=_levels(p["asks"]),
                    taker_fee=Decimal(meta[name]["fees"]["flat_rate"]["taker"]),
                    minimum_amount=Decimal(meta[name]["minimum_amount"]),
                )
            except (httpx.HTTPError, TimeoutError, KeyError, ValueError) as exc:
                errors[name] = type(exc).__name__
                return None

        books = await asyncio.gather(*(one(n) for n in BOOKS))
    finally:
        if own:
            await c.aclose()
    return Market(
        books={b.name: b for b in books if b is not None},
        source="live",
        as_of=datetime.now(UTC),
        errors=errors,
    )


def load_recorded(path: Path = SNAPSHOT) -> Market:
    data = json.loads(path.read_text())
    books = {
        name: Book(
            name=name,
            bids=_levels(b["bids"]),
            asks=_levels(b["asks"]),
            taker_fee=Decimal(b["taker_fee"]),
            minimum_amount=Decimal(b["minimum_amount"]),
        )
        for name, b in data["books"].items()
    }
    return Market(
        books=books,
        source="recorded",
        as_of=datetime.fromisoformat(data["recorded_at"]),
    )


_cache: tuple[float, Market] | None = None


def get_market(source: Literal["live", "recorded"], *, cache_s: float = 10.0) -> Market:
    """Live market (cached briefly so a burst of requests doesn't hammer Bitso), falling
    back to nothing: callers decide whether to use the recorded snapshot."""
    global _cache
    if source == "recorded":
        return load_recorded()
    if _cache and time.monotonic() - _cache[0] < cache_s:
        return _cache[1]
    market = asyncio.run(fetch_market())
    if market.books:
        _cache = (time.monotonic(), market)
    return market


def legs_from_market(market: Market, *, stable_swap_fee: Decimal) -> list[Leg]:
    legs: list[Leg] = []
    for b in market.books.values():
        for side in ("sell_base", "buy_base"):
            levels = b.bids if side == "sell_base" else b.asks
            if not levels:
                continue
            legs.append(
                OrderBookLeg(
                    leg_id=f"bitso:{b.name}:{'sell' if side == 'sell_base' else 'buy'}",
                    venue="Bitso",
                    base=b.base,
                    quote=b.quote,
                    side=side,
                    levels=levels,
                    taker_fee=b.taker_fee,
                    minimum_base=b.minimum_amount,
                    source=market.source,
                )
            )
    for target in ("USDT", "USD"):
        legs.append(
            RateLeg(
                leg_id=f"swap:usdc_{target.lower()}",
                venue="Stablecoin swap (assumed)",
                from_ccy="USDC",
                to_ccy=target,
                rate=Decimal(1),
                pct_fee=stable_swap_fee,
                fixed_fee=Decimal(0),
                source="assumption",
                eta=timedelta(0),
                kind="swap",
                note=f"Bitso has no USDC market; assumed 1:1 with a "
                f"{stable_swap_fee * 100:.2f}% swap fee",
            )
        )
    return legs
