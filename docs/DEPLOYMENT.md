# Deployment, configuration, backup and recovery

> The application is a prototype. This guide describes how to run it responsibly; it does not make it production-ready (see KNOWN_LIMITATIONS.md). Items marked **untested** were written from the code and general practice but not executed.

## 1. Requirements

* Python 3.11+ (tested on 3.12). Exact tested package versions: `backend/requirements.lock.txt`.
* **Node.js is not needed to run the app.** It is needed only to rebuild the UI (Node 20+) or run the browser tests.
* Windows, Linux or macOS. The automated tests were run on **Linux only**; the Windows scripts were written carefully but **not executed on Windows**.

## 2. Environment variables

Read from the process environment or a `.env` file in the project folder or `backend/` (the real environment wins). Trailing ` # comments` on unquoted lines are ignored.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production`. Production enables the safety checks below, disables `/docs` and `/openapi.json`, uses JSON logs and secure cookies |
| `SECRET_KEY` | dev-only value | HMAC key for session tokens. **Production: random, at least 32 characters** (e.g. `python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `COOKIE_SECURE` | `true` in production | Sends the session cookie only over HTTPS. Production refuses to start without it |
| `SEED_DEMO_DATA` | `true` unless production | Demo users with well-known passwords. **Must be `false` in production** (enforced) |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | empty | Creates the first administrator only when the database has no users. Password at least 12 characters. Remove after first login |
| `DATABASE_URL` | SQLite at `backend/data/sbc.db` | SQLAlchemy URL. Only SQLite has been tested |
| `UPLOAD_DIR` | `backend/data/uploads` | Evidence files |
| `SESSION_TTL_MINUTES` / `SESSION_IDLE_MINUTES` | 480 / 60 | Absolute and idle session expiry |
| `LOGIN_MAX_FAILURES`, `LOGIN_IP_MAX_FAILURES`, `LOGIN_WINDOW_MINUTES` | 5, 30, 15 | Login rate limiting per account and per client address |
| `MIN_PASSWORD_LENGTH` | 8 (12 in production) | Minimum password length (also rejects passwords containing the username and a short blocklist of very common ones) |
| `MAX_UPLOAD_MB` | 8 | Evidence upload limit |
| `TRUST_PROXY` | `false` | Honour `X-Forwarded-For`. Set `true` **only** behind a reverse proxy you control; otherwise clients can spoof their address |
| `LOG_LEVEL`, `LOG_JSON` | `INFO`, `true` in production | Logging |
| `AI_PROVIDER` | `none` | `none`, `gemini`, `anthropic`, `openai`, `openai_compatible` (CoverMate AI chat; see COVERMATE_AI.md) |
| `AI_API_KEY`, `AI_TEXT_MODEL`, `AI_VISION_MODEL`, `AI_BASE_URL`, `AI_JSON_MODE`, `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_MAX_IMAGE_MB` | see `.env.example` | AI provider. Take model names from your provider's current documentation. The key never leaves the server |

## 3. Production checklist

1. `APP_ENV=production`, a generated `SECRET_KEY`, `SEED_DEMO_DATA=false`, a bootstrap admin (then remove those variables).
2. Serve **only over HTTPS** through a reverse proxy (so `COOKIE_SECURE=true` works). Bind uvicorn to `127.0.0.1`. Set `TRUST_PROXY=true` only if the proxy is trusted. **Untested** nginx sketch:
   ```
   location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host;
                proxy_set_header X-Forwarded-For $remote_addr; proxy_set_header X-Forwarded-Proto https;
                client_max_body_size 10m; }
   ```
3. Keep `backend/data/` (database and uploads) on a backed-up volume with restricted permissions.
4. Run one worker process (SQLite) under a service manager of your choice (Windows service wrapper, systemd, etc.).
5. Monitor `GET /api/health` (liveness) and `GET /api/ready` (checks the database). Logs are structured (JSON in production) and carry a request id, also returned as `X-Request-ID`.
6. Review `docs/SECURITY_REVIEW.md` and `docs/KNOWN_LIMITATIONS.md`.

