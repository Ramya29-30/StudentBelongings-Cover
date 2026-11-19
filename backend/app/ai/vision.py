"""Image analysis building blocks for claim verification.

Real components (no fabricated output):
  * OnnxDetector      - runs a YOLO-format ONNX object detector with onnxruntime (CPU, works on native Windows).
                        Used with the shipped COCO model (asset identification) and, if you train one, a damage model.
  * assess_quality    - classical computer vision with OpenCV (Laplacian-variance blur, luminance, resolution). A measurement, not machine learning.
  * dhash / sha256    - duplicate-evidence fingerprints.
  * read_exif         - capture metadata if the file still has it.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageOps

from ..config import settings

log = logging.getLogger("sbc.vision")
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard: Pillow raises above 2x this
MIN_SIDE = 320


class ImageError(ValueError):
    """The file is not a readable image."""


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 as fractions of the image (0..1)

    def as_dict(self) -> dict:
        return {"label": self.label, "confidence": round(self.confidence, 4), "box": [round(v, 4) for v in self.box],
                "area_fraction": round(max(0.0, (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])), 4)}


# ------------------------------------------------------------------ decoding & fingerprints
def decode(data: bytes) -> tuple[Image.Image, np.ndarray]:
    """Decode with Pillow (applies EXIF rotation) and return (PIL RGB image, BGR numpy array). Raises ImageError."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # PIL raises many types (DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError...)
        raise ImageError(f"unreadable or corrupted image ({type(e).__name__})") from None
    return im, cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dhash(bgr: np.ndarray) -> str:
    """64-bit difference hash (hex). Near-identical re-encodes/resizes differ by a few bits."""
    g = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1") if a and b else 64


_EXIF_KEEP = {"Make", "Model", "Software", "DateTimeOriginal", "DateTime", "DateTimeDigitized"}


def read_exif(im_bytes: bytes) -> dict:
    try:
        with Image.open(io.BytesIO(im_bytes)) as im:
            raw = im.getexif()
            out = {}
            for tag_id, val in list(raw.items()) + list(raw.get_ifd(0x8769).items()):
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if name in _EXIF_KEEP:
                    out[name] = str(val)[:60]
            return out
    except Exception:
        return {}


# ------------------------------------------------------------------ quality (classical CV)
def assess_quality(bgr: np.ndarray) -> dict:
    h, w = bgr.shape[:2]
    scale = 1024 / max(h, w)
    small = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean, contrast = float(gray.mean()), float(gray.std())
    issues = []
    if min(h, w) < MIN_SIDE:
        issues.append(f"resolution too low ({w}x{h}; at least {MIN_SIDE}px on the short side)")
    if lap < settings.BLUR_MIN_LAPLACIAN_VAR:
        issues.append("image is too blurry")
    if mean < 45:
        issues.append("image is too dark")
    elif mean > 235:
        issues.append("image is overexposed")
    if contrast < 12:
        issues.append("image has almost no detail (flat or covered lens)")
    sharp = min(1.0, lap / (settings.BLUR_MIN_LAPLACIAN_VAR * 3))
    light = 1.0 - min(1.0, abs(mean - 130) / 130)
    score = round(100 * (0.6 * sharp + 0.4 * light))
    if issues:
        score = min(score, 49)
    return {"usable": not issues, "score": score, "width": w, "height": h, "sharpness_laplacian_var": round(lap, 1), "mean_luminance": round(mean, 1),
            "contrast": round(contrast, 1), "issues": issues, "method": "OpenCV measurements (not a machine-learning model)"}


# ------------------------------------------------------------------ ONNX detector
COCO_ASSET_LABELS = {"laptop": "Laptop", "cell phone": "Smartphone", "bicycle": "Bicycle"}  # the only supported-category classes in COCO


