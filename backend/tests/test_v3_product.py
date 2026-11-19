"""Self-service product: registration, categories, eligibility, assets, purchase, premiums, calculation, uploads, finance."""
from datetime import date, timedelta

import pytest

from app.engine import insurance as I
from tests.conftest import login
from tests.helpers_v3 import add_asset, approve_evidence, cat_id, insured, make_img, register_login

SPEC = {"Earbuds": (2500, 50, 2000), "Smartphone": (15000, 99, 10000), "Tablet": (13000, 79, 8000), "Laptop": (25000, 99, 18000), "Bicycle": (10000, 69, 7000), "Smartwatch": (3000, 59, 2500)}


def test_registration_login_and_role_cannot_be_chosen(client):
    h = register_login(client)
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "student" if "role" in me else me["user"]["role"] == "student"
    r = client.post("/api/auth/register", json={"username": "evil", "full_name": "E", "email": "e@example.edu", "password": "Str0ng!pass-123", "role": "admin"})
    assert r.status_code == 422  # extra fields are forbidden
    assert client.post("/api/auth/register", json={"username": "tester", "full_name": "T", "email": "t@example.edu", "password": "Str0ng!pass-123"}).status_code == 409
    assert client.post("/api/auth/register", json={"username": "weakpw", "full_name": "W", "email": "w@example.edu", "password": "abc"}).status_code in (400, 422)


def test_categories_match_the_specified_pricing_table(client):
    cats = {c["name"]: c for c in client.get("/api/v2/categories").json()}
    assert set(cats) == set(SPEC)
    for n, (mn, prem, cov) in SPEC.items():
        assert (cats[n]["min_purchase_value"], cats[n]["monthly_premium"], cats[n]["max_coverage"]) == (mn, prem, cov)
        assert cats[n]["annual_premium"] == prem * 12


def test_only_admin_can_change_categories_and_changes_are_audited_and_validated(client, student, admin):
    c = next(c for c in client.get("/api/v2/categories").json() if c["name"] == "Earbuds")
    body = {k: c[k] for k in ("name", "description", "min_purchase_value", "monthly_premium", "max_coverage", "deductible", "policy_months", "waiting_period_days", "depreciation_pct_per_year",
                              "depreciation_max_pct", "exclusions", "covered_incident_types", "excluded_damage_types", "damage_types", "reference_repair_costs", "eligibility_conditions", "requires_serial", "active")}
    assert client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"monthly_premium": 60}, headers=student).status_code == 403
    assert client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"monthly_premium": 60, "max_coverage": 2200}, headers=admin).status_code == 200
    assert client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"monthly_premium": -5}, headers=admin).status_code == 422
    assert client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"deductible": 5000}, headers=admin).status_code == 422
    new = next(x for x in client.get("/api/v2/categories").json() if x["name"] == "Earbuds")
    assert (new["monthly_premium"], new["max_coverage"]) == (60, 2200)
    log = client.get("/api/audit?entity_type=category", headers=admin).json()
    assert any(r["action"] == "category_updated" for r in log)
    off = client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"active": False}, headers=admin).json()
    assert off["active"] is False and all(x["name"] != "Earbuds" for x in client.get("/api/v2/categories").json())


def test_eligibility_messages_and_minimums(client, student):
    r = client.post("/api/v2/eligibility", json={"category_id": cat_id(client, "Earbuds"), "purchase_price": 1500}, headers=student).json()
    assert r["eligible"] is False and r["reason"] == "Your earbuds are not eligible because the minimum purchase value for this category is \u20b92,500."
    ok = client.post("/api/v2/eligibility", json={"category_id": cat_id(client, "Earbuds"), "purchase_price": 3000}, headers=student).json()
    assert ok["eligible"] and ok["quote"]["monthly_premium"] == 50 and ok["quote"]["annual_premium"] == 600 and ok["quote"]["estimated_max_claim"] == 2000
    for n, (mn, _p, _c) in SPEC.items():
        assert not client.post("/api/v2/eligibility", json={"category_id": cat_id(client, n), "purchase_price": mn - 1}, headers=student).json()["eligible"]
        assert client.post("/api/v2/eligibility", json={"category_id": cat_id(client, n), "purchase_price": mn}, headers=student).json()["eligible"]


def test_claim_calculation_examples_from_the_brief_and_caps():
    t = {"name": "Laptop", "monthly_premium": 99, "max_coverage": 18000, "deductible": 0, "depreciation_pct_per_year": 0, "depreciation_max_pct": 0}
    d0 = date(2026, 1, 1)
    assert I.calculate_claim(t, d0, d0, 12000)["payable"] == 12000
    assert I.calculate_claim(t, d0, d0, 25000)["payable"] == 18000
    assert I.calculate_claim(t | {"deductible": 1000}, d0, d0, 12000)["payable"] == 11000
    assert I.calculate_claim(t, d0, d0, 12000, previously_paid=10000)["payable"] == 8000  # remaining policy limit
    assert I.calculate_claim(t, d0, d0, 12000, previously_paid=18000)["payable"] == 0
    dep = I.calculate_claim(t | {"depreciation_pct_per_year": 10, "depreciation_max_pct": 50}, date(2024, 1, 1), date(2026, 1, 1), 10000)
    assert 7900 < dep["payable"] < 8100 and dep["depreciation_pct"] > 19
    assert I.quote(t, 40000)["annual_premium"] == 1188 and I.quote(t, 5000)["estimated_max_claim"] == 5000


