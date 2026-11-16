"""Human annotation contracts; no assertion of real screenshot accuracy."""
import copy
import pytest

from app.field_model import features, inference_context
from app.recognition_feedback import build_feedback_annotation, merge_feedback_sample


def state():
    return {'confirmed':True,'is_demo':False,'gold':30,'hp':None,'level':None,'stage':None}


def positive():
    return {'slots':[{'field':'gold','bbox':[.5,.8,.06,.05]}]}


def negative():
    return {'bbox':[.1,.7,.05,.04],'reason':'xp_purchase_price','confirmed':True,'not_fields':['stage','gold','hp','level']}


def test_positives_do_not_implicitly_create_other():
    result=build_feedback_annotation(state(),positive())
    assert result['negative_boxes']==[]
    assert result['annotation_quality']['role']=='positive_only'
    assert result['annotation_quality']['contains_both_supervision_classes']is False


def test_reviewed_negative_only_feedback_is_useful():
    result=build_feedback_annotation(state(),{'slots':[]},[negative()])
    assert result['labels']=={}
    assert result['annotation_quality']['role']=='negative_only'


def test_negative_must_exclude_all_four_fields():
    row=negative();row['not_fields']=['gold']
    with pytest.raises(ValueError,match='all four'):build_feedback_annotation(state(),positive(),[row])


def test_positive_and_negative_conflict_rejected():
    row=negative();row['bbox']=[.5,.8,.06,.05]
    with pytest.raises(ValueError,match='overlap'):build_feedback_annotation(state(),positive(),[row])


def test_complete_review_cannot_hide_unknown_fields():
    with pytest.raises(ValueError,match='every field'):build_feedback_annotation(state(),positive(),all_fields_reviewed=True)
    result=build_feedback_annotation(state(),positive(),absent_fields=['stage','hp','level'],all_fields_reviewed=True)
    assert result['field_annotation_complete']is True


def test_known_absent_conflicts_with_actual_value():
    with pytest.raises(ValueError,match='Clear'):build_feedback_annotation(state(),positive(),absent_fields=['gold'])


def test_merge_keeps_partial_annotations_and_negative_regions():
    identity={'group_id':'user:one','mode':'nature','patch':'18.6','content_hash':'pixel:one'}
    old={**identity,**build_feedback_annotation(state(),positive(),[negative()])}
    current=state();current.update(gold=None,level=6)
    new={**identity,**build_feedback_annotation(current,{'slots':[{'field':'level','bbox':[.2,.8,.05,.05]}]})}
    merged=merge_feedback_sample(old,new)
    assert merged['labels']=={'gold':30,'level':6}
    assert len(merged['negative_boxes'])==1
    assert merged['feedback_revision']==1
    other=copy.deepcopy(new);other['group_id']='user:two'
    with pytest.raises(ValueError):merge_feedback_sample(old,other)


def test_manual_screen_label_cannot_change_training_feature_context():
    lines=[{'text':'3-2','confidence':.9,'bbox':[.4,.01,.08,.04]}]
    assert features(lines[0],lines,(1000,1600,3),'nature','board')==features(lines[0],lines,(1000,1600,3),'nature','unknown')
    assert inference_context(lines,'nature')=='board'


def test_menu_card_round_is_not_board_context():
    lines=[{'text':'卡组方案','confidence':.95,'bbox':[.1,.01,.2,.05]},
           {'text':'3-2获得奖励','confidence':.99,'bbox':[.4,.5,.2,.05]}]
    assert inference_context(lines,'orange')=='orange_menu'
