import threading
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services as S
from ..ai import service as ai
from ..config import settings
from ..database import get_db
from ..limits import enforce
from ..engine.rules import evaluate_claim
from ..models import AISuggestion, Evidence, Policy, RepairCatalogueEntry, User
from ..security import current_user, require_roles
from .claims import claim_access

router = APIRouter(prefix="/api/ai")


_SLOTS = threading.BoundedSemaphore(max(1, settings.AI_MAX_CONCURRENCY))


@contextmanager
def _slot():
    """A provider call can take minutes (timeouts and retries) and blocks a worker thread: cap concurrent calls so AI traffic cannot starve the whole API."""
    if not _SLOTS.acquire(timeout=3):
        raise HTTPException(503, "The AI service is busy. Please try again shortly.", headers={"Retry-After": "10"})
    try:
        yield
    finally:
        _SLOTS.release()


def _guard(db: Session, user: User) -> None:
    """Per-user ceiling on AI requests (they cost money when a real provider is configured)."""
    lim = settings.AI_CALLS_PER_10_MIN_STUDENT if user.role == "student" else settings.AI_CALLS_PER_10_MIN_STAFF
    enforce(db, AISuggestion.created_by, user.id, AISuggestion.created_at, lim, 10, "AI requests")


class EvidenceRef(BaseModel):
    evidence_id: int | None = None


def _store(db, user, claim_id, kind, result, evidence_id=None, policy_id=None) -> AISuggestion:
    s = AISuggestion(claim_id=claim_id, policy_id=policy_id, kind=kind, is_ai=result["is_ai"], provider=result["provider"], model=result["model"],
                     status_note=result["status_note"], evidence_id=evidence_id, content=result["content"], created_by=user.id,
                     meta=result.get("meta", {}), validation_status=result.get("validation_status", "n/a"))
    db.add(s); db.flush()
    S.audit(db, "ai_suggestion", s.id, f"ai_{kind}_generated", {"is_ai": s.is_ai, "provider": s.provider, "model": s.model}, user, claim_id=claim_id, policy_id=policy_id)
    return s


def _dict(s: AISuggestion) -> dict:
    return {"id": s.id, "claim_id": s.claim_id, "policy_id": s.policy_id, "kind": s.kind, "is_ai": s.is_ai, "provider": s.provider, "model": s.model,
            "status_note": s.status_note, "evidence_id": s.evidence_id, "content": s.content, "meta": s.meta or {}, "validation_status": s.validation_status, "accepted": s.accepted, "created_at": s.created_at.isoformat(),
            "label": "AI suggestion (unverified)" if s.is_ai else "Demo fallback - NOT an AI result"}


def _evidence(db, claim, evidence_id):
    e = db.get(Evidence, evidence_id) if evidence_id else None
    if evidence_id and (not e or e.claim_id != claim.id):
        raise HTTPException(404, "Evidence not found on this claim")
    return e


def _read(e: Evidence | None):
    if not e:
        return None
    p = settings.UPLOAD_DIR / e.stored_name
    return p.read_bytes() if p.exists() else None


def _media(e: Evidence | None) -> str:
    if not e:
        return ""
    ext = e.stored_name.rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(ext, e.content_type or "application/octet-stream")


@router.get("/status")
def ai_status(user: User = Depends(current_user)):
    return ai.status()


