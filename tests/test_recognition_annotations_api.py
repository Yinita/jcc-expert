"""Human annotation protocol through the actual API; temporary synthetic files."""
from copy import deepcopy
import io
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


def setup(tmp_path):
    client=TestClient(create_app(Path(__file__).resolve().parents[1]/'app/data',tmp_path))
    image=io.BytesIO();Image.new('RGB',(640,360),'#243441').save(image,'PNG')
    with patch('app.main.ScreenshotRecognizer.recognize',return_value={'state':{'mode':'nature'},'evidence':[]}):
        r=client.post('/api/recognize',data={'mode':'nature'},files={'file':('test.png',image.getvalue(),'image/png')})
    state=r.json()['state'];state.update(confirmed=True,match_id='source-a',gold=50,level=5)
    negative={'bbox':[.02,.80,.08,.06],'reason':'xp_purchase_price','confirmed':True,
              'not_fields':['stage','gold','hp','level']}
    return client,state,negative


def saved(tmp_path):
    paths=list((tmp_path/'recognition_labels').glob('*.json'));assert len(paths)==1
    return json.loads(paths[0].read_text())['samples'][0]


def test_explicit_negative_only_is_saved_without_win_event(tmp_path):
    client,state,negative=setup(tmp_path)
    body={'state':state,'layout_profile':{'slots':[]},'negative_regions':[negative]}
    r=client.post('/api/recognition/feedback',json=body)
    assert r.status_code==200,r.text
    record=saved(tmp_path)
    assert record['labels']=={} and record['negative_boxes']==[negative]
    assert record['annotation_quality']['role']=='negative_only'
    assert client.get('/api/history').json()['total']==0
    body['negative_regions'][0]['confirmed']=False
    assert client.post('/api/recognition/feedback',json=body).status_code==422


def test_partial_feedback_merges_and_explicit_replacement_removes_old_regions(tmp_path):
    client,state,negative=setup(tmp_path)
    body={'state':state,'layout_profile':{'slots':[{'field':'gold','bbox':[.8,.8,.1,.1]}]},
          'negative_regions':[negative]}
    assert client.post('/api/recognition/feedback',json=body).status_code==200
    body['layout_profile']['slots']=[{'field':'level','bbox':[.13,.91,.04,.05]}]
    body['negative_regions']=[]
    assert client.post('/api/recognition/feedback',json=body).status_code==200
    record=saved(tmp_path)
    assert record['labels']=={'gold':50,'level':5} and record['negative_boxes']==[negative]
    assert record['feedback_revision']==2
    body['replace_annotations']=True
    assert client.post('/api/recognition/feedback',json=body).status_code==200
    record=saved(tmp_path)
    assert record['labels']=={'level':5} and record['negative_boxes']==[]


def test_overlapping_positive_negative_or_false_absence_is_rejected(tmp_path):
    client,state,negative=setup(tmp_path)
    body={'state':state,'layout_profile':{'slots':[{'field':'gold','bbox':negative['bbox']}]},
          'negative_regions':[negative]}
    assert client.post('/api/recognition/feedback',json=body).status_code==422
    body={'state':state,'layout_profile':{'slots':[]},'absent_fields':['gold']}
    assert client.post('/api/recognition/feedback',json=body).status_code==422
    state['gold']=None
    body['absent_fields']=['stage','gold','hp','level'];body['all_fields_reviewed']=True
    assert client.post('/api/recognition/feedback',json=body).status_code==422
    state['level']=None
    assert client.post('/api/recognition/feedback',json=body).status_code==200
    assert saved(tmp_path)['field_annotation_complete']is True
