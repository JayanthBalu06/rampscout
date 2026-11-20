"""W1-W5 + agent loop behaviour: waits, matches, never converts below target."""

import threading

import pytest

from rampscout.agent import evaluate as evaluate_mod
from rampscout.agent.evaluate import run_due
from rampscout.config import get_settings
from rampscout.db.models import DecisionEvent
from rampscout.db.session import SessionLocal
from tests.helpers import (
    SequenceProvider,
    SpySettler,
    advance_without_eval,
    executions,
    notifications,
    onchain_txs,
    session_id_of,
)


@pytest.fixture
def spy(monkeypatch):
    s = SpySettler()
    monkeypatch.setattr(evaluate_mod, "get_settler", lambda _settings: s)
    monkeypatch.setattr("rampscout.api.routes.authorizations.get_settler", lambda _s: s)
    return s


def kinds(auth):
    return [e["kind"] for e in auth["events"]]


def test_tick0_waits_and_tick1_notifies(client, make_watch, spy):
    w = make_watch()
    assert w["status"] == "watching"
    assert kinds(w) == ["confirmed", "waiting_below_target"]
    assert "MX$6.75 short" in w["last_reason"]
    assert w["last_check_at"] == "2026-11-27T17:00:00Z"
    assert w["next_check_at"] == "2026-11-27T17:15:00Z"
    assert w["terms"]["deadline_utc"] == "2026-11-27T23:00:00Z"
    assert "5:00 PM CST" in w["terms"]["deadline_display"]

    adv = client.post("/demo/advance").json()
    assert adv["evaluations"][0]["status"] == "notified"
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "notified"
    assert kinds(w)[-2:] == ["matched", "notified"]
    assert w["events"][-2]["best_net_mxn"] == "10023.20"
    assert w["can_cancel"] is False


def test_notify_never_signs_and_notifies_once(client, make_watch, spy):
    make_watch()
    client.post("/demo/advance")
    client.post("/demo/advance")
    client.post("/demo/advance")
    assert spy.settled == []
    assert executions() == 0
    assert notifications() == 1
    assert len(client.get("/notifications").json()) == 1


def test_auto_mode_executes_once_on_match(client, make_watch, spy):
    w = make_watch(mode="auto")
    assert w["status"] == "watching"
    client.post("/demo/advance")
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "completed"
    assert kinds(w)[-6:] == [
        "claimed",
        "execution_started",
        "signed",
        "broadcast",
        "transfer_confirmed",
        "payout_posted",
    ]
    ex = w["execution"]
    assert ex["settlement_mode"] == "simulated"
    assert ex["quoted_net_mxn"] == "10023.20"
    assert ex["payout_mxn"] == "10023.20"
    assert ex["onchain_amount_usdc"] == "6.000000"  # 1:100 demo scale
    assert ex["explorer_url"] is None  # simulated runs never link to an explorer
    assert ex["state_label"] == "completed"
    assert w["executed_quote"]["route_id"] == "B"
    assert ex["network"] == "local simulated ledger"
    assert ex["tx_hash"].startswith("0x") and len(ex["tx_hash"]) == 66
    assert len(spy.settled) == 1
    client.post("/demo/advance")
    assert executions() == 1
    assert onchain_txs() == 1


