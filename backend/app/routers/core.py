from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import services as S
from ..config import settings
from ..database import get_db
from ..limits import enforce
from ..models import (Asset, AuditRecord, Claim, CoveragePlan, Exclusion, Policy, PolicyAsset, RepairCatalogueEntry, User)
from ..security import current_user, require_roles

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ meta
@router.get("/meta")
def meta(user: User = Depends(current_user)):
    return {"asset_categories": S.ASSET_CATEGORIES, "incident_types": S.INCIDENT_TYPES, "damage_types": S.DAMAGE_TYPES, "severities": S.SEVERITIES,
            "repair_actions": S.REPAIR_ACTIONS, "doc_types": S.DOC_TYPES, "confidence": S.CONFIDENCE, "policy_statuses": S.POLICY_STATUSES,
            "claim_statuses": S.CLAIM_STATUSES, "claim_transitions": {k: {t: list(r) for t, r in v.items()} for k, v in S.CLAIM_TRANSITIONS.items()}}


@router.get("/students")
def list_students(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return [S.user_dict(u) for u in db.scalars(select(User).where(User.role == "student").order_by(User.id))]


# ------------------------------------------------------------------ assets
class AssetIn(BaseModel):
    category: str
    name: str = Field(min_length=1, max_length=120)
    make_model: str = Field(default="", max_length=120)
    serial_number: str = Field(default="", max_length=80)
    purchase_date: date
    declared_value: float = Field(gt=0, le=10_000_000)
    proof_of_purchase_ref: str = Field(default="", max_length=120)
    owner_id: int | None = None

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        if v not in S.ASSET_CATEGORIES:
            raise ValueError(f"category must be one of {S.ASSET_CATEGORIES}")
        return v

    @field_validator("purchase_date")
    @classmethod
    def _pd(cls, v):
        if v > date.today():
            raise ValueError("purchase_date cannot be in the future")
        return v


def _asset_access(a: Asset | None, user: User) -> Asset:
    if not a or (user.role == "student" and a.owner_id != user.id):
        raise HTTPException(404, "Asset not found")
    return a


@router.get("/assets")
def list_assets(owner_id: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Asset).order_by(Asset.id)
    if user.role == "student":
        q = q.where(Asset.owner_id == user.id)
    elif owner_id:
        q = q.where(Asset.owner_id == owner_id)
    return [S.asset_dict(a) for a in db.scalars(q)]


@router.post("/assets", status_code=201)
def create_asset(body: AssetIn, user: User = Depends(require_roles("student", "admin")), db: Session = Depends(get_db)):
    owner = user.id if user.role == "student" else body.owner_id
    if not owner or not db.get(User, owner) or db.get(User, owner).role != "student":
        raise HTTPException(400, "owner_id must reference a student")
    enforce(db, Asset.owner_id, owner, Asset.created_at, settings.ASSETS_PER_HOUR, 60, "assets created")
    a = Asset(owner_id=owner, **body.model_dump(exclude={"owner_id"}))
    db.add(a); db.flush()
    S.audit(db, "asset", a.id, "asset_created", {"name": a.name, "category": a.category}, user)
    db.commit()
    return S.asset_dict(a)


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, body: AssetIn, user: User = Depends(require_roles("student", "admin")), db: Session = Depends(get_db)):
    a = _asset_access(db.get(Asset, asset_id), user)
    new = body.model_dump(exclude={"owner_id"})
    locked = bool(db.scalar(select(func.count()).select_from(PolicyAsset).where(PolicyAsset.asset_id == a.id))
                  or db.scalar(select(func.count()).select_from(Claim).where(Claim.asset_id == a.id)))
    if locked and user.role == "student":
        # The rules engine prices claims from these live values and policy versions snapshot only asset ids, so a student must not be able to
        # raise a declared value, backdate a purchase or swap the serial number after the asset is insured or claimed on. An administrator can (audited).
        changed = [k for k in ("category", "purchase_date", "declared_value", "serial_number") if str(new[k]) != str(getattr(a, k) if k != "declared_value" else float(a.declared_value))]
        if changed:
            raise HTTPException(409, "These details cannot be changed once the asset is insured or has a claim: " + ", ".join(changed) + ". Ask an administrator to correct them.")
    before = {k: str(getattr(a, k)) for k in new}
    for k, v in new.items():
        setattr(a, k, v)
    S.audit(db, "asset", a.id, "asset_updated", {"name": a.name, "changes": {k: {"before": before[k], "after": str(getattr(a, k))} for k in new if before[k] != str(getattr(a, k))}}, user)
    db.commit()
    return S.asset_dict(a)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: int, user: User = Depends(require_roles("student", "admin")), db: Session = Depends(get_db)):
    a = _asset_access(db.get(Asset, asset_id), user)
    if db.scalar(select(func.count()).select_from(PolicyAsset).where(PolicyAsset.asset_id == a.id)) or \
            db.scalar(select(func.count()).select_from(Claim).where(Claim.asset_id == a.id)):
        raise HTTPException(409, "Asset is referenced by a policy or claim and cannot be deleted")
    db.delete(a)
    S.audit(db, "asset", asset_id, "asset_deleted", {}, user)
    db.commit()


