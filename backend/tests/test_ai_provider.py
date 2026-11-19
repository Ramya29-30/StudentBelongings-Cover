"""AI provider integration tests against a MOCK provider (httpx.MockTransport). They verify request shape, schema validation, retries and
fallback behaviour. They do NOT prove that a real provider accepts the request - that needs real credentials (see README 'Test connection')."""
import io
import json

import httpx
import pytest
from sqlalchemy import select

from app.ai import service as ai
from app.config import settings
from app.database import SessionLocal
from app.models import AISuggestion, Claim

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KEY = "sk-test-SECRET-KEY-123"
GOOD_DESC = {"visible_description": "Crack across lower screen", "likely_components": ["Screen"], "suggested_damage_type": "Cracked screen",
             "suggested_severity": "Moderate", "suggested_repair_action": "Repair", "confidence": "Medium", "missing_information": [], "caveats": []}


class Provider:
    def __init__(self, responder):
        self.calls, self.sleeps, self.responder = [], [], responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.responder(len(self.calls), request)


def anthropic_ok(payload):
    return httpx.Response(200, headers={"request-id": "req_abc"}, json={"content": [{"type": "tool_use", "name": "submit_result", "input": payload}], "usage": {"input_tokens": 11, "output_tokens": 7}})


def openai_ok(payload):
    return httpx.Response(200, headers={"x-request-id": "oai_1"}, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})


@pytest.fixture()
def configure(monkeypatch):
    def _cfg(provider, responder, **extra):
        monkeypatch.setattr(settings, "AI_PROVIDER", provider)
        monkeypatch.setattr(settings, "AI_API_KEY", KEY)
        monkeypatch.setattr(settings, "AI_TEXT_MODEL", "text-model-x")
        monkeypatch.setattr(settings, "AI_VISION_MODEL", "vision-model-x")
        monkeypatch.setattr(settings, "AI_BASE_URL", extra.get("base", ""))
        monkeypatch.setattr(settings, "AI_MAX_RETRIES", 2)
        prov = Provider(responder)
        monkeypatch.setattr(ai, "_TRANSPORT", httpx.MockTransport(prov))
        monkeypatch.setattr(ai, "_sleep", lambda s: prov.sleeps.append(s))
        return prov
    return _cfg


def test_anthropic_structured_output_success_and_request_shape(configure):
    prov = configure("anthropic", lambda n, r: anthropic_ok(GOOD_DESC))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Accidental Damage", "screen cracked")
    assert out["is_ai"] is True and out["validation_status"] == "valid" and out["provider"] == "anthropic" and out["model"] == "vision-model-x"
    assert out["meta"]["attempts"] == 1 and out["meta"]["usage"] == {"input_tokens": 11, "output_tokens": 7} and out["meta"]["provider_request_id"] == "req_abc"
    assert out["meta"]["latency_ms"] >= 0 and out["meta"]["schema_valid"] is True
    req = prov.calls[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.anthropic.com/v1/messages" and req.headers["x-api-key"] == KEY and req.headers["anthropic-version"] == "2023-06-01"
    assert body["tool_choice"] == {"type": "tool", "name": "submit_result"} and body["tools"][0]["input_schema"]["properties"]["suggested_damage_type"]
    assert body["messages"][0]["content"][0]["type"] == "image" and body["messages"][0]["content"][0]["source"]["media_type"] == "image/png"
    assert "<untrusted_data>screen cracked</untrusted_data>" in body["messages"][0]["content"][1]["text"]  # claimant text is fenced as data
    assert out["content"]["caveats"][-1].startswith("A photograph cannot")


def test_openai_json_schema_and_compatible_json_object(configure):
    prov = configure("openai", lambda n, r: openai_ok(GOOD_DESC))
    assert ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")["is_ai"] is True
    req, body = prov.calls[0], json.loads(prov.calls[0].content)
    assert str(req.url) == "https://api.openai.com/v1/chat/completions" and req.headers["authorization"] == f"Bearer {KEY}"
    assert body["response_format"]["type"] == "json_schema" and "max_completion_tokens" in body
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    prov = configure("openai_compatible", lambda n, r: openai_ok(GOOD_DESC), base="http://localhost:11434/v1/")
    assert ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")["is_ai"] is True
    assert str(prov.calls[0].url) == "http://localhost:11434/v1/chat/completions" and json.loads(prov.calls[0].content)["response_format"] == {"type": "json_object"}


def test_invalid_schema_output_is_discarded_and_labelled(configure):
    bad = dict(GOOD_DESC, suggested_damage_type="Totally invented")
    configure("anthropic", lambda n, r: anthropic_ok(bad))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "water spill")
    assert out["is_ai"] is False and out["provider"] == "demo-fallback" and out["validation_status"] == "invalid" and "DEMO FALLBACK" in out["status_note"]
    assert out["meta"]["error"] == "schema validation failed" and out["meta"]["validation_errors"] and "Totally invented" in out["meta"]["raw_excerpt"]
    assert out["content"]["suggested_damage_type"] == "Liquid damage"  # came from the keyword fallback, not from the invalid AI output


