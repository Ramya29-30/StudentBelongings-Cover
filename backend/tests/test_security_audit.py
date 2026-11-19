"""Security audit regression tests. Each test asserts the SECURE behaviour; written first and run against the unmodified code to prove the issue."""
import io
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tests.conftest import login

BACKEND = Path(__file__).resolve().parent.parent
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _run_config(env: dict) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("APP_ENV", "SECRET_KEY", "COOKIE_", "SEED_", "CORS_", "ALLOWED_"))}
    e.update(env)
    code = "from app.config import validate_production_settings as v; v(); print('CONFIG_OK')"
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=e, capture_output=True, text=True, timeout=60)


@pytest.fixture()
def assessor2(client, admin):
    r = client.post("/api/users", headers=admin, json={"username": "assessor2", "full_name": "Second Assessor", "role": "assessor", "password": "second-assessor-pass-123"})
    assert r.status_code == 201, r.text
    return login(client, "assessor2", "second-assessor-pass-123")


# ---------------------------------------------------------------- configuration
def test_unknown_app_env_fails_closed():
    r = _run_config({"APP_ENV": "prod", "SECRET_KEY": "x"})
    assert r.returncode != 0 and "CONFIG_OK" not in r.stdout


def test_wildcard_cors_origin_is_refused():
    r = _run_config({"APP_ENV": "development", "CORS_ALLOWED_ORIGINS": "*"})
    assert r.returncode != 0


def test_production_requires_https_cors_origins():
    base = {"APP_ENV": "production", "SECRET_KEY": "k" * 40, "COOKIE_SECURE": "true", "SEED_DEMO_DATA": "false"}
    assert _run_config({**base, "CORS_ALLOWED_ORIGINS": "http://app.example.org"}).returncode != 0
    assert _run_config(base).returncode == 0


# ---------------------------------------------------------------- BOLA / IDOR
def test_student_cannot_open_claim_on_another_students_asset(client, student):
    r = client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 6, "incident_date": "2026-01-02", "incident_type": "Theft"})
    assert r.status_code in (404, 422), r.text


def test_asset_not_on_policy_is_rejected(client, student):
    # asset 5 (tablet) belongs to aarav but is not insured under policy 1
    r = client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 5, "incident_date": "2026-01-02", "incident_type": "Theft"})
    assert r.status_code in (404, 422), r.text


def test_other_assessor_cannot_write_to_claim_assigned_elsewhere(client, assessor2):
    w = [client.post("/api/claims/1/assign", headers=assessor2, json={}),
         client.put("/api/claims/1/assessment", headers=assessor2, json={"assessor_notes": "x"}),
         client.post("/api/claims/1/evaluate", headers=assessor2),
         client.post("/api/claims/1/reserve/recommend", headers=assessor2, json={"amount": 1}),
         client.post("/api/claims/1/items", headers=assessor2, json={"component": "Screen", "damage_type": "Scratch"}),
         client.post("/api/claims/1/status", headers=assessor2, json={"to": "Pending Information", "reason": "x"})]
    assert all(x.status_code in (403, 404, 409) for x in w), [x.status_code for x in w]


def test_assessor_cannot_see_student_drafts(client, assessor):
    assert client.get("/api/claims/4", headers=assessor).status_code == 404
    assert all(c["status"] != "Draft" for c in client.get("/api/claims", headers=assessor).json())


def test_assessor_audit_is_scoped_and_hides_login_ips(client, assessor):
    rows = client.get("/api/audit?limit=500", headers=assessor).json()
    assert all(r["entity_type"] != "user" for r in rows)


def test_audit_limit_is_bounded(client, admin):
    assert client.get("/api/audit?limit=-1", headers=admin).status_code == 422
    assert client.get("/api/audit?limit=100000", headers=admin).status_code == 422


