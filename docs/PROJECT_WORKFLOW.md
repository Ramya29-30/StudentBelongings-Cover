# Project workflow

## Student journey (all steps hit real backend APIs and database records)

1. **Register** (`POST /api/auth/register`, always creates a student) and **sign in** (HttpOnly session cookie, CSRF token on writes).
2. **Dashboard**: active policies, insured assets, total coverage, monthly premium commitment, recent claims and transactions, premium-due notices.
3. **Add asset**: category, brand, model, purchase price and date, serial/IMEI/frame number, description, invoice, photograph. The form shows the eligibility result live; the server enforces it. Below the minimum the asset is rejected with an explanation.
4. **Explore plans**: all categories with minimum value, premiums, maximum coverage, exclusions, eligibility conditions, and a premium calculator.
5. **Quote and purchase**: the asset's full breakdown (annual premium, maximum coverage, estimated maximum claim, deductible, duration, exclusions) is shown before the student accepts the terms. The purchase is simulated: it creates a policy with terms frozen from the category, a policy version and the first premium transaction.
6. **Damage happens, submit a claim** (wizard): select the insured asset, incident details (date, incident type, damage type, description, optional estimate), upload up to 5 photos, submit for verification.
7. **AI evidence verification** (see `AI_VERIFICATION.md`): image quality, asset identification, damage detection, description comparison, duplicate and metadata checks, confidence and evidence assessment, explainable report stored in the database.
   * *More Evidence Required*: unusable photos or unclear damage. The student uploads better photos and runs verification again.
   * *Evidence Supported*: continue.
   * *Evidence Inconsistent / Suspicious*, or damage could not be verified by any model: **Exceptional Review Required** (staff). This is never a finding of fraud.
8. **Policy validation and decision** (separate rule engine): ten checks, amount calculation with a breakdown, automatic decision.
9. **Simulated settlement**: Approved, Settlement Processing, Settled (a `settlements` row; no money moves).
10. **History**: claim result, AI report, decision checks, calculation and status history stay available; payments are listed under Payment history.

Claim statuses: Submitted, AI Verification in Progress, More Evidence Required, AI Verification Completed, Policy Validation in Progress, Approved, Rejected, Exceptional Review Required, Settlement Processing, Settled.

## Administrator workflow
* **Overview**: students, active policies, insured assets, premium revenue, claims received, approved, rejected, pending exceptional reviews.
* **Categories and plans**: add, disable or edit eligibility, minimum value, premium, coverage, deductible, duration, waiting period, depreciation, exclusions, damage types and reference costs. Validated and audited; applies to new policies only.
* **Policies**, **Claims** (with the complete AI report, decision checks and history), **Exceptional reviews** (approve or reject with a reason; hard rule failures cannot be overridden; approval recalculates the amount from the frozen terms and settles in simulation).
* **AI analytics**: images analysed, supported, uncertain, inconsistent, average processing time, damage distribution, configuration in use, measured model metrics if an evaluation file exists (otherwise "Not measured").
* **Financial performance**: see `INSURANCE_MODEL.md`.
* Assessors use the same exceptional-review queue. The earlier manual assessor workflow (rules POL-001 to POL-013, reserves, four-eyes payments) is preserved under the admin "Legacy" pages and the assessor portal.

## Two claim paths
| | Self-service (v3, `flow=auto`) | Legacy manual (v2, `flow=manual`) |
|---|---|---|
| Who decides | The rule engine, using AI evidence as one input; staff on exceptions | A human assessor, always |
| AI role | Evidence report only; never sets an amount or a decision | Suggestions that a human must verify |
| Settlement | Simulated, automatic when all checks pass | Reserve and payment with a different approver |
