"""Two-minute demo, scripted against the running API.

    python -m scripts.demo                       # auto-detects http://localhost:8000[/api]
    python -m scripts.demo --base http://host/api
    python -m scripts.demo --pause               # wait for Enter between steps (live demo)

Walks the same journey as docs/DEMO_SCRIPT.md: compare -> draft the watch from a sentence
-> confirm -> first decision -> advance the fixture -> receipt (explorer link on testnet).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from decimal import Decimal

import httpx

SENTENCE = (
    "Convert 600 USDC if I can receive at least 10,000 pesos by Friday at 5 p.m. Mexico City time."
)


def mxn(v: str | None) -> str:
    return f"MX${Decimal(v):,.2f}" if v else "-"


class Demo:
    def __init__(self, base: str, pause: bool) -> None:
        self.c = httpx.Client(base_url=base, timeout=60)
        self.pause = pause

    def step(self, title: str) -> None:
        if self.pause:
            input(f"\n[enter] {title} ")
        print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))

    def run(self) -> None:
        self.step("Reset to a fresh demo session")
        state = self.c.post("/demo/reset").json()
        print(f"Demo clock: {state['clock']['now']} (tick {state['clock']['tick']})")
        print(f"Settlement: {state['settlement']['mode']} - {state['settlement']['reason']}")
        dest = self.c.get("/destinations").json()[0]

        self.step("Compare 600 USDC -> MXN")
        q = self.c.post("/quotes", json={"amount_usdc": "600", "destination_id": dest["id"]})
        body = q.json()
        for quote in body["quotes"]:
            b = quote["breakdown"]
            print(
                f"#{quote['rank']} Route {quote['route_id']}: {mxn(quote['net_mxn'])}  "
                f"= ({b['input_usdc']} - {b['usdc_fee']} USDC) x {b['rate_mxn_per_usdc']} "
                f"- {b['mxn_withdrawal_fee']} MXN   ETA {quote['eta_seconds'] // 60} min"
            )
        print(f"Why: {body['insight']}")

        self.step("Agent drafts the watch from plain English")
        print(f'"{SENTENCE}"')
        d = self.c.post("/intents/parse", json={"text": SENTENCE}).json()
        draft = d["draft"]
        print(f"Drafted by: {d['source']}  missing: {d['missing'] or 'nothing'}")
        print(f"Deadline:   {d['deadline_display']}")

        self.step("Confirm: auto-convert, minimum MX$10,000.00")
        terms = {
            "mode": "auto",
            "amount_usdc": draft["amount"],
            "min_payout_mxn": draft["min_payout_mxn"],
            "destination_id": draft["destination_id"],
            "deadline_local": draft["deadline_local"] + ":00",
            "time_zone": draft["time_zone"],
            "intent_text": SENTENCE,
        }
        a = self.c.post(
            "/authorizations", json=terms, headers={"Idempotency-Key": str(uuid.uuid4())}
        ).json()
        print(f"Status: {a['status']}")
        print(f"First decision: {a['last_reason']}")
        print(f"Next check: {a['next_check_at']}")

        self.step("Advance the fixture clock one tick")
        adv = self.c.post("/demo/advance").json()
        print(f"Demo clock: {adv['clock']['now']} (tick {adv['clock']['tick']})")
        a = self.c.get(f"/authorizations/{a['id']}").json()
        for e in a["events"]:
            print(f"  {e['seq']:>2}. {e['kind']:<22} {e['reason'][:88]}")

        self.step("Receipt")
        ex = a["execution"]
        if ex is None:
            print("No execution yet (status: " + a["status"] + ")")
            return
        print(
            f"Transfer: {ex['onchain_amount_usdc']} USDC on {ex['network']} ({ex['state_label']})"
        )
        print(f"Tx hash:  {ex['tx_hash']}")
        if ex["explorer_url"]:
            print(f"Explorer: {ex['explorer_url']}")
        else:
            print("Explorer: n/a (simulated ledger; configure a testnet signer for a real tx)")
        print(f"Quoted payout:    {mxn(ex['quoted_net_mxn'])}")
        print(f"Simulated payout: {mxn(ex['payout_mxn'])}  ref {ex['payout_reference']}")


def detect(base: str | None) -> str:
    candidates = [base] if base else ["http://localhost:8000/api", "http://localhost:8000"]
    for b in candidates:
        try:
            if httpx.get(f"{b}/health", timeout=3).status_code == 200:
                return b
        except httpx.HTTPError:
            continue
    sys.exit("API not reachable. Start it with `make api` or `make stack`.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base")
    p.add_argument("--pause", action="store_true")
    args = p.parse_args()
    Demo(detect(args.base), args.pause).run()


if __name__ == "__main__":
    main()
