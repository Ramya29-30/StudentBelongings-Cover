"""Compare claim photographs with the photographs registered for the insured item.

METHOD (classical computer vision, no learned embedding is shipped):
  1. optionally crop each photo to the detected device (COCO detector) so the background counts for less;
  2. extract ORB keypoints;
  3. match them with a ratio test and keep only matches that agree on ONE geometric transform (RANSAC homography);
  4. the number and share of geometrically consistent matches gives a 0..1 score.
Visible serial / IMEI / brand / model text is compared only when a vision-language model is configured to read it; otherwise those checks say "Not checked".

WHAT THIS CAN AND CANNOT SHOW (repeated in every report):
  * Many consistent keypoints on a rigid surface (a logo, camera module, port layout, label) is real evidence that the photos show the same MODEL of object
    from compatible viewpoints, and mild evidence for the same unit.
  * It cannot prove that two photos show the same PHYSICAL device: two units of the same model look alike, and a stranger can photograph the same model.
  * A low score is NOT proof of a different device: close-ups, a different side, glare, a cracked screen or a changed background all lower it.
  * Thresholds are heuristic and uncalibrated until measured on labelled pairs (ai_training/evaluate_device_matching.py).
The result is never worded as "same device"; it is worded as agreement or lack of agreement of visible features.
"""
from __future__ import annotations

import re
from typing import Callable

import cv2
import numpy as np

METHOD = "ORB keypoint matching with RANSAC homography on device crops (classical computer vision; not a learned embedding)"
MIN_INLIERS = 12
LIMITATIONS = [
    "Agreement of visible features supports, but cannot prove, that two photos show the same physical device; two units of one model look alike.",
    "A weak result is not proof of a different device: close-ups, another side of the item, glare, damage or a different background all lower the score.",
    "Thresholds are heuristic and have not been calibrated on labelled data for this deployment.",
    "Serial, IMEI, brand and model text is only compared when a vision-language model is configured to read it, and such readings can be wrong.",
]
BAND_STRONG, BAND_PARTIAL, BAND_WEAK = "Strong feature agreement", "Partial feature agreement", "Weak or no feature agreement"
BAND_NODETAIL, BAND_NOREG, BAND_NOTRUN = "Not enough detail to compare", "No registered photographs", "Not run"


# ------------------------------------------------------------------ features
def _prep(bgr: np.ndarray, max_side: int = 800) -> np.ndarray:
    h, w = bgr.shape[:2]
    s = max_side / max(h, w)
    g = cv2.cvtColor(cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr, cv2.COLOR_BGR2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


def crop_to_box(bgr: np.ndarray, box: tuple[float, float, float, float] | None, margin: float = 0.05) -> tuple[np.ndarray, bool]:
    if not box:
        return bgr, False
    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = box
    if (x2 - x1) * (y2 - y1) < 0.08:
        return bgr, False
    x1, y1, x2, y2 = max(0, x1 - margin), max(0, y1 - margin), min(1, x2 + margin), min(1, y2 + margin)
    c = bgr[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
    return (c, True) if c.size and min(c.shape[:2]) >= 120 else (bgr, False)


def extract(bgr: np.ndarray):
    orb = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8, fastThreshold=10)
    kp, des = orb.detectAndCompute(_prep(bgr), None)
    return kp or [], des


def match_features(f1, f2) -> dict:
    """Return counts and a 0..1 score for one pair of (keypoints, descriptors)."""
    (kp1, d1), (kp2, d2) = f1, f2
    base = {"keypoints": [len(kp1), len(kp2)], "good_matches": 0, "inliers": 0, "score": 0.0, "geometry_ok": False}
    if d1 is None or d2 is None or len(kp1) < 8 or len(kp2) < 8:
        return base
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    base["good_matches"] = len(good)
    if len(good) < 8:
        return base
    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return base
    inl = int(mask.sum())
    # reject degenerate transforms (a real rigid object does not collapse, flip inside out or explode)
    xs, ys = src[:, 0, 0], src[:, 0, 1]
    corners = np.float32([[xs.min(), ys.min()], [xs.max(), ys.min()], [xs.max(), ys.max()], [xs.min(), ys.max()]]).reshape(-1, 1, 2)
    try:
        poly = cv2.perspectiveTransform(corners, H).reshape(-1, 2).astype(np.float32)
        area_src = float((xs.max() - xs.min()) * (ys.max() - ys.min())) or 1.0
        ratio = abs(float(cv2.contourArea(poly))) / area_src
        ok = bool(cv2.isContourConvex(poly)) and 0.05 <= ratio <= 20
    except cv2.error:
        ok = False
    base["inliers"], base["geometry_ok"] = inl, ok
    if inl >= MIN_INLIERS and ok:
        count = min(1.0, (inl - MIN_INLIERS) / 48.0)
        share = min(1.0, (inl / max(1, len(good))) / 0.6)
        base["score"] = round(0.7 * count + 0.3 * share, 3)
    return base


# ------------------------------------------------------------------ identifiers (only when a vision-language model reads the photo)
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits][::-1]
    return sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


