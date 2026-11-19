"""Insurance rules engine - pure, deterministic and unit-testable (no database, no HTTP, no AI).

Every rule returns one or more RuleResult dicts:
  rule_id, rule_name, outcome, inputs, reason, clause, follow_up, item_id
Outcomes: PASS | FAIL | FLAG | PENDING | ADJUSTED | APPLIED | SKIPPED

Rules can be switched off per plan via terms["disabled_rules"] (e.g. ["POL-010"]).
These are sample rules for an academic prototype - not universal insurance rules.
"""
from __future__ import annotations

from datetime import date, timedelta

from .calculator import calculate_claim, item_is_priced

BLOCKING_RULES = ("POL-001", "POL-002", "POL-003", "POL-004", "POL-011")


def _r(rule_id, name, outcome, inputs, reason, clause="", follow_up="", item_id=None):
    return {"rule_id": rule_id, "rule_name": name, "outcome": outcome, "inputs": inputs, "reason": reason,
            "clause": clause, "follow_up": follow_up, "item_id": item_id}


def cover_start(policy: dict) -> date | None:
    """Cover begins on the later of the policy start date and the activation date."""
    if policy.get("activated_on") is None:
        return None
    return max(policy["start_date"], policy["activated_on"])


def pol_001(c):
    p, d = c["policy"], c["incident"]["date"]
    problems = []
    start = cover_start(p)
    if start is None:
        problems.append("the policy was never activated (it is still a Draft)")
    elif d < start:
        problems.append(f"the incident date {d} is before cover began on {start}")
    if d > p["end_date"]:
        problems.append(f"the incident date {d} is after the policy expiry date {p['end_date']}")
    if p.get("cancelled_on") and d >= p["cancelled_on"]:
        problems.append(f"the policy was cancelled effective {p['cancelled_on']}")
    inputs = {"incident_date": str(d), "policy_start": str(p["start_date"]), "policy_end": str(p["end_date"]),
              "activated_on": str(p.get("activated_on")), "cancelled_on": str(p.get("cancelled_on")), "policy_status_now": p["status"]}
    if problems:
        return [_r("POL-001", "Policy active on incident date", "FAIL", inputs, "Not eligible: " + "; ".join(problems) + ".",
                   "Policy Wording s1 Period of Cover", "Reject with reason or confirm the incident date with the student.")]
    return [_r("POL-001", "Policy active on incident date", "PASS", inputs,
               f"Policy was in force on {d} (cover {start} to {p['end_date']}). Eligibility is judged on the incident date, not today.",
               "Policy Wording s1 Period of Cover")]


def pol_002(c):
    ids, aid = c["policy"]["insured_asset_ids"], c["asset_id"]
    inputs = {"asset_id": aid, "insured_asset_ids_in_policy_version": ids, "policy_version": c["policy"]["version"]}
    if aid in ids:
        return [_r("POL-002", "Asset insured under policy", "PASS", inputs,
                   f"Asset {aid} is listed as insured in policy version {c['policy']['version']}.", "Policy Schedule of Insured Items")]
    return [_r("POL-002", "Asset insured under policy", "FAIL", inputs,
               f"Asset {aid} was not insured under policy version {c['policy']['version']} that applied on the incident date.",
               "Policy Schedule of Insured Items", "Reject with reason, or ask Policy Administrator to review the schedule.")]


def pol_003(c):
    perils, t = c["policy"]["terms"].get("covered_perils", []), c["incident"]["type"]
    inputs = {"incident_type": t, "covered_perils": perils}
    if t in perils:
        return [_r("POL-003", "Incident type is a covered peril", "PASS", inputs, f"'{t}' is a covered peril.", "Policy Wording s2 Covered Perils")]
    return [_r("POL-003", "Incident type is a covered peril", "FAIL", inputs, f"'{t}' is not among the covered perils ({', '.join(perils) or 'none'}).",
               "Policy Wording s2 Covered Perils", "Reject with reason.")]


