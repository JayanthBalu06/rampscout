"""Record a snapshot of Bitso's public order books and fees.

    python -m scripts.record_bitso

The snapshot is used (clearly labeled "recorded") when the live API is unreachable during a
demo, and as reproducible data for the routing tests. No API key is needed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from rampscout.providers.bitso import BOOKS, fetch_market

OUT = (
    Path(__file__).resolve().parents[1] / "rampscout" / "providers" / "data" / "bitso_snapshot.json"
)


def main() -> None:
    market = asyncio.run(fetch_market(timeout_s=15))
    payload = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "https://api.bitso.com/v3 (public order_book + available_books)",
        "books": {
            name: {
                "taker_fee": format(b.taker_fee, "f"),
                "minimum_amount": format(b.minimum_amount, "f"),
                "bids": [[format(p, "f"), format(a, "f")] for p, a in b.bids],
                "asks": [[format(p, "f"), format(a, "f")] for p, a in b.asks],
            }
            for name, b in market.books.items()
        },
        "missing": sorted(set(BOOKS) - set(market.books)),
    }
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"wrote {OUT.name}: {len(payload['books'])} books, missing {payload['missing']}")


if __name__ == "__main__":
    main()
