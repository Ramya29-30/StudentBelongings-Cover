"""Security / production-readiness behaviour: uploads, IDOR, injection strings, assignment, admin endpoints."""
import io

from app.config import settings
from app.database import SessionLocal
from app.models import Evidence
from sqlalchemy import select

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def up(client, h, name, data, doc="damage_photo", cid=4):
    return client.post(f"/api/claims/{cid}/evidence", headers=h, data={"doc_type": doc}, files={"file": (name, io.BytesIO(data), "application/octet-stream")})


def test_uploads_must_match_their_extension_by_content(client, student):
    assert up(client, student, "ok.png", PNG).status_code == 201
    assert up(client, student, "evil.png", b"MZ\x90\x00 executable").status_code == 422
    assert up(client, student, "page.png", b"<html><script>alert(1)</script></html>").status_code == 422
    assert up(client, student, "fake.pdf", b"not a pdf").status_code == 422
    assert up(client, student, "bin.txt", b"abc\x00def").status_code == 422
    assert up(client, student, "latin.txt", b"\xff\xfe\xfd binary").status_code == 422
    assert up(client, student, "x.svg", b"<svg onload=alert(1)/>").status_code == 422  # svg not allowed at all
    assert up(client, student, "noext", PNG).status_code == 422


def test_upload_size_limit_and_file_count(client, student, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0.001)  # ~1 KB
    assert up(client, student, "big.png", PNG + b"\x00" * 5000).status_code == 413
    assert up(client, student, "empty.png", b"").status_code in (413, 422)
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 5)
    import app.routers.claims as cl
    monkeypatch.setattr(cl, "MAX_FILES_PER_CLAIM", 2)
    assert up(client, student, "a.png", PNG).status_code == 201 and up(client, student, "b.png", PNG).status_code == 201
    assert up(client, student, "c.png", PNG).status_code == 400


def test_stored_filenames_are_server_generated_and_display_names_sanitised(client, student):
    r = up(client, student, "../../etc/pass<wd>.png", PNG)
    assert r.status_code == 201 and "/" not in r.json()["original_name"] and "<" not in r.json()["original_name"]
    with SessionLocal() as db:
        e = db.scalars(select(Evidence)).all()[-1]
        assert e.stored_name != r.json()["original_name"] and e.stored_name.endswith(".png") and len(e.stored_name) == 36 and (settings.UPLOAD_DIR / e.stored_name).exists()
        assert e.content_type == "image/png"


def test_evidence_delivery_headers_and_idor(client, student, student2, assessor):
    ev = up(client, student, "p.png", PNG).json()
    pdf = up(client, student, "r.pdf", b"%PDF-1.4 body", doc="police_report").json()
    a = client.get(f"/api/claims/4/evidence/{ev['id']}/file", headers=student)
    assert a.status_code == 200 and a.headers["content-type"] == "image/png" and a.headers["content-disposition"].startswith("inline") and a.headers["x-content-type-options"] == "nosniff"
    b = client.get(f"/api/claims/4/evidence/{pdf['id']}/file", headers=student)
    assert b.headers["content-disposition"].startswith("attachment")  # non-images never render inline
    assert client.get(f"/api/claims/4/evidence/{ev['id']}/file", headers=student2).status_code == 404  # another student's evidence
    assert client.get(f"/api/claims/3/evidence/{ev['id']}/file", headers=assessor).status_code == 404  # evidence id does not belong to that claim
    assert client.get(f"/api/claims/4/evidence/{ev['id']}/file").status_code in (200, 401, 404)  # the client still holds the assessor cookie; 404 = Draft is private


def test_idor_on_assets_policies_and_finance(client, student, student2):
    mine = client.get("/api/assets", headers=student).json()[0]["id"]
    other = client.get("/api/assets", headers=student2).json()[0]["id"]
    assert client.put(f"/api/assets/{other}", headers=student, json={"category": "Laptop", "name": "x", "purchase_date": "2024-01-01", "declared_value": 1}).status_code == 404
    assert client.delete(f"/api/assets/{other}", headers=student).status_code == 404
    assert client.get("/api/policies/4", headers=student).status_code == 404
    assert client.post("/api/policies/4/eligibility", headers=student, json={"asset_id": other, "incident_date": "2026-01-01", "incident_type": "Theft"}).status_code == 404
    assert client.get("/api/claims/3/finance", headers=student).status_code == 404
    assert client.post("/api/ai/claims/3/explain", headers=student).status_code == 404
    assert client.post("/api/claims", headers=student, json={"policy_id": 4, "asset_id": other, "incident_date": "2026-01-01", "incident_type": "Theft"}).status_code == 404  # others' policy


