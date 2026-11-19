"""Default product catalogue (the initial, administrator-editable academic pricing). Reference repair costs are fictional sample values."""

DEFAULT_CATEGORIES = [
    dict(name="Earbuds", description="Wireless earbuds and earphones.", min_purchase_value=2500, monthly_premium=50, max_coverage=2000,
         damage_types=["Broken casing", "Physical damage", "Missing components", "Cosmetic damage only"],
         reference_repair_costs={"Broken casing": 600, "Physical damage": 800, "Missing components": 500}, requires_serial=False,
         eligibility_conditions="Purchased new for at least Rs 2,500. Invoice and photograph required."),
    dict(name="Smartphone", description="Smartphones.", min_purchase_value=15000, monthly_premium=99, max_coverage=10000,
         damage_types=["Cracked screen", "Broken display", "Damaged body", "Camera lens damage", "Cosmetic damage only"],
         reference_repair_costs={"Cracked screen": 3500, "Broken display": 4500, "Damaged body": 2500, "Camera lens damage": 1800},
         eligibility_conditions="Purchased new for at least Rs 8,000. IMEI, invoice and photograph required."),
    dict(name="Tablet", description="Tablets.", min_purchase_value=13000, monthly_premium=79, max_coverage=8000,
         damage_types=["Cracked screen", "Broken body", "Visible physical damage", "Cosmetic damage only"],
         reference_repair_costs={"Cracked screen": 3500, "Broken body": 3000, "Visible physical damage": 3000},
         eligibility_conditions="Purchased new for at least Rs 8,000. Serial number, invoice and photograph required."),
    dict(name="Laptop", description="Laptops and notebooks.", min_purchase_value=25000, monthly_premium=99, max_coverage=18000,
         damage_types=["Broken screen", "Cracked body", "Damaged keyboard", "Broken hinge", "Visible external damage", "Cosmetic damage only"],
         reference_repair_costs={"Broken screen": 6000, "Cracked body": 4000, "Damaged keyboard": 3000, "Broken hinge": 4500, "Visible external damage": 3500},
         eligibility_conditions="Purchased new for at least Rs 20,000. Serial number, invoice and photograph required."),
    dict(name="Bicycle", description="Bicycles.", min_purchase_value=10000, monthly_premium=69, max_coverage=7000,
         damage_types=["Bent components", "Damaged wheels", "Broken frame", "Visible physical damage", "Cosmetic damage only"],
         reference_repair_costs={"Bent components": 1200, "Damaged wheels": 1500, "Broken frame": 4000, "Visible physical damage": 1000},
         eligibility_conditions="Purchased new for at least Rs 5,000. Frame number, invoice and photograph required."),
    dict(name="Smartwatch", description="Smartwatches and fitness bands.", min_purchase_value=3000, monthly_premium=59, max_coverage=2500,
         damage_types=["Cracked display", "Broken casing", "Strap damage", "Cosmetic damage only"],
         reference_repair_costs={"Cracked display": 1500, "Broken casing": 1200, "Strap damage": 400},
         eligibility_conditions="Purchased new for at least Rs 3,000. Serial number, invoice and photograph required."),
]
COMMON = dict(deductible=0, policy_months=12, waiting_period_days=0, depreciation_pct_per_year=0, depreciation_max_pct=0,
              covered_incident_types=["Accidental Damage", "Liquid Damage"], excluded_damage_types=["Cosmetic damage only", "Wear and tear"],
              exclusions=["Theft and loss are not covered", "Intentional damage", "Wear and tear and gradual deterioration",
                          "Cosmetic damage that does not affect function", "Damage that happened before the policy start date"])
FINANCE_DEFAULTS = {"fin.expected_loss_ratio_pct": "50", "fin.operating_pct": "15", "fin.ai_tech_pct": "6", "fin.reserve_pct": "13"}
