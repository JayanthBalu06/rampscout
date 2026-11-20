def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"
