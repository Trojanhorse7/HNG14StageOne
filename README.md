# Insighta Labs — demographic profiles API (HNG Stage 1)

Django + Django REST Framework service with a `Profile` model (`UUID` v7 primary keys), PostgreSQL or SQLite, open CORS for grading scripts, and rule-based natural-language search (no LLMs).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Set `DATABASE_URL` (PostgreSQL) in `.env`, or leave it unset to use `db.sqlite3` in the project root. See [`.env.example`](.env.example) for the variables this project reads.

```bash
python manage.py migrate
python manage.py seed_profiles
python manage.py runserver 0.0.0.0:8000
```

`seed_profiles` reads `seed_profiles.json` at the project root. Re-running it **updates** existing rows by unique `name` and does **not** create duplicates.

**Postgres performance:** seeding uses multi-row `INSERT` / `UPDATE` in batches. Default batch size is **250** (about nine statements for ~2k rows). Tune for your host:

- `SEED_POSTGRES_BATCH=500` in the environment, or
- `python manage.py seed_profiles --batch 500`

If a batch hits `statement_timeout`, the command halves the batch size and retries (same as before). Use a smaller `SEED_POSTGRES_BATCH` (e.g. 32) only on very strict serverless Postgres tiers.

## Endpoints

### `GET /api/classify?name=...`

Legacy name-classification proxy (Genderize). Response format unchanged from the earlier stage.

### `GET /api/profiles`

List profiles with **filters**, **sorting**, and **pagination** in one request.

**Query parameters (all optional; unknown parameters return 422 with `Invalid query parameters`):**

| Parameter | Effect |
|-----------|--------|
| `gender` | Exact match (`male` / `female`) |
| `age_group` | `child`, `teenager`, `adult`, `senior` |
| `country_id` | Two-letter ISO code (e.g. `NG`) |
| `min_age`, `max_age` | Inclusive age bounds |
| `min_gender_probability`, `min_country_probability` | Lower bound (float) |
| `sort_by` | `age` \| `created_at` \| `gender_probability` (default: `created_at`) |
| `order` | `asc` \| `desc` (default: `desc`) |
| `page` | 1-based (default: `1`) |
| `limit` | Page size (default: `10`, max: `50`) |

**Success (200):**

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "data": [ { "id", "name", "gender", "gender_probability", "age", "age_group", "country_id", "country_name", "country_probability", "created_at" } ]
}
```

`created_at` is UTC, ISO 8601 with `Z`.

### `GET /api/profiles/search?q=...&page=...&limit=...`

Runs the **rule-based** parser on `q`, applies the result as the same filters as `GET /api/profiles`, and returns the same list payload. Pagination defaults match the list route.

If the string cannot be mapped to at least one filter, the response is **422** with:

```json
{ "status": "error", "message": "Unable to interpret query" }
```

If `q` is missing or empty: **400** with `Missing or empty parameter`.

### `GET /api/profiles/{uuid}` / `DELETE /api/profiles/{uuid}`

Single-profile read and delete.

### `POST /api/profiles`

Create a profile by aggregating live Genderize / Agify / Nationalize (unchanged). Duplicate `name` returns the existing profile with 200.

## Natural language parser — approach

Implementation: `classify/nl_query.py` (and country names: `classify/country_data.py`).

1. **Normalize** the query: trim, lowercase, strip accents, replace punctuation with spaces, collapse whitespace.
2. **Countries**: For each of the 65 names in the seed’s country list, match the **longest** country name first (so “Niger” is not taken from “Nigeria”, “Guinea” after “Equatorial Guinea”, etc.). A match requires the full normalized country phrase to appear in the text with **word boundaries** (regex `(?<!\w)…(?!\w)` on normalized tokens).
3. **Both genders**: Phrases like `male and female` / `men and women` (either order) remove a single-gender filter; remaining words still apply (e.g. `male and female teenagers above 17` → `age_group=teenager` + `min_age=17`, no `gender`).
4. **One gender**: `male` / `males` / `man` / `men` → `gender=male`; `female` / `females` / `woman` / `women` → `gender=female` (written so `female` is not misparsed as `male`).
5. **Age group words**: `child`/`children`, `teenager`/`teenagers`, `adult`/`adults`, `senior`/`seniors`, `elderly` map to the stored `age_group`. Conflicting two different groups in one query returns “unable to interpret.”
6. **“young”** (not a stored `age_group`): sets inclusive ages **16–24**; intersects with any other `min_age` / `max_age` from the same query (e.g. `above` / `below`).
7. **Numeric age**: `above N`, `over N`, `older than N`, `N+`, `at least N` → `min_age = N`. `below N`, `under N`, `younger than N`, `at most N` → `max_age = N-1` (inclusive end age so “below 30” matches ages ≤ 29).
8. Filler words (`people`, `from`, `in`, …) are stripped for parsing but are not required for a valid query if other cues exist.

The parsed result is a small dict of filter fields passed into the same `apply_filters` helper used by `GET /api/profiles` (and the query is sorted by `created_at` `desc` with stable tie-break on `id`).

### Supported examples (illustrative)

| Query (idea) | Parsed filters (conceptually) |
|--------------|------------------------------|
| young males from nigeria | `gender=male`, `min_age=16`, `max_age=24`, `country_id=NG` |
| females above 30 | `gender=female`, `min_age=30` |
| people from angola | `country_id=AO` |
| adult males from kenya | `age_group=adult`, `gender=male`, `country_id=KE` |
| male and female teenagers above 17 | `age_group=teenager`, `min_age=17` |

## Limitations and edge cases (parser)

- **Country vocabulary** is the **65 countries present in the seed** (`country_data.py`). Any ISO country not in that set cannot be resolved by name.
- **Short or ambiguous** country tokens (e.g. a lone “Congo” when multiple “Congo”-related names exist) may not map reliably; prefer full phrases such as “DR Congo” or “Republic of the Congo” as in the seed names.
- **Spelling, slang, and languages** other than a loose English keyword set are not supported.
- **“young”** is **always 16–24** for this layer; it does not set `age_group` and may intersect oddly with an explicit `age_group` in the same sentence (e.g. “young seniors” is rejected as an impossible age intersection).
- **No negation** (“not from Kenya”), **no OR** between countries, and **no sorting** in natural language; search uses default sort only.
- **Punctuation and typos** that break word boundaries or country phrases may cause “unable to interpret” even if a human would guess the intent.

## Errors

| HTTP | When |
|------|------|
| 400 | Missing / empty required parameter (e.g. `q` on search) |
| 422 | Invalid types or unknown query parameters; or NL query that cannot be interpreted |
| 404 | Profile ID not found |
| 502 | Upstream APIs failed on `POST` aggregate |

Body shape: `{ "status": "error", "message": "<string>" }`.

## CORS

`django-cors-headers` is enabled with `CORS_ALLOW_ALL_ORIGINS = True`, so responses include `Access-Control-Allow-Origin: *` for browser-based checks.

## Deploy

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

Set `DEBUG=False`, `DJANGO_SECRET_KEY`, and (for production) `ALLOWED_HOSTS` via the environment as appropriate.
