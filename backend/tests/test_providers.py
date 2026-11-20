"""Q5 and fixture-script behaviour."""

import asyncio
from datetime import timedelta
from decimal import Decimal as D

from rampscout.providers.base import QuoteRequest
from rampscout.providers.fixture import MX_SPEI, fixture_providers
from rampscout.providers.registry import fetch_all
from tests.factories import NOW

TTL = timedelta(seconds=120)


def req(tick=0):
    return QuoteRequest(amount_usdc=D("600"), destination_rail=MX_SPEI, now=NOW, tick=tick)


def nets(result):
    return {q.route_id: str(q.net_mxn) for q in result.quotes}


def test_tick_script_matches_brief():
    p = fixture_providers(TTL)
    assert nets(asyncio.run(fetch_all(p, req(0), 1))) == {"A": "9976.30", "B": "9993.25"}
    assert nets(asyncio.run(fetch_all(p, req(1), 1))) == {"A": "9976.30", "B": "10023.20"}
    # Terms persist after the last scripted change.
    assert nets(asyncio.run(fetch_all(p, req(7), 1))) == {"A": "9976.30", "B": "10023.20"}


def test_every_fetch_gets_fresh_quote_id_and_expiry():
    p = fixture_providers(TTL)
    first = asyncio.run(fetch_all(p, req(), 1)).quotes
    second = asyncio.run(fetch_all(p, req(), 1)).quotes
    assert {q.quote_id for q in first}.isdisjoint({q.quote_id for q in second})
    assert all(q.expires_at == NOW + TTL for q in first)


def test_provider_down_keeps_other_quote_and_reports_error():
    p = fixture_providers(TTL, {"provider_a_down": True})
    r = asyncio.run(fetch_all(p, req(), 1))
    assert nets(r) == {"B": "9993.25"}
    assert [(e.route_id, e.kind) for e in r.errors] == [("A", "unavailable")]


def test_provider_timeout_is_bounded_and_isolated():
    p = fixture_providers(TTL, {"provider_b_timeout": True})
    loop_start = asyncio.new_event_loop()
    try:
        t0 = loop_start.time()
        r = loop_start.run_until_complete(fetch_all(p, req(), 0.2))
        elapsed = loop_start.time() - t0
    finally:
        loop_start.close()
    assert elapsed < 1.0
    assert nets(r) == {"A": "9976.30"}
    assert [(e.route_id, e.kind) for e in r.errors] == [("B", "timeout")]
