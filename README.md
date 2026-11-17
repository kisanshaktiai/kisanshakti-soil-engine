# KisanShakti Soil Engine

Fetch soil predictions for registered-land integration, beginning with official
ISRIC SoilGrids REST and WCS. Dedicated repository:
https://github.com/kisanshaktiai/kisanshakti-soil-engine

Status: computational core, internal diagnostics and durable fetch worker implemented.
The companion farmer-app PR supplies the Edge route, database RPCs and report UI.
Deployment and a staged live end-to-end check are still required.
No existing app, weather, NDVI, crop scheduling, NASA importers, credentials,
production migrations, farmer records or old repository history are included.

## Implemented
- Deterministic in-polygon zigzag positions: minimum 4, maximum 20.
- Count = clamp(floor(5 × sqrt(area in hectares)), 4, 20).
- Polygon holes, irregular parcels and distinct coordinate validation.
- Native-grid WCS retrieval, per-cell provenance and area-weighted parcel means.
- REST property adapter for diagnostics; duplicate pixels are not independent samples.
- Eight properties and three default depths (0–5, 5–15, 15–30 cm).
- Source/geometry/algorithm cache eligibility and six-calendar-month checks.
- Read-only diagnostic CLI, repeatable REST/WCS comparison and automated tests.
- Authenticated internal HTTP sampling-plan endpoint with request/vertex limits.
- Leased worker, progress heartbeats and atomic report completion through database RPCs.

## Local use
```sh
python -m venv .venv
# Activate .venv for your operating system.
python -m pip install -r requirements-service.txt
python -m pytest -q soil_ingestion/tests
python -m soil_ingestion.parcel_cli --geometry examples/parcel.geojson --source-version diagnostic-release-unverified --property phh2o --out report.json
```
The example is an illustrative polygon, not a registered farmer land. The CLI
retrieves pH at three depths and four statistics when --property phh2o is used.
Do not call the full request pipeline from a long-running browser request.

## Internal diagnostic service

Configure `SOIL_INTERNAL_API_TOKEN` through your local environment or your hosting
secret manager: a random ASCII secret of at least 32 characters, never a frontend
environment variable. Start locally with:

```sh
python -m uvicorn soil_ingestion.service:app --host 127.0.0.1 --port 8000
```

- `GET /healthz`: process health and explicit `farmer_fetch_ready: false`.
- `POST /v1/sampling-plan`: internal Bearer token required. JSON body:
  `{"geometry": <Polygon or MultiPolygon GeoJSON>}`. Returns validated area,
  geometry fingerprint and 4–20 distinct zigzag coordinates. No remote fetches
  or database writes occur. Rings must be closed; at most 4096 vertices and
  256 KiB per request. Unconfigured services refuse startup.

This endpoint is for trusted internal diagnostics. It is **not** the farmer API:
the companion Edge route verifies the app session, accepts only a land ID, checks
ownership/tenant and loads the canonical boundary from the database. The browser
must never receive this internal token. Use TLS and a bounded reverse proxy for
any non-local service; apply gateway rate limits before exposing it to operators.

## Repeatable live verification

```sh
python -m soil_ingestion.verify_live --lat 16.75 --lon 74.35 --out reports/kolhapur.json
```

This explicitly calls live providers. It compares the eight properties at three
depths (24 comparisons), retains raw source evidence and rejects comparisons when
the tiny synthetic comparison polygon crosses more than one native pixel.
Exit 0 means matched; exit 2 means failure or discrepancy. It does not certify
laboratory accuracy. `reports/` is git-ignored because reports contain coordinates.
CI uses fixtures and never consumes provider quotas or production credentials.

## Interpretation
SoilGrids values are model predictions, not laboratory soil tests. Total nitrogen
is not plant-available nitrogen. Available phosphorus/potassium are not fabricated.
All sampled point values are linked to source pixels. Area-weighted reports include
all intersecting raster pixels; the 20-position cap does not discard raster evidence.
Quantile spatial averages are not parcel confidence intervals. pH remains depth-specific.

## Release requirements
Apply the companion migration in an isolated database, start the worker on the
existing server, deploy the updated lands-api, then release the UI. Confirm a live
synthetic parcel fetch, saved report and ownership denial before production.
The code does not deploy itself or provision hosting.

## Repository setup
The user-created GitHub repository is public. Only code, synthetic examples and
documentation belong here; never add credentials, real farmer boundaries, private
source reports or production exports. Work is isolated on a feature branch for
review. CI runs tests only and does not deploy or access Supabase.

## Provenance
Core extracted from local soil prototype commit 7b64c59 (2026-11-15).
SoilGrids-only provider functions were retained; unrelated NASA and centroid-only
Supabase importer functions and their tests were removed during extraction.

