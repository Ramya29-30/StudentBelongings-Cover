"""Pure unit tests for the rules + calculation engines (no DB, no HTTP). Expected amounts are worked out by hand in comments."""
from datetime import date

from app.engine.rules import evaluate_claim, suggest_repair_action

INCIDENT = date(2026, 6, 15)


def terms(**over):
    t = {"plan_name": "Test", "covered_perils": ["Theft", "Accidental Damage", "Fire"], "overall_limit": 60000, "default_per_item_limit": 20000,
         "per_item_limits": {"Laptop": 45000}, "cap_at_declared_value": False, "deductible_type": "fixed", "deductible_value": 1500,
         "calc_order": "LIMIT_THEN_DEDUCTIBLE", "depreciation": {"enabled": False}, "waiting_period_days": 0,
         "required_documents": {"Accidental Damage": ["damage_photo"], "Theft": ["police_report", "proof_of_purchase"]},
         "duplicate_window_days": 0, "disabled_rules": [],
         "exclusions": [{"code": "EXC-01", "title": "Wear and tear", "clause": "s3(a)", "incident_types": [], "damage_types": ["Wear and tear"], "severities": []},
                        {"code": "EXC-03", "title": "Intentional damage", "clause": "s3(c)", "incident_types": ["Intentional Damage"], "damage_types": [], "severities": []}]}
    t.update(over)
    return t


def item(i=1, comp="Screen", dmg="Cracked screen", sev="Moderate", act="Repair", parts=4000, labour=500, ver="Human Verified"):
    return {"id": i, "component": comp, "damage_type": dmg, "severity": sev, "repair_action": act, "parts_cost": parts, "labour_cost": labour,
            "verification_status": ver}


def ctx(items=None, t=None, cat="Laptop", value=55000, purchased=date(2024, 6, 15), itype="Accidental Damage", on=INCIDENT, evidence=("damage_photo",),
        insured=(1,), start=date(2026, 1, 1), end=date(2026, 12, 31), cancelled=None, activated=date(2026, 1, 1), others=(), paid_pol=0, paid_asset=0,
        owner=7, claimant=7, status="Active"):
    return {"policy": {"policy_number": "P1", "status": status, "start_date": start, "end_date": end, "activated_on": activated, "cancelled_on": cancelled,
                       "version": 1, "terms": t or terms(), "insured_asset_ids": list(insured)},
            "asset": {"id": 1, "owner_id": owner, "category": cat, "purchase_date": purchased, "declared_value": value, "proof_of_purchase_ref": "INV-1"},
            "asset_id": 1, "claimant_id": claimant, "incident": {"date": on, "type": itype, "location": ""},
            "items": items if items is not None else [item()], "evidence_types": list(evidence), "other_claims": list(others),
            "prior_paid_policy": paid_pol, "prior_paid_asset": paid_asset}


def outcome(res, rid, item_id=None):
    return [r["outcome"] for r in res["rule_results"] if r["rule_id"] == rid and (item_id is None or r["item_id"] == item_id)]


# 1 ------------------------------------------------------------------
def test_valid_claim_covered_asset_and_incident():
    res = evaluate_claim(ctx())
    # 4000 + 500 = 4500 ; limits not hit ; 4500 - 1500 deductible = 3000
    assert res["calculation"]["gross_total"] == 4500
    assert res["calculation"]["estimated_payable"] == 3000
    assert res["recommendation"] == "RECOMMEND_APPROVAL_REVIEW"
    assert outcome(res, "POL-001") == ["PASS"] and outcome(res, "POL-002") == ["PASS"] and outcome(res, "POL-003") == ["PASS"]
    assert all({"rule_id", "outcome", "inputs", "reason", "clause", "follow_up"} <= set(r) for r in res["rule_results"])  # decision trace shape


# 2 ------------------------------------------------------------------
def test_expired_policy_judged_on_incident_date():
    res = evaluate_claim(ctx(on=date(2027, 2, 1)))  # after 2026-12-31 expiry
    assert outcome(res, "POL-001") == ["FAIL"]
    assert res["recommendation"] == "RECOMMEND_REJECTION"
    assert res["calculation"]["estimated_payable"] == 0
    # same policy is eligible for an incident inside the period, whatever "today" is
    assert outcome(evaluate_claim(ctx(on=date(2026, 3, 1), status="Expired")), "POL-001") == ["PASS"]


