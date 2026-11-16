from pathlib import Path
from unittest.mock import patch
import io
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.vision import ScreenshotRecognizer


def test_new_announcement_is_visible_but_does_not_relabel_old_rules(tmp_path):
    client=TestClient(create_app(Path(__file__).resolve().parents[1]/'app/data',tmp_path))
    data=client.get('/api/health').json()
    assert data['patch']=='18.6'
    assert data['version_watch']['latest_announced_patch']=='18.6a'
    assert data['version_watch']['full_new_patch_config_available']is False
    state=client.get('/api/demo').json();state.update(patch='18.6a',confirmed=True,is_demo=False)
    result=client.post('/api/recommend',json=state).json()
    assert result['status']=='blocked' and result['state_probability']is None


def test_upload_preserves_user_patch_and_does_not_assume_ocr_inferred_version(tmp_path):
    client=TestClient(create_app(Path(__file__).resolve().parents[1]/'app/data',tmp_path))
    image=io.BytesIO();Image.new('RGB',(640,360)).save(image,'PNG')
    with patch('app.main.ScreenshotRecognizer.recognize',return_value={'state':{'mode':'nature','patch':'18.6'},'evidence':[]})as recognize:
        r=client.post('/api/recognize',data={'mode':'nature','patch':'18.6a'},files={'file':('test.png',image.getvalue(),'image/png')})
    assert r.status_code==200 and r.json()['state']['patch']=='18.6a'
    assert recognize.call_args.args[-1]=='18.6a'


def test_different_patch_cannot_use_old_supervised_field_weights(tmp_path):
    r=ScreenshotRecognizer(Path(__file__).resolve().parents[1]/'app/data',tmp_path)
    with patch.object(r,'_read_image',return_value=np.zeros((360,640,3),np.uint8)), \
         patch.object(r,'_ocr',return_value=([],None)),patch.object(r,'_templates',return_value=[]), \
         patch.object(r._field_model,'predict')as predict:
        result=r.recognize(tmp_path/'unused.png','nature',patch='18.6a')
    assert not predict.called
    assert result['state']['patch']=='18.6a' and result['capabilities']['image_patch_inferred']is False
