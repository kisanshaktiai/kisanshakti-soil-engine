"""Durable SoilGrids worker. No public port; claims jobs through service-only RPCs."""
from __future__ import annotations
import json
import logging
import os
import signal
import threading
import uuid
from urllib.parse import urlparse

import requests
from .ingest import SOILGRIDS
from .parcel import ALGORITHM, DEPTHS, STATISTICS, fetch_parcel, geometry

LOG = logging.getLogger('soil-worker')


class Database:
    def __init__(self, url, key):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('SUPABASE_URL must be an HTTPS project URL')
        if not key:
            raise ValueError('SUPABASE_SERVICE_ROLE_KEY is required')
        self.base = url.rstrip('/') + '/rest/v1/'
        self.headers = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}

    def request(self, path, payload, headers=None):
        # No automatic mutation retries: an uncertain completion is recovered by
        # the next queue claim, whose RPC observes the already committed status.
        response = requests.post(self.base + path, headers={**self.headers, **(headers or {})},
                                 json=payload, timeout=(10, 30))
        response.raise_for_status()
        return response.json() if response.content else None

    def rpc(self, name, **params):
        return self.request('rpc/' + name, params)

    def heartbeat(self, worker_id, source):
        from datetime import datetime, timezone
        self.request('soil_engine_workers?on_conflict=worker_id', {
            'worker_id': worker_id, 'source_version': source, 'algorithm_version': ALGORITHM,
            'heartbeat_at': datetime.now(timezone.utc).isoformat(),
        }, {'Prefer': 'resolution=merge-duplicates,return=minimal'})


def validate_report(report, job):
    _, fingerprint = geometry(job['geometry'])
    if (report.get('geometry_fingerprint') != fingerprint or
        report.get('algorithm_version') != job['algorithm_version'] or
        report.get('source_version') != job['source_version'] or
        report.get('quality') not in ('complete', 'partial') or
        report.get('modelled_not_measured') is not True or
        set(report.get('requested_properties', [])) != set(SOILGRIDS) or
        set(report.get('requested_depths', [])) != set(DEPTHS)):
        raise ValueError('INVALID_REPORT')
    for prop, (_, unit, _, low, high) in SOILGRIDS.items():
        for depth in DEPTHS:
            layer = report['properties'][prop][depth]
            value = layer['mean']
            if layer['unit'] != unit or (value is not None and not low <= value <= high):
                raise ValueError('INVALID_REPORT')
            if report['quality'] == 'complete' and (value is None or layer['quality'] != 'complete'):
                raise ValueError('INVALID_REPORT')
    json.dumps(report, allow_nan=False)


def process_job(db, job, fetcher=fetch_parcel):
    completed = 0
    def progress(_coverage):
        nonlocal completed
        completed += 1
        if not db.rpc('soil_progress', p_job=job['id'], p_lease=job['lease_token'],
                      p_progress=int(99 * completed / (len(SOILGRIDS)*len(DEPTHS)*len(STATISTICS)))):
            raise RuntimeError('LEASE_LOST')
    try:
        with requests.Session() as session:
            report = fetcher(job['geometry'], source_version=job['source_version'], session=session, progress=progress)
        validate_report(report, job)
        return db.rpc('soil_complete', p_job=job['id'], p_lease=job['lease_token'], p_report=report)
    except Exception as error:
        # Never log response bodies, provider URLs, farmer coordinates or keys.
        code = 'PROVIDER_UNAVAILABLE' if isinstance(error, requests.RequestException) else 'INVALID_REPORT' if isinstance(error, (ValueError, KeyError, TypeError)) else 'FETCH_FAILED'
        LOG.warning('Job stopped: %s', code)
        db.rpc('soil_fail', p_job=job['id'], p_lease=job['lease_token'], p_code=code)
        return False


def run():
    logging.basicConfig(level=logging.INFO)
    source = os.environ.get('SOILGRIDS_SOURCE_VERSION', '').strip()
    if not source:
        raise ValueError('Set the operator-verified SOILGRIDS_SOURCE_VERSION')
    db = Database(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    worker_id = str(uuid.uuid4())
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    def pulse():
        while not stop.is_set():
            try:
                db.heartbeat(worker_id, source)
            except Exception:
                LOG.warning('Worker heartbeat unavailable')
            stop.wait(20)
    # Initial heartbeat must succeed before accepting work.
    db.heartbeat(worker_id, source)
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    while not stop.is_set():
        try:
            job = db.rpc('soil_claim', p_source=source, p_algorithm=ALGORITHM)
            if job:
                process_job(db, job)
                continue
        except Exception:
            LOG.warning('Queue unavailable; backing off')
        stop.wait(10)
    thread.join(timeout=2)


if __name__ == '__main__':
    run()