def test_cancelled_and_draft_policies():
    assert outcome(evaluate_claim(ctx(cancelled=date(2026, 6, 1))), "POL-001") == ["FAIL"]
    assert outcome(evaluate_claim(ctx(cancelled=date(2026, 7, 1))), "POL-001") == ["PASS"]  # cancelled AFTER the loss
    assert outcome(evaluate_claim(ctx(activated=None, status="Draft")), "POL-001") == ["FAIL"]


def test_waiting_period():
    res = evaluate_claim(ctx(t=terms(waiting_period_days=14), on=date(2026, 1, 10)))
    assert outcome(res, "POL-011") == ["FAIL"] and res["recommendation"] == "RECOMMEND_REJECTION"
    assert outcome(evaluate_claim(ctx(t=terms(waiting_period_days=14), on=date(2026, 1, 15))), "POL-011") == ["PASS"]


# 3 ------------------------------------------------------------------
def test_asset_not_associated_with_policy():
    res = evaluate_claim(ctx(insured=(99,)))
    assert outcome(res, "POL-002") == ["FAIL"] and res["recommendation"] == "RECOMMEND_REJECTION"


def test_asset_not_in_claimants_inventory_is_flagged():
    res = evaluate_claim(ctx(owner=8, claimant=7))
    assert outcome(res, "POL-009") == ["FLAG"]


# 4 ------------------------------------------------------------------
def test_excluded_incident_type():
    res = evaluate_claim(ctx(itype="Intentional Damage"))
    assert outcome(res, "POL-003") == ["FAIL"] and outcome(res, "POL-004") == ["FAIL"]
    assert res["recommendation"] == "RECOMMEND_REJECTION" and res["calculation"]["estimated_payable"] == 0


def test_excluded_damage_item_removed_from_eligible_amount():
    items = [item(1), item(2, comp="Battery", dmg="Wear and tear", parts=2500, labour=300)]
    res = evaluate_claim(ctx(items))
    # screen 4500 eligible ; battery 2800 excluded by EXC-01 ; 4500 - 1500 = 3000
    assert res["calculation"]["excluded_total"] == 2800 and res["calculation"]["estimated_payable"] == 3000
    assert outcome(res, "POL-004", 2) == ["FAIL"]
    assert res["recommendation"] == "RECOMMEND_APPROVAL_REVIEW"  # item-level exclusion does not reject the whole claim


# 5 ------------------------------------------------------------------
def test_claim_exceeding_overall_limit():
    t = terms(default_per_item_limit=None)
    res = evaluate_claim(ctx([item(act="Replace", parts=70000, labour=0)], t=t, cat="Tablet", value=90000))
    c = res["calculation"]
    # 70000 -> overall limit 60000 (-10000) -> minus 1500 deductible = 58500
    assert c["overall_adjustment"] == 10000 and c["estimated_payable"] == 58500
    assert outcome(res, "POL-005") == ["ADJUSTED"]


def test_prior_payments_reduce_remaining_overall_limit():
    res = evaluate_claim(ctx([item(parts=9500, labour=500)], paid_pol=55000))
    # remaining 5000 ; 10000 -> 5000 ; minus 1500 = 3500
    assert res["calculation"]["estimated_payable"] == 3500 and res["calculation"]["facts"]["remaining_overall_limit"] == 5000


# 6 ------------------------------------------------------------------
def test_claim_exceeding_per_item_limit():
    res = evaluate_claim(ctx([item(act="Replace", parts=50000, labour=0)]))
    c = res["calculation"]
    # Laptop limit 45000 -> -5000 ; 45000 - 1500 = 43500
    assert c["per_item_adjustment"] == 5000 and c["estimated_payable"] == 43500
    assert outcome(res, "POL-006") == ["ADJUSTED"]


def test_cap_at_declared_value():
    res = evaluate_claim(ctx([item(act="Replace", parts=50000, labour=0)], t=terms(cap_at_declared_value=True), value=30000))
    assert res["calculation"]["per_item_adjustment"] == 20000 and res["calculation"]["estimated_payable"] == 28500


# 7 ------------------------------------------------------------------
def test_fixed_deductible():
    assert evaluate_claim(ctx())["calculation"]["deductible_applied"] == 1500


def test_loss_below_deductible_pays_nothing():
    res = evaluate_claim(ctx([item(comp="Battery", dmg="Other", parts=900, labour=300)]))
    assert res["calculation"]["estimated_payable"] == 0  # max(0, 1200 - 1500)
    assert res["recommendation"] == "RECOMMEND_REJECTION"


