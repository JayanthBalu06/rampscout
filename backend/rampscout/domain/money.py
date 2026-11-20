from __future__ import annotations

from decimal import Decimal


def fmt_mxn(d: Decimal) -> str:
    return f"MX${d:,.2f}"


def fmt_usdc(d: Decimal) -> str:
    return f"{format(d.normalize(), 'f')} USDC"
