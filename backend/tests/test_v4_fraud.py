"""Layered fraud checks: image authenticity, registered-device matching, damage verification outcomes, and the rule that AI never authorises a payout by itself.

The model-dependent tests use a tiny STUB detector (tests/stub_onnx.py) that always reports one fixed detection. It proves the plumbing through the real ONNX runtime;
it says nothing about how well any trained model detects damage.
"""
import io
import json
import shutil
import sys
from datetime import date, timedelta

import cv2
import numpy as np
import pytest
from PIL import Image

from app import evidence as EV
from app import v3
from app.ai import authenticity as au
from app.ai import device_match as dm
from app.ai import model_registry, verification, vision
from app.routers import insure
from tests.helpers_v3 import add_asset_with, admin_headers, approve_evidence, backdate, png, register_login, textured, warped
from tests.stub_onnx import build

MODULES = (vision, verification, model_registry, v3, insure, EV)


def patch_all(monkeypatch, name, value):
    for m in MODULES:
        monkeypatch.setattr(m.settings, name, value)


@pytest.fixture()
def stub_damage(monkeypatch, tmp_path):
    """Installs the stub damage detector (class 0, 'Cracked screen') next to the real COCO asset detector in a temporary model folder."""
    real = vision.settings.MODEL_DIR / vision.settings.ASSET_MODEL_FILE
    shutil.copy(real, tmp_path / real.name)
    build(tmp_path / "damage_model.onnx", class_idx=0, score=0.9)
    patch_all(monkeypatch, "MODEL_DIR", tmp_path)
    patch_all(monkeypatch, "AI_VERIFY_MODE", "auto")
    vision.reset_detectors()
    yield tmp_path
    vision.reset_detectors()


def upload(client, h, cid, data, name="photo.png"):
    r = client.post(f"/api/v2/claims/{cid}/images", files={"file": (name, data, "image/png")}, headers=h)
    assert r.status_code == 201, r.text