def match_exclusions(c):
    """Returns (incident_level_matches, {item_id: exclusion}) - used by POL-004 and by the calculator."""
    t = c["incident"]["type"]
    inc, per_item = [], {}
    for ex in c["policy"]["terms"].get("exclusions", []):
        types, dmg, sev = ex.get("incident_types") or [], ex.get("damage_types") or [], ex.get("severities") or []
        if not dmg:
            if t in types:
                inc.append(ex)
            continue
        if types and t not in types:
            continue
        for it in c["items"]:
            if it["damage_type"] in dmg and (not sev or it["severity"] in sev) and it.get("id") not in per_item:
                per_item[it.get("id")] = ex
    return inc, per_item


def pol_004(c):
    inc, per_item = match_exclusions(c)
    out = []
    for ex in inc:
        out.append(_r("POL-004", "Exclusion check", "FAIL", {"incident_type": c["incident"]["type"], "exclusion": ex["code"]},
                      f"Excluded under {ex['code']} - {ex['title']}: incident type '{c['incident']['type']}' is excluded.", ex.get("clause") or ex["code"],
                      "Reject with reason."))
    for iid, ex in per_item.items():
        it = next(i for i in c["items"] if i.get("id") == iid)
        out.append(_r("POL-004", "Exclusion check", "FAIL", {"damage_type": it["damage_type"], "severity": it["severity"], "exclusion": ex["code"]},
                      f"Item '{it['component']}' is excluded under {ex['code']} - {ex['title']}; its loss is removed from the eligible amount.",
                      ex.get("clause") or ex["code"], "Assessor to confirm the damage type is correct.", iid))
    if not out:
        names = [e["code"] for e in c["policy"]["terms"].get("exclusions", [])]
        out.append(_r("POL-004", "Exclusion check", "PASS", {"exclusions_checked": names}, "No configured exclusion applies to this incident or its damage items.",
                      "Policy Wording s3 Exclusions"))
    return out


def pol_008(c):
    req = c["policy"]["terms"].get("required_documents", {}).get(c["incident"]["type"], [])
    have = set(c["evidence_types"])
    if c["asset"] and c["asset"].get("proof_of_purchase_ref"):
        have.add("proof_of_purchase")  # the inventory record carries a proof-of-purchase reference
    missing = [d for d in req if d not in have]
    inputs = {"required": req, "provided": sorted(have)}
    if missing:
        return [_r("POL-008", "Mandatory evidence provided", "PENDING", inputs, "Missing mandatory evidence: " + ", ".join(missing) + ".",
                   "Policy Wording s5 Required Documents", "Set status to Pending Information and request: " + ", ".join(missing))]
    return [_r("POL-008", "Mandatory evidence provided", "PASS", inputs, "All mandatory documents are present." if req else "No mandatory documents configured for this incident type.",
               "Policy Wording s5 Required Documents")]


def pol_009(c):
    a, claimant = c["asset"], c["claimant_id"]
    inputs = {"asset_found": a is not None, "asset_owner_id": a and a["owner_id"], "claimant_id": claimant,
              "purchase_date": a and str(a["purchase_date"]), "incident_date": str(c["incident"]["date"])}
    if a is None or a["owner_id"] != claimant:
        return [_r("POL-009", "Asset in claimant's insured inventory", "FLAG", inputs, "The asset is not in the claimant's inventory - flagged for review.",
                   "Inventory Register", "Investigate ownership before any decision.")]
    if a["purchase_date"] > c["incident"]["date"]:
        return [_r("POL-009", "Asset in claimant's insured inventory", "FLAG", inputs,
                   f"Recorded purchase date {a['purchase_date']} is after the incident date.", "Inventory Register", "Verify purchase date and proof of purchase.")]
    return [_r("POL-009", "Asset in claimant's insured inventory", "PASS", inputs, "Asset belongs to the claimant's inventory and existed on the incident date.", "Inventory Register")]


def pol_010(c):
    window = int(c["policy"]["terms"].get("duplicate_window_days", 0))
    d = c["incident"]["date"]
    dups = [o for o in c["other_claims"] if o["asset_id"] == c["asset_id"] and o["status"] not in ("Draft", "Rejected with Reason")
            and abs((o["incident_date"] - d).days) <= window]
    inputs = {"window_days": window, "overlapping_claims": [o["claim_number"] for o in dups]}
    if dups:
        return [_r("POL-010", "Duplicate / overlapping claim", "FLAG", inputs,
                   f"Possible duplicate of {', '.join(o['claim_number'] for o in dups)} (same asset, incident within {window} day(s)).",
                   "Claims Handling Procedure", "Assessor must compare the claims before deciding.")]
    return [_r("POL-010", "Duplicate / overlapping claim", "PASS", inputs, "No other open or settled claim for this asset and incident date.", "Claims Handling Procedure")]


