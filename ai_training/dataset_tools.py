"""Shared helpers for the damage-model pipeline: class list, YOLO dataset validation, dataset fingerprint.

Needs only the standard library and Pillow, so it runs without PyTorch.

YOLO detection layout (what train, evaluate and validate expect):
    dataset/classes.txt          one class name per line (order = class id)
    dataset/images/<split>/*.jpg|jpeg|png
    dataset/labels/<split>/*.txt one file per image: "class_id cx cy w h" (normalised 0..1), one line per damaged region
    splits: train and val are required, test is optional
An image with no label file (or an empty one) is a valid NEGATIVE example (an undamaged device). Negatives matter: without them the model learns to see damage everywhere.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
IMG_EXT = {".jpg", ".jpeg", ".png"}
SPLITS = ("train", "val", "test")

# The initial damage classes of the application. Names are matched to a category's claimable damage types ignoring case and spacing,
# and by damage family (see backend/app/ai/verification.py), so the same six classes serve both categories below.
CLASSES = ["Cracked screen", "Broken display", "Damaged body", "Camera lens damage", "Damaged keyboard", "Broken hinge"]
CATEGORY_CLASSES = {
    "Smartphone": ["Cracked screen", "Broken display", "Damaged body", "Camera lens damage"],
    "Laptop": ["Cracked screen", "Broken display", "Damaged body", "Damaged keyboard", "Broken hinge"],
}
MIN_TRAIN_INSTANCES_WARN = 50  # per class; a demo needs a few hundred, real use thousands
MAX_NEAR_DUP_REPORT = 20


def norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (s or "").strip().lower())


def read_classes(data: Path) -> list[str]:
    f = data / "classes.txt"
    if not f.is_file():
        raise FileNotFoundError(f"{f} not found. Create it with one class name per line (see ai_training/classes.txt).")
    return [ln.strip() for ln in f.read_text("utf-8").splitlines() if ln.strip()]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash_pil(p: Path) -> int | None:
    """64-bit difference hash computed with Pillow only (so near-duplicate detection needs no OpenCV)."""
    try:
        with Image.open(p) as im:
            g = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            px = list(g.tobytes())  # mode L: one byte per pixel
    except Exception:
        return None
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c + 1] > px[r * 9 + c] else 0)
    return bits


def split_images(data: Path, split: str) -> list[Path]:
    d = data / "images" / split
    return sorted(p for p in d.glob("*") if p.suffix.lower() in IMG_EXT) if d.is_dir() else []


def parse_label_file(path: Path, n_classes: int) -> tuple[list[tuple[int, float, float, float, float]], list[str]]:
    """Return (boxes, problems). Each box is (class_id, cx, cy, w, h). Never raises on bad content."""
    boxes, problems = [], []
    seen = set()
    for ln_no, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            problems.append(f"{path.name}:{ln_no}: expected 5 values (class cx cy w h), found {len(parts)}. Segmentation/polygon labels are not supported.")
            continue
        try:
            c = int(parts[0]) if re.fullmatch(r"\d+", parts[0]) else None
            cx, cy, w, h = (float(x) for x in parts[1:])
        except ValueError:
            problems.append(f"{path.name}:{ln_no}: non-numeric value.")
            continue
        if c is None or c >= n_classes:
            problems.append(f"{path.name}:{ln_no}: class id {parts[0]!r} is not an integer between 0 and {n_classes - 1}.")
            continue
        if not all(0.0 <= v <= 1.0 for v in (cx, cy, w, h)):
            problems.append(f"{path.name}:{ln_no}: coordinates must be normalised to 0..1 (found {cx}, {cy}, {w}, {h}). Pixel coordinates?")
            continue
        if w <= 0 or h <= 0:
            problems.append(f"{path.name}:{ln_no}: box has zero width or height.")
            continue
        if cx - w / 2 < -1e-3 or cy - h / 2 < -1e-3 or cx + w / 2 > 1 + 1e-3 or cy + h / 2 > 1 + 1e-3:
            problems.append(f"{path.name}:{ln_no}: box extends outside the image.")
            continue
        key = (c, round(cx, 4), round(cy, 4), round(w, 4), round(h, 4))
        if key in seen:
            problems.append(f"{path.name}:{ln_no}: duplicate of an earlier line.")
            continue
        seen.add(key)
        boxes.append((c, cx, cy, w, h))
    return boxes, problems


def validate_dataset(data: Path, allowed: list[str] | None = None, allow_extra_classes: bool = False) -> dict:
    """Check class names, layout, every image and every annotation, split leakage and class balance. Returns {errors, warnings, stats}."""
    errors: list[str] = []
    warnings: list[str] = []
    allowed = CLASSES if allowed is None else allowed
    try:
        names = read_classes(data)
    except FileNotFoundError as e:
        return {"errors": [str(e)], "warnings": [], "stats": {}}
    if not names:
        return {"errors": ["classes.txt is empty."], "warnings": [], "stats": {}}
    seen_norm: dict[str, str] = {}
    for n in names:
        if norm(n) in seen_norm:
            errors.append(f"classes.txt lists {n!r} and {seen_norm[norm(n)]!r}: these are the same class once case and spacing are ignored.")
        seen_norm[norm(n)] = n
    allowed_n = {norm(a) for a in allowed}
    unknown = [n for n in names if norm(n) not in allowed_n]
    if unknown and not allow_extra_classes:
        errors.append(f"Class names not in the application's damage classes: {unknown}. Allowed: {allowed}. Rename them, or pass --allow-extra-classes "
                      "(detections of unknown classes are ignored by the application unless an administrator adds them to a category's damage types).")
    elif unknown:
        warnings.append(f"Extra classes will be trained but ignored by the application until they are claimable damage types: {unknown}.")
    missing_known = [a for a in allowed if norm(a) not in {norm(n) for n in names}]
    if missing_known:
        warnings.append(f"The dataset does not define these application damage classes, so they can never be detected: {missing_known}.")

    stats: dict = {"classes": names, "splits": {}}
    hashes: dict[str, dict[str, Path]] = {}
    dhashes: dict[str, list[tuple[int, Path]]] = {}
    for split in SPLITS:
        imgs = split_images(data, split)
        if not imgs:
            if split in ("train", "val"):
                errors.append(f"No images found in images/{split}.")
            continue
        per_class = [0] * len(names)
        no_label = bad_img = 0
        for img in imgs:
            try:
                with Image.open(img) as im:
                    im.verify()
                with Image.open(img) as im:
                    if min(im.size) < 64:
                        warnings.append(f"{split}/{img.name}: very small image {im.size}.")
            except Exception:
                bad_img += 1
                errors.append(f"{split}/{img.name}: unreadable or corrupted image.")
                continue
            hashes.setdefault(sha256_file(img), {})[split] = img
            dh = dhash_pil(img)
            if dh is not None:
                dhashes.setdefault(split, []).append((dh, img))
            lab = data / "labels" / split / (img.stem + ".txt")
            if not lab.is_file():
                no_label += 1
                continue
            boxes, problems = parse_label_file(lab, len(names))
            errors += [f"{split}/{p}" for p in problems]
            if not boxes:
                no_label += 1
            for b in boxes:
                per_class[b[0]] += 1
                if b[3] * b[4] < 0.0005:
                    warnings.append(f"{split}/{lab.name}: a tiny box (<0.05% of the image); check it.")
        orphans = [p.name for p in (data / "labels" / split).glob("*.txt") if not any((data / "images" / split / (p.stem + e)).exists() for e in IMG_EXT)] if (data / "labels" / split).is_dir() else []
        if orphans:
            warnings.append(f"labels/{split}: {len(orphans)} label file(s) without an image (first: {orphans[0]}).")
        stats["splits"][split] = {"images": len(imgs), "negative_images": no_label, "unreadable_images": bad_img, "instances_per_class": dict(zip(names, per_class))}
        if no_label / len(imgs) > 0.5:
            warnings.append(f"{split}: {no_label} of {len(imgs)} images have no annotations. Check that label files have the same base name as their images.")

    # ---- class coverage and balance
    tr, va = stats["splits"].get("train"), stats["splits"].get("val")
    if tr and va:
        for n in names:
            t, v = tr["instances_per_class"][n], va["instances_per_class"][n]
            if t == 0:
                errors.append(f"Class {n!r} has no training instances.")
            elif t < MIN_TRAIN_INSTANCES_WARN:
                warnings.append(f"Class {n!r} has only {t} training instances (fewer than {MIN_TRAIN_INSTANCES_WARN}); expect poor recall.")
            if t > 0 and v == 0:
                errors.append(f"Class {n!r} appears in training but not in validation, so its performance cannot be measured.")
        if tr["negative_images"] == 0:
            warnings.append("The training split has no negative images (undamaged devices). The model will tend to see damage everywhere.")

    # ---- leakage between splits
    leaks = [(h, s) for h, s in hashes.items() if len(s) > 1]
    for h, s in leaks:
        errors.append("The same image file appears in more than one split (" + ", ".join(f"{k}/{v.name}" for k, v in s.items()) + "). That inflates every metric.")
    near = 0
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        if a in dhashes and b in dhashes:
            for ha, pa in dhashes[a]:
                for hb, pb in dhashes[b]:
                    if pa.name != pb.name and (ha ^ hb).bit_count() <= 3 and sha256_file(pa) != sha256_file(pb):
                        near += 1
                        if near <= MAX_NEAR_DUP_REPORT:
                            warnings.append(f"Near-duplicate images across splits: {a}/{pa.name} and {b}/{pb.name}. Split by device/photo session, not by image, to avoid leakage.")
    if near > MAX_NEAR_DUP_REPORT:
        warnings.append(f"... and {near - MAX_NEAR_DUP_REPORT} more near-duplicate pairs across splits.")
    stats["near_duplicate_pairs_across_splits"] = near
    stats["fingerprint"] = fingerprint(data)
    return {"errors": errors, "warnings": warnings, "stats": stats}


def fingerprint(data: Path, splits: tuple[str, ...] = SPLITS) -> str:
    """Hash of the class list plus the content hash of every image and label file in the given splits (identifies exactly which data a model was trained or measured on)."""
    h = hashlib.sha256()
    cf = data / "classes.txt"
    if cf.is_file():
        h.update(cf.read_bytes())
    for split in splits:
        for img in split_images(data, split):
            h.update(f"{split}/{img.name}:{sha256_file(img)}".encode())
            lab = data / "labels" / split / (img.stem + ".txt")
            h.update(sha256_file(lab).encode() if lab.is_file() else b"-")
    return h.hexdigest()


def print_report(rep: dict) -> None:
    st = rep.get("stats", {})
    for split, s in st.get("splits", {}).items():
        print(f"{split:5s} images={s['images']:5d} negatives={s['negative_images']:5d} instances={s['instances_per_class']}")
    for w in rep["warnings"]:
        print("WARNING:", w)
    for e in rep["errors"]:
        print("ERROR:  ", e)
    print(f"{len(rep['errors'])} error(s), {len(rep['warnings'])} warning(s).")
