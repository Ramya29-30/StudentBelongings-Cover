"""API / workflow tests against the seeded demo database."""
import io
from datetime import date, timedelta

from tests.conftest import login


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def new_claim(client, h, policy_id, asset_id, itype="Accidental Damage", ago=10, desc="Dropped the laptop; screen cracked."):
    r = client.post("/api/claims", headers=h, json={"policy_id": policy_id, "asset_id": asset_id, "incident_date": days_ago(ago), "incident_type": itype,
                                                    "incident_location": "Hostel", "description": desc})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, h, cid, doc_type="damage_photo", name="photo.png", data=b"\x89PNG\r\n\x1a\nfake"):
    r = client.post(f"/api/claims/{cid}/evidence", headers=h, data={"doc_type": doc_type}, files={"file": (name, io.BytesIO(data), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- full lifecycle (also covers #1, #11 and AI fallback honesty)
def test_end_to_end_claim_lifecycle_with_human_correction_of_ai_suggestion(client, student, assessor):
    c = new_claim(client, student, 1, 1)
    ev = upload(client, student, c["id"])
    r = client.post(f"/api/claims/{c['id']}/submit", headers=student)
    assert r.status_code == 200 and r.json()["status"] == "Submitted"
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Under Assessment"}).status_code == 200

    sug = client.post(f"/api/ai/claims/{c['id']}/suggest-assessment", headers=assessor).json()
    assert sug["is_ai"] is False and "NOT an AI result" in sug["label"] and "DEMO FALLBACK" in sug["status_note"]  # honest fallback labelling
    original = sug["content"]
    item = client.post(f"/api/ai/suggestions/{sug['id']}/accept-item", headers=assessor).json()
    assert item["verification_status"] == "AI Suggested" and item["ai_suggestion_id"] == sug["id"]

    # unverified AI item blocks completion
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Assessment Completed"}).status_code == 400

    # human corrects the AI suggestion (#11): different severity, explicit assessor prices
    body = {"component": "Screen", "damage_type": "Cracked screen", "severity": "Severe", "repair_action": "Repair", "parts_cost": 4000, "labour_cost": 500,
            "evidence_refs": [ev["id"]], "confidence": "Medium", "notes": "Confirmed from photo", "decision_reason": "Crack spans full panel",
            "ai_suggestion_id": sug["id"]}
    upd = client.put(f"/api/items/{item['id']}", headers=assessor, json=body).json()
    assert upd["verification_status"] == "Human Corrected" and upd["severity"] == "Severe" and upd["price_source"] == "assessor"
    assert client.get(f"/api/ai/claims/{c['id']}/suggestions", headers=assessor).json()[0]["content"] == original  # AI output stays untouched
    audit = client.get(f"/api/claims/{c['id']}/audit", headers=assessor).json()
    corr = [a for a in audit if a["action"] == "damage_item_corrected"]
    assert corr and corr[0]["detail"]["changes"]["severity"]["after"] == "Severe"

    ev_out = client.post(f"/api/claims/{c['id']}/evaluate", headers=assessor).json()
    assert ev_out["estimated_payable"] == 3500 and ev_out["recommendation"] == "RECOMMEND_APPROVAL_REVIEW"  # 4500 - 1000 deductible (Campus Plus)
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Assessment Completed"}).status_code == 200
    # approval needs a reason, and never pays out automatically
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Approved for Review"}).status_code == 400
    ok = client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Approved for Review", "reason": "Verified damage, covered peril"})
    assert ok.status_code == 200 and ok.json()["status"] == "Approved for Review"
    rep = client.get(f"/api/claims/{c['id']}/report", headers=student).json()
    assert rep["claim"]["estimated_payable"] == 3500 and rep["ai_suggestions"] == [] and "recommendation" in rep["disclaimer"]
    assert len(rep["evaluation"]["rule_results"]) >= 13 and rep["evaluation"]["calculation_lines"][-1]["amount"] == 3500
    hist = [h["to"] for h in client.get(f"/api/claims/{c['id']}", headers=assessor).json()["status_history"]]
    assert hist == ["Draft", "Submitted", "Under Assessment", "Assessment Completed", "Approved for Review"]


# ---------------------------------------------------------------- policy versions: eligibility on the incident date
def test_policy_version_in_force_on_incident_date(client, student, assessor):
    # seeded policy 1 added the bicycle 60 days ago -> a theft 100 days ago is not covered, one 30 days ago is
    old = new_claim(client, student, 1, 4, "Theft", ago=100, desc="Stolen")
    new = new_claim(client, student, 1, 4, "Theft", ago=30, desc="Stolen")
    for c in (old, new):
        upload(client, student, c["id"], "police_report", "fir.pdf", b"%PDF-1.4 x")
        client.post(f"/api/claims/{c['id']}/submit", headers=student)
    r_old = {r["rule_id"]: r for r in client.get(f"/api/claims/{old['id']}/evaluation", headers=assessor).json()["rule_results"]}
    r_new = {r["rule_id"]: r for r in client.get(f"/api/claims/{new['id']}/evaluation", headers=assessor).json()["rule_results"]}
    assert r_old["POL-002"]["outcome"] == "FAIL" and "version 1" in r_old["POL-002"]["reason"]
    assert r_new["POL-002"]["outcome"] == "PASS"


def test_eligibility_endpoint_shows_reason(client, admin):
    r = client.post("/api/policies/2/eligibility", headers=admin, json={"asset_id": 5, "incident_date": days_ago(10), "incident_type": "Theft"}).json()
    assert r["eligible"] is False and any(x["rule_id"] == "POL-001" and "after the policy expiry" in x["reason"] for x in r["results"])


def test_plan_edit_does_not_change_existing_policy_until_reissued(client, admin):
    plan = client.get("/api/plans/2", headers=admin).json()
    plan["deductible_value"] = 2500
    assert client.put("/api/plans/2", headers=admin, json=plan).status_code == 200
    pol = client.get("/api/policies/1", headers=admin).json()
    assert pol["versions"][-1]["terms"]["deductible_value"] == 1000
    pol = client.post("/api/policies/1/reissue", headers=admin, json={}).json()
    assert pol["versions"][-1]["terms"]["deductible_value"] == 2500 and pol["current_version"] == 3


# ---------------------------------------------------------------- policy lifecycle validation
def test_policy_status_transitions_are_validated(client, admin):
    p = client.post("/api/policies", headers=admin, json={"student_id": 2, "plan_id": 1, "start_date": days_ago(0), "end_date": (date.today() + timedelta(days=300)).isoformat(),
                                                           "asset_ids": []}).json()
    assert p["status"] == "Draft"
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Active"}).status_code == 400  # no assets
    assert client.post(f"/api/policies/{p['id']}/assets", headers=admin, json={"asset_id": 6}).status_code == 201
    assert client.post(f"/api/policies/{p['id']}/assets", headers=admin, json={"asset_id": 1}).status_code == 400  # not this student's asset
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Expired"}).status_code == 400
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Active"}).json()["status"] == "Active"
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Draft"}).status_code == 400
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Cancelled"}).status_code == 400  # reason required
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Cancelled", "reason": "test"}).json()["status"] == "Cancelled"
    assert client.post(f"/api/policies/{p['id']}/transition", headers=admin, json={"to": "Active"}).status_code == 400  # terminal
    bad = client.post("/api/policies", headers=admin, json={"student_id": 2, "plan_id": 1, "start_date": days_ago(0), "end_date": days_ago(5)})
    assert bad.status_code == 400


def test_asset_validation_and_delete_protection(client, student):
    base = {"category": "Laptop", "name": "X", "purchase_date": days_ago(5), "declared_value": 1000}
    assert client.post("/api/assets", headers=student, json=base | {"category": "Spaceship"}).status_code == 422
    assert client.post("/api/assets", headers=student, json=base | {"declared_value": 0}).status_code == 422
    assert client.post("/api/assets", headers=student, json=base | {"purchase_date": (date.today() + timedelta(days=3)).isoformat()}).status_code == 422
    a = client.post("/api/assets", headers=student, json=base).json()
    assert client.delete(f"/api/assets/{a['id']}", headers=student).status_code == 204
    assert client.delete("/api/assets/1", headers=student).status_code == 409  # insured / claimed


# ---------------------------------------------------------------- claim rules via API (#3 #4 #9 #10 through the stack)
def test_duplicate_and_unpriced_flags_via_api(client, student, assessor):
    a = new_claim(client, student, 1, 2, ago=12)
    b = new_claim(client, student, 1, 2, ago=12)
    for c in (a, b):
        upload(client, student, c["id"])
        client.post(f"/api/claims/{c['id']}/submit", headers=student)
    res = {r["rule_id"]: r for r in client.get(f"/api/claims/{b['id']}/evaluation", headers=assessor).json()["rule_results"]}
    assert res["POL-010"]["outcome"] == "FLAG" and a["claim_number"] in res["POL-010"]["reason"]
    client.post(f"/api/claims/{b['id']}/status", headers=assessor, json={"to": "Under Assessment"})
    client.post(f"/api/claims/{b['id']}/items", headers=assessor, json={"component": "Back panel", "damage_type": "Other", "repair_action": "Repair"})
    ev = client.post(f"/api/claims/{b['id']}/evaluate", headers=assessor).json()
    assert [r for r in ev["rule_results"] if r["rule_id"] == "POL-012"][0]["outcome"] == "PENDING" and ev["estimated_payable"] == 0
    assert client.post(f"/api/claims/{b['id']}/status", headers=assessor, json={"to": "Assessment Completed"}).status_code == 400


def test_missing_evidence_via_api_and_pending_information_flow(client, student, assessor):
    c = new_claim(client, student, 1, 1)
    ev = client.post(f"/api/claims/{c['id']}/submit", headers=student).json()
    assert ev["recommendation"] == "PENDING_INFORMATION"
    client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Under Assessment"})
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Pending Information"}).status_code == 400  # reason needed
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Pending Information", "reason": "Please upload a photo"}).status_code == 200
    upload(client, student, c["id"])
    assert client.post(f"/api/claims/{c['id']}/status", headers=student, json={"to": "Submitted"}).status_code == 200


def test_evidence_upload_validation(client, student):
    c = new_claim(client, student, 1, 1)
    bad = client.post(f"/api/claims/{c['id']}/evidence", headers=student, data={"doc_type": "damage_photo"}, files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert bad.status_code == 422
    bad = client.post(f"/api/claims/{c['id']}/evidence", headers=student, data={"doc_type": "nonsense"}, files={"file": ("a.png", io.BytesIO(b"x"), "image/png")})
    assert bad.status_code == 422


# ---------------------------------------------------------------- AI behaviour
def test_ai_status_reports_unconfigured_and_explanations_are_grounded(client, assessor, student):
    st = client.get("/api/ai/status", headers=assessor).json()
    assert st["configured"] is False and "not configured" in st["message"]
    ex = client.post("/api/ai/claims/1/explain", headers=assessor).json()
    assert ex["is_ai"] is False and "3,500.00" in ex["content"]["explanation"]
    pe = client.post("/api/ai/policies/1/explain", headers=student).json()
    assert "Overall limit" in pe["content"]["explanation"] and pe["is_ai"] is False


def test_quotation_text_fallback_extracts_lines_for_user_verification(client, assessor, student):
    c = new_claim(client, student, 1, 1)
    quote = b"Screen panel   Rs 4,000\nLabour - 500\nTotal 4500\n"
    e = client.post(f"/api/claims/{c['id']}/evidence", headers=student, data={"doc_type": "repair_quote"}, files={"file": ("q.txt", io.BytesIO(quote), "text/plain")}).json()
    client.post(f"/api/claims/{c['id']}/submit", headers=student)
    out = client.post(f"/api/ai/claims/{c['id']}/extract-quotation", headers=assessor, json={"evidence_id": e["id"]}).json()
    assert [(i["description"], i["amount"]) for i in out["content"]["line_items"]] == [("Screen panel", 4000.0), ("Labour", 500.0)]
    assert out["is_ai"] is False and "verify" in out["verify_notice"].lower()


# ---------------------------------------------------------------- role-based access (#12)
def test_role_based_access_restrictions(client, student, student2, admin, assessor):
    client.cookies.clear()  # the test client keeps the session cookie set by login; an anonymous caller has none
    assert client.get("/api/claims").status_code == 401
    assert client.get("/api/dashboard", headers={"Authorization": "Bearer junk"}).status_code == 401
    # student restrictions
    assert client.get("/api/catalogue", headers=student).status_code == 403
    assert client.get("/api/audit", headers=student).status_code == 403
    assert client.post("/api/plans", headers=student, json={}).status_code == 403
    assert client.post("/api/policies", headers=student, json={}).status_code == 403
    assert client.post("/api/policies/1/transition", headers=student, json={"to": "Cancelled", "reason": "x"}).status_code == 403
    assert client.post("/api/claims/1/evaluate", headers=student).status_code == 403
    assert client.post("/api/claims/1/items", headers=student, json={"component": "x", "damage_type": "Other"}).status_code == 403
    assert client.post("/api/ai/claims/1/suggest-assessment", headers=student).status_code == 403
    assert client.post("/api/claims/1/status", headers=student, json={"to": "Approved for Review", "reason": "me"}).status_code in (400, 403)
    # students cannot see each other's data
    assert client.get("/api/claims/3", headers=student).status_code == 404  # Meera's claim
    assert client.get("/api/policies/4", headers=student).status_code == 404
    assert client.get("/api/assets/", headers=student).status_code in (200, 404, 405, 307)
    assert {a["owner_id"] for a in client.get("/api/assets", headers=student).json()} == {1}
    assert client.get("/api/claims/1", headers=student2).status_code == 404
    # assessor restrictions
    assert client.post("/api/plans", headers=assessor, json={}).status_code == 403
    assert client.post("/api/policies", headers=assessor, json={}).status_code == 403
    assert client.post("/api/claims", headers=assessor, json={}).status_code == 403
    assert client.put("/api/catalogue/1", headers=assessor, json={}).status_code == 403
    # admin cannot decide claims
    assert client.post("/api/claims/1/items", headers=admin, json={"component": "x", "damage_type": "Other"}).status_code == 403
    assert client.post("/api/claims/1/status", headers=admin, json={"to": "Closed"}).status_code in (400, 403)
    # allowed paths
    assert client.get("/api/claims", headers=assessor).status_code == 200 and len(client.get("/api/claims", headers=assessor).json()) == 3  # 4 seeded claims minus one student Draft, which staff cannot see (security audit change)
    assert client.get("/api/catalogue", headers=admin).status_code == 200


def test_login_rejects_bad_credentials(client):
    assert client.post("/api/auth/login", json={"username": "aarav", "password": "nope"}).status_code == 401


def test_status_machine_rejects_skipping_steps(client, student, assessor):
    c = new_claim(client, student, 1, 1)
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Approved for Review", "reason": "x"}).status_code in (400, 404)  # 404: staff cannot see a student's Draft
    client.post(f"/api/claims/{c['id']}/submit", headers=student)
    assert client.post(f"/api/claims/{c['id']}/submit", headers=student).status_code == 400  # already submitted
    assert client.post(f"/api/claims/{c['id']}/status", headers=assessor, json={"to": "Closed"}).status_code == 400
