# Stage 4B — Performance, canonical cache keys, CSV import

Scope matches the assignment: **same product API** for reads (plus the required **bulk import** endpoint), **no extra database products**, **no horizontal scaling**. Work focuses on PostgreSQL indexing, Django **DatabaseCache** for hot list/search reads, deterministic **canonical filter** strings for keys, and **streaming + batched** CSV ingestion.

---

## 1. Query performance (PostgreSQL)

### Indexes

| Change | Purpose |
|--------|---------|
| **`country_probability` with `db_index=True`** | Speeds predicates that bound probability (when the planner uses the btree). |
| **Composite index on `(-created_at, -id)`** | Aligns with default list ordering to cut sort cost on large pages when the planner uses it. |

**Migration:** `classify/migrations/0003_profile_perf_indexes.py`

### Application cache

| Change | Purpose |
|--------|---------|
| **Cache hits before ORM for successful list/search payloads** | Cuts redundant DB work for repeated identical queries (same TTL window). |
| **TTL ~90s** (`settings.CACHES["default"]["TIMEOUT"]`) | Bounded staleness without manual per-key eviction. |
| **Generation bump** (`bump_profile_query_cache_generation`) after creates, deletes, successful import end | Ensures mutations do not stick behind a long TTL. |

PostgreSQL uses **`django.core.cache.backends.db.DatabaseCache`** with table **`django_cache`** (**`python manage.py createcachetable django_cache`** once). SQLite dev/tests use **`LocMemCache`** (process-local).

### Connection handling

**`DATABASES["default"]["CONN_MAX_AGE"] = 60`** reuses TCP connections across requests (lightweight pooling behavior without PgBouncer).

### Constraints from the brief (how this repo complies)

| Constraint | Approach |
|------------|----------|
| No new database systems | Only Postgres + Django’s DB cache table on that same Postgres. |
| No horizontal scaling | Single-app scaling levers only (indexes, cache, batches, pooling). |
| API unchanged | List, search, export, classify behavior unchanged; import is additive per CSV section. |

### Trade-offs (brief asks for justification)

| Choice | Upside | Cost / risk |
|--------|--------|----------------|
| Indexes | Faster read paths the planner selects | Writes and imports pay small extra index maintenance. |
| Short TTL cache | Simple correctness window; workers share Postgres cache table | Cold traffic still pays full DB until warm. |
| Generation counter in key | No need to delete many cache keys on write | One cache read per request for generation. |
| Import + read on same DB | Operationally simple | Large imports still add load; mitigated by batching, not eliminated. |

---

## 2. Query normalization and cache efficiency

**Module:** `classify/filter_canonical.py`

| Piece | Behavior |
|-------|----------|
| **`canonical_filters(filters)`** | Builds a **sorted-key** JSON string with **normalized** scalars (e.g. gender/age_group lowercased, `country_id` ISO2, probabilities rounded) so equivalent filter dicts stringify the same. |
| **`profile_list_search_cache_key(...)`** | Hashes `v1`, **kind** (`list` vs `search`), canonical JSON, page, limit, sort, order, and **generation**. |

**Deterministic, no LLMs:** Normalization only changes representation; it does not infer new semantics. **Note:** two different English queries only share a cache entry if **`parse_nl_query`** and list params produce the **same** filter dict (e.g. ages as `min_age`/`max_age` vs only `age_group` are different filters by design).

---

## 3. CSV ingestion

**Route:** `POST /api/profiles/import` (admin, multipart field **`file`**).

| Requirement | Implementation |
|-------------|----------------|
| Streamed parsing | **`TextIOWrapper` + `csv.reader`** over the uploaded file stream. |
| Not row-at-a-time inserts (happy path) | **`bulk_create`** in batches of **2000**. |
| No single string of whole file | Rows processed incrementally from the reader. |
| Partial success / no full rollback | Each batch commits; earlier batches persist if later rows fail validation. |
| Summary response | **`status`, `total_rows`, `inserted`, `skipped`, `reasons`** map. |

**Concurrency / races:** Duplicate names checked per batch plus DB; **`IntegrityError`** on **`bulk_create`** falls back to **per-row** `save(force_insert=True)` so rare races still resolve without failing the batch (called out here because it is the only non-bulk persistence path).

**Large files:** Tune **`DATA_UPLOAD_MAX_MEMORY_SIZE`** / host limits if CSVs approach hundreds of MB.

---

## 4. Measuring latency

Replace placeholders with numbers from **your** production (or staging) environment. Record:

- Approximate **`Profile` row count** when measured.
- **App server shape** (e.g. Gunicorn workers — not Django `runserver` for finals).
- **Tool version** (`k6 version`).

### Recommended: **k6** (percentiles in the summary line)

#### Install

