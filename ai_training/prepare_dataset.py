"""Build the training dataset from labelled sources you downloaded. It FABRICATES NOTHING: it only converts, remaps class names, drops what you did not map,
splits by photo group (so near-identical photos never straddle train and val) and writes a manifest of where every image came from.

Supported sources:
  * YOLO-format folders      --yolo IMAGES_DIR LABELS_DIR NAMES_FILE   (NAMES_FILE: one source class name per line, in id order)
  * COCO bounding-box JSON   --coco ANNOTATIONS_JSON IMAGES_DIR
Every source needs a class map saying which of YOUR classes each source class becomes (a JSON object; null or a missing key drops the class):
    {"crack": "Cracked screen", "broken_screen": "Broken display", "dent": "Damaged body", "scratch": null}
Provide --licence and --source-url for each source: they are recorded in the manifest. Check each dataset's licence allows your use.

Example (two sources):
    python ai_training/prepare_dataset.py --out ai_training/dataset \
        --yolo ~/dl/phones/images ~/dl/phones/labels ~/dl/phones/names.txt --map phones_map.json --licence "CC BY 4.0" --source-url https://... --name phones \
        --coco ~/dl/laptops/_annotations.coco.json ~/dl/laptops/images --map laptops_map.json --licence "CC BY 4.0" --source-url https://... --name laptops
Options repeat per source in the order given. Then run validate_dataset.py.
Negatives: images with no mapped annotation are kept as negative examples (undamaged devices) ONLY if you pass --keep-negatives for that source; most damage datasets contain
only damaged images, so add undamaged device photos as a separate source.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_tools import CLASSES, IMG_EXT, dhash_pil, norm, sha256_file  # noqa: E402


class Source:
    def __init__(self, name: str, kind: str, a: Path, b: Path, names: list[str] | None, cmap: dict, licence: str, url: str, keep_negatives: bool):
        self.name, self.kind, self.a, self.b, self.names, self.cmap, self.licence, self.url, self.keep_negatives = name, kind, a, b, names, cmap, licence, url, keep_negatives


def load_yolo(src: Source):
    """Yield (image path, [(source class name, cx, cy, w, h)])."""
    for img in sorted(p for p in src.a.glob("*") if p.suffix.lower() in IMG_EXT):
        lab = src.b / (img.stem + ".txt")
        boxes = []
        if lab.is_file():
            for ln in lab.read_text("utf-8", errors="replace").splitlines():
                p = ln.split()
                if len(p) == 5 and p[0].isdigit() and int(p[0]) < len(src.names or []):
                    boxes.append((src.names[int(p[0])], *map(float, p[1:])))
        yield img, boxes


def load_coco(src: Source):
    data = json.loads(src.a.read_text("utf-8"))
    cats = {c["id"]: c["name"] for c in data.get("categories", [])}
    by_img: dict[int, list] = {}
    for an in data.get("annotations", []):
        by_img.setdefault(an["image_id"], []).append(an)
    for im in data.get("images", []):
        path = src.b / im["file_name"]
        if not path.is_file():
            continue
        w, h = im["width"], im["height"]
        boxes = []
        for an in by_img.get(im["id"], []):
            x, y, bw, bh = an["bbox"]
            boxes.append((cats.get(an["category_id"], str(an["category_id"])), (x + bw / 2) / w, (y + bh / 2) / h, bw / w, bh / h))
        yield path, boxes


def group_images(items: list[tuple[Path, int | None]], max_dist: int = 4) -> list[list[int]]:
    """Union-find over near-identical photos (dHash distance <= max_dist) so each group goes to exactly one split."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(items)):
        hi = items[i][1]
        if hi is None:
            continue
        for j in range(i + 1, len(items)):
            hj = items[j][1]
            if hj is not None and (hi ^ hj).bit_count() <= max_dist:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def main() -> None:
    argv = sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--test-fraction", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output folder")
    # per-source options are parsed by hand so they can repeat
    sources: list[Source] = []
    rest, cur = [], None
    i = 0
    opts = {"--yolo": 3, "--coco": 2, "--map": 1, "--licence": 1, "--source-url": 1, "--name": 1, "--keep-negatives": 0}
    pending: list[dict] = []
    while i < len(argv):
        t = argv[i]
        if t in opts:
            vals = argv[i + 1:i + 1 + opts[t]]
            if len(vals) != opts[t]:
                ap.error(f"{t} needs {opts[t]} value(s)")
            if t in ("--yolo", "--coco"):
                pending.append({"kind": t[2:], "vals": vals, "map": None, "licence": "", "url": "", "name": "", "keep": False})
            elif not pending:
                ap.error(f"{t} must come after --yolo or --coco")
            elif t == "--map":
                pending[-1]["map"] = vals[0]
            elif t == "--licence":
                pending[-1]["licence"] = vals[0]
            elif t == "--source-url":
                pending[-1]["url"] = vals[0]
            elif t == "--name":
                pending[-1]["name"] = vals[0]
            elif t == "--keep-negatives":
                pending[-1]["keep"] = True
            i += 1 + opts[t]
        else:
            rest.append(t)
            i += 1
    a = ap.parse_args(rest)
    if not pending:
        ap.error("give at least one --yolo or --coco source")
    canon = {norm(c): c for c in CLASSES}
    for n, p in enumerate(pending, 1):
        if not p["map"] or not p["licence"] or not p["url"]:
            ap.error(f"source {n}: --map, --licence and --source-url are required (the licence and origin go into the manifest)")
        cmap = {norm(k): (canon.get(norm(v)) if v else None) for k, v in json.loads(Path(p["map"]).read_text("utf-8")).items()}
        bad = [v for v in json.loads(Path(p["map"]).read_text("utf-8")).values() if v and norm(v) not in canon]
        if bad:
            ap.error(f"source {n}: map targets {bad} are not application classes {CLASSES}")
        if p["kind"] == "yolo":
            names = [ln.strip() for ln in Path(p["vals"][2]).read_text("utf-8").splitlines() if ln.strip()]
            sources.append(Source(p["name"] or f"yolo{n}", "yolo", Path(p["vals"][0]), Path(p["vals"][1]), names, cmap, p["licence"], p["url"], p["keep"]))
        else:
            sources.append(Source(p["name"] or f"coco{n}", "coco", Path(p["vals"][0]), Path(p["vals"][1]), None, cmap, p["licence"], p["url"], p["keep"]))

    if a.out.exists():
        if not a.overwrite:
            ap.error(f"{a.out} exists; pass --overwrite to replace it")
        shutil.rmtree(a.out)
    items: list[dict] = []  # image path, source, mapped boxes
    dropped: dict[str, int] = {}
    for s in sources:
        for img, boxes in (load_yolo(s) if s.kind == "yolo" else load_coco(s)):
            mapped = []
            for name, cx, cy, w, h in boxes:
                target = s.cmap.get(norm(name))
                if target is None:
                    dropped[f"{s.name}:{name}"] = dropped.get(f"{s.name}:{name}", 0) + 1
                    continue
                mapped.append((CLASSES.index(target), cx, cy, w, h))
            if not mapped and not s.keep_negatives:
                continue
            items.append({"path": img, "source": s, "boxes": mapped})
    if not items:
        sys.exit("Nothing to write: no image had a mapped annotation. Check your class maps.")
    hashed = [(it["path"], dhash_pil(it["path"])) for it in items]
    groups = group_images(hashed)
    random.Random(a.seed).shuffle(groups)
    total = len(items)
    n_val, n_test = int(total * a.val_fraction), int(total * a.test_fraction)
    split_of = {}
    count = {"val": 0, "test": 0}
    for g in groups:
        sp = "val" if count["val"] < n_val else "test" if count["test"] < n_test else "train"
        if sp in count:
            count[sp] += len(g)
        for idx in g:
            split_of[idx] = sp
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": a.seed, "classes": CLASSES, "sources": [], "dropped_source_classes": dropped, "images": []}
    for s in sources:
        manifest["sources"].append({"name": s.name, "kind": s.kind, "licence": s.licence, "url": s.url})
    used: set[str] = set()
    for idx, it in enumerate(items):
        sp = split_of[idx]
        stem = f"{it['source'].name}_{it['path'].stem}"
        while f"{sp}/{stem}" in used:
            stem += "_x"
        used.add(f"{sp}/{stem}")
        (a.out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (a.out / "labels" / sp).mkdir(parents=True, exist_ok=True)
        dest = a.out / "images" / sp / (stem + it["path"].suffix.lower())
        shutil.copy2(it["path"], dest)
        (a.out / "labels" / sp / (stem + ".txt")).write_text("".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in it["boxes"]), "utf-8")
        manifest["images"].append({"file": f"{sp}/{dest.name}", "source": it["source"].name, "sha256": sha256_file(dest)})
    (a.out / "classes.txt").write_text("\n".join(CLASSES) + "\n", "utf-8")
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    per = {sp: sum(1 for v in split_of.values() if v == sp) for sp in ("train", "val", "test")}
    print(f"Wrote {total} images to {a.out}: {per}. Dropped source classes: {dropped or 'none'}.")
    print("Next: python ai_training/validate_dataset.py --data", a.out)


if __name__ == "__main__":
    main()