def test_non_json_or_missing_tool_result_is_unusable(configure):
    configure("anthropic", lambda n, r: httpx.Response(200, json={"content": [{"type": "text", "text": "I think it is cracked"}]}))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is False and out["validation_status"] == "invalid"
    configure("openai", lambda n, r: httpx.Response(200, json={"choices": [{"message": {"content": "no json here"}}]}))
    assert ai.explain("claim", {"evaluation": {"rule_results": [], "estimated_payable": 0, "recommendation": "X"}})["is_ai"] is False


def test_ai_may_not_state_decisions_or_prices(configure):
    configure("openai", lambda n, r: openai_ok({"explanation": "Good news, your claim is approved and we will pay you 5000.", "key_points": []}))
    out = ai.explain("claim", {"evaluation": {"rule_results": [], "estimated_payable": 0, "recommendation": "RECOMMEND_REJECTION"}})
    assert out["is_ai"] is False and out["validation_status"] == "invalid"
    prov = configure("openai", lambda n, r: openai_ok(dict(GOOD_DESC, estimated_cost=4500, repair_price="Rs 4000")))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is True and "estimated_cost" not in out["content"] and "repair_price" not in out["content"]  # unknown fields (prices) are dropped


def test_catalogue_ids_outside_supplied_catalogue_are_discarded(configure):
    payload = {"suggested_items": [{"component": "Screen", "damage_type": "Cracked screen", "severity": "Moderate", "repair_action": "Repair", "catalogue_entry_id": 999, "confidence": "Low", "rationale": "x"},
                                   {"component": "Keyboard", "damage_type": "Broken component", "severity": "Minor", "repair_action": "Repair", "catalogue_entry_id": 2, "confidence": "High", "rationale": "y"}]}
    configure("anthropic", lambda n, r: anthropic_ok(payload))
    out = ai.suggest_assessment("Laptop", "Accidental Damage", "d", [{"id": 1, "component": "Screen", "damage_type": "", "action": "Repair"}, {"id": 2, "component": "Keyboard", "damage_type": "", "action": "Repair"}], [], [])
    assert [i["catalogue_entry_id"] for i in out["content"]["suggested_items"]] == [None, 2]


def test_rate_limit_retried_with_retry_after_then_succeeds(configure):
    prov = configure("anthropic", lambda n, r: httpx.Response(429, headers={"retry-after": "3"}) if n < 3 else anthropic_ok(GOOD_DESC))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is True and out["meta"]["attempts"] == 3
    assert prov.sleeps == [3.0, 3.0]  # Retry-After honoured


def test_provider_outage_falls_back_after_retries(configure):
    prov = configure("openai", lambda n, r: httpx.Response(503))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is False and "unavailable after 3 attempt" in out["status_note"] and out["meta"]["attempts"] == 3
    assert len(prov.calls) == 3 and prov.sleeps == [1, 2]  # exponential back-off


