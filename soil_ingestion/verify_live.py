"""Read-only point REST/WCS comparison; opt-in, never run automatically in CI."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import requests
from .ingest import SOILGRIDS, parse_soilgrids_rest, valid_coords
from .parcel import DEPTHS, fetch_parcel


def compare(rest_data, report):
    comparisons = []
    for depth in report['requested_depths']:
        rest = parse_soilgrids_rest(rest_data, depth=depth, statistics=('mean',),
                                   properties=report['requested_properties'])
        for prop, row in zip(report['requested_properties'], rest):
            layer = report['properties'][prop][depth]
            # A point/parcel mismatch is not an endpoint mismatch.
            if layer['distinct_pixels'] != 1 or layer['quality'] != 'complete':
                raise ValueError('Comparison requires one valid source pixel per layer')
            wcs = layer['mean']
            comparisons.append({'property': prop, 'depth': depth, 'unit': row['unit'],
                'rest': row['value'], 'wcs': wcs, 'difference': wcs-row['value'],
                'matched': math.isclose(wcs,row['value'],rel_tol=0,abs_tol=1e-9)})
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lat', type=float, required=True)
    parser.add_argument('--lon', type=float, required=True)
    parser.add_argument('--property', action='append', dest='properties', choices=list(SOILGRIDS))
    parser.add_argument('--out', required=True, help='Private diagnostic report; contains coordinates')
    args = parser.parse_args()
    lat, lon = valid_coords(args.lat,args.lon)
    props = args.properties or list(SOILGRIDS)
    # A small synthetic box, not a registered land. Reject if it crosses pixels.
    e = .00001
    polygon = {'type':'Polygon','coordinates':[[[lon-e,lat-e],[lon+e,lat-e],
        [lon+e,lat+e],[lon-e,lat+e],[lon-e,lat-e]]]}
    evidence = {'checked_at':datetime.now(timezone.utc).isoformat(), 'lat':lat, 'lon':lon,
                'status':'failed', 'laboratory_validation':False}
    try:
        with requests.Session() as session:
            params = [('lat',lat),('lon',lon)] + [('property',p) for p in props]
            params += [('depth',d) for d in DEPTHS] + [('value','mean')]
            response = session.get('https://rest.isric.org/soilgrids/v2.0/properties/query',
                                   params=params,timeout=(10,60))
            response.raise_for_status()
            evidence['rest'] = response.json()
            evidence['wcs'] = fetch_parcel(polygon,source_version='diagnostic-release-unverified',
                session=session,properties=props,statistics=['mean'])
        evidence['comparisons'] = compare(evidence['rest'],evidence['wcs'])
        evidence['status'] = 'matched' if all(v['matched'] for v in evidence['comparisons']) else 'discrepancy'
    except (requests.RequestException, ValueError, TypeError, KeyError) as error:
        # Avoid printing exception messages: HTTP errors can include coordinates.
        evidence['error_type'] = type(error).__name__
    path = Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':evidence['status'],'output':str(path),
                      'comparisons':len(evidence.get('comparisons',[]))}))
    return 0 if evidence['status']=='matched' else 2


if __name__ == '__main__':
    raise SystemExit(main())
