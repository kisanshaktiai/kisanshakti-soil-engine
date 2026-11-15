# KisanShakti Soil Engine

Dedicated SoilGrids parcel-prediction codebase, extracted from the soil prototype.
Status: tested computational core; the authenticated farmer workflow is incomplete.
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
- Read-only diagnostic CLI and automated tests. No database writer is included.

## Local use
```sh
python -m venv .venv
# Activate .venv for your operating system.
python -m pip install -r requirements.txt
python -m pytest -q soil_ingestion/tests
python -m soil_ingestion.parcel_cli --geometry examples/parcel.geojson --source-version diagnostic-release-unverified --property phh2o --out report.json
```
The example is an illustrative polygon, not a registered farmer land. The CLI
retrieves pH at three depths and four statistics when --property phh2o is used.
Do not call the full request pipeline from a long-running browser request.

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
No web service or production deployment is configured. Do not describe this core
as the completed production system.

## Repository setup
Suggested GitHub name: kisanshaktiai/kisanshakti-soil-engine. Use private visibility.
The provided project is initialized locally; the remote GitHub repository has not
been created. After creating an empty repository, set its verified URL as origin
and push main. CI runs tests only and does not deploy or access Supabase.

## Provenance
Core extracted from local soil prototype commit 7b64c59 (2026-11-15).
SoilGrids-only provider functions were retained; unrelated NASA and centroid-only
Supabase importer functions and their tests were removed during extraction.
