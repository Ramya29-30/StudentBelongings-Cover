"""Validate a YOLO-format damage dataset BEFORE training: class names, layout, images, annotations, split leakage, class balance.

Usage:
    python ai_training/validate_dataset.py --data ai_training/dataset
Exit status 0 = no errors (warnings may remain), 1 = errors found. Needs only Pillow.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_tools import print_report, validate_dataset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--allow-extra-classes", action="store_true", help="accept class names the application does not know")
    ap.add_argument("--json", type=Path, help="also write the full report here")
    a = ap.parse_args()
    rep = validate_dataset(a.data, allow_extra_classes=a.allow_extra_classes)
    print_report(rep)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2), "utf-8")
    sys.exit(1 if rep["errors"] else 0)


if __name__ == "__main__":
    main()