def test_timeout_retried_then_fallback(configure):
    def boom(n, r):
        raise httpx.ReadTimeout("slow")
    prov = configure("anthropic", boom)
    out = ai.explain("policy", {"terms": {"covered_perils": ["Theft"], "overall_limit": 1, "deductible_value": 0, "deductible_type": "fixed", "exclusions": [], "waiting_period_days": 0, "depreciation": {}}})
    assert out["is_ai"] is False and "network/timeout" in out["status_note"] and out["meta"]["attempts"] == 3


def test_bad_credentials_not_retried(configure):
    prov = configure("anthropic", lambda n, r: httpx.Response(401, json={"error": {"message": "invalid x-api-key"}}))
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is False and "rejected the credentials" in out["status_note"] and len(prov.calls) == 1
    assert KEY not in json.dumps(out)


def test_non_image_and_oversized_files_never_reach_the_provider(configure, monkeypatch):
    prov = configure("anthropic", lambda n, r: anthropic_ok(GOOD_DESC))
    assert ai.describe_damage(b"%PDF-1.4 not an image", "image/png", "Laptop", "Theft", "x")["is_ai"] is False  # content sniffing, not the claimed type
    assert ai.describe_damage(b"MZ\x90\x00 fake exe", "image/jpeg", "Laptop", "Theft", "x")["is_ai"] is False
    monkeypatch.setattr(settings, "AI_MAX_IMAGE_MB", 0.00001)
    assert "larger than" in ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")["status_note"]
    assert prov.calls == []


def test_no_provider_configured_uses_labelled_fallback(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "none")
    out = ai.describe_damage(PNG, "image/png", "Laptop", "Theft", "x")
    assert out["is_ai"] is False and "NOT an AI result" not in out["status_note"] and "DEMO FALLBACK" in out["status_note"] and out["validation_status"] == "n/a"
    assert ai.status()["configured"] is False


# ---------------------------------------------------------------- end to end through the API
def test_api_stores_ai_output_separately_with_metadata_and_never_changes_claim_status(client, student, assessor, admin, configure):
    configure("anthropic", lambda n, r: anthropic_ok(GOOD_DESC))
    ev = client.post("/api/claims/1/evidence", headers=assessor, data={"doc_type": "damage_photo"}, files={"file": ("p.png", io.BytesIO(PNG), "image/png")}).json()
    before = client.get("/api/claims/1", headers=assessor).json()
    r = client.post("/api/ai/claims/1/describe-image", headers=assessor, json={"evidence_id": ev["id"]}).json()
    assert r["is_ai"] is True and r["label"] == "AI suggestion (unverified)" and r["meta"]["usage"]["output_tokens"] == 7 and r["validation_status"] == "valid"
    assert KEY not in json.dumps(r)
    with SessionLocal() as db:
        row = db.scalars(select(AISuggestion)).all()[-1]
        assert row.provider == "anthropic" and row.model == "vision-model-x" and row.created_at and row.meta["attempts"] == 1
    item = client.post(f"/api/ai/suggestions/{r['id']}/accept-item", headers=assessor).json()
    assert item["verification_status"] == "AI Suggested" and item["price_source"] == "" and item["parts_cost"] is None  # no AI price
    after = client.get("/api/claims/1", headers=assessor).json()
    assert after["status"] == before["status"] and after["estimated_payable"] == before["estimated_payable"]  # AI cannot move a claim
    assert client.get("/api/claims/1/finance", headers=admin).json()["payments"] == []


def test_admin_test_connection_reports_real_outcome(client, admin, assessor, configure, monkeypatch):
    assert client.post("/api/ai/test-connection", headers=assessor).status_code == 403
    monkeypatch.setattr(settings, "AI_PROVIDER", "none")
    assert client.post("/api/ai/test-connection", headers=admin).json()["ok"] is False
    configure("openai", lambda n, r: openai_ok({"ok": True}))
    r = client.post("/api/ai/test-connection", headers=admin).json()
    assert r["ok"] is True and r["model"] == "text-model-x"
    configure("openai", lambda n, r: httpx.Response(401))
    assert client.post("/api/ai/test-connection", headers=admin).json()["ok"] is False
