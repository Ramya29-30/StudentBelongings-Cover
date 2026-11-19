# API documentation (v3 additions)

Base path `/api`. Browser auth: HttpOnly session cookie plus `X-CSRF-Token` header on writes (returned by login). Scripts may send `Authorization: Bearer <token>` after `POST /api/auth/login` with header `X-Return-Token: 1`. Interactive docs at `/docs` in development only. The earlier v1/v2 endpoints are listed in `docs/API.md`.
Errors: `{"detail": "..."}` with 401 (not signed in), 403 (wrong role), 404 (not found or not yours), 409 (state conflict, duplicate), 413 (too large), 422 (validation), 429 (rate limited). Internal errors never include stack traces.

| Method and path | Role | Purpose |
|---|---|---|
| POST `/auth/register` | public | Create a student account (role cannot be chosen; throttled) |
| GET `/v2/categories` | public | Active categories with premiums, limits, exclusions |
| GET/POST `/v2/admin/categories`, PUT `/v2/admin/categories/{id}` | admin | Manage categories (validated, audited) |
| POST `/v2/eligibility` | signed in | Eligibility check and quote for a category and price (nothing stored) |
| POST `/v2/assets` (multipart) | student | Register an asset: `front_photo` (legacy `photo`), `back_photo`, optional `invoice`, optional repeated `extra_files`. Starts as `Pending review` |
| GET `/v2/assets/{id}/evidence` | owner or staff | Evidence files, missing items, review status (staff also see hashes and automatic observations) |
| POST `/v2/assets/{id}/evidence` (multipart `kind`, `file`) | student | Add or replace one evidence file while the registration is open |
| DELETE `/v2/assets/{id}/evidence/{eid}` | student | Remove a file while the registration is open |
| GET `/v2/assets/{id}/evidence/{eid}/file` | owner or staff | Authenticated file download |
| GET `/v2/admin/evidence-reviews[?status=]` | admin | Registration review queue |
| GET `/v2/admin/assets/{id}/evidence-review` | admin | Review detail with files, observations and history |
| POST `/v2/admin/assets/{id}/evidence-review` | admin | `{decision: approve or request_more or reject, note, accept_missing_invoice}`; the only way to set the evidence status |
| GET `/v2/assets`, `/v2/assets/{id}`, `/v2/assets/{id}/file/{photo or invoice}` | owner or staff | List, detail, authenticated file download |
| GET `/v2/assets/{id}/quote` | owner | Pricing breakdown for the registered asset |
| POST `/v2/assets` | student | Register an asset with required `front_photo` and `back_photo`, optional `invoice` and repeated `extra_files`; evidence starts pending review |
| GET `/v2/assets/{id}/evidence` | owner or staff | Registration evidence summary and review status |
| POST `/v2/assets/{id}/evidence` / DELETE `/v2/assets/{id}/evidence/{eid}` | owner | Add, replace or remove evidence while review is open |
| GET `/v2/admin/evidence-reviews` | admin | Queue of registrations awaiting evidence review |
| GET `/v2/admin/assets/{id}/evidence-review` | admin | Registration evidence detail, observations and review history |
| POST `/v2/admin/assets/{id}/evidence-review` | admin | Approve, request more evidence or reject registration; approval requires front/back photos and an explained invoice exception if no invoice exists |
| POST `/v2/assets/{id}/purchase` | student | Simulated purchase; body `{"accept_terms": true}` only. 409 until the evidence is `Approved` |
| POST `/v2/assets/{id}/verify-invoice` | admin | Mark an invoice as verified |
| GET `/v2/policies`, `/v2/policies/{id}`, `/v2/admin/policies` | owner / admin | Policies with frozen terms |
| POST `/v2/policies/{id}/pay-premium` | student | Simulated payment of the oldest unpaid cover month |
| GET `/v2/payments` | owner or staff | Premium transactions (simulated) |
| POST `/v2/claims` | student | Create a claim (asset, incident date and type, damage type, description, optional estimate) |
| POST `/v2/claims/{id}/images` (multipart `file`) | claimant | Add a photo (JPEG or PNG, max 5 per claim) |
| POST `/v2/claims/{id}/documents` (multipart `file`) | claimant | Add a supporting document |
| POST `/v2/claims/{id}/verify` | claimant | Run AI verification and policy rules; claims passing automated checks wait for staff confirmation by default |
| GET `/v2/claims`, `/v2/claims/{id}`, `/v2/claims/{id}/images/{iid}/file` | claimant or staff | Claims, full detail (report, decision, settlement, history), image download |
| POST `/v2/claims/{id}/review` | admin, assessor | Exceptional review: `{"action": "approve" or "reject", "reason": "..."}` |
| GET `/v2/dashboard` | student | Dashboard figures |
| GET `/v2/admin/overview` | admin | Overview counts |
| GET `/v2/ai/capabilities` | signed in | Which models and mode are active |
| GET `/v2/ai/analytics` | admin | Damage model availability and SHA-256, measured evaluation (or unavailable), outcome counts, device matching, manual review and evidence review statistics |
| GET `/v2/finance/summary?months=6` | admin | Financial performance |
| POST `/v2/finance/scenario` | admin | Scenario calculator (no storage) |
| PUT `/v2/finance/assumptions`, POST `/v2/finance/expenses`, POST `/v2/finance/reserves` | admin | Finance inputs |

## Examples
```
POST /api/v2/eligibility            {"category_id": 1, "purchase_price": 1500}
-> 200 {"eligible": false, "reason": "Your earbuds are not eligible because the minimum purchase value for this category is ₹2,500.", "quote": null}

POST /api/v2/eligibility            {"category_id": 4, "purchase_price": 40000}
-> 200 {"eligible": true, "reason": "Eligible: ...", "quote": {"monthly_premium": 99.0, "annual_premium": 1188.0, "max_coverage": 18000.0, "estimated_max_claim": 18000.0, "deductible": 0.0, "policy_months": 12, "exclusions": [...]}}

POST /api/v2/assets/7/purchase      {"accept_terms": true, "monthly_premium": 1}
-> 422 (extra fields are rejected: the browser cannot supply prices or limits)

POST /api/v2/claims                 {"asset_id": 7, "incident_date": "2026-11-05", "incident_type": "Accidental Damage", "damage_type": "Broken screen", "description": "The laptop fell and the screen cracked.", "estimated_repair_cost": 8000}
-> 201 {"claim_number": "CLM-2026-01006", "status": "Submitted", ...}

POST /api/v2/claims/12/verify
-> 200 {"status": "Settled", "payable_amount": 8000.0,
        "report": {"mode": "development_simulation", "is_simulated": true, "outcome": "Evidence Supported", "quality": {...}, "asset_identification": {...},
                   "damage_detection": {...}, "description_check": {...}, "duplicate_check": {...}, "risk_indicators": [], "explanation": "...", "next_step": "Proceeding to policy eligibility checks."},
        "decision": {"outcome": "Approved", "checks": [{"id": "CHK-01", "result": "PASS", ...}], "calculation": {"payable": 8000.0, "lines": [...]}},
        "settlement": {"reference": "SET-...", "status": "Settled", "simulated": true}}

POST /api/v2/finance/scenario       {}
-> 200 {"premium_income": 79000.0, "surplus": 12000.0, "margin_pct": 15.2, "warnings": [], "disclaimer": "Sample assumptions ..."}
```
Interactive schema for every endpoint: `/docs` (development).