| OS | Command / link |
|----|----------------|
| Windows (winget) | Run `winget search k6` — install the **Id** shown (often **`GrafanaLabs.k6`**): `winget install GrafanaLabs.k6 -e`. If nothing appears, run `winget source update` (or reset sources per [Microsoft winget docs](https://learn.microsoft.com/windows/package-manager/winget/troubleshooting)). |
| Windows (no winget) | Download **`k6-*-windows-amd64.zip`** from [k6 releases](https://github.com/grafana/k6/releases), extract `k6.exe`, add its folder to **PATH**. |
| macOS | `brew install k6` |

Verify: `k6 version`

#### Get a JWT

From the repo (local or any env with Django):

```bash
python manage.py issue_tokens YOUR_GITHUB_USERNAME
```

Copy the printed **`access_token`**. **Long scripted runs**: also copy **`refresh_token`** into k6 as **`REFRESH_TOKEN`** so **`POST /auth/refresh`** can rotate both when **`GET /api/...`** returns **401**.

#### Run against your API **origin** (`BASE`)

This repo ships **`scripts/k6_profiles_smoke.js`**. **`TOKEN`** carries the JWT access value; **`REFRESH_TOKEN`** is optional opaque refresh (`issue_tokens` prints both). With refresh set, the script runs **one VU** by default (the API **rotates** refresh on each call, so parallel VUs sharing one pair invalidate each other's chain). **`K6_PARALLEL_WITH_REFRESH=1`** turns multi-VU back on — only for experimentation.

Examples — **Git Bash** and **PowerShell** (prefer **single quotes** around JWTs so nothing is interpolated).

**Git Bash:**

**Default list** (steady **~50 req/min × 2m** — one JWT shares **60/minute** throttle; exceeding it yields **429** and failed `status 200` checks):

```bash
cd /path/to/STAGE_ONE
export TOKEN="paste_jwt_access_here"
export REFRESH_TOKEN="opaque_refresh_if_long_run_optional"
export BASE="https://your-api.example.com"   # no trailing slash
k6 run -e TOKEN -e REFRESH_TOKEN -e BASE scripts/k6_profiles_smoke.js
```

**PowerShell (Windows)** — JWT must be one continuous string (three segments separated by **`.`**). If **`issue_tokens`** wraps output, paste the entire token on one line.

```powershell
Set-Location C:\path\to\STAGE_ONE
$env:TOKEN = 'paste_full_jwt_access_here'
$env:REFRESH_TOKEN = 'opaque_refresh_if_long_run_optional'  # omit line if unused
$env:BASE = 'https://your-api.example.com'
k6 run -e TOKEN -e REFRESH_TOKEN -e BASE scripts/k6_profiles_smoke.js
```

**Or** omit **`-e`** entries and inherit the shell session (**`TOKEN`** etc. already set on **`$env:`**):

```powershell
k6 run scripts/k6_profiles_smoke.js
```

**Search scenario:**

```bash
k6 run -e TOKEN -e BASE -e SCENARIO="search" scripts/k6_profiles_smoke.js
```

```powershell
$env:SCENARIO = 'search'
k6 run -e TOKEN -e BASE scripts/k6_profiles_smoke.js
```

**Filter-heavy list:**

```bash
k6 run -e TOKEN -e BASE -e SCENARIO="heavy" scripts/k6_profiles_smoke.js
```

```powershell
$env:SCENARIO = 'heavy'
k6 run -e TOKEN -e BASE scripts/k6_profiles_smoke.js
```

Read the **`http_req_duration`** line at the end: **`med`** is ~**p50**, **`p(95)`** is **p95**. To fail the script when breaching SLA, uncomment **`thresholds`** inside `scripts/k6_profiles_smoke.js`.

Optional quick check (**hey**):

```bash
hey -n 200 -c 10 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Version: 1" \
  "${BASE}/api/profiles?page=1&limit=50"
```

(hey prints some percentiles but k6 is clearer for **p95**. High **`hey -c`** with one token hits the same **60/min** cap and mostly **429**.)

### Results table — **paste your measured values**

_Assignment target: comfortably sub-500 ms median and sub-2 s p95 where the stack allows; depends on dataset, region, and plan._

| Scenario | Tool | k6 load shape | Profile rows (approx) | p50 (ms) | p95 (ms) | Notes |
|----------|------|----------------|-------------------------|-----------|-----------|-------|
| `GET /api/profiles?page=1&limit=50` default sort | k6 `SCENARIO=list` | ~50 iter/min × 2m (`constant-arrival-rate`) | | | | Same script for all scenarios; respects per-user throttle. |
| Heavy filter (`country_id` + `min_country_probability`) | k6 `SCENARIO=heavy` | ditto | | | | |
| `GET /api/profiles/search?...` | k6 `SCENARIO=search` | ditto | | | | |

_Add optional “before optimization” runs only if you still have git history / an old deployment to compare._

---

## 5. Automated tests & CI

- **`classify/tests/test_profile_cache_import.py`**: canonical filter equality; **list** vs **search** cache buckets differ for same JSON; CSV duplicate-name within file; analyst **403** on import.
- **CI:** SQLite job runs **`migrate`**; Postgres job runs **`migrate`** then **`createcachetable django_cache`** before **`manage.py test`**.

Local SQLite-only tests:

```bash
DATABASE_URL="" python manage.py test classify.tests.test_profile_cache_import -v 2
```

---

## 6. Migration ledger (corner case)

If a database already ran an older **`0003_…`** classify migration leaf and Django reports it missing after a pull, align **`django_migrations.name`** with **`0003_profile_perf_indexes`** for that row, **or** use a fresh database. Fresh installs only need **`migrate`**.
