"""S1-S7: one payment, persist-before-broadcast, crash recovery by original hash, payout
retry, receipt verification, simulated labeling, and no secrets in output."""

import threading
from dataclasses import replace
from decimal import Decimal

import pytest
import structlog
from sqlalchemy import select

from rampscout.agent import evaluate as evaluate_mod
from rampscout.agent.evaluate import run_due
from rampscout.config import get_settings
from rampscout.db.models import Authorization, Execution, SimChainTx
from rampscout.db.session import SessionLocal
from rampscout.logging import REDACTED, redact
from rampscout.settlement.reconcile import reconcile
from rampscout.settlement.sim_chain import SimulatedChain
from tests.helpers import (
    SpySettler,
    advance_without_eval,
    executions,
    onchain_txs,
    session_id_of,
)


def kinds(a):
    return [e["kind"] for e in a["events"]]


def best_quote(client, destination_id):
    return client.post(
        "/quotes", json={"amount_usdc": "600", "destination_id": destination_id}
    ).json()["quotes"][0]


def convert_now(client, make_watch, destination_id, key=None, expect=201):
    q = best_quote(client, destination_id)
    return make_watch(
        mode="immediate",
        min_payout=q["net_mxn"],
        selected_quote_id=q["quote_id"],
        deadline_local=None,
        key=key,
        expect=expect,
    )


def the_tx():
    with SessionLocal() as db:
        return db.scalars(select(SimChainTx)).one()


def the_execution():
    with SessionLocal() as db:
        return db.scalars(select(Execution)).one()


# ---------------------------------------------------------------- happy path


def test_convert_now_signs_once_and_posts_quoted_payout(client, make_watch, destination_id):
    a = convert_now(client, make_watch, destination_id)
    assert a["status"] == "completed"
    assert kinds(a)[-4:] == ["signed", "broadcast", "transfer_confirmed", "payout_posted"]
    ex = a["execution"]
    assert ex["chain_status"] == "confirmed" and ex["payout_status"] == "posted"
    assert ex["quoted_net_mxn"] == ex["payout_mxn"] == "9993.25"
    assert ex["onchain_amount_usdc"] == "6.000000"
    assert ex["broadcast_attempts"] == 1
    assert ex["explorer_url"] is None and ex["network"] == "local simulated ledger"
    assert onchain_txs() == 1
    tx = the_tx()
    assert tx.amount_units == 6_000_000 and tx.recipient.endswith("0b0b")  # Route B wallet


def test_duplicate_convert_requests_produce_one_payment(client, make_watch, destination_id):
    first = convert_now(client, make_watch, destination_id, key="pay-once")
    q = first["terms"]["selected_quote_id"]
    again = make_watch(
        mode="immediate",
        min_payout=first["terms"]["min_payout_mxn"],
        selected_quote_id=q,
        deadline_local=None,
        key="pay-once",
    )
    assert again["id"] == first["id"]
    assert executions() == 1 and onchain_txs() == 1


def test_signing_is_serialized_with_distinct_nonces(client, make_watch):
    from fastapi.testclient import TestClient

    from rampscout.api.app import create_app

    make_watch(mode="auto")
    sid1 = session_id_of(client)
    with TestClient(create_app()) as other:
        dest = other.get("/destinations").json()[0]["id"]
        r = other.post(
            "/authorizations",
            json={
                "mode": "auto",
                "amount_usdc": "600",
                "min_payout_mxn": "10000",
                "destination_id": dest,
                "deadline": "2026-11-27T23:00:00Z",
                "time_zone": "America/Mexico_City",
            },
            headers={"Idempotency-Key": "other"},
        )
        assert r.status_code == 201
        sid2 = session_id_of(other)
    advance_without_eval(sid1)
    advance_without_eval(sid2)
    barrier = threading.Barrier(2)

    def work(sid):
        barrier.wait()
        run_due(get_settings(), session_id=sid)

    ts = [threading.Thread(target=work, args=(s,)) for s in (sid1, sid2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    with SessionLocal() as db:
        nonces = sorted(e.nonce for e in db.scalars(select(Execution)))
    assert nonces == [0, 1]
    assert onchain_txs() == 2


# ---------------------------------------------------------------- crash recovery


def test_lost_broadcast_response_reconciles_by_original_hash(client, make_watch, destination_id):
    client.post("/demo/chaos", json={"flags": {"drop_broadcast_response": True}})
    a = convert_now(client, make_watch, destination_id)
    assert a["status"] == "executing"
    assert a["execution"]["chain_status"] == "unknown"
    assert a["execution"]["state_label"].startswith("broadcast outcome unknown")
    assert kinds(a)[-2:] == ["signed", "broadcast_unknown"]
    original_hash = a["execution"]["tx_hash"]
    assert the_tx().received  # it actually reached the node; only the response was lost

    # "Restart": a brand-new worker process runs startup reconciliation.
    reconcile(get_settings())
    a = client.get(f"/authorizations/{a['id']}").json()
    assert a["status"] == "completed"
    assert a["execution"]["tx_hash"] == original_hash
    assert "Reconciled by original hash" in a["events"][-2]["reason"]
    tx = the_tx()
    assert onchain_txs() == 1 and tx.send_count == 1  # never re-signed, never resent


def test_broadcast_lost_before_node_resends_identical_bytes(client, make_watch, monkeypatch):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)
    flaky = SpySettler(SimulatedChain(drop_requests=1))
    run_due(get_settings(), session_id=sid, settler=flaky)
    ex = the_execution()
    assert ex.chain_status == "unknown"
    signed_bytes, original_hash = ex.signed_tx, ex.tx_hash
    assert not the_tx().received

    reconcile(get_settings())  # fresh settler, as after a restart
    a = client.get(f"/authorizations/{w['id']}").json()
    assert a["status"] == "completed"
    assert "rebroadcast" in kinds(a)
    ex = the_execution()
    assert ex.tx_hash == original_hash and ex.signed_tx == signed_bytes
    tx = the_tx()
    assert tx.raw == signed_bytes and tx.send_count == 1
    assert onchain_txs() == 1


def test_unsigned_execution_with_stale_quote_is_voided_on_restart(client, make_watch):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)

    class CrashBeforeSigning(SpySettler):
        def settle(self, execution_id):
            raise SystemExit  # process dies right after the execution row commits

    with pytest.raises(SystemExit):
        run_due(get_settings(), session_id=sid, settler=CrashBeforeSigning())
    assert the_execution().chain_status == "not_started"
    advance_without_eval(sid)  # 15 minutes pass; the revalidated quote expired
    reconcile(get_settings())
    a = client.get(f"/authorizations/{w['id']}").json()
    assert a["status"] == "watching"
    assert a["events"][-1]["kind"] == "reconciled"
    assert executions() == 0 and onchain_txs() == 0


