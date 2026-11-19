# Database schema

SQLite for local use (`backend/data/sbc.db`), managed by Alembic (`backend/alembic/versions`, head revision `0004`). Migration path to PostgreSQL: set `DATABASE_URL=postgresql+psycopg://...`, install `psycopg`, run the app once (migrations are SQLAlchemy/Alembic generic). The PostgreSQL path is documented but was not exercised in this build.

Migration `0004` adds the v3 tables below and new columns on `assets`, `policies` and `claims`. Tables from earlier versions are listed after them.

## Relationships (v3)

```
users 1-* assets 1-* policy_assets *-1 policies *-1 asset_categories
asset_categories 1-1 coverage_plans (plan created and kept in sync by the server)
policies 1-* premium_transactions
policies 1-* claims 1-* claim_images
claims 1-* ai_verification_reports   (one per verification run)
claims 1-* claim_decisions           (system run, or staff decision after exceptional review)
claims 1-1 settlements
financial_expenses, risk_reserves: monthly finance inputs for the admin dashboard
audit_records: every important action (category changes, purchases, status changes, reviews)
```

## New v3 tables

### `ai_verification_reports`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| claim_id | INTEGER | no | FK claims.id, indexed |
| run | INTEGER | no |  |
| mode | VARCHAR(30) | no |  |
| is_simulated | BOOLEAN | no |  |
| model_info | JSON | no |  |
| quality | JSON | no |  |
| asset_identification | JSON | no |  |
| damage_detection | JSON | no |  |
| description_check | JSON | no |  |
| duplicate_check | JSON | no |  |
| evidence_completeness | JSON | no |  |
| risk_indicators | JSON | no |  |
| outcome | VARCHAR(40) | no |  |
| route | VARCHAR(20) | no |  |
| explanation | TEXT | no |  |
| next_step | TEXT | no |  |
| processing_ms | INTEGER | no |  |
| created_at | DATETIME | no |  |

### `asset_categories`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| name | VARCHAR(40) | no | unique |
| description | VARCHAR(300) | no |  |
| min_purchase_value | NUMERIC(12, 2) | no |  |
| monthly_premium | NUMERIC(12, 2) | no |  |
| max_coverage | NUMERIC(12, 2) | no |  |
| deductible | NUMERIC(12, 2) | no |  |
| policy_months | INTEGER | no |  |
| waiting_period_days | INTEGER | no |  |
| depreciation_pct_per_year | NUMERIC(5, 2) | no |  |
| depreciation_max_pct | NUMERIC(5, 2) | no |  |
| exclusions | JSON | no |  |
| covered_incident_types | JSON | no |  |
| excluded_damage_types | JSON | no |  |
| damage_types | JSON | no |  |
| reference_repair_costs | JSON | no |  |
| eligibility_conditions | VARCHAR(500) | no |  |
| requires_serial | BOOLEAN | no |  |
| active | BOOLEAN | no |  |
| plan_id | INTEGER | yes | FK coverage_plans.id |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

### `claim_decisions`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| claim_id | INTEGER | no | FK claims.id, indexed |
| run | INTEGER | no |  |
| outcome | VARCHAR(40) | no |  |
| decided_by | VARCHAR(10) | no |  |
| decided_by_user | INTEGER | yes | FK users.id |
| checks | JSON | no |  |
| calculation | JSON | no |  |
| payable_amount | NUMERIC(12, 2) | yes |  |
| reason | TEXT | no |  |
| created_at | DATETIME | no |  |

### `claim_images`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| claim_id | INTEGER | no | FK claims.id, indexed |
| student_id | INTEGER | no | FK users.id, indexed |
| stored_name | VARCHAR(80) | no |  |
| original_name | VARCHAR(200) | no |  |
| content_type | VARCHAR(40) | no |  |
| size_bytes | INTEGER | no |  |
| sha256 | VARCHAR(64) | no | indexed |
| phash | VARCHAR(16) | no | indexed |
| width | INTEGER | no |  |
| height | INTEGER | no |  |
| quality | JSON | no |  |
| exif | JSON | no |  |
| uploaded_at | DATETIME | no |  |

### `financial_expenses`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| period | VARCHAR(7) | no | indexed |
| category | VARCHAR(20) | no |  |
| amount | NUMERIC(12, 2) | no |  |
| description | VARCHAR(200) | no |  |
| created_by | INTEGER | yes | FK users.id |
| created_at | DATETIME | no |  |

### `premium_transactions`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| reference | VARCHAR(30) | no | unique |
| policy_id | INTEGER | no | FK policies.id, indexed |
| student_id | INTEGER | no | FK users.id, indexed |
| amount | NUMERIC(12, 2) | no |  |
| period_label | VARCHAR(7) | no |  |
| status | VARCHAR(12) | no |  |
| method | VARCHAR(20) | no |  |
| paid_at | DATETIME | no |  |

Unique together: policy_id, period_label

### `risk_reserves`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| period | VARCHAR(7) | no | indexed |
| amount | NUMERIC(12, 2) | no |  |
| description | VARCHAR(200) | no |  |
| created_by | INTEGER | yes | FK users.id |
| created_at | DATETIME | no |  |

### `settlements`

| Column | Type | Null | Notes |
|---|---|---|---|
| id | INTEGER | no | PK |
| claim_id | INTEGER | no | FK claims.id, unique |
| reference | VARCHAR(30) | no | unique |
| amount | NUMERIC(12, 2) | no |  |
| status | VARCHAR(20) | no |  |
| method | VARCHAR(20) | no |  |
| created_at | DATETIME | no |  |
| settled_at | DATETIME | yes |  |

## Columns added to existing tables by migration 0004

* `assets`: `brand`, `model_name`, `description`, `category_id`, `invoice_file`, `invoice_name`, `photo_file`, `photo_name`, `invoice_verified`, `eligibility_status`, `eligibility_reason`
* `policies`: `category_id`, `purchase_value`, `monthly_premium`, `annual_premium`, `max_coverage`, `deductible`, `terms_snapshot`
* `claims`: `flow`, `damage_type`, `estimated_repair_cost`, `assessed_loss`, `payable_amount`, `ai_outcome`, `decision_outcome`

Policies bought through the self-service flow carry their terms in `monthly_premium`, `max_coverage`, `deductible` and `terms_snapshot`. These are frozen at purchase and never read from the category again, so a later price change cannot alter an issued policy. `claims.flow` is `auto` for self-service claims and `manual` for the legacy assessor workflow.

## Existing tables (v1 and v2)

`ai_suggestions`, `assets`, `audit_records`, `auth_sessions`, `calculation_lines`, `claim_items`, `claim_reserves`, `claim_status_history`, `claims`, `coverage_plans`, `evidence_files`, `exclusions`, `login_attempts`, `payment_events`, `payments`, `policies`, `policy_assets`, `policy_versions`, `repair_catalogue`, `reserve_history`, `rule_results`, `schema_version`, `students`, `system_settings`, `users`. See `docs/ER_DIAGRAM.md` for their relationships.
