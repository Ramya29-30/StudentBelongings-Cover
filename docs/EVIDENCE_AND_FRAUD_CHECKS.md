# Registration evidence, fraud checks and claim decisions

This document describes the v4 upgrade: evidence collected when an item is registered, the review that gates policy activation, the layered fraud checks run on claim photographs, and how their results feed the claim decision. It is written to be honest about what each check can and cannot show.

**Rule that governs everything below: the AI never authorises a payout.** Its output is evidence for the policy rule engine and for people. When evidence is uncertain or conflicting a person decides.

## 1. Registration evidence

A student registers an item (`POST /api/v2/assets`, multipart) with:

| Field | Required | Notes |
|---|---|---|
| Category, brand, model, purchase date, declared value | yes | Checked against the category's eligibility rules as before |
| Serial number or IMEI | per category (`requires_serial`) | A 15-digit IMEI that fails the Luhn checksum is shown to the reviewer as a typing hint; it never rejects |
| Short description | no | |
| Front photograph (`front_photo`; legacy name `photo` still works) | yes | JPG or PNG |
| Back photograph (`back_photo`) | to be approved | The API accepts a registration without it; staff cannot approve until it is added (`POST /api/v2/assets/{id}/evidence`). The web form requires it |
| Invoice or receipt (`invoice`) | no ("where available") | Without one, the administrator must accept the exception in writing |
| Additional photographs or documents (`extra_files`, repeatable) | no | Up to `EVIDENCE_PER_ASSET_MAX` files (default 10) in total |

Every file is validated (extension, magic bytes, decodable image, `MAX_UPLOAD_MB`), stored under a random server-generated name in `UPLOAD_DIR`, and recorded in the new `asset_evidence` table with its SHA-256, perceptual hashes, dimensions, quality measurements, camera metadata, uploader, review status and automatic observations. Files are served only through authenticated routes to the owner or staff. A new front photo, back photo or invoice replaces the old one while the registration is open; the old file is deleted from disk. Registration is atomic: if any step fails nothing is stored.

### Evidence review status (set only by administrators)

`Pending review` then `Approved`, `Rejected` or `More evidence requested`. A student has no route or form field that can set it (extra form fields are ignored). Administrators review at **Admin, Evidence review**:

* each file with a preview, its hash, camera data and the **automatic observations** (not verdicts):
  * low quality (blur, darkness, resolution);
  * byte-identical or near-identical to a file registered for another item or student (`REG-DUP-EXACT`, `REG-DUP-NEAR`);
  * front and back photographs that are the same picture (`REG-SAME-VIEW`);
  * photograph captured before the purchase date, a future capture date, editing software named in the metadata, a screenshot (`META-*`, `REG-SCREENSHOT`);
* decision: approve, request more evidence, or reject, with a note the student sees (required for anything but a plain approval);
* a request for more evidence returns the registration to the queue as soon as the student uploads something;
* once an item has an active policy its evidence can no longer be re-reviewed (an administrator who wants to change it must handle that outside this flow);
* every upload, replacement, removal and decision is written to the audit log.

### Policy activation rule

`POST /api/v2/assets/{id}/purchase` now returns **409** unless the asset's evidence status is `Approved`, in addition to all earlier checks (eligibility, terms accepted, no active policy, simulated payment). The claim rule engine also requires an approved registration (CHK-03). The student interface hides "Insure this asset" until approval and explains what is missing.

## 2. Fraud and authenticity checks on claim photographs

Each check below is a **risk indicator for a person**. Severity `high` or two `medium` indicators route a claim to staff review; `low` indicators are shown but never route anything.

