"""Experimental trained Roman-suffix classifier; never changes a card ID.

Only local title crops are accepted. A base name must be explicitly supported
by the training manifest. Confidence is an SVM margin heuristic, not accuracy.
The candidate's tiny real corpus is insufficient for automatic ID correction.
"""
from __future__ import annotations
import functools
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

TIERS = ("I", "II", "III", "IV", "V")
_HOG = cv2.HOGDescriptor((16, 32), (8, 8), (8, 8), (4, 4), 9)


def extract_suffix(crop):
    """Conservatively isolate a final cluster of narrow light glyphs.

    Segmentation is intentionally allowed to reject a title. No OCR text or
    presumed suffix is used to choose between I and II.
    """
    if crop is None or not hasattr(crop, "shape") or len(crop.shape) != 3:
        return None, "invalid_title_crop"
    h, w = crop.shape[:2]
    if h < 10 or w < 20 or h > 512 or w > 2048:
        return None, "title_dimensions_outside_limit"
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Game labels are pale glyphs on coloured bands; exclude the outer border.
    mask = ((hsv[:, :, 2] >= 218) & (hsv[:, :, 1] <= 95)).astype(np.uint8) * 255
    margin_y, margin_x = max(1, int(.10*h)), max(1, int(.025*w))
    mask[:margin_y] = 0; mask[-margin_y:] = 0
    mask[:, :margin_x] = 0; mask[:, -margin_x:] = 0
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    pieces = []
    for i in range(1, count):
        x, y, cw, ch, area = map(int, stats[i])
        if .30*h <= ch <= .90*h and 2 <= area and cw <= 1.15*ch and x+cw < .96*w:
            pieces.append((x, y, cw, ch, i))
    if not pieces:
        return None, "no_suffix_components"
    pieces.sort(key=lambda p: p[0]+p[2], reverse=True)
    last = pieces[0]
    # Last Chinese glyphs tend to be almost square. Refuse those rather than
    # treating arbitrary strokes as a Roman numeral.
    if last[2]/last[3] > .90:
        return None, "final_component_not_roman_shaped"
    selected = [last]
    left = last[0]
    for p in pieces[1:]:
        gap = left-(p[0]+p[2])
        overlap = max(0, min(last[1]+last[3], p[1]+p[3])-max(last[1], p[1]))
        if gap < 0:
            continue
        if gap > .28*last[3] or overlap < .65*min(last[3], p[3]):
            break
        if p[2]/p[3] > .90 or len(selected) >= 4:
            break
        selected.append(p); left = p[0]
    x1 = min(p[0] for p in selected); y1 = min(p[1] for p in selected)
    x2 = max(p[0]+p[2] for p in selected); y2 = max(p[1]+p[3] for p in selected)
    if x1 < .45*w or (x2-x1)/(y2-y1) > 2.8:
        return None, "suffix_cluster_ambiguous"
    selected_mask = np.zeros(mask.shape, dtype=np.uint8)
    for p in selected:selected_mask[labels==p[4]] = 255
    glyph = selected_mask[y1:y2, x1:x2]
    if cv2.countNonZero(glyph) < 5:
        return None, "insufficient_suffix_pixels"
    return glyph, None


def glyph_features(glyph):
    if glyph is None or glyph.ndim != 2 or min(glyph.shape) < 1:
        raise ValueError("A nonempty glyph mask is required")
    h, w = glyph.shape
    scale = min(14/max(1,w), 28/max(1,h))
    resized = cv2.resize(glyph, (max(1,round(w*scale)), max(1,round(h*scale))), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((32,16), np.uint8)
    y=(32-resized.shape[0])//2; x=(16-resized.shape[1])//2
    canvas[y:y+resized.shape[0],x:x+resized.shape[1]]=resized
    histogram = np.r_[canvas.mean(axis=0)/255, canvas.mean(axis=1)/255].astype(np.float32)*.25
    geometry = np.array([min(w/h,3)/3, float(np.count_nonzero(glyph))/glyph.size],np.float32)
    return np.r_[_HOG.compute(canvas).ravel(), histogram, geometry].astype(np.float32)


class CardTierModel:
    def __init__(self, model_dir):
        self.model_dir=Path(model_dir)
        self.manifest=json.loads((self.model_dir/"manifest.json").read_text())
        self.models={tier:cv2.ml.SVM_load(str(self.model_dir/f"svm_{tier}.xml")) for tier in TIERS}

    def classify_glyph(self,glyph):
        feature=glyph_features(glyph).reshape(1,-1)
        scores={tier:float(model.predict(feature,flags=cv2.ml.StatModel_RAW_OUTPUT)[1][0,0])*float(self.manifest["orientations"][tier]) for tier,model in self.models.items()}
        ordered=sorted(scores,key=scores.get,reverse=True)
        best,second=scores[ordered[0]],scores[ordered[1]]
        gap=max(0.,best-second)
        confidence=gap/(1.+gap)
        return {"tier":ordered[0],"confidence":round(confidence,4),"decision_scores":scores}

    def predict_title(self,crop,base_name):
        if base_name not in self.manifest.get("allowed_base_names",[]):
            return {"tier":None,"confidence":0.,"status":"unsupported_base_name","safe_to_apply":False}
        glyph,error=extract_suffix(crop)
        if error:return {"tier":None,"confidence":0.,"status":error,"safe_to_apply":False}
        result=self.classify_glyph(glyph)
        if result["confidence"] < self.manifest.get("minimum_margin_confidence",.65):
            return {"tier":None,"confidence":result["confidence"],"status":"ambiguous_glyph","safe_to_apply":False}
        result.pop("decision_scores",None)
        result.update(status="candidate_only" if not self.manifest.get("approved_for_use",False) else "recognized_suffix",
                      safe_to_apply=False)
        return result


@functools.lru_cache(maxsize=4)
def _load(path):
    return CardTierModel(path)


def predict_title(crop,base_name):
    model_dir=Path(os.environ.get("JCC_CARD_TIER_MODEL",str(Path(__file__).resolve().parents[1]/"var/models/card-tier-candidate")))
    if not (model_dir/"manifest.json").exists():
        return {"tier":None,"confidence":0.,"status":"model_not_available","safe_to_apply":False}
    try:return _load(str(model_dir)).predict_title(crop,base_name)
    except (OSError,ValueError,cv2.error):
        return {"tier":None,"confidence":0.,"status":"model_invalid","safe_to_apply":False}
