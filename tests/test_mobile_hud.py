"""Visual anchoring contracts; synthetic UI fixtures are not real accuracy data."""
import cv2
import numpy as np
from app.hud import locate_mobile_hud, read_mobile_hud


def row(text,x,y,w=.02,h=.04,confidence=.99):
    return {"text":text,"compact_text":text,"bbox":[x,y,w,h],"confidence":confidence}


def fixture(gold=True):
    image=np.zeros((500,1100,3),np.uint8)
    cv2.circle(image,(85,442),45,(220,170,60),3)
    cv2.circle(image,(129,473),16,(180,170,120),3)
    if gold:cv2.circle(image,(1020,442),45,(60,170,240),3)
    lines=[row("购买经验",.045,.88,.06),row("9",.11,.93,.015),
           row("87",.918,.856,.025,.055),row("4",.065,.84),
           row("6/36",.045,.755,.04),row("3",.92,.77)]
    return image,lines


def test_visual_circles_xp_text_and_readable_digits_are_all_required():
    image,lines=fixture();evidence,hud=read_mobile_hud(image,lines)
    assert hud and {r["field"]:r["value"] for r in evidence}=={"gold":87,"level":9}
    assert all(r["requires_confirmation"] and r["value_source"]=="parseable_OCR_text" for r in evidence)
    assert locate_mobile_hud(np.zeros_like(image),lines) is None
    assert locate_mobile_hud(image,lines[1:]) is None
    assert read_mobile_hud(image,lines,context="inventory")==([],None)


def test_cost_interest_xp_fraction_and_other_player_hp_are_not_counters():
    image,lines=fixture();evidence,_=read_mobile_hud(image,lines[:1]+lines[3:]+[row("100",.93,.25)])
    assert evidence==[]


def test_conflicting_overlapping_ocr_abstains_instead_of_selecting_best_score():
    image,lines=fixture();lines.append(row("81",.918,.856,.025,.055,confidence=.85))
    evidence,_=read_mobile_hud(image,lines)
    assert {r["field"]:r["value"] for r in evidence}=={"level":9}


def test_level_badge_does_not_require_a_visible_gold_button():
    image,lines=fixture(gold=False);evidence,hud=read_mobile_hud(image,lines)
    assert hud and {r["field"]:r["value"] for r in evidence}=={"level":9}


def test_geometry_scales_with_actual_image_dimensions():
    image,lines=fixture();image=cv2.resize(image,None,fx=1.5,fy=1.5)
    evidence,_=read_mobile_hud(image,lines)
    assert {r["field"]:r["value"] for r in evidence}=={"gold":87,"level":9}
