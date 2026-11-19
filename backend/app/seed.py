"""Fictional demo data. Dates are relative to 'today' so the demo is always in a sensible state."""
import base64
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services as S
from .config import settings
from .models import (Asset, Claim, ClaimItem, ClaimStatusHistory, CoveragePlan, Evidence, Exclusion, Policy, PolicyAsset, RepairCatalogueEntry,
                     SchemaVersion, Student, User)
from .security import hash_password

PNG_1x1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def d(n: int) -> date:
    return date.today() - timedelta(days=n)


WORDING = """CAMPUS COVER - SAMPLE POLICY WORDING ({name})  [fictional, for an academic prototype only]
s1 Period of Cover: cover applies to incidents occurring between the policy start date (or activation, if later) and the expiry date, unless cancelled earlier.
s2 Covered Perils: {perils}.
s3 Exclusions: wear and tear; purely cosmetic minor scratches; intentional damage.
s4 Waiting Period: {wait} day(s) from the start of cover.
s5 Required Documents: Theft - police report and proof of purchase; Accidental/Liquid Damage - damage photographs; Fire - photographs and incident report.
s6 Limits: overall limit {limit:,.0f}; per-item limits by category; payments never exceed the declared value of an item when capping is on.
s7 Deductible: {ded}. Depreciation: {dep}."""


def make_plans(db: Session):
    docs = {"Theft": ["police_report", "proof_of_purchase"], "Accidental Damage": ["damage_photo"], "Liquid Damage": ["damage_photo"],
            "Fire": ["damage_photo", "incident_report"]}
    excl = [Exclusion(code="EXC-01", title="Wear and tear", clause="Policy Wording s3(a) Wear and tear", damage_types=["Wear and tear"]),
            Exclusion(code="EXC-02", title="Cosmetic minor scratches", clause="Policy Wording s3(b) Cosmetic damage", damage_types=["Scratch"], severities=["Minor"]),
            Exclusion(code="EXC-03", title="Intentional damage", clause="Policy Wording s3(c) Intentional acts", incident_types=["Intentional Damage"])]
    def ex():
        return [Exclusion(code=e.code, title=e.title, clause=e.clause, incident_types=e.incident_types, damage_types=e.damage_types, severities=e.severities) for e in excl]
    basic = CoveragePlan(name="Campus Basic", description="Entry-level cover: theft, accidental damage and fire. Fixed deductible, no depreciation.",
                         covered_perils=["Theft", "Accidental Damage", "Fire"], overall_limit=60000, default_per_item_limit=20000,
                         per_item_limits={"Laptop": 45000, "Smartphone": 35000}, deductible_type="fixed", deductible_value=1500,
                         depreciation={"enabled": False}, waiting_period_days=0, required_documents=docs, exclusions=ex())
    plus = CoveragePlan(name="Campus Plus", description="Adds liquid damage; higher limits; depreciation applies when an item is replaced; 7-day waiting period.",
                        covered_perils=["Theft", "Accidental Damage", "Liquid Damage", "Fire"], overall_limit=120000, default_per_item_limit=30000,
                        per_item_limits={"Laptop": 80000, "Smartphone": 60000}, deductible_type="fixed", deductible_value=1000,
                        depreciation={"enabled": True, "rate_per_year_pct": 10, "max_pct": 50, "applies_to": "replace"}, waiting_period_days=7,
                        duplicate_window_days=3, required_documents=docs, exclusions=ex())
    flex = CoveragePlan(name="Campus Flex", description="Percentage deductible taken BEFORE the overall limit (shows a different calculation order).",
                        covered_perils=["Theft", "Accidental Damage", "Liquid Damage", "Fire"], overall_limit=50000, default_per_item_limit=40000,
                        deductible_type="percent", deductible_value=10, calc_order="DEDUCTIBLE_THEN_LIMIT", depreciation={"enabled": False},
                        required_documents=docs, exclusions=ex())
    for p, dep in ((basic, "none"), (plus, "10%/year on replacement, max 50%"), (flex, "none")):
        p.wording = WORDING.format(name=p.name, perils=", ".join(p.covered_perils), wait=p.waiting_period_days, limit=float(p.overall_limit),
                                   ded=(f"{p.deductible_value}% ({p.calc_order})" if p.deductible_type == "percent" else f"fixed {p.deductible_value:,.0f}"), dep=dep)
    db.add_all([basic, plus, flex]); db.flush()
    return basic, plus, flex


