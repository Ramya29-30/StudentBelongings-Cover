import logging
import re
import time
import uuid
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select, text
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import bootstrap, models  # noqa: F401  (register tables)
from .config import settings, validate_production_settings
from .database import SessionLocal, engine
from .logging_setup import request_id_var, setup_logging
from .models import AuthSession, ChatConversation, LoginAttempt, now
from .migrate import upgrade_to_head
from .routers import admin, ai, auth, chat, claims, core, finance, insure, insure_finance, policies

setup_logging()
log = logging.getLogger("sbc")
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
# The React build ships only external script files and uses no inline <style>/<script>, so nothing inline is allowed.
_APP_CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
# Swagger UI (/docs, disabled in production) loads its assets from a CDN and needs inline bootstrap code, so only that one dev page is relaxed.
_DOCS_CSP = ("default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
             "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'")


_RID_BAD = re.compile(r"[^A-Za-z0-9_-]")


class _BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Pure ASGI limit on request bodies, applied BEFORE authentication and body parsing (FastAPI parses multipart bodies before it
    resolves auth dependencies, so without this an anonymous client could make the server spool arbitrarily large uploads)."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def limit_for(path: str) -> int:
        if path.startswith("/api/claims/") and path.endswith("/evidence"):
            return int(settings.MAX_UPLOAD_MB * 1024 * 1024) + 512 * 1024  # file + multipart overhead; the handler enforces the exact file limit
        if path == "/api/v2/assets":  # up to EVIDENCE_PER_ASSET_MAX files (photos, invoice, documents) plus form fields; the handler enforces each file's own limit
            return int(settings.MAX_UPLOAD_MB * settings.EVIDENCE_PER_ASSET_MAX * 1024 * 1024) + 512 * 1024
        if path.startswith("/api/v2/assets/") and path.endswith("/evidence"):  # one evidence file per request
            return int(settings.MAX_UPLOAD_MB * 1024 * 1024) + 512 * 1024
        if path.startswith("/api/v2/claims/") and path.endswith(("/images", "/documents")):
            return int(settings.MAX_UPLOAD_MB * 1024 * 1024) + 512 * 1024
        return settings.MAX_JSON_BODY_KB * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            return await self._reject(send, limit)
        seen, started, exceeded = 0, False, False

        async def counting_receive():
            nonlocal seen, exceeded
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise _BodyTooLarge()
            return msg

        async def tracking_send(msg):
            nonlocal started
            if exceeded:  # whatever the app answered after we cut the body off (e.g. "error parsing body"), the client gets a clear 413
                if not started:
                    started = True
                    await self._reject(send, limit)
                return
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send, limit)

    @staticmethod
    async def _reject(send, limit: int):
        body = ('{"detail":"Request body is too large (limit %d KB)","error":{"code":"http_413"}}' % (limit // 1024)).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


def _restrict_data_permissions() -> None:
    """The database, uploaded evidence and backups hold personal data: owner-only access (POSIX; harmless no-op where chmod is not supported)."""
    from .migrate import _sqlite_path
    db = _sqlite_path()
    targets = [(settings.UPLOAD_DIR, 0o700)] + ([(db, 0o600), (db.parent / "backups", 0o700)] if db else [])
    for path, mode in targets:
        try:
            if path.exists():
                path.chmod(mode)
        except OSError:
            log.warning("could not restrict permissions on %s", path.name)


def _prune_stale_rows() -> None:
    """Keep the security tables from growing without bound (login attempts: 7 days, ended sessions: 30 days)."""
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now() - timedelta(days=7)))
        db.execute(delete(AuthSession).where((AuthSession.expires_at < now() - timedelta(days=30)) | (AuthSession.revoked_at < now() - timedelta(days=30))))
        # Chat history is kept only as long as it is useful (CHAT_RETENTION_DAYS); messages go with their conversation (ORM cascade).
        for c in db.scalars(select(ChatConversation).where(ChatConversation.updated_at < now() - timedelta(days=settings.CHAT_RETENTION_DAYS))).all():
            db.delete(c)
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_settings()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upgrade_to_head()  # Alembic: creates a clean DB, upgrades an existing one, stamps legacy v1 databases
    with SessionLocal() as db:
        from . import v3
        bootstrap.run(db)
        v3.seed_categories(db)  # the product catalogue is required in every environment (administrator-editable afterwards); after demo seeding so legacy ids stay stable
        db.commit()
    _prune_stale_rows()
    _restrict_data_permissions()
    if settings.IS_PRODUCTION:
        if not settings.ALLOWED_HOSTS:
            log.warning("ALLOWED_HOSTS is not set: any Host header is accepted. Set it to your domain name(s).")
        if not (settings.LEGAL_OPERATOR_NAME and settings.LEGAL_CONTACT_EMAIL):
            log.warning("LEGAL_OPERATOR_NAME / LEGAL_CONTACT_EMAIL are not set: the Privacy Policy and Terms pages show them as missing.")
    log.info("started env=%s ai_provider=%s", settings.APP_ENV, settings.AI_PROVIDER)
    yield


