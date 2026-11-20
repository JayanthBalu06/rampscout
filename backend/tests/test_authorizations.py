"""W6, W8, idempotency, limits."""

import threading

from sqlalchemy import func, select

from rampscout.api.schemas import AuthorizationIn
from rampscout.config import get_settings
from rampscout.db.models import Authorization, DemoSession
from rampscout.db.session import SessionLocal
from rampscout.services.authorizations import create_authorization
from tests.helpers import executions, session_id_of


def test_rejects_incomplete_and_nonpositive_terms(client, make_watch):
    for overrides, code in [
        ({"min_payout_mxn": None}, "validation_error"),
        ({"deadline_local": None, "time_zone": "America/Mexico_City"}, "validation_error"),
        ({"amount_usdc": "0"}, "validation_error"),
        ({"amount_usdc": "-1"}, "validation_error"),
        ({"min_payout_mxn": "0"}, "validation_error"),
        ({"min_payout_mxn": "10000.001"}, "validation_error"),
        ({"deadline_local": "2026-11-27T10:00:00"}, "deadline_in_past"),
        ({"deadline_local": "2026-12-25T10:00:00"}, "deadline_too_far"),
        ({"amount_usdc": "5000"}, "over_limit"),
        ({"time_zone": "Mars/Base"}, "invalid_time_zone"),
    ]:
        body = make_watch(expect=422, **overrides)
        assert body["error"]["code"] == code, (overrides, body)


def test_requires_idempotency_key(client, destination_id):
    r = client.post(
        "/authorizations",
        json={
            "mode": "notify",
            "amount_usdc": "600",
            "min_payout_mxn": "10000",
            "destination_id": destination_id,
            "deadline": "2026-11-27T23:00:00Z",
            "time_zone": "America/Mexico_City",
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "idempotency_key_required"


def test_client_cannot_supply_addresses_or_unknown_fields(client, make_watch):
    body = make_watch(expect=422, recipient_address="0x" + "1" * 40)
    assert body["error"]["code"] == "validation_error"


def test_same_key_same_terms_replays(client, make_watch):
    first = make_watch(key="dup")
    r = client.post(
        "/authorizations",
        json={
            "mode": "notify",
            "amount_usdc": "600.00",  # same value, different spelling
            "min_payout_mxn": "10000",
            "destination_id": first["terms"]["destination"]["id"],
            "deadline": "2026-11-27T23:00:00Z",  # same instant, other form
            "time_zone": "America/Mexico_City",
        },
        headers={"Idempotency-Key": "dup"},
    )
    assert r.status_code == 201
    assert r.headers["Idempotent-Replay"] == "true"
    assert r.json()["id"] == first["id"]


def test_same_key_different_terms_rejected(client, make_watch):
    make_watch(key="dup")
    body = make_watch(key="dup", min_payout="9000", expect=422)
    assert body["error"]["code"] == "idempotency_key_reused"


def test_concurrent_duplicate_confirmations_create_one_authorization(client, destination_id):
    sid = session_id_of(client)
    body = AuthorizationIn.model_validate(
        {
            "mode": "auto",
            "amount_usdc": "600",
            "min_payout_mxn": "10000",
            "destination_id": destination_id,
            "deadline": "2026-11-27T23:00:00Z",
            "time_zone": "America/Mexico_City",
        }
    )
    results = []
    barrier = threading.Barrier(5)

    def confirm():
        with SessionLocal() as db:
            session = db.get(DemoSession, sid)
            barrier.wait()
            results.append(
                create_authorization(
                    db, session=session, body=body, idempotency_key="race", settings=get_settings()
                )
            )

    threads = [threading.Thread(target=confirm) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({r.authorization_id for r in results}) == 1
    assert sum(r.created for r in results) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Authorization)) == 1


def _best_quote(client, destination_id):
    return client.post(
        "/quotes", json={"amount_usdc": "600", "destination_id": destination_id}
    ).json()["quotes"][0]


def test_immediate_convert_with_current_quote(client, make_watch, destination_id):
    q = _best_quote(client, destination_id)
    w = make_watch(
        mode="immediate",
        min_payout=q["net_mxn"],
        selected_quote_id=q["quote_id"],
        deadline_local=None,
    )
    assert w["status"] == "completed"
    assert w["execution"]["quote_id"] == q["quote_id"]
    assert w["execution"]["payout_mxn"] == "9993.25"
    assert executions() == 1


def test_immediate_with_changed_quote_requires_fresh_confirmation(
    client, make_watch, destination_id
):
    q = _best_quote(client, destination_id)
    client.post("/demo/advance")  # 15 demo minutes later the 2-minute quote has expired
    body = make_watch(
        mode="immediate",
        min_payout=q["net_mxn"],
        selected_quote_id=q["quote_id"],
        deadline_local=None,
        expect=409,
    )
    assert body["error"]["code"] == "quote_changed"
    fresh = body["error"]["details"]["fresh_quote"]
    assert fresh["net_mxn"] == "10023.20"
    assert fresh["quote_id"] != q["quote_id"]
    assert executions() == 0
    # Confirming the fresh quote (new key = fresh confirmation) succeeds.
    ok = make_watch(
        mode="immediate",
        min_payout=fresh["net_mxn"],
        selected_quote_id=fresh["quote_id"],
        deadline_local=None,
    )
    assert ok["status"] == "completed"
    assert ok["execution"]["payout_mxn"] == "10023.20"


def test_immediate_min_above_quote_rejected(client, make_watch, destination_id):
    q = _best_quote(client, destination_id)
    body = make_watch(
        mode="immediate",
        min_payout="10000",
        selected_quote_id=q["quote_id"],
        deadline_local=None,
        expect=422,
    )
    assert body["error"]["code"] == "min_above_quote"


def test_quote_from_another_session_is_rejected(client, make_watch, destination_id):
    from fastapi.testclient import TestClient

    from rampscout.api.app import create_app

    with TestClient(create_app()) as other:
        other_dest = other.get("/destinations").json()[0]["id"]
        q = other.post("/quotes", json={"amount_usdc": "600", "destination_id": other_dest}).json()
    body = make_watch(
        mode="immediate",
        min_payout="9993.25",
        selected_quote_id=q["quotes"][0]["quote_id"],
        deadline_local=None,
        expect=409,
    )
    assert body["error"]["code"] == "quote_changed"


def test_preview_resolves_terms_without_creating(client, destination_id):
    r = client.post(
        "/authorizations/preview",
        json={
            "mode": "notify",
            "amount_usdc": "600",
            "min_payout_mxn": "10000",
            "destination_id": destination_id,
            "deadline_local": "2026-11-27T17:00:00",
            "time_zone": "America/Mexico_City",
        },
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["deadline_utc"] == "2026-11-27T23:00:00Z"
    assert "5:00 PM CST" in p["deadline_display"]
    assert p["onchain_amount_usdc"] == "6.000000"
    assert (p["current_best_route"], p["current_best_net_mxn"]) == ("B", "9993.25")
    assert p["meets_target_now"] is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Authorization)) == 0
