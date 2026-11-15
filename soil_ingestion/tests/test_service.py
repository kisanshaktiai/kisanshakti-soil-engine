import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from soil_ingestion.service import create_app, MAX_BODY_BYTES, validate_geometry_input

TOKEN='test-only-internal-token-01234567890123456789'
GEO=json.loads((Path(__file__).parents[2]/'examples'/'parcel.geojson').read_text())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('SOIL_INTERNAL_API_TOKEN',TOKEN)
    with TestClient(create_app()) as client:
        yield client


def test_missing_secret_prevents_start(monkeypatch):
    monkeypatch.delenv('SOIL_INTERNAL_API_TOKEN',raising=False)
    with pytest.raises(RuntimeError,match='SOIL_INTERNAL_API_TOKEN'):
        with TestClient(create_app()): pass


def test_health_is_not_a_false_farmer_readiness_claim(client):
    response=client.get('/healthz')
    assert response.status_code==200
    assert response.json()['farmer_fetch_ready'] is False


@pytest.mark.parametrize('auth',['','Bearer wrong','Basic credentials'])
def test_unauthorized_requests_rejected_before_geometry(client,auth):
    assert client.post('/v1/sampling-plan',json={'geometry':GEO},headers={'authorization':auth}).status_code==401


def test_valid_plan_returns_ten_distinct_points_and_stable_fingerprint(client):
    headers={'authorization':'Bearer '+TOKEN}
    a=client.post('/v1/sampling-plan',json={'geometry':GEO},headers=headers)
    b=client.post('/v1/sampling-plan',json={'geometry':GEO},headers=headers)
    assert a.status_code==200 and a.json()==b.json()
    points=a.json()['sampling']['points']
    assert len(points)==10
    assert len({(p['lon'],p['lat']) for p in points})==10


@pytest.mark.parametrize('payload',[{}, {'geometry':{'type':'Point','coordinates':[74,16]}}, {'geometry':GEO,'farmer_id':'spoof'}])
def test_malformed_or_spoofed_context_rejected(client,payload):
    response=client.post('/v1/sampling-plan',json=payload,headers={'authorization':'Bearer '+TOKEN})
    assert response.status_code==422


def test_body_size_limit(client):
    response=client.post('/v1/sampling-plan',content=' '* (MAX_BODY_BYTES+1),
                         headers={'authorization':'Bearer '+TOKEN,'content-type':'application/json'})
    assert response.status_code==413


def test_json_content_type_required(client):
    assert client.post('/v1/sampling-plan',content='{}',headers={'authorization':'Bearer '+TOKEN}).status_code==415


def test_vertex_limit_rejects_excessive_geometry():
    geo=copy.deepcopy(GEO)
    geo['coordinates'][0]=geo['coordinates'][0]*1025
    with pytest.raises(ValueError,match='vertex limit'):validate_geometry_input(geo)


def test_unclosed_rings_rejected():
    geo=copy.deepcopy(GEO)
    geo['coordinates'][0][-1]=[74.349,16.75]
    with pytest.raises(ValueError,match='closed'):validate_geometry_input(geo)
