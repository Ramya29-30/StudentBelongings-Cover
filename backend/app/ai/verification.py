"""Explainable AI evidence verification for damage claims (stages 2-8 of the product spec).

This module only ASSESSES EVIDENCE. It never approves, rejects or prices a claim: the policy-rule engine (engine/decision.py) does that.
It is database-free: the router passes in image bytes and the fingerprints of earlier submissions.

Modes (the report always says which one produced it):
  onnx_model            asset identification with the shipped COCO detector; damage from a trained ONNX damage model (if installed)
  vision_language_model damage observations from a configured vision-capable LLM provider (self-reported, uncalibrated confidence)
  limited               image quality, duplicates, metadata and text checks are real; damage could NOT be verified -> routed to staff review
  development_simulation AI_VERIFY_MODE=dev_simulation: asset and damage are ASSUMED from the claim form so the workflow can be demonstrated
                        without a model. Nothing is detected. Every screen and report is labelled; forbidden in production.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime

from pydantic import BaseModel, Field

from ..config import settings
from . import authenticity, device_match, service, vision

SUPPORTED, MORE, INCONSISTENT = "Evidence Supported", "More Evidence Required", "Evidence Inconsistent / Suspicious"
# Four-way workflow outcome shown to students and staff (the three legacy values above still drive the policy engine).
WF_CONSISTENT, WF_MORE = "Evidence appears consistent", "More evidence required"
WF_SUSPICIOUS, WF_UNABLE = "Suspicious evidence - manual review", "Unable to verify - manual review"
WORKFLOW_OUTCOMES = (WF_CONSISTENT, WF_MORE, WF_SUSPICIOUS, WF_UNABLE)


def workflow_for(outcome: str, route: str) -> str:
    if outcome == SUPPORTED:
        return WF_CONSISTENT
    if outcome == INCONSISTENT:
        return WF_SUSPICIOUS
    return WF_MORE if route == "more_evidence" else WF_UNABLE
ASSET_WORDS = {"Laptop": ("laptop", "notebook", "macbook", "chromebook"), "Smartphone": ("phone", "mobile", "smartphone", "iphone", "android", "handset"),
               "Tablet": ("tablet", "ipad"), "Earbuds": ("earbud", "earbuds", "earphone", "earphones", "airpods", "buds", "earpiece"),
               "Bicycle": ("bicycle", "bike", "cycle"), "Smartwatch": ("smartwatch", "watch", "wristband")}
DAMAGE_WORDS = {"screen": ("screen", "display", "crack", "cracked", "shatter", "shattered", "glass", "lcd", "touch"), "body": ("body", "casing", "case", "chassis", "dent", "dented", "bent", "broken", "scratch", "frame"),
                "lens": ("camera", "lens"), "keyboard": ("keyboard", "key", "keys"), "hinge": ("hinge", "hinges", "lid"), "wheel": ("wheel", "tyre", "tire", "rim", "spoke"),
                "strap": ("strap", "band"), "missing": ("missing", "lost", "fell out")}
DAMAGE_FAMILY = {"cracked screen": "screen", "broken screen": "screen", "broken display": "screen", "cracked display": "screen", "damaged body": "body", "cracked body": "body",
                 "visible external damage": "body", "visible physical damage": "body", "broken casing": "body", "broken body": "body", "physical damage": "body",
                 "camera lens damage": "lens", "damaged keyboard": "keyboard", "broken hinge": "hinge", "damaged hinge": "hinge", "hinge damage": "hinge", "damaged wheels": "wheel", "damaged wheel": "wheel", "bent components": "body", "broken frame": "body",
                 "strap damage": "strap", "missing components": "missing"}


def norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (s or "").strip().lower())


def family(damage: str) -> str:
    return DAMAGE_FAMILY.get(norm(damage), "")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def resolve_allowed(label: str, allowed: list[str]) -> str | None:
    """Map a detector class name to one of the category's claimable damage types: exact (ignoring case/spacing) first, else the single allowed type
    in the same damage family (so a model class 'Cracked screen' still counts for a laptop category that lists 'Broken screen')."""
    exact = {norm(a): a for a in allowed}
    if norm(label) in exact:
        return exact[norm(label)]
    fam = family(label)
    if not fam:
        return None
    same = [a for a in allowed if family(a) == fam]
    return same[0] if len(same) == 1 else None


class VLMIdentifiers(BaseModel):
    brand_seen: str = Field(default="", max_length=60)
    model_seen: str = Field(default="", max_length=80)
    serial_text: str = Field(default="", max_length=60)
    legible: bool = False


class VLMDamage(BaseModel):
    damage_type: str = Field(max_length=60)
    confidence: float = Field(ge=0, le=1)
    location: str = Field(default="", max_length=100)


class VLMObservation(BaseModel):
    asset_seen: str = Field(max_length=40)
    asset_confidence: float = Field(ge=0, le=1)
    visible_damage: list[VLMDamage] = Field(default_factory=list, max_length=6)
    notes: str = Field(default="", max_length=400)


def capabilities() -> dict:
    st = service.status()
    asset = vision.get_detector("asset")
    dmg = vision.get_detector("damage")
    return {"mode_setting": settings.AI_VERIFY_MODE, "asset_model": asset.info() if asset else None, "damage_model": dmg.info() if dmg else None,
            "vision_language_model": bool(st["vision_available"]), "provider": st["provider"],
            "effective_mode": ("development_simulation" if settings.AI_VERIFY_MODE == "dev_simulation" else
                               "onnx_model" if dmg else "vision_language_model" if st["vision_available"] else "limited"),
            "supported_asset_identification": sorted(vision.COCO_ASSET_LABELS.values()) if asset else [],
            "device_matching": {"available": True, "method": device_match.METHOD, "serial_and_brand_reading": bool(st["vision_available"]),
                                "thresholds": {"strong": settings.DEVICE_MATCH_STRONG, "partial": settings.DEVICE_MATCH_PARTIAL, "calibrated": False}},
            "auto_approval": settings.AUTO_APPROVAL,
            "note": ("Development simulation is ON: asset and damage are assumed from the claim form, not detected." if settings.AI_VERIFY_MODE == "dev_simulation" else
                     "No damage model or vision provider is configured: damage cannot be verified automatically and claims go to staff review." if not (dmg or st["vision_available"]) else "")}


# ------------------------------------------------------------------ stage 3: asset identification
def identify_asset(category: str, usable: list[tuple[int, object]], mode: str) -> dict:
    if mode == "development_simulation":
        return {"status": "Simulated", "detected": category, "confidence": None, "match": "Consistent (assumed)", "method": "assumed from the claim form (development simulation)",
                "explanation": "Development simulation: no detector ran. The insured category was assumed."}
    det = vision.get_detector("asset")
    if det is None:
        return {"status": "Unable to verify", "detected": None, "confidence": None, "match": "Unable to verify", "method": None,
                "explanation": f"The asset detector model ({settings.ASSET_MODEL_FILE}) is not installed."}
    best: dict[str, tuple[float, float]] = {}
    all_labels = []
    for _i, bgr in usable:
        for d in det.predict(bgr, min_conf=0.25):
            all_labels.append(d.label)
            cat = vision.COCO_ASSET_LABELS.get(d.label)
            if cat:
                area = (d.box[2] - d.box[0]) * (d.box[3] - d.box[1])
                if d.confidence > best.get(cat, (0, 0))[0]:
                    best[cat] = (d.confidence, area)
    covered = category in vision.COCO_ASSET_LABELS.values()
    if not best:
        why = ("The detector found no laptop, phone or bicycle in the photos." if covered else
               f"The detector only knows laptops, phones and bicycles; it has no class for {category.lower()}, so the category cannot be checked from the image.")
        return {"status": "Unable to verify", "detected": None, "confidence": None, "match": "Unable to verify", "method": f"{det.info()['file']} (COCO, 80 classes)", "explanation": why}
    top_cat, (top_conf, top_area) = max(best.items(), key=lambda kv: kv[1][0])
    if category in best and best[category][0] >= 0.35:
        return {"status": "Detected", "detected": category, "confidence": round(best[category][0], 3), "match": "Consistent", "method": f"{det.info()['file']} (COCO, 80 classes)",
                "explanation": f"A {category.lower()} was detected with {best[category][0]:.0%} confidence."}
    if category == "Tablet" and top_cat in ("Laptop", "Smartphone"):
        return {"status": "Unable to verify", "detected": top_cat, "confidence": round(top_conf, 3), "match": "Unable to verify", "method": f"{det.info()['file']} (COCO, 80 classes)",
                "explanation": f"The detector has no tablet class and reported a {top_cat.lower()}-like object ({top_conf:.0%}); tablets are often mistaken for these. Not treated as a mismatch."}
    if top_conf >= 0.6 and top_area >= 0.2:
        return {"status": "Detected", "detected": top_cat, "confidence": round(top_conf, 3), "match": "Inconsistent", "method": f"{det.info()['file']} (COCO, 80 classes)",
                "explanation": f"The main object looks like a {top_cat.lower()} ({top_conf:.0%}), not the insured {category.lower()}."}
    return {"status": "Unable to verify", "detected": top_cat, "confidence": round(top_conf, 3), "match": "Unable to verify", "method": f"{det.info()['file']} (COCO, 80 classes)",
            "explanation": f"A weak {top_cat.lower()} detection ({top_conf:.0%}) is not enough to confirm or contradict the insured {category.lower()}."}


# ------------------------------------------------------------------ stage 4: damage detection
def detect_damage(category: str, declared_damage: str, allowed: list[str], usable: list[tuple[int, object]], images_raw: list[tuple[int, bytes, str]], mode: str, description: str) -> dict:
    if mode == "development_simulation":
        return {"status": "Simulated", "method": "assumed from the claim form (development simulation)", "detections": [{"damage_type": declared_damage, "confidence": None, "box": None, "source": "simulation"}],
                "explanation": "Development simulation: no damage model ran. The declared damage type was assumed."}
    dmg = vision.get_detector("damage")
    if dmg is not None:
        found = []
        for idx, bgr in usable:
            for d in dmg.predict(bgr):
                lab = resolve_allowed(d.label, allowed)
                if lab:
                    found.append({"damage_type": lab, "confidence": round(d.confidence, 3), "box": [round(v, 4) for v in d.box], "image_index": idx, "source": dmg.info()["file"]})
        found.sort(key=lambda x: -x["confidence"])
        return {"status": "Detected" if found else "No damage detected", "method": f"trained ONNX damage detector ({dmg.info()['file']}, sha256 {dmg.info()['sha256']})", "detections": found,
                "explanation": ("Detected: " + ", ".join(f"{f['damage_type']} ({f['confidence']:.0%})" for f in found[:4]) + ".") if found else
                               "The damage model found no damage of the supported types in the usable photos."}
    st = service.status()
    if st["vision_available"] and images_raw:
        try:
            obs, meta = service.call_structured(VLMObservation, (f"Insured asset category: {category}. Allowed damage types: {', '.join(allowed)}. Claimant text: {service._untrusted(description)}\n"
                                                                  "Look only at the photo. Report the asset you see and ONLY visible damage from the allowed list. If none is visible, return an empty list. Do not guess."),
                                                (images_raw[0][1], images_raw[0][2]))
            allowed_n = {norm(a): a for a in allowed}
            found = [{"damage_type": allowed_n[norm(d.damage_type)], "confidence": round(d.confidence, 3), "box": None, "source": "vision-language model (self-reported)"} for d in obs.visible_damage if norm(d.damage_type) in allowed_n]
            return {"status": "Detected" if found else "No damage detected", "method": f"vision-language model {meta.get('model')} (confidence is self-reported and uncalibrated; no bounding boxes)",
                    "detections": found, "asset_seen": obs.asset_seen, "asset_seen_confidence": obs.asset_confidence, "notes": obs.notes,
                    "explanation": ("The vision model reports: " + ", ".join(f"{f['damage_type']} ({f['confidence']:.0%})" for f in found) + ".") if found else "The vision model reported no visible damage of the supported types."}
        except service.AIUnavailable as e:
            return {"status": "Unable to verify", "method": "vision-language model", "detections": [], "explanation": f"The vision provider could not analyse the image: {e}"}
    return {"status": "Unable to verify", "method": None, "detections": [], "capability_missing": True,
            "explanation": "No trained damage model and no vision provider are configured, so damage cannot be verified automatically. The claim goes to staff review rather than being rejected."}


# ------------------------------------------------------------------ stage 5: description comparison (rule-based text check)
def compare_description(category: str, declared_damage: str, description: str, damage: dict, asset: dict, mode: str) -> dict:
    words = _words(description)
    named = {c for c, ws in ASSET_WORDS.items() if words & set(ws)}
    other = named - {category}
    notes, result = [], "Consistent"
    if other and category not in named:
        result = "Inconsistent"
        notes.append(f"The description talks about a {', '.join(sorted(o.lower() for o in other))} but the insured asset is a {category.lower()}.")
    det = damage.get("detections") or []
    desc_fams = {f for f, ws in DAMAGE_WORDS.items() if words & set(ws)}
    declared_fam = family(declared_damage)
    if mode == "development_simulation":
        notes.append("Development simulation: image content was not compared.")
    elif det:
        det_fams = {family(d["damage_type"]) for d in det}
        if declared_fam and declared_fam not in det_fams:
            result = "Inconsistent"
            notes.append(f"Declared damage ({declared_damage}) differs from the detected damage ({', '.join(sorted({d['damage_type'] for d in det}))}).")
        elif desc_fams and not (desc_fams & det_fams) and result == "Consistent":
            result = "Inconsistent"
            notes.append("The damage described in the text is not what was detected in the photos.")
        elif result == "Consistent":
            notes.append("The description and declared damage match what was detected.")
    elif asset.get("match") == "Inconsistent":
        result = "Inconsistent"
    if damage.get("status") == "Unable to verify":
        result = result if result == "Inconsistent" else "Unable to verify"
        notes.append("Damage could not be verified from the image, so the text cannot be compared with it.")
    elif damage.get("status") == "No damage detected" and result == "Consistent":
        result = "Unable to verify"
        notes.append("No damage was detected, so the description is not supported by the photos.")
    return {"result": result, "notes": notes, "method": "rule-based keyword comparison (not machine learning)"}


# ------------------------------------------------------------------ stage 6: duplicate & risk checks
def duplicate_checks(images: list[dict], prior: list[dict], incident: date, student_id: int, claim_id: int, asset_id: int | None = None) -> tuple[dict, list[dict]]:
    """Exact (SHA-256) and perceptual duplicates against earlier claim photos AND registration photographs (prior entries carry source='claim'|'registration')."""
    res, risks = authenticity.find_duplicates(images, prior, student_id=student_id, claim_id=claim_id, asset_id=asset_id,
                                              dhash_max=settings.DUP_DHASH_MAX_DISTANCE, dct_max=settings.DUP_PHASH_MAX_DISTANCE)
    for im in images:
        raw = (im.get("exif") or {}).get("DateTimeOriginal") or (im.get("exif") or {}).get("DateTime")
        if raw:
            try:
                taken = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S").date()
                if (incident - taken).days > 1:
                    risks.append({"code": "META-DATE", "severity": "medium", "text": f"{im['original_name']} was captured on {taken}, before the stated incident date {incident}."})
            except ValueError:
                pass
    return res, risks


# ------------------------------------------------------------------ stage 6b: registered-device matching helpers
def _locator(category: str):
    """Crops photos to the device when the COCO detector can see it; None when it has no class for this category."""
    det = vision.get_detector("asset")
    want = {k for k, v in vision.COCO_ASSET_LABELS.items() if v == category}
    if det is None or not want:
        return None

    def locate(bgr):
        ds = [d for d in det.predict(bgr, min_conf=0.3) if d.label in want]
        return ds[0].box if ds else None
    return locate


def _decode_refs(registered: list[dict] | None) -> list[dict]:
    refs, extra = [], 0
    for r in registered or []:
        if r.get("kind") not in ("front_photo", "back_photo", "extra_photo"):
            continue
        try:
            _im, bgr = vision.decode(r["data"])
        except vision.ImageError:
            continue
        if r["kind"] == "extra_photo":
            extra += 1
        label = {"front_photo": "front photograph", "back_photo": "back photograph"}.get(r["kind"], f"additional photograph {extra}")
        refs.append({"kind": r["kind"], "label": label, "bgr": bgr})
    return refs[:6]


def _read_identifiers(raw: list[tuple[int, bytes, str]]) -> list[dict]:
    """Ask the configured vision-language model to transcribe text that is physically visible on the device. Empty when no provider is configured."""
    if not raw or not service.status()["vision_available"]:
        return []
    out = []
    for _i, data, mime in raw[:2]:
        try:
            obs, _meta = service.call_structured(VLMIdentifiers, ("Transcribe ONLY text that is physically printed, engraved or displayed on the device in the photo: brand, model name and any serial number or IMEI. "
                                                                  "Do not guess, complete or correct partial text. If a field is not clearly legible return an empty string and set legible to false."), (data, mime))
            out.append(obs.model_dump())
        except service.AIUnavailable:
            continue
    return out


# ------------------------------------------------------------------ orchestration & outcome
def verify(*, claim_id: int, category: str, allowed_damage: list[str], declared_damage: str, description: str, incident_date: date, student_id: int,
           files: list[dict], prior: list[dict], run: int, supporting_docs: int = 0, registered: list[dict] | None = None, asset_info: dict | None = None,
           purchase_date: date | None = None, asset_id: int | None = None) -> dict:
    """files: [{original_name, data, content_type, sha256, phash, phash_dct, exif}] (already validated). registered: [{kind, data}] registration photographs.
    asset_info: {brand, model, serial}. Returns the report as a dict (keys match AIVerificationReport columns)."""
    t0 = time.perf_counter()
    mode = "development_simulation" if settings.AI_VERIFY_MODE == "dev_simulation" else None
    qual, usable, raw, decoded, auth_imgs = [], [], [], {}, []
    for i, f in enumerate(files):
        try:
            _im, bgr = vision.decode(f["data"])
        except vision.ImageError as e:
            qual.append({"image": f["original_name"], "usable": False, "score": 0, "issues": [str(e)], "method": "decode failure"})
            continue
        q = vision.assess_quality(bgr) | {"image": f["original_name"]}
        qual.append(q)
        decoded[i] = bgr
        auth_imgs.append(authenticity.analyze_image(f["data"], bgr, f["original_name"], quality=q))
        if q["usable"]:
            usable.append((i, bgr)); raw.append((i, f["data"], f["content_type"]))
    n_usable = len(usable)
    avg = round(sum(q["score"] for q in qual) / len(qual)) if qual else 0
    quality = {"images": qual, "usable_count": n_usable, "total_count": len(files), "average_score": avg, "result": "Good" if n_usable and avg >= 70 else "Acceptable" if n_usable else "Insufficient"}

    dup, risks = duplicate_checks([{"original_name": f["original_name"], "sha256": f["sha256"], "phash": f["phash"], "phash_dct": f.get("phash_dct", ""), "exif": f.get("exif")} for f in files],
                                  prior, incident_date, student_id, claim_id, asset_id)
    seen_text = {r["text"] for r in risks}
    auth_inds = []
    for ai in auth_imgs:
        for r in authenticity.indicators_for(ai, incident=incident_date, purchase=purchase_date, today=date.today()):
            if r["text"] not in seen_text:
                auth_inds.append(r); seen_text.add(r["text"])
    risks += auth_inds
    authenticity_section = authenticity.summarise(auth_imgs, auth_inds)

    sim = mode == "development_simulation"
    if n_usable == 0:
        asset = {"status": "Not run", "detected": None, "confidence": None, "match": "Not run", "explanation": "No usable image."}
        damage = {"status": "Not run", "detections": [], "explanation": "No usable image."}
        descr = {"result": "Not run", "notes": [], "method": ""}
        mode_used = mode or "limited"
        devm = device_match.compare([], [], registered=asset_info or {}) | {"used_for_routing": False}
    else:
        asset = identify_asset(category, usable, mode or "x")
        damage = detect_damage(category, declared_damage, allowed_damage, usable, raw, mode or "x", description)
        dm_model = vision.get_detector("damage")
        mode_used = mode or ("onnx_model" if dm_model else "vision_language_model" if damage.get("method", "") and "vision-language" in str(damage.get("method")) else "limited")
        # a second asset opinion from the vision model when the detector cannot cover this category
        if asset["status"] == "Unable to verify" and damage.get("asset_seen"):
            seen = damage["asset_seen"]
            asset |= {"detected": seen, "confidence": damage.get("asset_seen_confidence"), "method": "vision-language model (self-reported)",
                      "match": "Consistent" if norm(seen) == norm(category) else ("Inconsistent" if seen in ASSET_WORDS and damage.get("asset_seen_confidence", 0) >= 0.7 else "Unable to verify")}
        descr = compare_description(category, declared_damage, description, damage, asset, mode_used)
        refs = _decode_refs(registered)
        readings = [] if sim else _read_identifiers(raw)
        devm = device_match.compare([(i, files[i]["original_name"], bgr) for i, bgr in usable], refs, registered=asset_info or {}, locate=_locator(category), readings=readings,
                                    strong=settings.DEVICE_MATCH_STRONG, partial=settings.DEVICE_MATCH_PARTIAL, min_keypoints=settings.DEVICE_MATCH_MIN_KEYPOINTS)
        devm["used_for_routing"] = not sim
        if devm["used_for_routing"]:
            if devm.get("serial_check", {}).get("status") == "Differs":
                risks.append({"code": "ID-SERIAL-DIFF", "severity": "high", "text": devm["serial_check"]["detail"]})
            if devm.get("brand_model_check", {}).get("status") == "Differs":
                risks.append({"code": "ID-BRAND-DIFF", "severity": "medium", "text": devm["brand_model_check"]["detail"]})
        else:
            devm["conclusion"] = "Development simulation: the comparison ran but is NOT used for routing. " + devm["conclusion"]

    completeness = {"photos_uploaded": len(files), "usable_photos": n_usable, "supporting_documents": supporting_docs, "description_provided": len(description.strip()) >= 15,
                    "registered_photos": len([r for r in (registered or []) if r.get("kind") in ("front_photo", "back_photo", "extra_photo")]),
                    "complete": n_usable >= 1 and len(description.strip()) >= 15}
    if not completeness["description_provided"]:
        risks.append({"code": "DESC-SHORT", "severity": "low", "text": "The incident description is very short."})

    high = [r for r in risks if r["severity"] == "high"]
    band = devm.get("band")
    route, outcome, reasons = "auto", SUPPORTED, []
    at_limit = run >= settings.MAX_VERIFICATION_RUNS
    if n_usable == 0:
        outcome, route = MORE, "more_evidence"
        reasons.append("None of the photos could be used: " + "; ".join(sorted({i for q in qual for i in q["issues"]})) + ". Please upload clearer photos in good light, with the damaged part in focus.")
    elif asset["match"] == "Inconsistent" or descr["result"] == "Inconsistent" or high:
        outcome, route = INCONSISTENT, "exceptional_review"
        if asset["match"] == "Inconsistent":
            reasons.append(asset["explanation"])
        reasons += descr["notes"] if descr["result"] == "Inconsistent" else []
        reasons += [r["text"] for r in high]
    elif damage["status"] == "Unable to verify":
        outcome = MORE
        route = "exceptional_review" if (damage.get("capability_missing") or at_limit) else "more_evidence"
        reasons.append(damage["explanation"])
    elif damage["status"] == "No damage detected":
        outcome = MORE
        route = "exceptional_review" if at_limit else "more_evidence"
        reasons.append("No clear damage is visible. Please add a close-up of the damaged area and a wider shot of the whole item.")
    elif descr["result"] != "Consistent" and not sim:
        outcome, route = MORE, ("exceptional_review" if at_limit else "more_evidence")
        reasons.append("The description could not be matched to the detected damage. " + " ".join(descr["notes"]))
    elif devm["used_for_routing"] and band in (device_match.BAND_WEAK, device_match.BAND_PARTIAL, device_match.BAND_NODETAIL):
        outcome, route = MORE, ("exceptional_review" if at_limit else "more_evidence")
        reasons.append(devm["conclusion"] + " Please add clear photos of the whole item from the front and the back in good light, ideally showing the label with the serial number or IMEI.")
    elif devm["used_for_routing"] and band in (device_match.BAND_NOREG, device_match.BAND_NOTRUN):
        outcome, route = MORE, "exceptional_review"
        reasons.append(devm["conclusion"])
    else:
        reasons.append("The photos are usable, the visible damage matches the declared damage, and no blocking inconsistency was found.")
    if not completeness["complete"] and outcome == SUPPORTED:
        outcome, route = MORE, "more_evidence"
        reasons.append("Please describe what happened in at least a sentence.")

    workflow = workflow_for(outcome, route)
    expl = ("DEVELOPMENT SIMULATION: asset and damage were assumed from the claim form; only image quality, duplicate, metadata and device-comparison checks are real. " if sim else "") + " ".join(reasons)
    if not sim and n_usable and outcome == SUPPORTED:
        expl += " Registered-device comparison: " + devm["conclusion"]
    nxt = {SUPPORTED: "Proceeding to policy eligibility checks.", MORE: ("Upload clearer or additional photos and run verification again." if route == "more_evidence" else "Referred to staff for manual review."),
           INCONSISTENT: "Referred to staff for manual review. This is not a finding of fraud."}[outcome]
    counts = {k: sum(1 for r in risks if r["severity"] == k) for k in ("high", "medium", "low")}
    authenticity_section["summary"] = {
        "expected_device_present": {"status": asset.get("match"), "detail": asset.get("explanation")},
        "visible_damage": {"status": damage.get("status"), "types": sorted({d["damage_type"] for d in damage.get("detections", [])}), "top_confidence": max([d["confidence"] for d in damage.get("detections", []) if d.get("confidence") is not None] or [None])},
        "description_matches": descr.get("result"),
        "registered_device_match": {"band": band, "score": devm.get("best_score"), "used_for_routing": devm.get("used_for_routing")},
        "authenticity_flags": counts,
        "note": "Detected damage describes what the software saw in the photographs. It does not establish that the claim is genuine: authenticity needs the device, duplicate and metadata checks above, and a person decides whenever the evidence is uncertain or conflicting."}
    model_info = {"asset_detector": (vision.get_detector("asset").info() if vision.get_detector("asset") else None), "damage_detector": (vision.get_detector("damage").info() if vision.get_detector("damage") else None),
                  "vision_language_model": service.status()["vision_model"] if service.status()["vision_available"] else None, "device_matching": device_match.METHOD}
    return {"mode": mode_used, "is_simulated": sim, "model_info": model_info, "quality": quality, "asset_identification": asset, "damage_detection": damage, "description_check": descr,
            "duplicate_check": dup, "evidence_completeness": completeness, "risk_indicators": risks, "device_match": devm, "authenticity": authenticity_section, "workflow_outcome": workflow,
            "outcome": outcome, "route": route, "explanation": expl, "next_step": nxt, "processing_ms": round((time.perf_counter() - t0) * 1000)}
