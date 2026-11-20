"""API-level quote comparison: Q1-Q7 through HTTP, plus validation and demo clock."""

from sqlalchemy import func, select

from rampscout.db.models import QuoteSnapshot
from rampscout.db.session import SessionLocal


def quotes(client, destination_id, **extra):
    return client.post(
        "/quotes", json={"amount_usdc": "600", "destination_id": destination_id, **extra}
    )


def test_600_usdc_ranks_b_over_a_with_exact_strings(client, destination_id):
    r = quotes(client, destination_id)
    assert r.status_code == 200
    body = r.json()
    assert [(q["route_id"], q["net_mxn"], q["rank"]) for q in body["quotes"]] == [
        ("B", "9993.25", 1),
        ("A", "9976.30", 2),
    ]
    assert body["best_quote_id"] == body["quotes"][0]["quote_id"]
    assert "Route A has the higher rate" in body["insight"]
    assert "16.95 MXN less" in body["insight"]
    b = body["quotes"][0]
    assert b["breakdown"]["gas_sponsored"] is True
    assert b["source"] == "fixture"
    assert b["expires_at"] == "2026-11-27T17:02:00Z"
    assert b["estimated_arrival"] == "2026-11-27T17:10:00Z"
    assert body["settlement"]["mode"] == "simulated"


def test_money_fields_are_strings_never_numbers(client, destination_id):
    body = quotes(client, destination_id).json()
    for q in body["quotes"]:
        assert isinstance(q["net_mxn"], str)
        for k, v in q["breakdown"].items():
            if k != "gas_sponsored":
                assert isinstance(v, str), k


def test_json_number_amount_rejected(client, destination_id):
    r = client.post("/quotes", json={"amount_usdc": 600, "destination_id": destination_id})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_nonpositive_and_overprecise_amounts_rejected(client, destination_id):
    for bad in ["0", "-5", "1.0000001", "abc", "NaN"]:
        r = client.post("/quotes", json={"amount_usdc": bad, "destination_id": destination_id})
        assert r.status_code == 422, bad


def test_tick_1_after_advance_gives_10023_20(client, destination_id):
    assert client.post("/demo/advance").json()["clock"]["tick"] == 1
    body = quotes(client, destination_id).json()
    assert body["quotes"][0]["route_id"] == "B"
    assert body["quotes"][0]["net_mxn"] == "10023.20"
    assert body["clock"]["now"] == "2026-11-27T17:15:00Z"


def test_deadline_excludes_slow_route_with_reason(client, destination_id):
    # 15 min of headroom: B (10 + 2 margin) fits, A (20 + 2) does not.
    body = quotes(client, destination_id, deadline="2026-11-27T17:15:00Z").json()
    assert [q["route_id"] for q in body["quotes"]] == ["B"]
    assert body["excluded"][0]["quote"]["route_id"] == "A"
    assert body["excluded"][0]["reasons"] == ["arrives_after_deadline"]


def test_local_deadline_is_resolved_with_time_zone(client, destination_id):
    body = quotes(
        client,
        destination_id,
        deadline_local="2026-11-27T17:00:00",
        time_zone="America/Mexico_City",
    ).json()
    assert body["deadline"] == "2026-11-27T23:00:00Z"


def test_past_deadline_rejected(client, destination_id):
    r = quotes(client, destination_id, deadline="2026-11-27T16:00:00Z")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "deadline_in_past"


def test_provider_down_keeps_other_route_and_reports_separately(client, destination_id):
    client.post("/demo/chaos", json={"flags": {"provider_b_down": True}})
    body = quotes(client, destination_id).json()
    assert [q["route_id"] for q in body["quotes"]] == ["A"]
    assert body["excluded"] == []
    assert [(e["route_id"], e["kind"]) for e in body["provider_errors"]] == [("B", "unavailable")]


def test_unknown_destination_is_404(client):
    r = client.post(
        "/quotes",
        json={"amount_usdc": "600", "destination_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404


def test_every_fetched_quote_is_snapshotted(client, destination_id):
    quotes(client, destination_id)
    quotes(client, destination_id)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(QuoteSnapshot)) == 4


def test_sessions_are_isolated(client, destination_id):
    client.post("/demo/advance")
    from fastapi.testclient import TestClient

    from rampscout.api.app import create_app

    with TestClient(create_app()) as other:
        assert other.get("/demo/state").json()["clock"]["tick"] == 0
    assert client.get("/demo/state").json()["clock"]["tick"] == 1


def test_unknown_chaos_flag_rejected(client):
    r = client.post("/demo/chaos", json={"flags": {"drain_wallet": True}})
    assert r.status_code == 422