class OnnxDetector:
    """Minimal YOLOv8/YOLO11-style detector (output [1, 4+nc, anchors], boxes as cx,cy,w,h, no objectness)."""

    def __init__(self, path: Path):
        import onnxruntime as ort
        self.path = path
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.session = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        names = None
        if "names" in meta:
            try:
                names = ast.literal_eval(meta["names"])
            except (ValueError, SyntaxError):
                names = None
        sidecar = path.with_suffix(".json")
        if names is None and sidecar.is_file():
            names = {i: n for i, n in enumerate(json.loads(sidecar.read_text("utf-8")).get("classes", []))}
        if not names:
            raise RuntimeError(f"{path.name}: no class names in the model metadata and no {sidecar.name} sidecar")
        self.names = {int(k): str(v) for k, v in names.items()}
        shape = self.session.get_inputs()[0].shape
        self.size = int(shape[2]) if isinstance(shape[2], int) else int(str(meta.get("imgsz", "[640, 640]")).strip("[]").split(",")[0])
        self.input_name = self.session.get_inputs()[0].name
        self.sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.lock = threading.Lock()

    def info(self) -> dict:
        return {"file": self.path.name, "sha256": self.sha[:16], "classes": len(self.names), "input_size": self.size, "runtime": f"onnxruntime {__import__('onnxruntime').__version__}"}

    def predict(self, bgr: np.ndarray, min_conf: float | None = None, iou: float = 0.5) -> list[Detection]:
        min_conf = settings.DETECTION_MIN_CONFIDENCE if min_conf is None else min_conf
        h, w = bgr.shape[:2]
        r = min(self.size / h, self.size / w)
        nh, nw = round(h * r), round(w * r)
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        top, left = (self.size - nh) // 2, (self.size - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self.lock:
            out = self.session.run(None, {self.input_name: np.ascontiguousarray(x)})[0][0]  # [4+nc, N]
        out = out.T
        scores = out[:, 4:]
        cls = scores.argmax(1)
        conf = scores[np.arange(len(cls)), cls]
        keep = conf >= min_conf
        if not keep.any():
            return []
        b, conf, cls = out[keep, :4], conf[keep], cls[keep]
        x1, y1 = (b[:, 0] - b[:, 2] / 2 - left) / r, (b[:, 1] - b[:, 3] / 2 - top) / r
        bw, bh = b[:, 2] / r, b[:, 3] / r
        boxes = [[float(a), float(c), float(d), float(e)] for a, c, d, e in zip(x1, y1, bw, bh)]
        dets: list[Detection] = []
        for k in set(cls.tolist()):  # NMS per class
            idx = [i for i in range(len(cls)) if cls[i] == k]
            sel = cv2.dnn.NMSBoxes([boxes[i] for i in idx], [float(conf[i]) for i in idx], min_conf, iou)
            for s in np.array(sel).flatten().tolist():
                i = idx[s]
                bx, by, bw_, bh_ = boxes[i]
                dets.append(Detection(self.names.get(int(k), str(k)), float(conf[i]),
                                      (max(0.0, bx / w), max(0.0, by / h), min(1.0, (bx + bw_) / w), min(1.0, (by + bh_) / h))))
        return sorted(dets, key=lambda d: -d.confidence)


_detectors: dict[str, OnnxDetector | None] = {}
_lock = threading.Lock()


def get_detector(kind: str) -> OnnxDetector | None:
    """kind: 'asset' (COCO) or 'damage' (user-trained). Returns None when the model file is absent or unusable (logged once)."""
    with _lock:
        if kind in _detectors:
            return _detectors[kind]
        f = settings.MODEL_DIR / (settings.ASSET_MODEL_FILE if kind == "asset" else settings.DAMAGE_MODEL_FILE)
        det = None
        if f.is_file():
            try:
                det = OnnxDetector(f)
            except Exception as e:
                log.error("could not load %s model %s: %s", kind, f.name, type(e).__name__)
        else:
            log.info("%s model not found at %s", kind, f)
        _detectors[kind] = det
        return det


def reset_detectors() -> None:
    with _lock:
        _detectors.clear()
