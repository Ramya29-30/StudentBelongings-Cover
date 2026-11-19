"""Measure how well the registered-device matcher separates "same item" pairs from "different item" pairs, on photos YOU labelled.

Without this, the matcher's thresholds (DEVICE_MATCH_STRONG / DEVICE_MATCH_PARTIAL) are uncalibrated heuristics and the admin page says so.
Nothing is invented: with too few labelled pairs the script refuses to write a result.

Input: a CSV with the columns  image_a,image_b,same_item   (same_item = 1 when both photos show the same physical item, 0 when they show different items).
Paths are relative to the CSV's folder (or --root). Build it from real pairs: for each item, 2+ photos from different angles/sessions (label 1),
and photos of OTHER items of the same model and of other models (label 0). Include hard negatives (same model, different unit) and
hard positives (different angle, damaged vs undamaged); easy pairs make every threshold look good.

    python ai_training/evaluate_device_matching.py --pairs ai_training/pairs/pairs.csv
Writes backend/models/device_match_evaluation.json: AUC, precision/recall at each threshold, and SUGGESTED thresholds. Suggestions are never applied automatically:
copy them into DEVICE_MATCH_STRONG / DEVICE_MATCH_PARTIAL yourself after reading the table.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
MIN_PER_CLASS = 20


def roc_auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based AUC with tie handling: the probability that a random same-item pair scores above a random different-item pair (ties count half)."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def threshold_table(scores: list[float], labels: list[int], grid=None) -> list[dict]:
    grid = grid or [round(0.05 * i, 2) for i in range(1, 21)]
    out = []
    npos = sum(labels)
    nneg = len(labels) - npos
    for t in grid:
        tp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 1)
        fp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 0)
        out.append({"threshold": t, "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / npos, 4) if npos else None,
                    "false_positive_rate": round(fp / nneg, 4) if nneg else None, "flagged_pairs": tp + fp})
    return out


def suggest(table: list[dict], target_precision: float) -> dict:
    strong = next((r["threshold"] for r in table if r["precision"] is not None and r["precision"] >= target_precision and r["recall"] and r["recall"] > 0), None)
    partial = next((r["threshold"] for r in table if r["recall"] is not None and r["recall"] >= 0.8), None)
    return {"strong": strong, "partial": partial, "target_precision": target_precision,
            "note": "Suggestions only. 'strong' is the lowest threshold whose precision on YOUR pairs reaches the target; 'partial' is the lowest that keeps 80% recall. None means the data does not support one."}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", required=True, type=Path)
    ap.add_argument("--root", type=Path, help="folder the CSV paths are relative to (default: the CSV's folder)")
    ap.add_argument("--out", type=Path, default=ROOT / "backend" / "models" / "device_match_evaluation.json")
    ap.add_argument("--target-precision", type=float, default=0.95)
    ap.add_argument("--min-per-class", type=int, default=MIN_PER_CLASS)
    a = ap.parse_args()
    import cv2
    from app.ai import device_match as dm
    from app.config import settings
    root = a.root or a.pairs.parent
    rows = list(csv.DictReader(a.pairs.open(encoding="utf-8")))
    if not rows or {"image_a", "image_b", "same_item"} - set(rows[0]):
        sys.exit("The CSV needs the columns image_a,image_b,same_item.")
    cache: dict[Path, tuple] = {}

    def feats(rel: str):
        p = root / rel
        if p not in cache:
            img = cv2.imread(str(p))
            cache[p] = dm.extract(img) if img is not None else None
        return cache[p]
    scores, labels, skipped = [], [], 0
    for r in rows:
        fa, fb = feats(r["image_a"]), feats(r["image_b"])
        if fa is None or fb is None or r["same_item"] not in ("0", "1"):
            skipped += 1
            continue
        scores.append(dm.match_features(fa, fb)["score"])
        labels.append(int(r["same_item"]))
    pos, neg = sum(labels), len(labels) - sum(labels)
    if pos < a.min_per_class or neg < a.min_per_class:
        sys.exit(f"Not enough labelled pairs: {pos} same-item and {neg} different-item (need at least {a.min_per_class} of each). Nothing was written.")
    table = threshold_table(scores, labels)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": dm.METHOD, "pairs": len(labels), "same_item_pairs": pos, "different_item_pairs": neg,
           "skipped_rows": skipped, "auc": round(roc_auc(scores, labels) or 0, 4), "thresholds": table, "suggested": suggest(table, a.target_precision),
           "currently_configured": {"strong": settings.DEVICE_MATCH_STRONG, "partial": settings.DEVICE_MATCH_PARTIAL},
           "note": "Measured on the supplied pairs only (whole photos, no device crop). Accuracy on other devices, lighting or cameras is unknown."}
    a.out.write_text(json.dumps(out, indent=2), "utf-8")
    print(f"{len(labels)} pairs ({pos} same, {neg} different). AUC={out['auc']}. Suggested thresholds: {out['suggested']['strong']} (strong), {out['suggested']['partial']} (partial). Wrote {a.out}")


if __name__ == "__main__":
    main()
