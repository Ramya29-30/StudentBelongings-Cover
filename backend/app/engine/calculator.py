"""Deterministic, explainable claim calculation.  No AI is involved anywhere in this module.

Sequence (documented in docs/RULES_CATALOGUE.md):
  1. per damage item: gross = parts + labour           (items with no price are NOT guessed; they are flagged)
  2. item-level exclusion  -> eligible 0               (POL-004)
  3. depreciation          -> only if plan enables it   (applies_to: "replace" or "all"; completed years of age)
  4. subtotal of eligible item amounts
  5. per-item limit        -> min(subtotal, limit - already paid on this asset)          (POL-006)
  6. then, depending on plan.calc_order:
       LIMIT_THEN_DEDUCTIBLE (baseline): payable = max(0, min(amount, remaining overall limit) - deductible)
       DEDUCTIBLE_THEN_LIMIT           : payable = min(max(0, amount - deductible), remaining overall limit)
  Percent deductibles are taken on the amount after the per-item limit (step 5).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .money import D, q

ZERO = Decimal("0")


def completed_years(start: date, end: date) -> int:
    if end < start:
        return 0
    return end.year - start.year - ((end.month, end.day) < (start.month, start.day))


def item_is_priced(item: dict) -> bool:
    if item.get("repair_action") == "Inspect Further":
        return False
    return not (item.get("parts_cost") is None and item.get("labour_cost") is None)


def _inr(x) -> str:
    return f"{float(x):,.2f}"


def calculate_claim(terms: dict, asset: dict | None, incident_date: date, items: list[dict], item_exclusions: dict,
                    prior_paid_policy: float = 0, prior_paid_asset: float = 0, blocked_by: list[str] | None = None) -> dict:
    blocked_by = blocked_by or []
    lines: list[dict] = []
    flags: list[str] = []
    state = {"running": ZERO}

    def add(kind, label, amount, rule="", note="", item_id=None, running=None):
        amount = q(amount)
        if running is None:
            state["running"] = q(state["running"] + amount)
        else:
            state["running"] = q(running)
        lines.append({"seq": len(lines) + 1, "kind": kind, "label": label, "amount": float(amount),
                      "running_total": float(state["running"]), "rule_ref": rule, "note": note, "item_id": item_id})

    dep = terms.get("depreciation") or {}
    dep_on = bool(dep.get("enabled"))
    rate = D(dep.get("rate_per_year_pct", 0)) or ZERO
    max_pct = D(dep.get("max_pct", 100)) or ZERO
    applies_to = dep.get("applies_to", "replace")
    age = completed_years(asset["purchase_date"], incident_date) if asset else 0

    gross_total = depr_total = excluded_total = subtotal = ZERO
    uncovered: list[dict] = []
    per_item = []
    for it in items:
        iid = it.get("id")
        label = f"{it['component']} - {it['damage_type']} ({it['repair_action']})"
        if not item_is_priced(it):
            flags.append(f"Item '{it['component']}' has no verified price or needs further inspection; it is excluded from the total until priced.")
            add("item", f"{label}: NOT PRICED - requires assessment", 0, "POL-012", "No price available; the system never invents prices.", iid)
            per_item.append({"item_id": iid, "gross": None, "eligible": 0.0, "priced": False})
            continue
        parts, labour = D(it.get("parts_cost")) or ZERO, D(it.get("labour_cost")) or ZERO
        gross = q(parts + labour)
        gross_total += gross
        add("item", f"{label}: parts {_inr(parts)} + labour {_inr(labour)}", gross, "", "Gross assessed loss", iid)
        exc = item_exclusions.get(iid)
        if exc:
            excluded_total += gross
            add("exclusion", f"Excluded by {exc['code']} - {exc['title']}", -gross, "POL-004", exc.get("clause", ""), iid)
            uncovered.append({"reason": f"Excluded by {exc['code']} ({exc['title']})", "amount": float(gross), "item_id": iid})
            per_item.append({"item_id": iid, "gross": float(gross), "eligible": 0.0, "priced": True, "excluded": exc["code"]})
            continue
        d_amt = ZERO
        if dep_on and (applies_to == "all" or it["repair_action"] == "Replace") and age > 0:
            pct = min(max_pct, rate * age)
            d_amt = q(gross * pct / 100)
            depr_total += d_amt
            add("depreciation", f"Depreciation {pct}% ({age} completed year(s) x {rate}%, cap {max_pct}%)", -d_amt, "POL-007A",
                "Configured depreciation", iid)
            uncovered.append({"reason": f"Depreciation {pct}%", "amount": float(d_amt), "item_id": iid})
        subtotal += gross - d_amt
        per_item.append({"item_id": iid, "gross": float(gross), "eligible": float(gross - d_amt), "priced": True})

    add("subtotal", "Eligible assessed loss after exclusions and depreciation", 0, "", "", None, running=subtotal)
    lines[-1]["amount"] = float(q(subtotal))

    # ---- per-item (per insured asset) limit
    limit = D((terms.get("per_item_limits") or {}).get(asset["category"])) if asset else None
    if limit is None:
        limit = D(terms.get("default_per_item_limit"))
    if asset and terms.get("cap_at_declared_value", False):
        decl = D(asset["declared_value"])
        limit = decl if limit is None else min(limit, decl)
    remaining_item = None if limit is None else max(ZERO, limit - D(prior_paid_asset))
    after_item = subtotal if remaining_item is None else min(subtotal, remaining_item)
    item_adj = q(subtotal - after_item)
    if item_adj > 0:
        add("limit", f"Per-item limit adjustment (limit {_inr(limit)}, already paid on asset {_inr(prior_paid_asset)})", -item_adj, "POL-006")
        uncovered.append({"reason": "Per-item limit", "amount": float(item_adj), "item_id": None})

    # ---- deductible and overall limit, in the configured order
    ded_type, ded_val = terms.get("deductible_type", "fixed"), D(terms.get("deductible_value", 0)) or ZERO
    ded = q(after_item * ded_val / 100) if ded_type == "percent" else q(ded_val)
    ded_label = f"Deductible ({ded_val}%)" if ded_type == "percent" else f"Deductible (fixed {_inr(ded_val)})"
    overall = D(terms.get("overall_limit"))
    remaining_policy = max(ZERO, overall - D(prior_paid_policy)) if overall is not None else None
    order = terms.get("calc_order", "LIMIT_THEN_DEDUCTIBLE")

    if order == "DEDUCTIBLE_THEN_LIMIT":
        ded_applied = min(ded, after_item)
        add("deductible", ded_label, -ded_applied, "POL-007")
        after_ded = after_item - ded_applied
        payable = after_ded if remaining_policy is None else min(after_ded, remaining_policy)
        overall_adj = q(after_ded - payable)
        if overall_adj > 0:
            add("limit", f"Overall coverage limit adjustment (remaining {_inr(remaining_policy)})", -overall_adj, "POL-005")
    else:
        capped = after_item if remaining_policy is None else min(after_item, remaining_policy)
        overall_adj = q(after_item - capped)
        if overall_adj > 0:
            add("limit", f"Overall coverage limit adjustment (remaining {_inr(remaining_policy)})", -overall_adj, "POL-005")
        ded_applied = min(ded, capped)
        add("deductible", ded_label, -ded_applied, "POL-007")
        payable = max(ZERO, capped - ded)
    payable = q(payable)
    if overall_adj > 0:
        uncovered.append({"reason": "Overall coverage limit", "amount": float(overall_adj), "item_id": None})
    if ded_applied > 0:
        uncovered.append({"reason": "Deductible", "amount": float(q(ded_applied)), "item_id": None})

    if blocked_by:
        add("blocked", "Claim not payable: " + "; ".join(blocked_by), -payable, "", "Blocking rule failure")
        uncovered.append({"reason": "Claim ineligible: " + "; ".join(blocked_by), "amount": float(payable), "item_id": None})
        payable = ZERO

    add("final", "ESTIMATED PAYABLE AMOUNT (recommendation only - requires human review)", 0, "", "", None, running=payable)
    lines[-1]["amount"] = float(payable)
    return {
        "lines": lines, "flags": flags, "uncovered": uncovered, "per_item": per_item, "calc_order": order,
        "gross_total": float(q(gross_total)), "excluded_total": float(q(excluded_total)),
        "depreciation_total": float(q(depr_total)), "eligible_subtotal": float(q(subtotal)),
        "per_item_adjustment": float(item_adj), "overall_adjustment": float(overall_adj),
        "deductible_applied": float(q(ded_applied)), "estimated_payable": float(payable),
        "uncovered_total": float(q(gross_total - payable)),
        "facts": {"per_item_limit": None if limit is None else float(limit),
                  "remaining_item_limit": None if remaining_item is None else float(remaining_item),
                  "overall_limit": None if overall is None else float(overall),
                  "remaining_overall_limit": None if remaining_policy is None else float(remaining_policy),
                  "deductible": float(ded), "age_years": age},
    }
