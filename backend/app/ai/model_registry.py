"""Facts about the installed damage model and its measured evaluation. Nothing here invents a number: a metric that was not measured is None.

Files (all in MODEL_DIR):
  damage_model.onnx    the trained detector (written by ai_training/train_damage_model.py or supplied by you)
  damage_model.json    training metadata sidecar written by the training script (classes, dataset fingerprint, ultralytics version, epochs). Optional.
  evaluation.json      written ONLY by ai_training/evaluate_damage_model.py after it ran on a labelled split. Never written by the application.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from . import vision

_SIDECAR_KEYS = ("trained_at", "base_weights", "epochs", "imgsz", "ultralytics_version", "classes", "dataset_fingerprint", "train_images", "val_images", "notes")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text("utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def load_evaluation() -> dict | None:
    return _read_json(settings.MODEL_DIR / "evaluation.json")


def damage_model_status() -> dict:
    """Availability, version (SHA-256 of the file) and whether the stored evaluation belongs to THIS model file."""
    f = settings.MODEL_DIR / settings.DAMAGE_MODEL_FILE
    det = vision.get_detector("damage")
    side = _read_json(f.with_suffix(".json"))
    ev = load_evaluation()
    matches = bool(det and ev and ev.get("model_sha256") and det.sha.startswith(str(ev["model_sha256"])))
    stat = None
    if f.is_file():
        stat = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    if det is not None:
        state = "Installed and loaded"
    elif f.is_file():
        state = "File present but could not be loaded (see the backend log)"
    else:
        state = "Not installed. No damage detector has been trained or supplied, so damage cannot be detected automatically."
    return {"available": det is not None, "state": state, "file": settings.DAMAGE_MODEL_FILE, "file_modified": stat, "sha256": det.sha if det else None,
            "classes": [det.names[i] for i in sorted(det.names)] if det else [], "input_size": det.size if det else None,
            "training_metadata": {k: side[k] for k in _SIDECAR_KEYS if side and k in side} if side else None,
            "evaluation_present": ev is not None, "evaluation_matches_model": matches,
            "evaluation_note": ("The stored evaluation was measured on this exact model file." if matches else
                                "An evaluation file exists but it was produced for a different model file; do not trust it for this model." if (ev and det) else
                                "No evaluation has been measured." if det else "")}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalise_evaluation(ev: dict | None) -> dict | None:
    """Return the evaluation in one fixed shape with None wherever the file does not contain a metric, plus the list of metrics that are unavailable."""
    if not ev:
        return None
    per = {}
    for name, r in (ev.get("per_class") or {}).items():
        p, rc = _num(r.get("precision")), _num(r.get("recall"))
        f1 = _num(r.get("f1"))
        if f1 is None and p is not None and rc is not None and (p + rc) > 0:
            f1 = round(2 * p * rc / (p + rc), 3)
        per[name] = {"precision": p, "recall": rc, "f1": f1, "ap50": _num(r.get("ap50")), "ap50_95": _num(r.get("ap50_95")), "tp": r.get("tp"), "fp": r.get("fp"), "fn": r.get("fn"),
                     "instances": r.get("instances", (r.get("tp", 0) + r.get("fn", 0)) if r.get("tp") is not None and r.get("fn") is not None else None)}
    overall = ev.get("overall") or {}
    unavailable = []
    if not overall or _num(overall.get("map50")) is None:
        unavailable.append("mAP@0.5")
    if not overall or _num(overall.get("map50_95")) is None:
        unavailable.append("mAP@0.5:0.95")
    if not ev.get("confusion_matrix"):
        unavailable.append("confusion matrix")
    if any(r["f1"] is None for r in per.values()):
        unavailable.append("F1 for classes without both precision and recall")
    return {"model": ev.get("model"), "model_sha256": ev.get("model_sha256"), "split": ev.get("split"), "images": ev.get("images"), "iou_threshold": ev.get("iou_threshold"),
            "confidence_threshold": ev.get("confidence_threshold"), "generated_at": ev.get("generated_at"), "dataset": ev.get("dataset"), "per_class": per,
            "overall": {"precision": _num(overall.get("precision")), "recall": _num(overall.get("recall")), "f1": _num(overall.get("f1")), "map50": _num(overall.get("map50")), "map50_95": _num(overall.get("map50_95"))},
            "confusion_matrix": ev.get("confusion_matrix"), "unavailable_metrics": unavailable, "note": ev.get("note")}
