# Known limitations (v2.1)

Read this before relying on the application for anything beyond a demonstration or coursework.

## It is a prototype, not production software
Passing the tests does not make it production-ready. Still outstanding: an independent security review and penetration test, load and concurrency testing, HTTPS deployment verified end to end, secrets management, monitoring/alerting, and a restore drill for backups. See `SECURITY_REVIEW.md` section 4 and `DEPLOYMENT.md`.

## Not Guidewire, not insurance advice
* It is **not** Guidewire software and calls no Guidewire API. `gosu/ClaimRules.gs` is an **uncompiled** port of the pure rule logic; the Guidewire names in `GUIDEWIRE_MAPPING.md` are conceptual and unverified. The adapter to real entities is not written.
* Rules, prices, deductibles and wording are fictional samples. Nothing here is insurance, legal or financial advice.

## Payments, AI and external services
* **Payments are simulated.** "Paid" means a simulated settlement was recorded. No bank, card or gateway exists.
* **AI has never been run against a real provider** (no key was available). The Anthropic, OpenAI and OpenAI-compatible adapters are tested only with mock transports; model names, endpoints and response shapes may need adjusting. Without a provider the app uses a labelled keyword-based demo fallback, which is not AI.
* AI image/quotation analysis needs a vision-capable model; text and CSV quotation parsing uses a simple regex fallback.

## Environment and platform coverage
* Automated tests ran on **Linux with SQLite and Chromium only**. The Windows scripts (`start.bat`, `build-frontend.bat`, `run-tests.bat`, `run-e2e.bat`, `backup.bat`) were written to be safe but **were not executed on Windows**. Firefox, Safari/WebKit and real mobile devices were not tested (responsive checks emulate viewports in Chromium).
* **PostgreSQL has not been tested.** `app.cli backup` supports SQLite only.
* **Docker files were not built or run.**
* The `COOKIE_SECURE=true` path over real HTTPS was not exercised in a browser.

## Authentication and access
* No multi-factor authentication, no email-based password reset (an administrator resets passwords), no lockout notification. Password policy is length, no username inside, and a five-entry blocklist; there is no breached-password check.
* Login rate limiting is database-backed, intended for a single worker process. Behind a reverse proxy set `TRUST_PROXY=true` only if the proxy is trusted.
* Demo accounts with well-known passwords exist whenever `SEED_DEMO_DATA=true` (the default outside production). Production refuses to start with it on.
* The client-side route guard is a usability aid; the backend enforces all authorization.

## Functional limits
* One asset per claim. A student cannot declare several assets in one claim.
* **Student-declared damage items** carry no price and no repair decision by design; an assessor must verify or correct them. Students cannot edit them after submission.
* Prior payments for limit calculations use the estimated payable of earlier claims, not settled amounts.
* Policy expiry is evaluated lazily when policies are read, not by a scheduled job.
* No virus scanning of uploads; evidence is stored on local disk.
* There is no notification system (email/SMS) and no activity/task engine.
* The administrator "assign claim" screen lists assessors from the user list; there is no workload balancing.
* The UI is English only; currency is INR.

## Accessibility
Automated axe WCAG A/AA checks, keyboard tests and layout checks passed (see `TESTING.md`). Manual screen-reader testing, user testing and a formal conformance audit were **not** done, so no conformance claim is made.

## Legacy UI
The old plain-JS interface (it kept a token in `sessionStorage` and needed inline scripts) was **removed from the package** in the security audit. It is still inside your original `StudentBelongingsCover_Complete.zip` if you need it for reference. Do not deploy it.

## Launch blockers that remain (see `SECURITY_AUDIT_REPORT.md`)
No custom domain is connected, the `LEGAL_*` operator details are empty, the Privacy Policy and Terms have not been reviewed by a lawyer, Git history could not be audited (no `.git` folder was supplied), there is no malware scanning of uploads, and no independent penetration test has been done.

## Resolved in v2.1 (previously listed here)
React/TypeScript/Vite frontend, UI for reserves, payments, users, administration, settings and assigned claims, Playwright suite, Gosu review and mapping rewrite, dependency audits (frontend now 0 advisories), Docker files (untested), deployment/backup documentation, strict CSP, `.env` comment parsing bug.

## v3 self-service product (InsurTech upgrade)
* No damage model ships with the package; automatic damage verification needs one you train or a vision provider you configure (untested with a live provider). See `AI_VERIFICATION.md`.
* The bundled COCO detector knows laptops, phones and bicycles only; tablets, earbuds and smartwatches cannot be identified from the image.
* `AI_VERIFY_MODE=dev_simulation` analyses nothing about damage; it is for demonstration and is blocked in production.
* The v3 Playwright spec was written but not executed; the v2 Playwright specs no longer match the student UI and are not run by default.
* Prices, repair costs and finance assumptions are sample values. Demo finance data is tiny and shows deficits.
* Uploaded photos keep their EXIF inside the stored file. Registration is open and throttled only.
* Self-service claims no longer settle automatically by default: a claim that passes every check waits for a staff member (`AUTO_APPROVAL=off`). `AUTO_APPROVAL=verified_only` allows rule-engine approval only with a trained, evaluated damage model, a strong device match and no risk indicators (see `EVIDENCE_AND_FRAUD_CHECKS.md`). The legacy manual workflow still requires a human.

## CoverMate AI
* The chat provider adapters have only been run against mock HTTP transports. Add your key and ask a few real questions before relying on them.
* Answers can still be wrong. The amount check flags only rupee figures that are not in the official data.
* Existing databases keep their stored category prices. Only new databases get the default catalogue.

## v4 evidence and fraud checks
* No damage model was trained, so there is **no measured damage accuracy, precision, recall or mAP**. The analytics page says "Not measured" until you run `ai_training/evaluate_damage_model.py`.
* Registered-device matching uses classical keypoint matching, not a learned embedding. It was tested only on synthetic images; its thresholds are uncalibrated heuristics and real-world accuracy is unknown. It cannot prove two photos show the same physical device, and a weak result is not proof of a different one.
* Reading visible serial numbers, IMEIs, brands and models needs a vision-language provider; that path was tested only with a stub, never against a live provider, and OCR can misread characters.
* Error-level analysis is a weak heuristic with many false alarms and no effect on routing beyond a low-severity note. Duplicate detection finds only identical and near-identical copies, not edited or re-photographed ones.
* Missing camera metadata is never a risk indicator, and present metadata can be edited.
* The registration review is a human check of photographs and an invoice that the system does not verify against the seller. An invoice is optional ("where available"); approving without one needs a written reason.
* Assets registered before the upgrade are `Approved` only if they already had an active policy; every other self-service asset must be reviewed before it can be insured. An item with an active policy cannot be re-reviewed.
* Existing databases keep their stored categories: add "Broken hinge" to the Laptop damage types in the admin page by hand, and replace the sample reference cost.
* Playwright end-to-end specs were not run in this environment and may need selectors updated for the new registration form.
