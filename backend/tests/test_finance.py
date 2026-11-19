"""Reserves and SIMULATED payments."""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Payment, User


@pytest.fixture()
def approved_claim(client, assessor):
    """Seeded claim 1 (payable 3,500) moved to 'Approved for Review' by the assessor."""
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Assessment Completed"}).status_code == 200
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Approved for Review", "reason": "verified"}).status_code == 200
    return 1


def pay(client, h, amount=3500, **kw):
    return client.post("/api/claims/1/payments", headers=h, json={"amount": amount, **kw})


def test_reserve_recommend_approve_adjust_and_history(client, assessor, admin, approved_claim):
    r = client.post("/api/claims/1/reserve/recommend", headers=assessor, json={"use_estimate": True}).json()
    assert r["recommended_reserve"] == 3500 and r["approved_reserve"] == 0
    assert client.post("/api/claims/1/reserve/approve", headers=assessor, json={}).status_code == 403  # only administrators approve
    r = client.post("/api/claims/1/reserve/approve", headers=admin, json={}).json()  # defaults to the recommendation
    assert r["approved_reserve"] == 3500
    assert client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 4000}).status_code == 400  # adjustment needs a reason
    r = client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 4000, "reason": "labour quote increased"}).json()
    assert r["approved_reserve"] == 4000 and r["remaining_reserve"] == 4000
    assert [(h["action"], h["field"], h["old"], h["new"]) for h in r["history"]] == [("Recommend", "recommended", 0, 3500), ("Approve", "approved", 0, 3500), ("Adjust", "approved", 3500, 4000)]
    assert r["history"][-1]["reason"] == "labour quote increased" and r["history"][-1]["by"] == "admin"
    actions = {a["action"] for a in client.get("/api/claims/1/audit", headers=assessor).json()}
    assert {"reserve_recommend", "reserve_approve", "reserve_adjust"} <= actions  # reserve audit trail


def test_reserve_amount_validation(client, assessor, admin, approved_claim):
    for bad in (-1, 10_000_001, 12.345):
        assert client.post("/api/claims/1/reserve/recommend", headers=assessor, json={"amount": bad}).status_code == 422
    assert client.post("/api/claims/1/reserve/recommend", headers=assessor, json={}).status_code == 422
    assert client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 0}).status_code == 400


def test_full_payment_lifecycle_simulated(client, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/recommend", headers=assessor, json={"use_estimate": True})
    assert pay(client, assessor).status_code == 400  # no approved reserve yet
    client.post("/api/claims/1/reserve/approve", headers=admin, json={})
    p = pay(client, assessor, 3500, notes="settle claim").json()
    assert p["status"] == "Requested" and p["reference"].startswith("PAY-") and p["method"] == "SIMULATED" and p["simulated"] is True
    assert p["payee_name"] == "Aarav Sharma"
    assert client.post(f"/api/payments/{p['id']}/simulate-settlement", headers=admin, json={}).status_code == 400  # must be approved first
    assert client.post(f"/api/payments/{p['id']}/approve", headers=assessor, json={}).status_code == 403
    a = client.post(f"/api/payments/{p['id']}/approve", headers=admin, json={"reason": "ok"}).json()
    assert a["status"] == "Approved" and a["decided_by"] == "admin"
    s = client.post(f"/api/payments/{p['id']}/simulate-settlement", headers=admin, json={"outcome": "paid"}).json()
    assert s["status"] == "Paid" and "SIMULATED" in s["simulation_note"] and "no real funds" in s["simulation_note"]
    assert [e["to"] for e in s["events"]] == ["Requested", "Approved", "Paid"]
    f = client.get("/api/claims/1/finance", headers=admin).json()
    assert f["paid_total_simulated"] == 3500 and f["remaining_reserve"] == 0 and "SIMULATED" in f["notice"]
    assert client.post(f"/api/payments/{p['id']}/reject", headers=admin, json={"reason": "late"}).status_code == 400  # terminal
    assert pay(client, assessor, 1).status_code == 400  # reserve exhausted
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Closed"}).status_code == 200


def test_payment_amount_validation_and_reserve_cap(client, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500})
    for bad in (0, -5, 1.234, 10_000_001, "abc"):
        assert pay(client, assessor, bad).status_code == 422, bad
    assert pay(client, assessor, 3500.01).status_code == 400  # above the approved reserve
    assert pay(client, assessor, 1000).status_code == 201
    assert pay(client, assessor, 2500.01).status_code == 400  # only 2,500 left
    assert pay(client, assessor, 2500).status_code == 201


