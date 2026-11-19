"""Automated policy-rule engine for the self-service claim flow.

Deliberately SEPARATE from AI verification: the AI report is one input (check 9). Hard policy failures reject with the rule that caused
it; uncertainty or risk routes to Exceptional Review, never to automatic rejection; only fully clean claims are approved.
`evaluate()` is a pure function over a plain dict so every rule can be unit-tested.
"""
from __future__ import annotations

from datetime import date

PASS, FAIL, REVIEW, WAIT = "PASS", "FAIL", "REVIEW", "WAIT"


def _c(n: int, name: str, result: str, reason: str) -> dict:
    return {"id": f"CHK-{n:02d}", "name": name, "result": result, "reason": reason}


def evaluate(c: dict) -> dict:
    """c keys: authenticated, owner_ok, asset_registered, policy_status, policy_start, policy_end, waiting_days, incident_date, today,
    incident_type, covered_incident_types, damage_type, excluded_damage_types, excluded_incident_types, duplicate_claim (str|None),
    ai_outcome, ai_route, ai_reason, risk_review_reasons (list), calc (dict|None), estimate_review (str|None), premium_current (bool)."""
    ck = []
    ck.append(_c(1, "Student is authenticated", PASS if c["authenticated"] else FAIL, "Signed-in student." if c["authenticated"] else "Not authenticated."))
    ck.append(_c(2, "Student owns the insured asset", PASS if c["owner_ok"] else FAIL, "Asset and policy belong to the claimant." if c["owner_ok"] else "The asset or policy does not belong to this student."))
    ck.append(_c(3, "Asset is registered and eligible", PASS if c["asset_registered"] else FAIL,
                 "Asset is registered with a verified eligibility result." if c["asset_registered"] else "Asset is not a registered eligible asset."))
    active = c["policy_status"] == "Active"
    ck.append(_c(4, "Policy is active", PASS if active and c["premium_current"] else FAIL,
                 "Policy is active and premiums are up to date." if active and c["premium_current"] else
                 (f"Policy status is {c['policy_status']}." if not active else "The monthly premium for the incident month has not been paid.")))
    start, end, inc = c["policy_start"], c["policy_end"], c["incident_date"]
    first_day = date.fromordinal(start.toordinal() + c["waiting_days"])
    if inc > c["today"]:
        ck.append(_c(5, "Incident is within the coverage period", FAIL, "The incident date is in the future."))
    elif inc < start or inc > end:
        ck.append(_c(5, "Incident is within the coverage period", FAIL, f"The incident ({inc}) is outside the coverage period {start} to {end}."))
    elif inc < first_day:
        ck.append(_c(5, "Incident is within the coverage period", FAIL, f"The incident falls inside the {c['waiting_days']}-day waiting period (cover starts {first_day})."))
    else:
        ck.append(_c(5, "Incident is within the coverage period", PASS, f"{inc} is inside {start} to {end}."))
    ok_type = c["incident_type"] in c["covered_incident_types"]
    ck.append(_c(6, "Incident type is covered", PASS if ok_type else FAIL,
                 f"{c['incident_type']} is covered." if ok_type else f"{c['incident_type']} is not a covered incident type. Covered: {', '.join(c['covered_incident_types']) or 'none'}."))
    excl = c["damage_type"] in c["excluded_damage_types"] or c["incident_type"] in c.get("excluded_incident_types", [])
    ck.append(_c(7, "No exclusion applies", FAIL if excl else PASS,
                 f"Excluded by the policy terms: {c['damage_type'] if c['damage_type'] in c['excluded_damage_types'] else c['incident_type']}." if excl else "No policy exclusion matches this claim."))
    dup = c.get("duplicate_claim")
    ck.append(_c(8, "Not a duplicate of an earlier claim", FAIL if dup else PASS,
                 f"A claim for the same asset and incident date already exists ({dup})." if dup else "No other claim exists for this asset and incident date."))
    ai = c["ai_outcome"]
    if ai == "Evidence Supported":
        ck.append(_c(9, "AI evidence outcome is sufficient", PASS, "Visual evidence supports the claim."))
    elif ai == "More Evidence Required":
        ck.append(_c(9, "AI evidence outcome is sufficient", REVIEW if c.get("ai_route") == "exceptional_review" else WAIT, c.get("ai_reason") or "More evidence is required."))
    else:
        ck.append(_c(9, "AI evidence outcome is sufficient", REVIEW, c.get("ai_reason") or "The evidence is inconsistent and needs a human review."))
    calc = c.get("calc")
    if calc is None:
        ck.append(_c(10, "Claim amount is within policy limits", WAIT, "Amount not calculated."))
    elif c.get("estimate_review"):
        ck.append(_c(10, "Claim amount is within policy limits", REVIEW, c["estimate_review"]))
    elif calc["payable"] <= 0:
        ck.append(_c(10, "Claim amount is within policy limits", FAIL, "Nothing is payable after the limit and deductible are applied."))
    else:
        ck.append(_c(10, "Claim amount is within policy limits", PASS, f"Payable {calc['payable']:,.0f} is within the limit (binding limit: {calc['binding_limit']})."))
    for i, r in enumerate(c.get("risk_review_reasons") or []):
        ck.append({"id": f"RSK-{i + 1:02d}", "name": "Risk indicator", "result": REVIEW, "reason": r})

    fails = [x for x in ck if x["result"] == FAIL]
    reviews = [x for x in ck if x["result"] == REVIEW]
    waits = [x for x in ck if x["result"] == WAIT]
    if fails:
        outcome, reason = "Rejected", " ".join(f"[{x['id']}] {x['reason']}" for x in fails)
    elif waits:
        outcome, reason = "More Evidence Required", " ".join(x["reason"] for x in waits)
    elif reviews:
        outcome, reason = "Exceptional Review Required", " ".join(x["reason"] for x in reviews)
    else:
        outcome, reason = "Approved", "All policy checks passed."
    return {"outcome": outcome, "reason": reason, "checks": ck}
