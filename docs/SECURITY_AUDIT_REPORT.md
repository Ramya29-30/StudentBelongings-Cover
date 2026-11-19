# Security audit, hardening and launch-readiness report

Audit date: 2 November 2026. Target: `StudentBelongingsCover_Complete.zip` (backend 2.1.0, React UI). Method: read the whole source, write tests that assert the secure behaviour, **run them against the unmodified code to prove each issue**, fix, re-run. Where an exploit was demonstrated on the original code it is marked **Demonstrated**; where it is from code reading only it is marked **By inspection**.

## Verdict

**Not ready for a public launch yet, but no known high-severity code issue remains.** Every code-level finding below was fixed and verified. What still blocks a launch is outside the code: no domain is connected, the legal pages need your details and a lawyer's review, Git history could not be audited, uploads are not malware-scanned, and no independent penetration test exists. Nothing here proves the application is "secure"; it shows the issues found were fixed and that the controls listed are tested.

## 1 and 2. Findings, severity, and how each was verified

| ID | Severity | Finding | Evidence on original code | Fix | Verification |
|---|---|---|---|---|---|
| F-01 | **High** | **BOLA:** a student could file a claim against *another student's asset* by id; the claim report then returned that asset's owner, serial number, value and receipt reference | **Demonstrated:** 201 Created, leaked `HP-5CD2201`, 62000, `INV-HP-777` | Asset must be owned by the caller (otherwise 404, indistinguishable from missing) and insured under the chosen policy (422) | `test_student_cannot_open_claim_on_another_students_asset`, `test_asset_not_on_policy_is_rejected` |
| F-02 | **High** | **Fail-open environment:** any `APP_ENV` other than the exact word `production` (for example `prod`) silently ran as development: demo accounts with known passwords, insecure cookies, API docs on | **Demonstrated:** `APP_ENV=prod` passed validation | `APP_ENV` must be `development`, `test` or `production`; validation now runs in every environment | `test_unknown_app_env_fails_closed`; live start-up refused (exit 3) |
| F-03 | **High** | **Payment race:** payment checks and inserts were not atomic. Concurrent requests produced `UNIQUE constraint failed: payments.reference` 500 errors and could pass the remaining-reserve check together; approve/cancel could interleave | **Demonstrated:** 500 errors under 8 concurrent requests (over-commitment itself was *not* reproduced) | Every money operation now takes a per-claim write lock before reading state; references derive from the primary key; same-key replay with a different amount returns 409; duplicate-key `IntegrityError` becomes 409 | `test_concurrent_payment_requests_cannot_exceed_reserve` (passed 5 of 5 repeats), `test_idempotent_replay_with_different_amount_conflicts` |
| F-04 | **High** | **Assessor takeover:** any assessor could take a claim assigned to someone else, overwrite its notes, add items, evaluate, recommend reserves and request payments | **Demonstrated:** steal 200 (claim moved to the second assessor), notes overwrite 200, add item 201 | Writes require the claim to be unassigned or yours (403 otherwise); also enforced in the status service. Reading submitted claims is kept because the UI has an "All claims" tab. Administrators can reassign | `test_other_assessor_cannot_write_to_claim_assigned_elsewhere` |
| F-05 | **Medium** | **Asset value tampering:** a student could raise `declared_value`, backdate `purchase_date` or change the serial number of an insured or claimed asset. The rules engine prices from these live values and policy versions snapshot only asset ids | **Demonstrated:** declared value set to 9,999,999 on an insured asset, 200 | Students can no longer change category, purchase date, declared value or serial number once an asset is on a policy or has a claim (409); administrators can, and the audit trail now records before and after | `test_student_cannot_rewrite_value_of_insured_asset` |
| F-06 | **Medium** | **Unauthenticated oversized uploads:** FastAPI parses multipart bodies before authentication, and the size limit ran only after the whole upload was received | Test expects 413; original did not provide it | Pure-ASGI body limit before auth: 256 KB for JSON, upload limit plus 0.5 MB for evidence, for declared and chunked bodies | `test_oversized_request_bodies_are_rejected_before_auth`; manual chunked test returned 413 |
| F-07 | **Medium** | **No abuse limits on expensive actions:** unlimited AI calls (cost: "denial of wallet"), claim creation, uploads, payment requests and asset creation. A slow AI call also holds a worker thread for up to minutes | Test expects 429; original returned none | Per-user, database-backed limits (configurable); at most 4 concurrent AI calls (503 when busy) | `test_ai_endpoints_are_rate_limited`, `test_claim_creation_is_capped` |
| F-08 | **Medium** | **Audit log over-exposure and unbounded size:** assessors could read every user's login IP addresses and user-management events; `limit=-1` removed the cap (SQLite treats a negative LIMIT as unlimited) | **Demonstrated:** 4 login-IP rows visible; `limit=-1` returned 200 | Assessors see claim work only; `limit` is 1 to 500 | `test_assessor_audit_is_scoped_and_hides_login_ips`, `test_audit_limit_is_bounded` |
| F-09 | **Medium** | **Internal assessor notes were returned to the claimant** in claim, report and status responses | Test failed (note text present) | Blank for students | `test_students_do_not_see_internal_assessor_notes`, and a real-browser check |
| F-10 | **Medium** | **Student drafts visible to staff** (data minimisation; assessors cannot act on drafts anyway) | Test failed; seed Draft listed | Drafts are 404 for assessors in lists, detail, dashboard | `test_assessor_cannot_see_student_drafts`, browser test. **Deliberate behaviour change:** see section 8 |
| F-11 | **Medium** | **Unbounded text and list inputs** (location, notes, reasons, asset fields, evidence reference lists, pagination) | **Demonstrated:** 20 KB location accepted (201) | Length caps matching column sizes, bounded `limit`/`offset`, bounded ids | `test_text_fields_are_length_limited` |
| F-12 | **Low** | `X-Forwarded-For` left-most value (client-supplied) was used for rate limits behind a proxy, so an attacker could dodge per-address limits | By inspection; unit test | The address added by your trusted proxy is used (`TRUSTED_PROXY_HOPS`, default 1) | `test_forwarded_for_uses_trusted_hop_not_client_supplied_value` |
| F-13 | **Low** | `ai_suggestion_id` on a claim item was not checked to belong to that claim (unknown id caused a 500 foreign-key error) | **Demonstrated** (500) | 422 unless the suggestion belongs to the claim | `test_ai_suggestion_must_belong_to_the_claim` |
| F-14 | **Low** | Prompt-injection surface: claimant-typed text inside item notes and rule data was sent to the AI unwrapped; provider error text could in theory contain the API key | By inspection | Wrapped as untrusted data; key and key-shaped strings redacted from provider errors and stored excerpts | Existing AI tests plus code review (no provider key was available to test live) |
| F-15 | **Low** | Environment name disclosed to anonymous callers by `/api/health` and `/api/public-config` | Test failed | Removed | `test_environment_is_not_disclosed_to_anonymous_callers` |
| F-16 | **Low** | Request-id header from the client was echoed into responses and logs unfiltered | Test failed | Only `[A-Za-z0-9_-]` kept | `test_request_id_header_is_sanitised` |
| F-17 | **Low** | Staff login names shown to students (status history, audit, payments) and idempotency keys exposed to students | By inspection | Students see "You" or "Claims team" | Covered by existing claim and finance tests |
| F-18 | **Low** | Database, uploads and backups created world-readable; error logs could include bound SQL parameters (password hashes, claim text) | `ls` showed `-rw-r--r--` for backups | Owner-only permissions (POSIX); `hide_parameters=True` | `test_database_and_uploads_are_owner_only`; backup mode checked by hand |
| F-19 | **Low** | Evidence downloads carried only the generic CSP; claim, policy and payment numbers derived from `max(id)+1` could collide | By inspection | Evidence served with `default-src 'none'; sandbox` and no-store; numbers derive from the primary key | `test_evidence_responses_are_sandboxed` |
| F-20 | **Info** | SPA fallback answered `/.env`, `*.map`, `/.git/config` with the HTML shell (200) | **Demonstrated** (no data leaked) | 404 for dotfiles, source maps and unknown file names | `test_static_server_does_not_leak_files` (7 variants) |
| F-21 | **Info** | Login-attempt and ended-session rows were never deleted; logout cookie deletion did not mirror its attributes | By inspection | Pruned at start (7 and 30 days); attributes mirrored | Start-up exercised by every test |
| F-22 | **Info** | `pytest` shipped in runtime requirements; test files and docs were copied into the Docker image; the unserved legacy UI (21 `innerHTML` sinks, `sessionStorage` token) shipped in the ZIP | By inspection | Dev requirements split out; `.dockerignore` tightened; legacy UI removed (your original ZIP keeps it) | `test_repo_hygiene.py` |

