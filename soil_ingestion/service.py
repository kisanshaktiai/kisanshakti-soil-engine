"""Internal sampling diagnostics only; not the farmer-facing fetch/job API."""
from contextlib import asynccontextmanager
import hmac
import json
import math
import os

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from shapely.errors import GEOSException

from .parcel import ALGORITHM, geometry
from .sampling import zigzag_plan

MAX_BODY_BYTES = 262_144
MAX_VERTICES = 4096


def validate_geometry_input(value):
    if not isinstance(value, dict) or set(value) != {'type', 'coordinates'}:
        raise ValueError('Expected a Polygon or MultiPolygon geometry')
    if value['type'] not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Expected a Polygon or MultiPolygon geometry')
    polygons = [value['coordinates']] if value['type'] == 'Polygon' else value['coordinates']
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('Empty polygon')
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError('Empty polygon')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('Rings must be closed with at least four coordinates')
            count += len(ring)
            if count > MAX_VERTICES:
                raise ValueError('Geometry exceeds vertex limit')
            for point in ring:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError('Expected longitude/latitude pairs')
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
                    raise ValueError('Coordinates must be finite numbers')
    return value


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        token = os.getenv('SOIL_INTERNAL_API_TOKEN', '')
        if len(token) < 32 or token != token.strip() or not token.isascii():
            raise RuntimeError('SOIL_INTERNAL_API_TOKEN must be a private ASCII token of at least 32 characters')
        app.state.internal_token = token
        yield
        app.state.internal_token = None

    app = FastAPI(title='KisanShakti Soil Engine', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/healthz')
    def health():
        return {'status': 'ok', 'algorithm_version': ALGORITHM,
                'mode': 'sampling_diagnostics', 'farmer_fetch_ready': False}

    @app.post('/v1/sampling-plan')
    async def sampling_plan(request: Request):
        expected = getattr(app.state, 'internal_token', None)
        if not expected:
            raise HTTPException(503, 'Service is not configured')
        auth = request.headers.get('authorization', '')
        if not hmac.compare_digest(auth.encode(), ('Bearer ' + expected).encode()):
            raise HTTPException(401, 'Internal authentication required')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'application/json required')
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, 'Request exceeds size limit')
            body.extend(chunk)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or set(payload) != {'geometry'}:
                raise ValueError('Only geometry is accepted by this diagnostic endpoint')
            geo = validate_geometry_input(payload['geometry'])
            def calculate():
                parcel, fingerprint = geometry(geo)
                return {'algorithm_version': ALGORITHM, 'geometry_fingerprint': fingerprint,
                        'area_m2': parcel.area, 'sampling': zigzag_plan(parcel)}
            return await run_in_threadpool(calculate)
        except (ValueError, TypeError, KeyError, OverflowError, GEOSException):
            raise HTTPException(422, 'Invalid or unsupported parcel geometry') from None

    return app


app = create_app()
