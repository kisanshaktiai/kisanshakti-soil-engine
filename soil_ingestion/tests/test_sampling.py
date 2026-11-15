import math
import pytest
from shapely.geometry import box, Polygon, MultiPolygon, Point
from soil_ingestion.sampling import sample_count, zigzag_plan
from soil_ingestion import parcel as engine
from soil_ingestion.tests.test_parcel import tiff


@pytest.mark.parametrize('hectares,count',[(.01,4),(.1,4),(.5,4),(1,5),(2,7),(4,10),(9,15),(16,20),(100,20)])
def test_area_policy(hectares,count):
    assert sample_count(hectares*10000)==count


@pytest.mark.parametrize('bad',[0,-1,float('nan'),float('inf'),True,None])
def test_invalid_area(bad):
    with pytest.raises(ValueError): sample_count(bad)


@pytest.mark.parametrize('field',[
    box(0,0,20,20), box(0,0,100,100), box(0,0,400,400),
    box(0,0,1000,1), box(0,0,1,1000),
    Polygon([(0,0),(300,0),(300,300),(200,300),(200,100),(100,100),(100,300),(0,300)]),
    Polygon([(0,0),(500,0),(500,500),(0,500)],holes=[[(100,100),(400,100),(400,400),(100,400)]]),
    MultiPolygon([box(0,0,100,100),box(200,200,350,350)]),
])
def test_distinct_inside_equal_area_and_zigzag(field):
    plan=zigzag_plan(field)
    assert plan==zigzag_plan(field.reverse())
    pts=plan['points']
    assert len(pts)==sample_count(field.area)
    assert len({(p['x_m'],p['y_m']) for p in pts})==len(pts)
    assert all(field.contains(Point(p['x_m'],p['y_m'])) for p in pts)
    assert sum(p['stratum_area_m2'] for p in pts)==pytest.approx(field.area)
    assert all(p['stratum_area_m2']==pytest.approx(field.area/len(pts),rel=1e-6) for p in pts)
    for row in range(plan['rows']):
        xs=[p['x_m'] for p in pts if p['row']==row]
        assert xs==sorted(xs,reverse=bool(row%2))


def test_four_positions_one_pixel_do_not_multiply_values_or_requests(monkeypatch):
    field=box(10,260,100,310)
    calls=[]
    monkeypatch.setattr(engine,'geometry',lambda geo:(field,'fingerprint'))
    def fetch(*args,**kwargs):
        calls.append(1)
        return tiff([[60,80],[70,90]])
    monkeypatch.setattr(engine,'get_bounded',fetch)
    report=engine.fetch_parcel({},source_version='test',properties=['phh2o'],depths=['0-5cm'],statistics=['mean'])
    v=report['properties']['phh2o']['0-5cm']
    assert len(calls)==1
    assert report['sampling']['generated_points']==4
    assert report['sampling']['distinct_sample_pixels']==1
    assert v['distinct_pixels']==1 and v['generated_points']==4
    assert len(v['evidence']['mean']['sample_values'])==4
    assert v['mean']==6 and v['spatial_std'] is None


def test_twenty_point_cap_does_not_drop_raster_coverage(monkeypatch):
    field=box(0,0,2000,2000)
    monkeypatch.setattr(engine,'geometry',lambda geo:(field,'fingerprint'))
    # Synthetic evidence representing 64 native pixels; correct location IDs.
    cells=[{'pixel_id':f'igh:{x:.3f}:{y:.3f}:250','area_m2':62500,
            'raw_value':60,'value':6.,'unit':'pH'}
           for x in range(0,2000,250) for y in range(250,2001,250)]
    monkeypatch.setattr(engine,'get_bounded',lambda *args,**kwargs:b'fixture')
    monkeypatch.setattr(engine,'cells_from_tiff',lambda *args:cells)
    report=engine.fetch_parcel({},source_version='test',properties=['phh2o'],depths=['0-5cm'],statistics=['mean'])
    v=report['properties']['phh2o']['0-5cm']
    assert report['sampling']['generated_points']==20
    assert len(v['evidence']['mean']['sample_values'])==20
    assert v['distinct_pixels']==64 and v['coverage_fraction']==1
    assert v['mean']==6
