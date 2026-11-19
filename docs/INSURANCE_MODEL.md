# Insurance model

> Academic prototype. All prices, limits and repair costs are sample values for a classroom demonstration. They are not actuarial figures, nothing here is a licensed insurance product, and no money moves (payments and settlements are simulated).

## Eligibility, premium and coverage (initial configuration, editable by an administrator)

| Asset category | Minimum purchase value | Monthly premium | Maximum coverage |
|---|---:|---:|---:|
| Earbuds | ₹2,500 | ₹50 | ₹2,000 |
| Smartphone | ₹8,000 | ₹99 | ₹7,000 |
| Tablet | ₹8,000 | ₹79 | ₹7,000 |
| Laptop | ₹20,000 | ₹99 | ₹18,000 |
| Bicycle | ₹5,000 | ₹69 | ₹4,000 |
| Smartwatch | ₹3,000 | ₹59 | ₹2,500 |

These live in the `asset_categories` table, never in the frontend. Each category also holds: deductible (default 0), policy duration (12 months), waiting period (0 days), optional depreciation (0%), covered incident types (Accidental Damage, Liquid Damage), exclusions, claimable damage types, and a reference repair cost per damage type.
Only these categories can be insured. An administrator can add, disable or edit categories; every change is validated and written to the audit log with before and after values. **A policy keeps the terms it was bought with**: price changes affect new policies only.

Eligibility is checked on the server when an asset is registered and again at purchase. Below the minimum the student sees, for example: "Your earbuds are not eligible because the minimum purchase value for this category is ₹2,500." The purchase price is entered by the student, so it is stored as *declared*. The invoice is stored as evidence and is shown as "Uploaded, not yet verified" until an administrator marks it verified.

## Formulas (implemented in `backend/app/engine/insurance.py`, Decimal arithmetic)

```
Annual premium            = monthly premium x 12
Eligible loss             = assessed loss x (1 - depreciation%)          (0% unless configured)
Payable before deductible = MIN(eligible loss, maximum coverage, remaining policy limit)
Payable                   = MAX(0, payable before deductible - deductible)
Remaining policy limit    = maximum coverage - amounts already paid on this policy
```

Examples from the brief (asserted by tests): laptop, assessed ₹12,000 gives ₹12,000; assessed ₹25,000 gives ₹18,000 (before any deductible). With a ₹1,000 deductible the first becomes ₹11,000. Every claim shows this breakdown line by line.

### Where the "assessed loss" comes from
The browser is never trusted for money. The server uses the category's *reference repair cost* for the declared damage type, or the student's optional estimate bounded by the asset's purchase value. If the estimate is more than `ESTIMATE_TOLERANCE` (default 1.5) times the reference cost, the claim goes to **exceptional review** instead of being paid. AI never sets an amount.

## Claim decision rules (separate from AI)
Ten checks run in `backend/app/engine/decision.py`: authenticated; owner of asset and policy; asset registered and eligible; policy active and the incident month's premium paid; incident inside the coverage period (and after any waiting period, not in the future); incident type covered; no exclusion; no duplicate claim for the same asset and incident date; AI evidence outcome sufficient; amount within limits. Hard failures **reject with the rule and reason**. Uncertainty, risk indicators, an inflated estimate, many recent claims, or inconsistent evidence send the claim to **Exceptional Review Required**, never to automatic rejection. Low model confidence alone never rejects. Only a fully clean claim is approved and settled (simulated).

## Business model and profitability
Premium income funds expected claims, operating costs, AI and technology costs and a risk reserve; what remains is surplus (or deficit).

```
Expected surplus = premium income - expected claims - operating expenses - AI/technology expenses - risk reserve allocation
```

Illustrative sample from the brief (1,000 students, average premium ₹79):

| Item | Per month |
|---|---:|
| Premium income (1,000 x ₹79) | ₹79,000 |
| Expected claims | ₹40,000 |
| Operating expenses | ₹12,000 |
| AI and technology | ₹5,000 |
| Risk reserve allocation | ₹10,000 |
| Illustrative surplus | ₹12,000 (15.2% margin) |

The admin Financial performance page computes real figures from the database (premiums paid, settlements, recorded expenses and reserves). Where a month has no recorded expenses it uses percentage assumptions (defaults: expected claims 50%, operating 15%, AI and technology 6%, reserve 13% of premium income), marks those months, and lets the administrator change the assumptions. It warns whenever expected claims plus costs exceed premium income. The scenario calculator reproduces the table above and lets you change any input; it also shows the break-even loss ratio.

## Assumptions and limitations
* Sample prices and reference costs, no actuarial basis. Loss ratios in real student insurance are driven by theft and loss, which these policies exclude.
* No adverse-selection, fraud-loss, reinsurance, tax or regulatory-capital modelling.
* Monthly premiums are simulated one cover month at a time; a claim is only eligible if the incident month was paid. There is no grace period, lapse notice or refund logic.
* Depreciation is available but off by default.
* The demo data is tiny (8 sample policies), so its finance charts show deficits. This is honest, not a bug: use the scenario calculator to discuss scale.