### Checked and found sound (verified, no change needed)
* **Passwords:** Argon2id (argon2-cffi defaults), transparent rehash, constant-time-style dummy verification for unknown users.
* **Sessions:** random 256-bit tokens stored as keyed hashes, absolute and idle expiry, new token at every login (no fixation), password change revokes other sessions, logout is server-side. Cookie flags `HttpOnly`, `SameSite=Strict`, `Secure` in production (seen on a live production-mode server).
* **CSRF:** synchronised token header on all state-changing requests plus `SameSite=Strict`.
* **CORS:** the original configured none (same-origin only), which is safe; verified that untrusted origins receive no CORS headers on simple and preflight requests. An optional strict allow-list now exists (see section 10).
* **XSS:** no `dangerouslySetInnerHTML`, `innerHTML`, `eval` or browser storage in the React source (a test enforces it); a real-browser test stores `<img onerror>`, `<script>` and `<svg onload>` in a claim and confirms they render as literal text and no script runs.
* **SQL injection:** all queries use the ORM with bound parameters; no string-built SQL found.
* **Uploads:** extension and content sniffing, allow-list (no SVG, HTML or scripts), random stored names, size cap, per-claim file cap, path-traversal check, attachment disposition for non-images, `nosniff`.
* **Static server path traversal:** seven traversal variants all returned 404 or the app shell with no file content.
* **Authorisation of money actions:** reserve and payment approval are administrator-only and four-eyes (the requester cannot approve); students and assessors receive 403 (existing tests plus browser tests).

