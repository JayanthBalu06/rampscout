"""Canonical, hashable form of confirmed terms.

The hash binds an idempotency key to exact terms and lets the executor detect any
change to the authorization between confirmation and signing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal

from rampscout.domain.pricing import CENTAVO, USDC_QUANTUM


def canonical_terms(
    *,
    mode: str,
    input_usdc: Decimal,
    min_payout_mxn: Decimal,
    destination_id: uuid.UUID,
    deadline_utc: datetime | None,
    display_tz: str,
    selected_quote_id: str | None,
) -> dict[str, str | None]:
    return {
        "mode": mode,
        "input_usdc": format(input_usdc.quantize(USDC_QUANTUM), "f"),
        "min_payout_mxn": format(min_payout_mxn.quantize(CENTAVO), "f"),
        "destination_id": str(destination_id),
        "deadline_utc": deadline_utc.isoformat() if deadline_utc else None,
        "display_tz": display_tz,
        "selected_quote_id": selected_quote_id,
    }


def terms_hash(terms: dict[str, str | None]) -> str:
    blob = json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def hash_of_authorization(auth: object) -> str:
    a = auth  # Authorization ORM row; typed loosely to keep this module DB-agnostic
    return terms_hash(
        canonical_terms(
            mode=a.mode,  # type: ignore[attr-defined]
            input_usdc=a.input_usdc,  # type: ignore[attr-defined]
            min_payout_mxn=a.min_payout_mxn,  # type: ignore[attr-defined]
            destination_id=a.destination_id,  # type: ignore[attr-defined]
            deadline_utc=a.deadline_utc,  # type: ignore[attr-defined]
            display_tz=a.display_tz,  # type: ignore[attr-defined]
            selected_quote_id=a.selected_quote_id,  # type: ignore[attr-defined]
        )
    )
