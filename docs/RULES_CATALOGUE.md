# Insurance rules catalogue

Sample rules for an academic prototype - **not** universal insurance rules. Implemented in `backend/app/engine/rules.py`; each can be disabled per plan (`disabled_rules`). Outcomes: PASS, FAIL, FLAG, PENDING, ADJUSTED, APPLIED, SKIPPED.
Every result records: rule ID, outcome, inputs used, reason, policy reference, follow-up action.

| ID | Name | Logic | Outcome / effect |
|---|---|---|---|
| POL-001 | Policy active on incident date | Cover starts on the later of start date and activation date; incident must be on/before expiry and before any cancellation date. Judged on the **incident date**, not today. | FAIL -> recommend rejection |
| POL-002 | Asset insured under policy | Asset ID must be in the insured list of the **policy version in force on the incident date**. | FAIL -> recommend rejection |
| POL-003 | Covered peril | Incident type must be in the plan's covered perils. | FAIL -> recommend rejection |
| POL-004 | Exclusions | Incident-level exclusion (incident types only) fails the claim; item-level exclusion (damage types, optional severities) removes that item's loss from the eligible amount. | FAIL (claim) or FAIL (item, amount removed) |
| POL-005 | Overall coverage limit | Amount limited to overall limit minus earlier approved payments on the policy. | ADJUSTED |
| POL-006 | Per-item limit | Limit per asset category (or default), optionally capped at declared value, minus earlier payments on that asset. | ADJUSTED |
| POL-007 | Deductible | Fixed amount or percentage (of the amount after the per-item limit). Order relative to the overall limit is configurable. | APPLIED |
| POL-008 | Mandatory evidence | Required document types per incident type; the asset's proof-of-purchase reference satisfies `proof_of_purchase`. | PENDING -> "Pending Information" |
| POL-009 | Asset in claimant's inventory | Asset must belong to the claimant and must have been purchased on/before the incident date. | FLAG |
| POL-010 | Duplicate / overlapping claim | Other non-draft, non-rejected claim for the same asset within `duplicate_window_days`. | FLAG -> manual review |
| POL-011 | Waiting period | Incident must be at least `waiting_period_days` after cover start. | FAIL |
| POL-012 | Priced damage items | Every item needs a catalogue/assessor price; "Inspect Further" or missing price is never guessed. No items = pending. | PENDING |
| POL-013 | AI suggestions verified | Items still `AI Suggested` or `Student Declared` (not yet reviewed by an assessor) block completion of the assessment. | PENDING |

Recommendation precedence: blocking FAIL -> `RECOMMEND_REJECTION`; any PENDING -> `PENDING_INFORMATION`; any FLAG -> `MANUAL_REVIEW`; payable 0 -> `RECOMMEND_REJECTION`; otherwise `RECOMMEND_APPROVAL_REVIEW`. All are recommendations; a human assessor decides.

## Calculation sequence (`engine/calculator.py`)
1. Gross per item = parts + labour (only priced items).
2. Item-level exclusions -> eligible 0 (POL-004).
3. Depreciation if enabled: `min(max%, rate% x completed years of age at incident)` on `replace` items (or `all`) (POL-007A).
4. Subtotal of eligible amounts.
5. Per-item limit (POL-006).
6. Order depends on `calc_order`:
   * `LIMIT_THEN_DEDUCTIBLE` (baseline): `payable = max(0, min(amount, remaining overall limit) - deductible)`
   * `DEDUCTIBLE_THEN_LIMIT`: `payable = min(max(0, amount - deductible), remaining overall limit)`
7. If a blocking rule failed, payable = 0 and the reason is shown.

Worked examples (from the tests): screen 4,000 + labour 500 = 4,500; deductible 1,500 -> **3,000**. Replacement 42,000, 2 years old, 10%/yr -> depreciation 8,400 -> 33,600; deductible 1,000 -> **32,600**. 10,000 loss, 10% deductible, 5,000 remaining limit: baseline order -> **4,000**, deductible-first -> **5,000**.
