"""Self-service InsurTech API (registration, eligibility, assets, purchase, premiums, AI-verified claims, review, analytics). All values are server-side."""
from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import evidence as EV
from .. import services as S
from .. import v3
from ..ai import authenticity, model_registry, verification, vision
from ..config import settings
from ..database import get_db
from ..engine import insurance as I
from ..limits import enforce
from ..models import (AIVerificationReport, Asset, AssetCategory, AssetEvidence, AuditRecord, Claim, ClaimDecision, ClaimImage, ClaimStatusHistory, Evidence, Policy, PremiumTransaction, Settlement, Student, User, now)
from ..security import check_password_policy, current_user, hash_password, require_roles
from .claims import _safe_name, _sniff
from .auth import USERNAME_RE

router = APIRouter(prefix="/api")
CHUNK = 64 * 1024
IMG_EXT = {".jpg", ".jpeg", ".png"}
DOC_EXT = {".jpg", ".jpeg", ".png", ".pdf"}


# ------------------------------------------------------------------ uploads
async def read_upload(file: UploadFile, allowed: set[str], kind: str) -> tuple[bytes, str, str]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(422, f"{kind}: file type {ext or '(none)'} is not allowed. Allowed: {', '.join(sorted(allowed))}")
    limit, buf = settings.MAX_UPLOAD_MB * 1024 * 1024, bytearray()
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"{kind}: file exceeds {settings.MAX_UPLOAD_MB} MB")
    data = bytes(buf)
    if not data:
        raise HTTPException(422, f"{kind}: the file is empty")
    verified = _sniff(ext, data[:16], data)
    if not verified:
        raise HTTPException(422, f"{kind}: the file content does not match its type ({ext}). Rejected.")
    if verified.startswith("image/"):
        try:
            vision.decode(data)
        except vision.ImageError:
            raise HTTPException(422, f"{kind}: the image is corrupted or unreadable. Please upload another file.")
    return data, ext, verified


def store(data: bytes, ext: str) -> str:
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    target = (settings.UPLOAD_DIR / name).resolve()
    if settings.UPLOAD_DIR.resolve() not in target.parents:
        raise HTTPException(400, "Invalid storage path")
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return name