## Farmer-request worker

`python -m soil_ingestion.worker` runs the durable fetch worker. It opens no public
port. The existing farmer-app `lands-api?action=soil` endpoint authenticates the
farmer, loads the registered boundary and enqueues an idempotent job. This worker
claims a leased job, fetches the full 4–20-position/native-pixel report, reports
actual layer progress, and atomically commits report evidence and completion.

Apply the companion farmer-app migration `20261116085603_soil_fetch_jobs.sql`
first. For the existing server, copy `.env.example` to `.env`, populate the target
project URL, server-only service-role key and operator-verified source version,
then run `docker compose up -d --build`. Never put this key in the farmer app.
Use a dedicated server account and keep `.env` readable only by that account.

Readiness is a database heartbeat every 20 seconds; the app refuses new work when
no worker has checked in within two minutes. A lost worker's job can be reclaimed
after its ten-minute lease expires, up to three attempts. A stale worker cannot
finish another worker's lease. SIGTERM stops claiming new work; interrupted jobs
recover through the lease. Do not run more workers than the provider quota permits.

Full depth, source, units, sample and native-pixel evidence is saved in
`soil_parcel_reports`. Only a complete 0–5 cm compatibility summary is projected
into `soil_health`, and only if there is no manual or laboratory row for that land.
Total nitrogen stays in the full report in g/kg; available N/P/K are not invented.
The app reads through the owner-checked backend. Database rows remain service-only.

Deploy order: isolated database migration → worker container → lands-api → farmer
UI. Verify one synthetic parcel in staging before applying production changes.
The container and code do not provision or access an existing server by themselves.

## No-server deployment: GitHub Actions (recommended)

The `.github/workflows/soil-on-demand.yml` workflow runs short-lived GitHub-hosted
workers. The database queue remains durable and authoritative. A farmer's request
is enqueued by the companion `lands-api`, which dispatches the workflow through
GitHub's authenticated REST API. Scheduled runs every 15 minutes attempt to
recover requests when API dispatch is unavailable or a runner exits unexpectedly.
Scheduled invocations are best-effort and may be delayed by GitHub.

**Enable only after both review PRs are merged and the database migration is applied:**

1. In this repository's GitHub **Settings → Environments**, create `soil-worker`.
   Add environment **secrets** `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
   Add environment **variable** `SOILGRIDS_SOURCE_VERSION`. Verify the release
   identifier against your actual provider, and use the same exact version in
   the Supabase Edge Function. Do not store real farmer coordinates in GitHub logs.
2. In the farmer-app's Supabase Edge Function secrets, configure
   `SOILGRIDS_SOURCE_VERSION` and `SOIL_GITHUB_DISPATCH_TOKEN`. The GitHub token
   must be fine-grained, restricted to this repo with Actions **write** permission,
   and protected by the Edge Function; never send it to frontend code.
3. Apply the companion migration `20261116230500_soil_github_actions_queue.sql`
   and deploy the updated `lands-api` from the farmer-app branch only after
   reviewing and testing in staging. It replaces the permanent-worker heartbeat
   gate without changing the RPC names.
4. The workflow runs from `main` after merge. For a controlled staging test,
   click **Actions → On-demand SoilGrids processing → Run workflow** using an
   isolated Supabase test project. Confirm one queued synthetic parcel job
   completes, inspect the saved JSON report and ensure an unrelated lab row
   is not overwritten.
5. After staging validation, configure production secrets. Avoid manual
   Run workflow against production until reviewed and explicitly authorized.

Each run processes at most eight jobs (a manual **Run workflow** may set `max_jobs`
up to 100 for a one-time backfill), targeting 40 minutes of work and with a
60-minute GitHub job timeout. A running fetch may exceed the soft 40-minute
target; interrupted jobs are retried through the database lease. The original
`docker compose` path remains available as an optional operator alternative,
but is not required for the GitHub Actions architecture.

**Important operational limits:** Workflow dispatch is best-effort and GitHub
runner startup is not immediate. Free GitHub-hosted runner usage is subject to
GitHub's published plan and usage limits. ISRIC WCS availability and quotas are
also external dependencies. Do not confuse SoilGrids modelled properties with
laboratory measurements. This workflow is not a real-time HTTP soil-analysis API.

**Dispatch is the primary trigger.** GitHub delays scheduled runs under load and
disables scheduled workflows in public repositories after 60 days without repository
activity, so the 15-minute schedule is only a backup. Keep `SOIL_GITHUB_DISPATCH_TOKEN`
configured and renewed before expiry; `lands-api` also re-dispatches a job that has
waited more than two minutes, or whose lease expired, while the farmer's page is open.