def new_claim(client, h, asset_id, images, damage="Broken screen", days_ago=0):
    r = client.post("/api/v2/claims", json={"asset_id": asset_id, "incident_date": str(date.today() - timedelta(days=days_ago)), "incident_type": "Accidental Damage", "damage_type": damage,
                                            "description": "My laptop fell off the desk and the screen cracked badly."}, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    for i, data in enumerate(images):
        upload(client, h, cid, data, f"p{i}.png")
    return cid


def insured_with(client, h, front: bytes, back: bytes | None = None, serial="SN-TEST-1"):
    a = add_asset_with(client, h, front, back or png(textured(3, "BACK")), invoice=png(textured(4, "INVOICE")), serial=serial)
    assert a.status_code == 201, a.text
    assert approve_evidence(client, a.json()["id"]).status_code == 200
    p = client.post(f"/api/v2/assets/{a.json()['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert p.status_code == 201, p.text
    return a.json(), p.json()


def run_verify(client, h, cid):
    r = client.post(f"/api/v2/claims/{cid}/verify", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ======================================================================= authenticity (unit)
def test_dct_hash_survives_resize_and_recompression_but_not_a_different_image():
    base = textured(1)
    h = au.phash_dct(base)
    resized = au.phash_dct(cv2.resize(base, (320, 240)))
    recompressed = au.phash_dct(vision.decode(png(base, "JPEG", quality=55))[1])
    other = au.phash_dct(textured(2))
    assert vision.hamming(h, resized) <= 8 and vision.hamming(h, recompressed) <= 8
    assert vision.hamming(h, other) > 8


def exif_jpeg(software=None, taken=None, gps=False, make="Canon", model="EOS 90D") -> bytes:
    im = Image.fromarray(cv2.cvtColor(textured(7), cv2.COLOR_BGR2RGB))
    ex = Image.Exif()
    ex[0x010F], ex[0x0110] = make, model
    if software:
        ex[0x0131] = software
    if taken:
        ex.get_ifd(0x8769)[0x9003] = taken
    if gps:
        ex.get_ifd(0x8825)[1] = "N"
        ex.get_ifd(0x8825)[2] = (12.0, 58.0, 1.0)
    buf = io.BytesIO(); im.save(buf, "JPEG", exif=ex)
    return buf.getvalue()


def test_exif_inspection_reads_camera_software_and_date_and_never_returns_gps_coordinates():
    d = au.inspect_exif(exif_jpeg(software="Adobe Photoshop 25", taken="2026:01:02 10:11:12", gps=True))
    assert d["present"] and d["camera"] == "Canon EOS 90D" and d["editing_software"] is True and d["captured"].startswith("2026-01-02")
    assert d["gps_present"] is True and "gps" not in json.dumps({k: v for k, v in d.items() if k != "gps_present"}).lower()
    plain = au.inspect_exif(exif_jpeg())
    assert plain["editing_software"] is False and plain["gps_present"] is False


def test_missing_exif_is_never_a_risk_indicator():
    data = png(textured(3))
    bgr = vision.decode(data)[1]
    img = au.analyze_image(data, bgr, "photo.png")
    assert img["exif"]["present"] is False
    assert au.indicators_for(img, incident=date.today(), purchase=date.today() - timedelta(days=10), today=date.today()) == []
    assert any("not evidence of fraud" in n for n in img["notes"])
    assert "not a sign of fraud" in au.LIMITATIONS["exif"].lower() or "not a sign of fraud" in au.LIMITATIONS["exif"]


def test_exif_date_indicators_use_the_incident_and_purchase_dates():
    today = date(2026, 6, 10)
    data = exif_jpeg(taken="2026:03:01 09:00:00")
    img = au.analyze_image(data, vision.decode(data)[1], "dmg.jpg")
    codes = {r["code"] for r in au.indicators_for(img, incident=date(2026, 6, 1), purchase=date(2026, 4, 1), today=today)}
    assert {"META-DATE", "META-PREPURCHASE"} <= codes
    assert au.indicators_for(img, incident=date(2026, 3, 1), purchase=date(2026, 1, 1), today=today) == []
    sw = exif_jpeg(software="GIMP 2.10")
    img2 = au.analyze_image(sw, vision.decode(sw)[1], "x.jpg")
    assert [r["severity"] for r in au.indicators_for(img2, incident=None, purchase=None, today=today) if r["code"] == "META-SOFTWARE"] == ["low"]


def test_error_level_analysis_only_applies_to_jpeg_and_is_labelled_weak():
    assert au.ela(png(textured(5)))["applicable"] is False
    j = au.ela(png(textured(5), "JPEG", quality=85))
    assert j["applicable"] is True and set(j) >= {"mean_error", "p95_over_median", "uneven", "reason"}
    assert "weak" in au.LIMITATIONS["manipulation"].lower()


def fp(data):
    bgr = vision.decode(data)[1]
    return {"original_name": "claim.png", "sha256": vision.sha256(data), "phash": vision.dhash(bgr), "phash_dct": au.phash_dct(bgr)}


def reg_entry(data, student=1, asset=10, label="the registration of Acme X1"):
    f = fp(data)
    return {"source": "registration", "asset_id": asset, "student_id": student, "sha256": f["sha256"], "phash": f["phash"], "phash_dct": f["phash_dct"], "label": label, "kind": "front_photo"}


def test_duplicate_detection_against_registration_photos_and_earlier_claims():
    reg = png(textured(1))
    exact, risks = au.find_duplicates([fp(reg)], [reg_entry(reg)], student_id=1, claim_id=99, asset_id=10)
    assert exact["result"] == "Matching earlier image found" and risks[0]["code"] == "DUP-REG-EXACT" and risks[0]["severity"] == "high" and "cannot show new damage" in risks[0]["text"]
    # another student's registration photo: high, and the text does not reveal who
    _, r2 = au.find_duplicates([fp(reg)], [reg_entry(reg, student=2, asset=11, label="the registration of Bob's phone")], student_id=1, claim_id=99, asset_id=10)
    assert r2[0]["code"] == "DUP-REG-EXACT" and "Bob" not in r2[0]["text"] and "another student" in r2[0]["text"]
    # near duplicate (recompressed copy)
    near_img = png(textured(1), "JPEG", quality=60)
    nres, r3 = au.find_duplicates([fp(near_img)], [reg_entry(reg)], student_id=1, claim_id=99, asset_id=10)
    assert nres["result"] == "Similar earlier image found" and r3[0]["code"] == "DUP-REG-NEAR" and r3[0]["severity"] == "medium"
    # an unrelated image and a row without fingerprints (legacy) produce nothing
    legacy = {"source": "registration", "asset_id": 3, "student_id": 1, "sha256": "", "phash": "", "phash_dct": "", "label": "x", "kind": "front_photo"}
    ok, r4 = au.find_duplicates([fp(png(textured(2)))], [reg_entry(reg), legacy], student_id=1, claim_id=99, asset_id=10)
    assert ok["result"] == "No matching previous image found" and r4 == []
    # a claim's own earlier upload is never compared with itself
    own = {"source": "claim", "claim_id": 99, "student_id": 1, "sha256": fp(reg)["sha256"], "phash": fp(reg)["phash"], "claim_number": "CLM-1", "label": "CLM-1"}
    assert au.find_duplicates([fp(reg)], [own], student_id=1, claim_id=99)[1] == []
    # the same file twice in one submission
    same, r5 = au.find_duplicates([fp(reg), fp(reg)], [], student_id=1, claim_id=99)
    assert [r["code"] for r in r5] == ["DUP-WITHIN"]


# ======================================================================= registered-device matching (unit)
def match(claim_bgr, ref_bgr, **kw):
    return dm.compare([(0, "claim.png", claim_bgr)], [{"kind": "front_photo", "label": "front photograph", "bgr": ref_bgr}], registered=kw.pop("registered", {}), **kw)


def test_matching_agrees_for_another_view_of_the_same_object_and_not_for_a_different_one():
    base = textured(1)
    same = match(warped(base), base)
    assert same["status"] == "Computed" and same["band"] == dm.BAND_STRONG and same["best_score"] >= 0.55 and same["pairs"][0]["inliers"] >= 12
    other = match(textured(2, None), base)
    assert other["band"] == dm.BAND_WEAK and other["best_score"] < 0.25
    closeup = match(cv2.resize(base[100:380, 150:520], (640, 480)), base)
    assert closeup["band"] == dm.BAND_STRONG  # a close-up of a printed area still shares local features


def test_matching_never_claims_the_same_physical_device():
    base = textured(1)
    for res in (match(warped(base), base), match(textured(2, None), base)):
        text = (res["conclusion"] + " " + " ".join(res["limitations"])).lower()
        assert "the same physical device" not in text.replace("cannot prove, that two photos show the same physical device", "")
        assert "not proof" in text or "does not prove" in text or "cannot prove" in text
    assert any("calibrated" in x.lower() for x in dm.LIMITATIONS)


def test_matching_reports_why_it_could_not_compare():
    base = textured(1)
    none = dm.compare([(0, "c.png", base)], [], registered={})
    assert none["status"] == "Unavailable" and none["band"] == dm.BAND_NOREG and none["best_score"] is None
    nothing = dm.compare([], [{"kind": "front_photo", "label": "front photograph", "bgr": base}], registered={})
    assert nothing["band"] == dm.BAND_NOTRUN
    flat = np.full((480, 640, 3), 128, np.uint8)
    blank = match(flat, base)
    assert blank["band"] == dm.BAND_NODETAIL and "too little visible detail" in blank["conclusion"]


def test_identifier_comparison_only_runs_on_real_readings_and_flags_conflicts():
    reg = {"serial": "SN-TEST-1", "brand": "Acme", "model": "X1 Pro"}
    s, b = dm.compare_identifiers(reg, [])
    assert s["status"] == "Not checked" and b["status"] == "Not checked" and s["method"] is None
    ok = dm.compare_identifiers(reg, [{"brand_seen": "ACME", "model_seen": "x1 pro 15", "serial_text": "sn-test-1", "legible": True}])
    assert ok[0]["status"] == "Matches" and ok[1]["status"] == "Matches"
    bad = dm.compare_identifiers(reg, [{"brand_seen": "Zeta", "model_seen": "Q9", "serial_text": "ZZ99887766", "legible": True}])
    assert bad[0]["status"] == "Differs" and bad[1]["status"] == "Differs" and "can be wrong" in bad[0]["detail"] + bad[0]["method"]
    unread = dm.compare_identifiers(reg, [{"brand_seen": "", "model_seen": "", "serial_text": "", "legible": False}])
    assert unread[0]["status"] == "Not legible" and unread[1]["status"] == "Not legible"


def test_imei_checksum_note_is_informational():
    assert dm.imei_note("490154203237518") is None
    assert "checksum" in dm.imei_note("490154203237519")
    assert dm.imei_note("SN-ABC-123") is None


def test_detector_labels_map_to_a_categorys_damage_types_by_family():
    assert verification.resolve_allowed("Cracked screen", ["Broken screen", "Damaged keyboard"]) == "Broken screen"
    assert verification.resolve_allowed("Broken hinge", ["Broken screen", "Broken hinge"]) == "Broken hinge"
    assert verification.resolve_allowed("Camera lens damage", ["Broken display", "Camera lens damage"]) == "Camera lens damage"
    assert verification.resolve_allowed("Cracked screen", ["Broken screen", "Broken display"]) is None  # two screen types: ambiguous, never guessed
    assert verification.resolve_allowed("Damaged keyboard", ["Broken screen"]) is None


# ======================================================================= pipeline with the stub damage model
def test_model_loading_reports_state_honestly(client, monkeypatch, tmp_path):
    patch_all(monkeypatch, "MODEL_DIR", tmp_path)
    vision.reset_detectors()
    try:
        st = model_registry.damage_model_status()
        assert st["available"] is False and st["sha256"] is None and "Not installed" in st["state"] and st["evaluation_present"] is False
        (tmp_path / "damage_model.onnx").write_bytes(b"this is not an onnx file")
        vision.reset_detectors()
        bad = model_registry.damage_model_status()
        assert bad["available"] is False and "could not be loaded" in bad["state"]
        build(tmp_path / "damage_model.onnx", class_idx=2)
        vision.reset_detectors()
        ok = model_registry.damage_model_status()
        assert ok["available"] is True and len(ok["sha256"]) == 64 and ok["classes"][0] == "Cracked screen" and ok["evaluation_matches_model"] is False
        assert "No evaluation has been measured" in ok["evaluation_note"]
    finally:
        vision.reset_detectors()


def test_consistent_evidence_still_waits_for_a_person_by_default(client, stub_damage):
    h = register_login(client)
    front = textured(1)
    a, p = insured_with(client, h, png(front))
    cid = new_claim(client, h, a["id"], [png(warped(front))])
    d = run_verify(client, h, cid)
    rep = d["report"]
    assert rep["mode"] == "onnx_model" and rep["is_simulated"] is False
    assert rep["damage_detection"]["detections"][0]["damage_type"] == "Broken screen"  # 'Cracked screen' mapped to the laptop's claimable type
    assert rep["device_match"]["band"] == dm.BAND_STRONG and rep["device_match"]["used_for_routing"] is True
    assert rep["workflow_outcome"] == "Evidence appears consistent" and rep["outcome"] == "Evidence Supported"
    assert rep["summary"]["registered_device_match"]["band"] == dm.BAND_STRONG and "does not establish that the claim is genuine" in rep["summary"]["note"]
    # no automatic payout: every policy check passed and a person must confirm
    assert d["status"] == "Exceptional Review Required" and d["awaiting_staff_confirmation"] is True and d["settlement"] is None and d["payable_amount"] is None
    assert d["ai_workflow_outcome"] == "Evidence appears consistent"
    ok = client.post(f"/api/v2/claims/{cid}/review", json={"action": "approve", "reason": "Compared photos by hand."}, headers=admin_headers(client))
    assert ok.status_code == 200 and ok.json()["status"] == "Settled" and ok.json()["decision"]["decided_by"] == "staff"


def test_weak_device_match_asks_for_more_evidence_then_hands_over_to_staff(client, stub_damage, monkeypatch):
    h = register_login(client)
    a, p = insured_with(client, h, png(textured(1)))
    cid = new_claim(client, h, a["id"], [png(textured(2, None))])
    d = run_verify(client, h, cid)
    assert d["report"]["device_match"]["band"] == dm.BAND_WEAK
    assert d["status"] == "More Evidence Required" and d["report"]["workflow_outcome"] == "More evidence required" and d["report"]["route"] == "more_evidence"
    assert "front and the back" in d["report"]["explanation"] and d["settlement"] is None
    # once the allowed number of runs is used up the claim is handed to staff instead of looping
    patch_all(monkeypatch, "MAX_VERIFICATION_RUNS", 2)
    upload(client, h, cid, png(textured(9, None)), "again.png")
    d2 = run_verify(client, h, cid)
    assert d2["report"]["workflow_outcome"] == "Unable to verify - manual review" and d2["status"] == "Exceptional Review Required"


def test_reusing_the_registration_photo_as_damage_evidence_is_suspicious(client, stub_damage):
    h = register_login(client)
    front = png(textured(1))
    a, p = insured_with(client, h, front)
    cid = new_claim(client, h, a["id"], [front])  # byte-identical to the registration photograph
    d = run_verify(client, h, cid)
    rep = d["report"]
    assert any(r["code"] == "DUP-REG-EXACT" and r["severity"] == "high" for r in rep["risk_indicators"])
    assert rep["workflow_outcome"] == "Suspicious evidence - manual review" and rep["outcome"] == "Evidence Inconsistent / Suspicious"
    assert d["status"] == "Exceptional Review Required" and d["awaiting_staff_confirmation"] is False and "not a finding of fraud" in rep["next_step"]


def test_a_photo_registered_by_another_student_is_flagged_without_naming_them(client, stub_damage):
    h1, h2 = register_login(client, "one"), register_login(client, "two")
    shared = png(textured(1))
    insured_with(client, h1, shared, serial="S-ONE")
    a2, _ = insured_with(client, h2, png(textured(5)), serial="S-TWO")
    cid = new_claim(client, h2, a2["id"], [shared])
    rep = run_verify(client, h2, cid)["report"]
    txt = " ".join(r["text"] for r in rep["risk_indicators"] if r["code"].startswith("DUP"))
    assert "another student" in txt and "one" not in txt.replace("another", "").split("registration")[0].lower().split("student")[-1]
    assert rep["workflow_outcome"] == "Suspicious evidence - manual review"


@pytest.mark.parametrize("reading,expected_band_flag", [({"brand_seen": "Acme", "model_seen": "X1", "serial_text": "SN-TEST-1", "legible": True}, None),
                                                        ({"brand_seen": "Acme", "model_seen": "X1", "serial_text": "OTHER-999999", "legible": True}, "ID-SERIAL-DIFF")])
def test_visible_serial_text_is_compared_with_the_registered_serial(client, stub_damage, monkeypatch, reading, expected_band_flag):
    monkeypatch.setattr(verification, "_read_identifiers", lambda raw: [reading])
    h = register_login(client)
    front = textured(1)
    a, _ = insured_with(client, h, png(front))
    cid = new_claim(client, h, a["id"], [png(warped(front))])
    rep = run_verify(client, h, cid)["report"]
    codes = {r["code"] for r in rep["risk_indicators"]}
    if expected_band_flag:
        assert expected_band_flag in codes and rep["workflow_outcome"] == "Suspicious evidence - manual review"
        assert rep["device_match"]["serial_check"]["status"] == "Differs"
    else:
        assert not codes and rep["device_match"]["serial_check"]["status"] == "Matches" and rep["workflow_outcome"] == "Evidence appears consistent"


def write_evaluation(folder, det_sha):
    """A TEST FIXTURE that only lets the gating logic see 'an evaluation exists for this model'; the content is not a performance claim."""
    (folder / "evaluation.json").write_text(json.dumps({"model": "damage_model.onnx", "model_sha256": det_sha, "split": "test-fixture", "per_class": {}, "overall": {}}))


def test_automatic_approval_is_off_by_default_and_needs_every_condition_when_enabled(client, stub_damage, monkeypatch):
    patch_all(monkeypatch, "AUTO_APPROVAL", "verified_only")
    h = register_login(client)
    front = textured(1)
    a, p = insured_with(client, h, png(front))
    backdate(p["id"])  # past the waiting period, as in the other claim tests
    # (1) enabled, but the installed model has never been evaluated: a person still confirms
    cid = new_claim(client, h, a["id"], [png(warped(front))])
    d = run_verify(client, h, cid)
    assert d["status"] == "Exceptional Review Required" and d["awaiting_staff_confirmation"] is True
    reason = next(x["reason"] for x in d["decision"]["checks"] if x["id"] == "RVW-01")
    assert "measured evaluation" in reason
    # (2) enabled and an evaluation exists for exactly this model file: the rule engine may approve without a person
    write_evaluation(stub_damage, vision.get_detector("damage").sha)
    cid2 = new_claim(client, h, a["id"], [png(warped(front, angle=-8, scale=0.9))], days_ago=2)
    d2 = run_verify(client, h, cid2)
    assert d2["status"] == "Settled" and d2["decision"]["decided_by"] != "staff" and d2["report"]["risk_indicators"] == []
    # (3) an evaluation that belongs to a different model file does not count
    write_evaluation(stub_damage, "0" * 64)
    cid3 = new_claim(client, h, a["id"], [png(warped(front, angle=15, scale=0.8))], days_ago=4)
    assert run_verify(client, h, cid3)["awaiting_staff_confirmation"] is True


def test_development_simulation_can_never_auto_approve(client, monkeypatch):
    patch_all(monkeypatch, "AI_VERIFY_MODE", "dev_simulation")
    patch_all(monkeypatch, "AUTO_APPROVAL", "verified_only")
    h = register_login(client)
    a, _ = insured_with(client, h, png(textured(1)))
    cid = new_claim(client, h, a["id"], [png(textured(2))])
    d = run_verify(client, h, cid)
    assert d["report"]["is_simulated"] is True and d["status"] == "Exceptional Review Required" and d["settlement"] is None
    assert "not used for routing" in d["report"]["device_match"]["conclusion"].lower()


def test_admin_analytics_distinguish_measured_from_unavailable(client, stub_damage):
    adm = admin_headers(client)
    a0 = client.get("/api/v2/ai/analytics", headers=adm).json()
    assert a0["damage_model"]["available"] is True and a0["evaluation"] is None and a0["damage_model"]["evaluation_present"] is False
    assert a0["device_matching"]["calibrated"] is False and a0["device_matching"]["average_best_score"] is None
    h = register_login(client)
    front = textured(1)
    a, _ = insured_with(client, h, png(front))
    cid = new_claim(client, h, a["id"], [png(warped(front))])
    run_verify(client, h, cid)
    an = client.get("/api/v2/ai/analytics", headers=adm).json()
    assert an["damage_model"]["sha256"] == vision.get_detector("damage").sha and an["workflow_outcomes"]["Evidence appears consistent"] == 1
    assert an["device_matching"]["bands"][dm.BAND_STRONG] == 1 and an["device_matching"]["scores_measured"] == 1
    assert an["manual_review"]["waiting_for_staff"] == 1 and an["manual_review"]["auto_approval_setting"] == "off"
    assert an["evidence_review"]["Approved"] >= 1 and set(an["evidence_review"]) == set(EV.STATUSES)
    # an evaluation file for a different model is shown as such, never as this model's performance
    (stub_damage / "evaluation.json").write_text(json.dumps({"model_sha256": "f" * 16, "split": "val", "overall": {"precision": 0.9, "recall": 0.9, "map50": 0.9},
                                                             "per_class": {"Cracked screen": {"precision": 0.9, "recall": 0.9, "tp": 9, "fp": 1, "fn": 1}}}))
    an2 = client.get("/api/v2/ai/analytics", headers=adm).json()
    assert an2["damage_model"]["evaluation_matches_model"] is False and "different model" in an2["damage_model"]["evaluation_note"]
    ev = an2["evaluation"]
    assert ev["per_class"]["Cracked screen"]["f1"] == 0.9 and "mAP@0.5:0.95" in ev["unavailable_metrics"] and "confusion matrix" in ev["unavailable_metrics"]