def imei_note(value: str) -> str | None:
    """Registration-time observation about an entered value that looks like an IMEI. Informational: a wrong checksum is a typing hint, not fraud."""
    v = re.sub(r"[\s-]", "", value or "")
    if v.isdigit() and len(v) == 15:
        return None if luhn_ok(v) else "The 15-digit IMEI fails the standard checksum (Luhn); it may have a typing error."
    return None


def compare_identifiers(registered: dict, readings: list[dict]) -> tuple[dict, dict]:
    """readings: [{brand_seen, model_seen, serial_text, legible}] from the vision model. Returns (serial_check, brand_model_check)."""
    method = "vision-language model reading visible text (self-reported; it can misread characters)"
    if not readings:
        nc = {"status": "Not checked", "detail": "No vision-language model is configured to read text in photographs.", "method": None}
        return dict(nc), dict(nc)
    reg_serial = _norm(registered.get("serial", ""))
    seen_serials = [_norm(r.get("serial_text", "")) for r in readings if r.get("legible")]
    seen_serials = [s for s in seen_serials if len(s) >= 6]
    if len(reg_serial) < 5:
        serial = {"status": "Not checked", "detail": "The registered identifier is too short to compare.", "method": method}
    elif not seen_serials:
        serial = {"status": "Not legible", "detail": "No serial number or IMEI could be read in the claim photographs (normal: it is usually not visible).", "method": method}
    elif any(s == reg_serial or s in reg_serial or reg_serial in s for s in seen_serials):
        serial = {"status": "Matches", "detail": "A serial number or IMEI visible in a claim photograph matches the registered one.", "method": method}
    else:
        serial = {"status": "Differs", "detail": "A serial number or IMEI read from a claim photograph differs from the registered one. Readings can be wrong: a person should compare the photo.", "method": method}
    brands = [_norm(r.get("brand_seen", "")) for r in readings if r.get("legible")]
    models = [_norm(r.get("model_seen", "")) for r in readings if r.get("legible")]
    rb = _norm(registered.get("brand", ""))
    rm_tokens = [t for t in re.findall(r"[a-z0-9]{2,}", (registered.get("model", "") or "").lower())]
    sb = [b for b in brands if len(b) >= 2]
    sm = [m for m in models if len(m) >= 2]
    if not sb and not sm:
        bm = {"status": "Not legible", "detail": "No brand or model text could be read in the claim photographs.", "method": method}
    else:
        brand_ok = (not sb) or any(b in rb or rb in b for b in sb)
        model_ok = (not sm) or not rm_tokens or any(any(t in m for t in rm_tokens) for m in sm)
        bm = ({"status": "Matches", "detail": "The brand and model text visible in the photographs is consistent with the registration.", "method": method} if brand_ok and model_ok else
              {"status": "Differs", "detail": "The brand or model text read from the photographs differs from the registration. Readings can be wrong: a person should compare the photo.", "method": method})
    return serial, bm