def test_percent_deductible_and_calculation_order_matters():
    items = [item(parts=10000, labour=0)]
    a = evaluate_claim(ctx(items, t=terms(deductible_type="percent", deductible_value=10, overall_limit=5000, per_item_limits={}, default_per_item_limit=None)))
    b = evaluate_claim(ctx(items, t=terms(deductible_type="percent", deductible_value=10, overall_limit=5000, per_item_limits={}, default_per_item_limit=None,
                                          calc_order="DEDUCTIBLE_THEN_LIMIT")))
    assert a["calculation"]["estimated_payable"] == 4000  # min(10000,5000)=5000 ; deductible 10% of 10000 = 1000 ; 5000-1000
    assert b["calculation"]["estimated_payable"] == 5000  # 10000-1000=9000 ; min(9000,5000)


def test_depreciation_on_replacement_only():
    t = terms(deductible_value=1000, depreciation={"enabled": True, "rate_per_year_pct": 10, "max_pct": 50, "applies_to": "replace"}, per_item_limits={"Smartphone": 60000})
    rep = evaluate_claim(ctx([item(comp="Whole device", dmg="Other", act="Replace", parts=42000, labour=0)], t=t, cat="Smartphone", purchased=date(2024, 6, 1)))
    # 2 completed years -> 20% of 42000 = 8400 ; 33600 - 1000 = 32600
    assert rep["calculation"]["depreciation_total"] == 8400 and rep["calculation"]["estimated_payable"] == 32600
    fix = evaluate_claim(ctx([item(parts=4000, labour=500)], t=t, purchased=date(2024, 6, 1)))
    assert fix["calculation"]["depreciation_total"] == 0 and fix["calculation"]["estimated_payable"] == 3500


# 8 ------------------------------------------------------------------
def test_missing_mandatory_evidence_triggers_pending_information():
    res = evaluate_claim(ctx(evidence=()))
    assert outcome(res, "POL-008") == ["PENDING"] and res["recommendation"] == "PENDING_INFORMATION"
    theft = evaluate_claim(ctx(itype="Theft", evidence=("police_report",)))  # proof_of_purchase satisfied by the asset's proof reference
    assert outcome(theft, "POL-008") == ["PASS"]


# 9 ------------------------------------------------------------------
def test_duplicate_claim_flagged():
    other = {"id": 5, "claim_number": "CLM-X", "asset_id": 1, "incident_date": INCIDENT, "status": "Submitted"}
    res = evaluate_claim(ctx(others=[other]))
    assert outcome(res, "POL-010") == ["FLAG"] and res["recommendation"] == "MANUAL_REVIEW"
    rejected = dict(other, status="Rejected with Reason")
    assert outcome(evaluate_claim(ctx(others=[rejected])), "POL-010") == ["PASS"]


# 10 -----------------------------------------------------------------
def test_damage_item_with_no_repair_price_is_not_guessed():
    res = evaluate_claim(ctx([item(act="Repair", parts=None, labour=None)]))
    assert outcome(res, "POL-012") == ["PENDING"]
    assert res["calculation"]["gross_total"] == 0 and res["calculation"]["flags"]
    assert res["recommendation"] == "PENDING_INFORMATION"
    inspect = evaluate_claim(ctx([item(act="Inspect Further", parts=4000, labour=500)]))
    assert outcome(inspect, "POL-012") == ["PENDING"]


def test_unverified_ai_item_blocks_completion_and_no_items_is_pending():
    assert outcome(evaluate_claim(ctx([item(ver="AI Suggested")])), "POL-013") == ["PENDING"]
    assert evaluate_claim(ctx([]))["recommendation"] == "PENDING_INFORMATION"


def test_rules_can_be_disabled_by_configuration():
    res = evaluate_claim(ctx(evidence=(), t=terms(disabled_rules=["POL-008"])))
    assert outcome(res, "POL-008") == ["SKIPPED"] and res["recommendation"] == "RECOMMEND_APPROVAL_REVIEW"


def test_engine_is_deterministic():
    assert evaluate_claim(ctx()) == evaluate_claim(ctx())


def test_repair_vs_replace_guidance():
    assert suggest_repair_action(4500, 50000)[0] == "Repair"
    assert suggest_repair_action(36000, 50000)[0] == "Replace"
    assert suggest_repair_action(None, 50000)[0] == "Inspect Further"
