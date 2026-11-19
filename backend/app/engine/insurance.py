"""Premium, eligibility and claim-amount calculations for the self-service product (pure functions, Decimal arithmetic).

Every input comes from the database (an AssetCategory row or the terms frozen on a Policy), never from the browser.
Formulas (documented in docs/INSURANCE_MODEL.md):
    Annual premium         = monthly premium x 12
    Eligible loss          = assessed loss x (1 - depreciation%)             (depreciation is 0 unless configured)
    Payable before deductible = MIN(eligible loss, maximum coverage, remaining policy limit)
    Payable                = MAX(0, payable before deductible - deductible)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .money import D, q


def inr(x) -> str:
    v = q(x)
    return f"\u20b9{v:,.0f}" if v == v.to_integral_value() else f"\u20b9{v:,.2f}"


def category_terms(c) -> dict:
    """Plain-dict snapshot of an AssetCategory (what a policy freezes at purchase)."""
    return {"category_id": c.id, "name": c.name, "min_purchase_value": float(c.min_purchase_value), "monthly_premium": float(c.monthly_premium),
            "max_coverage": float(c.max_coverage), "deductible": float(c.deductible), "policy_months": c.policy_months,
            "waiting_period_days": c.waiting_period_days, "depreciation_pct_per_year": float(c.depreciation_pct_per_year),
            "depreciation_max_pct": float(c.depreciation_max_pct), "exclusions": list(c.exclusions or []),
            "covered_incident_types": list(c.covered_incident_types or []), "excluded_damage_types": list(c.excluded_damage_types or []),
            "damage_types": list(c.damage_types or []), "reference_repair_costs": dict(c.reference_repair_costs or {})}


def check_eligibility(terms: dict, purchase_price, active: bool = True) -> dict:
    name = terms["name"].lower()
    verb = "are" if name.endswith("s") else "is"
    if not active:
        return {"eligible": False, "reason": f"{terms['name']} cover is not currently offered."}
    price, minimum = D(purchase_price), D(terms["min_purchase_value"])
    if price < minimum:
        return {"eligible": False, "reason": f"Your {name} {verb} not eligible because the minimum purchase value for this category is {inr(minimum)}."}
    return {"eligible": True, "reason": f"Eligible: the purchase value meets the {inr(minimum)} minimum for {terms['name']}."}


def quote(terms: dict, purchase_price) -> dict:
    price, monthly, cover = D(purchase_price), D(terms["monthly_premium"]), D(terms["max_coverage"])
    return {"category": terms["name"], "purchase_value": float(q(price)), "monthly_premium": float(q(monthly)), "annual_premium": float(q(monthly * 12)),
            "max_coverage": float(q(cover)), "estimated_max_claim": float(q(min(price, cover))), "deductible": float(q(D(terms["deductible"]))),
            "policy_months": terms.get("policy_months", 12), "waiting_period_days": terms.get("waiting_period_days", 0), "exclusions": terms.get("exclusions", []),
            "covered_incident_types": terms.get("covered_incident_types", []),
            "formula": {"annual_premium": f"{inr(monthly)} x 12 = {inr(monthly * 12)}",
                        "estimated_max_claim": f"MIN({inr(price)} purchase value, {inr(cover)} maximum coverage) = {inr(min(price, cover))}"}}


def depreciation_pct(terms: dict, purchase_date: date, incident_date: date) -> Decimal:
    rate, cap = D(terms.get("depreciation_pct_per_year", 0)), D(terms.get("depreciation_max_pct", 0))
    if rate <= 0 or cap <= 0:
        return Decimal("0")
    years = Decimal(max(0, (incident_date - purchase_date).days)) / Decimal("365.25")
    return q(min(rate * years, cap))


def calculate_claim(terms: dict, purchase_date: date, incident_date: date, assessed_loss, previously_paid=0) -> dict:
    """Returns the payable amount and a step-by-step breakdown the student can read."""
    loss, cover, ded = D(assessed_loss), D(terms["max_coverage"]), D(terms["deductible"])
    dep = depreciation_pct(terms, purchase_date, incident_date)
    eligible = q(loss * (Decimal(100) - dep) / Decimal(100))
    remaining = max(Decimal(0), cover - D(previously_paid))
    cap = min(cover, remaining)
    before = min(eligible, cap)
    payable = max(Decimal(0), before - ded)
    binding = "assessed loss" if eligible <= cap else ("remaining policy limit" if remaining < cover else "maximum coverage")
    lines = [{"label": "Assessed loss", "amount": float(q(loss)), "note": "Determined by the system from the claim (see calculation basis)."}]
    if dep > 0:
        lines.append({"label": f"Depreciation {dep}%", "amount": float(q(eligible - loss)), "note": "Configured for this category."})
    lines.append({"label": "Eligible loss", "amount": float(eligible), "note": "Assessed loss after depreciation."})
    lines.append({"label": "Maximum coverage", "amount": float(q(cover)), "note": "Frozen on the policy at purchase."})
    if D(previously_paid) > 0:
        lines.append({"label": "Already paid on this policy", "amount": float(q(-D(previously_paid))), "note": f"Remaining limit {inr(remaining)}."})
    lines.append({"label": "Payable before deductible", "amount": float(q(before)), "note": f"MIN(eligible loss, limit). Binding limit: {binding}."})
    lines.append({"label": "Deductible", "amount": float(q(-min(ded, before))), "note": "Frozen on the policy at purchase."})
    lines.append({"label": "Payable amount", "amount": float(q(payable)), "note": "Final amount, never above the maximum coverage."})
    return {"payable": float(q(payable)), "eligible_loss": float(eligible), "payable_before_deductible": float(q(before)), "deductible": float(q(ded)),
            "depreciation_pct": float(dep), "binding_limit": binding, "lines": lines}