def test_claimed_without_execution_is_finished_on_restart(client, make_watch):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)
    with SessionLocal() as db:
        a = db.get(Authorization, w["id"])
        a.status, a.last_best_route = "claimed", "B"  # crashed between claim and execute
        db.commit()
    reconcile(get_settings())
    a = client.get(f"/authorizations/{w['id']}").json()
    assert a["status"] == "completed"
    assert onchain_txs() == 1


# ---------------------------------------------------------------- payout


def test_payout_failure_retries_payout_only(client, make_watch, destination_id):
    client.post("/demo/chaos", json={"flags": {"fail_next_payout": True}})
    a = convert_now(client, make_watch, destination_id)
    assert a["status"] == "payout_pending"
    assert a["execution"]["state_label"] == "transfer confirmed / payout pending"
    exec_id = a["execution"]["id"]
    client.post("/demo/reconcile")
    a = client.get(f"/authorizations/{a['id']}").json()
    assert a["status"] == "completed"
    assert a["execution"]["id"] == exec_id
    assert a["execution"]["payout_attempts"] == 2
    assert kinds(a).count("signed") == 1
    assert onchain_txs() == 1 and the_tx().send_count == 1


# ---------------------------------------------------------------- verification


class TamperedChain(SimulatedChain):
    def __init__(self, *, status=1, value_delta=0):
        super().__init__()
        self.status, self.value_delta = status, value_delta

    def get_receipt(self, tx_hash):
        r = super().get_receipt(tx_hash)
        if r is None:
            return None
        t = r.transfers[0]
        return replace(
            r, status=self.status, transfers=(replace(t, value=t.value + self.value_delta),)
        )


@pytest.mark.parametrize(
    ("chain", "chain_status", "event"),
    [
        (TamperedChain(value_delta=1), "mismatch", "verification_failed"),
        (TamperedChain(status=0), "reverted", "transfer_reverted"),
    ],
)
def test_bad_receipt_never_posts_payout(client, make_watch, chain, chain_status, event):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)
    run_due(get_settings(), session_id=sid, settler=SpySettler(chain))
    a = client.get(f"/authorizations/{w['id']}").json()
    assert a["status"] == "failed"
    assert a["execution"]["chain_status"] == chain_status
    assert a["execution"]["payout_status"] == "not_started"
    assert kinds(a)[-1] == event


def test_spending_limit_blocks_and_releases_claim(client, make_watch, settings):
    settings.max_onchain_transfer_usdc = Decimal("1")
    w = make_watch(mode="auto")
    client.post("/demo/advance")
    a = client.get(f"/authorizations/{w['id']}").json()
    assert a["status"] == "watching"
    assert "spending limit" in a["events"][-1]["reason"]
    assert executions() == 0 and onchain_txs() == 0


# ---------------------------------------------------------------- labeling & secrets


def test_missing_rpc_or_signer_means_clearly_labeled_simulation(client, settings):
    s = client.get("/health/settlement").json()
    assert s["mode"] == "simulated"
    assert "RPC_URL" in s["reason"] and "SIGNER_PRIVATE_KEY" in s["reason"]
    settings.rpc_url = "http://127.0.0.1:9"
    s = client.get("/health/settlement").json()
    assert s["mode"] == "simulated" and "SIGNER_PRIVATE_KEY" in s["reason"]


def test_signed_bytes_and_keys_never_leave_the_server(client, make_watch, destination_id):
    with structlog.testing.capture_logs() as logs:
        a = convert_now(client, make_watch, destination_id)
        client.post("/demo/reconcile")
    raw_hex = the_execution().signed_tx.hex()
    body = client.get(f"/authorizations/{a['id']}").text
    assert raw_hex not in body and "signed_tx" not in body
    assert all(raw_hex not in str(entry) for entry in logs)
    event = redact(None, "info", {"signed_tx": b"\x01", "private_key": "0xabc", "ok": 1})
    assert event == {"signed_tx": REDACTED, "private_key": REDACTED, "ok": 1}


def test_spy_hook_still_patchable():
    # Guard for the test helpers above: run_due resolves the settler at call time.
    assert hasattr(evaluate_mod, "get_settler")
