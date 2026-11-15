"""SoilGrids-only provider adapters and validation. No database writes."""
from __future__ import annotations
import math

ISRIC_URL = "https://maps.isric.org/mapserv"


SOILGRIDS_CRS = "http://www.opengis.net/def/crs/EPSG/0/152160"


SOILGRIDS_PROJ = "+proj=igh +datum=WGS84 +units=m +no_defs +type=crs"


SOILGRIDS_DEPTH = {"0-5cm": (0, 5), "5-15cm": (5, 15), "15-30cm": (15, 30),
                    "30-60cm": (30, 60), "60-100cm": (60, 100), "100-200cm": (100, 200)}


SOILGRIDS = {
    "phh2o": ("soil_ph", "pH", 10, 2, 12),
    "soc": ("soil_organic_carbon", "%", 100, 0, 35),
    "nitrogen": ("soil_total_nitrogen", "g/kg", 100, 0, 100),
    "clay": ("soil_clay", "%", 10, 0, 100),
    "sand": ("soil_sand", "%", 10, 0, 100),
    "silt": ("soil_silt", "%", 10, 0, 100),
    "bdod": ("soil_bulk_density", "g/cm3", 100, 0, 3),
    "cec": ("soil_cec", "cmol(+)/kg", 10, 0, 200),
}


ALLOWED = {"ISRIC_SOILGRIDS": {v[0]: v[1] for v in SOILGRIDS.values()}}