## 4. Database migrations

Alembic migrations (`backend/alembic/versions`, revisions 0001 to 0003) run **automatically at start-up**. If an existing SQLite database needs upgrading, a copy is written first to `backend/data/backups/<name>-pre-migration-<timestamp>.db`. A database created by the original v1 prototype (no `alembic_version` table) is detected and stamped to the baseline, preserving policy versions and claim history (covered by the migration tests). Manual run: `cd backend && python -m app.cli migrate`.

To add a migration during development: `cd backend && alembic revision -m "describe change"`, edit the file, add a test in `tests/test_migrations.py`.

## 5. Backup and recovery

Back up **both** the database and the uploads folder, together.

* Windows: `backup.bat`. Linux/macOS: `cd backend && python -m app.cli backup [--dest DIR]`. This uses SQLite's online backup API (consistent even while the app runs) and prints the uploads path to copy as well. Copy `backend/data/uploads/` with your normal file backup tool.
* **Restore:** stop the app; replace `backend/data/sbc.db` with the backup file (renamed to `sbc.db`); restore the matching `uploads/` folder; start the app (pending migrations apply automatically). Then sign in and open a few claims to confirm evidence downloads work.
* **A backup that has never been restored is not a backup.** Practise the restore on a copy. This procedure was exercised only through the automated backup/migration tests, not as a full manual disaster-recovery drill.
* Other databases: use that database's own tools (for example `pg_dump`). `app.cli backup` supports SQLite only.

## 6. Docker (untested)

`Dockerfile` (multi-stage: Node builds the UI, Python image runs the app as a non-root user) and `docker-compose.yml` are provided as a starting point. **They were not built or run** because Docker was not available. Expect to adjust them. Create `.env.production` from `.env.example`, keep it out of version control, and put an HTTPS proxy in front.

## 7. Upgrading the UI

`build-frontend.bat` (Windows) or `./build-frontend.sh` runs `npm ci && npm run build`, writing `frontend/dist`. Restart is not required for static files but is harmless.

## 8. Updating dependencies

Python: `pip install -U -r backend/requirements.txt`, run the tests, regenerate `requirements.lock.txt` from a clean virtual environment, and run `pip-audit -r backend/requirements.txt`. Node: `npm audit` in `frontend-react` and `e2e`, upgrade, rebuild, re-run both test suites. Results of the audits performed for this release are in `docs/TESTING.md`.

## 9. Added by the security audit

* **Custom domain and HTTPS:** step by step in [CUSTOM_DOMAIN.md](CUSTOM_DOMAIN.md).
* **New settings** (all in `.env.example`): `ALLOWED_HOSTS`, `TRUSTED_PROXY_HOPS`, `CORS_ALLOWED_ORIGINS` (default empty, same-origin only), `MAX_JSON_BODY_KB`, per-user limits (`CLAIMS_PER_HOUR`, `UPLOADS_PER_HOUR`, `PAYMENT_REQUESTS_PER_HOUR`, `ASSETS_PER_HOUR`, `AI_CALLS_PER_10_MIN_*`, `AI_MAX_CONCURRENCY`) and the `LEGAL_*` operator details.
* **The server now refuses to start** when `APP_ENV` is not `development`, `test` or `production`, when a CORS origin is a wildcard, `null`, or (in production) not https.
* **Put a per-address request limit in the reverse proxy.** The application limits sign-in attempts per address and expensive actions per user, but it does not rate limit every request.
* **Install runtime packages from `requirements.lock.txt`; test tools are in `requirements-dev.txt`.**
* **Backup and restore drill** (verified in the audit on SQLite): `python -m app.cli backup` writes an owner-only copy using SQLite's online backup API; to restore, stop the server, copy the chosen backup over the database file (keep the uploads folder from the same time), start the server (migrations run automatically), and sign in. Backups contain all personal data: store them encrypted and delete old ones according to your retention policy. The application does not encrypt data at rest.
