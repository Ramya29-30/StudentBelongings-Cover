# Guidewire review and concept mapping

> **This application is a standalone prototype. It is not Guidewire software, it calls no Guidewire API, and nothing in this repository has been compiled or run against a Guidewire environment.**
> No Guidewire installation, Data Dictionary, Studio, Gosu compiler or documentation was available while this was written. Everything below that names a Guidewire concept is **conceptual and recalled from general public knowledge of the products**. Treat every Guidewire name as *unverified* until it is checked against the data dictionary and documentation of your licensed version.

## 1. Verification legend

| Label | Meaning |
|---|---|
| **Own (tested)** | Exists in this repository and is covered by automated tests |
| **Conceptual** | A reasonable analogy between a prototype feature and a Guidewire idea; the prototype does not implement or call it |
| **Unverified name** | A Guidewire entity/property/API name mentioned from memory; may be wrong for your version |
| **Needs Guidewire** | Cannot be written or validated without a real Guidewire environment |

## 2. Review of the previous `gosu/ClaimRules.gs`

The earlier file claimed to be a "sketch" but contained names that exist nowhere:

| Item in the old file | Problem | Action |
|---|---|---|
| `SbcPolicy`, `SbcClaim` | Invented types; not Guidewire entities and not defined anywhere | Replaced by plain value classes `PolicyFacts` / `ClaimFacts` defined in the same file and explicitly labelled as non-Guidewire |
| `new RuleResult(...)` | Class was used but never defined, so the file could not compile even in principle | `RuleResult` is now defined in the file |
| `policy.versionEffectiveOn(date)`, `version.InsuredAssets`, `.CoveredPerils` | Invented members | Removed. The caller supplies the facts of the version in force on the loss date |
| `policy.ActivatedOn/StartDate/EndDate/CancelledOn`, `claim.IncidentDate/IncidentType/Asset` | Property names look plausible but are the prototype's own column names, not Guidewire's | Kept only on the plain value classes, which are ours |
| Claim "this is conceptually a sketch" header | Honest, but did not say what was invented | Header rewritten to say precisely what is and is not verified |

**What the new file is:** a faithful port of the *pure* logic (POL-001, POL-002, POL-003, cover start, depreciation percentage, and the payable formula in both calculation orders) using only `java.*` types and core Gosu constructs (`package`, `uses`, `class`, `var x : T as Prop`, `construct`, `static function`, `and/or/not`, ternary). It touches no Guidewire API.

**What is still not verified:** that the file compiles. Gosu is an open-source language, but no Gosu compiler could be obtained in the build environment, so the syntax is believed correct but **has never been compiled or run**. The rules POL-004 to POL-013, exclusion matching, and the itemised calculation lines are **not ported**; the Python engine remains the only tested implementation.

## 3. Concept mapping (all conceptual)

| StudentBelongingsCover | Guidewire concept (unverified names) | Status |
|---|---|---|
| `coverage_plans`, `exclusions` | PolicyCenter product model: coverages, coverage terms, exclusions/conditions | Conceptual |
| `policies` (Draft/Active/Expired/Cancelled) | Policy and PolicyPeriod; jobs such as Submission, PolicyChange, Renewal, Cancellation | Conceptual |
| `policy_versions` snapshots, "version in force on the incident date" | PolicyPeriod revisions / effective-dated changes (a claim loss date is checked against the period in force) | Conceptual |
| `assets`, `policy_assets` | Risk units / coverable items | Conceptual |
| `POST /claims` | ClaimCenter FNOL (First Notice of Loss) | Conceptual |
| `claims` | Claim | Conceptual |
| `claim_items` (damaged component + assessment) | Exposure and/or Incident (e.g. a property-damage style incident) | Conceptual |
| POL-001..003 | Coverage verification against the policy in force on the loss date | Conceptual |
| `engine/rules.py` | Gosu rule sets (validation / exposure rules) | Conceptual; port is partial (section 2) |
| `engine/calculator.py` | Gosu calculation or an external service called from rules | Conceptual |
| Claim statuses and `assessor_id` | Claim state, assignment (assignment rules / groups / queues), Activities | Conceptual |
| `claim_reserves`, `reserve_history`, `/reserve/recommend`, `/reserve/approve` | Financials: reserve lines / reserve sets with authority limits and approval | Conceptual |
| `payments`, `/payments`, four-eyes approval, status events | Financials: checks / payments created through transactions that follow approval (authority limit) rules | Conceptual |
| Duplicate-payment prevention (idempotency key + duplicate check) | Duplicate check logic on payments | Conceptual |
| `claim_status_history`, `audit_records` | Claim history and notes | Conceptual |
| Evidence uploads | Documents attached to the claim | Conceptual |
| React pages (Policy Centre, Claim Centre, Admin) | PCF (Page Configuration Files) screens | Conceptual |
| AI suggestions (labelled, human-verified) | No direct equivalent; would be an external integration | Needs Guidewire + an integration design |

### How policy administration, claims, assessments, reserves and payments map

* **Policy administration.** The prototype's admin portal creates a policy in Draft, activates it, and creates a new version for each change. In PolicyCenter terms this resembles submitting a job that produces a new effective-dated policy period revision. The prototype has no underwriting, rating or renewal.
* **Claims.** Student registration corresponds to FNOL. The prototype checks coverage when the claim is submitted and again when the assessor re-runs the rules.
* **Assessments.** Assessor damage items correspond loosely to exposures with an assessed value. The explainable rule trace and itemised calculation are the prototype's own design.
* **Reserves.** The assessor *recommends*, the administrator *approves*. This is deliberately similar in spirit to reserve authority limits, but it is the prototype's own simple two-role rule, not Guidewire's authority-limit model.
* **Payments.** Payments are **simulated**: no bank, card or gateway is contacted. Approval requires a different person from the requester.

## 4. Adapter layer (design only)

A real integration would add an adapter that builds `PolicyFacts` and `ClaimFacts` from real entities on the loss date, calls `ClaimRules`, and writes results back (for example as validation messages or activities). **That adapter is not in this repository** because the real entity and property names (for example the policy period dates, loss date, loss type, covered item and coverage term accessors) cannot be confirmed without a Guidewire environment.

## 5. What needs a real Guidewire environment

1. Compiling and unit-testing `gosu/ClaimRules.gs` (Gosu compiler / Studio).
2. The adapter that fills the value classes from real PolicyCenter / ClaimCenter entities.
3. Modelling the product (coverages, terms, exclusions) in the PolicyCenter product model.
4. Reserve and payment creation through ClaimCenter financial transactions, including authority limits and approval flows.
5. Authentication via the organisation's identity provider, and any use of Guidewire Cloud APIs (names, scopes and payloads must be taken from the vendor documentation you are licensed to use).
6. Security, privacy and regulatory review, and load/concurrency testing.
