"""Q2-Q4, Q6: ranking and exclusions."""

from datetime import timedelta
from decimal import Decimal as D

from rampscout.domain.eligibility import Constraints, ExclusionReason, partition, rank
from rampscout.providers.fixture import MX_SPEI
from tests.factories import NOW, make_quote

MARGIN = timedelta(minutes=2)


def constraints(deadline=None, budget="600", rail=MX_SPEI):
    return Constraints(
        budget_usdc=D(budget), destination_rail=rail, deadline=deadline, safety_margin=MARGIN
    )


def test_higher_rate_ranks_below_higher_payout():
    a = make_quote("A", rate="16.85", usdc_fee="2", mxn_fee="100", eta_min=20)
    b = make_quote("B", rate="16.75", usdc_fee="1", mxn_fee="40", eta_min=10)
    assert [q.route_id for q in rank([a, b])] == ["B", "A"]


def test_tie_breaks_by_earlier_arrival_then_route_id():
    slow = make_quote("A", eta_min=20)
    fast = make_quote("Z", eta_min=5)
    assert [q.route_id for q in rank([slow, fast])] == ["Z", "A"]
    c = make_quote("C", eta_min=10)
    b = make_quote("B", eta_min=10)
    assert [q.route_id for q in rank([c, b])] == ["B", "C"]


def test_high_paying_route_arriving_late_is_excluded():
    rich_but_slow = make_quote("A", rate="18.00", eta_min=60)
    modest_fast = make_quote("B", rate="16.75", eta_min=10)
    deadline = NOW + timedelta(minutes=30)
    eligible, excluded = partition([rich_but_slow, modest_fast], constraints(deadline), NOW)
    assert [q.route_id for q in eligible] == ["B"]
    assert excluded[0].quote.route_id == "A"
    assert excluded[0].reasons == (ExclusionReason.ARRIVES_AFTER_DEADLINE,)
    assert "safety margin" in excluded[0].detail


def test_safety_margin_boundary_is_inclusive():
    q = make_quote("B", eta_min=10)
    exactly = NOW + timedelta(minutes=12)
    assert partition([q], constraints(exactly), NOW)[0] == [q]
    one_second_short = exactly - timedelta(seconds=1)
    assert partition([q], constraints(one_second_short), NOW)[0] == []


def test_expired_over_budget_and_unsupported_are_excluded():
    expired = make_quote("A", ttl_s=60)
    over = make_quote("B", amount="601")
    card_only = make_quote("C", rails=frozenset({"mx_debit_card"}))
    ok = make_quote("D")
    later = NOW + timedelta(seconds=61)
    eligible, excluded = partition([expired, over, card_only, ok], constraints(), later)
    assert [q.route_id for q in eligible] == ["D"]
    reasons = {e.quote.route_id: e.reasons for e in excluded}
    assert reasons["A"] == (ExclusionReason.QUOTE_EXPIRED,)
    assert reasons["B"] == (ExclusionReason.OVER_BUDGET,)
    assert reasons["C"] == (ExclusionReason.UNSUPPORTED_DESTINATION,)


def test_quote_valid_until_exact_expiry_instant_is_expired():
    q = make_quote("A", ttl_s=120)
    assert partition([q], constraints(), NOW + timedelta(seconds=120))[0] == []
