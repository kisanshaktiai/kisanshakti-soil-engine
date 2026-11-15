# KisanShakti Soil Engine

Fetch soil predictions for registered-land integration, beginning with official
ISRIC SoilGrids REST and WCS. Dedicated repository:
https://github.com/kisanshaktiai/kisanshakti-soil-engine

Status: tested computational core and internal sampling diagnostic service;
the authenticated farmer fetch/job workflow is incomplete.
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
No database writer is included.

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
the future Edge route must verify the app session, accept only a land ID, check
ownership/tenant and load the canonical boundary from the database. The browser
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

## Remaining application work
Durable jobs/leased worker; authenticated, owner-checked Edge API; additive storage
and atomic report upserts; lab-data-preserving read contracts; frontend integration;
isolated staging deployment and registered-land end-to-end verification.
No production deployment is configured. Do not describe this core and diagnostic
service as the completed farmer-facing production system.

## Repository setup
The user-created GitHub repository is public. Only code, synthetic examples and
documentation belong here; never add credentials, real farmer boundaries, private
source reports or production exports. Work is isolated on a feature branch for
review. CI runs tests only and does not deploy or access Supabase.

## Provenance
Core extracted from local soil prototype commit 7b64c59 (2026-11-15).
SoilGrids-only provider functions were retained; unrelated NASA and centroid-only
Supabase importer functions and their tests were removed during extraction.