def valid_coords(lat, lon):
    for v, low, high in ((lat, -90, 90), (lon, -180, 180)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError("Invalid location coordinates")
    return float(lat), float(lon)


def finite_value(v, low, high):
    if isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v in (-999, -9999, -32768) or not low <= v <= high:
        return None
    return v


def record(provider, property_code, unit, value, *, depth_top_cm=None, depth_bottom_cm=None,
           observed_at=None, statistic, reference, metadata):
    if provider not in ALLOWED or ALLOWED[provider].get(property_code) != unit:
        raise ValueError("Invalid source/property/unit combination")
    if finite_value(value, 0 if property_code != "soil_ph" else 2,
                    12 if property_code == "soil_ph" else
                    200 if property_code == "soil_cec" else
                    100 if property_code in ("soil_total_nitrogen","soil_clay","soil_sand","soil_silt") else
                    35 if property_code == "soil_organic_carbon" else
                    3 if property_code == "soil_bulk_density" else 1) is None:
        raise ValueError("Out-of-range or missing data")
    return dict(provider=provider, property_code=property_code, unit=unit,
                value=round(float(value), 6), depth_top_cm=depth_top_cm,
                depth_bottom_cm=depth_bottom_cm, observed_at=observed_at,
                statistic=statistic, source_reference=reference, source_metadata=metadata)


def soilgrids_tiff_pixel(blob, lat, lon):
    """Read a masked WCS raster at a GPS point; all-zero grid fails closed."""
    from rasterio.io import MemoryFile
    from rasterio.warp import transform
    if not blob.startswith((b"II*\x00", b"MM\x00*")):
        raise ValueError("WCS returned non-TIFF response")
    with MemoryFile(blob) as mem, mem.open() as ds:
        if ds.count != 1 or not ds.crs:
            raise ValueError("Unusable WCS raster structure")
        band = ds.read(1, masked=True)
        if band.count() == 0:
            raise ValueError("WCS has no valid pixels")
        if ds.nodata is None and not band.any():
            raise ValueError("WCS all-zero raster without nodata metadata")
        x, y = transform("EPSG:4326", ds.crs, [lon], [lat])
        if not (ds.bounds.left <= x[0] < ds.bounds.right and ds.bounds.bottom < y[0] <= ds.bounds.top):
            raise ValueError("WCS raster does not cover location")
        sample = next(ds.sample([(x[0], y[0])], masked=True))[0]
        if bool(getattr(sample, "mask", False)):
            raise ValueError("WCS point is nodata")
        return float(sample)


def get_soilgrids(session, lat, lon, depth="0-5cm", statistics=("Q0.05", "Q0.5", "Q0.95"),
                  properties=("phh2o", "soc", "nitrogen", "clay", "sand", "silt", "bdod", "cec")):
    from pyproj import Transformer
    lat, lon = valid_coords(lat, lon)
    if depth not in SOILGRIDS_DEPTH or not set(statistics).issubset({"Q0.05","Q0.5","Q0.95","mean"}):
        raise ValueError("Invalid SoilGrids depth/statistic")
    if not set(properties).issubset(SOILGRIDS):
        raise ValueError("Unknown SoilGrids property")
    tr = Transformer.from_crs("EPSG:4326", SOILGRIDS_PROJ, always_xy=True)
    x, y = tr.transform(lon, lat)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Cannot project SoilGrids location")
    out = []
    top, bottom = SOILGRIDS_DEPTH[depth]
    for layer in properties:
        code, unit, divisor, low, high = SOILGRIDS[layer]
        for stat in statistics:
            cov = f"{layer}_{depth}_{stat}"
            params = [("map",f"/map/{layer}.map"),("SERVICE","WCS"),
                      ("VERSION","2.0.1"),("REQUEST","GetCoverage"),
                      ("COVERAGEID",cov),("FORMAT","GEOTIFF_INT16"),
                      ("SUBSET",f"X({x-500:.3f},{x+500:.3f})"),
                      ("SUBSET",f"Y({y-500:.3f},{y+500:.3f})"),
                      ("SUBSETTINGCRS",SOILGRIDS_CRS),("OUTPUTCRS",SOILGRIDS_CRS)]
            res = session.get(ISRIC_URL, params=params, timeout=90)
            res.raise_for_status()
            raw = soilgrids_tiff_pixel(res.content, lat, lon)
            value = finite_value(raw / divisor, low, high)
            if value is None:
                raise ValueError(f"Invalid SoilGrids raster value for {cov}: {raw}")
            out.append(record("ISRIC_SOILGRIDS",code,unit,value,depth_top_cm=top,
                depth_bottom_cm=bottom,statistic=stat,reference=res.url,
                metadata={"coverage_id":cov,"raw_value":raw,"native_divisor":divisor,
                          "modelled_not_measured":True,"nominal_grid_m":250,
                          "soilgrids_depth":depth,"license":"CC-BY-4.0","ingestion_transport":"WCS"}))
    return out


def parse_soilgrids_rest(data, *, depth="0-5cm", statistics=("Q0.05","Q0.5","Q0.95"),
                         properties=("phh2o","soc","nitrogen","clay","sand","silt","bdod","cec"),
                         source_url="https://rest.isric.org/soilgrids/v2.0/properties/query"):
    """Parse official point-query GeoJSON. Missing/null predictions are never invented."""
    if not isinstance(data,dict) or data.get("type")!="Feature":
        raise ValueError("Unexpected SoilGrids REST response shape")
    layers=data.get("properties",{}).get("layers")
    if not isinstance(layers,list) or not layers:
        raise ValueError("No SoilGrids REST property layers")
    by_name={layer.get("name"):layer for layer in layers if isinstance(layer,dict)}
    if len(by_name)!=len(layers):
        raise ValueError("Duplicate or invalid SoilGrids REST layers")
    top,bottom=SOILGRIDS_DEPTH[depth]
    out=[]
    for prop in properties:
        layer=by_name.get(prop)
        if layer is None:
            raise ValueError(f"Missing SoilGrids REST property {prop}")
        code,unit,divisor,low,high=SOILGRIDS[prop]
        depths=[d for d in layer.get("depths",[]) if d.get("label")==depth]
        if len(depths)!=1:
            raise ValueError(f"Missing or duplicate SoilGrids REST depth: {prop} {depth}")
        depth_data=depths[0]
        rng=depth_data.get("range",{})
        if (rng.get("top_depth"),rng.get("bottom_depth"),rng.get("unit_depth"))!=(top,bottom,"cm"):
            raise ValueError("SoilGrids REST depth metadata mismatch")
        values=depth_data.get("values")
        if not isinstance(values,dict):
            raise ValueError("SoilGrids REST statistics unavailable")
        for stat in statistics:
            raw=values.get(stat)
            if raw is None:
                raise ValueError(f"SoilGrids REST null value: {prop} {depth} {stat}")
            raw_number=finite_value(raw,0,32767)
            if raw_number is None:
                raise ValueError(f"SoilGrids REST invalid raw value: {prop} {stat}")
            value=finite_value(raw_number/divisor,low,high)
            if value is None:
                raise ValueError(f"SoilGrids REST implausible value: {prop} {stat}")
            out.append(record("ISRIC_SOILGRIDS",code,unit,value,
                depth_top_cm=top,depth_bottom_cm=bottom,statistic=stat,
                reference=source_url,metadata={"coverage_id":f"{prop}_{depth}_{stat}",
                    "native_raw_value":raw_number,"native_divisor":divisor,
                    "rest_unit_measure":layer.get("unit_measure"),
                    "ingestion_transport":"REST","modelled_not_measured":True,
                    "nominal_grid_m":250,"license":"CC-BY-4.0"}))
    return out


def get_soilgrids_rest(session,lat,lon,depth="0-5cm",
                       statistics=("Q0.05","Q0.5","Q0.95"),
                       properties=("phh2o","soc","nitrogen","clay","sand","silt","bdod","cec")):
    lat,lon=valid_coords(lat,lon)
    if depth not in SOILGRIDS_DEPTH or not set(statistics).issubset({"Q0.05","Q0.5","Q0.95","mean"}):
        raise ValueError("Invalid REST depth/statistic")
    if not set(properties).issubset(SOILGRIDS):
        raise ValueError("Unknown SoilGrids REST property")
    # One REST request for all fields; honor the published fair-use rate (5/minute).
    params=[("lon",lon),("lat",lat)]
    params += [("property",p) for p in properties]
    params += [("depth",depth)]
    params += [("value",s) for s in statistics]
    res=session.get("https://rest.isric.org/soilgrids/v2.0/properties/query",
                    params=params,timeout=50)
    res.raise_for_status()
    return parse_soilgrids_rest(res.json(),depth=depth,statistics=statistics,
                               properties=properties,source_url=res.url)

