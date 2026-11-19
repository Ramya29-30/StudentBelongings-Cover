# Security and accessibility review

> **Update 2026-11-01:** a hands-on audit with fixes and verification followed this review. Read [SECURITY_AUDIT_REPORT.md](SECURITY_AUDIT_REPORT.md) first; where the two differ, the audit report is newer.

Scope: this release (backend v2.0 plus the new React frontend). This is a **developer review with automated checks, not a penetration test or an independent audit.** Nothing here is a guarantee.

## 1. Controls in place (verified by automated tests unless noted)

| Area | Control | Evidence |
|---|---|---|
| Passwords | Argon2id hashing; password policy (minimum length, must not contain the username, short blocklist of five very common passwords - **not** a breached-password check); admin password reset revokes the user's sessions | backend `test_auth_security.py`; browser test "users: create ... reset password" |
| Sessions | Random token, only an HMAC is stored server-side; **HttpOnly, SameSite=Strict** cookie; absolute and idle expiry; server-side logout; sessions revoked when a user is disabled | backend tests; browser tests "server-side logout invalidates the session", "no authentication secret is exposed to JavaScript" |
| CSRF | Every state-changing request needs the `X-CSRF-Token` header (issued at login and by `/auth/me`, so a page reload restores it without storing any secret) | browser tests "writes without the CSRF token are rejected", "state-changing requests carry the CSRF header" |
| Login abuse | Rate limiting per account and per client address | browser test "login rate limiting blocks an account" |
| Authorization | Role checks on every endpoint (`require_roles`); students are confined to their own records (other students get 404); four-eyes rule on payments; admins cannot demote/disable themselves | browser tests "role restrictions", "another student cannot see the claim", "assessor cannot approve a reserve"; backend tests |
| Frontend role routing | Route guards redirect by role. **Usability only**: the backend enforces roles regardless | `auth.spec.ts` |
| Browser hardening | `Content-Security-Policy`: `default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` (**no inline scripts, no inline styles, no eval**). Also `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS when `COOKIE_SECURE` | browser test "CSP forbids inline scripts"; the "no console errors, CSP violations or page errors" test visits every page of every role |
| Uploads | Size limit, extension allow-list, content sniffing (a script renamed `.png` is rejected), random stored names, only verified images served inline, other types downloaded | backend tests; browser test "the backend validates independently of the UI" |
| Input validation | Pydantic validation on the server; the UI validates the same rules first for fast feedback; the server is authoritative | browser tests in `quality.spec.ts` |
| Output encoding | React escapes all rendered text; no `dangerouslySetInnerHTML` | code review (`grep` finds none) |
| AI safety | AI output is schema-validated, labelled, never states decisions (validators reject "claim approved" style text), never sets prices, and starts items as *AI Suggested* needing human verification | backend AI tests; browser lifecycle test |
| Secrets | API key and secrets stay in the server environment; production refuses to start with default/short secrets, insecure cookies or demo data | backend tests |
| Error handling | Unhandled errors return a generic message with a request id, details only in the server log | backend tests |
| Audit | Create/update/decision/reserve/payment/user actions are recorded with user and time | browser test "audit logs list the administrator actions" |

## 2. Findings from this review and what was done

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | Legacy UI stored its bearer token in `sessionStorage` and needed `'unsafe-inline'` scripts | High (for that UI) | New React UI uses the HttpOnly cookie only; legacy UI is **no longer served and was removed from the package in the audit**; CSP is now strict unconditionally (previously it relaxed itself when the built UI was absent) |
| 2 | CSP still allowed inline styles | Low | `style-src 'self'` only; verified with zero violations across all pages |
| 3 | `.env.example` used trailing `# comments`; copying it unchanged made the parser keep the comment as part of values (for example `APP_ENV`) | Medium (misconfiguration, could silently disable production checks) | Parser fixed (quoted values and inline comments handled) with a regression test |
| 4 | Frontend dependencies had advisories (1 high, 3 moderate: esbuild dev server, react-router) | Medium | Upgraded to react-router-dom 7.18.x and Vite 6.4.x; `npm audit` now reports 0 vulnerabilities |
| 5 | Students could not enter damage items, a required feature, and any shortcut would have bypassed assessor verification | Design | Added student-declared items: unpriced, `Student Declared`, locked after submission, and blocking completion (POL-013) until an assessor verifies or corrects them |
| 6 | Payment idempotency key derived from the form values could silently replay a cancelled payment | Low | One random key per form instance; deliberate identical requests get an explicit duplicate error |
| 7 | Swagger UI (`/docs`) cannot work under the strict CSP | Info | Only `/docs` gets a relaxed CSP, and `/docs` is disabled in production |

## 3. Dependency review (performed for this release)

* `pip-audit -r backend/requirements.txt`: **no known vulnerabilities** at the time of the run.
* `npm audit` in `frontend-react` (including dev dependencies) and in `e2e`: **0 vulnerabilities** after the upgrades above.
* Runtime Python dependencies are few (FastAPI, SQLAlchemy, Alembic, Pydantic, httpx, argon2-cffi, uvicorn, python-multipart). The packaged UI contains only React, React DOM and React Router.
* Advisories change daily; re-run the audits before any deployment (commands in `DEPLOYMENT.md`).

## 4. Residual risks (not addressed)

* No multi-factor authentication, no email-based password reset, no account-lockout notification.
* No malware scanning of uploads; content sniffing is not a scanner.
* SQLite and a single worker process; not load tested; PostgreSQL untested.
* Rate limiting is database-backed and per-process-safe only for the single-worker setup.
* The `Secure` cookie path (`COOKIE_SECURE=true` over HTTPS) is covered by configuration checks but was **not exercised in a real browser over TLS**.
* Payments are simulated; a real payment integration would need a separate security and compliance review.
* No penetration test, no threat model review by a second person, no data-protection (privacy) impact assessment.
* Browser testing used Chromium on Linux only.

## 5. Accessibility

Implemented in the React UI: semantic landmarks (`header`, `nav`, `main`), a skip link, one `h1` per page, focus moved to the page content on in-app navigation (not on first load, so the skip link stays the first Tab stop), every form control has a programmatically associated `<label>` plus `aria-invalid`/`aria-describedby` for errors, errors announced with `role="alert"`, toasts in a live region, data tables with captions and scoped headers inside keyboard-reachable scroll regions, tabs with roving tabindex and arrow-key support, modals built on the native `<dialog>` element (focus trap, Esc to close, focus returns to the opener), visible 3px focus indicators, and reduced-motion support.

Automated verification (all executed): axe-core WCAG 2.0/2.1 A and AA scans of every page of all three roles plus every claim tab, keyboard tests (skip link, tab arrows, dialog focus trap and return), a test that every form control has an accessible name, and layout checks at 375 px and 768 px widths with no horizontal page scroll.

**Limits of that evidence:** automated tools catch only a subset of accessibility problems. No manual screen-reader testing (NVDA, JAWS, VoiceOver), no user testing with disabled people, and no formal conformance audit were done, so the app must not be described as WCAG-conformant. Responsive checks use browser viewport emulation, not physical devices.
