# Sample claims and test scenarios

Seeded claims (relative to the day the database is first created):

| Claim | Student | Scenario | Expected |
|---|---|---|---|
| CLM-...-00001 | aarav | Laptop screen cracked (accidental), photo uploaded, screen priced from catalogue 4,000 + 500 | Under Assessment; all rules pass; payable **3,500** (Campus Plus, deductible 1,000) |
| CLM-...-00002 | aarav | Bicycle theft dated 100 days ago; bicycle was added to the policy 60 days ago | POL-002 FAIL (policy version 1) -> recommend rejection |
| CLM-...-00003 | meera | Liquid damage under Campus Basic | POL-003 FAIL -> recommend rejection |
| CLM-...-00004 | aarav | Phone dropped, left as Draft | Student continues: upload photo, submit |

Automated scenarios (`backend/tests`): valid claim (3,000); expired/cancelled/draft policy; waiting period; asset not on policy; asset not in inventory; excluded incident; excluded item (wear and tear); overall limit (58,500); prior payments; per-item limit (43,500); declared-value cap; fixed and percent deductibles and calculation order; depreciation (32,600); missing evidence; duplicate claim; unpriced item; unverified AI item; human correction of an AI suggestion with audit trail; policy-version-at-loss-date; plan edit vs re-issue; status machines; evidence validation; role-based access.
Machine-readable data: `sample_data/scenarios.json`.
