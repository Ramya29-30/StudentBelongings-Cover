"""Measure an ONNX damage detector on a labelled YOLO-format split and write backend/models/evaluation.json (shown on the admin AI analytics page).

This is the ONLY thing that writes evaluation.json. Without it the admin page says "Not measured". The file records which model (full SHA-256) and which data
(fingerprint) were measured, so the application can tell when an evaluation belongs to a different model.

Usage (from the project root, backend dependencies installed):
    python ai_training/evaluate_damage_model.py --data ai_training/dataset --split val
    python ai_training/evaluate_damage_model.py --data ai_training/dataset --split test      # best practice: a split never used for training or tuning
Metrics: per-class precision, recall, F1, AP@0.5, AP@0.5:0.95; overall precision/recall/F1, mAP@0.5, mAP@0.5:0.95; confusion matrix.
Precision/recall/F1/confusion use the application's confidence threshold (--conf, default DETECTION_MIN_CONFIDENCE=0.35) at IoU 0.5; AP uses all detections above --ap-conf.
Measuring on the training split is refused unless --allow-train-split (the result would not estimate performance on new photos).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "backend"))
from dataset_tools import fingerprint, norm, parse_label_file, read_classes, split_images  # noqa: E402
from detection_metrics import _match_class, evaluate_detections, iou  # noqa: E402,F401  (iou stays importable from here: older tests use it)


def score(preds: list[tuple], truths: list[tuple], iou_thr: float = 0.5) -> dict[str, list[int]]:
    """Backward-compatible helper kept from the first version of this script. preds: [(class, confidence, box)], truths: [(class, box)] for ONE split
    (boxes in any consistent unit). Returns {class: [tp, fp, fn]} with greedy one-to-one matching by descending confidence."""
    out: dict[str, list[int]] = {}
    for c in {k for k, _, _ in preds} | {k for k, _ in truths}:
        cp = sorted([("split", cf, b) for k, cf, b in preds if k == c], key=lambda p: -p[1])
        ct = [("split", b) for k, b in truths if k == c]
        tp = sum(_match_class(cp, ct, iou_thr))
        out[c] = [tp, len(cp) - tp, len(ct) - tp]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--split", default="val", choices=["train", "val", "test"])
    ap.add_argument("--model", default=ROOT / "backend" / "models" / "damage_model.onnx", type=Path)
    ap.add_argument("--out", default=ROOT / "backend" / "models" / "evaluation.json", type=Path)
    ap.add_argument("--conf", type=float, default=None, help="confidence threshold for precision/recall/F1/confusion (default: the application's)")
    ap.add_argument("--ap-conf", type=float, default=0.01, help="lowest confidence kept when computing AP")
    ap.add_argument("--allow-train-split", action="store_true")
    a = ap.parse_args()
    if a.split == "train" and not a.allow_train_split:
        sys.exit("Refusing to evaluate on the training split: the result would not estimate performance on new photos. Use --split val or test (or --allow-train-split).")
    if not a.model.is_file():
        sys.exit(f"{a.model} not found. Train or supply a damage model first (see ai_training/README.md). Nothing was written.")
    names = read_classes(a.data)
    imgs = split_images(a.data, a.split)
    if not imgs:
        sys.exit(f"No images found in {a.data}/images/{a.split}. Nothing was written.")
    problems = []
    for img in imgs:  # only the split being measured has to be well formed (run validate_dataset.py for the whole dataset)
        lab = a.data / "labels" / a.split / (img.stem + ".txt")
        if lab.is_file():
            problems += parse_label_file(lab, len(names))[1]
    if problems:
        sys.exit("Annotation problems in this split (fix them, or run validate_dataset.py for details):\n  " + "\n  ".join(problems[:10]))
    import cv2
    from app.ai import vision
    from app.config import settings
    conf = settings.DETECTION_MIN_CONFIDENCE if a.conf is None else a.conf
    idx = {norm(n): i for i, n in enumerate(names)}
    det = vision.OnnxDetector(a.model)
    model_classes = [norm(det.names[i]) for i in sorted(det.names)]
    if model_classes != [norm(n) for n in names]:
        sys.exit(f"The model's classes {model_classes} differ from the dataset's {[norm(n) for n in names]}. Evaluate with the dataset the model was trained for.")
    preds, truths, unknown, n_img, n_neg = [], [], 0, 0, 0
    for img in imgs:
        bgr = cv2.imread(str(img))
        if bgr is None:
            continue
        n_img += 1
        key = img.name
        lab = a.data / "labels" / a.split / (img.stem + ".txt")
        boxes = parse_label_file(lab, len(names))[0] if lab.is_file() else []
        n_neg += (not boxes)
        for c, cx, cy, w, h in boxes:
            truths.append((key, c, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
        for d in det.predict(bgr, min_conf=a.ap_conf):
            k = idx.get(norm(d.label))
            if k is None:
                unknown += 1
                continue
            preds.append((key, k, d.confidence, d.box))
    if not truths:
        sys.exit(f"The {a.split} split has no ground-truth boxes, so nothing can be measured. Nothing was written.")
    res = evaluate_detections(preds, truths, names, conf_thr=conf, iou_thr=0.5)
    out = {"model": a.model.name, "model_sha256": det.sha, "split": a.split, "images": n_img, "negative_images": n_neg, "instances": len(truths), "iou_threshold": 0.5,
           "confidence_threshold": conf, "ap_confidence_floor": a.ap_conf, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "dataset": {"path": str(a.data), "split": a.split, "fingerprint": fingerprint(a.data, (a.split,)), "predictions_with_unknown_class": unknown},
           **res, "note": "Measured on the supplied split only. It says nothing about photos unlike that split, and nothing about other devices, lighting or cameras."}
    if a.split == "train":
        out["warning"] = "Evaluated on the TRAINING split: not an estimate of performance on new photos."
    a.out.write_text(json.dumps(out, indent=2), "utf-8")
    o = res["overall"]
    print(f"{a.split}: {n_img} images, {len(truths)} instances. P={o['precision']} R={o['recall']} F1={o['f1']} mAP50={o['map50']} mAP50-95={o['map50_95']}")
    for k, v in res["per_class"].items():
        print(f"  {k:20s} P={v['precision']} R={v['recall']} F1={v['f1']} AP50={v['ap50']} AP50-95={v['ap50_95']} (n={v['instances']})")
    print("Wrote", a.out)


if __name__ == "__main__":
    main()