CATALOGUE = [
    ("Laptop", "Screen", "Cracked screen", "Repair", 4000, 500), ("Laptop", "Keyboard", "Broken component", "Repair", 1800, 400),
    ("Laptop", "Hinge", "Broken component", "Repair", 1500, 600), ("Laptop", "Motherboard", "Liquid damage", "Repair", 9000, 1500),
    ("Laptop", "Battery", "", "Repair", 2500, 300), ("Laptop", "Whole device", "", "Replace", 50000, 0),
    ("Smartphone", "Screen", "Cracked screen", "Repair", 3500, 500), ("Smartphone", "Battery", "", "Repair", 1800, 300),
    ("Smartphone", "Back panel", "", "Repair", 1200, 300), ("Smartphone", "Motherboard", "Liquid damage", "Repair", 7000, 1000),
    ("Smartphone", "Whole device", "", "Replace", 42000, 0),
    ("Tablet", "Screen", "Cracked screen", "Repair", 4500, 600), ("Tablet", "Whole device", "", "Replace", 28000, 0),
    ("Headphones and accessories", "Headband", "Broken component", "Repair", 1500, 200), ("Headphones and accessories", "Ear cushion", "", "Repair", 800, 0),
    ("Headphones and accessories", "Whole device", "", "Replace", 15000, 0),
    ("Bicycle", "Wheel", "Dent", "Repair", 1800, 300), ("Bicycle", "Drivetrain", "Broken component", "Repair", 1200, 400), ("Bicycle", "Whole device", "", "Replace", 8500, 0),
    ("Academic equipment", "Scientific calculator", "", "Replace", 1400, 0), ("Academic equipment", "Drafting kit", "", "Replace", 900, 0),
    ("Academic equipment", "Whole device", "", "Replace", 2300, 0),
]


