"""Registration evidence: what a student uploads when registering an item, the automatic observations shown to the reviewing administrator,
and the administrator's review decision. Policy purchase requires an APPROVED review (v3.purchase_policy).

The automatic observations (`flags`) are hints for a person. They never approve, reject or block anything by themselves.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services as S
from .ai import authenticity, device_match, vision
from .config import settings
from .models import Asset, AssetEvidence, User, now

KINDS = ("front_photo", "back_photo", "extra_photo", "invoice", "document")
PHOTO_KINDS = ("front_photo", "back_photo", "extra_photo")
SINGLE_KINDS = ("front_photo", "back_photo", "invoice")  # a new upload replaces the old one while the registration is still open
REQUIRED_KINDS = ("front_photo", "back_photo")
KIND_LABEL = {"front_photo": "Front photograph", "back_photo": "Back photograph", "extra_photo": "Additional photograph", "invoice": "Purchase invoice or receipt", "document": "Other document"}
OPEN_STATUSES = ("Pending review", "More evidence requested")
STATUSES = ("Pending review", "More evidence requested", "Approved", "Rejected")


# ------------------------------------------------------------------ queries
def rows(db: Session, asset_id: int) -> list[AssetEvidence]:
    return list(db.scalars(select(AssetEvidence).where(AssetEvidence.asset_id == asset_id).order_by(AssetEvidence.id)))


def missing_required(items: list[AssetEvidence]) -> list[str]:
    have = {e.kind for e in items}
    return [KIND_LABEL[k] for k in REQUIRED_KINDS if k not in have]


def fingerprint_row(e: AssetEvidence) -> bool:
    """Fill the fingerprints of a row copied from the legacy asset columns (migration 0006 leaves them empty). Returns True if the row changed."""
    if e.sha256:
        return False
    p = (settings.UPLOAD_DIR / e.stored_name).resolve()
    if settings.UPLOAD_DIR.resolve() not in p.parents or not p.is_file():
        return False
    data = p.read_bytes()
    e.sha256, e.size_bytes = vision.sha256(data), len(data)
    if e.content_type.startswith("image/"):
        try:
            _im, bgr = vision.decode(data)
        except vision.ImageError:
            return True
        e.phash, e.phash_dct = vision.dhash(bgr), authenticity.phash_dct(bgr)
        e.width, e.height = bgr.shape[1], bgr.shape[0]
        e.quality, e.exif = vision.assess_quality(bgr), vision.read_exif(data)
    return True


def ensure_fingerprints(db: Session, items: list[AssetEvidence]) -> None:
    changed = [fingerprint_row(e) for e in items]  # a list, not a generator: every row must be processed, not just the first that changes
    if any(changed):
        db.flush()


def corpus(db: Session, exclude_asset_id: int | None = None, photos_only: bool = True) -> list[dict]:
    """Fingerprints of registration files for duplicate detection. Legacy rows without a fingerprint are filled in first (bounded)."""
    q = select(AssetEvidence, Asset).join(Asset, Asset.id == AssetEvidence.asset_id).order_by(AssetEvidence.id.desc()).limit(5000)
    out, pending = [], []
    for e, a in db.execute(q):
        if exclude_asset_id is not None and a.id == exclude_asset_id:
            continue
        if photos_only and e.kind not in PHOTO_KINDS:
            continue
        if not e.sha256:
            pending.append(e)
            continue
        out.append({"source": "registration", "asset_id": a.id, "student_id": a.owner_id, "sha256": e.sha256, "phash": e.phash, "phash_dct": e.phash_dct, "label": f"the registration of {a.name}", "kind": e.kind})
    if pending:
        ensure_fingerprints(db, pending[:200])
        for e in pending[:200]:
            if e.sha256:
                a = db.get(Asset, e.asset_id)
                out.append({"source": "registration", "asset_id": a.id, "student_id": a.owner_id, "sha256": e.sha256, "phash": e.phash, "phash_dct": e.phash_dct, "label": f"the registration of {a.name}", "kind": e.kind})
    return out


# ------------------------------------------------------------------ recording a file
def record(db: Session, a: Asset, kind: str, data: bytes, stored_name: str, original_name: str, content_type: str, user: User, corp: list[dict] | None = None) -> AssetEvidence:
    """Create the evidence row (the file is already stored) with fingerprints and automatic observations. Replaces the old file of a SINGLE kind."""
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    e = AssetEvidence(asset_id=a.id, kind=kind, stored_name=stored_name, original_name=original_name, content_type=content_type, size_bytes=len(data), sha256=vision.sha256(data),
                      uploaded_by=user.id, review_status="Pending")
    flags: list[dict] = []
    if content_type.startswith("image/"):
        _im, bgr = vision.decode(data)
        q = vision.assess_quality(bgr)
        e.phash, e.phash_dct, e.width, e.height, e.quality, e.exif = vision.dhash(bgr), authenticity.phash_dct(bgr), bgr.shape[1], bgr.shape[0], q, vision.read_exif(data)
        if kind in PHOTO_KINDS:
            if not q["usable"]:
                flags.append({"code": "REG-QUALITY", "severity": "low", "text": f"{KIND_LABEL[kind]} may be hard to use: {'; '.join(q['issues'])}."})
            img = authenticity.analyze_image(data, bgr, KIND_LABEL[kind], quality=q)
            flags += authenticity.indicators_for(img, incident=None, purchase=a.purchase_date, today=date.today())
            for n in img["notes"]:
                if n.startswith("The file looks like a screenshot"):
                    flags.append({"code": "REG-SCREENSHOT", "severity": "medium", "text": f"{KIND_LABEL[kind]}: {n}"})
    for p in (corp if corp is not None else corpus(db, exclude_asset_id=a.id, photos_only=False)):
        if p["sha256"] == e.sha256:
            same = p["student_id"] == a.owner_id
            flags.append({"code": "REG-DUP-EXACT", "severity": "high", "text": f"This file is byte-identical to a file registered for {p['label']}" + (" (same student)." if same else " (a different student).")})
            break
        if e.phash and kind in PHOTO_KINDS and p["kind"] in PHOTO_KINDS and vision.hamming(e.phash, p["phash"]) <= settings.DUP_DHASH_MAX_DISTANCE and \
                (not (e.phash_dct and p["phash_dct"]) or vision.hamming(e.phash_dct, p["phash_dct"]) <= settings.DUP_PHASH_MAX_DISTANCE):
            flags.append({"code": "REG-DUP-NEAR", "severity": "medium", "text": f"This photograph is visually almost identical to one registered for {p['label']}."})
            break
    existing = rows(db, a.id)
    if kind in SINGLE_KINDS:
        for old in [x for x in existing if x.kind == kind]:
            remove(db, old, user, reason="replaced")
        existing = [x for x in existing if x.kind != kind]
    if kind in PHOTO_KINDS and e.phash:
        for o in existing:
            if o.kind in PHOTO_KINDS and o.phash and (o.sha256 == e.sha256 or (vision.hamming(o.phash, e.phash) <= settings.DUP_DHASH_MAX_DISTANCE)):
                flags.append({"code": "REG-SAME-VIEW", "severity": "medium", "text": f"{KIND_LABEL[kind]} is identical or nearly identical to the {KIND_LABEL[o.kind].lower()}, so the second view adds no information."})
                break
    e.flags = flags
    db.add(e)
    db.flush()
    S.audit(db, "asset_evidence", e.id, "evidence_uploaded", {"asset_id": a.id, "kind": kind, "bytes": len(data), "sha256": e.sha256, "flags": [f["code"] for f in flags]}, user)
    return e


def remove(db: Session, e: AssetEvidence, user: User, reason: str = "removed") -> None:
    p = (settings.UPLOAD_DIR / e.stored_name).resolve()
    if settings.UPLOAD_DIR.resolve() in p.parents:
        p.unlink(missing_ok=True)
    S.audit(db, "asset_evidence", e.id, f"evidence_{reason}", {"asset_id": e.asset_id, "kind": e.kind, "sha256": e.sha256}, user)
    db.delete(e)
    db.flush()


# ------------------------------------------------------------------ views
def evidence_dict(e: AssetEvidence, staff: bool = False) -> dict:
    d = {"id": e.id, "kind": e.kind, "label": KIND_LABEL.get(e.kind, e.kind), "original_name": e.original_name, "content_type": e.content_type, "size_bytes": e.size_bytes,
         "width": e.width, "height": e.height, "uploaded_at": S.iso(e.uploaded_at), "review_status": e.review_status, "is_image": e.content_type.startswith("image/"),
         "quality_issues": (e.quality or {}).get("issues", []), "file_url": f"/api/v2/assets/{e.asset_id}/evidence/{e.id}/file"}
    if staff:
        d |= {"sha256": e.sha256, "phash": e.phash, "flags": e.flags or [], "exif": e.exif or {}, "reviewed_at": S.iso(e.reviewed_at)}
    return d


def summary(db: Session, a: Asset, items: list[AssetEvidence] | None = None, staff: bool = False) -> dict:
    items = rows(db, a.id) if items is None else items
    missing = missing_required(items)
    has_invoice = any(e.kind == "invoice" for e in items)
    if a.evidence_status == "Approved":
        reason = ""
    elif a.evidence_status == "Rejected":
        reason = "The registration evidence was rejected by an administrator." + (f" Reason: {a.evidence_review_note}" if a.evidence_review_note else "")
    elif a.evidence_status == "More evidence requested":
        reason = "An administrator asked for more evidence." + (f" {a.evidence_review_note}" if a.evidence_review_note else "")
    else:
        reason = "The registration evidence is waiting for an administrator's review. A policy can be bought once it is approved."
    out = {"status": a.evidence_status, "note": a.evidence_review_note, "reviewed_at": S.iso(a.evidence_reviewed_at), "missing_required": missing, "has_invoice": has_invoice,
           "counts": {k: sum(1 for e in items if e.kind == k) for k in KINDS}, "can_purchase": a.evidence_status == "Approved", "reason": reason,
           "can_add": a.evidence_status in OPEN_STATUSES, "files": [evidence_dict(e, staff) for e in items]}
    note = device_match.imei_note(a.serial_number) if a.category == "Smartphone" else None
    if staff and note:
        out["identifier_note"] = note
    return out


# ------------------------------------------------------------------ administrator review
def apply_review(db: Session, a: Asset, decision: str, note: str, admin: User, accept_missing_invoice: bool = False) -> None:
    from . import v3  # local import: v3 imports this module
    if v3.active_policy_for(db, a.id):
        raise HTTPException(409, "This asset already has an active policy, so its registration evidence can no longer be re-reviewed.")
    items = rows(db, a.id)
    ensure_fingerprints(db, items)
    before = a.evidence_status
    if decision == "approve":
        miss = missing_required(items)
        if miss:
            raise HTTPException(409, "Cannot approve: required evidence is missing (" + ", ".join(miss) + "). Ask the student for it first.")
        if not any(e.kind == "invoice" for e in items) and not accept_missing_invoice:
            raise HTTPException(409, "No invoice or receipt was provided. Tick 'accept missing invoice' and explain why in the note to approve without one.")
        a.evidence_status = "Approved"
        for e in items:
            e.review_status, e.reviewed_by, e.reviewed_at = "Accepted", admin.id, now()
        a.invoice_verified = any(e.kind == "invoice" for e in items)
    elif decision == "request_more":
        a.evidence_status = "More evidence requested"
        a.invoice_verified = False
    elif decision == "reject":
        a.evidence_status = "Rejected"
        a.invoice_verified = False
        for e in items:
            e.review_status, e.reviewed_by, e.reviewed_at = "Rejected", admin.id, now()
    else:
        raise HTTPException(422, "decision must be approve, request_more or reject")
    a.evidence_reviewed_by, a.evidence_reviewed_at, a.evidence_review_note = admin.id, now(), note.strip()[:500]
    S.audit(db, "asset", a.id, "evidence_review_decided", {"decision": decision, "from": before, "to": a.evidence_status, "note": note.strip()[:300],
                                                            "accepted_missing_invoice": bool(accept_missing_invoice and not any(e.kind == "invoice" for e in items)),
                                                            "files": [e.id for e in items]}, admin)
