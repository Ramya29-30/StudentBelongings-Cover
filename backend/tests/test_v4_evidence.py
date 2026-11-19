"""Registration evidence: what a student uploads, what staff review, and the rule that no policy is activated before an administrator approves it."""
from datetime import date, timedelta

import pytest

from app.config import settings
from tests.helpers_v3 import add_asset, admin_headers, approve_evidence, cat_id, make_img, register_login


def db():
    from app.database import SessionLocal
    return SessionLocal()


def review(client, aid, decision, note="", **kw):
    return client.post(f"/api/v2/admin/assets/{aid}/evidence-review", json={"decision": decision, "note": note, **kw}, headers=admin_headers(client))


def test_registration_collects_front_back_invoice_and_extras_and_starts_pending(client):
    h = register_login(client)
    files = {"front_photo": ("f.png", make_img(947), "image/png"), "back_photo": ("b.png", make_img(983), "image/png"), "invoice": ("i.png", make_img(939), "image/png"),
             "extra_files": ("e.png", make_img(61), "image/png")}
    r = client.post("/api/v2/assets", data={"category_id": cat_id(client, "Laptop"), "brand": "Acme", "model": "X1", "purchase_price": 42000, "serial_number": "SN-1",
                                            "purchase_date": str(date.today() - timedelta(days=50))}, files=files, headers=h)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["evidence_status"] == "Pending review" and a["can_purchase"] is False
    ev = a["evidence"]
    assert ev["counts"]["front_photo"] == 1 and ev["counts"]["back_photo"] == 1 and ev["counts"]["invoice"] == 1 and ev["counts"]["extra_photo"] == 1
    assert ev["missing_required"] == [] and ev["has_invoice"] is True and ev["can_add"] is True
    # a student never sees fingerprints or reviewer flags
    assert all("sha256" not in f and "flags" not in f for f in ev["files"])
    with db() as s:
        from app.models import AssetEvidence
        rows = s.query(AssetEvidence).filter_by(asset_id=a["id"]).all()
        assert len(rows) == 4 and all(len(x.sha256) == 64 for x in rows) and all(x.review_status == "Pending" for x in rows)
        assert all("/" not in x.stored_name and ".." not in x.stored_name for x in rows)


def test_legacy_field_name_photo_still_registers_and_front_photo_is_required(client):
    h = register_login(client)
    base = {"category_id": cat_id(client, "Earbuds"), "brand": "a", "model": "b", "purchase_price": 3000, "purchase_date": str(date.today())}
    ok = client.post("/api/v2/assets", data=base, files={"photo": ("p.png", make_img(2), "image/png"), "invoice": ("i.png", make_img(3), "image/png")}, headers=h)
    assert ok.status_code == 201 and ok.json()["evidence"]["counts"]["front_photo"] == 1
    none = client.post("/api/v2/assets", data=base, files={"invoice": ("i.png", make_img(3), "image/png")}, headers=h)
    assert none.status_code == 422 and "front photograph" in none.json()["detail"]


