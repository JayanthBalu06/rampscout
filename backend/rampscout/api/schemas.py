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
    signer_address: str | None = None
    signer_usdc: str | None = None
    signer_eth: str | None = None
    explorer_tx_url: str | None = None


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
    onchain_amount_usdc: Dec  # what a conversion would actually send onchain (demo scale)


class DemoStateOut(BaseModel):
    session_id: uuid.UUID
    clock: ClockOut
    chaos: dict[str, bool]
    settlement: SettlementOut


# ---------- intents ----------


class IntentParseIn(Strict):
    text: str

    @model_validator(mode="after")
    def _len(self) -> IntentParseIn:
        if not self.text.strip():
            raise ValueError("text must not be empty")
        if len(self.text) > 1000:
            raise ValueError("text must be at most 1000 characters")
        return self


class AmbiguityOut(BaseModel):
    field: str
    question: str


class IntentDraftOut(BaseModel):
    amount: str | None
    currency: str | None
    min_payout_mxn: str | None
    destination_id: str | None
    destination_alias: str | None
    deadline_local: str | None
    time_zone: str | None
    mode: Literal["notify", "auto"]


class IntentParseOut(BaseModel):
    draft: IntentDraftOut
    deadline_utc: datetime | None
    deadline_display: str | None
    missing: list[str]
    ambiguities: list[AmbiguityOut]
    assumptions: list[str]
    source: Literal["claude", "rules"]
    model: str | None
    model_note: str | None
    creates_authorization: Literal[False] = False


# ---------- authorizations ----------


class AuthorizationIn(Strict):
    mode: Literal["immediate", "notify", "auto"]
    amount_usdc: UsdcIn
    currency: Literal["USDC"] = "USDC"
    min_payout_mxn: MxnIn
    destination_id: uuid.UUID
    deadline: AwareDatetime | None = None
    deadline_local: NaiveDatetime | None = None
    time_zone: str
    selected_quote_id: str | None = None
    intent_text: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> AuthorizationIn:
        if self.deadline is not None and self.deadline_local is not None:
            raise ValueError("give either deadline or deadline_local, not both")
        if (
            self.mode in ("notify", "auto")
            and self.deadline is None
            and self.deadline_local is None
        ):
            raise ValueError("a watch needs a deadline")
        if self.mode == "immediate" and not self.selected_quote_id:
            raise ValueError("immediate mode requires selected_quote_id")
        if self.mode != "immediate" and self.selected_quote_id:
            raise ValueError("selected_quote_id is only valid for immediate mode")
        if self.intent_text is not None and len(self.intent_text) > 1000:
            raise ValueError("intent_text must be at most 1000 characters")
        return self


class TermsOut(BaseModel):
    amount_usdc: Dec
    currency: str
    min_payout_mxn: Dec
    destination: DestinationOut
    deadline_utc: datetime | None
    deadline_display: str | None
    time_zone: str
    selected_quote_id: str | None


class EventOut(BaseModel):
    seq: int
    at: datetime
    kind: str
    reason: str
    best_quote_id: str | None
    best_route: str | None
    best_net_mxn: Dec | None
    payload: dict[str, Any]


class ExecutionOut(BaseModel):
    id: uuid.UUID
    quote_id: str
    route_id: str
    input_usdc: Dec
    quoted_net_mxn: Dec
    onchain_amount_usdc: Dec
    transfer_scale: str
    settlement_mode: str
    chain_id: int | None
    token_contract: str | None
    recipient_address: str | None
    chain_status: str
    tx_hash: str | None
    explorer_url: str | None
    signer_address: str | None
    network: str
    broadcast_attempts: int
    payout_attempts: int
    block_number: int | None
    payout_status: str
    payout_mxn: Dec | None
    payout_reference: str | None
    state_label: str


class AuthorizationOut(BaseModel):
    id: uuid.UUID
    mode: str
    status: str
    version: int
    can_cancel: bool
    terms: TermsOut
    intent_text: str | None
    confirmed_at: datetime
    closed_at: datetime | None
    last_check_at: datetime | None
    next_check_at: datetime | None
    last_reason: str | None
    last_best_route: str | None
    last_best_net_mxn: Dec | None
    events: list[EventOut]
    execution: ExecutionOut | None
    executed_quote: QuoteOut | None
    clock: ClockOut


class NotificationOut(BaseModel):
    id: uuid.UUID
    authorization_id: uuid.UUID
    kind: str
    title: str
    body: str
    at: datetime
    read: bool


class EvaluationOut(BaseModel):
    authorization_id: uuid.UUID
    status: str
    reason: str


class AdvanceOut(DemoStateOut):
    evaluations: list[EvaluationOut]


class PreviewOut(BaseModel):
    mode: str
    amount_usdc: Dec
    min_payout_mxn: Dec
    destination: DestinationOut
    deadline_utc: datetime | None
    deadline_display: str | None
    time_zone: str
    onchain_amount_usdc: Dec
    transfer_scale: str
    settlement: SettlementOut
    current_best_route: str | None
    current_best_net_mxn: Dec | None
    meets_target_now: bool
