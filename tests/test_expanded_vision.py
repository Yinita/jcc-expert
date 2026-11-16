from pathlib import Path
from app.vision import ScreenshotRecognizer


def line(text,x,y,w=.05):
    return {'text':text,'compact_text':text,'bbox':[x,y,w,.04],'confidence':.99}


def names():
    return [{**line('Hero'+str(i),.15+i*.16,.40),'name':'Hero'+str(i),
             'entity_id':str(i),'entity_type':'hero','alternatives':[]} for i in range(5)]


def test_top_shop_needs_all_five_names_and_both_controls():
    controls=[line('购买经验',.03,.88),line('刷新',.90,.65)]
    found,_=ScreenshotRecognizer._complete_shop_grid(controls,names())
    assert [x['slot'] for x in found]==list(range(5))
    assert ScreenshotRecognizer._complete_shop_grid(controls,names()[:4])==([],[])
    assert ScreenshotRecognizer._complete_shop_grid(controls[:1],names())==([],[])


def test_irregular_or_ambiguous_top_row_is_rejected():
    controls=[line('购买经验',.03,.88),line('刷新',.90,.65)]
    rows=names();rows[2]['bbox'][0]+=.08
    assert ScreenshotRecognizer._complete_shop_grid(controls,rows)==([],[])
    rows=names();rows[2]['alternatives']=[{'entity_id':'unknown'}]
    assert ScreenshotRecognizer._complete_shop_grid(controls,rows)==([],[])


def test_one_character_hero_is_not_matched_inside_sentences():
    r=ScreenshotRecognizer.__new__(ScreenshotRecognizer)
    r.entities={'nature':[{'id':'hero-yi','name':'易','kind':'hero'}]}
    assert r._entity_candidates([line('易',.3,.4)],'nature')[0]['entity_id']=='hero-yi'
    assert not r._entity_candidates([line('容易获得',.3,.4)],'nature')


def test_partial_top_shop_keeps_middle_gap_and_rejects_missing_first_slot():
    controls=[line('购买经验',.04,.88),line('刷新',.91,.65)]
    rows=names();rows=[rows[i]for i in [0,1,3,4]]
    found,_=ScreenshotRecognizer._top_shop_grid(controls,rows,{'regions':{'gold':[.9,.9,.1]}})
    assert [r['slot']for r in found]==[0,1,3,4]
    assert ScreenshotRecognizer._top_shop_grid(controls,rows[1:],{'regions':{'gold':[.9,.9,.1]}})==([],[])
    assert ScreenshotRecognizer._top_shop_grid(controls,rows,None)==([],[])
    assert ScreenshotRecognizer._top_shop_grid(controls[:1],rows,{'regions':{'gold':[.9,.9,.1]}})==([],[])


def test_same_name_different_trait_forms_are_ambiguous_from_title_alone(tmp_path):
    import json
    facts={'champion_star_form_records':[
        {'official_id':'base','name':'同名英雄','observed_star_level':1,'shows_in_official_gallery':True,'cost':5,'origin_ids':['base'],'class_ids':[]},
        {'official_id':'form','name':'同名英雄','observed_star_level':1,'shows_in_official_gallery':False,'cost':5,'origin_ids':['base','extra'],'class_ids':[]}]}
    (tmp_path/'nature_facts.json').write_text(json.dumps(facts))
    r=ScreenshotRecognizer(tmp_path,tmp_path/'assets')
    candidate=r._entity_candidates([line('同名英雄',.2,.4)],'nature')[0]
    assert candidate['entity_id']=='base' and candidate['alternatives'][0]['entity_id']=='form'
