"""Real image-analysis components: quality measurement, fingerprints, ONNX detector, metadata."""
import io
from datetime import date

import numpy as np
import pytest
from PIL import Image

from app.ai import vision, verification
from tests.helpers_v3 import make_img


def bgr(data):
    return vision.decode(data)[1]


def test_quality_measures_blur_darkness_and_resolution():
    good = vision.assess_quality(bgr(make_img(1)))
    assert good["usable"] and good["score"] >= 70
    assert "blurry" in " ".join(vision.assess_quality(bgr(make_img(1, blur=True)))["issues"])
    assert "dark" in " ".join(vision.assess_quality(bgr(make_img(1, dark=True)))["issues"])
    assert "resolution" in " ".join(vision.assess_quality(bgr(make_img(1, size=(200, 150))))["issues"])
    assert vision.assess_quality(bgr(make_img(1, blur=True)))["score"] < 50


def test_decode_rejects_garbage_and_truncated_files():
    for bad in (b"", b"not an image", make_img(1)[:60]):
        with pytest.raises(vision.ImageError):
            vision.decode(bad)


def test_fingerprints_exact_and_near_duplicates():
    a = make_img(3)
    assert vision.sha256(a) == vision.sha256(make_img(3)) != vision.sha256(make_img(4))
    im = Image.open(io.BytesIO(a)); buf = io.BytesIO(); im.resize((320, 240)).save(buf, "JPEG", quality=70)
    assert vision.hamming(vision.dhash(bgr(a)), vision.dhash(bgr(buf.getvalue()))) <= 5  # resized + recompressed copy still matches
    assert vision.hamming(vision.dhash(bgr(make_img(3))), vision.dhash(bgr(make_img(77)))) > 5


def test_exif_reading_and_metadata_inconsistency_indicator():
    im = Image.new("RGB", (400, 400), (120, 120, 120)); ex = im.getexif(); ex[0x010F] = "TestCam"; ex[0x0132] = "2020:01:01 10:00:00"
    buf = io.BytesIO(); im.save(buf, "JPEG", exif=ex)
    info = vision.read_exif(buf.getvalue())
    assert info["Make"] == "TestCam" and info["DateTime"].startswith("2020:01:01")
    dup, risks = verification.duplicate_checks([{"original_name": "a.jpg", "sha256": "x", "phash": "0" * 16, "exif": info}], [], date(2026, 6, 1), 1, 1)
    assert any(r["code"] == "META-DATE" and r["severity"] == "medium" for r in risks)
    assert vision.read_exif(make_img(1)) == {}  # missing metadata is normal (messaging apps strip it) and raises nothing


def test_onnx_detector_loads_real_model_and_runs_inference():
    det = vision.get_detector("asset")
    assert det is not None and len(det.names) == 80 and det.names[63] == "laptop" and det.names[67] == "cell phone" and det.names[1] == "bicycle"
    out = det.predict(bgr(make_img(1)), min_conf=0.25)  # synthetic noise: must run and return a list, never crash
    assert isinstance(out, list)
    for d in out:
        assert 0 <= d.confidence <= 1 and all(0 <= v <= 1 for v in d.box)
    assert det.info()["sha256"] and det.info()["input_size"] == 640


def test_missing_model_is_reported_not_faked(monkeypatch, tmp_path):
    monkeypatch.setattr(vision.settings, "MODEL_DIR", tmp_path)  # the settings object vision actually uses (other tests reload app.config)
    vision.reset_detectors()
    try:
        assert vision.get_detector("asset") is None and vision.get_detector("damage") is None
        r = verification.identify_asset("Laptop", [(0, bgr(make_img(1)))], "auto")
        assert r["status"] == "Unable to verify" and r["match"] == "Unable to verify" and r["confidence"] is None
    finally:
        vision.reset_detectors()


def test_asset_identification_logic_with_a_stub_detector(monkeypatch):
    class Stub:
        def __init__(self, dets): self.dets = dets
        def info(self): return {"file": "stub.onnx", "sha256": "0"}
        def predict(self, img, min_conf=None, iou=0.5): return self.dets
    D = vision.Detection
    def run(cat, dets):
        monkeypatch.setattr(vision, "get_detector", lambda kind: Stub(dets))
        return verification.identify_asset(cat, [(0, bgr(make_img(1)))], "auto")
    assert run("Laptop", [D("laptop", 0.9, (0, 0, 1, 1))])["match"] == "Consistent"
    assert run("Smartphone", [D("laptop", 0.9, (0, 0, 1, 1))])["match"] == "Inconsistent"           # confident, large, different category
    assert run("Smartphone", [D("laptop", 0.4, (0, 0, .2, .2))])["match"] == "Unable to verify"      # weak evidence is never a mismatch
    assert run("Tablet", [D("laptop", 0.9, (0, 0, 1, 1))])["match"] == "Unable to verify"            # COCO has no tablet class
    assert run("Earbuds", [])["match"] == "Unable to verify" and "no class for earbuds" in run("Earbuds", [])["explanation"]
    assert run("Bicycle", [D("bicycle", 0.8, (0, 0, .5, .5))])["match"] == "Consistent"


def test_damage_model_path_uses_only_allowed_types_and_real_detections(monkeypatch):
    class Stub:
        def info(self): return {"file": "damage.onnx", "sha256": "abc"}
        def predict(self, img, min_conf=None, iou=0.5):
            D = vision.Detection
            return [D("cracked_screen", 0.91, (.1, .1, .6, .6)), D("unrelated_class", 0.99, (0, 0, 1, 1))]
    monkeypatch.setattr(vision, "get_detector", lambda kind: Stub() if kind == "damage" else None)
    out = verification.detect_damage("Smartphone", "Cracked screen", ["Cracked screen", "Damaged body"], [(0, bgr(make_img(1)))], [], "auto", "")
    assert out["status"] == "Detected" and [d["damage_type"] for d in out["detections"]] == ["Cracked screen"] and out["detections"][0]["confidence"] == 0.91 and out["detections"][0]["box"]
    desc = verification.compare_description("Smartphone", "Cracked screen", "My phone screen cracked", out, {"match": "Consistent"}, "onnx_model")
    assert desc["result"] == "Consistent"
    mism = verification.compare_description("Smartphone", "Damaged body", "The back is dented", out, {"match": "Consistent"}, "onnx_model")
    assert mism["result"] == "Inconsistent"