def pol_011(c):
    wait = int(c["policy"]["terms"].get("waiting_period_days", 0))
    start, d = cover_start(c["policy"]), c["incident"]["date"]
    inputs = {"waiting_period_days": wait, "cover_start": str(start), "incident_date": str(d)}
    if wait <= 0 or start is None:
        return [_r("POL-011", "Waiting period", "PASS", inputs, "No waiting period applies.", "Policy Wording s4 Waiting Period")]
    ends = start + timedelta(days=wait)
    if d < ends:
        return [_r("POL-011", "Waiting period", "FAIL", inputs, f"Incident {d} falls inside the {wait}-day waiting period that ends {ends}.",
                   "Policy Wording s4 Waiting Period", "Reject with reason.")]
    return [_r("POL-011", "Waiting period", "PASS", inputs, f"Waiting period of {wait} day(s) had elapsed on {ends}.", "Policy Wording s4 Waiting Period")]


def pol_012(c):
    items, out = c["items"], []
    if not items:
        return [_r("POL-012", "Damage items priced from catalogue or assessor input", "PENDING", {"items": 0},
                   "No damage items have been assessed yet.", "Assessment Procedure", "Assessor to add and price damage items.")]
    for it in items:
        if not item_is_priced(it):
            out.append(_r("POL-012", "Damage items priced from catalogue or assessor input", "PENDING",
                          {"component": it["component"], "repair_action": it["repair_action"], "parts_cost": it.get("parts_cost"), "labour_cost": it.get("labour_cost")},
                          f"'{it['component']}' has no repair price or requires further inspection. Prices come only from the catalogue or assessor input.",
                          "Assessment Procedure", "Assessor to apply a catalogue price, enter a price, or inspect further.", it.get("id")))
    return out or [_r("POL-012", "Damage items priced from catalogue or assessor input", "PASS", {"items": len(items)}, "Every damage item has a price.", "Assessment Procedure")]


def pol_013(c):
    unv = [i for i in c["items"] if i.get("verification_status") in ("AI Suggested", "Student Declared")]
    if unv:
        return [_r("POL-013", "AI suggestions verified by a human", "PENDING", {"unverified_items": [i["component"] for i in unv]},
                   "Items still awaiting human verification ('AI Suggested' or 'Student Declared'): " + ", ".join(i["component"] for i in unv) + ".", "Assessment Procedure",
                   "Assessor must review, correct or verify these items.")]
    return [_r("POL-013", "AI suggestions verified by a human", "PASS", {}, "No unverified AI-suggested or student-declared items.", "Assessment Procedure")]


def check_eligibility(c) -> list[dict]:
    """Policy-level eligibility only (used by the policy page before any claim exists)."""
    dis = set(c["policy"]["terms"].get("disabled_rules", []))
    res = []
    for fn, rid in ((pol_001, "POL-001"), (pol_002, "POL-002"), (pol_003, "POL-003"), (pol_011, "POL-011")):
        res += [_r(rid, "", "SKIPPED", {}, "Rule disabled in plan configuration.") if rid in dis else x for x in fn(c)]
    return res


