"""Wire schemas. Money is always a decimal *string* in JSON, in and out."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    NaiveDatetime,
    PlainSerializer,
    model_validator,
)


def _decimal_string(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if not isinstance(v, str):
        raise ValueError('money must be a decimal string, e.g. "600"')
    try:
        d = Decimal(v.strip())
    except InvalidOperation as exc:
        raise ValueError("not a decimal number") from exc
    if not d.is_finite():
        raise ValueError("not a finite decimal number")
    return d


def _max_places(places: int) -> Any:
    def check(d: Decimal) -> Decimal:
        exp = d.as_tuple().exponent
        if isinstance(exp, int) and exp < -places:
            raise ValueError(f"at most {places} decimal places")
        return d

    return check


def _positive(d: Decimal) -> Decimal:
    if d <= 0:
        raise ValueError("must be greater than 0")
    return d


def _sane_size(d: Decimal) -> Decimal:
    if d > Decimal("1000000"):
        raise ValueError("must be at most 1,000,000")
    return d


Dec = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]
UsdcIn = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    AfterValidator(_max_places(6)),
    AfterValidator(_positive),
    AfterValidator(_sane_size),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
]
MxnIn = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    AfterValidator(_max_places(2)),
    AfterValidator(_positive),
    AfterValidator(_sane_size),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- requests ----------


class QuotesIn(Strict):
    amount_usdc: UsdcIn
    corridor: Literal["USDC-MXN"] = "USDC-MXN"
    destination_id: uuid.UUID
    deadline: AwareDatetime | None = None
    deadline_local: NaiveDatetime | None = None
    time_zone: str | None = None

    @model_validator(mode="after")
    def _one_deadline_form(self) -> QuotesIn:
        if self.deadline is not None and self.deadline_local is not None:
            raise ValueError("give either deadline or deadline_local + time_zone, not both")
        if self.deadline_local is not None and not self.time_zone:
            raise ValueError("deadline_local requires time_zone")
        return self


class ChaosIn(Strict):
    flags: dict[str, bool]


# ---------- responses ----------


class DestinationOut(BaseModel):
    id: uuid.UUID
    alias: str
    bank_name: str
    masked_account: str
    currency: str
    rail: str


class FeeBreakdownOut(BaseModel):
    input_usdc: Dec
    usdc_fee: Dec
    gas_cost_usdc: Dec
    gas_sponsored: bool
    usdc_converted: Dec
    rate_mxn_per_usdc: Dec
    gross_mxn: Dec
    mxn_withdrawal_fee: Dec
    net_mxn: Dec


class QuoteOut(BaseModel):
    quote_id: str
    provider_id: str
    route_id: str
    route_name: str
    rank: int | None
    net_mxn: Dec
    breakdown: FeeBreakdownOut
    eta_seconds: int
    estimated_arrival: datetime
    issued_at: datetime
    expires_at: datetime
    source: str


class ExcludedOut(BaseModel):
    quote: QuoteOut
    reasons: list[str]
    detail: str


class ProviderErrorOut(BaseModel):
    provider_id: str
    route_id: str
    kind: str
    message: str


class ClockOut(BaseModel):
    now: datetime
    tick: int
    display_tz: str
    mode: Literal["fixture", "system"]


class SettlementOut(BaseModel):
    mode: Literal["testnet", "simulated"]
    reason: str
    chain_id: int
    network: str
    token_contract: str
    transfer_scale: str


class QuotesOut(BaseModel):
    amount_usdc: Dec
    corridor: str
    destination: DestinationOut
    deadline: datetime | None
    clock: ClockOut
    quotes: list[QuoteOut]
    best_quote_id: str | None
    excluded: list[ExcludedOut]
    provider_errors: list[ProviderErrorOut]
    insight: str | None
    settlement: SettlementOut


class DemoStateOut(BaseModel):
    session_id: uuid.UUID
    clock: ClockOut
    chaos: dict[str, bool]
    settlement: SettlementOut