def test_asset_registration_rules_and_upload_security(client):
    h = register_login(client)
    low = add_asset(client, h, "Earbuds", 1500, serial="")
    assert low.status_code == 422 and "not eligible" in low.json()["detail"]
    assert add_asset(client, h, "Laptop", 42000, serial="").status_code == 422  # serial required
    bad = client.post("/api/v2/assets", data={"category_id": cat_id(client, "Earbuds"), "brand": "a", "model": "b", "purchase_price": 3000, "purchase_date": str(date.today())},
                      files={"invoice": ("i.png", b"this is not an image at all", "image/png"), "photo": ("p.png", make_img(2), "image/png")}, headers=h)
    assert bad.status_code == 422
    exe = client.post("/api/v2/assets", data={"category_id": cat_id(client, "Earbuds"), "brand": "a", "model": "b", "purchase_price": 3000, "purchase_date": str(date.today())},
                      files={"invoice": ("i.exe", b"MZ\x90\x00", "application/octet-stream"), "photo": ("p.png", make_img(2), "image/png")}, headers=h)
    assert exe.status_code == 422
    fut = add_asset(client, h, "Earbuds", 3000, serial="", purchase_date=str(date.today() + timedelta(days=3)))
    assert fut.status_code == 422
    ok = add_asset(client, h, "Earbuds", 3000, serial="")
    assert ok.status_code == 201
    a = ok.json()
    assert a["invoice_verified"] is False and a["invoice_status"] == "Uploaded, not yet verified" and a["eligibility_status"] == "Eligible"
    # stored names are server generated (no user-controlled path), files are not world readable via static routes
    from app.database import SessionLocal
    from app.models import Asset
    with SessionLocal() as db:
        stored = db.get(Asset, a["id"]).photo_file
    assert stored not in str(a) and client.get(f"/{stored}").status_code == 404 and client.get(f"/uploads/{stored}").status_code == 404
    assert client.get(f"/api/v2/assets/{a['id']}/file/photo", headers=h).status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/v2/assets/{a['id']}/file/photo").status_code == 401


def test_oversize_upload_is_refused(client, monkeypatch):
    from app.routers import insure
    h = register_login(client)
    monkeypatch.setattr(insure.settings, "MAX_UPLOAD_MB", 0.01)
    r = add_asset(client, h, "Earbuds", 3000, serial="")
    assert r.status_code in (413, 422)


def test_students_cannot_see_each_others_assets_files_or_policies(client):
    h1, h2 = register_login(client, "one"), register_login(client, "two")
    a, p = insured(client, h1)
    assert client.get(f"/api/v2/assets/{a['id']}", headers=h2).status_code == 404
    assert client.get(f"/api/v2/assets/{a['id']}/file/invoice", headers=h2).status_code == 404
    assert client.get(f"/api/v2/assets/{a['id']}/quote", headers=h2).status_code == 404
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h2).status_code == 404
    assert client.get(f"/api/v2/policies/{p['id']}", headers=h2).status_code == 404
    assert client.get("/api/v2/policies", headers=h2).json() == [] and client.get("/api/v2/assets", headers=h2).json() == []
    assert client.get("/api/v2/payments", headers=h2).json() == []


def test_purchase_freezes_server_side_terms_and_rejects_tampering(client, admin):
    h = register_login(client)
    a = add_asset(client, h, "Laptop", 42000).json()
    q = client.get(f"/api/v2/assets/{a['id']}/quote", headers=h).json()["quote"]
    assert (q["monthly_premium"], q["annual_premium"], q["max_coverage"], q["estimated_max_claim"]) == (99, 1188, 18000, 18000)
    # no cover before an administrator approves the registration evidence
    early = client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert early.status_code == 409 and "administrator" in early.json()["detail"]
    assert approve_evidence(client, a["id"]).status_code == 200
    # the browser cannot send premium or coverage values
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True, "monthly_premium": 1, "max_coverage": 99999}, headers=h).status_code == 422
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": False}, headers=h).status_code == 422
    p = client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert p.status_code == 201
    p = p.json()
    assert p["status"] == "Active" and p["monthly_premium"] == 99 and p["max_coverage"] == 18000 and p["premiums_paid"] == 99
    assert client.post(f"/api/v2/assets/{a['id']}/purchase", json={"accept_terms": True}, headers=h).status_code == 409  # no double cover
    # later admin price change never alters the issued policy
    c = next(c for c in client.get("/api/v2/categories").json() if c["name"] == "Laptop")
    body = {k: c[k] for k in ("name", "description", "min_purchase_value", "monthly_premium", "max_coverage", "deductible", "policy_months", "waiting_period_days", "depreciation_pct_per_year",
                              "depreciation_max_pct", "exclusions", "covered_incident_types", "excluded_damage_types", "damage_types", "reference_repair_costs", "eligibility_conditions", "requires_serial", "active")}
    assert client.put(f"/api/v2/admin/categories/{c['id']}", json=body | {"monthly_premium": 150, "max_coverage": 9000}, headers=admin).status_code == 200
    again = client.get(f"/api/v2/policies/{p['id']}", headers=h).json()
    assert again["monthly_premium"] == 99 and again["max_coverage"] == 18000


