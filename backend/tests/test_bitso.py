"""Bitso adapter: parsing, per-book failure isolation, and the recorded snapshot."""

import asyncio
from decimal import Decimal as D

import httpx

from rampscout.domain.routing import find_routes
from rampscout.providers.bitso import BOOKS, fetch_market, legs_from_market, load_recorded


def fake_api(fail: set[str] = frozenset()):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/available_books/"):
            payload = [
                {"book": b, "minimum_amount": "0.01", "fees": {"flat_rate": {"taker": "0.0078"}}}
                for b in BOOKS
            ]
            return httpx.Response(200, json={"success": True, "payload": payload})
        book = request.url.params["book"]
        if book in fail:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "payload": {
                    "bids": [{"price": "19.00", "amount": "1000"}],
                    "asks": [{"price": "19.10", "amount": "1000"}],
                }
            },
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.bitso.com/v3"
    )


def test_fetch_market_parses_books_and_fees():
    m = asyncio.run(fetch_market(client=fake_api()))
    assert m.source == "live" and set(m.books) == set(BOOKS)
    b = m.books["usdt_mxn"]
    assert (b.base, b.quote, b.taker_fee) == ("USDT", "MXN", D("0.0078"))
    assert b.bids[0] == (D("19.00"), D("1000"))


def test_one_failing_book_does_not_sink_the_rest():
    m = asyncio.run(fetch_market(client=fake_api({"usd_mxn"})))
    assert "usd_mxn" not in m.books and "usdt_mxn" in m.books
    assert m.errors["usd_mxn"] == "HTTPStatusError"


def test_recorded_snapshot_yields_routes_to_every_supported_currency():
    m = load_recorded()
    assert m.source == "recorded"
    legs = legs_from_market(m, stable_swap_fee=D("0.0005"))
    assert any(leg.leg_id == "swap:usdc_usdt" for leg in legs)
    for ccy in ("MXN", "ARS", "COP", "BRL"):
        routes = find_routes(legs, from_ccy="USDC", to_ccy=ccy, amount=D("600"), max_hops=3)
        assert routes, ccy
        assert routes[0].path.startswith("USDC → ")
        assert routes == sorted(routes, key=lambda r: -r.amount_out)  # best first