def test_student_cannot_rewrite_value_of_insured_asset(client, student):
    a = client.get("/api/assets", headers=student).json()[0]
    r = client.put(f"/api/assets/{a['id']}", headers=student, json={"category": a["category"], "name": a["name"], "purchase_date": a["purchase_date"], "declared_value": 9_999_999})
    assert r.status_code in (400, 403, 409), r.text


def test_students_do_not_see_internal_assessor_notes(client, student, assessor):
    client.put("/api/claims/1/assessment", headers=assessor, json={"assessor_notes": "INTERNAL-NOTE-XYZ"})
    assert "INTERNAL-NOTE-XYZ" not in client.get("/api/claims/1", headers=student).text
    assert "INTERNAL-NOTE-XYZ" not in client.get("/api/claims/1/report", headers=student).text


def test_ai_suggestion_must_belong_to_the_claim(client, assessor):
    r = client.post("/api/claims/1/items", headers=assessor, json={"component": "Screen", "damage_type": "Scratch", "ai_suggestion_id": 99999})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- input limits / abuse
def test_text_fields_are_length_limited(client, student, assessor):
    big = "x" * 20_000
    assert client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 1, "incident_date": "2026-01-02", "incident_type": "Theft", "incident_location": big}).status_code == 422
    assert client.put("/api/claims/4", headers=student, json={"description": big}).status_code == 422
    assert client.put("/api/claims/1/assessment", headers=assessor, json={"assessor_notes": "y" * 100_000}).status_code == 422


def test_oversized_request_bodies_are_rejected_before_auth(client):
    r = client.post("/api/auth/login", content=b"{" + b" " * 3_000_000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    r = client.post("/api/claims/4/evidence", data={"doc_type": "other"}, files={"file": ("a.txt", io.BytesIO(b"a" * (10 * 1024 * 1024)), "text/plain")})
    assert r.status_code == 413


def test_ai_endpoints_are_rate_limited(client, student):
    codes = [client.post("/api/ai/policies/1/explain", headers=student).status_code for _ in range(40)]
    assert 429 in codes


def test_claim_creation_is_capped(client, student):
    codes = [client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 1, "incident_date": "2026-01-02", "incident_type": "Theft"}).status_code for _ in range(40)]
    assert 429 in codes


# ---------------------------------------------------------------- money: atomicity
def _approved_claim(client, assessor, admin):
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Assessment Completed"}).status_code == 200
    assert client.post("/api/claims/1/reserve/recommend", headers=assessor, json={"amount": 1000, "reason": "t"}).status_code == 200
    assert client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 1000, "reason": "t"}).status_code == 200
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Approved for Review", "reason": "ok"}).status_code == 200


def test_concurrent_payment_requests_cannot_exceed_reserve(client, assessor, admin):
    _approved_claim(client, assessor, admin)
    results = []

    def go(i):
        r = client.post("/api/claims/1/payments", headers=assessor, json={"amount": f"{400 + i}.00", "idempotency_key": f"k{i}"})
        results.append(r.status_code)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(c in (201, 400, 409, 429) for c in results), results  # never a 500
    fin = client.get("/api/claims/1/finance", headers=assessor).json()
    assert fin["committed"] <= fin["approved_reserve"], (fin["committed"], results)


def test_idempotent_replay_with_different_amount_conflicts(client, assessor, admin):
    _approved_claim(client, assessor, admin)
    a = client.post("/api/claims/1/payments", headers=assessor, json={"amount": "100.00", "idempotency_key": "same"})
    assert a.status_code == 201
    assert client.post("/api/claims/1/payments", headers=assessor, json={"amount": "100.00", "idempotency_key": "same"}).json()["id"] == a.json()["id"]
    assert client.post("/api/claims/1/payments", headers=assessor, json={"amount": "200.00", "idempotency_key": "same"}).status_code == 409