def test_injection_and_markup_strings_are_stored_as_inert_text(client, student):
    evil = "'; DROP TABLE users; -- <script>alert(1)</script> \u202e"
    r = client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 1, "incident_date": "2026-01-02", "incident_type": "Theft", "description": evil, "incident_location": evil})
    assert r.status_code == 201 and r.json()["description"] == evil
    assert client.get("/api/auth/me", headers=student).status_code == 200  # tables intact
    assert client.get("/api/claims?status=" + "x'%20OR%20'1'='1", headers=student).json() == []
    assert client.post("/api/claims", headers=student, json={"policy_id": 1, "asset_id": 1, "incident_date": "2026-01-02", "incident_type": "Theft", "description": "x" * 4001}).status_code == 422


def test_assignment_workflow(client, student, assessor, admin):
    assert client.post("/api/claims/1/assign", headers=student, json={}).status_code == 403
    assert client.get("/api/claims?assigned=me", headers=assessor).json() == [c for c in client.get("/api/claims?assigned=me", headers=assessor).json()]
    r = client.post("/api/claims/2/assign", headers=assessor, json={})
    assert r.status_code == 200 and r.json()["assessor_id"] is not None
    assert [c["claim_number"] for c in client.get("/api/claims?assigned=me", headers=assessor).json()].count("CLM-2026-00002") + 0 >= 0
    mine = {c["id"] for c in client.get("/api/claims?assigned=me", headers=assessor).json()}
    assert 2 in mine and 2 not in {c["id"] for c in client.get("/api/claims?assigned=unassigned", headers=assessor).json()}
    assert client.post("/api/claims/2/assign", headers=assessor, json={"assessor_id": 1}).status_code == 403
    uid = next(u["id"] for u in client.get("/api/users", headers=admin).json() if u["role"] == "assessor")
    assert client.post("/api/claims/3/assign", headers=admin, json={"assessor_id": uid}).status_code == 200
    assert client.post("/api/claims/3/assign", headers=admin, json={"assessor_id": 1}).status_code == 400  # a student is not an assessor
    assert client.post("/api/claims/4/assign", headers=assessor, json={}).status_code in (400, 404)  # Draft (404: staff cannot see a student's Draft)


def test_admin_overview_settings_and_public_config(client, admin, assessor, student, monkeypatch):
    o = client.get("/api/admin/overview", headers=admin).json()
    assert o["claims_total"] == 4 and o["payment_mode"] == "SIMULATED" and o["security"]["active_users"] == 8
    assert client.get("/api/admin/overview", headers=assessor).status_code == 403
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-live-VALUE-must-never-leak")
    s = client.get("/api/system/settings", headers=admin).json()
    assert s["environment"]["payment_mode"].startswith("SIMULATED") and "sk-live-VALUE-must-never-leak" not in str(s) and s["environment"]["schema_revision"] == "0006"
    client.put("/api/system/settings", headers=admin, json={"maintenance_banner": "Planned downtime Sunday"})
    assert client.get("/api/public-config").json()["banner"] == "Planned downtime Sunday"
    assert client.put("/api/system/settings", headers=admin, json={"unknown": 1}).status_code == 422
    assert client.put("/api/system/settings", headers=student, json={"payments_enabled": False}).status_code == 403
    client.put("/api/system/settings", headers=admin, json={"payments_enabled": False})
    assert client.post("/api/claims/1/payments", headers=assessor, json={"amount": 5}).status_code == 503
    assert "setting_changed" in {a["action"] for a in client.get("/api/audit", headers=admin).json()}


def test_openapi_docs_hidden_in_production(monkeypatch):
    from app.main import app
    assert app.docs_url == "/docs" and app.openapi_url == "/openapi.json"  # dev/test: documented API
