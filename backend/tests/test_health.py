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