## 3. Files modified
**Backend:** `config.py`, `main.py`, `security.py`, `services.py`, `database.py`, `cli.py`, `limits.py` (new), `ai/service.py`, `routers/{auth,claims,core,policies,finance,ai,admin}.py`.
**Frontend:** `index.html`, `public/` (favicons, new), `src/App.tsx`, `src/components/Layout.tsx`, `src/pages/Login.tsx`, `src/pages/Legal.tsx` (new), `src/styles.css`; production bundle rebuilt.
**Tests:** new `test_security_audit.py` (35), `test_repo_hygiene.py` (5), `e2e/tests/launch.spec.ts` (7); changed `test_api.py` and `test_hardening.py` (3 assertions, section 8), `e2e/tests/quality.spec.ts` (WCAG 2.2 tag), `e2e/tests/admin.spec.ts` (flaky selector), `e2e/playwright.config.ts` (optional browser path).
**Packaging and docs:** `.env.example`, `.gitignore`, `.dockerignore`, `requirements*.txt`, `requirements.lock.txt`, `start.sh`, `start.bat`, `run-tests.bat`, README, `docs/` (this report, `CUSTOM_DOMAIN.md`, API, deployment, testing, limitations). Removed: `frontend-legacy/`.
Preserved untouched: rules POL-001 to POL-013, the claim calculation engine, policy versioning, audit trail, authentication architecture, AI verification requirements, reserve and payment workflows. No claim is approved or settled automatically.

