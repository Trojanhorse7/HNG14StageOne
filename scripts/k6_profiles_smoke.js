/**
 * k6 load script for Insighta profiles list/search endpoints.
 *
 * Required env:
 *   TOKEN — JWT access (Bearer); optional alias ACCESS_TOKEN if TOKEN unset
 * Optional:
 *   REFRESH_TOKEN — opaque refresh from `issue_tokens` or CLI OAuth; POST /auth/refresh rotates pair
 *   BASE — origin, default http://127.0.0.1:8000
 *   SCENARIO — list | search | heavy (filter-heavy list)
 *   K6_PARALLEL_WITH_REFRESH=1 — allow multiple VUs while using REFRESH_TOKEN (unsafe: server rotates
 *     one refresh chain per user, so concurrent VUs sharing credentials break each other).
 *
 * Throttling: 60 requests/minute per authenticated user (same JWT user = one DRF bucket).
 * This script uses constant-arrival-rate well under that. Increase `rate` only if limits change.
 *
 * Examples:
 *   Bash: k6 run -e TOKEN="$(cat token.txt)" -e BASE="https://api.example.com" scripts/k6_profiles_smoke.js
 *   PowerShell: $env:TOKEN = 'jwt...'; $env:BASE = 'https://api.example.com'; k6 run scripts/k6_profiles_smoke.js
 *   k6 run -e TOKEN="..." -e REFRESH_TOKEN="..." -e SCENARIO="search" scripts/k6_profiles_smoke.js
 */

import http from "k6/http";
import { check, sleep } from "k6";

function trimEnv(name) {
  return String(__ENV[name] || "").trim();
}

const hasRefreshCred = trimEnv("REFRESH_TOKEN") !== "";
const forceParallelRefresh = trimEnv("K6_PARALLEL_WITH_REFRESH") === "1";

const LOAD_STEADY = {
  executor: "constant-arrival-rate",
  rate: 50,
  timeUnit: "1m",
  duration: "2m",
  preAllocatedVUs: hasRefreshCred && !forceParallelRefresh ? 1 : 5,
  maxVUs: hasRefreshCred && !forceParallelRefresh ? 1 : 15,
};

export const options = {
  scenarios: {
    steady: LOAD_STEADY,
  },

  // Uncomment to enforce SLA-style thresholds (non-zero exit if breached):
  // thresholds: {
  //   http_req_duration: ["p(50)<500", "p(95)<2000"],
  //   http_req_failed: ["rate<0.01"],
  // },
};

export function setup() {
  const access = trimEnv("TOKEN") || trimEnv("ACCESS_TOKEN");
  if (!access) {
    throw new Error(
      "Missing JWT access: export TOKEN=<access> or ACCESS_TOKEN=<access> (same value)"
    );
  }
}

/** Per-VU mutable tokens (each VU gets a copy seeded from env init). */
let accessJwt = trimEnv("TOKEN") || trimEnv("ACCESS_TOKEN");
let refreshOpaque = trimEnv("REFRESH_TOKEN");

const BASE = (trimEnv("BASE") || "http://127.0.0.1:8000").replace(/\/$/, "");
const SCENARIO = (trimEnv("SCENARIO") || "list").toLowerCase();

function targetUrl() {
  if (SCENARIO === "search") {
    return `${BASE}/api/profiles/search?q=male&page=1&limit=50`;
  }
  if (SCENARIO === "heavy") {
    return `${BASE}/api/profiles?country_id=NG&min_country_probability=0.5&page=1&limit=50`;
  }
  return `${BASE}/api/profiles?page=1&limit=50`;
}

function profilesGet() {
  return http.get(targetUrl(), {
    headers: {
      Authorization: `Bearer ${accessJwt}`,
      "X-API-Version": "1",
    },
    tags: { name: "Profiles" },
  });
}

/** POST /auth/refresh — rotation returns new access_token and refresh_token. */
function exchangeRefresh() {
  if (!refreshOpaque) {
    return false;
  }
  const url = `${BASE}/auth/refresh`;
  const res = http.post(
    url,
    JSON.stringify({ refresh_token: refreshOpaque }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { name: "AuthRefresh" },
    }
  );
  if (res.status !== 200) {
    console.error(
      `refresh HTTP ${res.status} — ${String(res.body || "").slice(0, 200)}`
    );
    return false;
  }
  let body;
  try {
    body = JSON.parse(res.body);
  } catch (_e) {
    console.error("refresh: response is not JSON");
    return false;
  }
  if (
    body.status !== "success" ||
    typeof body.access_token !== "string" ||
    typeof body.refresh_token !== "string"
  ) {
    console.error(`refresh: unexpected body ${JSON.stringify(body).slice(0, 200)}`);
    return false;
  }
  accessJwt = body.access_token;
  refreshOpaque = body.refresh_token;
  return true;
}

export default function () {
  let res = profilesGet();
  if (res.status === 401 && refreshOpaque && exchangeRefresh()) {
    res = profilesGet();
  }

  check(res, {
    "status 200": (r) => r.status === 200,
  });

  const bodyPreview = String(res.body || "").slice(0, 200);
  if (res.status !== 200) {
    console.error(`HTTP ${res.status} — ${bodyPreview}`);
  }

  sleep(0.05);
}
