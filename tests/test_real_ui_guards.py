from app.vision import ScreenshotRecognizer
from pathlib import Path
from unittest.mock import patch
import numpy as np


def line(text, x, y, w=.05, confidence=.99):
    return {'text':text,'compact_text':text,'bbox':[x,y,w,.025],'confidence':confidence}


def shop_rows():
    rows=[]
    for i, x in [(0,.26),(1,.385),(2,.51),(4,.76)]:
        rows.append({**line('Hero'+str(i),x,.95),'entity_type':'hero','entity_id':str(i),
                     'name':'Hero'+str(i),'alternatives':[]})
    return rows


def test_bottom_shop_keeps_missing_slot_and_requires_both_controls():
    controls=[line('购买经验',.145,.84),line('刷新',.145,.93)]
    recognized,_=ScreenshotRecognizer._bottom_shop_grid(controls,shop_rows())
    assert [x['slot'] for x in recognized]==[0,1,2,4]
    assert ScreenshotRecognizer._bottom_shop_grid(controls[:1],shop_rows())==([],[])
    # Missing first card makes the slot offset ambiguous: do not shift everything left.
    assert ScreenshotRecognizer._bottom_shop_grid(controls,shop_rows()[1:])==([],[])


def test_bare_gold_needs_level_and_purchase_context():
    rows=[line('5级',.13,.77),line('购买经验',.145,.84),line('50',.49,.77),line('6',.57,.77)]
    assert ScreenshotRecognizer._bottom_gold(rows)[0]['value']==50
    assert not ScreenshotRecognizer._bottom_gold(rows[1:])
    assert not ScreenshotRecognizer._bottom_gold(rows+[line('60',.53,.77)])


def test_lobby_card_activation_rounds_are_not_current_state():
    assert ScreenshotRecognizer._screen_context([line('卡组方案',.1,.03),line('2-7',.4,.52)],'orange')=='orange_loadout'
    assert ScreenshotRecognizer._screen_context([line('时间卡册',.1,.03)],'orange')=='inventory'


def test_suffix_level_requires_xp_control_for_unlabelled_ui():
    rows=[line('5级',.13,.77),line('购买经验',.145,.84)]
    assert ScreenshotRecognizer._scalar_candidates(rows, 'level')[0]['value']==5
    assert not ScreenshotRecognizer._scalar_candidates(rows[:1], 'level')


def test_partial_numeric_profile_preserves_independent_shop_result(tmp_path):
    data=Path(__file__).resolve().parents[1]/'app/data'
    r=ScreenshotRecognizer(data,tmp_path)
    with patch.object(r,'_read_image',return_value=np.zeros((360,640,3),dtype=np.uint8)), \
         patch.object(r,'_ocr',return_value=([],None)), \
         patch.object(r,'_numeric_region',return_value=([],None)), \
         patch.object(r,'_templates',return_value=[]), \
         patch.object(r,'_automatic_shop',return_value=([{'hero_id':'11500','slot':2}],[])):
        result=r.recognize(tmp_path/'unused.png','nature',{'slots':[{'field':'gold','bbox':[.4,.7,.1,.1]}]})
    assert result['state']['shop']==[None,None,'11500',None,None]


def test_roman_card_suffix_does_not_match_a_shorter_tier():
    r=ScreenshotRecognizer.__new__(ScreenshotRecognizer)
    r.entities={'orange':[{'id':'a','name':'次级复制 I','kind':'card'}, {'id':'b','name':'次级复制 II','kind':'card'}]}
    assert not r._entity_candidates([line('次级复制III',.3,.4)],'orange')
    assert r._entity_candidates([line('次级复制II',.3,.4)],'orange')[0]['entity_id']=='b'