def run(db: Session):
    if db.scalar(select(User.id).limit(1)):
        return
    db.add(SchemaVersion(version=1))
    users = {}
    for uname, pw, name, role in (("aarav", "student123", "Aarav Sharma", "student"), ("meera", "student123", "Meera Nair", "student"),
                                  ("admin", "admin123", "Priya Policy-Admin", "admin"), ("assessor", "assessor123", "Rahul Assessor", "assessor")):
        u = User(username=uname, password_hash=hash_password(pw), full_name=name, role=role, email=f"{uname}@example.edu")
        db.add(u); db.flush(); users[uname] = u
        if role == "student":
            db.add(Student(user_id=u.id, college="Fictional Institute of Technology", roll_number=f"FIT{u.id:04d}"))
    basic, plus, flex = make_plans(db)
    for row in CATALOGUE:
        db.add(RepairCatalogueEntry(category=row[0], component=row[1], damage_type=row[2], action=row[3], parts_cost=row[4], labour_cost=row[5],
                                    notes="Sample catalogue price (fictional)"))
    a, m, adm, asr = users["aarav"], users["meera"], users["admin"], users["assessor"]
    def asset(owner, cat, name, model, serial, age, value, proof):
        x = Asset(owner_id=owner.id, category=cat, name=name, make_model=model, serial_number=serial, purchase_date=d(age), declared_value=value, proof_of_purchase_ref=proof)
        db.add(x); db.flush(); return x
    laptop = asset(a, "Laptop", "Dell Inspiron 15", "Dell Inspiron 15 3520", "DL-8H2K91", 500, 55000, "INV-DEL-118")
    phone = asset(a, "Smartphone", "Samsung Galaxy S23", "SM-S911B", "IMEI-3566-0021", 300, 48000, "INV-SAM-552")
    phones = asset(a, "Headphones and accessories", "Sony WH-1000XM4", "WH-1000XM4", "SN-77281", 700, 18000, "")
    bike = asset(a, "Bicycle", "Hero Sprint 21", "Sprint 21T", "FRAME-HS-4471", 400, 9500, "INV-HERO-31")
    tablet = asset(a, "Tablet", "iPad 9th Gen", "A2602", "DMPXK1", 250, 30000, "INV-APL-009")
    mlap = asset(m, "Laptop", "HP Pavilion 14", "14-ec1002", "HP-5CD2201", 200, 62000, "INV-HP-777")
    meq = asset(m, "Academic equipment", "Casio fx-991EX + drafting kit", "fx-991EX", "KIT-0042", 150, 6500, "INV-CAS-12")

    def policy(student, plan, start, end, status, assets, activated=True, cancelled_on=None, reason=""):
        n = db.query(Policy).count() + 1
        p = Policy(policy_number=f"SBC-{date.today().year}-{n:05d}", student_id=student.id, plan_id=plan.id, start_date=start, end_date=end, status=status,
                   activated_on=start if activated else None, cancelled_on=cancelled_on, cancellation_reason=reason)
        db.add(p); db.flush()
        for x in assets:
            db.add(PolicyAsset(policy_id=p.id, asset_id=x.id, added_on=start))
        db.flush(); db.refresh(p)
        S.create_version(db, p, start, "Initial policy version", adm)
        return p
    p1 = policy(a, plus, d(200), d(200) + timedelta(days=364), "Active", [laptop, phone, phones])
    db.add(PolicyAsset(policy_id=p1.id, asset_id=bike.id, added_on=d(60))); db.flush(); db.refresh(p1)
    S.create_version(db, p1, d(60), "Asset added: Hero Sprint 21 (mid-term change)", adm)
    policy(a, basic, d(500), d(135), "Expired", [tablet])
    policy(a, flex, d(250), d(250) + timedelta(days=364), "Cancelled", [phones], cancelled_on=d(100), reason="Cancelled at policyholder request")
    p4 = policy(m, basic, d(100), d(100) + timedelta(days=364), "Active", [mlap, meq])
    policy(m, flex, date.today(), date.today() + timedelta(days=364), "Draft", [meq], activated=False)

    def claim(student, pol, ast, inc_days, itype, loc, desc):
        c = Claim(claim_number=f"CLM-{date.today().year}-{db.query(Claim).count() + 1:05d}", policy_id=pol.id, claimant_id=student.id, asset_id=ast.id,
                  incident_date=d(inc_days), incident_type=itype, incident_location=loc, description=desc)
        db.add(c); db.flush()
        db.add(ClaimStatusHistory(claim_id=c.id, from_status="", to_status="Draft", reason="Claim created", changed_by=student.id))
        S.audit(db, "claim", c.id, "claim_created", {"seed": True}, student, claim_id=c.id)
        db.refresh(c)
        return c

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    c1 = claim(a, p1, laptop, 20, "Accidental Damage", "Hostel room, Block C", "Laptop slipped off the study desk; the screen is cracked across the lower half. It still boots.")
    (settings.UPLOAD_DIR / "seed-photo.png").write_bytes(PNG_1x1)
    ev = Evidence(claim_id=c1.id, doc_type="damage_photo", original_name="cracked-screen.png", stored_name="seed-photo.png", content_type="image/png",
                  size_bytes=len(PNG_1x1), uploaded_by=a.id)
    db.add(ev); db.flush(); db.refresh(c1)
    S.change_claim_status(db, c1, "Submitted", a, "Submitted by student")
    S.change_claim_status(db, c1, "Under Assessment", asr, "Assessment started")
    cat = db.scalar(select(RepairCatalogueEntry).where(RepairCatalogueEntry.category == "Laptop", RepairCatalogueEntry.component == "Screen"))
    db.add(ClaimItem(claim_id=c1.id, component="Screen", damage_type="Cracked screen", severity="Moderate", repair_action="Repair", parts_cost=cat.parts_cost,
                     labour_cost=cat.labour_cost, price_source="catalogue", catalogue_entry_id=cat.id, evidence_refs=[ev.id], confidence="Medium",
                     verification_status="Human Verified", verified_by=asr.id, notes="Visible crack in photo; internal damage not ruled out."))
    db.flush(); db.refresh(c1)
    S.evaluate_and_store(db, c1, asr)

    c2 = claim(a, p1, bike, 100, "Theft", "Campus bicycle stand", "Bicycle stolen from the stand outside the library.")
    S.change_claim_status(db, c2, "Submitted", a, "Submitted by student")
    c3 = claim(m, p4, mlap, 30, "Liquid Damage", "Library", "Water bottle leaked inside my bag; the laptop will not power on.")
    S.change_claim_status(db, c3, "Submitted", m, "Submitted by student")
    claim(a, p1, phone, 5, "Accidental Damage", "Cafeteria", "Dropped phone on the floor; back panel cracked.")  # left in Draft
    from . import seed_v3
    seed_v3.run(db)  # self-service product demo data (v3)
    db.commit()
