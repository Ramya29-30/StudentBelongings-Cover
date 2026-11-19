# Model files

* `yolo11n.onnx` : Ultralytics YOLO11n, COCO-pretrained (80 classes), exported to ONNX. Used only to identify laptops, phones and bicycles in claim photos.
  Source: https://github.com/ultralytics/assets/releases (v8.3.0). Licence: AGPL-3.0 (see https://ultralytics.com/license). Bundled for academic use; review the licence before commercial use.
  If it is missing the app still runs and reports "Unable to verify" for the asset check.
* `damage_model.onnx` (optional, NOT shipped): your trained damage detector. See ../../ai_training/README.md.
* `evaluation.json` (optional): written by `ai_training/evaluate_damage_model.py`; shown on the admin AI analytics page.
