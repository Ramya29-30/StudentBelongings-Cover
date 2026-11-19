import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services as S
from ..config import settings
from ..database import get_db
from ..models import Student, User, now
from ..security import (burn_time, check_login_allowed, check_password_policy, client_ip, create_session, current_session, hash_password,
                        record_login_attempt, require_roles, revoke_user_sessions, verify_password)

router = APIRouter(prefix="/api")
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")
ROLES = ("student", "admin", "assessor")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    username, ip = body.username.strip().lower(), client_ip(request)
    check_login_allowed(db, username, ip)
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        burn_time()
        record_login_attempt(db, username, ip, False)
        raise HTTPException(401, "Invalid username or password")
    ok, rehash = verify_password(body.password, user.password_hash)
    if not ok:
        record_login_attempt(db, username, ip, False)
        raise HTTPException(401, "Invalid username or password")
    if rehash:
        user.password_hash = hash_password(body.password)  # upgrades legacy PBKDF2 hashes to Argon2id
    user.last_login_at = now()
    token, sess = create_session(db, user, ip, request.headers.get("user-agent", ""))
    S.audit(db, "user", user.id, "login", {"ip": ip}, user)
    db.commit()
    record_login_attempt(db, username, ip, True)
    response.set_cookie(settings.COOKIE_NAME, token, httponly=True, secure=settings.COOKIE_SECURE, samesite="strict",
                        max_age=settings.SESSION_TTL_MINUTES * 60, path="/")
    out = {"user": S.user_dict(user), "csrf_token": sess.csrf_token, "expires_at": sess.expires_at.isoformat()}
    if request.headers.get("x-return-token") == "1":  # non-browser API clients only
        out["token"] = token
    return out


@router.post("/auth/logout")
def logout(response: Response, ctx=Depends(current_session), db: Session = Depends(get_db)):
    user, sess = ctx
    sess.revoked_at = now()
    S.audit(db, "user", user.id, "logout", {}, user)
    db.commit()
    response.delete_cookie(settings.COOKIE_NAME, path="/", secure=settings.COOKIE_SECURE, httponly=True, samesite="strict")
    return {"ok": True}


@router.get("/auth/me")
def me(ctx=Depends(current_session)):
    user, sess = ctx
    return S.user_dict(user) | {"csrf_token": sess.csrf_token, "expires_at": sess.expires_at.isoformat()}


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


@router.post("/auth/change-password")
def change_password(body: PasswordChange, ctx=Depends(current_session), db: Session = Depends(get_db)):
    user, sess = ctx
    if not verify_password(body.current_password, user.password_hash)[0]:
        raise HTTPException(400, "Current password is incorrect")
    check_password_policy(body.new_password, user.username)
    user.password_hash, user.password_changed_at = hash_password(body.new_password), now()
    revoke_user_sessions(db, user.id, except_id=sess.id)
    S.audit(db, "user", user.id, "password_changed", {}, user)
    db.commit()
    return {"ok": True}


@router.get("/auth/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)):
    """Development convenience only. Returns 404 when demo data is disabled (always in production)."""
    if settings.IS_PRODUCTION or not settings.SEED_DEMO_DATA:
        raise HTTPException(404, "Not found")
    return [{"username": "riya", "password": "student123", "role": "student", "label": "Student - Riya Menon (insured laptop and earbuds)"},
            {"username": "aarav", "password": "student123", "role": "student", "label": "Student - Aarav Sharma"},
            {"username": "meera", "password": "student123", "role": "student", "label": "Student - Meera Nair"},
            {"username": "admin", "password": "admin123", "role": "admin", "label": "Policy Administrator"},
            {"username": "assessor", "password": "assessor123", "role": "assessor", "label": "Claims Assessor"}]


# ------------------------------------------------------------------ administrator: user management
class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    full_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=120)
    role: str
    password: str = Field(max_length=128)

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("username must be 3-50 characters: a-z, 0-9, dot, dash, underscore")
        return v

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return v

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid email address")
        return v


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=120)
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v is not None and v not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return v


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(max_length=128)


def _u(u: User) -> dict:
    return S.user_dict(u) | {"is_active": u.is_active, "last_login_at": S.iso(u.last_login_at), "created_at": S.iso(u.created_at)}


@router.get("/users")
def list_users(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return [_u(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    check_password_policy(body.password, body.username)
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username, full_name=body.full_name, email=body.email, role=body.role, password_hash=hash_password(body.password), password_changed_at=now())
    db.add(u); db.flush()
    if u.role == "student":
        db.add(Student(user_id=u.id, college="", roll_number=""))
    S.audit(db, "user", u.id, "user_created", {"username": u.username, "role": u.role}, admin)
    db.commit()
    return _u(u)


@router.put("/users/{uid}")
def update_user(uid: int, body: UserUpdate, admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    ch = body.model_dump(exclude_none=True)
    if u.id == admin.id and (ch.get("role", u.role) != "admin" or ch.get("is_active") is False):
        raise HTTPException(400, "Administrators cannot demote or disable their own account")
    if ch.get("role") and ch["role"] != u.role and u.role == "student":
        from ..models import Claim, Policy
        if db.scalar(select(Policy.id).where(Policy.student_id == u.id)) or db.scalar(select(Claim.id).where(Claim.claimant_id == u.id)):
            raise HTTPException(409, "A student with policies or claims cannot change role")
    before = {k: getattr(u, k) for k in ch}
    for k, v in ch.items():
        setattr(u, k, v)
    if ch.get("is_active") is False or ("role" in ch and ch["role"] != before.get("role")):
        revoke_user_sessions(db, u.id)  # role/disable takes effect immediately
    if u.role == "student" and not u.student:
        db.add(Student(user_id=u.id, college="", roll_number=""))
    S.audit(db, "user", u.id, "user_updated", {"before": before, "after": ch}, admin)
    db.commit()
    return _u(u)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, body: PasswordReset, admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    check_password_policy(body.new_password, u.username)
    u.password_hash, u.password_changed_at = hash_password(body.new_password), now()
    revoke_user_sessions(db, u.id)
    S.audit(db, "user", u.id, "password_reset_by_admin", {}, admin)
    db.commit()
    return {"ok": True}
