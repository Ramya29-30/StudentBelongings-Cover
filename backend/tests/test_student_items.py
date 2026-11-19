"""Student-declared damage items: unpriced, flagged, and held at POL-013 until a human assessor verifies them."""
from tests.test_api import new_claim

BODY = {"component": "Screen", "damage_type": "Cracked screen", "severity": "Severe", "notes": "Fell off desk"}


def test_student_declares_item_unpriced_and_unverified(client, student):
    c = new_claim(client, student, 1, 1)
    r = client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY)
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["verification_status"] == "Student Declared"
    assert it["parts_cost"] is None and it["labour_cost"] is None and it["repair_action"] == "Inspect Further"


def test_student_item_blocks_pol013_until_assessor_verifies(client, student, assessor):
    c = new_claim(client, student, 1, 1)
    it = client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY).json()
    assert client.post(f"/api/claims/{c['id']}/submit", headers=student).status_code == 200
    ev = client.post(f"/api/claims/{c['id']}/evaluate", headers=assessor).json()
    p13 = [r for r in ev["rule_results"] if r["rule_id"] == "POL-013"]
    assert p13 and p13[0]["outcome"] == "PENDING"
    assert client.post(f"/api/items/{it['id']}/verify", headers=assessor).json()["verification_status"] == "Human Verified"
    ev = client.post(f"/api/claims/{c['id']}/evaluate", headers=assessor).json()
    assert [r["outcome"] for r in ev["rule_results"] if r["rule_id"] == "POL-013"] == ["PASS"]


def test_student_item_permissions_and_state(client, student, student2, assessor):
    c = new_claim(client, student, 1, 1)
    assert client.post(f"/api/claims/{c['id']}/student-items", headers=student2, json=BODY).status_code == 404  # not their claim
    assert client.post(f"/api/claims/{c['id']}/student-items", headers=assessor, json=BODY).status_code == 403  # assessors use /items
    assert client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY | {"damage_type": "Nope"}).status_code == 422
    it = client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY).json()
    assert client.delete(f"/api/claims/{c['id']}/student-items/{it['id']}", headers=student2).status_code == 404
    client.post(f"/api/claims/{c['id']}/submit", headers=student)
    assert client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY).status_code == 400  # locked after submit
    assert client.delete(f"/api/claims/{c['id']}/student-items/{it['id']}", headers=student).status_code == 400


def test_student_can_remove_own_unverified_item_while_open(client, student):
    c = new_claim(client, student, 1, 1)
    it = client.post(f"/api/claims/{c['id']}/student-items", headers=student, json=BODY).json()
    assert client.delete(f"/api/claims/{c['id']}/student-items/{it['id']}", headers=student).status_code == 204
    assert client.get(f"/api/claims/{c['id']}", headers=student).json()["items"] == []
