"""Business logic for the self-service InsurTech flow: categories, purchase, premiums, AI-verified claim pipeline, simulated settlement."""
from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import evidence as EV
from . import services as S
from .ai import device_match, model_registry, verification
from .catalog import COMMON, DEFAULT_CATEGORIES, FINANCE_DEFAULTS
from .config import settings
from .engine import decision as D
from .engine import insurance as I
from .models import (AIVerificationReport, Asset, AssetCategory, Claim, ClaimDecision, ClaimImage, ClaimStatusHistory, CoveragePlan, Evidence, Policy, PolicyAsset,
                     PremiumTransaction, Settlement, SystemSetting, User, now)

ACTIVE_CLAIM = ("Approved", "Settlement Processing", "Settled")
AUTO_STATUSES = ["Submitted", "AI Verification in Progress", "More Evidence Required", "AI Verification Completed", "Policy Validation in Progress", "Approved", "Rejected",
                 "Exceptional Review Required", "Settlement Processing", "Settled"]


def f(x):
    return None if x is None else float(x)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, mo = d.year + m // 12, m % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def period(d: date) -> str:
    return f"{d:%Y-%m}"


# ------------------------------------------------------------------ categories
def sync_plan(db: Session, c: AssetCategory) -> None:
    """Each category owns a CoveragePlan so legacy policy machinery (versions, audit) keeps working. Issued policies keep their own frozen terms."""
    plan = db.get(CoveragePlan, c.plan_id) if c.plan_id else None
    if plan is None:
        plan = CoveragePlan(name=f"Cover: {c.name}", overall_limit=c.max_coverage)
        db.add(plan)
    plan.description = c.description or f"{c.name} cover"
    plan.covered_perils = list(c.covered_incident_types or [])
    plan.overall_limit = c.max_coverage
    plan.default_per_item_limit = c.max_coverage
    plan.deductible_type, plan.deductible_value = "fixed", c.deductible
    plan.waiting_period_days = c.waiting_period_days
    plan.wording = (f"{c.name.upper()} COVER (sample wording, academic prototype). Monthly premium {I.inr(c.monthly_premium)}. Maximum coverage {I.inr(c.max_coverage)}. "
                    f"Exclusions: {'; '.join(c.exclusions or [])}.")
    db.flush()
    c.plan_id = plan.id


def category_dict(c: AssetCategory) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description, "min_purchase_value": f(c.min_purchase_value), "monthly_premium": f(c.monthly_premium),
            "annual_premium": f(c.monthly_premium * 12), "max_coverage": f(c.max_coverage), "deductible": f(c.deductible), "policy_months": c.policy_months,
            "waiting_period_days": c.waiting_period_days, "depreciation_pct_per_year": f(c.depreciation_pct_per_year), "depreciation_max_pct": f(c.depreciation_max_pct),
            "exclusions": c.exclusions or [], "covered_incident_types": c.covered_incident_types or [], "excluded_damage_types": c.excluded_damage_types or [],
            "damage_types": c.damage_types or [], "reference_repair_costs": c.reference_repair_costs or {}, "eligibility_conditions": c.eligibility_conditions,
            "requires_serial": c.requires_serial, "active": c.active, "updated_at": S.iso(c.updated_at)}


def seed_categories(db: Session) -> None:
    if db.scalar(select(AssetCategory.id).limit(1)):
        return
    for row in DEFAULT_CATEGORIES:
        c = AssetCategory(**COMMON, **row)
        db.add(c); db.flush(); sync_plan(db, c)
    for k, v in FINANCE_DEFAULTS.items():
        if not db.get(SystemSetting, k):
            db.add(SystemSetting(key=k, value=v))


# ------------------------------------------------------------------ views
def asset_v2(a: Asset, db: Session | None = None) -> dict:
    d = S.asset_dict(a) | {"brand": a.brand, "model_name": a.model_name, "description": a.description, "category_id": a.category_id, "purchase_price": f(a.declared_value),
                           "has_invoice": bool(a.invoice_file), "has_photo": bool(a.photo_file), "invoice_verified": a.invoice_verified,
                           "invoice_status": "Verified by staff" if a.invoice_verified else ("Uploaded, not yet verified" if a.invoice_file else "Not uploaded"),
                           "eligibility_status": a.eligibility_status, "eligibility_reason": a.eligibility_reason, "policy": None, "evidence_status": a.evidence_status,
                           "can_purchase": a.evidence_status == "Approved"}
    if db is not None:
        d["evidence"] = EV.summary(db, a)
        pol = active_policy_for(db, a.id)
        if pol:
            d["policy"] = {"id": pol.id, "policy_number": pol.policy_number, "status": pol.status, "max_coverage": f(pol.max_coverage), "monthly_premium": f(pol.monthly_premium)}
    return d


