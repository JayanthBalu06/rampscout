"""Payout math. The single source of truth for net MXN.

net_mxn = floor_to_centavos((input_usdc - usdc_fee - gas_cost_usdc) * rate - mxn_withdrawal_fee)

All arithmetic is Decimal under a fixed context; rounding happens exactly once, at the end,
toward zero (ROUND_DOWN) so we never promise a centavo the provider would not pay.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal, localcontext

CENTAVO = Decimal("0.01")
USDC_QUANTUM = Decimal("0.000001")  # USDC has 6 decimals
ZERO = Decimal("0")

_CTX = Context(prec=34)  # far beyond any (6dp x 6dp) product we can produce


@dataclass(frozen=True)
class PayoutBreakdown:
    input_usdc: Decimal
    usdc_fee: Decimal
    gas_cost_usdc: Decimal
    usdc_converted: Decimal
    rate_mxn_per_usdc: Decimal
    gross_mxn: Decimal  # exact, unrounded
    mxn_withdrawal_fee: Decimal
    net_mxn: Decimal  # rounded down to centavos, never negative
    viable: bool  # False when fees consume the whole input


def compute_payout(
    *,
    input_usdc: Decimal,
    rate_mxn_per_usdc: Decimal,
    usdc_fee: Decimal,
    mxn_withdrawal_fee: Decimal,
    gas_cost_usdc: Decimal = ZERO,
) -> PayoutBreakdown:
    """Compute the recipient's net MXN for a total USDC budget.

    gas_cost_usdc is 0 while gas is demo-sponsored; when users pay gas it is deducted
    here, so ranking automatically accounts for it.
    """
    for name, value in (
        ("input_usdc", input_usdc),
        ("rate_mxn_per_usdc", rate_mxn_per_usdc),
        ("usdc_fee", usdc_fee),
        ("mxn_withdrawal_fee", mxn_withdrawal_fee),
        ("gas_cost_usdc", gas_cost_usdc),
    ):
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
        if not value.is_finite() or value < 0:
            raise ValueError(f"{name} must be a finite, non-negative decimal")

    with localcontext(_CTX):
        usdc_converted = input_usdc - usdc_fee - gas_cost_usdc
        gross_mxn = usdc_converted * rate_mxn_per_usdc
        raw_net = gross_mxn - mxn_withdrawal_fee
        viable = usdc_converted > 0 and raw_net > 0
        net = raw_net.quantize(CENTAVO, rounding=ROUND_DOWN) if viable else ZERO.quantize(CENTAVO)

    return PayoutBreakdown(
        input_usdc=input_usdc,
        usdc_fee=usdc_fee,
        gas_cost_usdc=gas_cost_usdc,
        usdc_converted=usdc_converted,
        rate_mxn_per_usdc=rate_mxn_per_usdc,
        gross_mxn=gross_mxn,
        mxn_withdrawal_fee=mxn_withdrawal_fee,
        net_mxn=net,
        viable=viable,
    )