# ------------------------------------------------------------------ coverage plans
class ExclusionIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    title: str
    clause: str = ""
    incident_types: list[str] = []
    damage_types: list[str] = []
    severities: list[str] = []


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    covered_perils: list[str]
    overall_limit: float = Field(gt=0)
    default_per_item_limit: float | None = Field(default=None, gt=0)
    per_item_limits: dict[str, float] = {}
    cap_at_declared_value: bool = True
    deductible_type: str = "fixed"
    deductible_value: float = Field(default=0, ge=0)
    calc_order: str = "LIMIT_THEN_DEDUCTIBLE"
    depreciation: dict = {}
    waiting_period_days: int = Field(default=0, ge=0)
    required_documents: dict[str, list[str]] = {}
    duplicate_window_days: int = Field(default=0, ge=0)
    repair_replace_threshold_pct: float = Field(default=70, gt=0, le=100)
    disabled_rules: list[str] = []
    wording: str = ""
    exclusions: list[ExclusionIn] = []

    @field_validator("covered_perils")
    @classmethod
    def _p(cls, v):
        bad = [x for x in v if x not in S.INCIDENT_TYPES]
        if bad:
            raise ValueError(f"unknown incident types {bad}")
        return v

    @field_validator("deductible_type")
    @classmethod
    def _d(cls, v):
        if v not in ("fixed", "percent"):
            raise ValueError("deductible_type must be fixed or percent")
        return v

    @field_validator("calc_order")
    @classmethod
    def _o(cls, v):
        if v not in ("LIMIT_THEN_DEDUCTIBLE", "DEDUCTIBLE_THEN_LIMIT"):
            raise ValueError("calc_order must be LIMIT_THEN_DEDUCTIBLE or DEDUCTIBLE_THEN_LIMIT")
        return v


def _apply_plan(p: CoveragePlan, body: PlanIn):
    for k, v in body.model_dump(exclude={"exclusions"}).items():
        setattr(p, k, v)
    p.exclusions = [Exclusion(**e.model_dump()) for e in body.exclusions]