def policy_v2(p: Policy, db: Session, detail: bool = False) -> dict:
    d = S.policy_dict(p, detail=detail)
    pa = p.assets[0].asset if p.assets else None
    paid = db.scalar(select(func.coalesce(func.sum(PremiumTransaction.amount), 0)).where(PremiumTransaction.policy_id == p.id, PremiumTransaction.status == "Paid"))
    d |= {"category_id": p.category_id, "category": pa.category if pa else None, "asset_id": pa.id if pa else None, "asset_name": pa.name if pa else None,
          "purchase_value": f(p.purchase_value), "monthly_premium": f(p.monthly_premium), "annual_premium": f(p.annual_premium), "max_coverage": f(p.max_coverage),
          "deductible": f(p.deductible), "premiums_paid": f(paid), "next_premium_due": next_due(db, p), "is_v3": p.category_id is not None,
          "terms": p.terms_snapshot if p.category_id else None}
    return d


def active_policy_for(db: Session, asset_id: int) -> Policy | None:
    return db.scalar(select(Policy).join(PolicyAsset, PolicyAsset.policy_id == Policy.id).where(PolicyAsset.asset_id == asset_id, Policy.status == "Active",
                                                                                                 Policy.category_id.is_not(None)).order_by(Policy.id.desc()))


# ------------------------------------------------------------------ purchase & premiums
def next_due(db: Session, p: Policy) -> str | None:
    """Oldest unpaid cover month up to the current month (and within the term)."""
    if p.category_id is None or p.status != "Active":
        return None
    paid = set(db.scalars(select(PremiumTransaction.period_label).where(PremiumTransaction.policy_id == p.id, PremiumTransaction.status == "Paid")))
    cur = date(p.start_date.year, p.start_date.month, 1)
    last = min(date.today(), p.end_date)
    while cur <= last:
        if period(cur) not in paid:
            return period(cur)
        cur = add_months(cur, 1)
    return None


def charge_premium(db: Session, p: Policy, label: str, user: User, when=None) -> PremiumTransaction:
    t = PremiumTransaction(reference=f"PRM-{uuid.uuid4().hex[:10].upper()}", policy_id=p.id, student_id=p.student_id, amount=p.monthly_premium, period_label=label,
                           status="Paid", method="SIMULATED", paid_at=when or now())
    db.add(t); db.flush()
    S.audit(db, "premium", t.id, "premium_paid_simulated", {"policy": p.policy_number, "period": label, "amount": float(p.monthly_premium)}, user, policy_id=p.id)
    return t


def purchase_policy(db: Session, a: Asset, user: User) -> Policy:
    cat = db.get(AssetCategory, a.category_id) if a.category_id else None
    if cat is None or a.eligibility_status != "Eligible":
        raise HTTPException(409, "This asset is not eligible for self-service cover.")
    if not cat.active:
        raise HTTPException(409, f"{cat.name} cover is not currently offered.")
    chk = I.check_eligibility(I.category_terms(cat), a.declared_value)
    if not chk["eligible"]:
        raise HTTPException(422, chk["reason"])
    if active_policy_for(db, a.id):
        raise HTTPException(409, "This asset already has an active policy.")
    if a.evidence_status != "Approved":
        raise HTTPException(409, "A policy cannot be bought yet: the registration evidence must be approved by an administrator first. " + EV.summary(db, a)["reason"])
    start = date.today()
    terms = I.category_terms(cat)
    q = I.quote(terms, a.declared_value)
    n = (db.scalar(select(func.max(Policy.id))) or 0) + 1
    p = Policy(policy_number=f"SBC-{start.year}-{n:05d}", student_id=a.owner_id, plan_id=cat.plan_id, status="Active", start_date=start,
               end_date=add_months(start, cat.policy_months) - timedelta(days=1), activated_on=start, category_id=cat.id, purchase_value=a.declared_value,
               monthly_premium=cat.monthly_premium, annual_premium=q["annual_premium"], max_coverage=cat.max_coverage, deductible=cat.deductible, terms_snapshot=terms)
    db.add(p); db.flush()
    db.add(PolicyAsset(policy_id=p.id, asset_id=a.id, added_on=start)); db.flush(); db.refresh(p)
    S.create_version(db, p, start, "Policy purchased (simulated)", user)
    charge_premium(db, p, period(start), user)
    S.audit(db, "policy", p.id, "policy_purchased_simulated", {"asset_id": a.id, "category": cat.name, "monthly_premium": q["monthly_premium"], "max_coverage": q["max_coverage"]}, user, policy_id=p.id)
    return p


