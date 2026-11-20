"""The agent inside the wallet: drafting sends from plain English, and send-when watches on
live routes (notify / auto), with expiry, cancellation and re-pricing before signing."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from rampscout.agent import send_watch as sw
from rampscout.db.models import Execution, Notification, SimChainTx
from rampscout.services import send as send_mod
from tests.helpers import count


@pytest.fixture
def clock(monkeypatch):
    """Movable real clock for send watches."""
    state = {"now": datetime.now(UTC).replace(microsecond=0)}
    monkeypatch.setattr(sw, "now_utc", lambda: state["now"])
    return state


@pytest.fixture(autouse=True)
def recorded_for_watches(monkeypatch):
    """Watches insist on live data; in tests 'live' is the recorded snapshot."""
    from rampscout.providers import bitso

    # Patch where it's used (send.py imported the name), not just where it's defined.
    monkeypatch.setattr(send_mod, "get_market", lambda source, **kw: bitso.load_recorded())


def contacts(client):
    return {c["name"]: c for c in client.get("/contacts").json()}


def best_out(client, contact, amount="600"):
    r = client.post("/send/routes", json={"contact_id": contact["id"], "amount_usdc": amount})
    return D(r.json()["routes"][0]["amount_out"])


def watch(client, contact, min_out, mode="notify", deadline=None, clock=None, expect=201):
    deadline = deadline or (clock["now"] + timedelta(hours=2)).isoformat()
    r = client.post(
        "/send/watch",
        json={
            "contact_id": contact["id"],
            "amount_usdc": "600",
            "min_out": str(min_out),
            "deadline": deadline,
            "mode": mode,
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == expect, r.text
    return r.json()


def kinds(a):
    return [e["kind"] for e in a["events"]]


# ------------------------------------------------------------------ drafting


def draft(client, text):
    r = client.post("/agent/draft", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_draft_send_now_to_a_contact(client):
    d = draft(client, "Send 600 USDC to Mamá")
    assert (d["mode"], d["amount"], d["recipient_name"], d["receive_currency"]) == (
        "send_now",
        "600",
        "Mamá",
        "MXN",
    )
    assert d["contact_id"] and d["missing"] == [] and d["creates_authorization"] is False


def test_draft_conditional_send_defaults_to_notify(client):
    d = draft(client, "send 600 usdc to mama when she gets at least 11,400 pesos by 11pm")
    assert d["mode"] == "notify" and d["min_out"] == "11400" and d["receive_currency"] == "MXN"
    assert d["deadline_display"] and d["missing"] == []


def test_draft_pasted_address_as_token_and_auto(client):
    addr = "0x" + "12" * 20
    d = draft(
        client,
        f"automatically send 50 USDC to {addr} as BTC if they get at least 0.0001 BTC by 11pm",
    )
    assert d["mode"] == "auto" and d["recipient_address"] == addr and d["receive_currency"] == "BTC"
    assert d["contact_id"] is None


def test_draft_unknown_recipient_is_missing(client):
    d = draft(client, "pay Pedro 100 USDC")
    assert "recipient" in d["missing"]


# ------------------------------------------------------------------ watches


def test_below_target_waits_and_reports_the_gap(client, clock):
    mama = contacts(client)["Mamá"]
    target = best_out(client, mama) + D("50")
    a = watch(client, mama, target, clock=clock)
    assert a["status"] == "watching"
    assert kinds(a)[-1] == "waiting_below_target"
    assert "short of" in a["last_reason"]
    assert a["next_check_at"] is not None and a["route"] is None


def test_notify_when_met_never_sends(client, clock):
    mama = contacts(client)["Mamá"]
    a = watch(client, mama, best_out(client, mama) - D("1"), clock=clock)
    assert a["status"] == "notified"
    assert kinds(a)[-2:] == ["matched", "notified"]
    assert count(Notification) == 1 and count(Execution) == 0 and count(SimChainTx) == 0


def test_auto_send_when_met_executes_once(client, clock):
    mama = contacts(client)["Mamá"]
    a = watch(client, mama, best_out(client, mama) - D("1"), mode="auto", clock=clock)
    assert a["status"] == "completed"
    assert kinds(a)[-6:] == [
        "claimed",
        "execution_started",
        "signed",
        "broadcast",
        "transfer_confirmed",
        "payout_posted",
    ]
    assert a["route"]["path"].endswith("MXN")
    assert count(Execution) == 1 and count(SimChainTx) == 1


def test_waiting_watch_later_matches_through_the_worker_loop(client, clock, monkeypatch):
    from rampscout.agent.evaluate import run_due
    from rampscout.config import get_settings

    mama = contacts(client)["Mamá"]
    current = best_out(client, mama)
    a = watch(client, mama, current + D("10"), mode="auto", clock=clock)
    assert a["status"] == "watching"
    # Market improves by 0.2% on every Bitso book; 31 s later the worker re-checks.
    real = send_mod.legs_for

    def better(contact, market, settings, mode):
        from dataclasses import replace

        prefix, conv, suffix = real(contact, market, settings, mode)
        conv = [
            replace(leg, levels=tuple((p * D("1.002"), q) for p, q in leg.levels))
            if hasattr(leg, "levels") and leg.side == "sell_base"
            else leg
            for leg in conv
        ]
        return prefix, conv, suffix

    monkeypatch.setattr(send_mod, "legs_for", better)
    clock["now"] += timedelta(seconds=31)
    with pytest.MonkeyPatch.context() as m:
        from sqlalchemy import func

        m.setattr(func, "now", lambda: clock["now"])  # due-ness follows the moved clock
        run_due(get_settings())
    a = client.get(f"/authorizations/{a['id']}").json()
    assert a["status"] == "completed"


def test_price_drop_between_match_and_signing_releases_claim(client, clock, monkeypatch):
    mama = contacts(client)["Mamá"]
    target = best_out(client, mama) - D("1")
    calls = {"n": 0}
    real = send_mod.legs_for

    def worse_on_second_look(contact, market, settings, mode):
        from dataclasses import replace

        calls["n"] += 1
        prefix, conv, suffix = real(contact, market, settings, mode)
        if calls["n"] >= 2:  # the re-price right before signing
            conv = [
                replace(leg, levels=tuple((p * D("0.98"), q) for p, q in leg.levels))
                if hasattr(leg, "levels")
                else leg
                for leg in conv
            ]
        return prefix, conv, suffix

    monkeypatch.setattr(send_mod, "legs_for", worse_on_second_look)
    a = watch(client, mama, target, mode="auto", clock=clock)
    assert a["status"] == "watching"
    assert kinds(a)[-3:] == ["matched", "claimed", "claim_released"]
    assert "below the minimum" in a["events"][-1]["reason"]
    assert count(Execution) == 0 and count(SimChainTx) == 0


def test_deadline_expires_without_sending(client, clock):
    mama = contacts(client)["Mamá"]
    a = watch(
        client,
        mama,
        best_out(client, mama) + D("1000"),
        mode="auto",
        deadline=(clock["now"] + timedelta(minutes=30)).isoformat(),
        clock=clock,
    )
    assert a["status"] == "watching"
    clock["now"] += timedelta(minutes=31)
    a = client.post(f"/authorizations/{a['id']}/check").json()  # "Check now"
    assert a["status"] == "expired" and "Nothing was sent" in a["last_reason"]
    assert count(Execution) == 0


def test_cancel_send_watch(client, clock):
    mama = contacts(client)["Mamá"]
    a = watch(client, mama, best_out(client, mama) + D("100"), clock=clock)
    r = client.post(f"/authorizations/{a['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "canceled"


def test_watch_validation(client, clock):
    mama = contacts(client)["Mamá"]
    past = (clock["now"] - timedelta(minutes=1)).isoformat()
    assert (
        watch(client, mama, "11000", deadline=past, clock=clock, expect=422)["error"]["code"]
        == "deadline_in_past"
    )
    assert watch(client, mama, "11000.001", clock=clock, expect=422)["error"]["code"] in (
        "too_precise",
        "validation_error",
    )