@router.post("/test-connection")
def test_connection(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    """Administrator action: one tiny structured request to verify credentials/model names. Reports the real outcome."""
    with _slot():
        res = ai.check_connection()
    S.audit(db, "system", 0, "ai_connection_tested", {"ok": res["ok"], "provider": settings.AI_PROVIDER}, user)
    db.commit()
    return res


@router.get("/claims/{cid}/suggestions")
def list_suggestions(cid: int, user: User = Depends(require_roles("assessor", "admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    return [_dict(s) for s in db.scalars(select(AISuggestion).where(AISuggestion.claim_id == c.id).order_by(AISuggestion.id.desc()))]


def _student_view(d: dict, user: User) -> dict:
    """Students get the AI-assisted information (clearly labelled) but not provider metadata / raw excerpts."""
    return {k: v for k, v in d.items() if k not in ("meta",)} if user.role == "student" else d


def _student_ok(c, user: User):
    if user.role == "student" and c.status not in ("Draft", "Submitted", "Pending Information"):
        raise HTTPException(400, "AI-assisted information can only be requested while the claim is open for your input")


@router.post("/claims/{cid}/describe-image")
def describe_image(cid: int, body: EvidenceRef, user: User = Depends(require_roles("student", "assessor", "admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    _student_ok(c, user)
    _guard(db, user)
    e = _evidence(db, c, body.evidence_id)
    with _slot():
        res = ai.describe_damage(_read(e), _media(e), c.asset.category, c.incident_type, c.description)
    s = _store(db, user, c.id, "image_description", res, e.id if e else None)
    db.commit()
    return _student_view(_dict(s), user)


@router.post("/claims/{cid}/suggest-assessment")
def suggest_assessment(cid: int, user: User = Depends(require_roles("assessor", "admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    _guard(db, user)
    cat = [{"id": x.id, "component": x.component, "damage_type": x.damage_type, "action": x.action}
           for x in db.scalars(select(RepairCatalogueEntry).where(RepairCatalogueEntry.category == c.asset.category, RepairCatalogueEntry.active == True))]  # noqa: E712
    with _slot():
        res = ai.suggest_assessment(c.asset.category, c.incident_type, c.description, cat, [S.item_dict(i) for i in c.items], sorted({e.doc_type for e in c.evidence}))
    s = _store(db, user, c.id, "assessment", res)
    db.commit()
    return _dict(s)


@router.post("/claims/{cid}/explain")
def explain_claim(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    _guard(db, user)
    ev = S.latest_evaluation(db, c)
    if not ev:
        raise HTTPException(400, "No rule evaluation exists yet - nothing to explain")
    ver = S.version_in_force(c.policy, c.incident_date)
    grounded = {"policy_terms": ver.snapshot["terms"], "evaluation": ev, "claim": {"incident_type": c.incident_type, "incident_date": str(c.incident_date), "status": c.status}}
    with _slot():
        res = ai.explain("claim", grounded)
    s = _store(db, user, c.id, "explanation", res)
    db.commit()
    return _dict(s)


@router.post("/policies/{pid}/explain")
def explain_policy(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Policy, pid)
    if not p or (user.role == "student" and p.student_id != user.id):
        raise HTTPException(404, "Policy not found")
    _guard(db, user)
    ver = max(p.versions, key=lambda v: v.version)
    with _slot():
        res = ai.explain("policy", {"terms": ver.snapshot["terms"], "policy_number": p.policy_number})
    s = _store(db, user, None, "explanation", res, policy_id=p.id)
    db.commit()
    return _dict(s)


@router.post("/claims/{cid}/extract-quotation")
def extract_quotation(cid: int, body: EvidenceRef, user: User = Depends(require_roles("student", "assessor", "admin")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user, write=True)
    _student_ok(c, user)
    _guard(db, user)
    e = _evidence(db, c, body.evidence_id)
    if not e:
        raise HTTPException(422, "evidence_id is required")
    raw = _read(e)
    media = _media(e)
    text = raw.decode("utf-8", errors="ignore") if raw is not None and e.stored_name.endswith((".txt", ".csv")) else None
    with _slot():
        res = ai.extract_quotation(raw, media, text)
    s = _store(db, user, c.id, "quotation", res, e.id)
    db.commit()
    return _student_view(_dict(s), user) | {"verify_notice": "Extracted lines are unverified. Verify against the document before using any amount."}


@router.post("/suggestions/{sid}/accept-item")
def accept_item(sid: int, index: int = Query(0, ge=0, le=9), user: User = Depends(require_roles("assessor")), db: Session = Depends(get_db)):
    """Turn one suggested item into a claim item flagged 'AI Suggested' (needs human verification). The suggestion row is left untouched."""
    s = db.get(AISuggestion, sid)
    if not s or s.kind not in ("assessment", "image_description") or not s.claim_id:
        raise HTTPException(404, "Suggestion not found or not convertible")
    c = claim_access(db, s.claim_id, user, write=True)
    from .claims import ItemIn, add_item
    if s.kind == "assessment":
        items = s.content.get("suggested_items", [])
        if index >= len(items):
            raise HTTPException(404, "No such suggested item")
        it = items[index]
        body = ItemIn(component=it["component"], damage_type=it["damage_type"], severity=it["severity"], repair_action=it["repair_action"],
                      catalogue_entry_id=it.get("catalogue_entry_id"), confidence=it["confidence"], notes=f"AI rationale: {it.get('rationale', '')}", ai_suggestion_id=s.id)
    else:
        comps = s.content.get("likely_components") or ["Unspecified"]
        body = ItemIn(component=str(comps[0]), damage_type=s.content["suggested_damage_type"], severity=s.content["suggested_severity"],
                      repair_action=s.content["suggested_repair_action"], confidence=s.content["confidence"], notes="From image description suggestion.",
                      ai_suggestion_id=s.id, evidence_refs=[s.evidence_id] if s.evidence_id else [])
    out = add_item(c.id, body, user, db)
    s.accepted = True
    db.commit()
    return out
