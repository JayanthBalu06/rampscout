"""Multi-hop routing: order-book walking, fees, depth, minimums, and exact ranking."""

from datetime import timedelta
from decimal import Decimal as D

from rampscout.domain.routing import OrderBookLeg, RateLeg, find_routes, price_path


def book(leg_id, base, quote, side, levels, fee="0.0078", minimum="0.01"):
    return OrderBookLeg(
        leg_id=leg_id,
        venue="Bitso",
        base=base,
        quote=quote,
        side=side,
        levels=tuple((D(p), D(a)) for p, a in levels),
        taker_fee=D(fee),
        minimum_base=D(minimum),
        source="recorded",
    )


def swap(leg_id, a, b, rate="1", pct="0", fixed="0", eta=0):
    return RateLeg(
        leg_id=leg_id,
        venue="test",
        from_ccy=a,
        to_ccy=b,
        rate=D(rate),
        pct_fee=D(pct),
        fixed_fee=D(fixed),
        source="assumption",
        eta=timedelta(minutes=eta),
    )


def test_selling_base_walks_bids_and_charges_taker_fee_on_proceeds():
    leg = book("b", "USDT", "MXN", "sell_base", [("19.00", "100"), ("18.90", "1000")])
    hop = leg.convert(D("150"))
    # 100 @ 19.00 + 50 @ 18.90 = 2845.00 gross; 0.78% fee = 22.191 -> 2822.809 -> floor 2822.80
    assert hop.gross_out == D("2845.00")
    assert hop.amount_out == D("2822.80")
    assert hop.avg_price == D("2845.00") / D("150")


def test_buying_base_spends_quote_walking_asks():
    leg = book("b", "BTC", "MXN", "buy_base", [("2000000", "0.001"), ("2100000", "1")], minimum="0")
    hop = leg.convert(D("4100"))
    # 0.001 BTC costs 2000; remaining 2100 buys 0.001 at 2.1M -> 0.002 BTC gross
    assert hop.gross_out == D("0.002")
    assert hop.amount_out == D("0.00198440")  # minus 0.78%, floored to 8 dp


def test_insufficient_depth_or_below_minimum_is_not_viable():
    shallow = book("b", "USDT", "MXN", "sell_base", [("19", "10")])
    assert shallow.convert(D("11")) is None
    assert (
        book("b", "USDT", "MXN", "sell_base", [("19", "10")], minimum="5").convert(D("1")) is None
    )


def test_multi_hop_beats_direct_when_cheaper():
    legs = [
        swap("direct", "USDC", "MXN", rate="18.00", pct="0.02"),  # 2% fee
        swap("to_usd", "USDC", "USD", pct="0.0005"),
        book("usd_mxn", "USD", "MXN", "sell_base", [("18.10", "1000")]),
    ]
    routes = find_routes(legs, from_ccy="USDC", to_ccy="MXN", amount=D("600"))
    assert [r.path for r in routes] == ["USDC → USD → MXN", "USDC → MXN"]
    assert routes[0].amount_out > routes[1].amount_out


def test_fixed_fee_flips_ranking_by_size():
    """A leg with a better rate but a fixed fee loses on small amounts and wins on large
    ones: something a percentage-only shortest path cannot express."""
    legs = [
        swap("pct", "USDC", "MXN", rate="18.00", pct="0.01"),
        swap("fixed", "USDC", "MXN", rate="18.10", fixed="100"),
    ]
    small = find_routes(legs, from_ccy="USDC", to_ccy="MXN", amount=D("50"))
    large = find_routes(legs, from_ccy="USDC", to_ccy="MXN", amount=D("5000"))
    assert small[0].leg_ids == ("pct",)
    assert large[0].leg_ids == ("fixed",)


def test_per_hop_rounding_and_no_cycles():
    legs = [
        swap("a", "USDC", "USDT", pct="0.0005"),
        swap("b", "USDT", "USDC"),  # would create a cycle
        book("c", "USDT", "MXN", "sell_base", [("19", "10000")]),
    ]
    routes = find_routes(legs, from_ccy="USDC", to_ccy="MXN", amount=D("600.123456"))
    assert len(routes) == 1
    hop1 = routes[0].hops[0]
    assert hop1.amount_out == D("599.823394")  # 6 dp USDT, floored
    assert routes[0].amount_out == routes[0].hops[-1].amount_out


def test_prefix_and_suffix_legs_wrap_the_search():
    transfer = swap("xfer", "USDC", "USDC", eta=1)
    payout = swap("payout", "MXN", "MXN", eta=10)
    legs = [swap("conv", "USDC", "MXN", rate="18")]
    (r,) = find_routes(
        legs, from_ccy="USDC", to_ccy="MXN", amount=D("10"), prefix=[transfer], suffix=[payout]
    )
    assert r.leg_ids == ("xfer", "conv", "payout")
    assert r.path == "USDC → MXN"
    assert r.eta == timedelta(minutes=11)


def test_same_currency_route_is_just_the_transfer():
    transfer = swap("xfer", "USDC", "USDC", eta=1)
    (r,) = find_routes([], from_ccy="USDC", to_ccy="USDC", amount=D("600"), prefix=[transfer])
    assert r.leg_ids == ("xfer",) and r.amount_out == D("600")


def test_price_path_rejects_mismatched_chain():
    import pytest

    with pytest.raises(ValueError):
        price_path([swap("x", "USDT", "MXN")], D("1"), "USDC")
