"""Administrator financial performance: how premium income is spent. All figures come from the database; assumptions are labelled."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import services as S
from .. import v3
from ..catalog import FINANCE_DEFAULTS
from ..database import get_db
from ..models import Asset, Claim, FinancialExpense, Policy, PremiumTransaction, RiskReserve, Settlement, SystemSetting, User
from ..security import require_roles

router = APIRouter(prefix="/api/v2/finance")
DISCLAIMER = ("Sample assumptions for an academic prototype. These are NOT validated actuarial projections and nothing here guarantees profit.")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def assumptions(db: Session) -> dict:
    out = {}
    for k, dv in FINANCE_DEFAULTS.items():
        row = db.get(SystemSetting, k)
        out[k.split(".", 1)[1]] = float(row.value if row else dv)
    return out


def months_back(n: int) -> list[str]:
    today, out = date.today().replace(day=1), []
    for i in range(n - 1, -1, -1):
        out.append(f"{v3.add_months(today, -i):%Y-%m}")
    return out


def r2(x) -> float:
    return round(float(x), 2)


@router.get("/summary")
def summary(months: int = Query(6, ge=1, le=24), user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    a = assumptions(db)
    labels = months_back(months)
    prem = {m: 0.0 for m in labels}; pay = {m: 0.0 for m in labels}
    for amt, at in db.execute(select(PremiumTransaction.amount, PremiumTransaction.paid_at).where(PremiumTransaction.status == "Paid")):
        k = f"{at:%Y-%m}"
        if k in prem:
            prem[k] += float(amt)
    for amt, at in db.execute(select(Settlement.amount, Settlement.settled_at).where(Settlement.status == "Settled")):
        k = f"{at:%Y-%m}"
        if k in pay:
            pay[k] += float(amt)
    rec = {"operating": {}, "ai_technology": {}}
    for per, cat, amt in db.execute(select(FinancialExpense.period, FinancialExpense.category, FinancialExpense.amount)):
        rec[cat][per] = rec[cat].get(per, 0.0) + float(amt)
    res = {}
    for per, amt in db.execute(select(RiskReserve.period, RiskReserve.amount)):
        res[per] = res.get(per, 0.0) + float(amt)
    rows, assumed_any = [], False
    for m in labels:
        p = prem[m]
        op, ai, rr = rec["operating"].get(m), rec["ai_technology"].get(m), res.get(m)
        assumed = [n for n, v in (("operating", op), ("ai_technology", ai), ("risk_reserve", rr)) if v is None]
        assumed_any |= bool(assumed)
        op = p * a["operating_pct"] / 100 if op is None else op
        ai = p * a["ai_tech_pct"] / 100 if ai is None else ai
        rr = p * a["reserve_pct"] / 100 if rr is None else rr
        exp_claims = max(pay[m], p * a["expected_loss_ratio_pct"] / 100)
        rows.append({"month": m, "premium_income": r2(p), "claim_payouts": r2(pay[m]), "expected_claims": r2(exp_claims), "operating_expenses": r2(op), "ai_technology_expenses": r2(ai),
                     "risk_reserve": r2(rr), "expected_surplus": r2(p - exp_claims - op - ai - rr), "actual_surplus": r2(p - pay[m] - op - ai - rr), "assumed_items": assumed})
    tot = {k: r2(sum(r[k] for r in rows)) for k in ("premium_income", "claim_payouts", "expected_claims", "operating_expenses", "ai_technology_expenses", "risk_reserve", "expected_surplus", "actual_surplus")}
    active = db.scalars(select(Policy).where(Policy.status == "Active", Policy.category_id.is_not(None))).all()
    cl = lambda *w: db.scalar(select(func.count()).select_from(Claim).where(Claim.flow == "auto", *w)) or 0
    by_cat = {}
    for p in active:
        e = by_cat.setdefault(p.assets[0].asset.category if p.assets else "?", {"category": p.assets[0].asset.category if p.assets else "?", "active_policies": 0, "monthly_premium": 0.0})
        e["active_policies"] += 1; e["monthly_premium"] += float(p.monthly_premium)
    for e in by_cat.values():
        e["annualized_premium"] = r2(e["monthly_premium"] * 12)
    for name, collected in db.execute(select(Asset.category, func.sum(PremiumTransaction.amount)).select_from(PremiumTransaction).join(Policy, Policy.id == PremiumTransaction.policy_id)
                                      .join(Asset, Asset.category_id == Policy.category_id, isouter=True).where(PremiumTransaction.status == "Paid").group_by(Asset.category)):
        pass
    cat_rev = {}
    for cat, amt in db.execute(select(Asset.category, PremiumTransaction.amount).select_from(PremiumTransaction).join(Policy, Policy.id == PremiumTransaction.policy_id)
                               .join(__import__("app.models", fromlist=["PolicyAsset"]).PolicyAsset, __import__("app.models", fromlist=["PolicyAsset"]).PolicyAsset.policy_id == Policy.id)
                               .join(Asset, Asset.id == __import__("app.models", fromlist=["PolicyAsset"]).PolicyAsset.asset_id).where(PremiumTransaction.status == "Paid")):
        cat_rev[cat] = cat_rev.get(cat, 0.0) + float(amt)
    cat_pay = {}
    for cat, amt in db.execute(select(Asset.category, Settlement.amount).select_from(Settlement).join(Claim, Claim.id == Settlement.claim_id).join(Asset, Asset.id == Claim.asset_id).where(Settlement.status == "Settled")):
        cat_pay[cat] = cat_pay.get(cat, 0.0) + float(amt)
    for cat, e in by_cat.items():
        e["premiums_collected"], e["claims_paid"] = r2(cat_rev.get(cat, 0)), r2(cat_pay.get(cat, 0))
        e["net"] = r2(e["premiums_collected"] - e["claims_paid"]); e["monthly_premium"] = r2(e["monthly_premium"])
    warnings = []
    for r in rows:
        if r["premium_income"] > 0 and r["expected_claims"] + r["operating_expenses"] + r["ai_technology_expenses"] + r["risk_reserve"] > r["premium_income"]:
            warnings.append(f"{r['month']}: expected claims and expenses exceed premium income (deficit {abs(r['expected_surplus']):,.0f}).")
    if tot["actual_surplus"] < 0:
        warnings.append("Actual payouts and expenses exceed premium income for this period.")
    income = tot["premium_income"]
    distribution = [{"name": n, "amount": tot[k]} for n, k in (("Expected claims", "expected_claims"), ("Operating expenses", "operating_expenses"), ("AI and technology", "ai_technology_expenses"), ("Risk reserve", "risk_reserve"))]
    distribution.append({"name": "Surplus" if tot["expected_surplus"] >= 0 else "Deficit", "amount": abs(tot["expected_surplus"])})
    return {"disclaimer": DISCLAIMER, "assumptions": a, "months": rows, "totals": tot, "warnings": warnings, "distribution": distribution, "policy_breakdown": sorted(by_cat.values(), key=lambda e: e["category"]),
            "assumed_values_used": assumed_any, "formula": "Expected surplus = premium income - expected claims - operating expenses - AI/technology expenses - risk reserve",
            "counts": {"active_policies": len(active), "insured_students": len({p.student_id for p in active}), "insured_assets": len(active),
                       "monthly_premium_collection": r2(sum(float(p.monthly_premium) for p in active)), "annualized_premium_income": r2(sum(float(p.monthly_premium) for p in active) * 12),
                       "claims_submitted": cl(), "claims_approved": cl(Claim.status.in_(v3.ACTIVE_CLAIM)), "claims_rejected": cl(Claim.status == "Rejected"),
                       "claims_in_review": cl(Claim.status == "Exceptional Review Required"), "total_payouts": r2(db.scalar(select(func.coalesce(func.sum(Settlement.amount), 0)).where(Settlement.status == "Settled")))}}


class ScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    students: int = Field(default=1000, ge=0, le=10_000_000)
    avg_monthly_premium: float = Field(default=79, ge=0, le=100_000)
    expected_claims: float = Field(default=40000, ge=0, le=1_000_000_000)
    operating_expenses: float = Field(default=12000, ge=0, le=1_000_000_000)
    ai_technology_expenses: float = Field(default=5000, ge=0, le=1_000_000_000)
    risk_reserve: float = Field(default=10000, ge=0, le=1_000_000_000)


def scenario_calc(b: ScenarioIn) -> dict:
    income = round(b.students * b.avg_monthly_premium, 2)
    spend = b.expected_claims + b.operating_expenses + b.ai_technology_expenses + b.risk_reserve
    surplus = round(income - spend, 2)
    fixed = b.operating_expenses + b.ai_technology_expenses + b.risk_reserve
    warnings = []
    if surplus < 0:
        warnings.append(f"Deficit: expected claims and expenses ({spend:,.0f}) exceed premium income ({income:,.0f}).")
    elif income and surplus / income < 0.05:
        warnings.append("The margin is under 5%, so a modest rise in claims would cause a deficit.")
    return {"premium_income": income, "rows": [{"name": "Premium income", "amount": income}, {"name": "Expected claims", "amount": b.expected_claims},
                                               {"name": "Operating expenses", "amount": b.operating_expenses}, {"name": "AI and technology expenses", "amount": b.ai_technology_expenses},
                                               {"name": "Risk reserve allocation", "amount": b.risk_reserve}, {"name": "Surplus" if surplus >= 0 else "Deficit", "amount": surplus}],
            "surplus": surplus, "margin_pct": round(100 * surplus / income, 1) if income else None, "loss_ratio_pct": round(100 * b.expected_claims / income, 1) if income else None,
            "break_even_loss_ratio_pct": round(100 * (income - fixed) / income, 1) if income else None, "warnings": warnings, "disclaimer": DISCLAIMER}


@router.post("/scenario")
def scenario(body: ScenarioIn, user: User = Depends(require_roles("admin"))):
    return scenario_calc(body)


class AssumptionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_loss_ratio_pct: float = Field(ge=0, le=300)
    operating_pct: float = Field(ge=0, le=100)
    ai_tech_pct: float = Field(ge=0, le=100)
    reserve_pct: float = Field(ge=0, le=100)


@router.put("/assumptions")
def set_assumptions(body: AssumptionsIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    before = assumptions(db)
    for k, v in body.model_dump().items():
        key = f"fin.{k}"
        row = db.get(SystemSetting, key)
        if row:
            row.value, row.updated_by = str(v), user.id
        else:
            db.add(SystemSetting(key=key, value=str(v), updated_by=user.id))
    S.audit(db, "finance", 0, "assumptions_updated", {"before": before, "after": body.model_dump()}, user)
    db.commit()
    return assumptions(db)


class ExpenseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str
    category: str
    amount: float = Field(gt=0, le=1_000_000_000)
    description: str = Field(default="", max_length=200)


@router.post("/expenses", status_code=201)
def add_expense(body: ExpenseIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    if not PERIOD_RE.match(body.period):
        raise HTTPException(422, "period must be YYYY-MM")
    if body.category not in ("operating", "ai_technology"):
        raise HTTPException(422, "category must be operating or ai_technology")
    e = FinancialExpense(period=body.period, category=body.category, amount=body.amount, description=body.description, created_by=user.id)
    db.add(e); db.flush()
    S.audit(db, "finance", e.id, "expense_recorded", body.model_dump(), user)
    db.commit()
    return {"id": e.id, **body.model_dump()}


class ReserveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str
    amount: float = Field(gt=0, le=1_000_000_000)
    description: str = Field(default="", max_length=200)


@router.post("/reserves", status_code=201)
def add_reserve(body: ReserveIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    if not PERIOD_RE.match(body.period):
        raise HTTPException(422, "period must be YYYY-MM")
    r = RiskReserve(period=body.period, amount=body.amount, description=body.description, created_by=user.id)
    db.add(r); db.flush()
    S.audit(db, "finance", r.id, "reserve_recorded", body.model_dump(), user)
    db.commit()
    return {"id": r.id, **body.model_dump()}