def test_upload_validation_covers_every_evidence_field(client):
    h = register_login(client)
    base = {"category_id": cat_id(client, "Earbuds"), "brand": "a", "model": "b", "purchase_price": 3000, "purchase_date": str(date.today())}
    front = ("f.png", make_img(2), "image/png")
    for name, bad in (("back_photo", ("b.exe", b"MZ\x90\x00", "application/octet-stream")), ("back_photo", ("b.png", b"not an image", "image/png")),
                      ("extra_files", ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")), ("invoice", ("i.php", b"<?php echo 1;", "text/plain"))):
        r = client.post("/api/v2/assets", data=base, files={"front_photo": front, name: bad}, headers=h)
        assert r.status_code == 422, (name, r.text)
    with db() as s:
        from app.models import Asset
        assert s.query(Asset).filter(Asset.owner_id.isnot(None), Asset.category_id.isnot(None), Asset.brand == "a").count() == 0  # nothing half-stored
    many = [("extra_files", (f"e{i}.png", make_img(70 + i), "image/png")) for i in range(settings.EVIDENCE_PER_ASSET_MAX + 1)]
    assert client.post("/api/v2/assets", data=base, files=[("front_photo", front)] + many, headers=h).status_code == 422


def test_no_policy_before_administrator_approval(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    r = client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert r.status_code == 409 and "administrator" in r.json()["detail"]
    assert review(client, a["id"], "approve", "Photos and invoice checked.").status_code == 200
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h).status_code == 201


def test_rejected_and_more_evidence_requested_also_block_purchase(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    assert review(client, a["id"], "request_more", "Please send a sharper back photo.").status_code == 200
    r = client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert r.status_code == 409 and "sharper back photo" in r.json()["detail"]
    b = add_asset(client, h, serial="SN-2").json()
    assert review(client, b["id"], "reject", "The invoice is for a different product.").status_code == 200
    assert client.post(f"/api/v2/assets/{b['id']}/purchase", json={"accept_terms": True}, headers=h).status_code == 409


def test_approval_needs_front_and_back_and_either_an_invoice_or_an_explained_exception(client):
    h = register_login(client)
    a = add_asset(client, h, back=False, invoice=False).json()
    assert a["evidence"]["missing_required"] == ["Back photograph"]
    miss = review(client, a["id"], "approve", "looks fine")
    assert miss.status_code == 409 and "Back photograph" in miss.json()["detail"]
    # the student adds the back photo later
    up = client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "back_photo"}, files={"file": ("b.png", make_img(983), "image/png")}, headers=h)
    assert up.status_code == 201 and up.json()["missing_required"] == []
    noinv = review(client, a["id"], "approve", "fine")
    assert noinv.status_code == 409 and "No invoice" in noinv.json()["detail"]
    assert review(client, a["id"], "approve", "", accept_missing_invoice=True).status_code == 422  # exception needs a reason
    ok = review(client, a["id"], "approve", "Receipt lost; seller confirmed by phone.", accept_missing_invoice=True)
    assert ok.status_code == 200 and ok.json()["evidence_status"] == "Approved" and ok.json()["invoice_verified"] is False


def test_students_cannot_set_or_change_review_status(client, admin):
    h = register_login(client)
    a = add_asset(client, h).json()
    assert client.post(f"/api/v2/admin/assets/{a['id']}/evidence-review", json={"decision": "approve", "note": "me"}, headers=h).status_code == 403
    assert client.get("/api/v2/admin/evidence-reviews", headers=h).status_code == 403
    assert client.get(f"/api/v2/admin/assets/{a['id']}/evidence-review", headers=h).status_code == 403
    # smuggled form fields are ignored
    r = client.post("/api/v2/assets", data={"category_id": cat_id(client, "Laptop"), "brand": "z", "model": "z", "purchase_price": 42000, "serial_number": "SN-X", "evidence_status": "Approved",
                                            "invoice_verified": "true", "purchase_date": str(date.today())}, files={"front_photo": ("f.png", make_img(5), "image/png")}, headers=h)
    assert r.status_code == 201 and r.json()["evidence_status"] == "Pending review" and r.json()["invoice_verified"] is False
    # the upload route has no status field either, and an extra JSON key on the review is refused
    assert client.post(f"/api/v2/admin/assets/{a['id']}/evidence-review", json={"decision": "approve", "note": "ok ok", "evidence_status": "Approved"}, headers=admin).status_code == 422
    assert client.get(f"/api/v2/assets/{a['id']}", headers=h).json()["evidence_status"] == "Pending review"


def test_other_students_cannot_read_or_change_evidence(client):
    h1, h2 = register_login(client, "one"), register_login(client, "two")
    a = add_asset(client, h1).json()
    eid = a["evidence"]["files"][0]["id"]
    assert client.get(f"/api/v2/assets/{a['id']}/evidence", headers=h2).status_code == 404
    assert client.get(f"/api/v2/assets/{a['id']}/evidence/{eid}/file", headers=h2).status_code == 404
    assert client.delete(f"/api/v2/assets/{a['id']}/evidence/{eid}", headers=h2).status_code == 404
    assert client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "extra_photo"}, files={"file": ("e.png", make_img(9), "image/png")}, headers=h2).status_code == 404
    assert client.get(f"/api/v2/assets/{a['id']}/evidence/{eid}/file", headers=h1).status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/v2/assets/{a['id']}/evidence/{eid}/file").status_code == 401


def test_evidence_is_locked_once_approved_and_reopens_when_more_is_requested(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    assert review(client, a["id"], "request_more", "Back photo is too dark.").status_code == 200
    up = client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "back_photo"}, files={"file": ("b2.png", make_img(990), "image/png")}, headers=h)
    assert up.status_code == 201
    assert client.get(f"/api/v2/assets/{a['id']}", headers=h).json()["evidence_status"] == "Pending review"  # back in the queue
    assert review(client, a["id"], "approve", "Now fine.").status_code == 200
    late = client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "extra_photo"}, files={"file": ("x.png", make_img(991), "image/png")}, headers=h)
    assert late.status_code == 409
    fid = client.get(f"/api/v2/assets/{a['id']}/evidence", headers=h).json()["files"][0]["id"]
    assert client.delete(f"/api/v2/assets/{a['id']}/evidence/{fid}", headers=h).status_code == 409


def test_replacing_a_single_kind_removes_the_old_file_from_disk(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    with db() as s:
        from app.models import AssetEvidence
        old = s.query(AssetEvidence).filter_by(asset_id=a["id"], kind="front_photo").one()
        old_path = settings.UPLOAD_DIR / old.stored_name
        assert old_path.is_file()
    client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "front_photo"}, files={"file": ("new.png", make_img(995), "image/png")}, headers=h)
    with db() as s:
        rows = s.query(AssetEvidence).filter_by(asset_id=a["id"], kind="front_photo").all()
        assert len(rows) == 1 and rows[0].original_name == "new.png"
    assert not old_path.exists()