@router.get("/plans")
def list_plans(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [S.plan_dict(p) for p in db.scalars(select(CoveragePlan).order_by(CoveragePlan.id))]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(CoveragePlan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    return S.plan_dict(p)


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(CoveragePlan).where(CoveragePlan.name == body.name)):
        raise HTTPException(409, "A plan with this name already exists")
    p = CoveragePlan(); _apply_plan(p, body); db.add(p); db.flush()
    S.audit(db, "plan", p.id, "plan_created", {"name": p.name}, user)
    db.commit()
    return S.plan_dict(p)


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    p = db.get(CoveragePlan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    _apply_plan(p, body)
    S.audit(db, "plan", p.id, "plan_updated", {"name": p.name, "note": "Existing policies keep their snapshot until re-issued (new version)."}, user)
    db.commit()
    return S.plan_dict(p)


# ------------------------------------------------------------------ repair catalogue
class CatalogueIn(BaseModel):
    category: str
    component: str
    damage_type: str = ""
    action: str = "Repair"
    parts_cost: float = Field(ge=0)
    labour_cost: float = Field(default=0, ge=0)
    notes: str = ""
    active: bool = True


def _cat_dict(c: RepairCatalogueEntry):
    return {"id": c.id, "category": c.category, "component": c.component, "damage_type": c.damage_type, "action": c.action,
            "parts_cost": float(c.parts_cost), "labour_cost": float(c.labour_cost), "notes": c.notes, "active": c.active}


@router.get("/catalogue")
def list_catalogue(category: str | None = None, user: User = Depends(require_roles("admin", "assessor")), db: Session = Depends(get_db)):
    q = select(RepairCatalogueEntry).order_by(RepairCatalogueEntry.category, RepairCatalogueEntry.component)
    if category:
        q = q.where(RepairCatalogueEntry.category == category)
    return [_cat_dict(c) for c in db.scalars(q)]


@router.post("/catalogue", status_code=201)
def create_catalogue(body: CatalogueIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = RepairCatalogueEntry(**body.model_dump()); db.add(c); db.flush()
    S.audit(db, "catalogue", c.id, "catalogue_created", body.model_dump(), user)
    db.commit()
    return _cat_dict(c)


@router.put("/catalogue/{cid}")
def update_catalogue(cid: int, body: CatalogueIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = db.get(RepairCatalogueEntry, cid)
    if not c:
        raise HTTPException(404, "Entry not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    S.audit(db, "catalogue", c.id, "catalogue_updated", body.model_dump(), user)
    db.commit()
    return _cat_dict(c)


# ------------------------------------------------------------------ dashboard / audit
@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pq, cq, aq = select(Policy), select(Claim).where(Claim.flow == "manual"), select(Asset)
    if user.role == "assessor":
        cq = cq.where(Claim.status != "Draft")
    if user.role == "student":
        pq, cq, aq = pq.where(Policy.student_id == user.id), cq.where(Claim.claimant_id == user.id), aq.where(Asset.owner_id == user.id)
    policies, claims, assets = db.scalars(pq).all(), db.scalars(cq).all(), db.scalars(aq).all()
    for p in policies:
        S.refresh_policy_status(db, p)
    db.commit()
    by = lambda rows, f: {k: sum(1 for r in rows if f(r) == k) for k in sorted({f(r) for r in rows})}
    return {"role": user.role, "assets": len(assets), "insured_value": sum(float(a.declared_value) for a in assets),
            "policies_by_status": by(policies, lambda p: p.status), "claims_by_status": by(claims, lambda c: c.status),
            "open_claims": sum(1 for c in claims if c.status not in ("Closed", "Rejected with Reason")),
            "estimated_payable_open": sum(float(c.estimated_payable or 0) for c in claims if c.status in ("Assessment Completed", "Approved for Review")),
            "awaiting_assessor": sum(1 for c in claims if c.status in ("Submitted", "Under Assessment")),
            "pending_information": sum(1 for c in claims if c.status == "Pending Information"),
            "recent_claims": [S.claim_dict(c) for c in sorted(claims, key=lambda c: c.id, reverse=True)[:5]],
            "recent_policies": [S.policy_dict(p) for p in policies[-5:]]}


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), entity_type: str | None = Query(None, max_length=30), user: User = Depends(require_roles("admin", "assessor")),
              db: Session = Depends(get_db)):
    q = select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit)
    if user.role == "assessor":  # claim work only: no user-management or system records, and no login IP addresses
        q = q.where(AuditRecord.entity_type.not_in(("user", "system")), AuditRecord.action != "login")
    if entity_type:
        q = q.where(AuditRecord.entity_type == entity_type)
    return [{"id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "claim_id": a.claim_id, "policy_id": a.policy_id, "action": a.action,
             "detail": a.detail, "username": a.username, "created_at": a.created_at.isoformat()} for a in db.scalars(q)]