def send(stored: str, ctype: str, name: str):
    path = (settings.UPLOAD_DIR / stored).resolve()
    if settings.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "File missing")
    return FileResponse(path, media_type=ctype, filename=name, content_disposition_type="inline" if ctype.startswith("image/") else "attachment",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ registration
class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    full_name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120)
    password: str = Field(max_length=128)
    college: str = Field(default="", max_length=120)

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("username must be 3-50 characters: a-z, 0-9, dot, dash, underscore")
        return v

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid email address")
        return v


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Self-registration always creates a STUDENT. The role can never be chosen by the caller."""
    from datetime import timedelta
    if (db.scalar(select(func.count()).select_from(User).where(User.created_at > now() - timedelta(minutes=10))) or 0) >= 30:
        raise HTTPException(429, "Too many registrations right now. Please try again in a few minutes.", headers={"Retry-After": "600"})
    check_password_policy(body.password, body.username)
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "That username is already taken.")
    u = User(username=body.username, password_hash=hash_password(body.password), full_name=body.full_name.strip(), role="student", email=body.email, password_changed_at=now())
    db.add(u); db.flush()
    db.add(Student(user_id=u.id, college=body.college.strip(), roll_number=""))
    S.audit(db, "user", u.id, "student_registered", {"username": u.username}, u)
    db.commit()
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role}


# ------------------------------------------------------------------ categories
@router.get("/v2/categories")
def list_categories(db: Session = Depends(get_db)):
    return [v3.category_dict(c) for c in db.scalars(select(AssetCategory).where(AssetCategory.active.is_(True)).order_by(AssetCategory.id))]


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=40)
    description: str = Field(default="", max_length=300)
    min_purchase_value: float = Field(gt=0, le=10_000_000)
    monthly_premium: float = Field(gt=0, le=100_000)
    max_coverage: float = Field(gt=0, le=10_000_000)
    deductible: float = Field(default=0, ge=0, le=1_000_000)
    policy_months: int = Field(default=12, ge=1, le=60)
    waiting_period_days: int = Field(default=0, ge=0, le=365)
    depreciation_pct_per_year: float = Field(default=0, ge=0, le=100)
    depreciation_max_pct: float = Field(default=0, ge=0, le=100)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    covered_incident_types: list[str] = Field(default_factory=lambda: ["Accidental Damage", "Liquid Damage"], max_length=10)
    excluded_damage_types: list[str] = Field(default_factory=list, max_length=20)
    damage_types: list[str] = Field(default_factory=list, max_length=20)
    reference_repair_costs: dict[str, float] = Field(default_factory=dict)
    eligibility_conditions: str = Field(default="", max_length=500)
    requires_serial: bool = True
    active: bool = True

    @field_validator("covered_incident_types")
    @classmethod
    def _inc(cls, v):
        bad = [x for x in v if x not in S.INCIDENT_TYPES]
        if bad:
            raise ValueError(f"unknown incident types {bad}; allowed {S.INCIDENT_TYPES}")
        return v

    @field_validator("reference_repair_costs")
    @classmethod
    def _ref(cls, v):
        if any(x < 0 or x > 10_000_000 for x in v.values()):
            raise ValueError("reference costs must be between 0 and 10,000,000")
        return v


def _check_category(body: CategoryIn):
    if body.max_coverage > body.min_purchase_value * 1.0 and False:
        pass
    if body.deductible >= body.max_coverage:
        raise HTTPException(422, "The deductible must be lower than the maximum coverage.")


@router.get("/v2/admin/categories")
def admin_categories(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return [v3.category_dict(c) for c in db.scalars(select(AssetCategory).order_by(AssetCategory.id))]


@router.post("/v2/admin/categories", status_code=201)
def create_category(body: CategoryIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    _check_category(body)
    if db.scalar(select(AssetCategory.id).where(func.lower(AssetCategory.name) == body.name.strip().lower())):
        raise HTTPException(409, "A category with that name already exists.")
    c = AssetCategory(**body.model_dump() | {"name": body.name.strip()})
    db.add(c); db.flush(); v3.sync_plan(db, c)
    S.audit(db, "category", c.id, "category_created", body.model_dump(), user)
    db.commit()
    return v3.category_dict(c)


@router.put("/v2/admin/categories/{cid}")
def update_category(cid: int, body: CategoryIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = db.get(AssetCategory, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    _check_category(body)
    if db.scalar(select(AssetCategory.id).where(func.lower(AssetCategory.name) == body.name.strip().lower(), AssetCategory.id != cid)):
        raise HTTPException(409, "A category with that name already exists.")
    before = v3.category_dict(c)
    for k, v in (body.model_dump() | {"name": body.name.strip()}).items():
        setattr(c, k, v)
    v3.sync_plan(db, c)
    after = v3.category_dict(c)
    S.audit(db, "category", c.id, "category_updated", {"changes": {k: {"before": before[k], "after": after[k]} for k in after if before[k] != after[k] and k != "updated_at"},
                                                       "note": "Issued policies keep the terms frozen at purchase."}, user)
    db.commit()
    return after


# ------------------------------------------------------------------ eligibility & quote
class EligibilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_id: int
    purchase_price: float = Field(gt=0, le=10_000_000)


@router.post("/v2/eligibility")
def eligibility(body: EligibilityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(AssetCategory, body.category_id)
    if not c:
        raise HTTPException(404, "Category not found")
    t = I.category_terms(c)
    res = I.check_eligibility(t, body.purchase_price, c.active)
    return res | {"quote": I.quote(t, body.purchase_price) if res["eligible"] else None}


# ------------------------------------------------------------------ assets
def own_asset(db: Session, aid: int, user: User) -> Asset:
    a = db.get(Asset, aid)
    if not a or (user.role == "student" and a.owner_id != user.id):
        raise HTTPException(404, "Asset not found")
    return a


def _present(f: UploadFile | None) -> UploadFile | None:
    """Browsers send an empty part for an untouched file input; treat that as 'not provided'."""
    return f if f is not None and (f.filename or "").strip() else None


@router.post("/v2/assets", status_code=201)
async def register_asset(category_id: int = Form(...), brand: str = Form(..., min_length=1, max_length=80), model: str = Form(..., min_length=1, max_length=80),
                         purchase_price: float = Form(..., gt=0, le=10_000_000), purchase_date: date = Form(...), serial_number: str = Form("", max_length=80),
                         description: str = Form("", max_length=500), front_photo: UploadFile | None = File(None), photo: UploadFile | None = File(None),
                         back_photo: UploadFile | None = File(None), invoice: UploadFile | None = File(None), extra_files: list[UploadFile] | None = File(None),
                         user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    """Register an item with its evidence. `photo` is the legacy name of `front_photo`. A back photograph and an invoice may be added later (POST /v2/assets/{id}/evidence),
    but staff cannot approve the registration, and so no policy can be bought, until the front and back photographs are present."""
    cat = db.get(AssetCategory, category_id)
    if not cat:
        raise HTTPException(404, "Category not found")
    enforce(db, Asset.owner_id, user.id, Asset.created_at, settings.ASSETS_PER_HOUR, 60, "assets registered")
    if purchase_date > date.today():
        raise HTTPException(422, "The purchase date cannot be in the future.")
    chk = I.check_eligibility(I.category_terms(cat), purchase_price, cat.active)
    if not chk["eligible"]:
        raise HTTPException(422, chk["reason"])
    if cat.requires_serial and not serial_number.strip():
        raise HTTPException(422, f"A serial number, IMEI or frame number is required for {cat.name}.")
    front = _present(front_photo) or _present(photo)
    if front is None:
        raise HTTPException(422, "A front photograph of the item is required.")
    queue: list[tuple[str, UploadFile, str]] = [("front_photo", front, "Front photograph")]
    if _present(back_photo):
        queue.append(("back_photo", back_photo, "Back photograph"))
    if _present(invoice):
        queue.append(("invoice", invoice, "Invoice"))
    for i, f in enumerate([x for x in (extra_files or []) if _present(x)]):
        queue.append(("extra", f, f"Additional file {i + 1}"))
    if len(queue) > settings.EVIDENCE_PER_ASSET_MAX:
        raise HTTPException(422, f"At most {settings.EVIDENCE_PER_ASSET_MAX} evidence files can be attached to one registration.")
    read: list[tuple[str, bytes, str, str, UploadFile]] = []  # kind, data, ext, content type, upload
    for kind, up, label in queue:
        data, ext, ctype = await read_upload(up, IMG_EXT if kind in ("front_photo", "back_photo") else DOC_EXT, label)
        if kind == "extra":
            kind = "extra_photo" if ctype.startswith("image/") else "document"
        read.append((kind, data, ext, ctype, up))
    if serial_number.strip() and db.scalar(select(Asset.id).where(func.lower(Asset.serial_number) == serial_number.strip().lower(), Asset.category_id.is_not(None))):
        raise HTTPException(409, "An asset with that serial number is already registered.")
    stored: list[str] = []
    try:
        names = []
        for kind, data, ext, ctype, up in read:
            n = store(data, ext); stored.append(n); names.append(n)
        fr = next(i for i, r in enumerate(read) if r[0] == "front_photo")
        iv = next((i for i, r in enumerate(read) if r[0] == "invoice"), None)
        a = Asset(owner_id=user.id, category=cat.name, category_id=cat.id, name=f"{brand.strip()} {model.strip()}", make_model=f"{brand.strip()} {model.strip()}", brand=brand.strip(),
                  model_name=model.strip(), serial_number=serial_number.strip(), purchase_date=purchase_date, declared_value=purchase_price, description=description.strip(),
                  invoice_file=names[iv] if iv is not None else "", invoice_name=_safe_name(read[iv][4].filename) if iv is not None else "", photo_file=names[fr],
                  photo_name=_safe_name(read[fr][4].filename), invoice_verified=False, proof_of_purchase_ref="uploaded invoice" if iv is not None else "no invoice provided",
                  eligibility_status="Eligible", eligibility_reason=chk["reason"], evidence_status="Pending review")
        db.add(a); db.flush()
        corp = EV.corpus(db, exclude_asset_id=a.id, photos_only=False)
        for (kind, data, ext, ctype, up), n in zip(read, names):
            EV.record(db, a, kind, data, n, _safe_name(up.filename), ctype, user, corp=corp)
        S.audit(db, "asset", a.id, "asset_registered", {"category": cat.name, "price": purchase_price, "invoice_verified": False, "evidence_files": len(read), "evidence_status": a.evidence_status}, user)
        db.commit()
    except Exception:
        db.rollback()
        for n in stored:
            (settings.UPLOAD_DIR / n).unlink(missing_ok=True)
        raise
    return v3.asset_v2(a, db)


@router.get("/v2/assets")
def my_assets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Asset).where(Asset.category_id.is_not(None)).order_by(Asset.id)
    if user.role == "student":
        q = q.where(Asset.owner_id == user.id)
    return [v3.asset_v2(a, db) for a in db.scalars(q)]


@router.get("/v2/assets/{aid}")
def asset_detail(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return v3.asset_v2(own_asset(db, aid, user), db)


@router.get("/v2/assets/{aid}/file/{kind}")
def asset_file(aid: int, kind: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    if kind == "photo" and a.photo_file:
        return send(a.photo_file, "image/png" if a.photo_file.endswith(".png") else "image/jpeg", a.photo_name)
    if kind == "invoice" and a.invoice_file:
        ext = Path(a.invoice_file).suffix
        return send(a.invoice_file, {".pdf": "application/pdf", ".png": "image/png"}.get(ext, "image/jpeg"), a.invoice_name)
    raise HTTPException(404, "File not found")


# ------------------------------------------------------------------ registration evidence
def _is_staff(user: User) -> bool:
    return user.role in ("admin", "assessor")


@router.get("/v2/assets/{aid}/evidence")
def list_evidence(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    return EV.summary(db, a, staff=_is_staff(user))


@router.post("/v2/assets/{aid}/evidence", status_code=201)
async def add_evidence(aid: int, kind: str = Form(...), file: UploadFile = File(...), user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    """Add or replace one evidence file while the registration is still open. A new front photo, back photo or invoice replaces the old one."""
    a = own_asset(db, aid, user)
    if a.evidence_status not in EV.OPEN_STATUSES:
        raise HTTPException(409, f"Evidence can no longer be changed: the registration is '{a.evidence_status}'.")
    if kind not in EV.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(EV.KINDS)}")
    enforce(db, AssetEvidence.uploaded_by, user.id, AssetEvidence.uploaded_at, settings.UPLOADS_PER_HOUR, 60, "uploads")
    items = EV.rows(db, a.id)
    replaced = sum(1 for e in items if e.kind == kind) if kind in EV.SINGLE_KINDS else 0
    if len(items) - replaced >= settings.EVIDENCE_PER_ASSET_MAX:
        raise HTTPException(409, f"At most {settings.EVIDENCE_PER_ASSET_MAX} evidence files can be attached to one registration.")
    data, ext, ctype = await read_upload(file, IMG_EXT if kind in EV.PHOTO_KINDS else DOC_EXT, EV.KIND_LABEL[kind])
    name = store(data, ext)
    try:
        e = EV.record(db, a, kind, data, name, _safe_name(file.filename), ctype, user)
        if kind == "front_photo":
            a.photo_file, a.photo_name = name, e.original_name
        elif kind == "invoice":
            a.invoice_file, a.invoice_name, a.invoice_verified = name, e.original_name, False
        if a.evidence_status == "More evidence requested":
            a.evidence_status = "Pending review"  # the student answered the request: back into the review queue
            S.audit(db, "asset", a.id, "evidence_resubmitted", {"kind": kind}, user)
        db.commit()
    except Exception:
        db.rollback()
        (settings.UPLOAD_DIR / name).unlink(missing_ok=True)
        raise
    return EV.summary(db, a)


@router.delete("/v2/assets/{aid}/evidence/{eid}")
def delete_evidence(aid: int, eid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    if a.evidence_status not in EV.OPEN_STATUSES:
        raise HTTPException(409, f"Evidence can no longer be changed: the registration is '{a.evidence_status}'.")
    e = db.get(AssetEvidence, eid)
    if not e or e.asset_id != a.id:
        raise HTTPException(404, "Evidence file not found")
    if e.kind == "front_photo":
        a.photo_file, a.photo_name = "", ""
    elif e.kind == "invoice":
        a.invoice_file, a.invoice_name, a.invoice_verified = "", "", False
    EV.remove(db, e, user)
    db.commit()
    return EV.summary(db, a)


@router.get("/v2/assets/{aid}/evidence/{eid}/file")
def evidence_file(aid: int, eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    e = db.get(AssetEvidence, eid)
    if not e or e.asset_id != a.id:
        raise HTTPException(404, "Evidence file not found")
    return send(e.stored_name, e.content_type, e.original_name)


# ------------------------------------------------------------------ administrator evidence review
@router.get("/v2/admin/evidence-reviews")
def evidence_queue(status: str | None = Query(None, max_length=30), user: User = Depends(require_roles("admin")), db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=500)):
    q = select(Asset).where(Asset.category_id.is_not(None)).order_by(Asset.id.desc()).limit(limit)
    if status:
        if status not in EV.STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(EV.STATUSES)}")
        q = q.where(Asset.evidence_status == status)
    out = []
    for a in db.scalars(q):
        items = EV.rows(db, a.id)
        flags = [f for e in items for f in (e.flags or [])]
        out.append({"id": a.id, "name": a.name, "category": a.category, "owner": a.owner.full_name, "purchase_price": float(a.declared_value), "created_at": S.iso(a.created_at),
                    "evidence_status": a.evidence_status, "files": len(items), "missing_required": EV.missing_required(items), "has_invoice": any(e.kind == "invoice" for e in items),
                    "flags": {k: sum(1 for f in flags if f["severity"] == k) for k in ("high", "medium", "low")}, "insured": v3.active_policy_for(db, a.id) is not None})
    order = {s_: i for i, s_ in enumerate(EV.STATUSES)}
    return sorted(out, key=lambda r: (order[r["evidence_status"]], -r["id"]))


@router.get("/v2/admin/assets/{aid}/evidence-review")
def evidence_review_detail(aid: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    a = db.get(Asset, aid)
    if not a or a.category_id is None:
        raise HTTPException(404, "Asset not found")
    hist = db.scalars(select(AuditRecord).where(AuditRecord.entity_type == "asset", AuditRecord.entity_id == a.id, AuditRecord.action == "evidence_review_decided").order_by(AuditRecord.id.desc())).all()
    items = EV.rows(db, a.id)
    EV.ensure_fingerprints(db, items)
    db.commit()
    return v3.asset_v2(a, db) | {"owner_name": a.owner.full_name, "evidence": EV.summary(db, a, items, staff=True),
                                 "review_history": [{"at": S.iso(h.created_at), "by": h.username, **{k: h.detail.get(k) for k in ("decision", "from", "to", "note")}} for h in hist]}


class EvidenceReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str = Field(default="", max_length=500)
    accept_missing_invoice: bool = False

    @field_validator("decision")
    @classmethod
    def _d(cls, v):
        if v not in ("approve", "request_more", "reject"):
            raise ValueError("decision must be approve, request_more or reject")
        return v


@router.post("/v2/admin/assets/{aid}/evidence-review")
def evidence_review(aid: int, body: EvidenceReviewIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    """Only an administrator can set the evidence status. The student's own routes have no field for it."""
    a = db.get(Asset, aid)
    if not a or a.category_id is None:
        raise HTTPException(404, "Asset not found")
    if body.decision in ("request_more", "reject") and len(body.note.strip()) < 5:
        raise HTTPException(422, "Explain to the student what is wrong or missing (at least 5 characters).")
    if body.decision == "approve" and body.accept_missing_invoice and len(body.note.strip()) < 5:
        raise HTTPException(422, "Approving without an invoice needs a note explaining why.")
    EV.apply_review(db, a, body.decision, body.note, user, body.accept_missing_invoice)
    db.commit()
    return v3.asset_v2(a, db)


