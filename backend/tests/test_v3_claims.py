"""AI evidence verification + the separate policy-rule engine + exceptional review + settlement."""
from datetime import date, timedelta

import pytest

from app.routers.insure import settings  # same object the application uses (other tests reload app.config)
from app.engine import decision as D
from tests.helpers_v3 import admin_headers, backdate, file_claim, insured, make_img, register_login


@pytest.fixture()
def sim(monkeypatch):
    monkeypatch.setattr(settings, "AI_VERIFY_MODE", "dev_simulation")


@pytest.fixture()
def limited(monkeypatch):
    monkeypatch.setattr(settings, "AI_VERIFY_MODE", "auto")


def verify(client, h, cid):
    return client.post(f"/api/v2/claims/{cid}/verify", headers=h)


def settle(client, d):
    """With AUTO_APPROVAL=off (the default) a claim that passes every automatic check waits for a person. This is that person."""
    if d["status"] == "Exceptional Review Required" and d.get("awaiting_staff_confirmation"):
        r = client.post(f"/api/v2/claims/{d['id']}/review", json={"action": "approve", "reason": "Test: staff confirmed the claim."}, headers=admin_headers(client))
        assert r.status_code == 200, r.text
        return r.json()
    return d


def test_full_happy_path_in_simulation_is_labelled_and_settles_correctly(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"]).json()
    assert c["status"] == "Submitted" and c["claim_number"].startswith("CLM-")
    r = verify(client, h, c["id"])
    assert r.status_code == 200, r.text
    d = r.json()
    # every automatic check passed, but no payout without a person (AI evidence is never the authority)
    assert d["status"] == "Exceptional Review Required" and d["awaiting_staff_confirmation"] is True and d["payable_amount"] is None and d["settlement"] is None
    assert d["decision_outcome"] == "Exceptional Review Required" and any(x["id"] == "RVW-01" for x in d["decision"]["checks"])
    held_history = [x["to"] for x in d["history"]]
    d = settle(client, d)
    assert d["status"] == "Settled" and d["payable_amount"] == 6000 and d["decision_outcome"] == "Approved"  # reference cost for a broken laptop screen, below the 18,000 cap
    rep = d["report"]
    assert rep["is_simulated"] is True and rep["mode"] == "development_simulation" and rep["outcome"] == "Evidence Supported" and "DEVELOPMENT SIMULATION" in rep["explanation"]
    assert rep["asset_identification"]["confidence"] is None and rep["damage_detection"]["detections"][0]["confidence"] is None  # never a fabricated confidence
    assert rep["quality"]["usable_count"] == 1 and rep["duplicate_check"]["result"] == "No matching previous image found"
    assert d["settlement"]["simulated"] is True and d["settlement"]["status"] == "Settled" and d["settlement"]["amount"] == 6000
    ids = [x["id"] for x in d["decision"]["checks"]]
    assert ids[:10] == [f"CHK-{i:02d}" for i in range(1, 11)] and all(x["result"] == "PASS" for x in d["decision"]["checks"][:10])
    assert held_history == ["Submitted", "AI Verification in Progress", "AI Verification Completed", "Policy Validation in Progress", "Exceptional Review Required"]
    assert [x["to"] for x in d["history"]] == held_history + ["Approved", "Settlement Processing", "Settled"] and d["decision"]["decided_by"] == "staff"
    assert d["decision"]["calculation"]["lines"][-1]["label"] == "Payable amount"
    assert client.post(f"/api/v2/claims/{c['id']}/verify", headers=h).status_code == 409  # cannot be run twice


def test_estimate_is_bounded_and_never_exceeds_coverage(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    backdate(p["id"])
    c = file_claim(client, h, a["id"], estimate=8000).json()
    assert settle(client, verify(client, h, c["id"]).json())["payable_amount"] == 8000
    # an inflated estimate is NOT paid: it is routed to a human, and the engine amount is still capped by the frozen policy limit
    c2 = file_claim(client, h, a["id"], incident=date.today() - timedelta(days=2), estimate=25000).json()
    d = verify(client, h, c2["id"]).json()
    assert d["status"] == "Exceptional Review Required" and d["payable_amount"] is None
    assert any(x["id"] == "CHK-10" and x["result"] == "REVIEW" for x in d["decision"]["checks"])
    assert d["decision"]["calculation"]["payable"] <= 18000


def test_remaining_policy_limit_is_applied_across_claims(client, sim):
    h = register_login(client)
    a, p = insured(client, h, "Smartphone", 16000, "IMEI-1")
    backdate(p["id"])
    c1 = file_claim(client, h, a["id"], damage="Broken display", estimate=6500, itype="Accidental Damage",
                    desc="Phone fell out of my pocket and the display is shattered.").json()
    assert settle(client, verify(client, h, c1["id"]).json())["payable_amount"] == 6500
    c2 = file_claim(client, h, a["id"], damage="Cracked screen", incident=date.today() - timedelta(days=1), estimate=5000, images=(2,), desc="Dropped it again and the screen cracked once more.").json()
    d = settle(client, verify(client, h, c2["id"]).json())
    assert d["payable_amount"] == 3500 and d["decision"]["calculation"]["binding_limit"] == "remaining policy limit"  # 10,000 maximum minus 6,500 already paid


def test_policy_rules_reject_with_the_rule_that_caused_it(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    early = file_claim(client, h, a["id"], incident=date.today() - timedelta(days=20), desc="The screen cracked a few weeks ago after a fall.").json()
    d = verify(client, h, early["id"]).json()
    assert d["status"] == "Rejected" and "CHK-05" in d["decision_reason"] and "outside the coverage period" in d["decision_reason"] and d["payable_amount"] is None and d["settlement"] is None
    theft = file_claim(client, h, a["id"], itype="Theft", incident=date.today() - timedelta(days=0), images=(5,), desc="Somebody stole my laptop from the library desk.").json()
    d = verify(client, h, theft["id"]).json()
    assert d["status"] == "Rejected" and "CHK-06" in d["decision_reason"]


def test_cosmetic_exclusion_and_intentional_damage(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"], damage="Cosmetic damage only", desc="Small cosmetic scratch on the lid, still works perfectly.").json()
    d = verify(client, h, c["id"]).json()
    assert d["status"] == "Rejected" and "CHK-07" in d["decision_reason"]
    # a rejected claim does not block a new submission for the same date; intentional damage is excluded by the rule engine
    c2 = file_claim(client, h, a["id"], itype="Intentional Damage", images=(7,), desc="I damaged the screen on purpose to test the cover.")
    assert c2.status_code == 201
    d2 = verify(client, h, c2.json()["id"]).json()
    assert d2["status"] == "Rejected" and "CHK-06" in d2["decision_reason"] and "CHK-07" in d2["decision_reason"]


def test_duplicate_claim_submission_is_blocked(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    first = file_claim(client, h, a["id"], images=(1,))
    assert first.status_code == 201
    again = file_claim(client, h, a["id"], images=(2,))
    assert again.status_code == 409 and "Duplicate" in again.json()["detail"]


def test_unpaid_premium_for_incident_month_rejects(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    from app.database import SessionLocal
    from app.models import PremiumTransaction
    with SessionLocal() as db:
        for t in db.query(PremiumTransaction).filter_by(policy_id=p["id"]):
            db.delete(t)
        db.commit()
    c = file_claim(client, h, a["id"]).json()
    d = verify(client, h, c["id"]).json()
    assert d["status"] == "Rejected" and "CHK-04" in d["decision_reason"] and "premium" in d["decision_reason"]


def test_claims_need_an_active_policy_and_valid_input(client, sim):
    h = register_login(client)
    from tests.helpers_v3 import add_asset
    a = add_asset(client, h, "Laptop", 42000).json()  # registered, not bought
    r = client.post("/api/v2/claims", json={"asset_id": a["id"], "incident_date": str(date.today()), "incident_type": "Accidental Damage", "damage_type": "Broken screen", "description": "x" * 30}, headers=h)
    assert r.status_code == 409
    a2, p = insured(client, h, "Laptop", 42000, "SN-2")
    base = {"asset_id": a2["id"], "incident_type": "Accidental Damage", "damage_type": "Broken screen", "description": "The screen cracked when I dropped it."}
    assert client.post("/api/v2/claims", json=base | {"incident_date": str(date.today() + timedelta(days=1))}, headers=h).status_code == 422
    assert client.post("/api/v2/claims", json=base | {"incident_date": str(date.today()), "damage_type": "Exploded"}, headers=h).status_code == 422
    assert client.post("/api/v2/claims", json=base | {"incident_date": str(date.today()), "description": "short"}, headers=h).status_code == 422
    assert client.post("/api/v2/claims", json=base | {"incident_date": str(date.today()), "payable_amount": 99999, "policy_id": 1}, headers=h).status_code == 422  # no browser-supplied money or policy


def test_claim_ownership_is_enforced_everywhere(client, sim):
    h1, h2 = register_login(client, "owner"), register_login(client, "intruder")
    a, p = insured(client, h1)
    c = file_claim(client, h1, a["id"]).json()
    cid = c["id"]
    assert client.post("/api/v2/claims", json={"asset_id": a["id"], "incident_date": str(date.today()), "incident_type": "Accidental Damage", "damage_type": "Broken screen", "description": "y" * 30}, headers=h2).status_code == 404
    assert client.get(f"/api/v2/claims/{cid}", headers=h2).status_code == 404
    assert client.post(f"/api/v2/claims/{cid}/images", files={"file": ("x.png", make_img(3), "image/png")}, headers=h2).status_code == 404
    assert client.post(f"/api/v2/claims/{cid}/verify", headers=h2).status_code == 404
    assert client.get(f"/api/v2/claims/{cid}/images/{c['id']}/file", headers=h2).status_code == 404
    assert client.get("/api/v2/claims", headers=h2).json() == []
    assert client.post(f"/api/v2/claims/{cid}/review", json={"action": "approve", "reason": "let me in"}, headers=h2).status_code == 403


def test_image_upload_validation(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"], images=()).json()
    up = lambda name, data, ct="image/png": client.post(f"/api/v2/claims/{c['id']}/images", files={"file": (name, data, ct)}, headers=h)
    assert up("evil.svg", b"<svg onload=alert(1)>", "image/svg+xml").status_code == 422
    assert up("a.png", b"GIF89a" + b"\0" * 50).status_code == 422  # content does not match extension
    assert up("a.png", b"\x89PNG\r\n\x1a\n" + b"junk").status_code == 422  # signature ok but corrupted body
    assert up("../../etc/passwd.png", make_img(9)).status_code == 201  # path traversal in the name is neutralised
    from app.database import SessionLocal
    from app.models import ClaimImage
    with SessionLocal() as db:
        im = db.query(ClaimImage).first()
        assert "/" not in im.stored_name and ".." not in im.stored_name and im.original_name == "passwd.png"
    for i in range(10, 14):
        up(f"p{i}.png", make_img(i))
    assert up("extra.png", make_img(99)).status_code == 409  # at most 5 photos
    img = client.get(f"/api/v2/claims/{c['id']}").json()["images"][0]
    f = client.get(f"/api/v2/claims/{c['id']}/images/{img['id']}/file", headers=h)
    assert f.status_code == 200 and f.headers["content-type"] == "image/png" and "sandbox" in f.headers["content-security-policy"]


def test_blurry_or_dark_photos_ask_for_better_evidence_then_succeed(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"], images=()).json()
    for name, data in (("blur.png", make_img(1, blur=True)), ("dark.png", make_img(2, dark=True))):
        assert client.post(f"/api/v2/claims/{c['id']}/images", files={"file": (name, data, "image/png")}, headers=h).status_code == 201
    d = verify(client, h, c["id"]).json()
    assert d["status"] == "More Evidence Required" and d["report"]["outcome"] == "More Evidence Required" and d["report"]["quality"]["usable_count"] == 0
    issues = " ".join(i for q in d["report"]["quality"]["images"] for i in q["issues"])
    assert "blurry" in issues and "dark" in issues and d["settlement"] is None
    assert client.post(f"/api/v2/claims/{c['id']}/images", files={"file": ("good.png", make_img(5), "image/png")}, headers=h).status_code == 201
    d2 = settle(client, verify(client, h, c["id"]).json())
    assert d2["status"] == "Settled" and d2["report_count"] == 2


def test_without_a_damage_model_the_claim_goes_to_staff_review_not_rejection(client, limited):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"]).json()
    d = verify(client, h, c["id"]).json()
    rep = d["report"]
    assert rep["mode"] == "limited" and rep["is_simulated"] is False and rep["damage_detection"]["status"] == "Unable to verify"
    assert rep["outcome"] == "More Evidence Required" and rep["route"] == "exceptional_review"
    assert d["status"] == "Exceptional Review Required" and d["settlement"] is None and d["payable_amount"] is None
    assert rep["asset_identification"]["match"] in ("Unable to verify", "Inconsistent", "Consistent")  # real detector ran (or reported why not)
    assert rep["model_info"]["asset_detector"]["file"] == "yolo11n.onnx"


def test_exceptional_review_staff_can_approve_or_reject(client, limited, admin, assessor):
    h = register_login(client)
    a, p = insured(client, h)
    backdate(p["id"])
    c = file_claim(client, h, a["id"]).json()
    assert verify(client, h, c["id"]).json()["status"] == "Exceptional Review Required"
    assert client.post(f"/api/v2/claims/{c['id']}/review", json={"action": "approve", "reason": "ok ok ok"}, headers=h).status_code == 403
    assert client.post(f"/api/v2/claims/{c['id']}/review", json={"action": "approve", "reason": "x"}, headers=admin).status_code == 422
    ok = client.post(f"/api/v2/claims/{c['id']}/review", json={"action": "approve", "reason": "Photos reviewed by hand; screen damage is visible."}, headers=assessor)
    assert ok.status_code == 200 and ok.json()["status"] == "Settled" and ok.json()["payable_amount"] == 6000 and ok.json()["decision"]["decided_by"] == "staff"
    assert client.post(f"/api/v2/claims/{c['id']}/review", json={"action": "reject", "reason": "too late now"}, headers=admin).status_code == 409
    c2 = file_claim(client, h, a["id"], incident=date.today() - timedelta(days=1), images=(8,)).json()
    assert verify(client, h, c2["id"]).json()["status"] == "Exceptional Review Required"
    rj = client.post(f"/api/v2/claims/{c2['id']}/review", json={"action": "reject", "reason": "The photo does not show the insured laptop."}, headers=admin).json()
    assert rj["status"] == "Rejected" and "insured laptop" in rj["decision_reason"]


def test_hard_rule_failures_cannot_be_overridden_by_staff(client, limited, admin):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"], itype="Theft", desc="Somebody stole my laptop from the library desk.").json()
    d = verify(client, h, c["id"]).json()
    assert d["status"] == "Rejected"
    assert client.post(f"/api/v2/claims/{c['id']}/review", json={"action": "approve", "reason": "please approve it"}, headers=admin).status_code == 409


def test_reused_image_is_a_risk_indicator_routed_to_review_without_leaking_other_students(client, sim, admin):
    h1, h2 = register_login(client, "first"), register_login(client, "second")
    a1, _ = insured(client, h1, serial="S-A")
    c1 = file_claim(client, h1, a1["id"], images=(42,)).json()
    assert settle(client, verify(client, h1, c1["id"]).json())["status"] == "Settled"
    a2, _ = insured(client, h2, serial="S-B")
    c2 = file_claim(client, h2, a2["id"], images=(42,)).json()  # identical file
    d = verify(client, h2, c2["id"]).json()
    rep = d["report"]
    assert rep["outcome"] == "Evidence Inconsistent / Suspicious" and rep["duplicate_check"]["result"] == "Matching earlier image found"
    assert d["status"] == "Exceptional Review Required" and "not a finding of fraud" in rep["next_step"]
    text = str(rep)
    assert c1["claim_number"] not in text and "first" not in text and "another student" in text  # no cross-student leakage
    assert "not proof of fraud" in rep["duplicate_check"]["note"]


def test_description_naming_a_different_asset_is_flagged(client, sim):
    h = register_login(client)
    a, p = insured(client, h)
    c = file_claim(client, h, a["id"], desc="My phone screen is broken after I dropped it on the road.").json()
    d = verify(client, h, c["id"]).json()
    assert d["report"]["description_check"]["result"] == "Inconsistent" and d["status"] == "Exceptional Review Required" and d["report"]["outcome"] == "Evidence Inconsistent / Suspicious"


def test_ai_analytics_and_capabilities(client, sim, admin):
    h = register_login(client)
    a, p = insured(client, h)
    verify(client, h, file_claim(client, h, a["id"]).json()["id"])
    s = client.get("/api/v2/ai/analytics", headers=admin).json()
    assert s["reports"] >= 2 and s["images_analyzed"] >= 1 and s["simulated_reports"] >= 1 and s["model_metrics"] is None and "Not measured" in s["model_metrics_note"]
    cap = client.get("/api/v2/ai/capabilities", headers=h).json()
    assert cap["effective_mode"] == "development_simulation" and cap["asset_model"]["file"] == "yolo11n.onnx" and cap["damage_model"] is None


# ------------------------------------------------------------------ pure rule-engine tests
def ctx(**kw):
    base = dict(authenticated=True, owner_ok=True, asset_registered=True, policy_status="Active", policy_start=date(2026, 1, 1), policy_end=date(2026, 12, 31), waiting_days=0,
                incident_date=date(2026, 6, 1), today=date(2026, 7, 1), incident_type="Accidental Damage", covered_incident_types=["Accidental Damage"], damage_type="Broken screen",
                excluded_damage_types=["Cosmetic damage only"], excluded_incident_types=["Intentional Damage"], duplicate_claim=None, ai_outcome="Evidence Supported", ai_route="auto", ai_reason="",
                risk_review_reasons=[], calc={"payable": 100, "binding_limit": "assessed loss"}, estimate_review=None, premium_current=True)
    return base | kw


@pytest.mark.parametrize("change,chk,outcome", [
    ({}, None, "Approved"), ({"owner_ok": False}, "CHK-02", "Rejected"), ({"asset_registered": False}, "CHK-03", "Rejected"), ({"policy_status": "Cancelled"}, "CHK-04", "Rejected"),
    ({"premium_current": False}, "CHK-04", "Rejected"), ({"incident_date": date(2025, 12, 31)}, "CHK-05", "Rejected"), ({"incident_date": date(2027, 1, 1)}, "CHK-05", "Rejected"),
    ({"waiting_days": 200}, "CHK-05", "Rejected"), ({"incident_type": "Theft"}, "CHK-06", "Rejected"), ({"damage_type": "Cosmetic damage only"}, "CHK-07", "Rejected"),
    ({"duplicate_claim": "CLM-1"}, "CHK-08", "Rejected"), ({"ai_outcome": "More Evidence Required", "ai_route": "more_evidence"}, "CHK-09", "More Evidence Required"),
    ({"ai_outcome": "More Evidence Required", "ai_route": "exceptional_review"}, "CHK-09", "Exceptional Review Required"),
    ({"ai_outcome": "Evidence Inconsistent / Suspicious"}, "CHK-09", "Exceptional Review Required"), ({"calc": {"payable": 0, "binding_limit": "x"}}, "CHK-10", "Rejected"),
    ({"estimate_review": "too high"}, "CHK-10", "Exceptional Review Required"), ({"risk_review_reasons": ["many claims"]}, "RSK-01", "Exceptional Review Required"),
])
def test_decision_engine_rules(change, chk, outcome):
    out = D.evaluate(ctx(**change))
    assert out["outcome"] == outcome
    if chk:
        assert any(c["id"] == chk and c["result"] != "PASS" for c in out["checks"])


def test_low_confidence_alone_never_rejects_and_hard_failure_beats_ai():
    assert D.evaluate(ctx(ai_outcome="More Evidence Required", ai_route="more_evidence"))["outcome"] != "Rejected"
    assert D.evaluate(ctx(ai_outcome="Evidence Supported", incident_type="Theft"))["outcome"] == "Rejected"