## 4. Vulnerabilities that remain (accepted or needing your decision)
* **Assessor read access to other assessors' submitted claims** is kept because the product has an "All claims" tab. To make it strict, restrict `claim_access` and `list_claims` for assessors to assigned or unassigned claims and remove that tab.
* **A single malicious administrator can bypass four-eyes** by creating an assessor account they control. Mitigated only by the audit trail; organisational controls are needed.
* **Rate limiting** covers sign-in and the expensive actions, not every request; use a reverse-proxy limit (documented). Counts are per user, not per address, for the new limits.
* **Account lockout by username** lets an attacker temporarily lock a known account (an accepted trade-off against password guessing).
* **No malware scanning** of uploaded PDFs and images; no EXIF removal; **no encryption at rest** in the application; SQLite is single-writer (the lock fix is SQLite-specific in its mechanism; other databases would use row locks and need their own test).
* **AI output filter** (`_no_decision`) is a heuristic, not a boundary. The real controls are mandatory human verification and no automatic approval.
* **No self-service password reset or data export/deletion**; resets are administrator-driven.

## 5. Dependencies
`pip-audit` on `requirements.txt` and on the lock file: no known vulnerabilities. `npm audit` for the frontend (with dev dependencies) and e2e: 0 vulnerabilities. No package was upgraded: nothing required it, and the remaining "outdated" ones are major versions (React 19, Vite 8, TypeScript 7) that were not taken blindly. `pytest` moved to `requirements-dev.txt`; the lock was regenerated from a clean runtime-only environment. `uvicorn[standard]` and `httpx` are used at runtime and were kept.

## 6. Git history
**Could not be audited:** the uploaded ZIP contains no `.git` directory. The working tree, built bundle and fixture database were scanned (`detect-secrets` plus pattern search): 25 heuristic hits, all demo or test passwords, UI placeholder text or the dev-only default key that production refuses; no private keys, provider keys or tokens; no `.env` file; no source maps. **Run this yourself on the real repository:** `gitleaks git --redact -v` (or `trufflehog git file://.`) and `git log --all --diff-filter=A -- '*.env*' '*.db' '*.pem'`. If anything real is found: rotate it first, then decide on history rewriting (it changes every commit id and forces all collaborators to re-clone). I rewrote nothing.

## 7. Database security
ORM with bound parameters throughout; `hide_parameters` on; owner-only files; generic error responses; Alembic migrations (tests cover fresh, legacy v1 and data-preserving upgrades); backup and restore drilled (integrity check OK, schema revision 0003, all rows present). Default SQLite credentials are not applicable. Not covered: encrypted backups and off-site copies (yours to arrange).

## 8. Deliberate behaviour changes (please review)
1. Assessors can no longer see students' **Draft** claims. This changed three existing assertions from "400" to "400 or 404" (`test_status_machine_rejects_skipping_steps`, `test_assignment_workflow`, evidence-file check) and one count from 4 to 3 (`test_role_based_access_restrictions`). The requests are still refused. No other existing assertion was altered.
2. Students cannot change category, purchase date, declared value or serial number of an insured or claimed asset.
3. Students see "Claims team" instead of staff usernames and never see assessor notes.
4. Assessors cannot take or edit a claim assigned to someone else; `/api/students` is administrator-only; the claim list is paged (default 200, maximum 500).

## 9. XSS, validation, headers
Headers on every response: `Content-Security-Policy` (`default-src 'self'`, no `unsafe-inline`, `frame-ancestors 'none'`, `object-src 'none'`, plus `upgrade-insecure-requests` over HTTPS), `Strict-Transport-Security` (HTTPS deployments), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (camera, microphone, geolocation, payment, usb off), `X-Frame-Options`, and cross-origin opener and resource policies. Verified on a live production-mode server and in a real browser (no CSP violations on any portal page).

## 10. CORS
Default: no CORS headers (same-origin). Optional `CORS_ALLOWED_ORIGINS`: explicit origins only, credentials allowed only for them, methods and headers restricted; the server **refuses to start** on `*`, `null`, paths, or non-https origins in production. Verified live: trusted origin gets the allow headers on preflight; untrusted origin gets none on preflight or on a normal request.

## 11. Accessibility
Existing axe scans (WCAG 2.0 to 2.1 A and AA) were raised to include WCAG 2.2 AA rules; all pass on every page of all three portals, dialogs and tabs, and on the new legal pages. Keyboard tests (skip link, tab order, dialog focus trap and return) pass. All 18 colour pairs in the design tokens were calculated and meet 4.5:1 (text) or 3:1 (input borders). Changes: checkboxes and radios enlarged to 20 px, site footer landmark with labelled navigation. **Not tested:** a real screen reader (NVDA, VoiceOver, JAWS) and reduced-motion behaviour beyond the existing CSS; automated tools find only part of WCAG issues.

