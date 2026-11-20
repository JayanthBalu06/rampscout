"""W7: natural language -> editable draft. Drafts never authorize anything."""

import json
from types import SimpleNamespace

from rampscout.agent import intent as intent_mod
from tests.helpers import count

BRIEF = (
    "Convert 600 USDC if I can receive at least 10,000 pesos by Friday at 5 p.m. Mexico City time."
)


def parse(client, text):
    r = client.post("/intents/parse", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_brief_sentence_parses_without_a_model(client, settings):
    settings.anthropic_api_key = type(settings.anthropic_api_key)("")
    d = parse(client, BRIEF)
    assert d["source"] == "rules"
    assert d["draft"] == {
        "amount": "600",
        "currency": "USDC",
        "min_payout_mxn": "10000",
        "destination_id": d["draft"]["destination_id"],
        "destination_alias": "My BBVA account",
        "deadline_local": "2026-11-27T17:00",
        "time_zone": "America/Mexico_City",
        "mode": "notify",
    }
    assert d["deadline_utc"] == "2026-11-27T23:00:00Z"
    assert d["missing"] == []
    assert d["creates_authorization"] is False


def test_parse_creates_no_authorization(client):
    from rampscout.db.models import Authorization

    parse(client, BRIEF)
    assert count(Authorization) == 0


def test_incomplete_request_lists_missing_fields(client):
    d = parse(client, "convert some USDC to pesos")
    assert set(d["missing"]) == {"amount", "min_payout_mxn", "deadline_local"}


def test_ambiguous_timezone_is_asked_not_guessed(client):
    d = parse(client, "auto-convert 600 usdc when I get 10k MXN by 4pm CST")
    assert d["draft"]["mode"] == "auto"
    assert d["draft"]["min_payout_mxn"] == "10000"
    assert "deadline_local" in d["missing"]
    assert any(a["field"] == "time_zone" for a in d["ambiguities"])


def test_past_time_today_is_ambiguous(client):
    d = parse(client, "convert 600 USDC for at least 10000 MXN by Friday 9am")
    assert "deadline_local" in d["missing"]
    assert any("next Friday" in a["question"] for a in d["ambiguities"])


def test_unsupported_currency_flagged(client):
    d = parse(client, "convert 600 USDT for at least 10000 pesos by 4pm Mexico City time")
    assert any(a["field"] == "currency" for a in d["ambiguities"])


def _fake_client(payload, stop_reason="end_turn"):
    response = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
    )
    messages = SimpleNamespace(create=lambda **kw: response)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))


def test_claude_draft_is_validated_server_side(client, settings, monkeypatch):
    import anthropic

    settings.anthropic_api_key = type(settings.anthropic_api_key)("sk-test")
    captured = {}

    def factory(**kw):
        payload = {
            "amount": "600",
            "currency": "USDC",
            "min_payout_mxn": "10000",
            "destination_alias": "BBVA",
            "deadline_local": "2026-11-27T17:00",
            "time_zone": "America/Mexico_City",
            "mode": None,
            "ambiguities": [],
        }
        c = _fake_client(payload)
        original = c.beta.messages.create

        def create(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        c.beta.messages.create = create
        c.messages.create = create
        return c

    monkeypatch.setattr(anthropic, "Anthropic", factory)
    d = parse(client, BRIEF)
    assert d["source"] == "claude"
    assert d["draft"]["destination_alias"] == "My BBVA account"
    assert d["draft"]["mode"] == "notify"
    assert d["missing"] == []
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "<request>" in captured["messages"][0]["content"]


def test_claude_hallucinated_values_are_rejected(client, settings, monkeypatch):
    import anthropic

    settings.anthropic_api_key = type(settings.anthropic_api_key)("sk-test")
    payload = {
        "amount": "-600",
        "currency": "USDC",
        "min_payout_mxn": "lots",
        "destination_alias": "Swiss bank",
        "deadline_local": "2026-11-20T09:00",  # in the past on the demo clock
        "time_zone": "America/Mexico_City",
        "mode": "auto",
        "ambiguities": [],
    }
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake_client(payload))
    d = parse(client, "whatever")
    assert set(d["missing"]) >= {"amount", "min_payout_mxn", "deadline_local", "destination"}


def test_model_refusal_falls_back_to_rules(client, settings, monkeypatch):
    import anthropic

    settings.anthropic_api_key = type(settings.anthropic_api_key)("sk-test")
    monkeypatch.setattr(
        anthropic, "Anthropic", lambda **kw: _fake_client({}, stop_reason="refusal")
    )
    d = parse(client, BRIEF)
    assert d["source"] == "rules"
    assert "declined" in d["model_note"]
    assert d["missing"] == []


def test_rules_parser_unit_cases():
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 27, 17, 0, tzinfo=UTC).astimezone(ZoneInfo("America/Mexico_City"))
    d = intent_mod.parse_with_rules(
        "Convert at least 600 USDC if MX$10,000.50 lands by tomorrow 9am", now, "x"
    )
    assert (d.amount, d.min_payout_mxn, d.deadline_local) == (
        "600",
        "10000.5",
        "2026-11-28T09:00",
    )
