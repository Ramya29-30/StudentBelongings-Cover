"""Object-detection metrics computed from predictions and ground truth. Pure Python + NumPy-free, so it is easy to unit-test.

Conventions (stated so the numbers can be compared with other tools):
  * A prediction matches a ground-truth box of the SAME class when IoU >= threshold; matching is greedy by descending confidence and one-to-one.
  * AP is the area under the precision-recall curve using the monotone precision envelope sampled at 101 recall points (the COCO / Ultralytics convention).
  * mAP@0.5 uses IoU 0.5; mAP@0.5:0.95 averages AP over IoU 0.50, 0.55, ..., 0.95.
  * Precision / recall / F1 are computed at ONE confidence threshold (the application's DETECTION_MIN_CONFIDENCE) and IoU 0.5.
  * A class with no ground-truth instances in the split has no AP / recall (None) and is left out of the mean.
  * The confusion matrix uses the same confidence threshold and IoU 0.5; cell [true][predicted]; the last row/column is "background" (missed objects / false alarms).
Boxes are (x1, y1, x2, y2) in any consistent unit.
"""
from __future__ import annotations

IOU_STEPS = [round(0.5 + 0.05 * i, 2) for i in range(10)]


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def compute_ap(recall: list[float], precision: list[float]) -> float:
    """101-point interpolated AP over the monotone precision envelope."""
    if not recall:
        return 0.0
    mrec = [0.0] + list(recall) + [1.0]
    mpre = [1.0] + list(precision) + [0.0]
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    total = 0.0
    for k in range(101):
        r = k / 100
        idx = next((i for i in range(len(mrec)) if mrec[i] >= r), len(mrec) - 1)  # first point whose recall reaches r
        total += mpre[idx]
    return total / 101


def _match_class(preds: list[tuple], truths: list[tuple], thr: float) -> list[bool]:
    """preds: [(image, conf, box)] of ONE class sorted by -conf; truths: [(image, box)] of that class. Returns tp flag per prediction."""
    by_img: dict = {}
    for i, (img, box) in enumerate(truths):
        by_img.setdefault(img, []).append((i, box))
    used: set[int] = set()
    flags = []
    for img, _conf, box in preds:
        best, bi = 0.0, -1
        for i, tb in by_img.get(img, []):
            if i in used:
                continue
            v = iou(box, tb)
            if v > best:
                best, bi = v, i
        if best >= thr and bi >= 0:
            used.add(bi)
            flags.append(True)
        else:
            flags.append(False)
    return flags


def average_precision(preds: list[tuple], truths: list[tuple], thr: float) -> float | None:
    if not truths:
        return None
    ps = sorted(preds, key=lambda p: -p[1])
    flags = _match_class(ps, truths, thr)
    tp = fp = 0
    rec, prec = [], []
    for f in flags:
        tp += f
        fp += (not f)
        rec.append(tp / len(truths))
        prec.append(tp / (tp + fp))
    return compute_ap(rec, prec)


def evaluate_detections(preds: list[tuple], truths: list[tuple], class_names: list[str], conf_thr: float = 0.35, iou_thr: float = 0.5) -> dict:
    """preds: [(image, class_idx, conf, box)] (include low-confidence ones for AP); truths: [(image, class_idx, box)]."""
    n = len(class_names)
    per, aps50, aps = {}, [], []
    tot_tp = tot_fp = tot_fn = 0
    for c, name in enumerate(class_names):
        cp = [(i, cf, b) for i, k, cf, b in preds if k == c]
        ct = [(i, b) for i, k, b in truths if k == c]
        ap50 = average_precision(cp, ct, 0.5)
        ap_all = [average_precision(cp, ct, t) for t in IOU_STEPS] if ct else None
        ap5095 = sum(ap_all) / len(ap_all) if ap_all else None
        hi = sorted([p for p in cp if p[1] >= conf_thr], key=lambda p: -p[1])
        flags = _match_class(hi, ct, iou_thr)
        tp = sum(flags)
        fp = len(flags) - tp
        fn = len(ct) - tp
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        f1 = 2 * p * r / (p + r) if p is not None and r is not None and p + r > 0 else (0.0 if (p is not None and r is not None) else None)
        per[name] = {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4), "f1": None if f1 is None else round(f1, 4),
                     "ap50": None if ap50 is None else round(ap50, 4), "ap50_95": None if ap5095 is None else round(ap5095, 4), "tp": tp, "fp": fp, "fn": fn, "instances": len(ct)}
        tot_tp, tot_fp, tot_fn = tot_tp + tp, tot_fp + fp, tot_fn + fn
        if ap50 is not None:
            aps50.append(ap50)
            aps.append(ap5095)
    mp = tot_tp / (tot_tp + tot_fp) if tot_tp + tot_fp else None
    mr = tot_tp / (tot_tp + tot_fn) if tot_tp + tot_fn else None
    mf = 2 * mp * mr / (mp + mr) if mp is not None and mr is not None and mp + mr > 0 else None
    # ---- confusion matrix (cross-class greedy matching at conf_thr, IoU iou_thr)
    bg = n
    cm = [[0] * (n + 1) for _ in range(n + 1)]
    gt_by_img: dict = {}
    for gi, (img, k, b) in enumerate(truths):
        gt_by_img.setdefault(img, []).append((gi, k, b))
    used: set[int] = set()
    for img, k, cf, b in sorted([p for p in preds if p[2] >= conf_thr], key=lambda p: -p[2]):
        best, bi, bk = 0.0, -1, -1
        for gi, gk, gb in gt_by_img.get(img, []):
            if gi in used:
                continue
            v = iou(b, gb)
            if v > best:
                best, bi, bk = v, gi, gk
        if best >= iou_thr and bi >= 0:
            used.add(bi)
            cm[bk][k] += 1
        else:
            cm[bg][k] += 1
    for gi, (img, k, b) in enumerate(truths):
        if gi not in used:
            cm[k][bg] += 1
    return {"per_class": per,
            "overall": {"precision": None if mp is None else round(mp, 4), "recall": None if mr is None else round(mr, 4), "f1": None if mf is None else round(mf, 4),
                        "map50": round(sum(aps50) / len(aps50), 4) if aps50 else None, "map50_95": round(sum(aps) / len(aps), 4) if aps else None,
                        "classes_averaged": len(aps50), "note": "Precision/recall/F1 are micro-averaged over all classes at the stated confidence threshold; mAP averages classes that have instances."},
            "confusion_matrix": {"labels": class_names + ["background"], "matrix": cm, "convention": "rows = true class, columns = predicted class; background row = false alarms, background column = missed objects"}}
