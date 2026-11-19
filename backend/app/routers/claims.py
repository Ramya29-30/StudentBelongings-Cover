import hashlib
import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import services as S
from ..config import settings
from ..database import get_db
from ..engine.rules import suggest_repair_action
from ..limits import enforce
from ..models import (AISuggestion, Asset, AuditRecord, Claim, ClaimItem, ClaimStatusHistory, Evidence, Policy, RepairCatalogueEntry, User)
from ..security import current_user, require_roles

router = APIRouter(prefix="/api")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".txt", ".csv"}
ASSESS_STATES = ("Submitted", "Under Assessment", "Pending Information", "Assessment Completed")


def claim_access(db: Session, cid: int, user: User, write: bool = False) -> Claim:
    """Object-level authorisation for every claim endpoint.
    * student: only own claims (anything else is a 404, so existence is not revealed)
    * assessor: submitted claims only (a student's Draft is private); READ any such claim (the queue and 'All claims' view are a product feature);
      WRITE only when the claim is unassigned or assigned to this assessor
    * admin: everything"""
    c = db.get(Claim, cid)
    if not c or (user.role == "student" and c.claimant_id != user.id) or (user.role == "assessor" and c.status == "Draft"):
        raise HTTPException(404, "Claim not found")
    if write and user.role == "assessor" and c.assessor_id not in (None, user.id):
        raise HTTPException(403, "This claim is assigned to another assessor")
    return c


def student_view(d: dict, user: User) -> dict:
    """Internal working notes are not shown to the claimant."""
    if user.role == "student":
        d = {**d, "assessor_notes": ""}
    return d


def actor_name(db: Session, uid: int | None, viewer: User) -> str:
    """Students see 'You' / 'Claims team' instead of staff login names (usernames are credentials' other half)."""
    if viewer.role != "student":
        u = db.get(User, uid) if uid else None
        return u.username if u else "system"
    return "You" if uid == viewer.id else ("system" if not uid else "Claims team")


class ClaimIn(BaseModel):
    policy_id: int
    asset_id: int
    incident_date: date
    incident_type: str
    incident_location: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)


class ClaimEdit(BaseModel):
    incident_date: date | None = None
    incident_type: str | None = Field(default=None, max_length=40)
    incident_location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class StatusIn(BaseModel):
    to: str = Field(max_length=30)
    reason: str = Field(default="", max_length=1000)


class AssessmentIn(BaseModel):
    assessor_notes: str = Field(default="", max_length=10000)


class ItemIn(BaseModel):
    component: str = Field(min_length=1, max_length=80)
    damage_type: str
    severity: str = "Moderate"
    repair_action: str = "Inspect Further"
    parts_cost: float | None = Field(default=None, ge=0, le=10_000_000)
    labour_cost: float | None = Field(default=None, ge=0, le=10_000_000)
    catalogue_entry_id: int | None = None
    evidence_refs: list[int] = Field(default=[], max_length=50)
    confidence: str = "Unknown"
    notes: str = Field(default="", max_length=2000)
    decision_reason: str = Field(default="", max_length=1000)
    ai_suggestion_id: int | None = None


def _validate_item(db: Session, claim: Claim, b: ItemIn):
    for val, allowed, name in ((b.damage_type, S.DAMAGE_TYPES, "damage_type"), (b.severity, S.SEVERITIES, "severity"),
                               (b.repair_action, S.REPAIR_ACTIONS, "repair_action"), (b.confidence, S.CONFIDENCE, "confidence")):
        if val not in allowed:
            raise HTTPException(422, f"{name} must be one of {allowed}")
    if b.ai_suggestion_id is not None:
        sug = db.get(AISuggestion, b.ai_suggestion_id)
        if not sug or sug.claim_id != claim.id:
            raise HTTPException(422, "ai_suggestion_id must reference an AI suggestion generated for this claim")
    valid_ev = {e.id for e in claim.evidence}
    if any(e not in valid_ev for e in b.evidence_refs):
        raise HTTPException(422, "evidence_refs must reference evidence uploaded to this claim")


