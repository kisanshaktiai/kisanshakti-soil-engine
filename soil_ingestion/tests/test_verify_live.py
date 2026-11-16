import pytest
from soil_ingestion.verify_live import compare


def evidence(value=6.8, pixels=1):
    rest={'type':'Feature','properties':{'layers':[{'name':'phh2o','depths':[
        {'label':'0-5cm','range':{'top_depth':0,'bottom_depth':5,'unit_depth':'cm'},'values':{'mean':68}}
    ]}]}}
    wcs={'requested_properties':['phh2o'],'requested_depths':['0-5cm'],
         'properties':{'phh2o':{'0-5cm':{'mean':value,'distinct_pixels':pixels,'quality':'complete'}}}}
    return rest,wcs


def test_matching_values():
    assert compare(*evidence())[0]['matched'] is True


def test_provider_discrepancy_not_hidden():
    r=compare(*evidence(6.7))[0]
    assert r['matched'] is False
    assert r['difference']==pytest.approx(-.1)


def test_cannot_compare_point_with_multi_pixel_parcel():
    with pytest.raises(ValueError,match='one valid source pixel'):
        compare(*evidence(pixels=2))
