"""Contacts and Send: the user picks who and how much; RampScout finds the best route."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Response
from sqlalchemy import select
from web3 import Web3

from rampscout.agent.clocks import clock_for_session
from rampscout.agent.events import record
from rampscout.agent.terms import terms_hash
from rampscout.api.deps import DbSession
from rampscout.api.errors import AppError
from rampscout.api.presenters import (
    authorization_out,
    contact_out,
    route_out,
    settlement_out,
)
from rampscout.api.schemas import (
    AuthorizationOut,
    ContactIn,
    ContactOut,
    MarketOut,
    SendIn,
    SendRoutesIn,
    SendRoutesOut,
    WalletOut,
)
from rampscout.api.session_dep import CurrentSession
from rampscout.config import get_settings
from rampscout.db.models import Authorization, Contact, RouteQuote
from rampscout.domain.currencies import fmt_amount
from rampscout.services.contacts import (
    ContactDraft,
    ContactError,
    create_contact,
    get_confirmed,
    get_contact,
    seed_contacts,
)
from rampscout.services.send import (
    execute_send,
    min_out_for,
    quote_send,
    send_terms,
)
from rampscout.settlement.base import onchain_amount
from rampscout.settlement.factory import get_settler

router = APIRouter(tags=["send"])


def _contact_error(exc: ContactError) -> AppError:
    return AppError(422, "invalid_contact", str(exc))


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(db: DbSession, session: CurrentSession) -> list[ContactOut]:
    seed_contacts(db, session, get_settings())
    db.commit()
    rows = db.scalars(
        select(Contact).where(Contact.session_id == session.id).order_by(Contact.created_at)
    ).all()
    return [contact_out(c) for c in rows]


@router.post("/contacts", response_model=ContactOut, status_code=201)
def add_contact(body: ContactIn, db: DbSession, session: CurrentSession) -> ContactOut:
    """Creates a *pending* contact; the user reviews the normalized details, then confirms."""
    settings = get_settings()
    signer = settings.signer_address or None
    try:
        c = create_contact(
            db,
            session,
            ContactDraft(
                body.name,
                body.kind,
                body.currency,
                body.bank_name,
                body.account,
                body.wallet_address,
            ),
            signer,
        )
    except ContactError as exc:
        raise _contact_error(exc) from exc
    db.commit()
    return contact_out(c)


@router.post("/contacts/{contact_id}/confirm", response_model=ContactOut)
def confirm_contact(contact_id: uuid.UUID, db: DbSession, session: CurrentSession) -> ContactOut:
    c = db.get(Contact, contact_id)
    if c is None or c.session_id != session.id:
        raise AppError(404, "not_found", "Contact not found")
    if c.status != "confirmed":
        c.status = "confirmed"
        c.confirmed_at = clock_for_session(session, get_settings()).now()
        db.commit()
    return contact_out(c)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: uuid.UUID, db: DbSession, session: CurrentSession) -> None:
    c = db.get(Contact, contact_id)
    if c is None or c.session_id != session.id:
        raise AppError(404, "not_found", "Contact not found")
    in_use = db.scalar(select(Authorization.id).where(Authorization.contact_id == c.id).limit(1))
    if in_use:
        raise AppError(409, "contact_in_use", "This contact has transfers; it can't be deleted")
    db.delete(c)
    db.commit()


def _routes_response(
    db: DbSession,
    session: CurrentSession,
    contact: Contact,
    amount: Decimal,
    source: str | None,
) -> SendRoutesOut:
    settings = get_settings()
    settler = get_settler(settings)
    rs = quote_send(
        db,
        session=session,
        contact=contact,
        amount=amount,
        settings=settings,
        settlement_mode=settler.mode,
        source=source,
    )
    db.commit()
    best = rs.routes[0] if rs.routes else None
    return SendRoutesOut(
        contact=contact_out(contact),
        amount_usdc=amount,
        routes=[
            r
            for r in (route_out(row, best.amount_out if best else None) for row in rs.rows)
            if r is not None
        ],
        best_route_id=rs.rows[0].id if rs.rows else None,
        min_out=min_out_for(best.amount_out, contact.currency, settings) if best else None,
        slippage_bps=settings.slippage_bps,
        market=MarketOut(
            source=rs.market.source,
            as_of=rs.market.as_of,
            venue="Bitso public order books",
            fell_back=rs.fell_back,
            errors=rs.market.errors,
        ),
        settlement=settlement_out(settings),
        onchain_amount_usdc=onchain_amount(amount, settings),
    )


@router.post("/send/routes", response_model=SendRoutesOut)
def send_routes(body: SendRoutesIn, db: DbSession, session: CurrentSession) -> SendRoutesOut:
    """Every viable route to this contact, best first. Creates no authorization."""
    try:
        contact = get_contact(db, session, body.contact_id, confirmed=False)
    except ContactError as exc:
        raise _contact_error(exc) from exc
    return _routes_response(db, session, contact, body.amount_usdc, body.source)


@router.post("/send", response_model=AuthorizationOut, status_code=201)
def send(
    body: SendIn,
    db: DbSession,
    session: CurrentSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthorizationOut:
    settings = get_settings()
    if not idempotency_key or len(idempotency_key) > 100:
        raise AppError(422, "idempotency_key_required", "Send an Idempotency-Key header")
    try:
        contact = get_confirmed(db, session, body.contact_id)
    except ContactError as exc:
        raise _contact_error(exc) from exc
    quote = db.get(RouteQuote, body.route_quote_id)
    if quote is None or quote.session_id != session.id or quote.contact_id != contact.id:
        raise AppError(404, "route_not_found", "Unknown route for this contact")
    min_out = min_out_for(quote.amount_out, contact.currency, settings)
    digest = terms_hash(
        send_terms(
            amount=body.amount_usdc,
            contact_id=contact.id,
            route_quote_id=quote.id,
            min_out=min_out,
            ccy=contact.currency,
        )
    )
    existing = db.scalars(
        select(Authorization).where(
            Authorization.owner_id == session.owner_id,
            Authorization.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if existing is not None:
        if existing.terms_hash != digest:
            raise AppError(422, "idempotency_key_reused", "Key already used with different terms")
        response.headers["Idempotent-Replay"] = "true"
        return authorization_out(db, existing, settings)

    now = clock_for_session(session, settings).now()
    if quote.amount_in != body.amount_usdc:
        raise AppError(422, "terms_mismatch", "The route was quoted for a different amount")
    if body.amount_usdc > settings.max_authorization_usdc:
        raise AppError(
            422, "over_limit", f"Sends are limited to {settings.max_authorization_usdc} USDC"
        )
    if now >= quote.expires_at:
        fresh = _routes_response(db, session, contact, body.amount_usdc, None)
        raise AppError(
            409,
            "route_changed",
            "That route quote expired. Review the fresh best route and confirm again.",
            {"routes": fresh.model_dump(mode="json")},
        )

    from sqlalchemy.dialects.postgresql import insert

    inserted = db.execute(
        insert(Authorization)
        .values(
            id=uuid.uuid4(),
            owner_id=session.owner_id,
            session_id=session.id,
            idempotency_key=idempotency_key,
            terms_hash=digest,
            mode="send",
            status="claimed",
            version=1,
            input_usdc=body.amount_usdc,
            display_tz="America/Mexico_City",
            contact_id=contact.id,
            out_currency=contact.currency,
            min_out=min_out,
            route_quote_id=quote.id,
            confirmed_at=now,
            claimed_at=now,
            event_count=0,
        )
        .on_conflict_do_nothing(index_elements=["owner_id", "idempotency_key"])
        .returning(Authorization.id)
    ).scalar_one_or_none()
    if inserted is None:
        db.rollback()
        winner = db.scalars(
            select(Authorization).where(
                Authorization.owner_id == session.owner_id,
                Authorization.idempotency_key == idempotency_key,
            )
        ).one()
        response.headers["Idempotent-Replay"] = "true"
        return authorization_out(db, winner, settings)
    auth = db.scalars(
        select(Authorization).where(Authorization.id == inserted).with_for_update()
    ).one()
    record(
        db,
        auth,
        now,
        "confirmed",
        f"You confirmed: send {body.amount_usdc} USDC to {contact.name} "
        f"({contact.account_masked}) via {quote.path}; they receive at least "
        f"{fmt_amount(contact.currency, min_out)} "
        f"(quoted {fmt_amount(contact.currency, quote.amount_out)}, "
        f"{settings.slippage_bps / 100:.2f}% tolerance).",
        payload={"route_quote_id": quote.id, "path": quote.path},
    )
    db.commit()
    execute_send(auth.id, settings=settings, settler=get_settler(settings))
    db.expire_all()
    final = db.get(Authorization, auth.id)
    assert final is not None
    return authorization_out(db, final, settings)


@router.get("/wallet", response_model=WalletOut)
def wallet(db: DbSession, session: CurrentSession) -> WalletOut:
    """The demo wallet that sends pay from. On testnet: real balances read from Base
    Sepolia. In simulated mode: a demo balance on the local ledger."""
    from sqlalchemy import func

    from rampscout.db.models import Execution
    from rampscout.settlement.sim_chain import SIM_SIGNER
    from rampscout.settlement.status import settlement_status

    settings = get_settings()
    st = settlement_status(settings)
    scale = format(settings.demo_transfer_scale, "f")
    if st.mode == "testnet" and st.signer_address:
        return WalletOut(
            address=st.signer_address,
            network="Base Sepolia",
            mode="testnet",
            usdc=Decimal(st.signer_usdc) if st.signer_usdc else None,
            eth=Decimal(st.signer_eth) if st.signer_eth else None,
            explorer_url=f"https://sepolia.basescan.org/address/{st.signer_address}",
            shared=True,
            note="Shared demo wallet holding Base Sepolia test funds",
            transfer_scale=scale,
        )
    spent = db.scalar(
        select(func.coalesce(func.sum(Execution.onchain_amount_usdc), 0))
        .join(Authorization, Authorization.id == Execution.authorization_id)
        .where(Authorization.session_id == session.id, Execution.chain_status == "confirmed")
    )
    return WalletOut(
        address=Web3.to_checksum_address(SIM_SIGNER),
        network="local simulated ledger",
        mode="simulated",
        usdc=Decimal("1000") - Decimal(spent or 0),
        eth=Decimal("1"),
        explorer_url=None,
        shared=False,
        note=st.reason,
        transfer_scale=scale,
    )
