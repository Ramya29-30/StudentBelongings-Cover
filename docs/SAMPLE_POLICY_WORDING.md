# Sample policy wording and coverage configuration (fictional)

Seeded in `backend/app/seed.py`; wording text is stored with each plan and shown on the policy page.

**Campus Plus (demonstration plan)**
* s1 Period of cover: from policy start (or activation, if later) to expiry unless cancelled.
* s2 Covered perils: Theft, Accidental Damage, Liquid Damage, Fire.
* s3 Exclusions: EXC-01 wear and tear; EXC-02 purely cosmetic minor scratches; EXC-03 intentional damage.
* s4 Waiting period: 7 days. s5 Required documents: Theft - police report + proof of purchase; Accidental/Liquid damage - damage photograph; Fire - photograph + incident report.
* s6 Limits: overall 1,20,000; Laptop 80,000; Smartphone 60,000; other 30,000; never above declared value.
* s7 Deductible 1,000 fixed. Depreciation 10% per completed year on replacement, maximum 50%. Order: per-item limit, overall limit, deductible.

| Plan | Perils | Overall | Deductible | Depreciation | Waiting | Order |
|---|---|---|---|---|---|---|
| Campus Basic | Theft, Accidental, Fire | 60,000 | 1,500 fixed | none | 0 | limit then deductible |
| Campus Plus | + Liquid Damage | 1,20,000 | 1,000 fixed | 10%/yr, max 50%, replacements | 7 days | limit then deductible |
| Campus Flex | + Liquid Damage | 50,000 | 10% | none | 0 | deductible then limit |