# ---------------------------------------------------------------- headers, CORS, static
def test_no_cors_headers_for_untrusted_origin(client, student):
    h = {"Origin": "https://evil.example"}
    r = client.get("/api/health", headers=h)
    assert "access-control-allow-origin" not in r.headers
    r = client.options("/api/claims", headers={**h, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-csrf-token"})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/auth/me", headers={**student, **h})
    assert "access-control-allow-origin" not in r.headers


def test_security_headers_on_app_and_api(client):
    for path in ("/", "/api/health", "/login", "/privacy"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"], path
        assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers["content-security-policy"], path
        assert r.headers["referrer-policy"] and r.headers["permissions-policy"], path


def test_environment_is_not_disclosed_to_anonymous_callers(client):
    assert "env" not in client.get("/api/health").json()
    assert "app_env" not in client.get("/api/public-config").json()


@pytest.mark.parametrize("path", ["/.env", "/..%2f..%2fapp%2fconfig.py", "/%2e%2e/%2e%2e/backend/app/config.py", "/assets/../../backend/app/config.py", "/index.html.map", "/assets/x.js.map", "/.git/config"])
def test_static_server_does_not_leak_files(client, path):
    r = client.get(path)
    assert "SECRET_KEY" not in r.text and "[core]" not in r.text
    assert r.status_code == 404, (path, r.status_code)


def test_favicon_and_legal_pages_are_served(client):
    assert client.get("/favicon.ico").headers["content-type"].startswith("image/")
    assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg")
    assert client.get("/privacy").status_code == 200 and client.get("/terms").status_code == 200
    assert "favicon" in client.get("/").text


def test_evidence_responses_are_sandboxed(client, student):
    ev = client.post("/api/claims/4/evidence", headers=student, data={"doc_type": "damage_photo"}, files={"file": ("p.png", io.BytesIO(PNG), "image/png")}).json()
    r = client.get(f"/api/claims/4/evidence/{ev['id']}/file", headers=student)
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp


def test_request_id_header_is_sanitised(client):
    r = client.get("/api/health", headers={"X-Request-ID": "abc<script>\"def"})
    assert all(ch.isalnum() or ch in "-_" for ch in r.headers["x-request-id"])


def test_forwarded_for_uses_trusted_hop_not_client_supplied_value(monkeypatch):
    from app import security

    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
        client = type("c", (), {"host": "10.0.0.1"})()
    monkeypatch.setattr(security.settings, "TRUST_PROXY", True)  # the object security.py really uses (test_dotenv reloads app.config)
    assert security.client_ip(Req()) == "203.0.113.9"


# ---------------------------------------------------------------- sessions / cookies
def test_cookie_flags_and_session_rotation(client):
    r1 = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"})
    sc = r1.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc
    t1 = client.cookies.get("sbc_session")
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "aarav", "password": "student123"})
    assert client.cookies.get("sbc_session") != t1


def test_password_change_revokes_other_sessions_and_logout_is_server_side(client):
    a = login(client, "aarav", "student123")
    b = login(client, "aarav", "student123")
    assert client.post("/api/auth/change-password", headers=b, json={"current_password": "student123", "new_password": "a-new-strong-pass-1"}).status_code in (403, 200)
    c = login(client, "aarav", "a-new-strong-pass-1") if client.get("/api/auth/me", headers=a).status_code == 401 else None
    assert client.get("/api/auth/me", headers=a).status_code == 401
    assert c is not None
    csrf_cookie_client = client.post("/api/auth/logout", headers=c)
    assert client.get("/api/auth/me", headers=c).status_code == 401
    assert csrf_cookie_client.status_code in (200, 204)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_database_and_uploads_are_owner_only(client):
    from app.config import settings
    from app.migrate import _sqlite_path
    db = _sqlite_path()
    assert (db.stat().st_mode & 0o077) == 0, oct(db.stat().st_mode)
    assert (settings.UPLOAD_DIR.stat().st_mode & 0o077) == 0, oct(settings.UPLOAD_DIR.stat().st_mode)
