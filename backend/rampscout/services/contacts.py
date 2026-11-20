"""Saved recipients. Sends can only target confirmed contacts, by id."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from web3 import Web3

from rampscout.config import Settings
from rampscout.db.models import Contact, DemoSession
from rampscout.settlement.sim_chain import SIM_ROUTE_RECIPIENTS

BANK_CURRENCIES = {"MXN": "MX", "ARS": "AR", "COP": "CO", "BRL": "BR"}
WALLET_CURRENCIES = {"USDC"}
MAX_CONTACTS = 20


class ContactError(ValueError):
    pass


def clabe_is_valid(clabe: str) -> bool:
    """Mexican CLABE: 18 digits, last is a weighted (3,7,1) mod-10 check digit."""
    if not re.fullmatch(r"\d{18}", clabe):
        return False
    weights = (3, 7, 1)
    total = sum((int(d) * weights[i % 3]) % 10 for i, d in enumerate(clabe[:17]))
    return (10 - total % 10) % 10 == int(clabe[17])


def with_clabe_check(first17: str) -> str:
    weights = (3, 7, 1)
    total = sum((int(d) * weights[i % 3]) % 10 for i, d in enumerate(first17))
    return first17 + str((10 - total % 10) % 10)


@dataclass(frozen=True)
class ContactDraft:
    name: str
    kind: str
    currency: str
    bank_name: str | None
    account: str | None
    wallet_address: str | None


def normalize(draft: ContactDraft, signer_address: str | None) -> dict[str, str | None]:
    name = draft.name.strip()
    if not 1 <= len(name) <= 80:
        raise ContactError("Name must be 1-80 characters")
    if draft.kind == "bank":
        if draft.currency not in BANK_CURRENCIES:
            raise ContactError(f"Bank payouts support {', '.join(BANK_CURRENCIES)}")
        account = re.sub(r"[\s-]", "", draft.account or "")
        if draft.currency == "MXN":
            if not clabe_is_valid(account):
                raise ContactError("Enter a valid 18-digit CLABE (check digit failed)")
            masked = f"CLABE •••• {account[-4:]}"
        else:
            if not re.fullmatch(r"\d{8,30}", account):
                raise ContactError("Enter the account number (8-30 digits)")
            masked = f"•••• {account[-4:]}"
        bank = (draft.bank_name or "").strip()
        if not bank:
            raise ContactError("Bank name is required")
        return {
            "name": name,
            "kind": "bank",
            "currency": draft.currency,
            "country": BANK_CURRENCIES[draft.currency],
            "bank_name": bank[:80],
            "account_masked": masked,
            "wallet_address": None,
        }
    if draft.kind == "wallet":
        if draft.currency not in WALLET_CURRENCIES:
            raise ContactError("Wallet contacts receive USDC on Base Sepolia")
        addr = (draft.wallet_address or "").strip()
        if not Web3.is_address(addr):
            raise ContactError("Not a valid EVM address")
        checksummed = Web3.to_checksum_address(addr)
        if int(checksummed, 16) == 0:
            raise ContactError("The zero address can't receive funds")
        if signer_address and checksummed.lower() == signer_address.lower():
            raise ContactError("That is RampScout's own signer wallet")
        return {
            "name": name,
            "kind": "wallet",
            "currency": "USDC",
            "country": None,
            "bank_name": None,
            "account_masked": f"{checksummed[:6]}…{checksummed[-4:]}",
            "wallet_address": checksummed,
        }
    raise ContactError("kind must be bank or wallet")


def create_contact(
    db: Session, session: DemoSession, draft: ContactDraft, signer_address: str | None
) -> Contact:
    n = db.scalar(select(func.count()).select_from(Contact).where(Contact.session_id == session.id))
    if (n or 0) >= MAX_CONTACTS:
        raise ContactError("Contact limit reached for this demo session")
    c = Contact(
        owner_id=session.owner_id,
        session_id=session.id,
        status="pending",
        **normalize(draft, signer_address),
    )
    db.add(c)
    db.flush()
    return c


def demo_wallet(settings: Settings) -> str:
    """The seeded wallet contact receives at Route A's wallet, whose key the operator keeps
    (secrets/route_wallets.json) so demo funds can be swept back."""
    return settings.route_a_settlement_address or Web3.to_checksum_address(
        SIM_ROUTE_RECIPIENTS["A"]
    )


def seed_contacts(db: Session, session: DemoSession, settings: Settings) -> None:
    existing = db.scalar(
        select(func.count()).select_from(Contact).where(Contact.session_id == session.id)
    )
    if existing:
        return
    seeds = [
        ContactDraft(
            "Mamá", "bank", "MXN", "BBVA México", with_clabe_check("01218000118359719"), None
        ),
        ContactDraft("Mateo", "bank", "ARS", "Banco Galicia", "0070999030004123456789", None),
        ContactDraft("Ana", "wallet", "USDC", None, None, demo_wallet(settings)),
    ]
    for d in seeds:
        c = Contact(
            owner_id=session.owner_id,
            session_id=session.id,
            status="confirmed",
            **normalize(d, None),
        )
        c.confirmed_at = session.clock_now
        db.add(c)
    db.flush()


def get_confirmed(db: Session, session: DemoSession, contact_id: uuid.UUID) -> Contact:
    c = db.get(Contact, contact_id)
    if c is None or c.session_id != session.id:
        raise ContactError("Unknown contact")
    if c.status != "confirmed":
        raise ContactError("Confirm this contact before sending to it")
    return c