| Check | Method | What it can show | What it cannot show | Effect |
|---|---|---|---|---|
| Exact duplicate | SHA-256 | A byte-identical file was submitted before (earlier claim, this item's own registration photo, another student's registration photo) | Anything about re-saved, cropped, screenshotted or recompressed copies | `high` |
| Perceptual duplicate | 64-bit difference hash **and** DCT hash must both agree (`DUP_DHASH_MAX_DISTANCE`, `DUP_PHASH_MAX_DISTANCE`) | A resized or recompressed copy of an earlier picture | Heavily edited or re-photographed copies; plain scenes can false-match | `medium` |
| Camera metadata (EXIF) | Capture date vs incident date and purchase date, editing software name, future date | A capture date that contradicts the story | **Missing EXIF is normal** (messaging apps, screenshots) and is never an indicator. Present EXIF can be edited. GPS coordinates are never read out, only whether they exist | `medium` (dates), `low` (software, future date) |
| Manipulation heuristic | Error level analysis on JPEGs | Unusually uneven recompression error | Not proof of editing: resizing and repeated saves do the same. Not applicable to PNG | `low` |
| Image quality | Blur, exposure, resolution, size | Photos too poor to analyse | Anything about authenticity | asks for better photos |
| Registered-device matching | ORB keypoints + RANSAC on device crops (section 3) | Visible local features agree or do not | That two photos show the same *physical* device | see section 3 |
| Visible serial / IMEI / brand / model | Read by the configured vision-language model, only if one is configured | A visible identifier that differs from the registration | OCR can misread; when no model is configured this check says "Not checked" | `high` (serial differs), `medium` (brand or model differs) |

## 3. Registered-device matching

Claim photographs are compared with the photographs registered for the item (front, back, additional). Method: crop each photo to the detected device when the COCO detector can see it, extract ORB keypoints, match with a ratio test, keep only matches that agree on **one** geometric transform (RANSAC homography), reject degenerate transforms, and score by the number and share of consistent matches. The report shows the best pair, the number of consistent keypoints, the band, supporting evidence and the limits.

Bands: *Strong feature agreement*, *Partial feature agreement*, *Weak or no feature agreement*, *Not enough detail to compare*, *No registered photographs*.

How the band affects the decision (in real analysis modes; in `dev_simulation` it is computed and shown but not used):

* Strong: no effect.
* Partial, weak or not enough detail: the claim gets **More evidence required** ("add clear photos of the whole item, front and back, ideally showing the serial or IMEI label"). After `MAX_VERIFICATION_RUNS` rounds it goes to staff as **Unable to verify**.
* No registered photographs, or no usable claim photo: **Unable to verify**, staff review.

Honest limits:

* Strong agreement supports, but cannot prove, that the photos show the same item: two units of one model look alike. The report never says "same device".
* A weak result is not proof of a different device (close-ups, other side, glare, damage, background).
* No learned embedding model is shipped. The thresholds `DEVICE_MATCH_STRONG` (0.55) and `DEVICE_MATCH_PARTIAL` (0.25) are **heuristic and uncalibrated** until you run `ai_training/evaluate_device_matching.py` on photo pairs you labelled; the admin page says "No" under "Calibrated" until `backend/models/device_match_evaluation.json` exists. The script suggests thresholds but never applies them.
* Checked only on synthetic images in the automated tests (identical, rotated and dimmed views match; unrelated images do not). No real device photographs were available while building this, so real-world accuracy is **unmeasured**.

## 4. Damage verification and claim authenticity are separate

The report's *Verification summary* keeps four things apart: expected device present, visible damage detected (category and confidence), description matches the image, and registered-device comparison plus authenticity flags. Its note states that detected damage describes what the software saw and does not establish that a claim is genuine.

Damage detection needs a trained model (`backend/models/damage_model.onnx`) or a configured vision-language model. With neither, the damage check says "Unable to verify" and the claim goes to staff. Detector class names are mapped to the category's claimable damage types by name, then by damage family (so a class "Cracked screen" counts for a laptop category that lists "Broken screen"); an ambiguous mapping is never guessed.

## 5. Outcomes and the decision

| Workflow outcome (new) | Stored legacy outcome | Route |
|---|---|---|
| Evidence appears consistent | Evidence Supported | on to the policy rule engine |
| More evidence required | More Evidence Required | student uploads more, up to `MAX_VERIFICATION_RUNS` |
| Suspicious evidence - manual review | Evidence Inconsistent / Suspicious | staff. This is not a finding of fraud |
| Unable to verify - manual review | More Evidence Required (route: exceptional review) | staff |