@router.post("/v2/assets/{aid}/verify-invoice")
def verify_invoice(aid: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    a.invoice_verified = True
    S.audit(db, "asset", a.id, "invoice_verified_by_staff", {}, user)
    db.commit()
    return v3.asset_v2(a, db)


@router.get("/v2/assets/{aid}/quote")
def asset_quote(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own_asset(db, aid, user)
    cat = db.get(AssetCategory, a.category_id) if a.category_id else None
    if not cat:
        raise HTTPException(409, "This asset was not registered through the self-service flow.")
    t = I.category_terms(cat)
    chk = I.check_eligibility(t, a.declared_value, cat.active)
    return chk | {"quote": I.quote(t, a.declared_value) if chk["eligible"] else None, "active_policy": v3.active_policy_for(db, a.id) is not None}


class PurchaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_terms: bool


@router.post("/v2/assets/{aid}/purchase", status_code=201)
def purchase(aid: int, body: PurchaseIn, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    if not body.accept_terms:
        raise HTTPException(422, "You must accept the policy terms to continue.")
    enforce(db, PremiumTransaction.student_id, user.id, PremiumTransaction.paid_at, settings.PAYMENT_REQUESTS_PER_HOUR, 60, "payment requests")
    a = own_asset(db, aid, user)
    p = v3.purchase_policy(db, a, user)
    db.commit()
    return v3.policy_v2(p, db, detail=True)


# ------------------------------------------------------------------ policies & premiums
@router.get("/v2/policies")
def my_policies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Policy).where(Policy.category_id.is_not(None)).order_by(Policy.id.desc())
    if user.role == "student":
        q = q.where(Policy.student_id == user.id)
    return [v3.policy_v2(p, db) for p in db.scalars(q)]


@router.get("/v2/policies/{pid}")
def policy_detail(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Policy, pid)
    if not p or p.category_id is None or (user.role == "student" and p.student_id != user.id):
        raise HTTPException(404, "Policy not found")
    return v3.policy_v2(p, db, detail=True)


@router.post("/v2/policies/{pid}/pay-premium", status_code=201)
def pay_premium(pid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    p = db.get(Policy, pid)
    if not p or p.category_id is None or p.student_id != user.id:
        raise HTTPException(404, "Policy not found")
    enforce(db, PremiumTransaction.student_id, user.id, PremiumTransaction.paid_at, settings.PAYMENT_REQUESTS_PER_HOUR, 60, "payment requests")
    due = v3.next_due(db, p)
    if not due:
        raise HTTPException(409, "No premium is due right now.")
    t = v3.charge_premium(db, p, due, user)
    db.commit()
    return tx_dict(t, p)


def tx_dict(t: PremiumTransaction, p: Policy) -> dict:
    return {"id": t.id, "reference": t.reference, "policy_id": p.id, "policy_number": p.policy_number, "amount": float(t.amount), "period": t.period_label, "status": t.status,
            "method": t.method, "simulated": True, "paid_at": S.iso(t.paid_at), "student_id": t.student_id}


@router.get("/v2/payments")
def payments(user: User = Depends(current_user), db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=1000)):
    q = select(PremiumTransaction, Policy).join(Policy, Policy.id == PremiumTransaction.policy_id).order_by(PremiumTransaction.id.desc()).limit(limit)
    if user.role == "student":
        q = q.where(PremiumTransaction.student_id == user.id)
    return [tx_dict(t, p) for t, p in db.execute(q)]


# ------------------------------------------------------------------ claims
class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: int
    incident_date: date
    incident_type: str
    damage_type: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=2000)
    estimated_repair_cost: float | None = Field(default=None, gt=0, le=10_000_000)

    @field_validator("incident_type")
    @classmethod
    def _it(cls, v):
        if v not in S.INCIDENT_TYPES:
            raise ValueError(f"incident_type must be one of {S.INCIDENT_TYPES}")
        return v


def claim_access(db: Session, cid: int, user: User) -> Claim:
    c = db.get(Claim, cid)
    if not c or c.flow != "auto" or (user.role == "student" and c.claimant_id != user.id):
        raise HTTPException(404, "Claim not found")
    return c


@router.post("/v2/claims", status_code=201)
def create_claim(body: ClaimIn, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    """Never trusts the browser for the policy, coverage or amount: the policy is looked up from the owned asset."""
    enforce(db, Claim.claimant_id, user.id, Claim.created_at, settings.CLAIMS_PER_HOUR, 60, "claims submitted")
    a = own_asset(db, body.asset_id, user)
    pol = v3.active_policy_for(db, a.id)
    if pol is None:
        raise HTTPException(409, "This asset has no active policy, so a claim cannot be submitted.")
    cat = db.get(AssetCategory, pol.category_id)
    if body.damage_type not in (pol.terms_snapshot or {}).get("damage_types", cat.damage_types):
        raise HTTPException(422, f"damage_type must be one of {(pol.terms_snapshot or {}).get('damage_types', cat.damage_types)}")
    if body.incident_date > date.today():
        raise HTTPException(422, "The incident date cannot be in the future.")
    if len(body.description.strip()) < 15:
        raise HTTPException(422, "Please describe what happened in at least 15 characters.")
    dup = db.scalar(select(Claim.claim_number).where(Claim.asset_id == a.id, Claim.incident_date == body.incident_date, Claim.status.not_in(("Rejected", "Draft"))))
    if dup:
        raise HTTPException(409, f"A claim for this asset and incident date already exists ({dup}). Duplicate submissions are not accepted.")
    c = Claim(claim_number="TMP-" + uuid.uuid4().hex[:20], policy_id=pol.id, claimant_id=user.id, asset_id=a.id, incident_date=body.incident_date, incident_type=body.incident_type,
              incident_location="", description=body.description.strip(), status="Submitted", flow="auto", damage_type=body.damage_type,
              estimated_repair_cost=body.estimated_repair_cost, submitted_at=now(), policy_version_used=max((v.version for v in pol.versions), default=1))
    db.add(c); db.flush(); v3.new_claim_number(db, c)
    db.add(__import__("app.models", fromlist=["ClaimStatusHistory"]).ClaimStatusHistory(claim_id=c.id, from_status="", to_status="Submitted", reason="Claim submitted by student", changed_by=user.id))
    S.audit(db, "claim", c.id, "claim_created", {"flow": "auto", "asset_id": a.id}, user, claim_id=c.id)
    db.commit(); db.refresh(c)
    return v3.claim_v2(db, c, detail=True)


@router.post("/v2/claims/{cid}/images", status_code=201)
async def upload_claim_image(cid: int, file: UploadFile = File(...), user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    if c.status not in ("Submitted", "More Evidence Required"):
        raise HTTPException(409, f"Photos can no longer be added in status '{c.status}'.")
    enforce(db, ClaimImage.student_id, user.id, ClaimImage.uploaded_at, settings.UPLOADS_PER_HOUR, 60, "uploads")
    if (db.scalar(select(func.count()).select_from(ClaimImage).where(ClaimImage.claim_id == c.id)) or 0) >= settings.CLAIM_IMAGES_MAX:
        raise HTTPException(409, f"A claim can hold at most {settings.CLAIM_IMAGES_MAX} photos.")
    data, ext, ctype = await read_upload(file, IMG_EXT, "Photo")
    _im, bgr = vision.decode(data)
    name = store(data, ext)
    try:
        im = ClaimImage(claim_id=c.id, student_id=user.id, stored_name=name, original_name=_safe_name(file.filename), content_type=ctype, size_bytes=len(data), sha256=vision.sha256(data),
                        phash=vision.dhash(bgr), phash_dct=authenticity.phash_dct(bgr), width=bgr.shape[1], height=bgr.shape[0], quality={}, exif=vision.read_exif(data))
        db.add(im); db.flush()
        S.audit(db, "claim_image", im.id, "claim_image_uploaded", {"bytes": len(data), "sha256": im.sha256}, user, claim_id=c.id)
        db.commit()
    except Exception:
        db.rollback()
        (settings.UPLOAD_DIR / name).unlink(missing_ok=True)
        raise
    return {"id": im.id, "original_name": im.original_name, "width": im.width, "height": im.height}


@router.post("/v2/claims/{cid}/documents", status_code=201)
async def upload_claim_document(cid: int, file: UploadFile = File(...), user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    if c.status not in ("Submitted", "More Evidence Required"):
        raise HTTPException(409, f"Documents can no longer be added in status '{c.status}'.")
    enforce(db, Evidence.uploaded_by, user.id, Evidence.uploaded_at, settings.UPLOADS_PER_HOUR, 60, "uploads")
    if len(c.evidence) >= 5:
        raise HTTPException(409, "A claim can hold at most 5 supporting documents.")
    data, ext, ctype = await read_upload(file, DOC_EXT, "Document")
    e = Evidence(claim_id=c.id, doc_type="other", original_name=_safe_name(file.filename), stored_name=store(data, ext), content_type=ctype, size_bytes=len(data), uploaded_by=user.id)
    db.add(e); db.commit()
    return {"id": e.id, "original_name": e.original_name}


@router.get("/v2/claims/{cid}/images/{iid}/file")
def claim_image_file(cid: int, iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    im = db.get(ClaimImage, iid)
    if not im or im.claim_id != c.id:
        raise HTTPException(404, "Image not found")
    return send(im.stored_name, im.content_type, im.original_name)


@router.post("/v2/claims/{cid}/verify")
def verify_claim(cid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    c = claim_access(db, cid, user)
    if c.status not in ("Submitted", "More Evidence Required"):
        raise HTTPException(409, f"This claim is already '{c.status}' and cannot be verified again.")
    from datetime import timedelta
    recent = db.scalar(select(func.count()).select_from(AIVerificationReport).join(Claim, Claim.id == AIVerificationReport.claim_id)
                       .where(Claim.claimant_id == user.id, AIVerificationReport.created_at > now() - timedelta(minutes=10))) or 0
    if recent >= settings.AI_CALLS_PER_10_MIN_STUDENT:
        raise HTTPException(429, "Too many verification runs in a short time. Please wait a few minutes.", headers={"Retry-After": "600"})
    v3.run_verification_and_decision(db, c, user)
    db.commit(); db.refresh(c)
    return v3.claim_v2(db, c, detail=True)


@router.get("/v2/claims")
def list_claims(user: User = Depends(current_user), db: Session = Depends(get_db), status: str | None = Query(None, max_length=40), limit: int = Query(200, ge=1, le=500)):
    q = select(Claim).where(Claim.flow == "auto").order_by(Claim.id.desc()).limit(limit)
    if user.role == "student":
        q = q.where(Claim.claimant_id == user.id)
    if status:
        q = q.where(Claim.status == status)
    return [v3.claim_v2(db, c) for c in db.scalars(q)]


@router.get("/v2/claims/{cid}")
def get_claim(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return v3.claim_v2(db, claim_access(db, cid, user), detail=True)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("action")
    @classmethod
    def _a(cls, v):
        if v not in ("approve", "reject"):
            raise ValueError("action must be approve or reject")
        return v


@router.post("/v2/claims/{cid}/review")
def review_claim(cid: int, body: ReviewIn, user: User = Depends(require_roles("admin", "assessor")), db: Session = Depends(get_db)):
    """Exceptional-review path. Staff decide; the amount is still computed by the engine and capped by the frozen policy limits."""
    c = claim_access(db, cid, user)
    if c.status != "Exceptional Review Required":
        raise HTTPException(409, f"Only claims in 'Exceptional Review Required' can be reviewed (current: '{c.status}').")
    dec = db.scalar(select(ClaimDecision).where(ClaimDecision.claim_id == c.id).order_by(ClaimDecision.id.desc()))
    if body.action == "reject":
        db.add(ClaimDecision(claim_id=c.id, run=dec.run if dec else 1, outcome="Rejected", decided_by="staff", decided_by_user=user.id, checks=dec.checks if dec else [],
                             calculation=dec.calculation if dec else {}, payable_amount=None, reason=body.reason))
        c.decision_outcome, c.decision_reason, c.payable_amount = "Rejected", body.reason, None
        v3.set_status(db, c, "Rejected", f"Rejected after exceptional review: {body.reason}", user)
    else:
        hard = [x for x in (dec.checks if dec else []) if x["result"] == "FAIL"]
        if hard or not dec:
            raise HTTPException(409, "A hard policy rule failed for this claim; it cannot be approved.")
        policy = c.policy
        terms = policy.terms_snapshot
        paid_before = db.scalar(select(func.coalesce(func.sum(Claim.payable_amount), 0)).where(Claim.policy_id == policy.id, Claim.id != c.id, Claim.status.in_(v3.ACTIVE_CLAIM)))
        loss, _r, basis = v3.assessed_loss(terms, c, float(policy.purchase_value))
        calc = I.calculate_claim(terms, c.asset.purchase_date, c.incident_date, loss, paid_before) | {"basis": basis}
        if calc["payable"] <= 0:
            raise HTTPException(409, "Nothing is payable under the policy limits.")
        db.add(ClaimDecision(claim_id=c.id, run=dec.run, outcome="Approved", decided_by="staff", decided_by_user=user.id, checks=dec.checks, calculation=calc,
                             payable_amount=calc["payable"], reason=body.reason))
        c.decision_outcome = "Approved"
        v3.approve_and_settle(db, c, calc, f"Approved after exceptional review: {body.reason}", user)
    S.audit(db, "claim", c.id, "exceptional_review_decided", {"action": body.action, "reason": body.reason}, user, claim_id=c.id)
    db.commit(); db.refresh(c)
    return v3.claim_v2(db, c, detail=True)


# ------------------------------------------------------------------ AI status & analytics, dashboards
@router.get("/v2/ai/capabilities")
def ai_capabilities(user: User = Depends(current_user)):
    return verification.capabilities()


def _count(d: dict, k) -> None:
    if k:
        d[k] = d.get(k, 0) + 1


@router.get("/v2/ai/analytics")
def ai_analytics(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    """Every figure is either counted from stored records or read from the evaluation file. A metric that was never measured is reported as unavailable, never estimated."""
    reps = db.scalars(select(AIVerificationReport)).all()
    images = sum((r.quality or {}).get("total_count", 0) for r in reps)
    dist, modes, bands, serial, brandm, wf, ind, scores = {}, {}, {}, {}, {}, {}, {}, []
    for r in reps:
        modes[r.mode] = modes.get(r.mode, 0) + 1
        if not r.is_simulated:
            for d in (r.damage_detection or {}).get("detections", []):
                dist[d["damage_type"]] = dist.get(d["damage_type"], 0) + 1
        dmx = r.device_match or {}
        _count(bands, dmx.get("band"))
        if dmx.get("status") == "Computed" and dmx.get("best_score") is not None:
            scores.append(dmx["best_score"])
        _count(serial, (dmx.get("serial_check") or {}).get("status"))
        _count(brandm, (dmx.get("brand_model_check") or {}).get("status"))
        if not r.is_simulated:  # a simulated report is not a measurement of anything
            _count(wf, r.workflow_outcome or verification.workflow_for(r.outcome, r.route))
        for x in r.risk_indicators or []:
            _count(ind, x.get("code"))
    outcomes = {k: sum(1 for r in reps if r.outcome == k) for k in ("Evidence Supported", "More Evidence Required", "Evidence Inconsistent / Suspicious")}
    claims = db.scalars(select(Claim.damage_type).where(Claim.flow == "auto")).all()
    declared = {}
    for d in claims:
        declared[d] = declared.get(d, 0) + 1
    import json
    mp = settings.MODEL_DIR / "evaluation.json"
    try:
        metrics = json.loads(mp.read_text("utf-8")) if mp.is_file() else None
    except (OSError, ValueError):
        metrics = None
    ms = model_registry.damage_model_status()
    evaluation = model_registry.normalise_evaluation(metrics)
    try:  # written only by ai_training/evaluate_device_matching.py
        dmp = settings.MODEL_DIR / "device_match_evaluation.json"
        dm_eval = json.loads(dmp.read_text("utf-8")) if dmp.is_file() else None
    except (OSError, ValueError):
        dm_eval = None

    # ---- manual review statistics
    cl = select(func.count()).select_from(Claim).where(Claim.flow == "auto")
    staff_dec = dict(db.execute(select(ClaimDecision.outcome, func.count()).where(ClaimDecision.decided_by == "staff").group_by(ClaimDecision.outcome)).all())
    reviewed_ids = [r[0] for r in db.execute(select(ClaimDecision.claim_id).where(ClaimDecision.decided_by == "staff").distinct()).all()]
    hours = []
    if reviewed_ids:
        hist: dict[int, list] = {}
        for h in db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id.in_(reviewed_ids)).order_by(ClaimStatusHistory.id)):
            hist.setdefault(h.claim_id, []).append(h)
        for rows_ in hist.values():
            start_ = next((h.changed_at for h in rows_ if h.to_status == "Exceptional Review Required"), None)
            end_ = next((h.changed_at for h in rows_ if h.changed_by and h.to_status in ("Approved", "Rejected")), None)
            if start_ and end_ and end_ >= start_:
                hours.append((end_ - start_).total_seconds() / 3600)
    manual = {"waiting_for_staff": db.scalar(cl.where(Claim.status == "Exceptional Review Required")) or 0, "decided_by_staff": staff_dec,
              "average_hours_to_decision": round(sum(hours) / len(hours), 1) if hours else None, "decisions_with_timing": len(hours),
              "sent_to_manual_review": sum(wf.get(k, 0) for k in (verification.WF_SUSPICIOUS, verification.WF_UNABLE)),
              "approved_after_suspicious_outcome": db.scalar(cl.where(Claim.ai_workflow_outcome == verification.WF_SUSPICIOUS, Claim.status.in_(v3.ACTIVE_CLAIM))) or 0,
              "rejected_after_consistent_outcome": db.scalar(cl.where(Claim.ai_workflow_outcome == verification.WF_CONSISTENT, Claim.status == "Rejected")) or 0,
              "auto_approval_setting": settings.AUTO_APPROVAL}
    evid = dict(db.execute(select(Asset.evidence_status, func.count()).where(Asset.category_id.is_not(None)).group_by(Asset.evidence_status)).all())
    return {"reports": len(reps), "images_analyzed": images, "successful": outcomes["Evidence Supported"], "uncertain": outcomes["More Evidence Required"],
            "inconsistent": outcomes["Evidence Inconsistent / Suspicious"], "avg_processing_ms": round(sum(r.processing_ms for r in reps) / len(reps)) if reps else 0,
            "damage_distribution_detected": dist, "damage_distribution_declared": declared, "modes": modes, "simulated_reports": sum(1 for r in reps if r.is_simulated),
            "model_metrics": metrics, "model_metrics_note": None if metrics else "Not measured: no labelled evaluation set has been run. See docs/AI_VERIFICATION.md (evaluate script).",
            "damage_model": ms, "evaluation": evaluation,
            "workflow_outcomes": wf, "workflow_outcomes_note": "Counts reports from real verification runs only; simulated development reports are excluded.",
            "device_matching": {"reports_compared": sum(bands.values()), "bands": bands, "average_best_score": round(sum(scores) / len(scores), 3) if scores else None, "scores_measured": len(scores),
                                "serial_check": serial, "brand_model_check": brandm, "calibrated": dm_eval is not None,
                                "calibration": ({k: dm_eval.get(k) for k in ("generated_at", "pairs", "same_item_pairs", "different_item_pairs", "auc", "suggested", "currently_configured")} if dm_eval else None),
                                "note": ("Thresholds were measured on a labelled set of pairs (see the calibration record); that says nothing about devices, lighting or cameras unlike that set. " if dm_eval else
                                         "Thresholds are heuristic and have not been calibrated on labelled pairs. ") + "Counts show what the matcher reported, not how often it was right."},
            "authenticity_indicators": ind, "manual_review": manual, "evidence_review": {k: evid.get(k, 0) for k in EV.STATUSES},
            "capabilities": verification.capabilities()}


@router.get("/v2/dashboard")
def dashboard(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    pols = db.scalars(select(Policy).where(Policy.student_id == user.id, Policy.category_id.is_not(None), Policy.status == "Active")).all()
    assets = db.scalar(select(func.count()).select_from(Asset).where(Asset.owner_id == user.id, Asset.category_id.is_not(None))) or 0
    return {"active_policies": len(pols), "insured_assets": len(pols), "registered_assets": assets, "total_coverage": float(sum(p.max_coverage for p in pols)),
            "monthly_commitment": float(sum(p.monthly_premium for p in pols)), "premium_due": [{"policy_id": p.id, "policy_number": p.policy_number, "period": v3.next_due(db, p)} for p in pols if v3.next_due(db, p)],
            "recent_claims": [v3.claim_v2(db, c) for c in db.scalars(select(Claim).where(Claim.claimant_id == user.id, Claim.flow == "auto").order_by(Claim.id.desc()).limit(5))],
            "recent_transactions": [tx_dict(t, p) for t, p in db.execute(select(PremiumTransaction, Policy).join(Policy, Policy.id == PremiumTransaction.policy_id)
                                                                         .where(PremiumTransaction.student_id == user.id).order_by(PremiumTransaction.id.desc()).limit(5))]}


@router.get("/v2/admin/overview")
def admin_overview(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    cnt = lambda q: db.scalar(q) or 0
    cl = select(func.count()).select_from(Claim).where(Claim.flow == "auto")
    return {"students": cnt(select(func.count()).select_from(User).where(User.role == "student")), "active_policies": cnt(select(func.count()).select_from(Policy).where(Policy.status == "Active", Policy.category_id.is_not(None))),
            "insured_assets": cnt(select(func.count(func.distinct(Policy.id))).where(Policy.status == "Active", Policy.category_id.is_not(None))),
            "premium_revenue": float(cnt(select(func.coalesce(func.sum(PremiumTransaction.amount), 0)).where(PremiumTransaction.status == "Paid"))),
            "claims_received": cnt(cl), "claims_approved": cnt(cl.where(Claim.status.in_(v3.ACTIVE_CLAIM))), "claims_rejected": cnt(cl.where(Claim.status == "Rejected")),
            "pending_exceptional_reviews": cnt(cl.where(Claim.status == "Exceptional Review Required")), "more_evidence": cnt(cl.where(Claim.status == "More Evidence Required")),
            "pending_evidence_reviews": cnt(select(func.count()).select_from(Asset).where(Asset.category_id.is_not(None), Asset.evidence_status == "Pending review"))}


@router.get("/v2/admin/policies")
def admin_policies(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return [v3.policy_v2(p, db) | {"student_name": p.student.full_name} for p in db.scalars(select(Policy).where(Policy.category_id.is_not(None)).order_by(Policy.id.desc()))]