# ------------------------------------------------------------------ main comparison
def compare(claim: list[tuple[int, str, np.ndarray]], refs: list[dict], *, registered: dict, locate: Callable[[np.ndarray], tuple | None] | None = None,
            readings: list[dict] | None = None, strong: float = 0.55, partial: float = 0.25, min_keypoints: int = 40) -> dict:
    """claim: [(index, name, bgr)]; refs: [{kind, label, bgr}] (photographs only). Returns the device_match section of the report."""
    base = {"method": METHOD, "limitations": LIMITATIONS, "thresholds": {"strong": strong, "partial": partial, "note": "Heuristic, uncalibrated."},
            "pairs": [], "best_score": None, "registered_photos_used": [r["label"] for r in refs]}
    if not claim:
        return base | {"status": "Not run", "band": BAND_NOTRUN, "conclusion": "No usable claim photograph was available to compare.", "supporting_evidence": []}
    if not refs:
        return base | {"status": "Unavailable", "band": BAND_NOREG, "conclusion": "No registration photograph is stored for this item, so the claim photographs cannot be compared with it.", "supporting_evidence": []}
    prepared_ref, prepared_claim = [], []
    for r in refs:
        box = locate(r["bgr"]) if locate else None
        img, cropped = crop_to_box(r["bgr"], box)
        prepared_ref.append((r, extract(img), cropped, box))
    for idx, name, bgr in claim:
        box = locate(bgr) if locate else None
        img, cropped = crop_to_box(bgr, box)
        prepared_claim.append((idx, name, extract(img), cropped, box))
    pairs, best, max_kp = [], None, 0
    for idx, name, fc, cc, cbox in prepared_claim:
        for r, fr, rc, rbox in prepared_ref:
            m = match_features(fc, fr)
            max_kp = max(max_kp, min(len(fc[0]), len(fr[0])))
            rec = {"claim_image": name, "claim_index": idx, "reference": r["label"], **m, "cropped_claim": cc, "cropped_reference": rc}
            pairs.append(rec)
            if best is None or rec["score"] > best["score"] or (rec["score"] == best["score"] and rec["inliers"] > best["inliers"]):
                best = rec
    pairs.sort(key=lambda p: (-p["score"], -p["inliers"]))
    structural, notes = {}, []
    boxes_c = [t[4] for t in prepared_claim if t[4]]
    boxes_r = [t[3] for t in prepared_ref if t[3]]
    if boxes_c and boxes_r:
        def ar(b):
            w, h = b[2] - b[0], b[3] - b[1]
            return min(w, h) / max(w, h) if max(w, h) > 0 else 0
        diff = abs(float(np.median([ar(b) for b in boxes_c])) - float(np.median([ar(b) for b in boxes_r])))
        structural = {"aspect_ratio_difference": round(diff, 3), "note": "Difference in the outline proportions of the detected device (informational)."}
        if diff > 0.3:
            notes.append("The outline proportions of the device differ noticeably between the claim and registration photos (a different view, a folded device or a different item).")
    if max_kp < min_keypoints:
        band, status = BAND_NODETAIL, "Computed"
        concl = "At least one image had too little visible detail (fewer than the minimum number of keypoints) for a meaningful comparison. Ask for a sharper, closer photo of the whole item."
    else:
        s = best["score"] if best else 0.0
        status = "Computed"
        band = BAND_STRONG if s >= strong else BAND_PARTIAL if s >= partial else BAND_WEAK
        concl = {BAND_STRONG: f"Visible features in the claim photograph agree with the registered photograph ({best['inliers']} geometrically consistent keypoints). This supports, but does not prove, that the photos show the same item.",
                 BAND_PARTIAL: f"Some visible features agree ({best['inliers']} consistent keypoints) but not enough to be confident. This often happens with a different angle or a close-up.",
                 BAND_WEAK: "Few or no visible features agree with the registered photographs. This can be caused by a different view, a close-up, glare, damage or a changed background; it is not proof of a different item."}[band]
    if best and best["score"] > 0:
        notes.insert(0, f"Best agreement: {best['claim_image']} against the registered {best['reference']} ({best['inliers']} consistent keypoints out of {best['good_matches']} candidate matches).")
    serial, bm = compare_identifiers(registered, readings or [])
    return base | {"status": status, "band": band, "best_score": best["score"] if best else None, "pairs": pairs[:12], "structural": structural,
                   "serial_check": serial, "brand_model_check": bm, "conclusion": concl, "supporting_evidence": notes}
