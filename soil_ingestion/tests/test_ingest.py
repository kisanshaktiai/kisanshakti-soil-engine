import pytest
from soil_ingestion.ingest import valid_coords, finite_value, record, soilgrids_tiff_pixel, get_soilgrids

class Response:
    def __init__(self,data=None,content=b"",url="https://example.org"):
        self._data=data
        self.content=content
        self.url=url
    def raise_for_status(self):pass
    def json(self):return self._data


class Session:
    def __init__(self,responses):
        self.responses=list(responses)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(("get",url,kwargs))
        return self.responses.pop(0)
    def post(self,url,**kwargs):
        self.calls.append(("post",url,kwargs))
        return self.responses.pop(0)


@pytest.mark.parametrize("lat,lon",[(91,77),(10,190),(float("nan"),70),(True,70)])
def test_invalid_coordinates(lat,lon):
    with pytest.raises(ValueError):valid_coords(lat,lon)


def test_valid_ranges_and_missing():
    assert finite_value(-999,0,1) is None
    assert finite_value(1.2,0,1) is None
    assert finite_value("0.65",0,1)==0.65


def test_provider_units_restricted():
    with pytest.raises(ValueError):record("NASA_POWER","soil_moisture_surface","m3/m3",0.3,
          statistic="daily",reference="https://example.org",metadata={})


def tiff(raw=65,nodata=-32768):
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    with MemoryFile() as mem:
        with mem.open(driver="GTiff",height=10,width=10,count=1,
            dtype="int16",crs="EPSG:4326",nodata=nodata,
            transform=from_origin(73.85,18.53,.001,.001)) as ds:
            ds.write(np.full((10,10),raw,dtype="int16"),1)
        return mem.read()


def test_soilgrids_pixel_and_ph_conversion():
    assert soilgrids_tiff_pixel(tiff(),18.525,73.855)==65
    s=Session([Response(content=tiff(),url="https://maps.isric.org/test")])
    r=get_soilgrids(s,18.525,73.855,statistics=("Q0.5",),properties=("phh2o",))
    assert len(r)==1
    assert r[0]["value"]==6.5 and r[0]["unit"]=="pH"
    assert r[0]["observed_at"] is None
    assert r[0]["source_metadata"]["coverage_id"]=="phh2o_0-5cm_Q0.5"


def test_all_zero_wcs_fail_closed():
    with pytest.raises(ValueError,match="all-zero"):
        soilgrids_tiff_pixel(tiff(0,nodata=None),18.525,73.855)


def test_nodata_soilgrids_fail_closed():
    with pytest.raises(ValueError,match="no valid pixels"):
        soilgrids_tiff_pixel(tiff(-32768),18.525,73.855)


def test_wcs_xml_not_tiff():
    with pytest.raises(ValueError,match="non-TIFF"):
        soilgrids_tiff_pixel(b"<ExceptionReport/>",18.525,73.855)


def test_no_available_npk_outputs():
    from soil_ingestion.ingest import ALLOWED
    assert not any("available" in key for values in ALLOWED.values() for key in values)


def test_rest_properties_are_scaled_and_source_labelled():
    from soil_ingestion.ingest import parse_soilgrids_rest
    data={"type":"Feature","properties":{"layers":[
      {"name":"phh2o","unit_measure":{"d_factor":10},
       "depths":[{"range":{"top_depth":0,"bottom_depth":5,"unit_depth":"cm"},
                  "label":"0-5cm","values":{"Q0.05":59,"Q0.5":65,"Q0.95":73}}]}
    ]}}
    rows=parse_soilgrids_rest(data,properties=("phh2o",))
    assert [r["value"] for r in rows]==[5.9,6.5,7.3]
    assert all(r["source_metadata"]["ingestion_transport"]=="REST" for r in rows)
    assert all(r["unit"]=="pH" for r in rows)
    assert all(r["observed_at"] is None for r in rows)


def test_rest_null_is_not_fabricated():
    from soil_ingestion.ingest import parse_soilgrids_rest
    data={"type":"Feature","properties":{"layers":[
      {"name":"phh2o","depths":[{"range":{"top_depth":0,"bottom_depth":5,"unit_depth":"cm"},
                  "label":"0-5cm","values":{"Q0.5":None}}]}
    ]}}
    with pytest.raises(ValueError,match="null value"):
        parse_soilgrids_rest(data,statistics=("Q0.5",),properties=("phh2o",))


def test_rest_rejects_inconsistent_depth():
    from soil_ingestion.ingest import parse_soilgrids_rest
    data={"type":"Feature","properties":{"layers":[
      {"name":"phh2o","depths":[{"range":{"top_depth":10,"bottom_depth":15,"unit_depth":"cm"},
                  "label":"0-5cm","values":{"Q0.5":65}}]}
    ]}}
    with pytest.raises(ValueError,match="depth metadata mismatch"):
        parse_soilgrids_rest(data,statistics=("Q0.5",),properties=("phh2o",))


def test_rest_only_one_request_with_repeated_property_keys():
    from soil_ingestion.ingest import get_soilgrids_rest
    d={"type":"Feature","properties":{"layers":[
        {"name":"phh2o","depths":[{"range":{"top_depth":0,"bottom_depth":5,"unit_depth":"cm"},
                                  "label":"0-5cm","values":{"Q0.5":65}}]}]}}
    session=Session([Response(d,url="https://rest.isric.org/soilgrids/v2.0/properties/query?lon=73&lat=18")])
    rows=get_soilgrids_rest(session,18.5,73.8,statistics=("Q0.5",),properties=("phh2o",))
    assert rows[0]["value"]==6.5
    assert len(session.calls)==1
    assert session.calls[0][2]["params"]==[
       ("lon",73.8),("lat",18.5),("property","phh2o"),("depth","0-5cm"),("value","Q0.5")]