def test_duplicate_payment_prevention(client, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500})
    first = pay(client, assessor, 1000, idempotency_key="req-1")
    assert first.status_code == 201
    replay = pay(client, assessor, 1000, idempotency_key="req-1")  # same key -> same payment, not a second one
    assert replay.json()["id"] == first.json()["id"]
    assert pay(client, assessor, 1000).status_code == 409  # identical open payment without a key
    with SessionLocal() as db:
        assert len(db.scalars(select(Payment)).all()) == 1


def test_four_eyes_rule_and_reject_cancel(client, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500})
    p = pay(client, assessor, 1000).json()
    with SessionLocal() as db:  # force requester == approver
        db.get(Payment, p["id"]).requested_by = db.scalar(select(User.id).where(User.username == "admin"))
        db.commit()
    assert client.post(f"/api/payments/{p['id']}/approve", headers=admin, json={}).status_code == 403
    p2 = pay(client, assessor, 500).json()
    assert client.post(f"/api/payments/{p2['id']}/reject", headers=admin, json={}).status_code == 400  # reason required
    r = client.post(f"/api/payments/{p2['id']}/reject", headers=admin, json={"reason": "wrong payee"}).json()
    assert r["status"] == "Rejected" and r["decision_reason"] == "wrong payee"
    p3 = pay(client, assessor, 500).json()  # rejected amounts are released from the reserve
    assert client.post(f"/api/payments/{p3['id']}/cancel", headers=admin, json={"reason": "x"}).status_code == 403
    assert client.post(f"/api/payments/{p3['id']}/cancel", headers=assessor, json={"reason": "duplicate"}).json()["status"] == "Cancelled"


def test_cannot_request_payment_before_approval_and_cannot_close_with_pending_payment(client, assessor, admin):
    assert pay(client, assessor).status_code == 400  # claim 1 is only 'Under Assessment'
    client.post("/api/claims/1/status", headers=assessor, json={"to": "Assessment Completed"})
    assert client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500}).status_code == 200
    client.post("/api/claims/1/status", headers=assessor, json={"to": "Approved for Review", "reason": "ok"})
    p = pay(client, assessor, 3500).json()
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Closed"}).status_code == 400
    client.post(f"/api/payments/{p['id']}/reject", headers=admin, json={"reason": "no"})
    assert client.post("/api/claims/1/status", headers=assessor, json={"to": "Closed"}).status_code == 200
    r = client.post("/api/claims/1/reserve/release", headers=admin, json={"reason": "claim closed unpaid"}).json()
    assert r["approved_reserve"] == 0 and r["history"][-1]["action"] == "Release"


def test_reserve_cannot_drop_below_committed_payments(client, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500})
    pay(client, assessor, 3000)
    assert client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 2000, "reason": "cut"}).status_code == 400


def test_students_see_payment_status_but_not_reserves_and_cannot_act(client, student, student2, assessor, admin, approved_claim):
    client.post("/api/claims/1/reserve/approve", headers=admin, json={"amount": 3500})
    pay(client, assessor, 3500)
    f = client.get("/api/claims/1/finance", headers=student).json()
    assert f["payments"][0]["status"] == "Requested" and "approved_reserve" not in f and "history" not in f
    assert client.get("/api/claims/1/finance", headers=student2).status_code == 404  # someone else's claim
    assert client.post("/api/claims/1/payments", headers=student, json={"amount": 1}).status_code == 403
    assert client.post("/api/payments/1/approve", headers=student, json={}).status_code == 403
