def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


def test_server_mounts_api_under_prefix():
    from fastapi.testclient import TestClient

    from rampscout.api.server import create_server

    with TestClient(create_server()) as c:
        assert c.get("/api/health").json()["status"] == "ok"


def test_render_style_database_url_is_normalized():
    from rampscout.config import Settings

    s = Settings(database_url="postgres://u:p@h:5432/db")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"


def test_intent_parse_is_rate_limited(client, settings):
    settings.intent_parses_per_hour = 2
    for _ in range(2):
        assert client.post("/intents/parse", json={"text": "hi"}).status_code == 200
    r = client.post("/intents/parse", json={"text": "hi"})
    assert r.status_code == 429


def test_embedded_worker_processes_due_watches(make_watch, client, settings):
    import time

    from fastapi.testclient import TestClient

    from rampscout.api.server import create_server
    from tests.helpers import advance_without_eval, session_id_of

    settings.embedded_worker = True
    settings.worker_loop_seconds = 0.1
    w = make_watch()
    advance_without_eval(session_id_of(client))
    with TestClient(create_server()):
        for _ in range(50):
            if client.get(f"/authorizations/{w['id']}").json()["status"] == "notified":
                break
            time.sleep(0.1)
    assert client.get(f"/authorizations/{w['id']}").json()["status"] == "notified"


def test_pasted_values_are_trimmed():
    from rampscout.config import Settings

    s = Settings(
        route_a_settlement_address=" 0x4fF3CFC3e88a508Dd71A8D12d8a79ee43Ec5C23C\n",
        signer_private_key='"0xabc"\n',
    )
    assert s.route_a_settlement_address == "0x4fF3CFC3e88a508Dd71A8D12d8a79ee43Ec5C23C"
    assert s.signer_private_key.get_secret_value() == "0xabc"


def test_session_bootstrap_is_stable(client):
    first = client.post("/session").json()["session_id"]
    assert client.post("/session").json()["session_id"] == first
    assert client.get("/demo/state").json()["session_id"] == first
