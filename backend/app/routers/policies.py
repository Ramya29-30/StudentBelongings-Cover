import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import services as S
from ..database import get_db
from ..engine.rules import check_eligibility
from ..models import Asset, CoveragePlan, Policy, PolicyAsset, User
from ..security import current_user, require_roles

router = APIRouter(prefix="/api/policies")


def _policy_access(db: Session, pid: int, user: User) -> Policy:
    p = db.get(Policy, pid)
    if not p or (user.role == "student" and p.student_id != user.id):
        raise HTTPException(404, "Policy not found")
    S.refresh_policy_status(db, p)
    return p


class PolicyIn(BaseModel):
    student_id: int
    plan_id: int
    start_date: date
    end_date: date
    asset_ids: list[int] = Field(default=[], max_length=100)


class PolicyUpdate(BaseModel):
    plan_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    effective_from: date | None = None
    reason: str = Field(default="Policy terms updated", max_length=300)


class TransitionIn(BaseModel):
    to: str = Field(max_length=20)
    reason: str = Field(default="", max_length=300)
    on_date: date | None = None


class AssetLink(BaseModel):
    asset_id: int


class ReissueIn(BaseModel):
    effective_from: date | None = None
    reason: str = Field(default="Re-issued with current plan terms", max_length=300)


class EligibilityIn(BaseModel):
    asset_id: int
    incident_date: date
    incident_type: str = Field(max_length=40)


def _check_dates(start: date, end: date):
    if start >= end:
        raise HTTPException(400, "Policy start date must be before the expiry date")


def _next_effective(p: Policy, requested: date | None) -> date:
    if p.status == "Draft":
        return requested or p.start_date
    eff = requested or date.today()
    if eff < date.today():
        raise HTTPException(400, "A new version of an active policy cannot be back-dated; effective_from must be today or later")
    return eff


@router.get("")
def list_policies(student_id: int | None = Query(None, ge=1), status: str | None = Query(None, max_length=20), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Policy).order_by(Policy.id)
    if user.role == "student":
        q = q.where(Policy.student_id == user.id)
    elif student_id:
        q = q.where(Policy.student_id == student_id)
    rows = db.scalars(q).all()
    for p in rows:
        S.refresh_policy_status(db, p)
    db.commit()
    return [S.policy_dict(p) for p in rows if not status or p.status == status]


