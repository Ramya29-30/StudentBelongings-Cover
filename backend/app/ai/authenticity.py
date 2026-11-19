"""Image authenticity checks for registration and claim photographs.

Everything here is a RISK INDICATOR for a human reviewer. None of it proves that an image is genuine or fake, and nothing here rejects a claim.
The module is database-free: callers pass bytes and the fingerprints of earlier images.

What each check can and cannot tell you (also shown to administrators, see LIMITATIONS):
  sha256            exact byte-for-byte duplicate. Defeated by any re-save, crop, screenshot or messaging-app recompression.
  dhash + DCT hash  perceptual near-duplicate (resized / recompressed copies). Can false-match flat or very similar scenes and can be defeated by heavy edits.
  EXIF              camera metadata. Most messaging apps and screenshots strip it, so MISSING EXIF IS NORMAL and is never treated as a risk. Present EXIF can be edited.
  ELA               error-level analysis of JPEGs. Unreliable: re-saved, resized or heavily compressed photos produce uneven error levels without any manipulation.
  quality           classical blur / exposure / resolution measurements (see vision.assess_quality).
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime

import cv2
import numpy as np
from PIL import ExifTags, Image

from . import vision

LIMITATIONS = {
    "sha256": "Detects only byte-identical files. A re-saved, cropped, screenshotted or re-compressed copy has a different SHA-256.",
    "perceptual_hash": "Detects resized or re-compressed copies of the same picture. It can match very similar plain scenes and can be defeated by heavy edits.",
    "exif": "Camera metadata is often removed by messaging apps and screenshots, so missing metadata is normal and is NOT a sign of fraud. Metadata that is present can be edited.",
    "manipulation": "Error-level analysis is a weak, error-prone heuristic. Uneven error levels also come from resizing and repeated compression. It never proves editing.",
    "quality": "Blur, exposure and resolution are measured with classical image statistics, not machine learning.",
}
EDITOR_SOFTWARE = re.compile(r"photoshop|gimp|canva|snapseed|lightroom|pixlr|facetune|picsart|paint\.net|affinity|photoscape|fotor|stable diffusion|midjourney|dall", re.I)
_PHOTO_EXT = {"JPEG", "MPO"}


# ------------------------------------------------------------------ fingerprints
def phash_dct(bgr: np.ndarray) -> str:
    """64-bit DCT perceptual hash (hex). Complements dhash: the two agree on benign re-encodes and disagree more often on unrelated images."""
    g = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    low = cv2.dct(g)[:8, :8].flatten()
    med = float(np.median(low[1:]))  # ignore the DC term when choosing the threshold
    bits = low > med
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def fingerprints(data: bytes, bgr: np.ndarray) -> dict:
    return {"sha256": vision.sha256(data), "phash": vision.dhash(bgr), "phash_dct": phash_dct(bgr)}


# ------------------------------------------------------------------ EXIF
def inspect_exif(data: bytes) -> dict:
    """Richer than vision.read_exif (which keeps the stored subset). GPS coordinates are NOT returned: only whether they exist."""
    out = {"present": False, "camera": None, "software": None, "captured": None, "gps_present": False, "editing_software": False}
    try:
        with Image.open(io.BytesIO(data)) as im:
            raw = im.getexif()
            if not raw:
                return out
            sub = raw.get_ifd(0x8769)
            tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in list(raw.items()) + list(sub.items())}
            out["gps_present"] = bool(raw.get_ifd(0x8825))
    except Exception:
        return out
    out["present"] = True
    make, model = str(tags.get("Make", "")).strip(), str(tags.get("Model", "")).strip()
    out["camera"] = (f"{make} {model}".strip() or None)
    sw = str(tags.get("Software", "")).strip()[:60]
    out["software"] = sw or None
    out["editing_software"] = bool(sw and EDITOR_SOFTWARE.search(sw))
    raw_dt = str(tags.get("DateTimeOriginal") or tags.get("DateTime") or "")[:19]
    try:
        out["captured"] = datetime.strptime(raw_dt, "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        out["captured"] = None
    return out


# ------------------------------------------------------------------ error level analysis (weak heuristic)
def ela(data: bytes, quality: int = 90) -> dict:
    """Re-compress a JPEG and look at how unevenly the error is spread. Only meaningful for JPEG photographs; reported as a weak indicator."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in _PHOTO_EXT:
                return {"applicable": False, "reason": f"{im.format or 'unknown'} is not a JPEG, so error-level analysis does not apply.", "uneven": False}
            rgb = im.convert("RGB")
            if min(rgb.size) < 128:
                return {"applicable": False, "reason": "Image too small for error-level analysis.", "uneven": False}
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=quality)
            re_img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    except Exception:
        return {"applicable": False, "reason": "Could not run error-level analysis on this file.", "uneven": False}
    a, b = np.asarray(rgb, dtype=np.int16), np.asarray(re_img, dtype=np.int16)
    err = np.abs(a - b).max(axis=2).astype(np.float32)
    h, w = err.shape
    gh, gw = max(1, h // 16), max(1, w // 16)
    blocks = err[: gh * 16, : gw * 16].reshape(gh, 16, gw, 16).mean(axis=(1, 3)).flatten()
    med, p95 = float(np.median(blocks)), float(np.percentile(blocks, 95))
    ratio = p95 / med if med > 0.05 else 0.0
    uneven = bool(ratio > 4.0 and p95 > 6.0)
    return {"applicable": True, "mean_error": round(float(err.mean()), 2), "p95_over_median": round(ratio, 2), "uneven": uneven,
            "reason": ("Error levels are unusually uneven across the image. This is a weak signal: resizing and repeated compression do the same." if uneven else
                       "Error levels are spread evenly.")}


# ------------------------------------------------------------------ per-image analysis
def analyze_image(data: bytes, bgr: np.ndarray, name: str, *, quality: dict | None = None) -> dict:
    """Return the authenticity section for one image plus indicator candidates (info items never affect routing)."""
    fp = fingerprints(data, bgr)
    ex = inspect_exif(data)
    el = ela(data)
    h, w = bgr.shape[:2]
    notes: list[str] = []
    if not ex["present"]:
        notes.append("No camera metadata. This is normal for photos sent through messaging apps and for screenshots; it is not evidence of fraud.")
    if ex["editing_software"]:
        notes.append(f"The metadata names image-editing software ({ex['software']}). Editing is common and legitimate; a reviewer may want to look.")
    if el.get("uneven"):
        notes.append(el["reason"])
    fmt = None
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
    except Exception:
        pass
    if fmt == "PNG" and not ex["present"] and (w, h) in {(1170, 2532), (1179, 2556), (1284, 2778), (1080, 1920), (1080, 2340), (1080, 2400), (1920, 1080), (2560, 1440), (3840, 2160), (1440, 900), (1920, 1200)}:
        notes.append("The file looks like a screenshot (PNG, no camera metadata, common screen resolution). A screenshot is not a photograph of the item.")
    return {"image": name, **fp, "width": w, "height": h, "megapixels": round(w * h / 1e6, 2), "format": fmt, "exif": ex, "ela": el, "quality_score": (quality or {}).get("score"), "notes": notes}


def indicators_for(img: dict, *, incident: date | None, purchase: date | None, today: date) -> list[dict]:
    """Risk indicators for ONE image. Severities: low and medium raise review flags; missing EXIF yields none."""
    out: list[dict] = []
    cap = img["exif"].get("captured")
    if cap:
        taken = datetime.fromisoformat(cap).date()
        if incident and (incident - taken).days > 1:
            out.append({"code": "META-DATE", "severity": "medium", "text": f"{img['image']} was captured on {taken}, before the stated incident date {incident}."})
        if (taken - today).days > 1:
            out.append({"code": "META-FUTURE", "severity": "low", "text": f"{img['image']} has a capture date in the future ({taken}); the camera clock may be wrong."})
        if purchase and taken < purchase and not (incident and taken >= incident):
            out.append({"code": "META-PREPURCHASE", "severity": "medium", "text": f"{img['image']} was captured on {taken}, before the item's purchase date {purchase}."})
    if img["exif"].get("editing_software"):
        out.append({"code": "META-SOFTWARE", "severity": "low", "text": f"{img['image']} metadata names editing software ({img['exif'].get('software')})."})
    if img["ela"].get("uneven"):
        out.append({"code": "ELA-UNEVEN", "severity": "low", "text": f"{img['image']} shows uneven error levels (a weak manipulation indicator, often a false alarm)."})
    return out


# ------------------------------------------------------------------ duplicates against earlier images
def find_duplicates(images: list[dict], corpus: list[dict], *, student_id: int, claim_id: int, asset_id: int | None = None,
                    dhash_max: int = 5, dct_max: int = 8) -> tuple[dict, list[dict]]:
    """images: [{original_name, sha256, phash, phash_dct}]. corpus entries: {source: 'claim'|'registration', claim_id, asset_id, student_id, sha256, phash, phash_dct, label}.
    Entries without a SHA-256 (legacy rows whose fingerprints have not been computed) are skipped."""
    exact, near, reg_exact, reg_near = [], [], [], []

    def who(p: dict) -> str:
        return (p.get("label") or p.get("claim_number") or "an earlier submission") if p["student_id"] == student_id else "another student's records"

    for im in images:
        for p in corpus:
            if p.get("source", "claim") == "claim" and p.get("claim_id") == claim_id:
                continue
            if not p.get("sha256"):
                continue
            same_asset_reg = p.get("source") == "registration" and asset_id is not None and p.get("asset_id") == asset_id
            if im["sha256"] == p["sha256"]:
                rec = {"image": im["original_name"], "against": who(p), "same_student": p["student_id"] == student_id, "same_asset": same_asset_reg}
                (reg_exact if p.get("source") == "registration" else exact).append(rec)
                continue
            d1 = vision.hamming(im["phash"], p.get("phash", ""))
            d2 = vision.hamming(im.get("phash_dct", ""), p.get("phash_dct", "")) if im.get("phash_dct") and p.get("phash_dct") else None
            if d1 <= dhash_max and (d2 is None or d2 <= dct_max):
                rec = {"image": im["original_name"], "against": who(p), "same_student": p["student_id"] == student_id, "same_asset": same_asset_reg, "distance": d1, "dct_distance": d2}
                (reg_near if p.get("source") == "registration" else near).append(rec)
    risks: list[dict] = []
    for e in exact:
        risks.append({"code": "DUP-EXACT", "severity": "high", "text": f"{e['image']} is byte-identical to an image in {'claim ' if e['same_student'] else ''}{e['against']}."})
    for n in near:
        risks.append({"code": "DUP-NEAR", "severity": "medium", "text": f"{n['image']} is visually almost identical to an image in {'claim ' if n['same_student'] else ''}{n['against']} (hash distance {n['distance']})."})
    for e in reg_exact:
        if e["same_asset"]:
            txt = f"{e['image']} is byte-identical to this item's own registration photograph, so it cannot show new damage."
        else:
            txt = f"{e['image']} is byte-identical to a registration photograph of {'another of your items' if e['same_student'] else 'an item registered by another student'}."
        risks.append({"code": "DUP-REG-EXACT", "severity": "high", "text": txt})
    for n in reg_near:
        if n["same_asset"]:
            txt = f"{n['image']} is visually almost identical to this item's registration photograph (hash distance {n['distance']}); the registration photo shows the item before the loss."
        else:
            txt = f"{n['image']} is visually almost identical to a registration photograph of {'another of your items' if n['same_student'] else 'an item registered by another student'} (hash distance {n['distance']})."
        risks.append({"code": "DUP-REG-NEAR", "severity": "medium", "text": txt})
    seen: dict[str, str] = {}
    for im in images:
        if im["sha256"] in seen:
            risks.append({"code": "DUP-WITHIN", "severity": "medium", "text": f"{im['original_name']} and {seen[im['sha256']]} are the same file uploaded twice."})
        seen[im["sha256"]] = im["original_name"]
    any_exact = exact or reg_exact
    any_near = near or reg_near
    res = {"result": "Matching earlier image found" if any_exact else ("Similar earlier image found" if any_near else "No matching previous image found"),
           "exact_matches": exact, "near_matches": near, "registration_exact_matches": reg_exact, "registration_near_matches": reg_near,
           "compared_against": len([p for p in corpus if p.get("sha256")]),
           "note": "A match is a risk indicator for review, not proof of fraud: people legitimately re-send photos. Only byte-identical and visually near-identical copies are found; edited or re-photographed copies are not."}
    return res, risks


def summarise(images: list[dict], indicators: list[dict]) -> dict:
    return {"images": images, "indicator_count": len(indicators), "indicators": indicators, "limitations": LIMITATIONS,
            "missing_exif_policy": "Missing metadata is never treated as a risk indicator."}
