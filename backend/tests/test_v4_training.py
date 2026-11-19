"""Training pipeline: dataset validation, the detection metrics, and the evaluation script.

Datasets built here are tiny SYNTHETIC fixtures (blank images and hand-written boxes). They exist to prove that the validators and the metric maths are right.
No model quality is measured or implied by anything in this file.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.stub_onnx import CLASSES, build

ROOT = Path(__file__).resolve().parents[2]
TRAIN = ROOT / "ai_training"
sys.path.insert(0, str(TRAIN))
import dataset_tools as dt  # noqa: E402
from detection_metrics import compute_ap, evaluate_detections, iou  # noqa: E402

BOX = "0 0.5 0.5 0.15625 0.208333"  # the box the stub detector always reports (class 0)


def make_image(path: Path, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rnd = np.random.default_rng(seed)
    Image.fromarray(rnd.integers(0, 255, (96, 128, 3), dtype=np.uint8)).save(path)


def make_dataset(root: Path, train=6, val=3, classes=CLASSES, label="0 0.5 0.5 0.2 0.2", labels_for_all=True) -> Path:
    (root).mkdir(parents=True, exist_ok=True)
    (root / "classes.txt").write_text("\n".join(classes) + "\n")
    n = 0
    for split, count in (("train", train), ("val", val)):
        for i in range(count):
            n += 1
            make_image(root / "images" / split / f"img{n}.png", n)
            (root / "labels" / split).mkdir(parents=True, exist_ok=True)
            if labels_for_all or i % 2 == 0:
                # every class appears in both splits so the coverage checks pass
                lines = "\n".join(f"{c} 0.5 0.5 0.2 0.2" for c in range(len(classes))) if i == 0 else label
                (root / "labels" / split / f"img{n}.txt").write_text(lines + "\n")
    return root


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd, timeout=300)


# ======================================================================= metrics
def test_iou_and_ap_match_hand_computed_values():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0 and iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    # TP, FP, TP over two ground truths: recall .5,.5,1  precision 1,.5,.667  ->  (51*1.0 + 50*0.6667)/101
    assert compute_ap([0.5, 0.5, 1.0], [1.0, 0.5, 2 / 3]) == pytest.approx((51 + 50 * 2 / 3) / 101, abs=1e-6)
    assert compute_ap([], []) == 0.0


def test_perfect_detector_scores_one_everywhere_it_has_ground_truth():
    truths = [("a", 0, (0, 0, 10, 10)), ("b", 0, (0, 0, 10, 10)), ("b", 1, (20, 20, 30, 30))]
    preds = [("a", 0, 0.9, (0, 0, 10, 10)), ("b", 0, 0.8, (0, 0, 10, 10)), ("b", 1, 0.7, (20, 20, 30, 30))]
    r = evaluate_detections(preds, truths, ["x", "y", "unused"])
    assert r["overall"]["map50"] == 1.0 and r["overall"]["map50_95"] == 1.0 and r["overall"]["f1"] == 1.0 and r["overall"]["classes_averaged"] == 2
    unused = r["per_class"]["unused"]
    assert unused["instances"] == 0 and unused["ap50"] is None and unused["recall"] is None and unused["f1"] is None  # no ground truth: not measured, not zero


def test_false_alarms_misses_and_the_confusion_matrix():
    truths = [("a", 0, (0, 0, 10, 10)), ("b", 0, (0, 0, 10, 10)), ("b", 1, (20, 20, 30, 30))]
    preds = [("a", 0, 0.9, (0, 0, 10, 10)), ("b", 0, 0.8, (0, 0, 10, 10)), ("b", 0, 0.6, (50, 50, 60, 60))]  # class 1 missed, one false alarm of class 0
    r = evaluate_detections(preds, truths, ["x", "y"])
    x, y = r["per_class"]["x"], r["per_class"]["y"]
    assert (x["tp"], x["fp"], x["fn"]) == (2, 1, 0) and x["precision"] == pytest.approx(0.6667, abs=1e-4) and x["recall"] == 1.0 and x["f1"] == 0.8
    assert x["ap50"] == 1.0  # the false alarm ranks below both true positives
    assert (y["tp"], y["fn"]) == (0, 1) and y["recall"] == 0.0 and y["ap50"] == 0.0
    assert r["confusion_matrix"]["labels"] == ["x", "y", "background"]
    assert r["confusion_matrix"]["matrix"] == [[2, 0, 0], [0, 0, 1], [1, 0, 0]]  # rows true, columns predicted; y missed, one false alarm of x


def test_wrong_class_is_counted_in_the_confusion_matrix_and_loose_boxes_lower_map5095():
    truths = [("a", 0, (0, 0, 10, 10))]
    r = evaluate_detections([("a", 1, 0.9, (0, 0, 10, 10))], truths, ["x", "y"])
    assert r["confusion_matrix"]["matrix"][0][1] == 1 and r["per_class"]["x"]["fn"] == 1 and r["per_class"]["y"]["fp"] == 1
    loose = evaluate_detections([("a", 0, 0.9, (0, 0, 10, 7))], truths, ["x"])  # IoU 0.7: right at 0.5, wrong at 0.75 and above
    assert loose["per_class"]["x"]["ap50"] == 1.0 and 0.3 < loose["per_class"]["x"]["ap50_95"] < 0.7


# ======================================================================= dataset validation
def test_a_well_formed_dataset_has_no_errors(tmp_path):
    rep = dt.validate_dataset(make_dataset(tmp_path / "d"))
    assert rep["errors"] == [] and rep["stats"]["splits"]["train"]["images"] == 6 and len(rep["stats"]["fingerprint"]) == 64
    assert rep["stats"]["splits"]["val"]["instances_per_class"]["Broken hinge"] == 1


def test_class_names_are_validated(tmp_path):
    d = make_dataset(tmp_path / "d", classes=CLASSES[:5] + ["Exploded phone"])
    assert any("not in the application's damage classes" in e for e in dt.validate_dataset(d)["errors"])
    assert dt.validate_dataset(d, allow_extra_classes=True)["errors"] == []
    dup = make_dataset(tmp_path / "dup", classes=["Cracked screen", "cracked  screen"] + CLASSES[2:])
    assert any("same class" in e for e in dt.validate_dataset(dup)["errors"])
    missing = dt.validate_dataset(tmp_path / "missing")
    assert len(missing["errors"]) == 1 and "classes.txt not found" in missing["errors"][0]


@pytest.mark.parametrize("bad,fragment", [("9 0.5 0.5 0.2 0.2", "class id"), ("0 1.5 0.5 0.2 0.2", "normalised"), ("0 0.5 0.5 0 0.2", "zero width"), ("0 0.95 0.5 0.2 0.2", "outside the image"),
                                         ("0 0.1 0.1 0.2 0.2 0.3 0.3 0.4 0.4", "expected 5 values"), ("0 a b c d", "non-numeric"), ("-1 0.5 0.5 0.2 0.2", "class id")])
def test_bad_annotations_are_reported_with_file_and_line(tmp_path, bad, fragment):
    d = make_dataset(tmp_path / "d")
    (d / "labels" / "train" / "img2.txt").write_text(bad + "\n")
    errs = dt.validate_dataset(d)["errors"]
    assert any(fragment in e and "img2.txt:1" in e for e in errs), errs


def test_duplicate_lines_unreadable_images_and_coverage_gaps(tmp_path):
    d = make_dataset(tmp_path / "d")
    (d / "labels" / "train" / "img3.txt").write_text("0 0.5 0.5 0.2 0.2\n0 0.5 0.5 0.2 0.2\n")
    (d / "images" / "train" / "img4.png").write_bytes(b"not an image")
    errs = dt.validate_dataset(d)["errors"]
    assert any("duplicate of an earlier line" in e for e in errs) and any("img4.png" in e and "unreadable" in e for e in errs)
    # a class that is annotated in training only cannot be measured
    (d2 := make_dataset(tmp_path / "e"))
    for f in (d2 / "labels" / "val").glob("*.txt"):
        f.write_text("1 0.5 0.5 0.2 0.2\n")
    assert any("'Broken hinge' appears in training but not in validation" in e for e in dt.validate_dataset(d2)["errors"])


def test_the_same_file_in_train_and_val_is_a_leak_error(tmp_path):
    d = make_dataset(tmp_path / "d")
    (d / "images" / "val" / "leak.png").write_bytes((d / "images" / "train" / "img1.png").read_bytes())
    (d / "labels" / "val" / "leak.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    assert any("more than one split" in e for e in dt.validate_dataset(d)["errors"])


def test_no_negative_images_and_missing_application_classes_are_warnings(tmp_path):
    d = make_dataset(tmp_path / "d", classes=["Cracked screen", "Damaged body"])
    w = dt.validate_dataset(d)["warnings"]
    assert any("no negative images" in x for x in w) and any("can never be detected" in x for x in w)


def test_validate_cli_and_train_script_stop_on_errors_without_training(tmp_path):
    good, bad = make_dataset(tmp_path / "good"), make_dataset(tmp_path / "bad")
    (bad / "labels" / "train" / "img2.txt").write_text("0 7 7 7 7\n")
    assert run(TRAIN / "validate_dataset.py", "--data", good).returncode == 0
    r = run(TRAIN / "validate_dataset.py", "--data", bad)
    assert r.returncode == 1 and "ERROR" in r.stdout
    assert run(TRAIN / "train_damage_model.py", "--data", good, "--validate-only").returncode == 0
    t = run(TRAIN / "train_damage_model.py", "--data", bad)
    assert t.returncode != 0 and "Fix the dataset errors" in (t.stderr + t.stdout)


@pytest.mark.skipif(importlib.util.find_spec("ultralytics") is not None, reason="ultralytics is installed: this test would start a real training run")
def test_training_explains_how_to_install_ultralytics_when_missing(tmp_path):
    t = run(TRAIN / "train_damage_model.py", "--data", make_dataset(tmp_path / "d"))
    assert t.returncode != 0 and "pip install ultralytics" in (t.stderr + t.stdout)


def test_prepare_dataset_remaps_classes_splits_by_group_and_records_licences(tmp_path):
    src_img, src_lab = tmp_path / "src" / "images", tmp_path / "src" / "labels"
    for i in range(10):
        make_image(src_img / f"p{i}.jpg", 100 + i)
        (src_lab).mkdir(parents=True, exist_ok=True)
        (src_lab / f"p{i}.txt").write_text("0 0.5 0.5 0.2 0.2\n1 0.3 0.3 0.1 0.1\n")
    (tmp_path / "src" / "names.txt").write_text("crack\nscratch\n")
    (tmp_path / "map.json").write_text(json.dumps({"crack": "Cracked screen", "scratch": None}))
    out = tmp_path / "out"
    r = run(TRAIN / "prepare_dataset.py", "--out", out, "--yolo", src_img, src_lab, tmp_path / "src" / "names.txt", "--map", tmp_path / "map.json", "--licence", "CC BY 4.0",
            "--source-url", "https://example.org/data", "--name", "phones", "--val-fraction", "0.3")
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "manifest.json").read_text())
    assert man["sources"][0]["licence"] == "CC BY 4.0" and man["dropped_source_classes"] == {"phones:scratch": 10} and len(man["images"]) == 10
    labels = [ln for f in (out / "labels").rglob("*.txt") for ln in f.read_text().splitlines()]
    assert len(labels) == 10 and all(ln.startswith("0 ") for ln in labels)  # "scratch" dropped, "crack" became class 0
    assert len(list((out / "images" / "val").glob("*"))) == 3
    refused = run(TRAIN / "prepare_dataset.py", "--out", tmp_path / "x", "--yolo", src_img, src_lab, tmp_path / "src" / "names.txt", "--map", tmp_path / "map.json")
    assert refused.returncode != 0 and "--licence" in refused.stderr  # licence and origin are mandatory


# ======================================================================= evaluation script (with the stub detector: tests the machinery, not a model)
def test_evaluation_script_measures_the_stub_and_records_model_and_dataset(tmp_path):
    d = make_dataset(tmp_path / "d", train=2, val=4)
    for i, f in enumerate(sorted((d / "labels" / "val").glob("*.txt"))):
        f.write_text((BOX if i < 3 else BOX.replace("0 ", "3 ", 1)) + "\n")  # three boxes the stub gets right, one it labels with the wrong class
    model = build(tmp_path / "stub.onnx", class_idx=0, score=0.9)
    out = tmp_path / "evaluation.json"
    r = run(TRAIN / "evaluate_damage_model.py", "--data", d, "--split", "val", "--model", model, "--out", out)
    assert r.returncode == 0, r.stderr + r.stdout
    ev = json.loads(out.read_text())
    assert ev["split"] == "val" and ev["images"] == 4 and ev["instances"] == 4 and len(ev["model_sha256"]) == 64 and len(ev["dataset"]["fingerprint"]) == 64
    c0, c3 = ev["per_class"]["Cracked screen"], ev["per_class"]["Camera lens damage"]
    assert (c0["tp"], c0["fp"], c0["fn"]) == (3, 1, 0) and c0["precision"] == 0.75 and c0["recall"] == 1.0
    assert (c3["tp"], c3["fn"]) == (0, 1) and c3["recall"] == 0.0
    assert ev["per_class"]["Broken hinge"]["ap50"] is None  # nothing to measure in this split
    assert ev["confusion_matrix"]["matrix"][3][0] == 1 and "note" in ev


def test_evaluation_script_refuses_to_guess(tmp_path):
    d = make_dataset(tmp_path / "d")
    stub = build(tmp_path / "stub.onnx")
    out = tmp_path / "evaluation.json"
    no_model = run(TRAIN / "evaluate_damage_model.py", "--data", d, "--model", tmp_path / "nope.onnx", "--out", out)
    assert no_model.returncode != 0 and "Nothing was written" in (no_model.stderr + no_model.stdout) and not out.exists()
    train = run(TRAIN / "evaluate_damage_model.py", "--data", d, "--split", "train", "--model", stub, "--out", out)
    assert train.returncode != 0 and "training split" in (train.stderr + train.stdout) and not out.exists()
    other = make_dataset(tmp_path / "o", classes=["Cracked screen", "Damaged body"])
    mism = run(TRAIN / "evaluate_damage_model.py", "--data", other, "--model", stub, "--out", out)
    assert mism.returncode != 0 and "differ" in (mism.stderr + mism.stdout) and not out.exists()
    empty = make_dataset(tmp_path / "e", labels_for_all=False)
    for f in (empty / "labels" / "val").glob("*.txt"):
        f.write_text("")
    none = run(TRAIN / "evaluate_damage_model.py", "--data", empty, "--model", stub, "--out", out)
    assert none.returncode != 0 and "no ground-truth boxes" in (none.stderr + none.stdout) and not out.exists()


# ======================================================================= device-matching calibration script (mechanics, on synthetic pairs)
def test_roc_auc_and_threshold_table_match_hand_computed_values():
    sys.path.insert(0, str(TRAIN))
    from evaluate_device_matching import roc_auc, suggest, threshold_table
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert roc_auc([0.5, 0.5], [1, 0]) == 0.5  # ties count half
    assert roc_auc([0.5, 0.6], [1, 1]) is None  # needs both classes
    t = threshold_table([0.9, 0.6, 0.4, 0.1], [1, 0, 1, 0], grid=[0.5, 0.8])
    assert t[0] == {"threshold": 0.5, "precision": 0.5, "recall": 0.5, "false_positive_rate": 0.5, "flagged_pairs": 2}
    assert t[1]["precision"] == 1.0 and t[1]["recall"] == 0.5
    assert suggest(t, 0.95)["strong"] == 0.8


def test_device_matching_calibration_refuses_too_few_pairs_and_records_results_otherwise(tmp_path):
    import cv2
    from tests.helpers_v3 import textured, warped
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    rows = ["image_a,image_b,same_item"]
    for i in range(22):
        base = textured(500 + i)
        cv2.imwrite(str(pairs / f"a{i}.png"), base)
        cv2.imwrite(str(pairs / f"b{i}.png"), warped(base))
        cv2.imwrite(str(pairs / f"c{i}.png"), textured(900 + i, None))
        rows += [f"a{i}.png,b{i}.png,1", f"a{i}.png,c{i}.png,0"]
    csv_path = pairs / "pairs.csv"
    csv_path.write_text("\n".join(rows) + "\n")
    out = tmp_path / "device_match_evaluation.json"
    r = run(TRAIN / "evaluate_device_matching.py", "--pairs", csv_path, "--out", out)
    assert r.returncode == 0, r.stderr + r.stdout
    ev = json.loads(out.read_text())
    assert ev["pairs"] == 44 and ev["same_item_pairs"] == 22 and ev["different_item_pairs"] == 22 and ev["auc"] > 0.95 and "uncalibrated" not in json.dumps(ev["note"])
    assert ev["suggested"]["note"].startswith("Suggestions only") and ev["currently_configured"]["strong"] > ev["currently_configured"]["partial"]
    few = pairs / "few.csv"
    few.write_text("\n".join(rows[:7]) + "\n")
    out2 = tmp_path / "few.json"
    r2 = run(TRAIN / "evaluate_device_matching.py", "--pairs", few, "--out", out2)
    assert r2.returncode != 0 and "Not enough labelled pairs" in (r2.stderr + r2.stdout) and not out2.exists()