def test_review_decisions_are_audited_and_need_a_reason_when_negative(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    assert review(client, a["id"], "reject", "no").status_code == 422
    assert review(client, a["id"], "request_more", "Please add a clearer invoice.").status_code == 200
    assert review(client, a["id"], "approve", "All good now.").status_code == 200
    with db() as s:
        from app.models import AuditRecord
        acts = [(r.action, r.detail.get("decision")) for r in s.query(AuditRecord).filter_by(entity_type="asset", entity_id=a["id"]).order_by(AuditRecord.id)]
        uploads = [r for r in s.query(AuditRecord).filter_by(entity_type="asset_evidence", action="evidence_uploaded") if r.detail.get("asset_id") == a["id"]]
    assert ("evidence_review_decided", "request_more") in acts and ("evidence_review_decided", "approve") in acts
    assert len(uploads) == 3 and all(len(u.detail["sha256"]) == 64 for u in uploads)  # front, back, invoice
    d = client.get(f"/api/v2/admin/assets/{a['id']}/evidence-review", headers=admin_headers(client)).json()
    assert [x["decision"] for x in d["review_history"]] == ["approve", "request_more"]


def test_an_insured_asset_cannot_be_re_reviewed(client):
    h = register_login(client)
    a = add_asset(client, h).json()
    assert approve_evidence(client, a["id"]).status_code == 200
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h).status_code == 201
    r = review(client, a["id"], "reject", "Changed my mind about this.")
    assert r.status_code == 409 and "active policy" in r.json()["detail"]


def test_admin_queue_lists_assets_with_flags_and_filters_by_status(client):
    h1, h2 = register_login(client, "one"), register_login(client, "two")
    a = add_asset(client, h1, serial="S-1").json()
    b = add_asset(client, h2, serial="S-2", back=False).json()
    adm = admin_headers(client)
    q = client.get("/api/v2/admin/evidence-reviews", headers=adm).json()
    mine = {r["id"]: r for r in q}
    assert mine[a["id"]]["evidence_status"] == "Pending review" and mine[b["id"]]["missing_required"] == ["Back photograph"]
    assert approve_evidence(client, a["id"]).status_code == 200
    pend = client.get("/api/v2/admin/evidence-reviews?status=Pending%20review", headers=adm).json()
    assert a["id"] not in [r["id"] for r in pend] and b["id"] in [r["id"] for r in pend]
    assert client.get("/api/v2/admin/evidence-reviews?status=Bogus", headers=adm).status_code == 422
    assert client.get("/api/v2/admin/overview", headers=adm).json()["pending_evidence_reviews"] >= 1


def test_reviewer_sees_duplicate_flags_students_do_not(client):
    h1, h2 = register_login(client, "one"), register_login(client, "two")
    first = add_asset(client, h1, serial="S-1", seeds=(939, 947, 983))
    assert first.status_code == 201
    second = add_asset(client, h2, serial="S-2", seeds=(939, 947, 983))  # identical files registered by another student
    assert second.status_code == 201
    assert "flags" not in str(second.json()["evidence"])
    d = client.get(f"/api/v2/admin/assets/{second.json()['id']}/evidence-review", headers=admin_headers(client)).json()
    codes = {f["code"] for e in d["evidence"]["files"] for f in e["flags"]}
    assert "REG-DUP-EXACT" in codes
    assert "another student" in " ".join(f["text"] for e in d["evidence"]["files"] for f in e["flags"] if f["code"] == "REG-DUP-EXACT") or "different student" in str([f for e in d["evidence"]["files"] for f in e["flags"]])


def test_identical_front_and_back_is_flagged_for_the_reviewer(client):
    h = register_login(client)
    r = client.post("/api/v2/assets", data={"category_id": cat_id(client, "Laptop"), "brand": "a", "model": "b", "purchase_price": 42000, "serial_number": "S-9", "purchase_date": str(date.today())},
                    files={"front_photo": ("f.png", make_img(947), "image/png"), "back_photo": ("b.png", make_img(947), "image/png")}, headers=h)
    assert r.status_code == 201
    d = client.get(f"/api/v2/admin/assets/{r.json()['id']}/evidence-review", headers=admin_headers(client)).json()
    assert "REG-SAME-VIEW" in {f["code"] for e in d["evidence"]["files"] for f in e["flags"]}


def test_students_have_a_per_hour_cap_on_evidence_uploads(client, monkeypatch):
    from app.routers import insure
    h = register_login(client)
    a = add_asset(client, h).json()
    monkeypatch.setattr(insure.settings, "UPLOADS_PER_HOUR", 2)
    codes = [client.post(f"/api/v2/assets/{a['id']}/evidence", data={"kind": "extra_photo"}, files={"file": (f"e{i}.png", make_img(300 + i), "image/png")}, headers=h).status_code for i in range(3)]
    assert 429 in codes