# ------------------------------------------------------------------ claims
def set_status(db: Session, c: Claim, to: str, reason: str, user: User | None) -> None:
    old = c.status
    c.status = to
    db.add(ClaimStatusHistory(claim_id=c.id, from_status=old, to_status=to, reason=reason[:1000], changed_by=user.id if user else None))
    S.audit(db, "claim", c.id, "claim_status_changed", {"from": old, "to": to, "reason": reason[:300]}, user, claim_id=c.id)


def new_claim_number(db: Session, c: Claim) -> None:
    c.claim_number = f"CLM-{date.today().year}-{c.id + 1000:05d}"


def assessed_loss(cat_terms: dict, claim: Claim, purchase_value: float) -> tuple[float, str | None, str]:
    """The browser-supplied estimate is never trusted: it is bounded by the asset's purchase value and compared with the category's reference cost."""
    ref = float((cat_terms.get("reference_repair_costs") or {}).get(claim.damage_type, 0) or 0)
    est = f(claim.estimated_repair_cost)
    review, basis = None, ""
    if est:
        loss = min(est, purchase_value)
        basis = "student's estimate"
        if ref and est > ref * settings.ESTIMATE_TOLERANCE:
            review = f"The estimated repair cost ({I.inr(est)}) is more than {settings.ESTIMATE_TOLERANCE:g} times the reference cost for {claim.damage_type} ({I.inr(ref)})."
        elif not ref:
            review = "There is no reference cost for this damage type to check the estimate against."
    elif ref:
        loss, basis = min(ref, purchase_value), "reference repair cost for this damage type (no estimate given)"
    else:
        loss, basis, review = 0.0, "none", "No estimate was given and there is no reference cost for this damage type."
    return loss, review, basis


def prior_images(db: Session, claim: Claim) -> list[dict]:
    """Fingerprints of every earlier claim photograph and every registration photograph, for duplicate detection."""
    rows = db.execute(select(ClaimImage.claim_id, ClaimImage.student_id, ClaimImage.sha256, ClaimImage.phash, ClaimImage.phash_dct, Claim.claim_number).join(Claim, Claim.id == ClaimImage.claim_id)
                      .where(ClaimImage.claim_id != claim.id).order_by(ClaimImage.id.desc()).limit(5000)).all()
    out = [{"source": "claim", "claim_id": r[0], "student_id": r[1], "sha256": r[2], "phash": r[3], "phash_dct": r[4], "claim_number": r[5], "label": r[5]} for r in rows]
    return out + EV.corpus(db)


def registered_photos(db: Session, asset: Asset) -> list[dict]:
    """Registration photographs (never a rejected one) as bytes for device matching. Falls back to the legacy single photo column."""
    items = EV.rows(db, asset.id)
    EV.ensure_fingerprints(db, items)
    out = []
    for e in items:
        if e.kind in EV.PHOTO_KINDS and e.review_status != "Rejected":
            p = (settings.UPLOAD_DIR / e.stored_name).resolve()
            if settings.UPLOAD_DIR.resolve() in p.parents and p.is_file():
                out.append({"kind": e.kind, "data": p.read_bytes()})
    if not out and asset.photo_file:
        p = (settings.UPLOAD_DIR / asset.photo_file).resolve()
        if settings.UPLOAD_DIR.resolve() in p.parents and p.is_file():
            out.append({"kind": "front_photo", "data": p.read_bytes()})
    return out


