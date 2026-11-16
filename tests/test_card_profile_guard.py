from pathlib import Path
from unittest.mock import patch
import numpy as np
from app.vision import ScreenshotRecognizer


def test_manual_card_region_cannot_bypass_title_and_ownership_guards(tmp_path):
    r=ScreenshotRecognizer(Path(__file__).resolve().parents[1]/'app/data',tmp_path)
    template={'kind':'card','entity_id':'wrong-tier','name':'Shared illustration I'}
    with patch.object(r,'_read_image',return_value=np.zeros((360,640,3),np.uint8)), \
         patch.object(r,'_ocr',return_value=([],None)), \
         patch.object(r,'_templates',return_value=[template]), \
         patch.object(r,'_match_region',return_value=[{**template,'entity_type':'card','confidence':.99,'bbox':[0,0,1,1]}])as match, \
         patch.object(r,'_automatic_shop',return_value=([],[])):
        result=r.recognize(tmp_path/'unused.png','orange',{'slots':[{'field':'orange_card_ids','bbox':[.1,.1,.2,.3]}]})
    assert result['state']['orange_card_ids']==[]
    assert not match.called
    assert any(x['field']=='orange_card_ids'for x in result['uncertain'])
