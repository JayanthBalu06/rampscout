"""Send to a contact: find the best route automatically, then execute it safely.

Route = [onchain USDC transfer] + [conversions on Bitso's live books] + [payout].
  * bank contacts: deposit to the venue wallet -> USDC→USD/USDT (assumed) -> ... -> payout
  * wallet contacts (USDC): a single onchain transfer to the contact's confirmed address
The onchain transfer is real on Base Sepolia when configured (scaled for faucet limits);
conversions use live (or recorded) Bitso order books; fiat payouts are simulated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rampscout.agent.clocks import clock_for_auth, clock_for_session
from rampscout.agent.events import record
from rampscout.agent.terms import terms_hash
from rampscout.config import Settings
from rampscout.db.models import Authorization, Contact, DemoSession, Execution, RouteQuote
from rampscout.db.session import SessionLocal
from rampscout.domain.currencies import FIAT, floor_to, fmt_amount
from rampscout.domain.money import fmt_usdc
from rampscout.domain.routing import Hop, Leg, RateLeg, Route, find_routes, price_path
from rampscout.providers.bitso import Market, get_market, legs_from_market, load_recorded
from rampscout.settlement.base import onchain_amount
from rampscout.settlement.chain_settler import ChainSettler

log = structlog.get_logger()

PAYOUT_ETA = {"MXN": timedelta(minutes=10)}
DEFAULT_PAYOUT_ETA = timedelta(minutes=30)


@dataclass(frozen=True)
class RouteSet:
    routes: list[Route]
    market: Market
    fell_back: bool
    rows: list[RouteQuote]


def load_market(settings: Settings, source: str | None = None) -> tuple[Market, bool]:
    """Live Bitso data, falling back to the recorded snapshot (flagged) if unreachable."""
    want = source or settings.market_source
    if want == "recorded":
        return load_recorded(), False
    try:
        market = get_market("live")
        if market.books:
            return market, False
    except Exception as exc:
        log.warning("bitso.unreachable", error=type(exc).__name__)
    return load_recorded(), True


def _transfer_leg(leg_id: str, venue: str, mode: str) -> RateLeg:
    return RateLeg(
        leg_id=leg_id,
        venue=venue,
        from_ccy="USDC",
        to_ccy="USDC",
        rate=Decimal(1),
        pct_fee=Decimal(0),
        fixed_fee=Decimal(0),
        source="real-onchain" if mode == "testnet" else "simulated",
        eta=timedelta(minutes=1),
        kind="transfer",
        note="gas demo-sponsored",
    )


def legs_for(
    contact: Contact, market: Market, settings: Settings, settlement_mode: str
) -> tuple[list[Leg], list[Leg], list[Leg]]:
    """(prefix, conversion legs, suffix) for this contact.

    USDC wallet: one direct onchain transfer. Everything else: onchain deposit to the venue,
    conversions on the exchange, then a payout (bank transfer or crypto withdrawal)."""
    if contact.kind == "wallet" and contact.currency == "USDC":
        leg = _transfer_leg("onchain:to_contact", f"Base Sepolia → {contact.name}", settlement_mode)
        return [leg], [], []
    prefix: list[Leg] = [
        _transfer_leg(
            "onchain:to_venue", "Base Sepolia → Bitso deposit (demo wallet)", settlement_mode
        )
    ]
    conversions = legs_from_market(
        market, stable_swap_fee=Decimal(settings.stable_swap_fee_bps) / Decimal(10_000)
    )
    ccy = contact.currency
    if contact.kind == "wallet":
        venue, eta, note = (
            f"Bitso withdrawal → {contact.name} (simulated)",
            timedelta(minutes=5),
            "network withdrawal fee not modeled",
        )
    else:
        venue = "SPEI (simulated)" if ccy == "MXN" else "Local bank transfer (simulated)"
        eta = PAYOUT_ETA.get(ccy, DEFAULT_PAYOUT_ETA)
        note = "withdrawal fee not modeled"
    suffix: list[Leg] = [
        RateLeg(
            leg_id=f"payout:{ccy.lower()}",
            venue=venue,
            from_ccy=ccy,
            to_ccy=ccy,
            rate=Decimal(1),
            pct_fee=Decimal(0),
            fixed_fee=Decimal(0),
            source="simulated",
            eta=eta,
            kind="payout",
            note=note,
        )
    ]
    return prefix, conversions, suffix


def price_label(h: Hop) -> str | None:
    """Human price, quoted the way traders read it (e.g. "59,743.21 USDT per BTC")."""
    if h.avg_price is None or h.from_ccy == h.to_ccy or h.avg_price <= 0:
        return None
    if h.avg_price >= 1:
        return f"{h.avg_price:,.4f}".rstrip("0").rstrip(".") + f" {h.to_ccy} per {h.from_ccy}"
    inverse = 1 / h.avg_price
    return f"{inverse:,.2f} {h.from_ccy} per {h.to_ccy}"


def hop_json(h: Hop) -> dict[str, Any]:
    return {
        "leg_id": h.leg_id,
        "kind": h.kind,
        "venue": h.venue,
        "from_ccy": h.from_ccy,
        "to_ccy": h.to_ccy,
        "amount_in": format(h.amount_in, "f"),
        "amount_out": format(h.amount_out, "f"),
        "fee": format(floor_to(h.to_ccy, h.fee), "f"),
        "avg_price": format(h.avg_price.normalize(), "f") if h.avg_price is not None else None,
        "price_label": price_label(h),
        "eta_seconds": int(h.eta.total_seconds()),
        "source": h.source,
        "note": h.note,
    }


def find_send_routes(
    contact: Contact, amount: Decimal, market: Market, settings: Settings, settlement_mode: str
) -> list[Route]:
    prefix, conversions, suffix = legs_for(contact, market, settings, settlement_mode)
    return find_routes(
        conversions,
        from_ccy="USDC",
        to_ccy=contact.currency,
        amount=amount,
        max_hops=settings.max_route_hops,
        prefix=prefix,
        suffix=suffix,
    )


def quote_send(
    db: Session,
    *,
    session: DemoSession,
    contact: Contact,
    amount: Decimal,
    settings: Settings,
    settlement_mode: str,
    source: str | None = None,
    limit: int = 6,
) -> RouteSet:
    market, fell_back = load_market(settings, source)
    routes = find_send_routes(contact, amount, market, settings, settlement_mode)[:limit]
    now = clock_for_session(session, settings).now()
    rows = [
        _persist(db, session.id, contact.id, r, i + 1, market, now, settings)
        for i, r in enumerate(routes)
    ]
    db.flush()
    return RouteSet(routes=routes, market=market, fell_back=fell_back, rows=rows)


def _persist(
    db: Session,
    session_id: uuid.UUID,
    contact_id: uuid.UUID,
    r: Route,
    rank: int,
    market: Market,
    now: datetime,
    settings: Settings,
    authorization_id: uuid.UUID | None = None,
) -> RouteQuote:
    row = RouteQuote(
        id=f"r_{uuid.uuid4().hex[:20]}",
        session_id=session_id,
        contact_id=contact_id,
        authorization_id=authorization_id,
        amount_in=r.amount_in,
        from_ccy=r.from_ccy,
        amount_out=r.amount_out,
        to_ccy=r.to_ccy,
        path=r.path[:120],
        leg_ids=list(r.leg_ids),
        hops=[hop_json(h) for h in r.hops],
        rank=rank,
        eta_seconds=int(r.eta.total_seconds()),
        market_source=market.source,
        market_as_of=market.as_of,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.route_quote_ttl_seconds),
    )
    db.add(row)
    return row


def min_out_for(amount_out: Decimal, ccy: str, settings: Settings) -> Decimal:
    return floor_to(ccy, amount_out * (1 - Decimal(settings.slippage_bps) / Decimal(10_000)))


def send_terms(
    *, amount: Decimal, contact_id: uuid.UUID, route_quote_id: str, min_out: Decimal, ccy: str
) -> dict[str, str | None]:
    return {
        "mode": "send",
        "input_usdc": format(amount.normalize(), "f"),
        "contact_id": str(contact_id),
        "route_quote_id": route_quote_id,
        "min_out": format(min_out.normalize(), "f"),
        "out_currency": ccy,
    }


def send_hash_of(auth: Authorization) -> str:
    assert (
        auth.contact_id and auth.route_quote_id and auth.min_out is not None and auth.out_currency
    )
    return terms_hash(
        send_terms(
            amount=auth.input_usdc,
            contact_id=auth.contact_id,
            route_quote_id=auth.route_quote_id,
            min_out=auth.min_out,
            ccy=auth.out_currency,
        )
    )


# --------------------------------------------------------------------------- execution


@dataclass(frozen=True)
class SendOutcome:
    authorization_id: uuid.UUID
    status: str
    reason: str


def _recipient(contact: Contact, settler: ChainSettler, settings: Settings) -> tuple[str, str]:
    if contact.kind == "wallet" and contact.currency == "USDC":
        assert contact.wallet_address
        return contact.wallet_address, f"{contact.name}'s wallet {contact.account_masked}"
    venue = (
        settings.venue_deposit_address
        if settler.mode == "testnet" and settings.venue_deposit_address
        else settler.recipient_for("B")
    )
    assert venue
    return venue, "Bitso deposit (demo wallet)"


def execute_send(
    authorization_id: uuid.UUID, *, settings: Settings, settler: ChainSettler
) -> SendOutcome:
    """Re-price the confirmed path on fresh market data immediately before signing; every
    approved limit must still hold, or nothing is sent."""
    with SessionLocal() as db:
        auth = db.scalars(
            select(Authorization).where(Authorization.id == authorization_id).with_for_update()
        ).one()
        if auth.status != "claimed" or auth.mode != "send":
            return SendOutcome(auth.id, auth.status, "not a claimed send")
        now = clock_for_auth(db, auth, settings).now()
        contact = db.get(Contact, auth.contact_id)
        quoted = db.get(RouteQuote, auth.route_quote_id)
        assert contact is not None and quoted is not None
        assert auth.min_out is not None and auth.out_currency is not None

        source = "recorded" if quoted.market_source == "recorded" else None
        market, fell_back = load_market(settings, source)
        prefix, conversions, suffix = legs_for(contact, market, settings, settler.mode)
        by_id = {leg.leg_id: leg for leg in (*prefix, *conversions, *suffix)}
        failures: list[str] = []
        fresh: Route | None = None
        if quoted.market_source == "live" and fell_back:
            failures.append("live market data unavailable for re-pricing")
        elif missing := [lid for lid in quoted.leg_ids if lid not in by_id]:
            failures.append(f"market legs no longer available: {', '.join(missing)}")
        else:
            fresh = price_path([by_id[i] for i in quoted.leg_ids], auth.input_usdc, "USDC")
            if fresh is None:
                failures.append("route no longer executable at this size")
            elif fresh.amount_out < auth.min_out:
                failures.append(
                    f"fresh quote {fmt_amount(auth.out_currency, fresh.amount_out)} is below "
                    f"the minimum {fmt_amount(auth.out_currency, auth.min_out)}"
                )
        if contact.status != "confirmed":
            failures.append("contact is not confirmed")
        if send_hash_of(auth) != auth.terms_hash:
            failures.append("authorization terms changed since confirmation")
        if auth.input_usdc > settings.max_authorization_usdc:
            failures.append("amount exceeds the configured authorization limit")
        recipient, label = _recipient(contact, settler, settings)
        amount_onchain = onchain_amount(auth.input_usdc, settings)
        failures += settler.preflight("SEND", amount_onchain, recipient)

        if failures or fresh is None:
            reason = f"Not sent: {'; '.join(failures)}. Get a fresh route and confirm again."
            auth.status = "requote_required"
            auth.closed_at = now
            auth.claimed_at = None
            auth.version += 1
            auth.last_reason = reason
            record(db, auth, now, "claim_released", reason, payload={"failures": failures})
            db.commit()
            return SendOutcome(auth.id, auth.status, reason)

        row = _persist(db, auth.session_id, contact.id, fresh, 0, market, now, settings, auth.id)
        ex = Execution(
            authorization_id=auth.id,
            quote_id=row.id,
            route_id=fresh.path.replace(" → ", ">")[:64],
            input_usdc=auth.input_usdc,
            quoted_net_mxn=fresh.amount_out if auth.out_currency == "MXN" else None,
            out_currency=auth.out_currency,
            quoted_out=fresh.amount_out,
            onchain_amount_usdc=amount_onchain,
            settlement_mode=settler.mode,
            recipient_address=recipient,
            recipient_label=label[:120],
        )
        db.add(ex)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return SendOutcome(authorization_id, "executing", "execution already exists")
        auth.status = "executing"
        auth.version += 1
        auth.last_reason = (
            f"Re-priced {fresh.path} on {market.source} data: "
            f"{fmt_amount(auth.out_currency, fresh.amount_out)} "
            f"(minimum {fmt_amount(auth.out_currency, auth.min_out)}). "
            f"Sending {fmt_usdc(amount_onchain)} to {label} ({settler.mode})."
        )
        record(db, auth, now, "execution_started", auth.last_reason)
        db.commit()
        execution_id = ex.id

    settler.settle(execution_id)
    with SessionLocal() as db:
        final = db.get(Authorization, authorization_id)
        assert final is not None
        return SendOutcome(final.id, final.status, final.last_reason or "")


def outcome_currency_kind(ccy: str) -> Literal["fiat", "crypto"]:
    return "fiat" if ccy in FIAT else "crypto"
