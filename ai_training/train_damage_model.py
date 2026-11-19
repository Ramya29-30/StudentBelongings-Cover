"""Fine-tune a YOLO11 detector for the damage classes (phones and laptops) and export it as ONNX for the application.

NOTHING HERE HAS BEEN RUN ON REAL DAMAGE DATA IN THE AUTHORING ENVIRONMENT: no damage dataset or GPU was available, so no weights, accuracy or evaluation result ships
with the project. The script validates your dataset first, trains, exports, then checks that the exported file loads in the SAME runtime the application uses.

Requirements (large download, separate from the app):   pip install ultralytics      (pulls PyTorch)
Steps:
    python ai_training/validate_dataset.py --data ai_training/dataset
    python ai_training/train_damage_model.py --data ai_training/dataset --epochs 100
    python ai_training/evaluate_damage_model.py --data ai_training/dataset --split val
Output: backend/models/damage_model.onnx (class names embedded in the ONNX metadata) and backend/models/damage_model.json (training metadata).
Training NEVER writes evaluation.json: only evaluate_damage_model.py does, after measuring on a labelled split. Until then the admin page says "Not measured".
Use --no-install to export without replacing the installed model. Licence: Ultralytics YOLO is AGPL-3.0 (or commercial); check it fits your use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "backend"))
from dataset_tools import norm, print_report, read_classes, split_images, validate_dataset  # noqa: E402


def verify_export(onnx: Path, classes: list[str]) -> dict:
    """Load the exported file with the application's own detector class and run one forward pass. Exits with a clear reason on any mismatch."""
    import numpy as np
    from app.ai import vision
    try:
        det = vision.OnnxDetector(onnx)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"The exported model does not load in the application's runtime: {type(e).__name__}: {e}")
    exported = [det.names[i] for i in sorted(det.names)]
    if [norm(n) for n in exported] != [norm(n) for n in classes]:
        sys.exit(f"Class names in the ONNX file {exported} differ from classes.txt {classes}. Not installing.")
    det.predict(np.full((480, 640, 3), 127, np.uint8))  # raises if the output layout is not the [1, 4+classes, N] layout the application expects
    return {"classes": exported, "input_size": det.size}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--base", default="yolo11n.pt", help="pretrained starting weights (yolo11n/s/m .pt, downloaded by ultralytics)")
    ap.add_argument("--device", default=None, help="e.g. 0 for the first GPU, cpu")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default="damage")
    ap.add_argument("--allow-extra-classes", action="store_true")
    ap.add_argument("--validate-only", action="store_true", help="only validate the dataset and exit")
    ap.add_argument("--no-install", action="store_true", help="export next to the run folder but do not copy into backend/models")
    a = ap.parse_args()

    rep = validate_dataset(a.data, allow_extra_classes=a.allow_extra_classes)
    print_report(rep)
    if rep["errors"]:
        sys.exit("Fix the dataset errors above before training (nothing was trained).")
    if a.validate_only:
        return
    try:
        import ultralytics
        from ultralytics import YOLO
    except ImportError:
        sys.exit("ultralytics is not installed. Run:  pip install ultralytics   (it installs PyTorch; large download)")
    names = read_classes(a.data)
    cfg = a.data / "data.yaml"
    has_test = bool(split_images(a.data, "test"))
    cfg.write_text(f"path: {a.data.resolve().as_posix()}\ntrain: images/train\nval: images/val\n" + ("test: images/test\n" if has_test else "") + "names:\n" +
                   "".join(f"  {i}: {n}\n" for i, n in enumerate(names)), "utf-8")
    model = YOLO(a.base)
    kw = {"device": a.device} if a.device is not None else {}
    model.train(data=str(cfg), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, seed=a.seed, project=str(ROOT / "ai_training" / "runs"), name=a.name, **kw)
    best = Path(model.trainer.best) if getattr(model, "trainer", None) and Path(model.trainer.best).is_file() else None
    if best is None:
        sys.exit("Training finished but no best.pt was found; nothing exported.")
    onnx = Path(YOLO(str(best)).export(format="onnx", imgsz=a.imgsz, dynamic=True, simplify=True))
    info = verify_export(onnx, names)
    sha = hashlib.sha256(onnx.read_bytes()).hexdigest()
    meta = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base_weights": a.base, "epochs": a.epochs, "imgsz": a.imgsz, "seed": a.seed,
            "ultralytics_version": ultralytics.__version__, "classes": info["classes"], "dataset_fingerprint": rep["stats"].get("fingerprint"),
            "train_images": rep["stats"]["splits"]["train"]["images"], "val_images": rep["stats"]["splits"]["val"]["images"], "onnx_sha256": sha,
            "notes": "Not evaluated yet. Run ai_training/evaluate_damage_model.py to measure it; until then no performance claim applies."}
    if a.no_install:
        onnx.with_suffix(".json").write_text(json.dumps(meta, indent=2), "utf-8")
        print(f"Exported and verified {onnx} (sha256 {sha[:16]}). Not installed (--no-install).")
        return
    dest_dir = ROOT / "backend" / "models"
    dest = dest_dir / "damage_model.onnx"
    old_eval = dest_dir / "evaluation.json"
    if old_eval.is_file():
        old_eval.replace(dest_dir / "evaluation.previous.json")  # it describes the previous model, not this one
        print("Moved the old evaluation.json to evaluation.previous.json: it belongs to the previous model.")
    shutil.copy2(onnx, dest)
    (dest_dir / "damage_model.json").write_text(json.dumps(meta, indent=2), "utf-8")
    print(f"Installed {dest} (sha256 {sha[:16]}). Restart the backend, then run evaluate_damage_model.py to measure it.")


if __name__ == "__main__":
    main()
