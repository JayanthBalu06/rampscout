"""Currency precision. Each hop of a route is a separate trade that settles in whole minor
units, so multi-hop routes round down at every hop (single quotes round once at the end)."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

DECIMALS: dict[str, int] = {
    "USDC": 6,
    "USDT": 6,
    "USD": 2,
    "MXN": 2,
    "ARS": 2,
    "COP": 2,
    "BRL": 2,
    "BTC": 8,
    "ETH": 8,
}
FIAT = frozenset({"MXN", "ARS", "COP", "BRL"})
SYMBOL = {"MXN": "MX$", "ARS": "AR$", "COP": "COL$", "BRL": "R$"}


def quantum(ccy: str) -> Decimal:
    return Decimal(1).scaleb(-DECIMALS[ccy])


def floor_to(ccy: str, amount: Decimal) -> Decimal:
    return amount.quantize(quantum(ccy), rounding=ROUND_DOWN)


def fmt_amount(ccy: str, amount: Decimal) -> str:
    if ccy in SYMBOL:
        return f"{SYMBOL[ccy]}{amount:,.2f}"
    return f"{format(amount.normalize(), 'f')} {ccy}"
