"""Demo data for the self-service product (development only, fictional people). Premium history makes the finance charts meaningful;
the one settled claim is inserted directly and labelled as a demo seed with a SIMULATED report."""
import io
import random
from datetime import date, timedelta

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services as S
from . import v3
from .ai import authenticity, vision
from .config import settings
from .engine import insurance as I
from .models import (AIVerificationReport, Asset, AssetCategory, AssetEvidence, Claim, ClaimDecision, ClaimStatusHistory, FinancialExpense, PolicyAsset, PremiumTransaction, RiskReserve,
                     Settlement, Student, User, now)
from .security import hash_password


def _png(label: str, seed: int) -> bytes:
    rnd = random.Random(seed)
    im = Image.new("RGB", (480, 320), (rnd.randint(150, 230), rnd.randint(150, 230), rnd.randint(150, 230)))
    d = ImageDraw.Draw(im)
    d.rectangle((60, 60, 420, 260), outline=(40, 40, 40), width=6)
    d.text((80, 140), f"DEMO IMAGE: {label}", fill=(20, 20, 20))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def _evidence(db: Session, a: Asset, kind: str, stored: str, original: str, data: bytes, status: str, admin: User | None) -> None:
    """Demo evidence row with real fingerprints (the demo images are synthetic and say so on their face)."""
    e = AssetEvidence(asset_id=a.id, kind=kind, stored_name=stored, original_name=original, content_type="image/png", size_bytes=len(data), sha256=vision.sha256(data),
                      uploaded_by=a.owner_id, review_status=status, reviewed_by=admin.id if admin and status == "Accepted" else None, reviewed_at=now() if status == "Accepted" else None)
    _im, bgr = vision.decode(data)
    e.phash, e.phash_dct, e.width, e.height, e.quality = vision.dhash(bgr), authenticity.phash_dct(bgr), bgr.shape[1], bgr.shape[0], vision.assess_quality(bgr)
    db.add(e)


