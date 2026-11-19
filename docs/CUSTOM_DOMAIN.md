# Connecting a custom domain (steps you must perform)

**Status: not connected.** No domain name or DNS access was provided during the security audit, so none was configured and none is claimed. This page lists exactly what to do. Replace `cover.example.org` with your real domain.

## What you need
1. A registered domain name and access to its DNS settings (at your registrar or DNS host).
2. A server with a public IP address that runs this application (a VPS, or a container host), and the ability to open ports 80 and 443.
3. A reverse proxy that terminates HTTPS in front of the application (Caddy is shown because it obtains and renews certificates automatically; nginx works too).

## Steps
1. **Run the application privately.** Bind it to localhost only (the provided `docker-compose.yml` already publishes `127.0.0.1:8000`).
2. **Create DNS records** at your DNS host, pointing at the server's public address:
   * `A` record: name `cover` (or `@` for the bare domain), value = server IPv4 address.
   * `AAAA` record (only if the server has IPv6): same name, value = server IPv6 address.
   * Optionally a `CNAME` for `www` pointing to the main name. Use a short TTL (300 seconds) until everything works.
   * Check propagation: `dig +short cover.example.org` must print your server address.
3. **Install the reverse proxy and open ports 80 and 443.** Example `Caddyfile` (certificates are obtained automatically once DNS resolves to this server):
   ```
   cover.example.org {
       encode zstd gzip
       request_body {
           max_size 9MB
       }
       reverse_proxy 127.0.0.1:8000
   }
   ```
   For nginx use `client_max_body_size 9m;`, `proxy_set_header Host $host;`, `proxy_set_header X-Forwarded-For $remote_addr;`, `proxy_set_header X-Forwarded-Proto https;`, and add a request limit such as `limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;` on `/api/`.
4. **Set the production environment** (file `.env.production`, never committed). Generate the secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`:
   ```
   APP_ENV=production
   SECRET_KEY=<generated value>
   COOKIE_SECURE=true
   SEED_DEMO_DATA=false
   ALLOWED_HOSTS=cover.example.org
   TRUST_PROXY=true
   TRUSTED_PROXY_HOPS=1
   BOOTSTRAP_ADMIN_USERNAME=<your admin name>
   BOOTSTRAP_ADMIN_PASSWORD=<12+ character passphrase, remove after first login>
   LEGAL_OPERATOR_NAME=<your legal or trading name>
   LEGAL_CONTACT_EMAIL=<monitored address>
   LEGAL_POSTAL_ADDRESS=<postal address>
   LEGAL_GOVERNING_LAW=<jurisdiction>
   ```
   Leave `CORS_ALLOWED_ORIGINS` empty: the UI and API share one origin, so no CORS headers are needed or sent. Only set it if a separate web origin must call the API; use exact `https://` origins, never `*`.
5. **Start, then verify** (from any machine):
   ```
   curl -sI https://cover.example.org/ | grep -iE "strict-transport|content-security|x-content-type"
   curl -s  https://cover.example.org/api/health
   curl -s -o /dev/null -w "%{http_code}\n" -H "Host: wrong.example" https://cover.example.org/api/health   # expect 400 or a proxy error, not 200
   ```
   Sign in in a browser and confirm in the developer tools that the `sbc_session` cookie shows `HttpOnly`, `Secure` and `SameSite=Strict`.
6. **Test certificate quality** with a public TLS checker, and consider adding your domain to the HSTS preload list only after everything works for several weeks (it is hard to undo; the application sends HSTS with `includeSubDomains` but does not request preloading).
7. **Do not forget** to fill in the `LEGAL_*` values and to have the Privacy Policy and Terms reviewed by a lawyer before setting `LEGAL_REVIEWED_BY_COUNSEL=true`.

## Why these settings matter
* `ALLOWED_HOSTS` makes the application refuse requests for any other host name.
* `TRUST_PROXY` and `TRUSTED_PROXY_HOPS` make per-address rate limits use the address added by your proxy rather than a value supplied by the client. Set `TRUST_PROXY=true` only if every request really passes through your proxy.
* Cookie `Secure` plus HSTS keep sessions off plain HTTP.
