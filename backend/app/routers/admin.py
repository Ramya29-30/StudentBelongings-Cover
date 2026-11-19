"""Administrator: monitoring overview, runtime settings, public (unauthenticated) UI config."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import services as S
from ..ai import service as ai
from ..config import settings
from ..database import get_db
from ..models import AuthSession, Claim, ClaimReserve, LoginAttempt, Payment, SystemSetting, User, now
from ..security import require_roles

router = APIRouter(prefix="/api")
DEFAULTS = {"maintenance_banner": "", "payments_enabled": "true"}


def get_setting(db: Session, key: str) -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else DEFAULTS[key]


@router.get("/public-config")
def public_config(db: Session = Depends(get_db)):
    return {"banner": get_setting(db, "maintenance_banner"), "demo_mode": bool(settings.SEED_DEMO_DATA and not settings.IS_PRODUCTION)}


@router.get("/legal-config")
def legal_config():
    """Operator-supplied facts shown on the Privacy Policy and Terms pages. Empty values are shown as 'not provided', never invented."""
    return {"operator_name": settings.LEGAL_OPERATOR_NAME, "contact_email": settings.LEGAL_CONTACT_EMAIL, "postal_address": settings.LEGAL_POSTAL_ADDRESS,
            "governing_law": settings.LEGAL_GOVERNING_LAW, "reviewed_by_counsel": settings.LEGAL_REVIEWED_BY_COUNSEL,
            "ai_enabled": ai.status()["configured"], "ai_provider": ai.status()["provider"] if ai.status()["configured"] else "", "payments": "simulated"}


@router.get("/system/settings")
def system_settings(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    with db.get_bind().connect() as c:
        rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    st = ai.status()
    return {"editable": {k: get_setting(db, k) for k in DEFAULTS},
            "environment": {"app_env": settings.APP_ENV, "schema_revision": rev, "session_ttl_minutes": settings.SESSION_TTL_MINUTES,
                            "session_idle_minutes": settings.SESSION_IDLE_MINUTES, "login_max_failures": settings.LOGIN_MAX_FAILURES, "login_window_minutes": settings.LOGIN_WINDOW_MINUTES,
                            "min_password_length": settings.MIN_PASSWORD_LENGTH, "max_upload_mb": settings.MAX_UPLOAD_MB, "cookie_secure": settings.COOKIE_SECURE,
                            "demo_data_enabled": settings.SEED_DEMO_DATA, "payment_mode": "SIMULATED (no gateway integrated)"},
            "ai": {k: st[k] for k in ("provider", "configured", "text_model", "vision_model", "vision_available", "message")}}  # never includes the API key


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    maintenance_banner: str | None = Field(default=None, max_length=300)
    payments_enabled: bool | None = None


@router.put("/system/settings")
def update_settings(body: SettingsIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    ch = body.model_dump(exclude_none=True)
    for k, v in ch.items():
        val = str(v).lower() if isinstance(v, bool) else v
        row = db.get(SystemSetting, k)
        old = row.value if row else DEFAULTS[k]
        if row:
            row.value, row.updated_by = val, user.id
        else:
            db.add(SystemSetting(key=k, value=val, updated_by=user.id))
        S.audit(db, "system", 0, "setting_changed", {"key": k, "old": old, "new": val}, user)
    db.commit()
    return system_settings(user, db)


@router.get("/admin/overview")
def overview(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    claims = db.scalars(select(Claim).where(Claim.flow == "manual")).all()  # self-service claims have their own overview
    by = {}
    for c in claims:
        by[c.status] = by.get(c.status, 0) + 1
    week = now() - timedelta(days=7)
    day = now() - timedelta(days=1)
    reserves = db.scalars(select(ClaimReserve)).all()
    pay = {s: db.scalar(select(func.count()).select_from(Payment).where(Payment.status == s)) for s in ("Requested", "Approved", "Paid", "Rejected", "Failed", "Cancelled")}
    return {"claims_by_status": by, "claims_total": len(claims), "unassigned_open": sum(1 for c in claims if c.assessor_id is None and c.status in ("Submitted", "Under Assessment", "Pending Information")),
            "aging_over_7_days": [S.claim_dict(c) for c in claims if c.submitted_at and c.submitted_at < week and c.status in ("Submitted", "Under Assessment", "Pending Information")][:20],
            "reserves": {"recommended": float(sum(r.recommended_amount for r in reserves)), "approved": float(sum(r.approved_amount for r in reserves)),
                         "paid_simulated": float(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "Paid")))},
            "payments_by_status": pay, "payment_mode": "SIMULATED",
            "security": {"active_sessions": db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > now())),
                         "failed_logins_24h": db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.success.is_(False), LoginAttempt.created_at > day)),
                         "active_users": db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))}}
