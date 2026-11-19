from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings, validate_production_settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import AuthSession, User, now
from tests.conftest import login


def browser(username="aarav", password="student123"):
    """A cookie-based 'browser' session: returns (client, csrf_headers)."""
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    assert "token" not in r.json()  # tokens are not handed to browser JS
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def test_passwords_are_argon2id_hashed(client):
    with SessionLocal() as db:
        hashes = [u.password_hash for u in db.scalars(select(User))]
    assert hashes and all(h.startswith("$argon2id$") for h in hashes)
    assert not any("student123" in h or "admin123" in h for h in hashes)


def test_session_cookie_flags_and_no_token_in_body(client):
    r = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc and "max-age=" in sc
    assert "secure" not in sc  # test env: COOKIE_SECURE defaults to false outside production


def test_cookie_secure_flag_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    r = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"})
    assert "secure" in r.headers["set-cookie"].lower()
    assert "strict-transport-security" in r.headers


def test_session_token_stored_only_as_hmac(client):
    r = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"}, headers={"X-Return-Token": "1"})
    token = r.json()["token"]
    with SessionLocal() as db:
        stored = [s.token_hash for s in db.scalars(select(AuthSession))]
    assert stored and token not in stored and all(len(h) == 64 for h in stored)


def test_csrf_required_for_cookie_authenticated_writes():
    c, csrf = browser()
    body = {"category": "Laptop", "name": "CSRF test", "purchase_date": "2025-01-01", "declared_value": 1000}
    assert c.post("/api/assets", json=body).status_code == 403  # no CSRF header
    assert c.post("/api/assets", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.post("/api/assets", json=body, headers=csrf).status_code == 201
    assert c.get("/api/assets").status_code == 200  # safe methods need no CSRF token


def test_logout_revokes_session_server_side(client):
    c, csrf = browser()
    cookie = c.cookies.get(settings.COOKIE_NAME)
    assert c.post("/api/auth/logout").status_code == 403  # logout is a write: needs CSRF too
    assert c.post("/api/auth/logout", headers=csrf).status_code == 200
    c.cookies.clear()
    c.cookies.set(settings.COOKIE_NAME, cookie)  # replaying the old cookie must fail: revoked on the server
    assert c.get("/api/auth/me").status_code == 401


def test_session_absolute_and_idle_expiry(client):
    h = login(client, "aarav", "student123")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    with SessionLocal() as db:
        s = db.scalars(select(AuthSession)).all()[-1]
        s.last_seen_at = now() - timedelta(minutes=settings.SESSION_IDLE_MINUTES + 1)
        db.commit()
    assert client.get("/api/auth/me", headers=h).status_code == 401  # idle timeout
    h = login(client, "aarav", "student123")
    with SessionLocal() as db:
        s = db.scalars(select(AuthSession)).all()[-1]
        s.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/me", headers=h).status_code == 401  # absolute expiry


def test_token_in_query_string_is_not_accepted(client):
    r = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"}, headers={"X-Return-Token": "1"})
    token = r.json()["token"]
    fresh = TestClient(app)
    assert fresh.get(f"/api/claims?token={token}").status_code == 401


def test_login_rate_limiting_per_user(client):
    for _ in range(settings.LOGIN_MAX_FAILURES):
        assert client.post("/api/auth/login", json={"username": "aarav", "password": "wrong-password"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "aarav", "password": "student123"})  # even the correct password is blocked now
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert client.post("/api/auth/login", json={"username": "meera", "password": "student123"}).status_code == 200  # other accounts unaffected


def test_login_rate_limit_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_FAILURES", 4)
    for i in range(4):
        client.post("/api/auth/login", json={"username": f"nobody{i}", "password": "x"})
    assert client.post("/api/auth/login", json={"username": "meera", "password": "student123"}).status_code == 429


def test_login_input_validation_and_unknown_user(client):
    assert client.post("/api/auth/login", json={"username": "a" * 80, "password": "x"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "aarav", "password": "x", "role": "admin"}).status_code == 422  # extra fields forbidden
    assert client.post("/api/auth/login", json={"username": "ghost", "password": "x"}).json()["detail"] == "Invalid username or password"
    assert client.post("/api/auth/login", json={"username": "aarav", "password": "x"}).json()["detail"] == "Invalid username or password"  # no user enumeration


def test_student_cannot_reach_admin_or_assessor_endpoints_even_with_forged_requests(client, student):
    forbidden = [("get", "/api/users"), ("post", "/api/users"), ("get", "/api/payments"), ("get", "/api/reserves"), ("get", "/api/audit"),
                 ("post", "/api/plans"), ("put", "/api/plans/1"), ("get", "/api/catalogue"), ("post", "/api/policies"), ("get", "/api/students"),
                 ("post", "/api/claims/1/evaluate"), ("post", "/api/claims/1/items"), ("post", "/api/claims/1/reserve/approve"),
                 ("post", "/api/claims/1/reserve/recommend"), ("post", "/api/claims/1/payments"), ("post", "/api/payments/1/approve"),
                 ("post", "/api/payments/1/simulate-settlement"), ("post", "/api/ai/claims/1/suggest-assessment")]
    for m, url in forbidden:
        r = getattr(client, m)(url, headers=student, **({"json": {}} if m != "get" else {}))
        assert r.status_code == 403, (m, url, r.status_code)
    # privilege-escalation attempts
    me = client.get("/api/auth/me", headers=student).json()
    assert client.put(f"/api/users/{me['id']}", headers=student, json={"role": "admin"}).status_code == 403
    assert client.post("/api/auth/change-password", headers=student, json={"current_password": "student123", "new_password": "a-long-new-password", "role": "admin"}).status_code == 422
    assert client.get("/api/auth/me", headers=student).json()["role"] == "student"
    assert client.post("/api/assets", headers=student, json={"category": "Laptop", "name": "x", "purchase_date": "2025-01-01", "declared_value": 10, "owner_id": 2}).json()["owner_id"] == me["id"]


def test_assessor_cannot_use_admin_only_endpoints(client, assessor):
    for m, url in [("get", "/api/users"), ("post", "/api/users"), ("post", "/api/payments/1/approve"), ("post", "/api/claims/1/reserve/approve")]:
        assert getattr(client, m)(url, headers=assessor, **({"json": {}} if m != "get" else {})).status_code == 403


def test_admin_user_management_validation(client, admin):
    ok = {"username": "new.assessor", "full_name": "New Assessor", "role": "assessor", "password": "a-strong-passphrase"}
    assert client.post("/api/users", headers=admin, json=ok | {"password": "short"}).status_code == 422
    assert client.post("/api/users", headers=admin, json=ok | {"role": "superuser"}).status_code == 422
    assert client.post("/api/users", headers=admin, json=ok | {"username": "Bad Name!"}).status_code == 422
    assert client.post("/api/users", headers=admin, json=ok | {"email": "nope"}).status_code == 422
    assert client.post("/api/users", headers=admin, json=ok | {"password": "new.assessor-123456"}).status_code == 422  # contains username
    u = client.post("/api/users", headers=admin, json=ok)
    assert u.status_code == 201 and "password" not in str(u.json())
    assert client.post("/api/users", headers=admin, json=ok).status_code == 409
    assert login(client, "new.assessor", "a-strong-passphrase")


def test_admin_cannot_demote_or_disable_self_and_disable_kills_sessions(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.put(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 400
    assert client.put(f"/api/users/{me['id']}", headers=admin, json={"role": "student"}).status_code == 400
    sh = login(client, "aarav", "student123")
    sid = client.get("/api/auth/me", headers=sh).json()["id"]
    assert client.put(f"/api/users/{sid}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=sh).status_code == 401  # existing session revoked immediately
    assert client.post("/api/auth/login", json={"username": "aarav", "password": "student123"}).status_code == 401


def test_password_change_and_admin_reset_revoke_sessions(client, admin):
    h1, h2 = login(client, "aarav", "student123"), login(client, "aarav", "student123")
    assert client.post("/api/auth/change-password", headers=h1, json={"current_password": "wrong", "new_password": "another-long-pass"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=h1, json={"current_password": "student123", "new_password": "weak"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h1, json={"current_password": "student123", "new_password": "another-long-pass"}).status_code == 200
    assert client.get("/api/auth/me", headers=h2).status_code == 401 and client.get("/api/auth/me", headers=h1).status_code == 200
    assert client.post("/api/auth/login", json={"username": "aarav", "password": "student123"}).status_code == 401
    uid = client.get("/api/auth/me", headers=h1).json()["id"]
    assert client.post(f"/api/users/{uid}/reset-password", headers=admin, json={"new_password": "reset-by-admin-123"}).status_code == 200
    assert client.get("/api/auth/me", headers=h1).status_code == 401


def test_demo_accounts_endpoint_disabled_outside_development(client, monkeypatch):
    assert client.get("/api/auth/demo-accounts").status_code == 200
    monkeypatch.setattr(settings, "SEED_DEMO_DATA", False)
    assert client.get("/api/auth/demo-accounts").status_code == 404


def test_production_config_refuses_unsafe_defaults(monkeypatch):
    monkeypatch.setattr(settings, "IS_PRODUCTION", True)
    with pytest.raises(RuntimeError) as e:
        validate_production_settings()
    assert "SECRET_KEY" in str(e.value) and "SEED_DEMO_DATA" in str(e.value) and "COOKIE_SECURE" in str(e.value)
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 40); monkeypatch.setattr(settings, "COOKIE_SECURE", True); monkeypatch.setattr(settings, "SEED_DEMO_DATA", False)
    validate_production_settings()


def test_bootstrap_admin_only_when_no_demo_data(monkeypatch, tmp_path):
    from app import bootstrap
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    eng = create_engine(f"sqlite:///{(tmp_path / 'b.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(settings, "SEED_DEMO_DATA", False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "root.admin")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "a-long-bootstrap-pass")
    with sessionmaker(bind=eng)() as db:
        bootstrap.run(db)
        users = db.scalars(select(User)).all()
        assert [(u.username, u.role) for u in users] == [("root.admin", "admin")] and users[0].password_hash.startswith("$argon2id$")


def test_health_ready_and_error_envelope(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/ready").json() == {"status": "ready", "schema_revision": "0006"}
    r = client.get("/api/claims")
    r2 = TestClient(app).get("/api/claims")
    assert r2.status_code == 401 and r2.json()["error"]["request_id"] and r2.headers["x-request-id"] == r2.json()["error"]["request_id"]
    assert r2.headers["x-content-type-options"] == "nosniff" and r2.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r2.headers["content-security-policy"]
    assert r2.headers["cache-control"] == "no-store"


def test_unhandled_errors_do_not_leak_details(client, monkeypatch):
    import app.routers.core as core
    def boom(*a, **k):
        raise RuntimeError("secret internal detail /etc/passwd")
    monkeypatch.setattr(core, "list_assets", boom, raising=False)
    h = login(client, "aarav", "student123")
    app.router.routes  # noqa
    from app import services
    monkeypatch.setattr(services, "asset_dict", boom)
    r = client.get("/api/assets", headers=h)
    assert r.status_code == 500 and "secret internal detail" not in r.text and r.json()["detail"] == "Internal server error"