def auto_approval_allowed(rep: dict) -> tuple[bool, str]:
    """AI evidence is never the authority for a payout. Unless AUTO_APPROVAL=verified_only AND every condition below holds, a person confirms."""
    if settings.AUTO_APPROVAL != "verified_only":
        return False, "Automatic approval is switched off (AUTO_APPROVAL=off), so a staff member confirms every claim before any payout."
    ms = model_registry.damage_model_status()
    if rep["is_simulated"] or rep["mode"] != "onnx_model" or not ms["available"]:
        return False, "Automatic approval needs a trained damage model; this verification did not use one."
    if not ms["evaluation_matches_model"]:
        return False, "Automatic approval needs a measured evaluation of the installed damage model, and none matches it."
    if rep["workflow_outcome"] != verification.WF_CONSISTENT:
        return False, "The evidence outcome is not 'Evidence appears consistent'."
    if (rep.get("device_match") or {}).get("band") != device_match.BAND_STRONG:
        return False, "The photographs were not strongly matched to the registered device."
    if rep["risk_indicators"]:
        return False, "Evidence risk indicators were raised."
    return True, ""


def hold_for_staff(out: dict, why: str) -> dict:
    reason = f"All automatic policy checks passed, but a person must confirm before any payout. {why}"
    return {"outcome": "Exceptional Review Required", "reason": reason, "checks": out["checks"] + [{"id": "RVW-01", "name": "A person confirms before any payout", "result": "REVIEW", "reason": why}]}