app = FastAPI(title="StudentBelongings Cover API", version="3.0.0", lifespan=lifespan,
              docs_url="/docs" if not settings.IS_PRODUCTION else None, redoc_url=None, openapi_url="/openapi.json" if not settings.IS_PRODUCTION else None,
              description="Standalone academic prototype inspired by Guidewire PolicyCenter / ClaimCenter concepts. NOT Guidewire software. "
                          "Browser clients authenticate with an HttpOnly session cookie + X-CSRF-Token header; API clients may use Bearer tokens.")


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = _RID_BAD.sub("", request.headers.get("x-request-id", ""))[:64] or uuid.uuid4().hex[:16]  # client value is only echoed after stripping anything but [A-Za-z0-9_-]
    request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # unhandled -> centralized 500 (details only in the log)
        log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
        response = JSONResponse({"detail": "Internal server error", "error": {"code": "internal_error", "request_id": rid}}, status_code=500)
    response.headers["X-Request-ID"] = rid
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                             "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
                             "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin", "X-Permitted-Cross-Domain-Policies": "none"})
    if "content-security-policy" not in response.headers:  # an endpoint (e.g. evidence download) may set a stricter policy of its own
        csp = _DOCS_CSP if request.url.path == "/docs" else _APP_CSP
        response.headers["Content-Security-Policy"] = csp + ("; upgrade-insecure-requests" if settings.COOKIE_SECURE and request.url.path != "/docs" else "")
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    if settings.COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    log.info(f"{request.method} {request.url.path} {response.status_code}", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                               "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
    return response


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail, "error": {"code": f"http_{exc.status_code}", "request_id": request_id_var.get()}},
                        status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    errs = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": errs, "error": {"code": "validation_error", "request_id": request_id_var.get()}}, status_code=422)


@app.get("/api/health", tags=["ops"])
def health():
    """Liveness: the process is up."""
    return {"status": "ok", "version": app.version}


@app.get("/api/ready", tags=["ops"])
def ready():
    """Readiness: database reachable and migrated."""
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
            rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return {"status": "ready", "schema_revision": rev}
    except Exception:
        log.exception("readiness check failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)


for r in (auth.router, core.router, policies.router, claims.router, finance.router, admin.router, ai.router, chat.router, insure.router, insure_finance.router):
    app.include_router(r)

# Browser origin policy. Default: no CORS headers at all (the UI is same-origin). Only explicitly listed, validated origins get credentialed access.
if settings.CORS_ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"], expose_headers=["X-Request-ID", "Retry-After"], max_age=600)
if settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
app.add_middleware(BodyLimitMiddleware)  # outermost: oversized bodies are refused before anything else runs

if not FRONTEND_DIST.exists():
    @app.get("/", include_in_schema=False)
    def frontend_missing():
        return HTMLResponse("<!doctype html><html lang=\"en\"><title>Frontend not built</title><body><h1>Frontend not built</h1>"
                            "<p>The API is running (see <a href=\"/docs\">/docs</a>), but <code>frontend/dist</code> is missing. "
                            "Run <code>build-frontend.bat</code> (needs Node.js once) or use the pre-built release package.</p></body></html>", status_code=503)
else:
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        parts = path.split("/")
        if any(x.startswith(".") for x in parts) or path.endswith((".map", ".py", ".db", ".env", ".log", ".bak")):
            raise HTTPException(404, "Not found")  # dotfiles, source maps and backend-looking names are never served, not even as the app shell
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST in f.parents:
            return FileResponse(f, headers={"Cache-Control": "public, max-age=86400"})
        if "." in parts[-1]:
            raise HTTPException(404, "Not found")  # a missing file (not an app route): do not answer with the HTML shell
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
