"""Q1 / Q7: exact fixture payouts and end-only ROUND_DOWN."""

from decimal import Decimal as D

import pytest

from rampscout.domain.pricing import compute_payout


@pytest.mark.parametrize(
    ("rate", "usdc_fee", "mxn_fee", "expected"),
    [
        ("16.85", "2", "100", "9976.30"),  # tick 0, route A
        ("16.75", "1", "40", "9993.25"),  # tick 0, route B
        ("16.80", "1", "40", "10023.20"),  # tick 1, route B
    ],
)
def test_brief_fixture_payouts_exact(rate, usdc_fee, mxn_fee, expected):
    b = compute_payout(
        input_usdc=D("600"),
        rate_mxn_per_usdc=D(rate),
        usdc_fee=D(usdc_fee),
        mxn_withdrawal_fee=D(mxn_fee),
    )
    assert str(b.net_mxn) == expected
    assert b.viable


def test_rounds_down_not_half_up():
    b = compute_payout(
        input_usdc=D("1"), rate_mxn_per_usdc=D("16.855"), usdc_fee=D("0"), mxn_withdrawal_fee=D("0")
    )
    assert str(b.net_mxn) == "16.85"


def test_rounds_only_at_the_end():
    # 10.005 * 16.85 = 168.58425 -> 168.58. Rounding USDC to cents first would give
    # 168.50 (10.00) or 168.66 (10.01).
    b = compute_payout(
        input_usdc=D("10.005"),
        rate_mxn_per_usdc=D("16.85"),
        usdc_fee=D("0"),
        mxn_withdrawal_fee=D("0"),
    )
    assert b.gross_mxn == D("168.58425")
    assert str(b.net_mxn) == "168.58"


def test_user_paid_gas_reduces_payout():
    base = dict(input_usdc=D("600"), rate_mxn_per_usdc=D("16.75"), usdc_fee=D("1"))
    sponsored = compute_payout(**base, mxn_withdrawal_fee=D("40"))
    paid = compute_payout(**base, mxn_withdrawal_fee=D("40"), gas_cost_usdc=D("0.5"))
    assert str(sponsored.net_mxn) == "9993.25"
    assert str(paid.net_mxn) == "9984.87"  # 598.5 * 16.75 - 40 = 9984.875 -> floors


def test_fees_exceeding_input_are_not_viable():
    b = compute_payout(
        input_usdc=D("2"),
        rate_mxn_per_usdc=D("16.85"),
        usdc_fee=D("2"),
        mxn_withdrawal_fee=D("100"),
    )
    assert not b.viable
    assert str(b.net_mxn) == "0.00"


def test_rejects_floats_and_negatives():
    with pytest.raises(TypeError):
        compute_payout(
            input_usdc=600.0,  # type: ignore[arg-type]
            rate_mxn_per_usdc=D("16.85"),
            usdc_fee=D("2"),
            mxn_withdrawal_fee=D("100"),
        )
    with pytest.raises(ValueError):
        compute_payout(
            input_usdc=D("-1"),
            rate_mxn_per_usdc=D("16.85"),
            usdc_fee=D("2"),
            mxn_withdrawal_fee=D("100"),
        )
