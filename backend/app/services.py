"""Business services shared by the routers (policy lifecycle, versioning, claim evaluation, audit)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .engine.rules import evaluate_claim
from .models import (Asset, AuditRecord, CalculationLine, Claim, ClaimItem, ClaimStatusHistory, CoveragePlan, Policy, PolicyAsset,
                     PolicyVersion, RuleEvaluationResult, User, now)

ASSET_CATEGORIES = ["Laptop", "Smartphone", "Tablet", "Headphones and accessories", "Bicycle", "Academic equipment"]
INCIDENT_TYPES = ["Theft", "Accidental Damage", "Liquid Damage", "Fire", "Loss", "Intentional Damage"]
DAMAGE_TYPES = ["Scratch", "Dent", "Cracked screen", "Broken component", "Liquid damage", "Wear and tear", "Other"]
SEVERITIES = ["Minor", "Moderate", "Severe"]
REPAIR_ACTIONS = ["Repair", "Replace", "Inspect Further"]
DOC_TYPES = ["damage_photo", "police_report", "proof_of_purchase", "repair_quote", "incident_report", "other"]
CONFIDENCE = ["Unknown", "Low", "Medium", "High"]
VERIFICATION = ["AI Suggested", "Student Declared", "Human Corrected", "Human Verified"]
POLICY_STATUSES = ["Draft", "Active", "Expired", "Cancelled"]
CLAIM_STATUSES = ["Draft", "Submitted", "Under Assessment", "Pending Information", "Assessment Completed", "Approved for Review",
                  "Rejected with Reason", "Closed"]

CLAIM_TRANSITIONS = {
    "Draft": {"Submitted": ("student",)},
    "Submitted": {"Under Assessment": ("assessor",)},
    "Under Assessment": {"Pending Information": ("assessor",), "Assessment Completed": ("assessor",)},
    "Pending Information": {"Submitted": ("student",), "Under Assessment": ("assessor",)},
    "Assessment Completed": {"Approved for Review": ("assessor",), "Rejected with Reason": ("assessor",), "Under Assessment": ("assessor",)},
    "Approved for Review": {"Closed": ("assessor",)},
    "Rejected with Reason": {"Closed": ("assessor",)},
}
POLICY_TRANSITIONS = {"Draft": {"Active", "Cancelled"}, "Active": {"Cancelled", "Expired"}, "Expired": set(), "Cancelled": set()}


def audit(db: Session, entity_type: str, entity_id: int, action: str, detail: dict | None = None, user: User | None = None,
          claim_id: int | None = None, policy_id: int | None = None):
    db.add(AuditRecord(entity_type=entity_type, entity_id=entity_id, claim_id=claim_id, policy_id=policy_id, action=action,
                       detail=detail or {}, user_id=user.id if user else None, username=user.username if user else "system"))


# ------------------------------------------------------------------ policy terms & versions
def plan_terms(plan: CoveragePlan) -> dict:
    return {
        "plan_name": plan.name, "covered_perils": list(plan.covered_perils or []),
        "overall_limit": float(plan.overall_limit),
        "default_per_item_limit": None if plan.default_per_item_limit is None else float(plan.default_per_item_limit),
        "per_item_limits": {k: float(v) for k, v in (plan.per_item_limits or {}).items()},
        "cap_at_declared_value": bool(plan.cap_at_declared_value),
        "deductible_type": plan.deductible_type, "deductible_value": float(plan.deductible_value), "calc_order": plan.calc_order,
        "depreciation": dict(plan.depreciation or {}), "waiting_period_days": plan.waiting_period_days,
        "required_documents": dict(plan.required_documents or {}), "duplicate_window_days": plan.duplicate_window_days,
        "repair_replace_threshold_pct": float(plan.repair_replace_threshold_pct), "disabled_rules": list(plan.disabled_rules or []),
        "exclusions": [{"code": e.code, "title": e.title, "clause": e.clause, "incident_types": e.incident_types or [],
                        "damage_types": e.damage_types or [], "severities": e.severities or []} for e in plan.exclusions],
    }


def create_version(db: Session, policy: Policy, effective_from: date, reason: str, user: User | None) -> PolicyVersion:
    db.flush()
    n = (db.scalar(select(func.max(PolicyVersion.version)).where(PolicyVersion.policy_id == policy.id)) or 0) + 1
    ids = sorted(pa.asset_id for pa in db.scalars(select(PolicyAsset).where(PolicyAsset.policy_id == policy.id)))
    v = PolicyVersion(policy_id=policy.id, version=n, effective_from=effective_from, reason=reason, created_by=user.id if user else None,
                      snapshot={"plan_id": policy.plan_id, "terms": plan_terms(policy.plan), "insured_asset_ids": ids,
                                "start_date": str(policy.start_date), "end_date": str(policy.end_date)})
    db.add(v)
    audit(db, "policy", policy.id, "policy_version_created", {"version": n, "effective_from": str(effective_from), "reason": reason, "assets": ids}, user, policy_id=policy.id)
    return v


def version_in_force(policy: Policy, on: date) -> PolicyVersion:
    cands = [v for v in policy.versions if v.effective_from <= on]
    return max(cands, key=lambda v: v.version) if cands else policy.versions[0]


def refresh_policy_status(db: Session, policy: Policy):
    if policy.status == "Active" and policy.end_date < date.today():
        policy.status = "Expired"
        audit(db, "policy", policy.id, "policy_auto_expired", {"end_date": str(policy.end_date)}, None, policy_id=policy.id)


def transition_policy(db: Session, policy: Policy, to: str, user: User, reason: str = "", on_date: date | None = None):
    if to not in POLICY_STATUSES:
        raise HTTPException(400, f"Unknown status '{to}'")
    if to not in POLICY_TRANSITIONS[policy.status]:
        raise HTTPException(400, f"Invalid transition {policy.status} -> {to}. Allowed: {sorted(POLICY_TRANSITIONS[policy.status]) or 'none (terminal)'}")
    if to == "Active":
        if policy.start_date >= policy.end_date:
            raise HTTPException(400, "Policy start date must be before the expiry date")
        if not policy.assets:
            raise HTTPException(400, "A policy needs at least one insured asset before activation")
        if policy.end_date < date.today():
            raise HTTPException(400, "Cannot activate a policy whose expiry date is in the past")
        policy.activated_on = date.today()
    elif to == "Cancelled":
        on_date = on_date or date.today()
        if on_date < policy.start_date or on_date > policy.end_date:
            raise HTTPException(400, "Cancellation date must lie within the policy period")
        if not reason:
            raise HTTPException(400, "A cancellation reason is required")
        policy.cancelled_on, policy.cancellation_reason = on_date, reason
    elif to == "Expired" and policy.end_date >= date.today():
        raise HTTPException(400, "A policy can only be set to Expired after its expiry date")
    old, policy.status = policy.status, to
    audit(db, "policy", policy.id, "policy_status_changed", {"from": old, "to": to, "reason": reason}, user, policy_id=policy.id)


# ------------------------------------------------------------------ claim context and evaluation
def _asset_dict(a: Asset | None):
    if a is None:
        return None
    return {"id": a.id, "owner_id": a.owner_id, "category": a.category, "name": a.name, "purchase_date": a.purchase_date,
            "declared_value": float(a.declared_value), "proof_of_purchase_ref": a.proof_of_purchase_ref}


def item_dict(i: ClaimItem) -> dict:
    return {"id": i.id, "component": i.component, "damage_type": i.damage_type, "severity": i.severity, "repair_action": i.repair_action,
            "parts_cost": None if i.parts_cost is None else float(i.parts_cost), "labour_cost": None if i.labour_cost is None else float(i.labour_cost),
            "price_source": i.price_source, "catalogue_entry_id": i.catalogue_entry_id, "evidence_refs": i.evidence_refs or [],
            "confidence": i.confidence, "verification_status": i.verification_status, "notes": i.notes, "decision_reason": i.decision_reason,
            "ai_suggestion_id": i.ai_suggestion_id, "verified_by": i.verified_by, "updated_at": i.updated_at.isoformat() if i.updated_at else None}


def _paid(db: Session, claims_q) -> float:
    total = 0.0
    for c in db.scalars(claims_q):
        approved = c.status == "Approved for Review" or (c.status == "Closed" and db.scalar(
            select(ClaimStatusHistory.id).where(ClaimStatusHistory.claim_id == c.id, ClaimStatusHistory.to_status == "Approved for Review")))
        if approved and c.estimated_payable:
            total += float(c.estimated_payable)
    return total


def build_context(db: Session, claim: Claim) -> tuple[dict, PolicyVersion]:
    pol = claim.policy
    ver = version_in_force(pol, claim.incident_date)
    asset = db.get(Asset, claim.asset_id)
    others = db.scalars(select(Claim).where(Claim.policy_id == pol.id, Claim.id != claim.id)).all()
    same_period = select(Claim).where(Claim.policy_id == pol.id, Claim.id != claim.id)
    ctx = {
        "policy": {"policy_number": pol.policy_number, "status": pol.status, "start_date": pol.start_date, "end_date": pol.end_date,
                   "activated_on": pol.activated_on, "cancelled_on": pol.cancelled_on, "version": ver.version,
                   "terms": ver.snapshot["terms"], "insured_asset_ids": ver.snapshot["insured_asset_ids"]},
        "asset": _asset_dict(asset), "asset_id": claim.asset_id, "claimant_id": claim.claimant_id,
        "incident": {"date": claim.incident_date, "type": claim.incident_type, "location": claim.incident_location},
        "items": [item_dict(i) for i in claim.items], "evidence_types": sorted({e.doc_type for e in claim.evidence}),
        "other_claims": [{"id": o.id, "claim_number": o.claim_number, "asset_id": o.asset_id, "incident_date": o.incident_date, "status": o.status} for o in others],
        "prior_paid_policy": _paid(db, same_period),
        "prior_paid_asset": _paid(db, same_period.where(Claim.asset_id == claim.asset_id)),
    }
    return ctx, ver


def evaluate_and_store(db: Session, claim: Claim, user: User | None) -> dict:
    ctx, ver = build_context(db, claim)
    out = evaluate_claim(ctx)
    run = (claim.last_run or 0) + 1
    for r in out["rule_results"]:
        db.add(RuleEvaluationResult(claim_id=claim.id, run=run, seq=r["seq"], rule_id=r["rule_id"], rule_name=r["rule_name"], outcome=r["outcome"],
                                    inputs=r["inputs"], reason=r["reason"], clause=r["clause"], follow_up=r["follow_up"], item_id=r["item_id"]))
    for ln in out["calculation"]["lines"]:
        db.add(CalculationLine(claim_id=claim.id, run=run, seq=ln["seq"], kind=ln["kind"], label=ln["label"], amount=ln["amount"],
                               running_total=ln["running_total"], rule_ref=ln["rule_ref"], note=ln["note"], item_id=ln["item_id"]))
    claim.last_run, claim.policy_version_used = run, ver.version
    claim.recommendation, claim.recommendation_reasons = out["recommendation"], out["recommendation_reasons"]
    claim.estimated_payable = out["calculation"]["estimated_payable"]
    audit(db, "claim", claim.id, "rules_evaluated", {"run": run, "policy_version": ver.version, "recommendation": out["recommendation"],
                                                      "estimated_payable": out["calculation"]["estimated_payable"]}, user, claim_id=claim.id)
    db.flush()
    return out


def latest_evaluation(db: Session, claim: Claim) -> dict | None:
    if not claim.last_run:
        return None
    rr = db.scalars(select(RuleEvaluationResult).where(RuleEvaluationResult.claim_id == claim.id, RuleEvaluationResult.run == claim.last_run)
                    .order_by(RuleEvaluationResult.seq)).all()
    cl = db.scalars(select(CalculationLine).where(CalculationLine.claim_id == claim.id, CalculationLine.run == claim.last_run)
                    .order_by(CalculationLine.seq)).all()
    return {"run": claim.last_run, "policy_version": claim.policy_version_used, "recommendation": claim.recommendation,
            "recommendation_reasons": claim.recommendation_reasons,
            "rule_results": [{"rule_id": r.rule_id, "rule_name": r.rule_name, "outcome": r.outcome, "inputs": r.inputs, "reason": r.reason,
                              "clause": r.clause, "follow_up": r.follow_up, "item_id": r.item_id} for r in rr],
            "calculation_lines": [{"seq": c.seq, "kind": c.kind, "label": c.label, "amount": float(c.amount),
                                   "running_total": None if c.running_total is None else float(c.running_total),
                                   "rule_ref": c.rule_ref, "note": c.note, "item_id": c.item_id} for c in cl],
            "estimated_payable": None if claim.estimated_payable is None else float(claim.estimated_payable)}


def change_claim_status(db: Session, claim: Claim, to: str, user: User, reason: str = ""):
    allowed = CLAIM_TRANSITIONS.get(claim.status, {})
    if to not in allowed:
        raise HTTPException(400, f"Invalid transition {claim.status} -> {to}. Allowed: {sorted(allowed) or 'none'}")
    role = "assessor" if user.role in ("assessor",) else user.role
    if role not in allowed[to]:
        raise HTTPException(403, f"Role '{user.role}' may not move a claim {claim.status} -> {to}")
    if user.role == "student" and claim.claimant_id != user.id:
        raise HTTPException(403, "Not your claim")
    if user.role == "assessor" and claim.assessor_id not in (None, user.id):
        raise HTTPException(403, "This claim is assigned to another assessor")
    if to == "Closed":
        from .models import Payment
        if db.scalar(select(Payment.id).where(Payment.claim_id == claim.id, Payment.status.in_(("Requested", "Approved")))):
            raise HTTPException(400, "Cannot close the claim while payments are pending - approve, reject or cancel them first")
    if to in ("Rejected with Reason", "Approved for Review", "Pending Information") and not reason.strip():
        raise HTTPException(400, f"A reason is required to move a claim to '{to}'")
    if to == "Submitted":
        evaluate_and_store(db, claim, user)
        claim.submitted_at = claim.submitted_at or now()
    if to == "Assessment Completed":
        out = evaluate_and_store(db, claim, user)
        pend = [r for r in out["rule_results"] if r["outcome"] == "PENDING"]
        if pend:
            raise HTTPException(400, "Cannot complete the assessment while items are pending: " + "; ".join(r["reason"] for r in pend)
                                + ". Move the claim to 'Pending Information' or finish the assessment.")
    if to == "Under Assessment" and user.role == "assessor":
        claim.assessor_id = user.id
    old = claim.status
    claim.status = to
    if to in ("Approved for Review", "Rejected with Reason"):
        claim.decision_reason = reason
    db.add(ClaimStatusHistory(claim_id=claim.id, from_status=old, to_status=to, reason=reason, changed_by=user.id))
    audit(db, "claim", claim.id, "claim_status_changed", {"from": old, "to": to, "reason": reason}, user, claim_id=claim.id)


# ------------------------------------------------------------------ serializers
def iso(d):
    return d.isoformat() if d else None


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "email": u.email}


def asset_dict(a: Asset) -> dict:
    return {"id": a.id, "owner_id": a.owner_id, "owner_name": a.owner.full_name if a.owner else None, "category": a.category, "name": a.name,
            "make_model": a.make_model, "serial_number": a.serial_number, "purchase_date": iso(a.purchase_date), "declared_value": float(a.declared_value),
            "proof_of_purchase_ref": a.proof_of_purchase_ref}


def plan_dict(p: CoveragePlan) -> dict:
    d = plan_terms(p)
    d.update({"id": p.id, "name": p.name, "description": p.description, "wording": p.wording})
    return d


def policy_dict(p: Policy, detail: bool = False) -> dict:
    d = {"id": p.id, "policy_number": p.policy_number, "student_id": p.student_id, "student_name": p.student.full_name, "plan_id": p.plan_id,
         "plan_name": p.plan.name, "status": p.status, "start_date": iso(p.start_date), "end_date": iso(p.end_date),
         "activated_on": iso(p.activated_on), "cancelled_on": iso(p.cancelled_on), "cancellation_reason": p.cancellation_reason,
         "asset_count": len(p.assets), "current_version": max((v.version for v in p.versions), default=0)}
    if detail:
        d["assets"] = [asset_dict(pa.asset) | {"added_on": iso(pa.added_on)} for pa in p.assets]
        d["versions"] = [{"version": v.version, "effective_from": iso(v.effective_from), "reason": v.reason, "created_at": iso(v.created_at),
                          "plan_name": v.snapshot["terms"]["plan_name"], "insured_asset_ids": v.snapshot["insured_asset_ids"],
                          "terms": v.snapshot["terms"]} for v in p.versions]
        d["wording"] = p.plan.wording
    return d


def claim_dict(c: Claim, detail: bool = False) -> dict:
    d = {"id": c.id, "claim_number": c.claim_number, "policy_id": c.policy_id, "policy_number": c.policy.policy_number, "claimant_id": c.claimant_id,
         "claimant_name": c.claimant.full_name, "asset_id": c.asset_id, "asset_name": c.asset.name, "asset_category": c.asset.category,
         "incident_date": iso(c.incident_date), "incident_type": c.incident_type, "incident_location": c.incident_location,
         "description": c.description, "status": c.status, "policy_version_used": c.policy_version_used, "recommendation": c.recommendation,
         "recommendation_reasons": c.recommendation_reasons or [], "estimated_payable": None if c.estimated_payable is None else float(c.estimated_payable),
         "assessor_notes": c.assessor_notes, "decision_reason": c.decision_reason, "created_at": iso(c.created_at), "submitted_at": iso(c.submitted_at),
         "assessor_id": c.assessor_id}
    if detail:
        d["items"] = [item_dict(i) for i in c.items]
        d["evidence"] = [{"id": e.id, "doc_type": e.doc_type, "original_name": e.original_name, "content_type": e.content_type,
                          "size_bytes": e.size_bytes, "uploaded_at": iso(e.uploaded_at)} for e in c.evidence]
    return d