def run_verification_and_decision(db: Session, c: Claim, user: User) -> None:
    """Stages 2-8 (AI evidence report) then the separate policy-rule engine, then simulated settlement. All state is persisted."""
    set_status(db, c, "AI Verification in Progress", "Automated evidence verification started", None)
    db.commit()
    policy, asset = c.policy, c.asset
    cat = db.get(AssetCategory, policy.category_id)
    terms = policy.terms_snapshot or I.category_terms(cat)
    imgs = db.scalars(select(ClaimImage).where(ClaimImage.claim_id == c.id).order_by(ClaimImage.id)).all()
    files = []
    for im in imgs:
        p = (settings.UPLOAD_DIR / im.stored_name).resolve()
        if settings.UPLOAD_DIR.resolve() in p.parents and p.is_file():
            files.append({"original_name": im.original_name, "data": p.read_bytes(), "content_type": im.content_type, "sha256": im.sha256, "phash": im.phash, "exif": im.exif})
    for f_, im in zip(files, imgs):
        f_["phash_dct"] = im.phash_dct
    registered = registered_photos(db, asset)
    docs = db.scalar(select(func.count()).select_from(Evidence).where(Evidence.claim_id == c.id)) or 0
    run = (db.scalar(select(func.count()).select_from(AIVerificationReport).where(AIVerificationReport.claim_id == c.id)) or 0) + 1
    rep = verification.verify(claim_id=c.id, category=asset.category, allowed_damage=list(terms.get("damage_types") or []), declared_damage=c.damage_type, description=c.description,
                              incident_date=c.incident_date, student_id=c.claimant_id, files=files, prior=prior_images(db, c), run=run, supporting_docs=docs,
                              registered=registered, asset_info={"brand": asset.brand, "model": asset.model_name, "serial": asset.serial_number}, purchase_date=asset.purchase_date, asset_id=asset.id)
    r = AIVerificationReport(claim_id=c.id, run=run, **rep)
    db.add(r)
    c.ai_outcome, c.ai_workflow_outcome = rep["outcome"], rep["workflow_outcome"]
    S.audit(db, "ai_report", c.id, "ai_verification_completed", {"run": run, "outcome": rep["outcome"], "workflow_outcome": rep["workflow_outcome"], "mode": rep["mode"], "route": rep["route"],
                                                                   "device_band": rep["device_match"].get("band"), "device_score": rep["device_match"].get("best_score"),
                                                                   "risk_codes": [x["code"] for x in rep["risk_indicators"]]}, user, claim_id=c.id)
    set_status(db, c, "AI Verification Completed", f"{rep['outcome']} ({rep['mode']})", None)
    db.flush()

    # ---------- policy engine (separate from the AI)
    set_status(db, c, "Policy Validation in Progress", "Policy rules are being evaluated", None)
    pv = float(policy.purchase_value or asset.declared_value)
    loss, est_review, basis = assessed_loss(terms, c, pv)
    paid_before = db.scalar(select(func.coalesce(func.sum(Claim.payable_amount), 0)).where(Claim.policy_id == policy.id, Claim.id != c.id, Claim.status.in_(ACTIVE_CLAIM)))
    calc = I.calculate_claim(terms, asset.purchase_date, c.incident_date, loss, paid_before)
    calc["basis"] = basis
    c.assessed_loss = loss
    dup = db.scalar(select(Claim.claim_number).where(Claim.asset_id == c.asset_id, Claim.incident_date == c.incident_date, Claim.id != c.id,
                                                      Claim.status.not_in(("Rejected", "Draft"))).limit(1))
    review_reasons = []
    recent = db.scalar(select(func.count()).select_from(Claim).where(Claim.claimant_id == c.claimant_id, Claim.id != c.id, Claim.status != "Draft",
                                                                      Claim.created_at > now() - timedelta(days=90))) or 0
    if recent >= 3:
        review_reasons.append(f"The student has {recent} other claims in the last 90 days (repeated submissions).")
    medium = [x for x in rep["risk_indicators"] if x["severity"] == "medium"]
    if len(medium) >= 2:
        review_reasons.append("Several evidence risk indicators were raised: " + " ".join(x["text"] for x in medium))
    month = period(c.incident_date)
    premium_ok = bool(db.scalar(select(PremiumTransaction.id).where(PremiumTransaction.policy_id == policy.id, PremiumTransaction.period_label == month, PremiumTransaction.status == "Paid")))
    ctx = {"authenticated": True, "owner_ok": policy.student_id == c.claimant_id == asset.owner_id, "asset_registered": asset.eligibility_status == "Eligible" and asset.category_id == policy.category_id and asset.evidence_status == "Approved",
           "policy_status": policy.status, "policy_start": policy.start_date, "policy_end": policy.end_date, "waiting_days": int(terms.get("waiting_period_days") or 0), "incident_date": c.incident_date,
           "today": date.today(), "incident_type": c.incident_type, "covered_incident_types": terms.get("covered_incident_types") or [], "damage_type": c.damage_type,
           "excluded_damage_types": terms.get("excluded_damage_types") or [], "excluded_incident_types": ["Intentional Damage"], "duplicate_claim": dup, "ai_outcome": rep["outcome"],
           "ai_route": rep["route"], "ai_reason": rep["explanation"], "risk_review_reasons": review_reasons, "calc": calc, "estimate_review": est_review, "premium_current": premium_ok}
    out = D.evaluate(ctx)
    held = False
    if out["outcome"] == "Approved":
        ok, why = auto_approval_allowed(rep)
        if not ok:
            out, held = hold_for_staff(out, why), True
        else:
            S.audit(db, "claim", c.id, "auto_approval_conditions_met", {"mode": settings.AUTO_APPROVAL}, user, claim_id=c.id)
    db.add(ClaimDecision(claim_id=c.id, run=run, outcome=out["outcome"], decided_by="system", checks=out["checks"], calculation=calc, payable_amount=calc["payable"], reason=out["reason"]))
    c.decision_outcome, c.decision_reason = out["outcome"], out["reason"]
    c.recommendation = out["outcome"]
    if out["outcome"] == "Approved":
        approve_and_settle(db, c, calc, "Automatically approved: all policy checks passed.", None)
    elif out["outcome"] == "Rejected":
        c.payable_amount = None
        set_status(db, c, "Rejected", out["reason"], None)
    elif out["outcome"] == "Exceptional Review Required":
        c.payable_amount = None
        set_status(db, c, "Exceptional Review Required", out["reason"], None)
    else:
        set_status(db, c, "More Evidence Required", out["reason"], None)


def approve_and_settle(db: Session, c: Claim, calc: dict, reason: str, staff: User | None) -> None:
    c.payable_amount = calc["payable"]
    c.decision_reason = reason
    set_status(db, c, "Approved", reason, staff)
    s = db.scalar(select(Settlement).where(Settlement.claim_id == c.id))
    if s:
        raise HTTPException(409, "A settlement already exists for this claim.")
    s = Settlement(claim_id=c.id, reference=f"SET-{uuid.uuid4().hex[:10].upper()}", amount=calc["payable"], status="Processing", method="SIMULATED")
    db.add(s); db.flush()
    set_status(db, c, "Settlement Processing", "Simulated settlement created. No money moves.", staff)
    s.status, s.settled_at = "Settled", now()
    set_status(db, c, "Settled", f"Simulated settlement {s.reference} completed.", staff)
    S.audit(db, "settlement", s.id, "settlement_simulated", {"amount": calc["payable"], "reference": s.reference}, staff, claim_id=c.id)


