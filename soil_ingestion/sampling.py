"""Deterministic 4–20 in-field positions, arranged in alternating rows.

This is a product sampling policy, not a claim of laboratory sampling accuracy.
Strata cover equal parcel area; holes and disconnected components are retained.
Connecting lines between positions are not guaranteed walkable inside the field.
"""
import math

from pyproj import Transformer
from shapely import normalize
from shapely.geometry import box

from .ingest import SOILGRIDS_PROJ

SAMPLING_VERSION = "equal-area-zigzag-4-20-v1"


def sample_count(area_m2):
    if isinstance(area_m2, bool) or not isinstance(area_m2, (int, float)) or not math.isfinite(area_m2) or area_m2 <= 0:
        raise ValueError("Sampling area must be positive and finite")
    # Retain V5's area scaling, but enforce the requested minimum of four.
    return max(4, min(20, math.floor(5 * math.sqrt(area_m2 / 10_000))))


def area_cut(geom, axis, fraction):
    """Locate a monotone equal-area cut, including concave/holed geometries."""
    x0, y0, x1, y1 = geom.bounds
    low, high = (x0, x1) if axis == "x" else (y0, y1)
    target = geom.area * fraction
    for _ in range(55):
        mid = (low + high) / 2
        clipped = geom.intersection(box(x0, y0, mid, y1) if axis == "x" else box(x0, y0, x1, mid))
        if clipped.area < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def zigzag_plan(parcel):
    """Accept a validated parcel in SoilGrids equal-area metres, not degrees."""
    if parcel.geom_type not in ("Polygon", "MultiPolygon") or parcel.is_empty or not parcel.is_valid:
        raise ValueError("Invalid parcel for sampling")
    parcel = normalize(parcel)
    count = sample_count(parcel.area)
    x0, y0, x1, y1 = parcel.bounds
    rows = max(2, min(count // 2, round(math.sqrt(count * (y1-y0) / (x1-x0)))))
    per_row = [count // rows + (i < count % rows) for i in range(rows)]
    inverse = Transformer.from_crs(SOILGRIDS_PROJ, 4326, always_xy=True)
    points, cumulative, bottom = [], 0, y0
    for row, columns in enumerate(per_row):
        cumulative += columns
        top = y1 if row == rows-1 else area_cut(parcel, "y", cumulative / count)
        band = parcel.intersection(box(x0, bottom, x1, top))
        left = x0
        row_points = []
        for column in range(columns):
            right = x1 if column == columns-1 else area_cut(band, "x", (column+1) / columns)
            stratum = band.intersection(box(left, bottom, right, top))
            if stratum.is_empty or stratum.area <= 0:
                raise ValueError("Cannot construct a nonempty sampling stratum")
            point = stratum.representative_point()
            if not parcel.contains(point):
                raise ValueError("Sampling position is not strictly inside parcel")
            lon, lat = inverse.transform(point.x, point.y)
            # Same native grid as the validated WCS raster. Top/left boundaries
            # follow rasterio's floor-based row/column indexing convention.
            pixel_left = math.floor(point.x / 250) * 250
            pixel_top = (math.floor(-point.y / 250) * -250)
            row_points.append({"row": row, "column": column,
                "lon": lon, "lat": lat, "x_m": point.x, "y_m": point.y,
                "stratum_area_m2": stratum.area,
                "pixel_id": f"igh:{pixel_left:.3f}:{pixel_top:.3f}:250"})
            left = right
        points.extend(row_points if row % 2 == 0 else reversed(row_points))
        bottom = top
    if len({(p['x_m'], p['y_m']) for p in points}) != count:
        raise ValueError("Duplicate sampling positions")
    for index, point in enumerate(points):
        point['order'] = index + 1
    return {"algorithm": SAMPLING_VERSION, "count_policy": "clamp(floor(5*sqrt(area_ha)),4,20)",
        "generated_points": count, "rows": rows, "points": points,
        "distinct_sample_pixels": len({p['pixel_id'] for p in points}),
        "note": "Positions are not independent soil measurements when they share a source pixel"}


def values_at_points(plan, cells):
    """Map every planned point to its already fetched cell, with no extra calls."""
    by_pixel = {c['pixel_id']: c for c in cells}
    if len(by_pixel) != len(cells):
        raise ValueError("Duplicate source pixels")
    values = []
    for point in plan['points']:
        cell = by_pixel.get(point['pixel_id'])
        if cell is None:
            raise ValueError("Sampling position has no corresponding raster cell")
        values.append({"order": point['order'], "pixel_id": point['pixel_id'],
            "raw_value": cell['raw_value'], "value": cell['value'], "unit": cell['unit']})
    return values