def test_premium_payments_are_simulated_idempotent_per_month(client):
    h = register_login(client)
    a, p = insured(client, h)
    assert client.post(f"/api/v2/policies/{p['id']}/pay-premium", headers=h).status_code == 409  # current month already paid
    tx = client.get("/api/v2/payments", headers=h).json()
    assert len(tx) == 1 and tx[0]["simulated"] is True and tx[0]["amount"] == 99 and tx[0]["method"] == "SIMULATED"
    # an unpaid earlier month becomes due
    from app.database import SessionLocal
    from app.models import Policy, PremiumTransaction
    with SessionLocal() as db:
        pol = db.get(Policy, p["id"])
        pol.start_date = date.today() - timedelta(days=65)
        db.commit()
    due = client.post(f"/api/v2/policies/{p['id']}/pay-premium", headers=h)
    assert due.status_code == 201 and due.json()["status"] == "Paid"
    assert client.post(f"/api/v2/policies/{p['id']}/pay-premium", headers=h).status_code in (201, 409)


def test_card_or_bank_fields_do_not_exist_anywhere(client):
    h = register_login(client)
    a, p = insured(client, h)
    blob = str(client.get("/api/v2/payments", headers=h).json()) + str(p)
    for w in ("card_number", "cvv", "iban", "account_number"):
        assert w not in blob


def test_finance_scenario_matches_the_brief_and_warns_on_deficit(client, admin, student):
    r = client.post("/api/v2/finance/scenario", json={}, headers=admin).json()
    assert r["premium_income"] == 79000 and r["surplus"] == 12000 and r["warnings"] == [] and "NOT validated" in r["disclaimer"]
    bad = client.post("/api/v2/finance/scenario", json={"expected_claims": 70000}, headers=admin).json()
    assert bad["surplus"] < 0 and bad["warnings"] and bad["rows"][-1]["name"] == "Deficit"
    assert client.post("/api/v2/finance/scenario", json={}, headers=student).status_code == 403
    assert client.post("/api/v2/finance/scenario", json={"students": -1}, headers=admin).status_code == 422


def test_finance_summary_uses_database_figures(client, admin, student):
    s = client.get("/api/v2/finance/summary?months=6", headers=admin).json()
    assert s["counts"]["active_policies"] >= 8 and s["totals"]["premium_income"] > 0 and len(s["months"]) == 6 and s["formula"].startswith("Expected surplus")
    assert s["counts"]["annualized_premium_income"] == pytest.approx(s["counts"]["monthly_premium_collection"] * 12)
    assert {"category", "premiums_collected", "claims_paid", "net"} <= set(s["policy_breakdown"][0])
    assert client.get("/api/v2/finance/summary", headers=student).status_code == 403
    a = client.put("/api/v2/finance/assumptions", json={"expected_loss_ratio_pct": 90, "operating_pct": 20, "ai_tech_pct": 10, "reserve_pct": 15}, headers=admin)
    assert a.status_code == 200
    s2 = client.get("/api/v2/finance/summary?months=6", headers=admin).json()
    assert s2["warnings"], "a 135% cost structure must raise deficit warnings"


def test_expense_validation(client, admin):
    assert client.post("/api/v2/finance/expenses", json={"period": "2026-13", "category": "operating", "amount": 5}, headers=admin).status_code == 422
    assert client.post("/api/v2/finance/expenses", json={"period": "2026-05", "category": "x", "amount": 5}, headers=admin).status_code == 422
    assert client.post("/api/v2/finance/expenses", json={"period": "2026-05", "category": "operating", "amount": 5}, headers=admin).status_code == 201


def test_admin_overview_and_roles(client, admin, student):
    o = client.get("/api/v2/admin/overview", headers=admin).json()
    assert o["students"] >= 6 and o["active_policies"] >= 8 and o["premium_revenue"] > 0
    assert client.get("/api/v2/admin/overview", headers=student).status_code == 403
    assert client.get("/api/v2/admin/policies", headers=student).status_code == 403
    assert client.get("/api/v2/ai/analytics", headers=student).status_code == 403
    assert client.get("/api/v2/dashboard", headers=admin).status_code == 403


def test_dev_simulation_is_refused_in_production(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "APP_ENV", "production"); monkeypatch.setattr(config.settings, "IS_PRODUCTION", True)
    monkeypatch.setattr(config.settings, "AI_VERIFY_MODE", "dev_simulation")
    monkeypatch.setattr(config.settings, "SECRET_KEY", "x" * 40); monkeypatch.setattr(config.settings, "COOKIE_SECURE", True); monkeypatch.setattr(config.settings, "SEED_DEMO_DATA", False)
    with pytest.raises(RuntimeError, match="dev_simulation"):
        config.validate_production_settings()
