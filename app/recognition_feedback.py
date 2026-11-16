"""Pure validation/merge protocol for human OCR field corrections.

The caller retains screenshot authentication, source binding and atomic writes.
Unknown text is never automatically labelled other. A negative region means the
user reviewed it against ALL four current scalar fields, not merely one field.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .field_model import FIELDS, parse_value, valid_bbox

NEGATIVE_REASONS = {"xp_purchase_price", "refresh_price", "countdown", "trait_count",
                    "other_player_hp", "card_activation_round", "menu_currency", "reward_value",
                    "card_title_or_effect", "other_confirmed_not_current_scalar"}


def overlap_fraction(first, second):
    x,y,w,h=map(float,first); a,b,c,d=map(float,second)
    area=max(0.,min(x+w,a+c)-max(x,a))*max(0.,min(y+h,b+d)-max(y,b))
    return area/min(w*h,c*d)


def quality(annotation):
    positive=set(annotation.get("field_boxes",{}))
    absent=set(annotation.get("known_absent_fields",[]))
    negatives=len(annotation.get("negative_boxes",[]))
    both=bool(positive and (negatives or annotation.get("field_annotation_complete")))
    return {"positive_fields":len(positive),"explicit_negative_regions":negatives,
            "known_absent_fields":len(absent),"unknown_fields":sorted(set(FIELDS)-positive-absent),
            "contains_both_supervision_classes":both,
            "role":"positive_and_negative"if both else "positive_only"if positive else "negative_only"if negatives or absent else "no_reliable_annotation",
            "warning":None if both else "Positive boxes alone do not supply other-class negatives; add explicitly reviewed negative regions across several source groups."}


def validate_annotation(annotation):
    labels=annotation.get("labels",{});boxes=annotation.get("field_boxes",{})
    absent=set(annotation.get("known_absent_fields",[]))
    if absent-set(FIELDS):raise ValueError("Unknown absent scalar field")
    for field,box in boxes.items():
        if field not in FIELDS or not valid_bbox(box):raise ValueError("Invalid positive scalar region")
        value=labels.get(field)
        if value is None or str(parse_value(str(value),field))!=str(value):raise ValueError("Positive region needs a confirmed legal scalar value")
        if field in absent:raise ValueError("A field cannot be positive and explicitly absent")
    for region in annotation.get("negative_boxes",[]):
        box=region.get("bbox")if isinstance(region,dict)else None
        if not valid_bbox(box):raise ValueError("Negative region needs an in-bounds normalized bbox")
        if region.get("confirmed") is not True or set(region.get("not_fields",[]))!=set(FIELDS):
            raise ValueError("Review a negative against all four current scalar fields")
        if region.get("reason")not in NEGATIVE_REASONS:raise ValueError("Negative region needs an explicit supported reason")
        if any(overlap_fraction(box,positive)>.1 for positive in boxes.values()):
            raise ValueError("Negative and positive regions overlap; correct the annotation before saving")
    if annotation.get("field_annotation_complete")is True and set(FIELDS)-set(boxes)-absent:
        raise ValueError("Complete field review must cover every field with a value+box or explicit absence")
    return annotation


def build_feedback_annotation(state, layout_profile, negative_regions=None, absent_fields=None, all_fields_reviewed=False):
    if state.get("confirmed")is not True or state.get("is_demo")is True:
        raise ValueError("Only human-confirmed non-demo state can supervise recognition")
    boxes={}
    for slot in (layout_profile or {}).get("slots",[]):
        field=slot.get("field")
        if field not in FIELDS:continue
        if field in boxes:raise ValueError("A scalar field may have only one positive region")
        if not valid_bbox(slot.get("bbox")):raise ValueError("Invalid positive region")
        if state.get(field)is not None:boxes[field]=list(map(float,slot["bbox"]))
    labels={field:state[field]for field in boxes}
    absent=sorted(set(absent_fields or []))
    if any(state.get(field)is not None for field in absent):
        raise ValueError("Clear a field value before confirming that the field is absent")
    negatives=[]
    for raw in negative_regions or []:
        if not isinstance(raw,dict):raise ValueError("A negative needs bbox, reason and explicit confirmation")
        if not valid_bbox(raw.get('bbox')):raise ValueError("Invalid negative region")
        negatives.append({"bbox":list(map(float,raw["bbox"])),"reason":raw.get("reason"),
                          "confirmed":raw.get("confirmed")is True,"not_fields":raw.get("not_fields",[])})
    annotation={"recognition_annotation_version":2,"labels":labels,"field_boxes":boxes,
                "negative_boxes":negatives,"known_absent_fields":absent,
                "field_annotation_complete":all_fields_reviewed is True,
                "annotation_method":"user_confirmed_positive_and_explicit_negative_regions"}
    validate_annotation(annotation)
    if not boxes and not negatives and not absent:raise ValueError("No reliable positive, negative or explicit-absence annotation supplied")
    annotation["annotation_quality"]=quality(annotation)
    return annotation


def merge_feedback_sample(existing, incoming, replace_annotations=False):
    """Preserve partial prior corrections/negatives; never move a source group."""
    if not existing:
        merged=deepcopy(incoming)
    else:
        for key in ("group_id","mode","patch","content_hash"):
            if existing.get(key)!=incoming.get(key):raise ValueError("Feedback source identity or grouping cannot change")
        merged=deepcopy(existing);merged.update({k:deepcopy(v)for k,v in incoming.items()if k not in {"labels","field_boxes","negative_boxes","known_absent_fields"}})
        if replace_annotations:
            for key,default in [("labels",{}),("field_boxes",{}),("negative_boxes",[]),("known_absent_fields",[])]:merged[key]=deepcopy(incoming.get(key,default))
        else:
            merged["labels"]={**existing.get("labels",{}),**incoming.get("labels",{})}
            merged["field_boxes"]={**existing.get("field_boxes",{}),**incoming.get("field_boxes",{})}
            absent=(set(existing.get("known_absent_fields",[]))|set(incoming.get("known_absent_fields",[])))-set(incoming.get("field_boxes",{}))
            for field in incoming.get("known_absent_fields",[]):merged["labels"].pop(field,None);merged["field_boxes"].pop(field,None)
            merged["known_absent_fields"]=sorted(absent)
            combined=existing.get("negative_boxes",[])+incoming.get("negative_boxes",[])
            unique={json.dumps(row,sort_keys=True):row for row in combined}
            merged["negative_boxes"]=list(unique.values())
    validate_annotation(merged)
    merged["annotation_quality"]=quality(merged)
    merged["feedback_revision"]=int((existing or {}).get("feedback_revision",0))+1
    merged["annotation_updated_at"]=datetime.now(timezone.utc).isoformat()
    return merged