def test_canceled_watch_never_executes(client, make_watch, spy):
    w = make_watch(mode="auto")
    r = client.post(f"/authorizations/{w['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"
    client.post("/demo/advance")
    assert client.get(f"/authorizations/{w['id']}").json()["status"] == "canceled"
    assert executions() == 0 and spy.settled == []
    again = client.post(f"/authorizations/{w['id']}/cancel")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_terminal"


def test_cancel_after_claim_conflicts(client, make_watch):
    w = make_watch(mode="auto")
    from rampscout.db.models import Authorization

    with SessionLocal() as db:
        a = db.get(Authorization, w["id"])
        a.status = "claimed"
        db.commit()
    r = client.post(f"/authorizations/{w['id']}/cancel")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_claimed"


def test_deadline_closes_watch_even_if_later_quote_qualifies(client, make_watch, spy):
    # Deadline 11:10: at tick 1 (11:15) B would pay 10,023.20, but time is up.
    w = make_watch(mode="auto", deadline_local="2026-11-27T11:10:00")
    assert w["next_check_at"] == "2026-11-27T17:10:00Z"  # clamped to the deadline
    client.post("/demo/advance")
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "expired"
    assert "Nothing was converted" in w["last_reason"]
    assert executions() == 0 and spy.settled == []


def test_late_arrival_makes_route_ineligible_then_expires(client, make_watch, spy):
    # Deadline 11:20: tick 0 B fits (11:10 + 2 min), tick 1 (11:15) B would land 11:27.
    w = make_watch(mode="auto", deadline_local="2026-11-27T11:20:00")
    assert w["status"] == "watching"
    client.post("/demo/advance")
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "watching"
    assert w["events"][-1]["kind"] == "no_eligible_route"
    assert "safety margin" in w["events"][-1]["reason"]
    client.post("/demo/advance")
    assert client.get(f"/authorizations/{w['id']}").json()["status"] == "expired"
    assert executions() == 0


def test_stale_quote_triggers_revalidation_and_releases_claim(client, make_watch, spy):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)
    # Matching quote 10,023.20, then the refresh before signing drops to 9,973.30.
    b = SequenceProvider(["16.80", "16.70"])
    run_due(get_settings(), session_id=sid, providers_factory=lambda s, c: [b], settler=spy)
    w = client.get(f"/authorizations/{w['id']}").json()
    assert b.calls == 2  # evaluated, then refreshed
    assert w["status"] == "watching"
    assert kinds(w)[-3:] == ["matched", "claimed", "claim_released"]
    assert "below your MX$10,000.00 minimum" in w["events"][-1]["reason"]
    assert executions() == 0 and spy.settled == []

    # Next tick: matched and the refreshed quote still qualifies -> executes on the
    # *refreshed* quote id, not the one that matched.
    advance_without_eval(sid)
    good = SequenceProvider(["16.80"])
    run_due(get_settings(), session_id=sid, providers_factory=lambda s, c: [good], settler=spy)
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "completed"
    matched_qid = next(e for e in reversed(w["events"]) if e["kind"] == "matched")["best_quote_id"]
    assert w["execution"]["quote_id"] != matched_qid


def test_provider_errors_are_reported_separately_and_watch_continues(client, make_watch, spy):
    client.post("/demo/chaos", json={"flags": {"provider_b_down": True}})
    w = make_watch()
    assert w["status"] == "watching"
    assert kinds(w) == ["confirmed", "provider_error", "waiting_below_target"]
    assert "Route B" in w["events"][1]["reason"]
    assert "Route A at MX$9,976.30" in w["last_reason"]
    client.post("/demo/chaos", json={"flags": {"provider_a_down": True}})
    client.post("/demo/advance")
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "watching"
    assert w["events"][-1]["kind"] == "no_eligible_route"


def test_concurrent_workers_process_a_watch_once(client, make_watch, spy):
    w = make_watch(mode="auto")
    sid = session_id_of(client)
    advance_without_eval(sid)
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        run_due(get_settings(), session_id=sid, settler=spy)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    w = client.get(f"/authorizations/{w['id']}").json()
    assert w["status"] == "completed"
    assert kinds(w).count("matched") == 1
    assert executions() == 1 and len(spy.settled) == 1
    assert onchain_txs() == 1
    with SessionLocal() as db:
        seqs = [e.seq for e in db.query(DecisionEvent).order_by(DecisionEvent.seq)]
    assert seqs == list(range(1, len(seqs) + 1))


def test_watch_survives_a_new_client_with_same_cookie(client, make_watch):
    w = make_watch()
    cookie = client.cookies.get("rs_session")
    from fastapi.testclient import TestClient

    from rampscout.api.app import create_app

    with TestClient(create_app(), cookies={"rs_session": cookie}) as reopened:
        listed = reopened.get("/authorizations").json()
        assert [a["id"] for a in listed] == [w["id"]]
        assert reopened.get(f"/authorizations/{w['id']}").status_code == 200
    with TestClient(create_app()) as stranger:
        assert stranger.get(f"/authorizations/{w['id']}").status_code == 404


def test_worker_tick_picks_up_due_watches_without_the_browser(client, make_watch, spy):
    from rampscout.worker.main import tick_once

    w = make_watch()
    sid = session_id_of(client)
    assert tick_once() == 0  # nothing due until the clock moves
    advance_without_eval(sid)
    assert tick_once() == 1
    assert client.get(f"/authorizations/{w['id']}").json()["status"] == "notified"