def report_dict(r: AIVerificationReport | None) -> dict | None:
    if r is None:
        return None
    return {"id": r.id, "run": r.run, "mode": r.mode, "is_simulated": r.is_simulated, "model_info": r.model_info, "quality": r.quality, "asset_identification": r.asset_identification,
            "damage_detection": r.damage_detection, "description_check": r.description_check, "duplicate_check": r.duplicate_check, "evidence_completeness": r.evidence_completeness,
            "risk_indicators": r.risk_indicators, "device_match": r.device_match or {}, "authenticity": r.authenticity or {}, "summary": (r.authenticity or {}).get("summary"),
            "workflow_outcome": r.workflow_outcome or verification.workflow_for(r.outcome, r.route), "outcome": r.outcome, "route": r.route, "explanation": r.explanation, "next_step": r.next_step,
            "processing_ms": r.processing_ms, "created_at": S.iso(r.created_at)}


def claim_v2(db: Session, c: Claim, detail: bool = False) -> dict:
    d = {"id": c.id, "claim_number": c.claim_number, "status": c.status, "asset_id": c.asset_id, "asset_name": c.asset.name, "asset_category": c.asset.category, "policy_id": c.policy_id,
         "policy_number": c.policy.policy_number, "claimant_id": c.claimant_id, "claimant_name": c.claimant.full_name, "incident_date": S.iso(c.incident_date), "incident_type": c.incident_type,
         "damage_type": c.damage_type, "description": c.description, "estimated_repair_cost": f(c.estimated_repair_cost), "assessed_loss": f(c.assessed_loss),
         "payable_amount": f(c.payable_amount), "ai_outcome": c.ai_outcome, "ai_workflow_outcome": c.ai_workflow_outcome or None, "decision_outcome": c.decision_outcome, "decision_reason": c.decision_reason, "flow": c.flow,
         "created_at": S.iso(c.created_at)}
    if detail:
        reports = db.scalars(select(AIVerificationReport).where(AIVerificationReport.claim_id == c.id).order_by(AIVerificationReport.id.desc())).all()
        dec = db.scalar(select(ClaimDecision).where(ClaimDecision.claim_id == c.id).order_by(ClaimDecision.id.desc()))
        st = db.scalar(select(Settlement).where(Settlement.claim_id == c.id))
        d["images"] = [{"id": i.id, "original_name": i.original_name, "size_bytes": i.size_bytes, "width": i.width, "height": i.height} for i in
                       db.scalars(select(ClaimImage).where(ClaimImage.claim_id == c.id).order_by(ClaimImage.id))]
        d["documents"] = [{"id": e.id, "original_name": e.original_name} for e in c.evidence]
        d["report"] = report_dict(reports[0] if reports else None)
        d["report_count"] = len(reports)
        d["awaiting_staff_confirmation"] = bool(dec and dec.outcome == "Exceptional Review Required" and any(x["id"] == "RVW-01" for x in (dec.checks or [])) and
                                                not any(x["result"] == "REVIEW" and x["id"] != "RVW-01" for x in (dec.checks or [])) and c.status == "Exceptional Review Required")
        d["decision"] = None if dec is None else {"outcome": dec.outcome, "decided_by": dec.decided_by, "checks": dec.checks, "calculation": dec.calculation,
                                                  "payable_amount": f(dec.payable_amount), "reason": dec.reason, "created_at": S.iso(dec.created_at)}
        d["settlement"] = None if st is None else {"reference": st.reference, "amount": f(st.amount), "status": st.status, "method": st.method, "simulated": True,
                                                    "settled_at": S.iso(st.settled_at)}
        d["history"] = [{"from": h.from_status, "to": h.to_status, "reason": h.reason, "at": S.iso(h.changed_at)} for h in
                        db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == c.id).order_by(ClaimStatusHistory.id))]
    return d
