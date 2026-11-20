"""Send flow: contacts, automatic best-route selection, safe execution."""

import uuid
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from rampscout.db.models import Execution, SimChainTx
from rampscout.db.session import SessionLocal
from rampscout.services import send as send_mod
from rampscout.services.contacts import clabe_is_valid, with_clabe_check
from tests.helpers import count


def contacts(client):
    return {c["name"]: c for c in client.get("/contacts").json()}


def routes(client, contact, amount="600"):
    r = client.post("/send/routes", json={"contact_id": contact["id"], "amount_usdc": amount})
    assert r.status_code == 200, r.text
    return r.json()


def send(client, contact, route_id, amount="600", key=None, expect=201):
    r = client.post(
        "/send",
        json={"contact_id": contact["id"], "amount_usdc": amount, "route_quote_id": route_id},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )
    assert r.status_code == expect, r.text
    return r.json()


def test_seeded_contacts_cover_bank_and_wallet(client):
    cs = contacts(client)
    assert {(c["kind"], c["currency"]) for c in cs.values()} == {
        ("bank", "MXN"),
        ("bank", "ARS"),
        ("wallet", "USDC"),
    }
    assert all(c["status"] == "confirmed" for c in cs.values())
    assert cs["Mamá"]["account_masked"].startswith("CLABE ••••")


def test_bank_contact_gets_ranked_multi_hop_routes(client):
    body = routes(client, contacts(client)["Mamá"])
    assert body["market"]["source"] == "recorded"
    rs = body["routes"]
    assert len(rs) >= 3 and rs[0]["route_quote_id"] == body["best_route_id"]
    assert [D(r["amount_out"]) for r in rs] == sorted(
        (D(r["amount_out"]) for r in rs), reverse=True
    )
    best = rs[0]
    assert best["path"].startswith("USDC → ") and best["path"].endswith("MXN")
    kinds = [h["kind"] for h in best["hops"]]
    assert kinds[0] == "transfer" and kinds[-1] == "payout"
    assert best["hops"][1]["source"] == "assumption"  # USDC enters via the labeled swap
    assert any(h["source"] == "recorded" for h in best["hops"])  # Bitso order book
    assert D(body["min_out"]) == (D(best["amount_out"]) * D("0.995")).quantize(
        D("0.01"), rounding="ROUND_DOWN"
    )
    assert D(rs[1]["behind_best"]) > 0


def test_wallet_contact_route_is_a_direct_transfer(client):
    body = routes(client, contacts(client)["Ana"])
    (only,) = body["routes"]
    assert only["path"] == "USDC" and [h["kind"] for h in only["hops"]] == ["transfer"]
    assert only["amount_out"] == "600"


def test_send_to_bank_executes_best_route_with_simulated_payout(client):
    mama = contacts(client)["Mamá"]
    body = routes(client, mama)
    a = send(client, mama, body["best_route_id"])
    assert a["status"] == "completed" and a["mode"] == "send"
    ex = a["execution"]
    assert ex["out_currency"] == "MXN" and ex["delivered_out"] == ex["quoted_out"]
    assert D(ex["quoted_out"]) >= D(a["min_out"])
    assert ex["recipient_label"] == "Bitso deposit (demo wallet)"
    assert a["route"]["path"] == body["routes"][0]["path"]
    assert "posted to Mamá" in a["events"][-1]["reason"]
    assert [e["kind"] for e in a["events"]][-4:] == [
        "signed",
        "broadcast",
        "transfer_confirmed",
        "payout_posted",
    ]


def test_send_to_wallet_delivers_onchain_to_the_contact_address(client):
    ana = contacts(client)["Ana"]
    a = send(client, ana, routes(client, ana)["best_route_id"])
    assert a["status"] == "completed"
    with SessionLocal() as db:
        tx = db.scalars(select(SimChainTx)).one()
    assert tx.recipient.lower() == ana["wallet_address"].lower()
    assert "Delivered onchain" in a["events"][-1]["reason"]


def test_send_is_idempotent_and_pays_once(client):
    mama = contacts(client)["Mamá"]
    rid = routes(client, mama)["best_route_id"]
    a1 = send(client, mama, rid, key="k1")
    a2 = send(client, mama, rid, key="k1")
    assert a1["id"] == a2["id"]
    assert count(Execution) == 1 and count(SimChainTx) == 1


def test_expired_route_requires_fresh_confirmation(client):
    mama = contacts(client)["Mamá"]
    rid = routes(client, mama)["best_route_id"]
    client.post("/demo/advance")  # 15 demo minutes: the 30 s route quote expired
    err = send(client, mama, rid, expect=409)["error"]
    assert err["code"] == "route_changed"
    assert err["details"]["routes"]["best_route_id"] != rid
    assert count(Execution) == 0


def test_price_drop_before_signing_sends_nothing(client, monkeypatch):
    mama = contacts(client)["Mamá"]
    rid = routes(client, mama)["best_route_id"]
    real = send_mod.legs_for

    def worse_market(contact, market, settings, mode):
        prefix, conv, suffix = real(contact, market, settings, mode)
        from dataclasses import replace

        conv = [
            replace(leg, levels=tuple((p * D("0.98"), a) for p, a in leg.levels))
            if hasattr(leg, "levels")
            else leg
            for leg in conv
        ]
        return prefix, conv, suffix

    monkeypatch.setattr(send_mod, "legs_for", worse_market)
    a = send(client, mama, rid)
    assert a["status"] == "requote_required"
    assert "below the minimum" in a["last_reason"]
    assert count(Execution) == 0 and count(SimChainTx) == 0


def test_contact_validation_and_confirmation(client):
    bad = client.post(
        "/contacts",
        json={
            "name": "X",
            "kind": "bank",
            "currency": "MXN",
            "bank_name": "B",
            "account": "1" * 18,
        },
    )
    assert bad.status_code == 422 and "CLABE" in bad.json()["error"]["message"]
    bad_addr = client.post(
        "/contacts",
        json={"name": "Y", "kind": "wallet", "currency": "USDC", "wallet_address": "0x123"},
    )
    assert bad_addr.status_code == 422
    good = client.post(
        "/contacts",
        json={
            "name": "Lucía",
            "kind": "wallet",
            "currency": "USDC",
            "wallet_address": "0x" + "ab" * 20,
        },
    ).json()
    assert good["status"] == "pending"
    from web3 import Web3

    assert good["wallet_address"] == Web3.to_checksum_address("0x" + "ab" * 20)
    assert good["wallet_address"] != "0x" + "ab" * 20  # stored checksummed
    r = client.post("/send/routes", json={"contact_id": good["id"], "amount_usdc": "10"})
    assert r.status_code == 422 and "Confirm" in r.json()["error"]["message"]
    assert client.post(f"/contacts/{good['id']}/confirm").json()["status"] == "confirmed"
    assert routes(client, good, "10")["routes"]


def test_contacts_are_private_to_their_session(client):
    from fastapi.testclient import TestClient

    from rampscout.api.app import create_app

    mama = contacts(client)["Mamá"]
    with TestClient(create_app()) as other:
        r = other.post("/send/routes", json={"contact_id": mama["id"], "amount_usdc": "1"})
        assert r.status_code == 422


@pytest.mark.parametrize(
    ("clabe", "ok"),
    [(with_clabe_check("01218000118359719"), True), ("012180001183597190", False), ("123", False)],
)
def test_clabe_check_digit(clabe, ok):
    assert clabe_is_valid(clabe) is ok
