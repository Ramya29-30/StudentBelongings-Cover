"""Authentication & authorization.

* Passwords: Argon2id (argon2-cffi). Legacy v1 PBKDF2 hashes are still verified and transparently upgraded on next login.
* Sessions: random opaque token (secrets.token_urlsafe); only HMAC-SHA256(SECRET_KEY, token) is stored server-side, so a
  database leak does not expose usable tokens. Absolute and idle expiry, revocation on logout / password change / disable.
* Browsers get an HttpOnly, SameSite=Strict cookie (Secure in production) plus a CSRF token required on unsafe methods.
  Non-browser API clients may send `Authorization: Bearer <token>` (issued only when the login request sets `X-Return-Token: 1`).
* Authorization: `require_roles(...)` on every protected endpoint; roles come only from the database, never from the request.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, LoginAttempt, User, now

_ph = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)
_DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalisation")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    return _ph.hash(password)


def _legacy_verify(password: str, stored: str) -> bool:
    try:
        salt_b64, _ = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), 100_000)
        return hmac.compare_digest(base64.b64encode(base64.b64decode(salt_b64)).decode() + "$" + base64.b64encode(dk).decode(), stored)
    except Exception:
        return False


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Returns (ok, needs_rehash)."""
    if stored.startswith("$argon2"):
        try:
            _ph.verify(stored, password)
            return True, _ph.check_needs_rehash(stored)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False
    return _legacy_verify(password, stored), True


def burn_time() -> None:
    try:
        _ph.verify(_DUMMY_HASH, "x")
    except Exception:
        pass


def check_password_policy(password: str, username: str = "") -> None:
    if len(password) < settings.MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"Password must be at least {settings.MIN_PASSWORD_LENGTH} characters")
    if len(password) > 128:
        raise HTTPException(422, "Password is too long (max 128 characters)")
    if username and username.lower() in password.lower():
        raise HTTPException(422, "Password must not contain the username")
    if password.lower() in {"password", "password123", "12345678", "123456789012", "qwertyuiop12"}:
        raise HTTPException(422, "Password is too common")


# ------------------------------------------------------------------ sessions
def _token_hash(token: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(db: Session, user: User, ip: str, ua: str) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    sess = AuthSession(user_id=user.id, token_hash=_token_hash(token), csrf_token=secrets.token_urlsafe(24), ip=ip[:64], user_agent=(ua or "")[:200],
                       expires_at=now() + timedelta(minutes=settings.SESSION_TTL_MINUTES))
    db.add(sess)
    db.flush()
    return token, sess


def revoke_user_sessions(db: Session, user_id: int, except_id: int | None = None) -> None:
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))):
        if s.id != except_id:
            s.revoked_at = now()


def client_ip(request: Request) -> str:
    """Peer address. Behind a trusted proxy the address appended by THAT proxy is used (counted from the right):
    the left-most X-Forwarded-For entry is supplied by the client and would let an attacker dodge per-IP limits."""
    xff = request.headers.get("x-forwarded-for", "")
    if settings.TRUST_PROXY and xff:
        parts = [x.strip() for x in xff.split(",") if x.strip()]
        if len(parts) >= settings.TRUSTED_PROXY_HOPS:
            return parts[-settings.TRUSTED_PROXY_HOPS][:64]
    return request.client.host if request.client else ""


def _resolve(request: Request, db: Session) -> tuple[User, AuthSession, bool]:
    auth, via_cookie, raw = request.headers.get("authorization", ""), False, None
    if auth.lower().startswith("bearer "):
        raw = auth.split(" ", 1)[1].strip()
    else:
        raw, via_cookie = request.cookies.get(settings.COOKIE_NAME), True
    if not raw:
        raise HTTPException(401, "Not authenticated")
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(raw)))
    t = now()
    if not sess or sess.revoked_at or sess.expires_at <= t or sess.last_seen_at + timedelta(minutes=settings.SESSION_IDLE_MINUTES) <= t:
        raise HTTPException(401, "Session expired or invalid - please sign in again")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Account disabled")
    if (t - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = t
        db.commit()
    return user, sess, via_cookie


def current_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, AuthSession]:
    user, sess, via_cookie = _resolve(request, db)
    if via_cookie and request.method in UNSAFE:  # CSRF protection for cookie-authenticated requests
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, sess.csrf_token):
            raise HTTPException(403, "Missing or invalid CSRF token")
    return user, sess


def current_user(ctx=Depends(current_session)) -> User:
    return ctx[0]


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Role '{user.role}' is not permitted to perform this action")
        return user
    return dep


# ------------------------------------------------------------------ rate limiting (DB-backed so it survives restarts / multiple workers)
def check_login_allowed(db: Session, username: str, ip: str) -> None:
    since = now() - timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)
    last_ok = db.scalar(select(func.max(LoginAttempt.created_at)).where(LoginAttempt.username == username, LoginAttempt.success.is_(True)))
    q = select(func.count()).select_from(LoginAttempt).where(LoginAttempt.success.is_(False), LoginAttempt.created_at > since)
    by_user = db.scalar(q.where(LoginAttempt.username == username, LoginAttempt.created_at > (last_ok or since)))
    by_ip = db.scalar(q.where(LoginAttempt.ip == ip))
    if by_user >= settings.LOGIN_MAX_FAILURES or by_ip >= settings.LOGIN_IP_MAX_FAILURES:
        raise HTTPException(429, f"Too many failed sign-in attempts. Try again in {settings.LOGIN_WINDOW_MINUTES} minutes.",
                            headers={"Retry-After": str(settings.LOGIN_WINDOW_MINUTES * 60)})


def record_login_attempt(db: Session, username: str, ip: str, success: bool) -> None:
    db.add(LoginAttempt(username=username, ip=ip[:64], success=success))
    db.commit()
