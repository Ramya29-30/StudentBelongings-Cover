"""Claim reserves and (SIMULATED) payments.

Reserve: an assessor RECOMMENDS, an administrator APPROVES (four-eyes). History is append-only.
Payment lifecycle:  Requested -> Approved -> Paid | Failed ;  Requested -> Rejected | Cancelled
  * requested by an assessor, approved/rejected by an administrator who must be a DIFFERENT user;
  * no gateway is integrated: "Paid" only means a simulated settlement was recorded - NO funds are moved;
  * payments are limited by the approved reserve and by duplicates (idempotency key + identical open request).
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import services as S
from ..config import settings
from ..database import get_db
from ..limits import enforce
from ..models import Claim, ClaimReserve, Payment, PaymentEvent, ReserveHistory, User
from ..security import current_user, require_roles
from .claims import claim_access

router = APIRouter(prefix="/api")
SIM_NOTICE = "SIMULATED payment workflow: no bank, card or payment gateway is contacted and no money is moved."
COMMITTED = ("Requested", "Approved", "Paid")
PAY_TRANSITIONS = {"Requested": {"Approved", "Rejected", "Cancelled"}, "Approved": {"Paid", "Failed"}}
MAX_AMOUNT = Decimal("10000000")


def D(x) -> Decimal:
    return Decimal(str(x or 0))


class AmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT, decimal_places=2, max_digits=12)
    reason: str = Field(default="", max_length=1000)
    use_estimate: bool = False


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2, max_digits=12)
    payee_name: str = Field(default="", max_length=120)
    idempotency_key: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$")
    notes: str = Field(default="", max_length=1000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=1000)
    outcome: str = "paid"


def _reserve(db: Session, claim: Claim, lock: bool = True) -> ClaimReserve:
    """Return the claim's reserve row. With lock=True the row is write-locked for the rest of the transaction (SQLite: database write lock,
    other databases: row lock), which serialises every money operation on one claim. Callers must run their checks AFTER this call."""
    r = db.scalar(select(ClaimReserve).where(ClaimReserve.claim_id == claim.id))
    if not r:
        r = ClaimReserve(claim_id=claim.id, recommended_amount=0, approved_amount=0)
        db.add(r); db.flush()
    if lock:
        db.execute(update(ClaimReserve).where(ClaimReserve.claim_id == claim.id).values(recommended_amount=ClaimReserve.recommended_amount))
        db.refresh(r); db.refresh(claim)
    return r


def committed(db: Session, claim_id: int) -> Decimal:
    return D(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.claim_id == claim_id, Payment.status.in_(COMMITTED))))


def _hist(db, claim, action, field, old, new, reason, user):
    db.add(ReserveHistory(claim_id=claim.id, action=action, field=field, old_amount=old, new_amount=new, reason=reason, user_id=user.id))
    S.audit(db, "reserve", claim.id, f"reserve_{action.lower()}", {"field": field, "old": float(old), "new": float(new), "reason": reason}, user, claim_id=claim.id)


def _pay_dict(p: Payment, db: Session, viewer: User | None = None) -> dict:
    staff = viewer is None or viewer.role != "student"
    uname = (lambda i: db.get(User, i).username if i else None) if staff else (lambda i: "Claims team" if i else None)
    return {"id": p.id, "claim_id": p.claim_id, "reference": p.reference, "amount": float(p.amount), "status": p.status, "payee_name": p.payee_name,
            "method": p.method, "simulated": True, "notes": p.notes, "requested_by": uname(p.requested_by), "requested_at": S.iso(p.requested_at),
            "decided_by": uname(p.decided_by), "decided_at": S.iso(p.decided_at), "decision_reason": p.decision_reason, "executed_at": S.iso(p.executed_at),
            "simulation_note": p.simulation_note, "idempotency_key": p.idempotency_key if staff else None,
            "events": [{"from": e.from_status, "to": e.to_status, "reason": e.reason, "by": uname(e.user_id), "at": S.iso(e.created_at)}
                       for e in db.scalars(select(PaymentEvent).where(PaymentEvent.payment_id == p.id).order_by(PaymentEvent.id))]}


@router.get("/claims/{cid}/finance")
def claim_finance(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    pays = db.scalars(select(Payment).where(Payment.claim_id == c.id).order_by(Payment.id)).all()
    out = {"notice": SIM_NOTICE, "claim_status": c.status, "payments": [_pay_dict(p, db, user) for p in pays],
           "paid_total_simulated": float(sum(D(p.amount) for p in pays if p.status == "Paid"))}
    if user.role != "student":
        r = _reserve(db, c, lock=False)
        out |= {"estimated_payable": None if c.estimated_payable is None else float(c.estimated_payable), "recommended_reserve": float(r.recommended_amount),
                "approved_reserve": float(r.approved_amount), "committed": float(committed(db, c.id)),
                "remaining_reserve": float(D(r.approved_amount) - committed(db, c.id)),
                "history": [{"action": h.action, "field": h.field, "old": float(h.old_amount), "new": float(h.new_amount), "reason": h.reason,
                             "by": db.get(User, h.user_id).username if h.user_id else None, "at": S.iso(h.created_at)}
                            for h in db.scalars(select(ReserveHistory).where(ReserveHistory.claim_id == c.id).order_by(ReserveHistory.id))]}
        db.commit()
    return out


@router.post("/claims/{cid}/reserve/recommend")
def recommend_reserve(cid: int, body: AmountIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    if c.status in ("Draft", "Closed", "Rejected with Reason"):
        raise HTTPException(400, f"A reserve cannot be recommended while the claim is '{c.status}'")
    amount = D(c.estimated_payable) if body.use_estimate else body.amount
    if amount is None:
        raise HTTPException(422, "Provide amount or use_estimate=true")
    if body.use_estimate and c.estimated_payable is None:
        raise HTTPException(400, "No rule evaluation exists yet, so there is no estimate to use")
    r = _reserve(db, c)
    if D(r.recommended_amount) != D(amount) and D(r.recommended_amount) > 0 and not body.reason.strip():
        raise HTTPException(400, "A reason is required when changing an existing reserve recommendation")
    old, r.recommended_amount = D(r.recommended_amount), amount
    _hist(db, c, "Recommend" if old == 0 else "Adjust", "recommended", old, amount, body.reason or ("Based on rules-engine estimate" if body.use_estimate else ""), user)
    db.commit()
    return claim_finance(cid, user, db)


@router.post("/claims/{cid}/reserve/approve")
def approve_reserve(cid: int, body: AmountIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    r = _reserve(db, c)
    if c.status not in ("Assessment Completed", "Approved for Review"):
        raise HTTPException(400, "A reserve can only be approved once the assessment is completed (or the claim is Approved for Review)")
    amount = D(r.recommended_amount) if body.amount is None else body.amount
    if amount <= 0:
        raise HTTPException(400, "Approved reserve must be greater than zero (use release to clear it)")
    old = D(r.approved_amount)
    if amount < committed(db, c.id):
        raise HTTPException(400, f"Approved reserve cannot be lower than payments already committed ({committed(db, c.id)})")
    if old > 0 and not body.reason.strip():
        raise HTTPException(400, "A reason is required to adjust an approved reserve")
    r.approved_amount = amount
    _hist(db, c, "Approve" if old == 0 else "Adjust", "approved", old, amount, body.reason, user)
    db.commit()
    return claim_finance(cid, user, db)


@router.post("/claims/{cid}/reserve/release")
def release_reserve(cid: int, body: AmountIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    r = _reserve(db, c)
    if c.status not in ("Closed", "Rejected with Reason"):
        raise HTTPException(400, "A reserve can only be released on a Closed or Rejected claim")
    if db.scalar(select(Payment.id).where(Payment.claim_id == c.id, Payment.status.in_(("Requested", "Approved")))):
        raise HTTPException(400, "Resolve open payments first")
    old = D(r.approved_amount)
    if not body.reason.strip():
        raise HTTPException(400, "A reason is required")
    r.approved_amount = D(committed(db, c.id))  # keep only what was actually paid
    _hist(db, c, "Release", "approved", old, r.approved_amount, body.reason, user)
    db.commit()
    return claim_finance(cid, user, db)


# ------------------------------------------------------------------ payments
def _event(db, p: Payment, to: str, reason: str, user: User):
    db.add(PaymentEvent(payment_id=p.id, from_status=p.status, to_status=to, reason=reason, user_id=user.id))
    S.audit(db, "payment", p.id, f"payment_{to.lower()}", {"reference": p.reference, "amount": float(p.amount), "reason": reason, "simulated": True}, user, claim_id=p.claim_id)
    p.status = to


def _get_payment(db: Session, pid: int) -> Payment:
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


@router.post("/claims/{cid}/payments", status_code=201)
def request_payment(cid: int, body: PaymentIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    from .admin import get_setting
    if get_setting(db, "payments_enabled") != "true":
        raise HTTPException(503, "Payment requests are currently disabled by an administrator")
    enforce(db, Payment.requested_by, user.id, Payment.requested_at, settings.PAYMENT_REQUESTS_PER_HOUR, 60, "payment requests")
    r = _reserve(db, c)  # lock first: everything below (replay check, status, remaining reserve, duplicate check) must see the latest committed state
    key = body.idempotency_key.strip()
    if key:
        existing = db.scalar(select(Payment).where(Payment.claim_id == c.id, Payment.idempotency_key == key))
        if existing:  # idempotent replay: never create a second payment for the same key
            if D(existing.amount) != body.amount or (body.payee_name.strip() and existing.payee_name != body.payee_name.strip()):
                raise HTTPException(409, "This idempotency key was already used for a different payment request")
            return _pay_dict(existing, db)
    if c.status != "Approved for Review":
        raise HTTPException(400, "Payments can only be requested for claims that are 'Approved for Review'")
    if D(r.approved_amount) <= 0:
        raise HTTPException(400, "No approved reserve - an administrator must approve a reserve first")
    remaining = D(r.approved_amount) - committed(db, c.id)
    if body.amount > remaining:
        raise HTTPException(400, f"Amount exceeds the remaining approved reserve ({remaining})")
    payee = body.payee_name.strip() or c.claimant.full_name
    if db.scalar(select(Payment.id).where(Payment.claim_id == c.id, Payment.status.in_(("Requested", "Approved")), Payment.amount == body.amount, Payment.payee_name == payee)):
        raise HTTPException(409, "Duplicate payment: an identical payment is already pending for this claim")
    p = Payment(claim_id=c.id, reference=f"TMP-{uuid.uuid4().hex[:20]}", amount=body.amount, payee_name=payee, idempotency_key=key or f"auto-{uuid.uuid4().hex[:24]}",
                notes=body.notes, requested_by=user.id, status="Requested")
    db.add(p); db.flush()
    p.reference = f"PAY-{date.today().year}-{p.id:06d}"  # from the primary key, so concurrent requests can never collide
    db.add(PaymentEvent(payment_id=p.id, from_status="", to_status="Requested", reason=body.notes, user_id=user.id))
    S.audit(db, "payment", p.id, "payment_requested", {"reference": p.reference, "amount": float(body.amount), "simulated": True}, user, claim_id=c.id)
    try:
        db.commit()
    except IntegrityError:  # defensive: a duplicate key that slipped past the lock is a replay, not a server error
        db.rollback()
        raise HTTPException(409, "Duplicate payment request")
    return _pay_dict(p, db, user)


def _decide(pid: int, to: str, reason: str, user: User, db: Session, need_reason: bool):
    p = _get_payment(db, pid)
    _reserve(db, db.get(Claim, p.claim_id))  # serialise with other money operations on the claim, then re-read the payment
    db.refresh(p)
    if to not in PAY_TRANSITIONS.get(p.status, set()):
        raise HTTPException(400, f"Invalid payment transition {p.status} -> {to}")
    if need_reason and not reason.strip():
        raise HTTPException(400, "A reason is required")
    return p


@router.post("/payments/{pid}/approve")
def approve_payment(pid: int, body: DecisionIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _decide(pid, "Approved", body.reason, user, db, False)
    if p.requested_by == user.id:
        raise HTTPException(403, "Four-eyes rule: the requester cannot approve their own payment")
    r = _reserve(db, db.get(Claim, p.claim_id), lock=False)
    others = committed(db, p.claim_id) - D(p.amount)  # p itself is already committed as Requested
    if others + D(p.amount) > D(r.approved_amount):
        raise HTTPException(400, "Approved reserve no longer covers this payment")
    _event(db, p, "Approved", body.reason, user)
    p.decided_by, p.decided_at, p.decision_reason = user.id, S.now() if hasattr(S, "now") else None, body.reason
    db.commit()
    return _pay_dict(p, db)


@router.post("/payments/{pid}/reject")
def reject_payment(pid: int, body: DecisionIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _decide(pid, "Rejected", body.reason, user, db, True)
    _event(db, p, "Rejected", body.reason, user)
    p.decided_by, p.decision_reason = user.id, body.reason
    p.decided_at = S.now()
    db.commit()
    return _pay_dict(p, db)


@router.post("/payments/{pid}/cancel")
def cancel_payment(pid: int, body: DecisionIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    p = _decide(pid, "Cancelled", body.reason, user, db, True)
    if p.requested_by != user.id:
        raise HTTPException(403, "Only the requester can cancel a pending payment")
    _event(db, p, "Cancelled", body.reason, user)
    db.commit()
    return _pay_dict(p, db)


@router.post("/payments/{pid}/simulate-settlement")
def simulate_settlement(pid: int, body: DecisionIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    to = "Paid" if body.outcome == "paid" else "Failed" if body.outcome == "failed" else None
    if not to:
        raise HTTPException(422, "outcome must be 'paid' or 'failed'")
    p = _decide(pid, to, body.reason, user, db, False)
    _event(db, p, to, body.reason or "simulated settlement", user)
    p.executed_at = S.now()
    p.simulation_note = "SIMULATED settlement - no real funds were moved" if to == "Paid" else "SIMULATED failure - nothing was transferred"
    db.commit()
    return _pay_dict(p, db)


@router.get("/payments")
def list_payments(status: str | None = None, user: User = Depends(require_roles("admin", "assessor")), db: Session = Depends(get_db)):
    q = select(Payment).order_by(Payment.id.desc()).limit(300)
    if status:
        q = q.where(Payment.status == status)
    rows = []
    for p in db.scalars(q):
        c = db.get(Claim, p.claim_id)
        rows.append(_pay_dict(p, db) | {"claim_number": c.claim_number})
    return {"notice": SIM_NOTICE, "payments": rows}


@router.get("/reserves")
def list_reserves(user: User = Depends(require_roles("admin", "assessor")), db: Session = Depends(get_db)):
    out = []
    for r in db.scalars(select(ClaimReserve).order_by(ClaimReserve.id.desc()).limit(500)):
        c = db.get(Claim, r.claim_id)
        out.append({"claim_id": c.id, "claim_number": c.claim_number, "claim_status": c.status, "recommended": float(r.recommended_amount),
                    "approved": float(r.approved_amount), "committed": float(committed(db, c.id))})
    return out
