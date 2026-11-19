# AI damage verification

This is the most important part to understand honestly: **what is real, what needs setup, and what is not possible**.

## What is real in this build
| Stage | Implementation | Machine learning? |
|---|---|---|
| Image quality (blur, darkness, exposure, resolution, corruption) | OpenCV measurements: Laplacian variance, mean luminance, contrast, size. Thresholds are configurable. | No. Classical computer vision. |
| Asset identification | **YOLO11n object detector** (`backend/models/yolo11n.onnx`, COCO-pretrained) run with `onnxruntime` on CPU (works on Windows). Letterbox preprocessing, YOLO decoding, per-class NMS. | **Yes**, but COCO has only three useful classes: laptop, cell phone, bicycle. |
| Damage detection | A **user-trained ONNX damage detector** (`backend/models/damage_model.onnx`, not shipped) **or** a configured vision-language model provider. | Yes, only if you supply one of them. |
| Description comparison | Keyword rules comparing the written description and declared damage with what was detected. | No. Labelled "rule-based" in every report. |
| Duplicate evidence | SHA-256 (exact), plus a difference hash **and** a DCT hash that must agree (near-duplicate), against all earlier claim images **and all registration photographs**. | No. |
| Metadata and manipulation | EXIF capture date vs the incident and purchase dates, editing-software name, and a weak error-level heuristic on JPEGs. Missing EXIF is normal and ignored. | No. |
| Registered-device matching | ORB keypoints with RANSAC geometry, claim photos against the registered front/back photos; optional vision-model reading of visible serial, IMEI, brand and model. Thresholds uncalibrated until you run `ai_training/evaluate_device_matching.py`. | No learned model. |

The vision-language provider path is implemented against the existing provider layer but **was not exercised against a live provider** in this build (no API key); it is covered only by the code path for "not configured". Treat it as untested until you run it with your own key.

Verified here: the detector loads and runs real inference (on a public sample photo it found a bus at 94% and four people), the pipeline reads real EXIF, scores real quality, and the whole flow persists a report. **Not verified: any laptop, phone, tablet or damaged-device photo, because none was available in the build environment.** No damage model exists in this package, so **damage is never detected automatically out of the box**.

## What is NOT possible, and what the system does instead
* The pretrained model **cannot see damage**. It has no class for cracked screens, bent frames and so on. The app does not pretend otherwise: with no damage model and no vision provider, the damage check returns **"Unable to verify"** and the claim goes to **Exceptional Review Required** for a person. It is not rejected.
* There is **no tablet, earbuds or smartwatch class** in COCO. For these, asset identification is "Unable to verify" (a tablet seen as laptop or phone is not treated as a mismatch).
* A photo **cannot prove ownership, a serial number, or honesty**. The system looks for visual consistency and risk indicators only. Model confidence is never treated as proof of truth or fraud. Duplicates and odd metadata are *indicators for review*, not accusations, and never reject a claim.
* No fabricated predictions or confidences exist anywhere. Where a number is not available, the report says "not available".

## Modes (the report always states which one produced it)
| `AI_VERIFY_MODE` | Behaviour |
|---|---|
| `auto` (default, required in production) | Real analysis. Damage via trained ONNX model, else vision-language provider (`AI_PROVIDER`, `AI_API_KEY`, `AI_VISION_MODEL`; its confidence is self-reported and uncalibrated, and it gives no boxes), else "Unable to verify". |
| `dev_simulation` (**demo only**) | Asset and damage are **assumed from the claim form** so the complete workflow can be shown without a model. Confidences are `null`, not invented. Image quality, duplicate and metadata checks are still real. Every report and claim page carries a prominent banner, `is_simulated=true` is stored, and **the server refuses to start in production with this value**. |

## Outcomes
1. **Evidence Supported**: usable photos, declared damage matches what was detected, no blocking inconsistency. The claim proceeds to the policy rules.
2. **More Evidence Required**: poor quality, unclear damage, or damage could not be verified. The student can upload more (up to `MAX_VERIFICATION_RUNS`, then staff review). If no model can ever verify damage in this deployment the claim goes straight to staff review instead of looping.
3. **Evidence Inconsistent / Suspicious**: a different asset is confidently detected (confidence at least 0.6 and the object fills at least 20% of the frame), the description names a different asset, declared and detected damage differ, or a high-severity indicator (identical image seen in another claim). Next step: **staff review**.

The report stores: mode, model files and hashes, per-image quality, asset identification, damage detections with boxes where the model gives them, description check, duplicate check, evidence completeness, risk indicators, outcome, route, explanation, next step and processing time. Students see the image with detection boxes (if any), each check, the reasons and the next step. Other students' claim numbers are never revealed in duplicate findings.

## Architecture
`app/ai/vision.py` (decode, quality, hashes, EXIF, `OnnxDetector`) and `app/ai/verification.py` (stages and outcome logic) are database-free; the router supplies image bytes and earlier fingerprints. The claim decision lives in `app/engine/decision.py` and only *reads* the report's outcome. To replace the model, drop a YOLO-format ONNX file at `backend/models/damage_model.onnx` (class names in its metadata, or a `damage_model.json` sidecar with `{"classes": [...]}`) or implement another provider behind `detect_damage`.

## Training and evaluation
See `ai_training/README.md`. Dataset layout is YOLO format; `train_damage_model.py` fine-tunes YOLO11n with Ultralytics and exports ONNX; `evaluate_damage_model.py` measures precision and recall per class at IoU 0.5 and writes `backend/models/evaluation.json`, which the admin AI analytics page then shows. **The training script was not run** (no dataset or PyTorch in the build environment); the evaluation script was run once on the COCO model to check its mechanics, which is not a performance result. Until an evaluation file exists the analytics page says "Not measured".

## Model limitations
* COCO model: 80 classes, trained on everyday photos; it can miss a small or partly visible phone and may confuse tablets.
* Any damage model only knows the damage styles in its training data and degrades on other devices, lighting and angles. Photos of a screen that is off or covered in glare are hard.
* Blur and darkness thresholds are heuristics tuned on synthetic images only.
* Perceptual hashes catch resizes and recompression, not a different photo of the same device.
* The bundled YOLO weights are AGPL-3.0; review that licence before any use beyond academic work.


## v4 addition: evidence, device matching and the four outcomes
Registration evidence, the review that gates policy activation, the fraud layers, the four-way workflow outcome (*Evidence appears consistent*, *More evidence required*, *Suspicious evidence - manual review*, *Unable to verify - manual review*), the rule that AI never authorises a payout (`AUTO_APPROVAL`, default `off`), the extended admin analytics and the migration are described in `EVIDENCE_AND_FRAUD_CHECKS.md`. Training, evaluation and dataset preparation: `ai_training/README.md`. Still true: no damage model ships, and no damage accuracy figure exists until you train and evaluate one.
