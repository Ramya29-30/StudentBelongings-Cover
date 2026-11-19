# Damage model: dataset, training, evaluation

**Status of this folder: tooling only.** No damage dataset, model weights or evaluation result ships with the project, and none was fabricated. The bundled detector (`backend/models/yolo11n.onnx`, COCO) recognises laptops and phones but cannot see damage. Until you train or supply a damage model, the damage check reports "Unable to verify" and claims go to staff. Everything below has to be run by you, on data you source.

Why nothing was trained here: it needs a labelled damage dataset (not available offline) and, realistically, a GPU. The scripts were exercised with synthetic fixtures and a stub ONNX file to prove the machinery (validation, metrics maths, export checks, evaluation output), not the model quality.

## Classes (phones and laptops)

`classes.txt` in this folder lists the initial classes, in id order:

| id | Class | Smartphone | Laptop |
|---|---|---|---|
| 0 | Cracked screen | yes | yes |
| 1 | Broken display | yes | yes |
| 2 | Damaged body | yes | yes |
| 3 | Camera lens damage | yes | no |
| 4 | Damaged keyboard | no | yes |
| 5 | Broken hinge | no | yes |

At inference a detection is mapped to the insured category's claimable damage types by name (ignoring case and spacing), then by damage family. So "Cracked screen" counts for a laptop category that lists "Broken screen"; if a category lists two types in the same family the mapping is ambiguous and the detection is ignored rather than guessed. Detections of a type the category does not allow are ignored.

## Dataset layout (YOLO detection format)

```
ai_training/dataset/
  classes.txt                 one class name per line (copy of ai_training/classes.txt)
  images/train|val|test/*.jpg|jpeg|png
  labels/train|val|test/*.txt one file per image: "class_id cx cy w h", normalised 0..1, one line per damaged region
```
`train` and `val` are required; `test` is optional but recommended (a split never used for training or tuning gives the honest number). **Include negatives**: photos of undamaged phones and laptops with an empty or missing label file. Without them the model learns to see damage everywhere.

## Step 1: prepare the dataset

Find labelled data yourself (for example on Roboflow Universe or Kaggle: "cracked screen", "phone damage", "laptop damage"). **Check each dataset's licence** allows your use, and its label quality. A few hundred well-labelled instances per class is a minimum for a demo, thousands for real use. Include several phone and laptop models, lighting and photographers.

`prepare_dataset.py` converts YOLO-folder or COCO-JSON sources into the layout above. It remaps each source's class names to ours through a JSON map you write (unmapped classes are dropped and counted), groups near-identical photos so they never straddle train and val, and writes `manifest.json` recording every source, its licence and URL, and the SHA-256 of every image. Licence and URL are mandatory.

```
python ai_training/prepare_dataset.py --out ai_training/dataset --val-fraction 0.15 --test-fraction 0.1 \
  --yolo ~/dl/phones/images ~/dl/phones/labels ~/dl/phones/names.txt --map phones_map.json --licence "CC BY 4.0" --source-url https://... --name phones \
  --coco ~/dl/laptops/_annotations.coco.json ~/dl/laptops/images --map laptops_map.json --licence "CC BY 4.0" --source-url https://... --name laptops \
  --yolo ~/dl/undamaged/images ~/dl/undamaged/labels ~/dl/undamaged/names.txt --map empty_map.json --licence "..." --source-url https://... --name undamaged --keep-negatives
```
A class map looks like `{"crack": "Cracked screen", "broken_screen": "Broken display", "dent": "Damaged body", "scratch": null}`. If your sources are already in our layout, just copy them in.

## Step 2: validate (always before training)

```
python ai_training/validate_dataset.py --data ai_training/dataset
```
Needs only Pillow. It checks class names (against the application's classes; `--allow-extra-classes` to override), that every image decodes, every label line (five values, integer class id in range, coordinates inside 0..1 and the image, no zero-size or duplicate boxes, polygon labels flagged), orphan labels, per-class counts per split, classes missing from validation, **identical files in more than one split**, near-duplicates across splits (warning), and the absence of negatives. Exit status 1 means errors. Training refuses to start while errors remain.

## Step 3: train and export

```
pip install ultralytics          # pulls PyTorch; large download; training only (the app needs only onnxruntime)
python ai_training/train_damage_model.py --data ai_training/dataset --epochs 100 --device 0
```
It validates, fine-tunes `yolo11n.pt` (use `--base yolo11s.pt` for more capacity), exports ONNX with the class names embedded, then **loads the export with the application's own detector class** and checks the class names and output layout before installing `backend/models/damage_model.onnx` plus a metadata record `damage_model.json` (dataset fingerprint, epochs, ultralytics version, ONNX SHA-256). `--no-install` exports without replacing the installed model. An evaluation of a previous model is moved aside to `evaluation.previous.json`. Training never writes `evaluation.json`. Ultralytics YOLO is AGPL-3.0 (or commercial); the bundled COCO weights share that licence; review it before use beyond academic work.

## Step 4: evaluate (the only thing that produces numbers)

```
python ai_training/evaluate_damage_model.py --data ai_training/dataset --split test      # or val
```
Writes `backend/models/evaluation.json`, shown on **Admin, AI verification analytics**: per-class precision, recall, F1, AP@0.5 and AP@0.5:0.95; overall precision, recall, F1, mAP@0.5, mAP@0.5:0.95; and a confusion matrix. Conventions: IoU 0.5 and the application's confidence threshold (`--conf`, default `DETECTION_MIN_CONFIDENCE`) for precision, recall, F1 and the matrix; AP over all detections above `--ap-conf`, 101-point interpolation (COCO/Ultralytics style); a class with no instances in the split is reported as not measured, not zero. The file records the full SHA-256 of the model and a fingerprint of the evaluated data, and the page warns when the evaluation belongs to a different model file. Evaluating on the training split is refused (`--allow-train-split` overrides and labels the result).

Restart the backend after installing a model; the analytics page then shows it as installed with its SHA-256.

## Optional: calibrate registered-device matching

The matcher's thresholds are uncalibrated until you measure them. Build a CSV of photo pairs you labelled (`image_a,image_b,same_item`, 1 = same physical item, 0 = different item; include hard negatives such as another unit of the same model, and hard positives such as a different angle or a damaged versus undamaged view), at least 20 of each:

```
python ai_training/evaluate_device_matching.py --pairs ai_training/pairs/pairs.csv
```
It writes `backend/models/device_match_evaluation.json` (AUC, precision and recall per threshold, suggested thresholds). Suggestions are never applied automatically: set `DEVICE_MATCH_STRONG` and `DEVICE_MATCH_PARTIAL` yourself.

## Files

| File | Purpose |
|---|---|
| `classes.txt` | The six initial damage classes |
| `dataset_tools.py` | Shared: class list, dataset validation, fingerprinting |
| `prepare_dataset.py` | Convert, remap, group-split and record licences |
| `validate_dataset.py` | Validate before training |
| `train_damage_model.py` | Validate, train YOLO11, export ONNX, verify, install |
| `detection_metrics.py` | The metric maths (unit-tested against hand-computed cases) |
| `evaluate_damage_model.py` | Measure a model on a labelled split |
| `evaluate_device_matching.py` | Calibrate device-matching thresholds on labelled pairs |

Model limits that no tooling removes: a model knows only the damage styles, devices, lighting and angles in its training data; a dark or glare-covered screen is hard; confidence is the model's certainty, not proof a claim is genuine.