(Hyphens replace the dashes of the original brief to follow the site's copy rules.)

**No automatic payout by default.** Even when the evidence appears consistent and every policy rule passes, the claim stops at *Exceptional Review Required* with the check `RVW-01 A person confirms before any payout`, and the student is told a staff member must confirm. Staff approve through the existing review endpoint (hard rule failures still cannot be overridden). This changes the earlier behaviour where clean claims were approved and settled automatically.

`AUTO_APPROVAL=verified_only` re-enables rule-engine approval without a person, but **only** when all of these hold: a trained damage model is installed and was used, an evaluation measured on exactly that model file exists, the outcome is "appears consistent", device matching is *Strong*, and no risk indicator of any severity was raised. `dev_simulation` can never auto-approve. The default is `off`; decide deliberately before changing it.

## 6. Admin analytics (`/api/v2/ai/analytics`, admin only)

Every number is counted from stored records or read from an evaluation file; a metric that was never measured is reported as unavailable, never estimated.

* damage model availability, file, **SHA-256**, classes, input size, training record;
* the dataset evaluation (written only by `evaluate_damage_model.py`): per-class precision, recall, F1, AP@0.5, AP@0.5:0.95; overall precision, recall, F1, mAP@0.5, mAP@0.5:0.95; confusion matrix; the split, image count, thresholds and dataset fingerprint; and a warning when the evaluation belongs to a different model file than the installed one;
* workflow outcome counts (real verification runs only; simulated reports excluded);
* registered-device matching: reports compared, results by band, average best score, serial and brand/model text check counts, calibration record;
* manual review: waiting for staff, sent to manual review, decided by staff, average time to decision, approvals after a suspicious outcome, rejections after a consistent outcome, the auto-approval setting;
* registration evidence review counts and the authenticity indicators raised.

## 7. Security

* Uploads: extension, magic bytes, full decode, size cap, random server-side names, no user-controlled paths; the request-body limiter knows the new routes (registration allows up to `EVIDENCE_PER_ASSET_MAX` files, evidence upload one file).
* All evidence routes require authentication; students reach only their own items; review routes are admin only; the audit log records uploads, removals, review decisions and verification runs.
* Reviewer observations (hashes, flags, who else registered a photo) are staff-only; student-facing duplicate text never names another student.
* API keys stay in backend environment variables. The frontend receives none.
* Existing rate limits (assets per hour, uploads per hour, verification runs per hour) apply to the new routes.

## 8. Migration

`alembic upgrade head` applies revision `0006` (the application also runs it at start-up). It only adds: table `asset_evidence`; columns `assets.evidence_status`, `evidence_reviewed_by`, `evidence_reviewed_at`, `evidence_review_note`; `claim_images.phash_dct`; `claims.ai_workflow_outcome`; `ai_verification_reports.device_match`, `authenticity`, `workflow_outcome`. All have defaults. Backfill: self-service assets that already have an **active policy** become `Approved` (grandfathered, with a note); every other self-service asset becomes `Pending review` and must be reviewed before it can be insured. The photo and invoice already stored on an asset row are copied into `asset_evidence`; their fingerprints are computed the first time they are needed. Existing claims and reports are untouched; reports created before the upgrade show the legacy outcome mapped to the new labels.

Existing databases keep their stored categories: to make **Broken hinge** claimable for laptops, add it to the Laptop category's damage types in *Admin, Categories and plans* (new databases get it by default, with a sample reference cost of 4,500 that you should replace with your own).

## 9. What was verified and what was not

See `PROJECT_HANDOVER.md` (section H) for the exact test results. In short: everything above is covered by automated tests that ran, using synthetic images and a tiny stub ONNX detector. **Not done**: no damage model was trained (no dataset or GPU was available), so no damage accuracy, precision, recall or mAP exists for this project; the device-matching thresholds were not calibrated on real photographs; the vision-language reading of serial numbers was tested only with a stub, not a live provider; the Playwright end-to-end specs were not run.
