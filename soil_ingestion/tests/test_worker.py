from unittest.mock import Mock
import pytest
import requests
from soil_ingestion.worker import Database, process_job, validate_report
from soil_ingestion.parcel import ALGORITHM, DEPTHS, geometry
from soil_ingestion.ingest import SOILGRIDS

GEO = {'type':'Polygon','coordinates':[[[74.349,16.749],[74.351,16.749],[74.351,16.751],[74.349,16.751],[74.349,16.749]]]}
JOB = {'id':'job','lease_token':'lease','geometry':GEO,'algorithm_version':ALGORITHM,'source_version':'test'}
def report():
    return {'geometry_fingerprint':geometry(GEO)[1], 'algorithm_version':ALGORITHM,
        'source_version':'test','modelled_not_measured':True,'quality':'complete',
        'requested_properties':list(SOILGRIDS),'requested_depths':list(DEPTHS),
        'properties':{p:{d:{'unit':spec[1],'mean':max(spec[3],1),'quality':'complete'} for d in DEPTHS} for p,spec in SOILGRIDS.items()}}

def test_save_after_provider_result_and_lease_progress():
    db=Mock(); db.rpc.return_value=True
    def fetcher(*_, **kwargs):
        kwargs['progress']('layer')
        return report()
    assert process_job(db,JOB,fetcher)
    assert [x.args[0] for x in db.rpc.call_args_list]==['soil_progress','soil_complete']
    assert db.rpc.call_args.kwargs['p_lease']=='lease'

def test_provider_failure_never_saves():
    db=Mock()
    def fail(*_,**__): raise requests.Timeout('private provider URL')
    assert not process_job(db,JOB,fail)
    assert db.rpc.call_args.args==('soil_fail',)
    assert db.rpc.call_args.kwargs['p_code']=='PROVIDER_UNAVAILABLE'

def test_lease_loss_never_saves():
    db=Mock(); db.rpc.return_value=False
    def fetcher(*_,**kw): kw['progress']('layer'); return report()
    assert not process_job(db,JOB,fetcher)
    assert 'soil_complete' not in [x.args[0] for x in db.rpc.call_args_list]

@pytest.mark.parametrize('change',[{'geometry_fingerprint':'wrong'},{'source_version':'wrong'},{'quality':'unavailable'},{'requested_properties':['phh2o']}])
def test_rejects_invalid_report(change):
    r=report();r.update(change)
    with pytest.raises(ValueError): validate_report(r,JOB)

def test_rejects_wrong_units():
    r=report();r['properties']['nitrogen']['0-5cm']['unit']='kg/ha'
    with pytest.raises(ValueError): validate_report(r,JOB)

@pytest.mark.parametrize('url',['http://remote.example','https://user:pass@example.com','https://example.com?key=x'])
def test_rejects_unsafe_database_url(url):
    with pytest.raises(ValueError): Database(url,'secret')