## 12. Design
The existing UI already met your rules (no gradients, emoji, fake metrics, testimonials, logos or hero copy; real data or empty states). Changes: status badges lost their pill shape (4 px radius), a shield favicon was added, and a restrained footer with legal links. A test now fails the build on em or en dashes, emoji, gradients, pill radii, unsafe DOM APIs and browser storage. No icon library was added because no icons are used; adding one would only add a dependency.

## 13. Privacy Policy and Terms: status
Pages exist at `/privacy` and `/terms`, public, linked from the login page and every portal footer. They describe what the software actually does: data stored, the one session cookie, AI processing (text changes with whether a provider is configured), storage, retention (stating honestly that there is **no automatic deletion**), access by role, rights, security (with its limits), and that the service is an academic prototype, not an insurer, with simulated payments. They contain **no invented company details**: operator name, address, contact email and governing law come from `LEGAL_*` settings and show as highlighted "not yet provided" until you set them. Each page carries a "Draft, not legal advice, not reviewed by a lawyer" notice until you set `LEGAL_REVIEWED_BY_COUNSEL=true`. **You must provide:** operator name, postal address, contact email, governing law and regulator, legal basis for processing, minimum age, retention period, server location and hosting provider, and AI provider name, location and retention terms if you enable AI. The text was drafted from the code and is not legal advice.

## 14. Favicon
Done and verified: SVG, ICO (16, 32, 48), 32 px PNG and 180 px Apple touch icon, declared in `index.html`; a browser test fetches every declared icon and checks it is served as an image. No default Vite icon.

## 15. Custom domain
**Not connected.** No domain or DNS access was supplied. Exact steps are in `CUSTOM_DOMAIN.md`.

## 16. "Made with AI" branding
None found in the source, the built bundle or the page title (a browser test checks for common badge strings). No licence notices were removed.

## 17. Test results (final run on the finished code)
| Suite | Result |
|---|---|
| Backend pytest | **141 passed** |
| Playwright (real Chromium 153) | **67 passed** (60 existing + 7 new) |
| Security audit tests (included above) | 35 backend + 7 browser, all passing. On the first run against the original code 26 of 33 backend tests failed; most were genuine findings, a few were mistakes in my own tests that I corrected (a fixture password, an over-complicated assertion), and the rest confirmed controls that were already secure |
| `npm run build` (strict `tsc` then Vite) | passes |
| `pip-audit`, `npm audit` | 0 vulnerabilities |
| Secret scan | no real secrets (Git history not available) |
| Live production-mode run | unsafe configs refused; docs off; wrong Host 400; Secure cookie; HSTS; CORS allow and deny verified |
| Backup and restore drill | passed |
One existing browser test (`administrator workflow ... payments can be disabled`) was **flaky on the original code too** (failed 2 of 6 runs): it matched two simultaneous success toasts. The selector was made robust and passed 8 of 8 repeats. The Chromium used is a bundled build with a newer major version than Playwright 1.56 expects; it worked, but you should re-run `npx playwright test` with your own installed browser.

## 18. Remaining production blockers
1. Connect a domain with HTTPS and set `ALLOWED_HOSTS`, `COOKIE_SECURE`, `TRUST_PROXY` (see `CUSTOM_DOMAIN.md`).
2. Fill in the `LEGAL_*` facts and have a lawyer review both legal pages before enabling `LEGAL_REVIEWED_BY_COUNSEL`.
3. Run a secret scan over the real Git history and rotate anything found.
4. Decide on assessor read scope and administrator separation of duties (section 4).
5. Add proxy-level rate limiting, encrypted backups, and a malware scan for uploads if real users will upload files.
6. Commission an independent penetration test, and run a screen-reader check, before describing the service as secure or accessible.
7. If real money or real insurance is ever intended, this prototype is not that system: payments are simulated by design.
