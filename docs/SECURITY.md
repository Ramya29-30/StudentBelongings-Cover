# Security

Scope: an academic prototype with simulated payments. It was hardened and tested, not independently pen-tested. See `SECURITY_REVIEW.md` and `SECURITY_AUDIT_REPORT.md` for the earlier audit of the v2 base.

## Controls
**Accounts and sessions**: Argon2id password hashing (legacy PBKDF2 hashes upgrade on login), password policy, login throttling and lockout window, server-side sessions in an HttpOnly cookie (Secure in production), idle and absolute expiry, session revocation on password change, CSRF token required on every write, generic login errors. Self-registration can only create students (extra fields are rejected) and is throttled.
**Authorization**: role checks on every endpoint (`require_roles`) and server-side ownership on every object. Another student's asset, policy, claim, image, payment or file returns 404. Tests cover cross-student access on assets, files, quotes, purchases, policies, claims, uploads, verification and review.
**Tamper resistance**: the browser cannot send premiums, coverage, deductibles, policy ids, payable amounts or statuses (strict request models reject unknown fields). Policy terms are frozen at purchase. The amount is calculated on the server and bounded by the frozen limit and remaining policy limit. Duplicate claims for the same asset and incident date and double policies on one asset are refused. A premium month cannot be paid twice (unique constraint).
**Input validation**: Pydantic models with bounds on every field, enumerated incident types, damage types validated against the category, dates not in the future.
**File upload**: extension allow-list (JPEG, PNG; PDF only for invoices and documents), size limit streamed in chunks (default 8 MB, enforced by a body limiter and again while reading), magic-byte signature check, full decode with Pillow (corrupt and truncated files rejected, decompression-bomb limit), server-generated random file names (the user name is stored only as a sanitised display name), storage inside one directory with a resolved-path check, atomic write, cleanup if the database write fails, at most 5 photos per claim. No static route serves uploads: every download is authenticated and ownership-checked, sent with `Content-Security-Policy: default-src 'none'; sandbox`, `nosniff` and `no-store`.
**Injection and XSS**: SQLAlchemy ORM with bound parameters (no string-built SQL); React escapes output; strict CSP and security headers; free text is never rendered as HTML; AI output is parsed into typed models and never executed.
**Abuse limits**: database-backed per-user limits for claims, uploads, assets, payments, verification runs, plus a registration throttle.
**Secrets and config**: everything from environment variables; `.env.example` provided; the server refuses to start in production with weak or demo settings, with `AI_VERIFY_MODE=dev_simulation`, or with demo seeding. Demo accounts exist only when `SEED_DEMO_DATA=true`, use fictional names and `example.edu` addresses, and the endpoint listing them returns 404 otherwise.
**Errors and logging**: no internal details in responses (request id only); every important action (registration, category change, purchase, premium, status change, review, settlement, AI report) is written to the audit log.
**Payment simulation**: no card number, CVV, bank or UPI field exists in any model, API or form; transactions are labelled SIMULATED.
**Privacy**: AI reports never reveal another student's claim number; only whitelisted EXIF fields (make, model, software, capture dates) are stored in the database.

## Known limitations
* Original uploaded images are stored as received, so embedded EXIF (including GPS, if present) remains inside the stored file. Only the owner and staff can download it, but it is not stripped.
* No antivirus scanning, no email or phone verification, no MFA, and open self-registration (throttled but not CAPTCHA-protected).
* The invoice and the purchase price are student-declared; invoices are only verified when an administrator marks them so.
* Rate limits are per user and database-backed; there is no per-IP network rate limiting beyond login throttling. Use a reverse proxy in production.
* SQLite is a single-writer database. The PostgreSQL path is documented but untested.
* The bundled detector licence is AGPL-3.0.
* Image-based checks cannot prove ownership or authenticity and can be fooled by a photo of a photo.
* The development-simulation AI mode performs no analysis; it exists for demonstration only and is blocked in production.
* No independent penetration test was performed.