@router.get("/{pid}")
def get_policy(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _policy_access(db, pid, user)
    db.commit()
    return S.policy_dict(p, detail=True)


@router.post("", status_code=201)
def create_policy(body: PolicyIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    _check_dates(body.start_date, body.end_date)
    student, plan = db.get(User, body.student_id), db.get(CoveragePlan, body.plan_id)
    if not student or student.role != "student":
        raise HTTPException(400, "student_id must reference a student")
    if not plan:
        raise HTTPException(400, "Unknown plan_id")
    p = Policy(policy_number=f"TMP-{uuid.uuid4().hex[:20]}", student_id=student.id, plan_id=plan.id, start_date=body.start_date, end_date=body.end_date)
    db.add(p); db.flush()
    p.policy_number = f"SBC-{date.today().year}-{p.id:05d}"
    for aid in dict.fromkeys(body.asset_ids):
        a = db.get(Asset, aid)
        if not a or a.owner_id != student.id:
            raise HTTPException(400, f"Asset {aid} does not belong to this student")
        db.add(PolicyAsset(policy_id=p.id, asset_id=aid))
    db.flush(); db.refresh(p)
    S.audit(db, "policy", p.id, "policy_created", {"plan": plan.name, "student": student.username}, user, policy_id=p.id)
    S.create_version(db, p, p.start_date, "Initial policy version", user)
    db.commit(); db.refresh(p)
    return S.policy_dict(p, detail=True)


@router.put("/{pid}")
def update_policy(pid: int, body: PolicyUpdate, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _policy_access(db, pid, user)
    if p.status not in ("Draft", "Active"):
        raise HTTPException(400, f"A {p.status} policy cannot be edited")
    if body.plan_id and body.plan_id != p.plan_id:
        if not db.get(CoveragePlan, body.plan_id):
            raise HTTPException(400, "Unknown plan_id")
        p.plan_id = body.plan_id
        db.flush(); db.refresh(p)
    start, end = body.start_date or p.start_date, body.end_date or p.end_date
    _check_dates(start, end)
    if p.status == "Active" and body.start_date and body.start_date != p.start_date:
        raise HTTPException(400, "The start date of an active policy cannot be changed")
    p.start_date, p.end_date = start, end
    S.create_version(db, p, _next_effective(p, body.effective_from), body.reason, user)
    db.commit(); db.refresh(p)
    return S.policy_dict(p, detail=True)


@router.post("/{pid}/transition")
def transition(pid: int, body: TransitionIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _policy_access(db, pid, user)
    S.transition_policy(db, p, body.to, user, body.reason, body.on_date)
    db.commit()
    return S.policy_dict(p, detail=True)


@router.post("/{pid}/assets", status_code=201)
def add_asset(pid: int, body: AssetLink, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _policy_access(db, pid, user)
    if p.status not in ("Draft", "Active"):
        raise HTTPException(400, f"Assets cannot be changed on a {p.status} policy")
    a = db.get(Asset, body.asset_id)
    if not a or a.owner_id != p.student_id:
        raise HTTPException(400, "Asset does not exist or does not belong to the policy holder")
    if any(pa.asset_id == a.id for pa in p.assets):
        raise HTTPException(409, "Asset is already insured under this policy")
    db.add(PolicyAsset(policy_id=p.id, asset_id=a.id)); db.flush(); db.refresh(p)
    S.create_version(db, p, _next_effective(p, None), f"Asset added: {a.name}", user)
    db.commit(); db.refresh(p)
    return S.policy_dict(p, detail=True)


@router.delete("/{pid}/assets/{aid}")
def remove_asset(pid: int, aid: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = _policy_access(db, pid, user)
    if p.status not in ("Draft", "Active"):
        raise HTTPException(400, f"Assets cannot be changed on a {p.status} policy")
    pa = next((x for x in p.assets if x.asset_id == aid), None)
    if not pa:
        raise HTTPException(404, "Asset is not on this policy")
    if p.status == "Active" and len(p.assets) == 1:
        raise HTTPException(400, "An active policy must keep at least one insured asset")
    name = pa.asset.name
    db.delete(pa); db.flush(); db.refresh(p)
    S.create_version(db, p, _next_effective(p, None), f"Asset removed: {name}", user)
    db.commit(); db.refresh(p)
    return S.policy_dict(p, detail=True)


@router.post("/{pid}/reissue")
def reissue(pid: int, body: ReissueIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    """Create a new version that picks up the CURRENT plan configuration (plan edits do not touch old versions)."""
    p = _policy_access(db, pid, user)
    if p.status not in ("Draft", "Active"):
        raise HTTPException(400, f"A {p.status} policy cannot be re-issued")
    db.refresh(p.plan)
    S.create_version(db, p, _next_effective(p, body.effective_from), body.reason, user)
    db.commit(); db.refresh(p)
    return S.policy_dict(p, detail=True)


@router.post("/{pid}/eligibility")
def eligibility(pid: int, body: EligibilityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Is this asset / incident eligible under the policy terms in force on the incident date?"""
    p = _policy_access(db, pid, user)
    ver = S.version_in_force(p, body.incident_date)
    ctx = {"policy": {"policy_number": p.policy_number, "status": p.status, "start_date": p.start_date, "end_date": p.end_date,
                      "activated_on": p.activated_on, "cancelled_on": p.cancelled_on, "version": ver.version, "terms": ver.snapshot["terms"],
                      "insured_asset_ids": ver.snapshot["insured_asset_ids"]},
           "asset_id": body.asset_id, "incident": {"date": body.incident_date, "type": body.incident_type}, "items": [], "evidence_types": []}
    res = check_eligibility(ctx)
    return {"policy_version": ver.version, "eligible": all(r["outcome"] in ("PASS", "SKIPPED") for r in res), "results": res}