def evaluate_claim(c: dict) -> dict:
    terms, dis = c["policy"]["terms"], set(c["policy"]["terms"].get("disabled_rules", []))
    results: list[dict] = []

    def run(rid, fn):
        if rid in dis:
            results.append(_r(rid, "Rule disabled", "SKIPPED", {}, "Rule disabled in plan configuration."))
        else:
            results.extend(fn(c))

    for rid, fn in (("POL-001", pol_001), ("POL-002", pol_002), ("POL-003", pol_003), ("POL-011", pol_011), ("POL-004", pol_004)):
        run(rid, fn)
    _, item_exc = match_exclusions(c) if "POL-004" not in dis else ([], {})
    blocked = [f"{x['rule_id']}: {x['reason']}" for x in results if x["rule_id"] in BLOCKING_RULES and x["outcome"] == "FAIL" and x["item_id"] is None]
    calc = calculate_claim(terms, c["asset"], c["incident"]["date"], c["items"], item_exc, c.get("prior_paid_policy", 0), c.get("prior_paid_asset", 0), blocked)

    fa = calc["facts"]
    if "POL-005" not in dis:
        adj = calc["overall_adjustment"]
        results.append(_r("POL-005", "Overall coverage limit", "ADJUSTED" if adj > 0 else "PASS",
                          {"overall_limit": fa["overall_limit"], "remaining_overall_limit": fa["remaining_overall_limit"], "claimed_after_item_limit": calc["eligible_subtotal"] - calc["per_item_adjustment"]},
                          f"Amount reduced by {adj:,.2f} to the remaining overall limit of {fa['remaining_overall_limit']:,.2f}." if adj > 0 else "Within the remaining overall coverage limit.",
                          "Policy Wording s6 Limits", "Assessor to explain the reduction to the student." if adj > 0 else ""))
    if "POL-006" not in dis:
        adj = calc["per_item_adjustment"]
        results.append(_r("POL-006", "Per-item coverage limit", "ADJUSTED" if adj > 0 else "PASS",
                          {"per_item_limit": fa["per_item_limit"], "remaining_item_limit": fa["remaining_item_limit"], "eligible_subtotal": calc["eligible_subtotal"],
                           "cap_at_declared_value": terms.get("cap_at_declared_value", False)},
                          f"Amount reduced by {adj:,.2f} to the per-item limit." if adj > 0 else "Within the per-item limit.", "Policy Wording s6 Limits",
                          "Assessor to explain the reduction." if adj > 0 else ""))
    if "POL-007" not in dis:
        ded = calc["deductible_applied"]
        results.append(_r("POL-007", "Deductible applied", "APPLIED" if ded > 0 else "PASS",
                          {"deductible_type": terms.get("deductible_type"), "deductible_value": terms.get("deductible_value"), "calc_order": calc["calc_order"]},
                          f"Deductible of {ded:,.2f} applied (order: {calc['calc_order']})." if ded > 0 else "No deductible reduced the amount.",
                          "Policy Wording s7 Deductible"))
    for rid, fn in (("POL-008", pol_008), ("POL-009", pol_009), ("POL-010", pol_010), ("POL-012", pol_012), ("POL-013", pol_013)):
        run(rid, fn)
    results.sort(key=lambda x: (x["rule_id"], x["item_id"] or 0))
    for n, x in enumerate(results, 1):
        x["seq"] = n

    fails = [x for x in results if x["outcome"] == "FAIL" and x["item_id"] is None and x["rule_id"] in BLOCKING_RULES]
    pending = [x for x in results if x["outcome"] == "PENDING"]
    flags = [x for x in results if x["outcome"] == "FLAG"]
    if fails:
        rec, reasons = "RECOMMEND_REJECTION", [x["reason"] for x in fails]
    elif pending:
        rec, reasons = "PENDING_INFORMATION", [x["reason"] for x in pending]
    elif flags:
        rec, reasons = "MANUAL_REVIEW", [x["reason"] for x in flags]
    elif calc["estimated_payable"] <= 0:
        rec, reasons = "RECOMMEND_REJECTION", ["The eligible loss does not exceed the deductible / no payable amount remains after policy terms."]
    else:
        rec, reasons = "RECOMMEND_APPROVAL_REVIEW", ["All blocking rules passed; amount is an estimate for human review."]
    return {"rule_results": results, "calculation": calc, "recommendation": rec, "recommendation_reasons": reasons,
            "review_flags": calc["flags"] + [x["reason"] for x in flags]}


def suggest_repair_action(repair_cost: float | None, replacement_cost: float | None, threshold_pct: float = 70) -> tuple[str, str]:
    """Configurable repair-vs-replace guidance (a suggestion; the assessor decides)."""
    if repair_cost is None:
        return "Inspect Further", "No repair price available."
    if replacement_cost and repair_cost >= replacement_cost * threshold_pct / 100:
        return "Replace", f"Repair cost {repair_cost:,.2f} is at least {threshold_pct}% of replacement cost {replacement_cost:,.2f}."
    return "Repair", "Repair cost is below the configured replacement threshold."
