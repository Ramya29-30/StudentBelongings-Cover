import io
import random
from datetime import date, timedelta

import cv2
import numpy as np
from PIL import Image


def make_img(seed: int = 1, blur: bool = False, dark: bool = False, size=(640, 480), fmt="PNG") -> bytes:
    """Synthetic but sharp (noise + shapes) photo; blur/dark variants for the quality checks."""
    rnd = np.random.default_rng(seed)
    a = rnd.integers(60, 200, (size[1], size[0], 3), dtype=np.uint8)
    cv2.rectangle(a, (100, 80), (500, 380), (int(seed * 7 % 255), 30, 200), -1)
    cv2.line(a, (120, 100), (480, 360), (255, 255, 255), 3)
    if blur:
        a = cv2.GaussianBlur(a, (0, 0), 25)
    if dark:
        a = (a * 0.08).astype(np.uint8)
    buf = io.BytesIO(); Image.fromarray(a).save(buf, fmt)
    return buf.getvalue()


def register_login(client, username="tester", password="Str0ng!pass-123"):
    r = client.post("/api/auth/register", json={"username": username, "full_name": "Test Student", "email": f"{username}@example.edu", "password": password})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-Return-Token": "1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def cat_id(client, name):
    return next(c["id"] for c in client.get("/api/v2/categories").json() if c["name"] == name)


def add_asset(client, h, category="Laptop", price=42000, serial="SN-TEST-1", back=True, invoice=True, seeds=(939, 947, 983), **kw):
    """Register an asset with front photo (and, by default, back photo and invoice). Pass back=False / invoice=False to leave them out."""
    files = {"front_photo": ("front.png", make_img(seeds[1]), "image/png")}
    if invoice:
        files["invoice"] = ("invoice.png", make_img(seeds[0]), "image/png")
    if back:
        files["back_photo"] = ("back.png", make_img(seeds[2]), "image/png")
    data = {"category_id": cat_id(client, category), "brand": "Acme", "model": "X1", "purchase_price": price, "purchase_date": str(date.today() - timedelta(days=100)), "serial_number": serial,
            "description": "test asset"} | kw
    return client.post("/api/v2/assets", data=data, files=files, headers=h)


def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}, headers={"X-Return-Token": "1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def approve_evidence(client, asset_id, note="Evidence checked in tests.", **kw):
    return client.post(f"/api/v2/admin/assets/{asset_id}/evidence-review", json={"decision": "approve", "note": note, **kw}, headers=admin_headers(client))


def insured(client, h, category="Laptop", price=42000, serial="SN-TEST-1"):
    a = add_asset(client, h, category, price, serial)
    assert a.status_code == 201, a.text
    ap = approve_evidence(client, a.json()["id"])
    assert ap.status_code == 200, ap.text
    p = client.post(f"/api/v2/assets/{a.json()['id']}/purchase", json={"accept_terms": True}, headers=h)
    assert p.status_code == 201, p.text
    return a.json(), p.json()


def file_claim(client, h, asset_id, damage="Broken screen", incident=None, itype="Accidental Damage", estimate=None, desc="My laptop fell off the desk and the screen cracked badly.", images=(1,)):
    body = {"asset_id": asset_id, "incident_date": str(incident or date.today()), "incident_type": itype, "damage_type": damage, "description": desc}
    if estimate:
        body["estimated_repair_cost"] = estimate
    r = client.post("/api/v2/claims", json=body, headers=h)
    if r.status_code != 201:
        return r
    cid = r.json()["id"]
    for s in images:
        u = client.post(f"/api/v2/claims/{cid}/images", files={"file": (f"p{s}.png", make_img(s), "image/png")}, headers=h)
        assert u.status_code == 201, u.text
    return r


def backdate(policy_id: int, days: int = 45):
    """Move a policy start into the past (and mark every month since as paid) so claims with earlier incident dates are in cover."""
    from app import v3
    from app.database import SessionLocal
    from app.models import Policy, PremiumTransaction
    with SessionLocal() as db:
        p = db.get(Policy, policy_id)
        p.start_date = date.today() - timedelta(days=days)
        have = {t.period_label for t in db.query(PremiumTransaction).filter_by(policy_id=p.id)}
        cur = date(p.start_date.year, p.start_date.month, 1)
        while cur <= date.today():
            if f"{cur:%Y-%m}" not in have:
                db.add(PremiumTransaction(reference=f"PRM-BD{policy_id}{cur:%y%m}", policy_id=p.id, student_id=p.student_id, amount=p.monthly_premium, period_label=f"{cur:%Y-%m}", status="Paid"))
            cur = v3.add_months(cur, 1)
        db.commit()


# ---- device-like images for the matching tests (synthetic: lines, blobs and a printed label; two views of one object share structure)
def textured(seed: int = 1, text: str | None = "ACME X1", size=(640, 480)) -> np.ndarray:
    r = np.random.default_rng(seed)
    a = cv2.GaussianBlur(r.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), (0, 0), 2)
    for _ in range(40):
        p1, p2 = (int(r.integers(0, size[0])), int(r.integers(0, size[1]))), (int(r.integers(0, size[0])), int(r.integers(0, size[1])))
        cv2.line(a, p1, p2, tuple(int(x) for x in r.integers(0, 255, 3)), int(r.integers(1, 4)))
        cv2.circle(a, p1, int(r.integers(5, 30)), tuple(int(x) for x in r.integers(0, 255, 3)), int(r.integers(1, 3)))
    if text:
        cv2.putText(a, text, (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
    return a


def warped(img: np.ndarray, angle: float = 12, scale: float = 0.85) -> np.ndarray:
    """Same object, different view: rotated, scaled, dimmer."""
    h, w = img.shape[:2]
    out = cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale), (w, h), borderValue=(90, 90, 90))
    return cv2.convertScaleAbs(out, alpha=0.9, beta=15)


def png(img: np.ndarray, fmt: str = "PNG", **save_kw) -> bytes:
    buf = io.BytesIO(); Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).save(buf, fmt, **save_kw)
    return buf.getvalue()


def add_asset_with(client, h, front: bytes, back: bytes | None = None, invoice: bytes | None = None, category="Laptop", price=42000, serial="SN-TEST-1", **kw):
    files = {"front_photo": ("front.png", front, "image/png")}
    if back:
        files["back_photo"] = ("back.png", back, "image/png")
    if invoice:
        files["invoice"] = ("invoice.png", invoice, "image/png")
    data = {"category_id": cat_id(client, category), "brand": "Acme", "model": "X1", "purchase_price": price, "purchase_date": str(date.today() - timedelta(days=100)),
            "serial_number": serial, "description": "test asset"} | kw
    return client.post("/api/v2/assets", data=data, files=files, headers=h)