def _apply_item(db: Session, claim: Claim, item: ClaimItem, b: ItemIn):
    item.component, item.damage_type, item.severity, item.repair_action = b.component, b.damage_type, b.severity, b.repair_action
    item.evidence_refs, item.confidence, item.notes, item.decision_reason = b.evidence_refs, b.confidence, b.notes, b.decision_reason
    if b.catalogue_entry_id:
        cat = db.get(RepairCatalogueEntry, b.catalogue_entry_id)
        if not cat or cat.category != claim.asset.category:
            raise HTTPException(422, "Catalogue entry not found for this asset category")
        item.catalogue_entry_id = cat.id
        if b.parts_cost is None and b.labour_cost is None:
            item.parts_cost, item.labour_cost, item.price_source = float(cat.parts_cost), float(cat.labour_cost), "catalogue"
            return
    item.catalogue_entry_id = b.catalogue_entry_id
    item.parts_cost, item.labour_cost = b.parts_cost, b.labour_cost
    item.price_source = "assessor" if (b.parts_cost is not None or b.labour_cost is not None) else ""


# ------------------------------------------------------------------ claim CRUD
@router.post("/claims", status_code=201)
def create_claim(body: ClaimIn, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    pol = db.get(Policy, body.policy_id)
    if not pol or pol.student_id != user.id:
        raise HTTPException(404, "Policy not found")
    if body.incident_type not in S.INCIDENT_TYPES:
        raise HTTPException(422, f"incident_type must be one of {S.INCIDENT_TYPES}")
    if body.incident_date > date.today():
        raise HTTPException(422, "incident_date cannot be in the future")
    asset = db.get(Asset, body.asset_id)
    if not asset or asset.owner_id != user.id:  # BOLA: another student's asset id must be indistinguishable from a missing one
        raise HTTPException(404, "Asset not found")
    insured_ever = {pa.asset_id for pa in pol.assets} | {i for v in pol.versions for i in v.snapshot.get("insured_asset_ids", [])}
    if asset.id not in insured_ever:
        raise HTTPException(422, "This asset is not insured under the selected policy")
    enforce(db, Claim.claimant_id, user.id, Claim.created_at, settings.CLAIMS_PER_HOUR, 60, "claims created")
    c = Claim(claim_number=f"TMP-{uuid.uuid4().hex[:20]}", claimant_id=user.id, **body.model_dump())
    db.add(c); db.flush()
    c.claim_number = f"CLM-{date.today().year}-{c.id:05d}"  # derived from the primary key: no read-then-write race between concurrent requests
    db.add(ClaimStatusHistory(claim_id=c.id, from_status="", to_status="Draft", reason="Claim created", changed_by=user.id))
    S.audit(db, "claim", c.id, "claim_created", {"policy": pol.policy_number, "asset_id": body.asset_id, "incident_type": body.incident_type}, user, claim_id=c.id)
    db.commit(); db.refresh(c)
    return student_view(S.claim_dict(c, True), user)


@router.get("/claims")
def list_claims(status: str | None = Query(None, max_length=30), assigned: str | None = Query(None, max_length=12), limit: int = Query(200, ge=1, le=500),
                offset: int = Query(0, ge=0, le=100_000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Claim).where(Claim.flow == "manual").order_by(Claim.id.desc()).limit(limit).offset(offset)
    if user.role == "assessor":
        q = q.where(Claim.status != "Draft")
    if assigned == "me":
        q = q.where(Claim.assessor_id == user.id)
    elif assigned == "unassigned":
        q = q.where(Claim.assessor_id.is_(None))
    if user.role == "student":
        q = q.where(Claim.claimant_id == user.id)
    if status:
        q = q.where(Claim.status == status)
    return [student_view(S.claim_dict(c), user) for c in db.scalars(q)]


@router.get("/claims/{cid}")
def get_claim(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    d = student_view(S.claim_dict(c, True), user)
    d["evaluation"] = S.latest_evaluation(db, c)
    d["status_history"] = [{"from": h.from_status, "to": h.to_status, "reason": h.reason, "changed_at": h.changed_at.isoformat(),
                            "changed_by": actor_name(db, h.changed_by, user)}
                           for h in db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == c.id).order_by(ClaimStatusHistory.id))]
    d["allowed_transitions"] = [t for t, roles in S.CLAIM_TRANSITIONS.get(c.status, {}).items()
                                if user.role in roles and (user.role != "student" or c.claimant_id == user.id)]
    return d


@router.put("/claims/{cid}")
def edit_claim(cid: int, body: ClaimEdit, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    if c.status not in ("Draft", "Pending Information"):
        raise HTTPException(400, f"A claim in status '{c.status}' can no longer be edited by the student")
    changes = body.model_dump(exclude_none=True)
    if "incident_type" in changes and changes["incident_type"] not in S.INCIDENT_TYPES:
        raise HTTPException(422, f"incident_type must be one of {S.INCIDENT_TYPES}")
    if changes.get("incident_date") and changes["incident_date"] > date.today():
        raise HTTPException(422, "incident_date cannot be in the future")
    for k, v in changes.items():
        setattr(c, k, v)
    S.audit(db, "claim", c.id, "claim_edited", {k: str(v) for k, v in changes.items()}, user, claim_id=c.id)
    db.commit()
    return student_view(S.claim_dict(c, True), user)


@router.post("/claims/{cid}/submit")
def submit_claim(cid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    S.change_claim_status(db, c, "Submitted", user, "Submitted by student")
    db.commit()
    return S.latest_evaluation(db, c) | {"status": c.status}


@router.post("/claims/{cid}/status")
def set_status(cid: int, body: StatusIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    S.change_claim_status(db, c, body.to, user, body.reason)
    db.commit()
    return student_view(S.claim_dict(c, True), user)


class AssignIn(BaseModel):
    assessor_id: int | None = None


@router.post("/claims/{cid}/assign")
def assign_claim(cid: int, body: AssignIn, user: User = Depends(require_roles("assessor", "admin")), db: Session = Depends(get_db)):
    """Assessors take a claim for themselves; administrators may assign any active assessor."""
    c = claim_access(db, cid, user, write=True)  # an assessor cannot take a claim that another assessor already holds; an administrator can reassign
    if c.status in ("Draft", "Closed"):
        raise HTTPException(400, f"A claim in status '{c.status}' cannot be assigned")
    target = user if user.role == "assessor" else (db.get(User, body.assessor_id) if body.assessor_id else None)
    if not target or target.role != "assessor" or not target.is_active:
        raise HTTPException(400, "assessor_id must reference an active assessor")
    if user.role == "assessor" and body.assessor_id not in (None, user.id):
        raise HTTPException(403, "Assessors can only assign claims to themselves")
    old, c.assessor_id = c.assessor_id, target.id
    S.audit(db, "claim", c.id, "claim_assigned", {"from": old, "to": target.id, "assessor": target.username}, user, claim_id=c.id)
    db.commit()
    return S.claim_dict(c)


@router.put("/claims/{cid}/assessment")
def save_assessment_notes(cid: int, body: AssessmentIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    S.audit(db, "claim", c.id, "assessor_notes_updated", {"before": c.assessor_notes, "after": body.assessor_notes}, user, claim_id=c.id)
    c.assessor_notes = body.assessor_notes
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ evidence
MAX_FILES_PER_CLAIM = 30
CHUNK = 64 * 1024


def _sniff(ext: str, head: bytes, data: bytes) -> str | None:
    """Content-based type check: the file must really be what its extension claims. Returns the verified content type."""
    if ext in (".jpg", ".jpeg") and head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if ext == ".png" and head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if ext == ".gif" and head[:4] == b"GIF8":
        return "image/gif"
    if ext == ".webp" and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if ext == ".pdf" and head.startswith(b"%PDF-"):
        return "application/pdf"
    if ext in (".txt", ".csv") and b"\x00" not in data[:8192]:
        try:
            data[:65536].decode("utf-8")
            return "text/plain" if ext == ".txt" else "text/csv"
        except UnicodeDecodeError:
            return None
    return None


def _safe_name(name: str) -> str:
    base = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "_", Path(name or "file").name).strip(" .")
    return (base or "file")[:120]


@router.post("/claims/{cid}/evidence", status_code=201)
async def upload_evidence(cid: int, doc_type: str = Form(...), file: UploadFile = File(...), user: User = Depends(require_roles("student", "assessor")),
                          db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    if user.role == "student" and c.status not in ("Draft", "Submitted", "Pending Information"):
        raise HTTPException(400, f"Evidence can no longer be added by the student in status '{c.status}'")
    enforce(db, Evidence.uploaded_by, user.id, Evidence.uploaded_at, settings.UPLOADS_PER_HOUR, 60, "uploads")
    if doc_type not in S.DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {S.DOC_TYPES}")
    if len(c.evidence) >= MAX_FILES_PER_CLAIM:
        raise HTTPException(400, f"A claim can hold at most {MAX_FILES_PER_CLAIM} files")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(422, f"File type {ext or '(none)'} not allowed. Allowed: {sorted(ALLOWED_EXT)}")
    limit, buf = settings.MAX_UPLOAD_MB * 1024 * 1024, bytearray()
    while True:  # stream in chunks so an oversized upload is rejected without being held in memory
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    data = bytes(buf)
    if not data:
        raise HTTPException(422, "Empty file")
    verified = _sniff(ext, data[:16], data)
    if not verified:
        raise HTTPException(422, f"File content does not match its type ({ext}). Rejected.")
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    target = (settings.UPLOAD_DIR / stored).resolve()
    if settings.UPLOAD_DIR.resolve() not in target.parents:
        raise HTTPException(400, "Invalid storage path")
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)  # atomic publish: no half-written files are ever visible
    try:
        e = Evidence(claim_id=c.id, doc_type=doc_type, original_name=_safe_name(file.filename), stored_name=stored, content_type=verified,
                     size_bytes=len(data), uploaded_by=user.id)
        db.add(e); db.flush()
        S.audit(db, "evidence", e.id, "evidence_uploaded", {"doc_type": doc_type, "name": e.original_name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}, user, claim_id=c.id)
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)  # do not leave an orphan file behind when the database write fails
        raise
    return {"id": e.id, "doc_type": doc_type, "original_name": e.original_name}


@router.get("/claims/{cid}/evidence/{eid}/file")
def download_evidence(cid: int, eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    e = db.get(Evidence, eid)
    if not e or e.claim_id != c.id:
        raise HTTPException(404, "Evidence not found")
    path = (settings.UPLOAD_DIR / e.stored_name).resolve()
    if settings.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "File missing")
    inline = e.content_type.startswith("image/")  # only verified images render inline; everything else downloads
    # Uploaded bytes are untrusted: a locked-down CSP + sandbox means that even a polyglot file could never run script in the app's origin.
    return FileResponse(path, media_type=e.content_type or "application/octet-stream", filename=e.original_name, content_disposition_type="inline" if inline else "attachment",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, no-store"})


# ------------------------------------------------------------------ damage items (assessor)
def _editable(c: Claim):
    if c.status not in ASSESS_STATES:
        raise HTTPException(400, f"Damage items cannot be changed while the claim is '{c.status}'")


@router.post("/claims/{cid}/items", status_code=201)
def add_item(cid: int, body: ItemIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    _editable(c); _validate_item(db, c, body)
    it = ClaimItem(claim_id=c.id, verification_status="AI Suggested" if body.ai_suggestion_id else "Human Verified", verified_by=None if body.ai_suggestion_id else user.id)
    it.ai_suggestion_id = body.ai_suggestion_id
    _apply_item(db, c, it, body)
    db.add(it); db.flush()
    S.audit(db, "claim_item", it.id, "damage_item_added", S.item_dict(it), user, claim_id=c.id)
    db.commit()
    return S.item_dict(it)


class StudentItemIn(BaseModel):
    """What a student may declare about damage. No prices and no repair decision: those belong to the assessor."""
    component: str = Field(min_length=1, max_length=80)
    damage_type: str
    severity: str = "Moderate"
    notes: str = Field(default="", max_length=1000)
    evidence_refs: list[int] = []


MAX_STUDENT_ITEMS = 20


@router.post("/claims/{cid}/student-items", status_code=201)
def add_student_item(cid: int, body: StudentItemIn, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    """Student-declared damage line. Stored as 'Student Declared' (unpriced); POL-013 keeps the claim pending until an assessor verifies or corrects it."""
    c = claim_access(db, cid, user)
    if c.status not in ("Draft", "Pending Information"):
        raise HTTPException(400, f"Damage items can no longer be added by the student in status '{c.status}'")
    if body.damage_type not in S.DAMAGE_TYPES:
        raise HTTPException(422, f"damage_type must be one of {S.DAMAGE_TYPES}")
    if body.severity not in S.SEVERITIES:
        raise HTTPException(422, f"severity must be one of {S.SEVERITIES}")
    if sum(1 for i in c.items if i.verification_status == "Student Declared") >= MAX_STUDENT_ITEMS:
        raise HTTPException(400, f"At most {MAX_STUDENT_ITEMS} student-declared items per claim")
    if any(e not in {x.id for x in c.evidence} for e in body.evidence_refs):
        raise HTTPException(422, "evidence_refs must reference evidence uploaded to this claim")
    it = ClaimItem(claim_id=c.id, component=body.component.strip(), damage_type=body.damage_type, severity=body.severity, repair_action="Inspect Further",
                   parts_cost=None, labour_cost=None, price_source="", evidence_refs=body.evidence_refs, confidence="Unknown", notes=body.notes,
                   decision_reason="", verification_status="Student Declared", verified_by=None)
    db.add(it); db.flush()
    S.audit(db, "claim_item", it.id, "damage_item_declared_by_student", S.item_dict(it), user, claim_id=c.id)
    db.commit()
    return S.item_dict(it)


@router.delete("/claims/{cid}/student-items/{iid}", status_code=204)
def delete_student_item(cid: int, iid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    it = db.get(ClaimItem, iid)
    if not it or it.claim_id != c.id:
        raise HTTPException(404, "Item not found")
    if c.status not in ("Draft", "Pending Information") or it.verification_status != "Student Declared":
        raise HTTPException(400, "Only unverified student-declared items on an open claim can be removed")
    S.audit(db, "claim_item", it.id, "damage_item_removed_by_student", S.item_dict(it), user, claim_id=c.id)
    db.delete(it)
    db.commit()


def _item_access(db: Session, iid: int, user: User, write: bool = True) -> tuple[ClaimItem, Claim]:
    it = db.get(ClaimItem, iid)
    if not it:
        raise HTTPException(404, "Item not found")
    return it, claim_access(db, it.claim_id, user, write=write)


@router.put("/items/{iid}")
def update_item(iid: int, body: ItemIn, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    it, c = _item_access(db, iid, user)
    _editable(c); _validate_item(db, c, body)
    before = S.item_dict(it)
    _apply_item(db, c, it, body)
    it.verified_by = user.id
    it.verification_status = "Human Corrected" if it.ai_suggestion_id and before["verification_status"] in ("AI Suggested", "Human Corrected") else "Human Verified"
    db.flush()
    after = S.item_dict(it)
    diff = {k: {"before": before[k], "after": after[k]} for k in after if k != "updated_at" and before[k] != after[k]}
    S.audit(db, "claim_item", it.id, "damage_item_corrected" if it.ai_suggestion_id else "damage_item_updated", {"changes": diff, "decision_reason": body.decision_reason}, user, claim_id=c.id)
    db.commit()
    return after


@router.post("/items/{iid}/verify")
def verify_item(iid: int, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    it, c = _item_access(db, iid, user)
    _editable(c)
    old = it.verification_status
    it.verification_status, it.verified_by = ("Human Corrected" if old == "Human Corrected" else "Human Verified"), user.id
    S.audit(db, "claim_item", it.id, "damage_item_verified", {"from": old, "to": it.verification_status}, user, claim_id=c.id)
    db.commit()
    return S.item_dict(it)


@router.delete("/items/{iid}", status_code=204)
def delete_item(iid: int, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    it, c = _item_access(db, iid, user)
    _editable(c)
    S.audit(db, "claim_item", it.id, "damage_item_deleted", S.item_dict(it), user, claim_id=c.id)
    db.delete(it)
    db.commit()


@router.get("/items/{iid}/action-guidance")
def action_guidance(iid: int, user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    """Repair-vs-replace guidance from configured catalogue prices (suggestion only)."""
    it, c = _item_access(db, iid, user, write=False)
    cat = c.asset.category
    repair = db.scalar(select(RepairCatalogueEntry).where(RepairCatalogueEntry.category == cat, RepairCatalogueEntry.component == it.component,
                                                           RepairCatalogueEntry.action == "Repair", RepairCatalogueEntry.active == True))  # noqa: E712
    whole = db.scalar(select(RepairCatalogueEntry).where(RepairCatalogueEntry.category == cat, RepairCatalogueEntry.component == "Whole device",
                                                          RepairCatalogueEntry.action == "Replace", RepairCatalogueEntry.active == True))  # noqa: E712
    ver = S.version_in_force(c.policy, c.incident_date)
    thr = ver.snapshot["terms"]["repair_replace_threshold_pct"]
    rc = float(repair.parts_cost + repair.labour_cost) if repair else (None if it.parts_cost is None else float((it.parts_cost or 0) + (it.labour_cost or 0)))
    rp = float(whole.parts_cost + whole.labour_cost) if whole else None
    action, why = suggest_repair_action(rc, rp, thr)
    return {"suggested_action": action, "reason": why, "repair_cost": rc, "replacement_cost": rp, "threshold_pct": thr,
            "note": "Suggestion only - the assessor decides."}


# ------------------------------------------------------------------ evaluation / report / audit
@router.post("/claims/{cid}/evaluate")
def evaluate(cid: int, user: User = Depends(require_roles("assessor", "admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    if c.status == "Draft":
        raise HTTPException(400, "Submit the claim before evaluating it")
    S.evaluate_and_store(db, c, user)
    db.commit()
    return S.latest_evaluation(db, c)


@router.get("/claims/{cid}/evaluation")
def get_evaluation(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    ev = S.latest_evaluation(db, c)
    if not ev:
        raise HTTPException(404, "No evaluation has been run yet")
    ctx, _ = S.build_context(db, c)
    from ..engine.rules import evaluate_claim
    calc = evaluate_claim(ctx)["calculation"] if ev else None
    ev["stale"] = calc["estimated_payable"] != ev["estimated_payable"]  # data changed since the stored run
    ev["calculation_summary"] = {k: calc[k] for k in ("gross_total", "excluded_total", "depreciation_total", "eligible_subtotal", "per_item_adjustment",
                                                      "overall_adjustment", "deductible_applied", "estimated_payable", "uncovered_total", "uncovered", "per_item", "flags", "calc_order", "facts")}
    return ev


@router.get("/claims/{cid}/audit")
def claim_audit(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    q = select(AuditRecord).where(AuditRecord.claim_id == c.id).order_by(AuditRecord.id)
    rows = db.scalars(q).all()
    if user.role == "student":
        rows = [a for a in rows if a.entity_type == "claim" and a.action in ("claim_created", "claim_status_changed", "claim_edited") or a.action == "evidence_uploaded"]
    return [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail,
             "username": a.username if user.role != "student" else actor_name(db, a.user_id, user), "created_at": a.created_at.isoformat()} for a in rows]


@router.get("/claims/{cid}/report")
def report(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    ev = S.latest_evaluation(db, c)
    ver = S.version_in_force(c.policy, c.incident_date)
    ctx, _ = S.build_context(db, c)
    from ..engine.rules import evaluate_claim
    calc = evaluate_claim(ctx)["calculation"] if ev else None
    items = []
    pi = {x["item_id"]: x for x in (calc["per_item"] if calc else [])}
    for i in c.items:
        d = S.item_dict(i)
        d["assessment"] = pi.get(i.id)
        items.append(d)
    ai = []
    if user.role != "student":
        for s in db.scalars(select(AISuggestion).where(AISuggestion.claim_id == c.id).order_by(AISuggestion.id)):
            ai.append({"id": s.id, "kind": s.kind, "is_ai": s.is_ai, "provider": s.provider, "status_note": s.status_note, "accepted": s.accepted})
    return {
        "generated_at": date.today().isoformat(),
        "disclaimer": "Estimate prepared by a rules engine for an academic prototype. It is a recommendation, not a settlement or payment decision; a human assessor makes the final decision.",
        "claim": student_view(S.claim_dict(c, True), user) | {"policy_number": c.policy.policy_number},
        "policy": {"policy_number": c.policy.policy_number, "version_applied": ver.version, "version_effective_from": ver.effective_from.isoformat(),
                   "plan_name": ver.snapshot["terms"]["plan_name"], "terms": ver.snapshot["terms"], "status_now": c.policy.status,
                   "period": f"{c.policy.start_date} to {c.policy.end_date}"},
        "asset": S.asset_dict(c.asset), "items": items, "evaluation": ev,
        "calculation_summary": None if not calc else {k: calc[k] for k in ("gross_total", "excluded_total", "depreciation_total", "eligible_subtotal", "per_item_adjustment",
                                                                           "overall_adjustment", "deductible_applied", "estimated_payable", "uncovered_total", "uncovered", "flags", "calc_order")},
        "assessor_notes": c.assessor_notes if user.role != "student" else "", "decision_reason": c.decision_reason, "ai_suggestions": ai,
        "status_history": [{"from": h.from_status, "to": h.to_status, "reason": h.reason, "changed_at": h.changed_at.isoformat()}
                           for h in db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == c.id).order_by(ClaimStatusHistory.id))],
    }