def run(db: Session) -> None:
    if db.scalar(select(User.id).where(User.username == "riya")):
        return
    v3.seed_categories(db); db.flush()
    cats = {c.name: c for c in db.scalars(select(AssetCategory))}
    admin = db.scalar(select(User).where(User.role == "admin"))
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    people = {}
    for uname, name in (("riya", "Riya Menon"), ("karan", "Karan Patel"), ("sana", "Sana Iqbal"), ("dev", "Dev Rao")):
        u = User(username=uname, password_hash=hash_password("student123"), full_name=name, role="student", email=f"{uname}@example.edu")
        db.add(u); db.flush()
        db.add(Student(user_id=u.id, college="Fictional Institute of Technology", roll_number=f"FIT{u.id:04d}"))
        people[uname] = u
    plan = [("riya", "Laptop", "Lenovo", "IdeaPad Slim 3", 42000, "LN-9KX2L1", 5), ("riya", "Earbuds", "boAt", "Airdopes 141", 3000, "", 3),
            ("karan", "Smartphone", "Redmi", "Note 13", 16000, "IMEI-8650-1144", 4), ("karan", "Bicycle", "Hero", "Lectro C6", 12000, "FRAME-LC6-0912", 2),
            ("sana", "Tablet", "Samsung", "Galaxy Tab A9", 14000, "TAB-RZ8M92", 5), ("sana", "Smartwatch", "Noise", "ColorFit Pro", 4000, "SW-NF-2201", 3),
            ("dev", "Laptop", "HP", "15s", 38000, "HP-5CG2201", 4), ("dev", "Smartphone", "Realme", "Narzo 60", 16500, "IMEI-8650-7732", 1)]
    # one demo registration that is still waiting for staff review (front photo and invoice only: the back photograph is missing, so it cannot be approved yet)
    pc = cats["Smartwatch"]
    pa = Asset(owner_id=people["riya"].id, category="Smartwatch", category_id=pc.id, name="Fastrack Reflex Vox", make_model="Fastrack Reflex Vox", brand="Fastrack", model_name="Reflex Vox",
               serial_number="FT-RX-1177", purchase_date=date.today() - timedelta(days=40), declared_value=3500, description="Demo registration waiting for review (fictional)",
               invoice_file="demo-inv-pending.png", invoice_name="invoice.png", photo_file="demo-photo-pending.png", photo_name="photo.png", invoice_verified=False,
               proof_of_purchase_ref="demo", eligibility_status="Eligible", eligibility_reason=I.check_eligibility(I.category_terms(pc), 3500)["reason"], evidence_status="Pending review")
    (settings.UPLOAD_DIR / "demo-inv-pending.png").write_bytes(_png("invoice", 31)); (settings.UPLOAD_DIR / "demo-photo-pending.png").write_bytes(_png("Smartwatch", 131))
    db.add(pa); db.flush()
    _evidence(db, pa, "front_photo", "demo-photo-pending.png", "photo.png", (settings.UPLOAD_DIR / "demo-photo-pending.png").read_bytes(), "Pending", None)
    _evidence(db, pa, "invoice", "demo-inv-pending.png", "invoice.png", (settings.UPLOAD_DIR / "demo-inv-pending.png").read_bytes(), "Pending", None)
    policies = {}
    for i, (uname, cat, brand, model, price, serial, months_ago) in enumerate(plan):
        u, c = people[uname], cats[cat]
        iv, ph = f"demo-inv-{i}.png", f"demo-photo-{i}.png"
        (settings.UPLOAD_DIR / iv).write_bytes(_png("invoice", i)); (settings.UPLOAD_DIR / ph).write_bytes(_png(cat, 100 + i))
        a = Asset(owner_id=u.id, category=cat, category_id=c.id, name=f"{brand} {model}", make_model=f"{brand} {model}", brand=brand, model_name=model, serial_number=serial,
                  purchase_date=date.today() - timedelta(days=300), declared_value=price, description="Demo asset (fictional)", invoice_file=iv, invoice_name="invoice.png",
                  photo_file=ph, photo_name="photo.png", invoice_verified=(i % 2 == 0), proof_of_purchase_ref="demo", eligibility_status="Eligible",
                  eligibility_reason=I.check_eligibility(I.category_terms(c), price)["reason"], evidence_status="Approved", evidence_reviewed_by=admin.id, evidence_reviewed_at=now(),
                  evidence_review_note="Demo seed: approved.")
        db.add(a); db.flush()
        bk = f"demo-back-{i}.png"
        (settings.UPLOAD_DIR / bk).write_bytes(_png(f"{cat} back", 200 + i))
        _evidence(db, a, "front_photo", ph, "photo.png", (settings.UPLOAD_DIR / ph).read_bytes(), "Accepted", admin)
        _evidence(db, a, "back_photo", bk, "back.png", (settings.UPLOAD_DIR / bk).read_bytes(), "Accepted", admin)
        _evidence(db, a, "invoice", iv, "invoice.png", (settings.UPLOAD_DIR / iv).read_bytes(), "Accepted", admin)
        start = v3.add_months(date.today().replace(day=1), -months_ago) + timedelta(days=min(date.today().day, 27) - 1)
        terms = I.category_terms(c)
        p = __import__("app.models", fromlist=["Policy"]).Policy(policy_number=f"SBC-{start.year}-{9000 + i:05d}", student_id=u.id, plan_id=c.plan_id, status="Active", start_date=start,
                                                                 end_date=v3.add_months(start, 12) - timedelta(days=1), activated_on=start, category_id=c.id, purchase_value=price,
                                                                 monthly_premium=c.monthly_premium, annual_premium=float(c.monthly_premium) * 12, max_coverage=c.max_coverage,
                                                                 deductible=c.deductible, terms_snapshot=terms)
        db.add(p); db.flush()
        db.add(PolicyAsset(policy_id=p.id, asset_id=a.id, added_on=start)); db.flush(); db.refresh(p)
        S.create_version(db, p, start, "Policy purchased (demo seed)", admin)
        cur = date(start.year, start.month, 1)
        while cur <= date.today():
            paid_at = now().replace(year=cur.year, month=cur.month, day=min(5, 28))
            db.add(PremiumTransaction(reference=f"PRM-DEMO{i}{cur:%y%m}", policy_id=p.id, student_id=u.id, amount=c.monthly_premium, period_label=f"{cur:%Y-%m}", status="Paid",
                                      method="SIMULATED", paid_at=paid_at))
            cur = v3.add_months(cur, 1)
        policies[(uname, cat)] = (p, a)
    # one settled demo claim (inserted directly, clearly labelled)
    p, a = policies[("riya", "Earbuds")]
    c = Claim(claim_number="TMP-DEMO", policy_id=p.id, claimant_id=a.owner_id, asset_id=a.id, incident_date=date.today() - timedelta(days=40), incident_type="Accidental Damage",
              incident_location="", description="Earbud case dropped on stairs and the casing cracked. (demo seed record)", status="Settled", flow="auto", damage_type="Broken casing",
              estimated_repair_cost=600, assessed_loss=600, payable_amount=600, ai_outcome="Evidence Supported", decision_outcome="Approved", decision_reason="Demo seed record",
              submitted_at=now() - timedelta(days=39))
    db.add(c); db.flush(); v3.new_claim_number(db, c)
    calc = I.calculate_claim(p.terms_snapshot, a.purchase_date, c.incident_date, 600)
    db.add(AIVerificationReport(claim_id=c.id, run=1, mode="development_simulation", is_simulated=True, quality={"total_count": 1, "usable_count": 1, "average_score": 0, "images": [], "result": "n/a"},
                                asset_identification={"status": "Simulated", "match": "Consistent (assumed)"}, damage_detection={"status": "Simulated", "detections": []},
                                description_check={"result": "Consistent", "notes": ["Demo seed record"]}, duplicate_check={"result": "n/a"}, evidence_completeness={}, risk_indicators=[],
                                outcome="Evidence Supported", route="auto", explanation="DEMO SEED RECORD: not produced by a model.", next_step="Settled.", processing_ms=0))
    db.add(ClaimDecision(claim_id=c.id, run=1, outcome="Approved", decided_by="system", checks=[], calculation=calc, payable_amount=600, reason="Demo seed record"))
    db.add(Settlement(claim_id=c.id, reference="SET-DEMO0001", amount=600, status="Settled", method="SIMULATED", settled_at=now() - timedelta(days=35)))
    db.add(ClaimStatusHistory(claim_id=c.id, from_status="", to_status="Settled", reason="Demo seed record", changed_by=None))
    for m in v3_months(4):
        db.add(FinancialExpense(period=m, category="operating", amount=300, description="Demo: support and administration", created_by=admin.id))
        db.add(FinancialExpense(period=m, category="ai_technology", amount=150, description="Demo: hosting and model compute", created_by=admin.id))
        db.add(RiskReserve(period=m, amount=250, description="Demo: reserve top-up", created_by=admin.id))
    db.flush()


def v3_months(n: int) -> list[str]:
    t = date.today().replace(day=1)
    return [f"{v3.add_months(t, -i):%Y-%m}" for i in range(n)]
