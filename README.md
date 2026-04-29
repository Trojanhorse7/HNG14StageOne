# Insighta Labs+ — profiles API (HNG Stage 1–3)

Django + Django REST Framework: **`Profile`** model (UUID v7), PostgreSQL or SQLite, **GitHub OAuth + JWT** (Bearer or **http-only cookies**), **RBAC**, **CSRF** for browser writes, rule-based natural-language search (no LLMs), **CSV export**, and **rate limits**.

Companion clients (same API & permissions):

- **Web portal:** [github.com/Trojanhorse7/insighta-frontend](https://github.com/Trojanhorse7/insighta-frontend)
- **CLI:** [github.com/Trojanhorse7/insighta-cli](https://github.com/Trojanhorse7/insighta-cli)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy [`.env.example`](.env.example) to `.env` and set at least **`DJANGO_SECRET_KEY`** (use a long random value; optional **`JWT_SIGNING_KEY`** for HS256). Set **`GITHUB_CLIENT_ID`** / **`GITHUB_CLIENT_SECRET`**, **`BACKEND_PUBLIC_URL`**, and **`WEB_PORTAL_ORIGIN`** for OAuth redirects and CORS/CSRF.

```bash
python manage.py migrate
python manage.py seed_profiles   # optional; reads seed_profiles.json
python manage.py runserver 0.0.0.0:8000
```

One-off **admin** by GitHub login (`User.username`): `python manage.py set_user_role Trojanhorse7` (optional `--role analyst`).

`DATABASE_URL` selects Postgres; if unset, **`db.sqlite3`** in the project root is used.

**`seed_profiles`:** re-running **updates** rows by unique `name`. Batching: `SEED_POSTGRES_BATCH` (default **250**), or `python manage.py seed_profiles --batch 500`.

---

## Authentication & security

| Mechanism | Notes |
|-----------|--------|
| **API version** | All **`/api/*`** requests must send **`X-API-Version: 1`** or the API returns **400** (`API version header required`). |
| **JWT access** | `Authorization: Bearer <jwt>` **or** http-only cookie **`insighta_access`**. Never expose tokens to frontend JS except via cookie (portal uses cookies only). |
| **Refresh (CLI / scripts)** | **`POST /auth/refresh`** JSON body: `{ "refresh_token": "<opaque>" }` — **CSRF-exempt** (machine clients). |
| **Refresh (browser)** | **`POST /auth/refresh/web`** — reads **`insighta_refresh`** http-only cookie; **CSRF required** (`X-CSRFToken` + `csrftoken` cookie). Rotates and sets new cookies. |
| **Logout (browser)** | **`POST /auth/logout/web`** — CSRF required; revokes refresh and clears cookies. |
| **CSRF bootstrap** | **`GET /auth/csrf`** — ensures **`csrftoken`** is set for SPA clients. |
| **Current user** | **`GET /auth/me`** — JWT required; returns `id`, `username`, `email`, `role`, `avatar_url`, `github_id`, `is_active`. |

**GitHub OAuth (browser):**

1. **`GET /auth/github`** — starts PKCE flow; GitHub redirects to **`{BACKEND_PUBLIC_URL}/auth/github/callback`**.
2. Callback sets **`insighta_access`** / **`insighta_refresh`** (http-only) and redirects to **`WEB_PORTAL_ORIGIN`**.

**CLI OAuth:** **`POST /auth/github/cli`** with `code`, `code_verifier`, `redirect_uri` (see CLI README).

**RBAC:**

- **Analyst:** `GET` profiles, classify, search, export.
- **Admin:** same, plus **`POST /api/profiles`** and **`DELETE /api/profiles/{uuid}`** (`UserRole.ADMIN`).

---

## CORS & CSRF

Browser clients that send **cookies** need aligned origins:

- **`CORS_ALLOWED_ORIGINS`** is built from **`WEB_PORTAL_ORIGIN`**, common Vite URLs, and optional comma-separated **`CORS_EXTRA_ORIGINS`**.
- **`CORS_ALLOW_CREDENTIALS = True`** (not `Access-Control-Allow-Origin: *` with credentials).
- **`CSRF_TRUSTED_ORIGINS`** matches the same portal origins for cross-origin **`POST`** with cookies.

Machine clients (CLI, curl with Bearer) are unaffected by CORS.

---

## Rate limiting & logging

- **`/auth/*`:** **10** requests per minute per IP.
- **`/api/*`:** **60** requests per minute per authenticated user (or per IP if anonymous).

**429** response: `{ "status": "error", "message": "Too many requests" }`.

Request timing and user id are logged at **INFO** (`accounts.rate_limit_middleware`).

---

## API endpoints (profiles & classify)

Send **`X-API-Version: 1`** on every **`/api/*`** call. Authenticate with **Bearer** or session cookies.

### `GET /api/classify?name=...`

Genderize-backed classification (legacy shape).

### `GET /api/profiles`

List with **filters**, **sort**, **pagination**; optional **`total_pages`** and **`links`** (`self`, `next`, `prev`).

Query parameters: same as before (`gender`, `age_group`, `country_id`, `min_age`, `max_age`, `min_gender_probability`, `min_country_probability`, `sort_by`, `order`, `page`, `limit` ≤ 50). Unknown keys → **422**.

### `GET /api/profiles/export?format=csv&...`

Streaming CSV with the **same filter/sort parameters** as list (no pagination). Filename includes timestamp.

### `GET /api/profiles/search?q=...&page=...&limit=...`

Rule-based NL parser on `q`; same list payload shape as **`GET /api/profiles`**. Uninterpretable query → **422** (`Unable to interpret query`).

### `GET /api/profiles/{uuid}`

Single profile.

### `POST /api/profiles`

**Admin only.** Body: `{ "name": "..." }`. Duplicate `name` returns existing profile **200**.

### `DELETE /api/profiles/{uuid}`

**Admin only.** **204** on success.

---

## Natural language parser

Implementation: `classify/nl_query.py` (countries: `classify/country_data.py`). Behaviour summarized below (unchanged in spirit from Stage 1).

1. **Normalize** the query: trim, lowercase, strip accents, replace punctuation with spaces, collapse whitespace.
2. **Countries**: longest-match against the **65** seed country names with **word boundaries** (`(?<!\w)…(?!\w)` on normalized tokens).
3. **Both genders**: phrases like `male and female` remove a single-gender filter; other cues still apply.
4. **One gender**: `male`/`men`/… → `male`; `female`/… → `female`.
5. **Age group words**: `child`/`teenager`/`adult`/`senior`/`elderly` → `age_group`; conflicts → unable to interpret.
6. **“young”**: ages **16–24**; intersects with explicit `min_age` / `max_age` if present.
7. **Numeric age**: `above N`, `below N`, etc. as documented previously in this section.
8. Filler words (`people`, `from`, `in`, …) optional if other cues exist.

### Supported examples (illustrative)

| Query (idea) | Parsed filters (conceptually) |
|--------------|--------------------------------|
| young males from nigeria | `gender=male`, `min_age=16`, `max_age=24`, `country_id=NG` |
| females above 30 | `gender=female`, `min_age=30` |
| people from angola | `country_id=AO` |
| adult males from kenya | `age_group=adult`, `gender=male`, `country_id=KE` |
| male and female teenagers above 17 | `age_group=teenager`, `min_age=17` |

### Limitations (parser)

- Country vocabulary = **countries in the seed** only.
- Short/ambiguous tokens may not map; spelling/slang/negation/OR unsupported; **“young”** is fixed 16–24; no NL-driven sort.

---

## Errors

| HTTP | When |
|------|------|
| 400 | Missing API version header (`/api/*`); missing/empty parameter |
| 401 | Missing/invalid/expired JWT |
| 403 | **Forbidden** (e.g. non-admin mutation) |
| 404 | Profile not found |
| 422 | Invalid query params; NL not interpretable; invalid body types |
| 429 | Rate limit exceeded |
| 502 | Upstream failure on profile aggregation |

Body shape (typical): `{ "status": "error", "message": "<string>" }`.

---

## Environment (see `.env.example`)

| Variable | Role |
|----------|------|
| `DJANGO_SECRET_KEY` | Django signing; use strong secret in production |
| `JWT_SIGNING_KEY` | Optional separate HS256 key for JWTs |
| `DATABASE_URL` | Postgres URL (omit for SQLite) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth |
| `BACKEND_PUBLIC_URL` | Public API base (OAuth callback URL) |
| `WEB_PORTAL_ORIGIN` | SPA origin (post-login redirect; CORS/CSRF) |
| `CORS_EXTRA_ORIGINS` | Optional extra allowed origins (comma-separated) |
| `INSIGHTA_CLI_OAUTH_REDIRECT` | Default CLI loopback redirect (CLI env) |
| `ACCESS_TOKEN_LIFETIME_SECONDS` / `REFRESH_TOKEN_LIFETIME_SECONDS` | JWT lifetimes |

---

## Deploy

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

Use **`DEBUG=False`**, strong secrets, **`ALLOWED_HOSTS`**, **`WEB_PORTAL_ORIGIN`** / **`BACKEND_PUBLIC_URL`** as HTTPS origins, and a production **`DATABASE_URL`**. Ensure **`CSRF_TRUSTED_ORIGINS`** and **`CORS_ALLOWED_ORIGINS`** include the real portal URL.
