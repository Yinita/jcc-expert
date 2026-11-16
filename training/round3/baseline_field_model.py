"""Supervised OCR-line field assignment. Values always come from OCR text.

This is a screenshot-layout classifier, never a win-probability model. Models
without independent group validation are saved as candidates and are not loaded
by the default predictor. No network calls or automatic training occur here.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

import joblib
import numpy as np

FEATURE_VERSION = "ocr-field-geometry-1"
FIELDS = ("stage", "gold", "hp", "level")
LIMITS = {"gold": (0, 999), "hp": (0, 200), "level": (1, 12)}
WORDS = {"stage": ["阶段", "回合", "stage", "round"], "gold": ["金币", "金幣", "gold"],
         "hp": ["血量", "生命", "hp"], "level": ["等级", "等級", "人口", "level", "lv"],
         "purchase": ["购买经验", "購買經驗"], "reward": ["总价值", "奖励", "最高收益", "金橘"],
         "card": ["获得", "复制", "卡册", "卡组", "时间卡片"], "xp": ["经验", "xp"]}


def normalize_screen_type(screen_type):
    value = str(screen_type or "unknown")
    if value in {"board", "gameplay", "battle", "preparation", "gameplay_candidate", "board_with_card_activation_overlay", "orange_super_time"}:
        return "board"
    if value in {"inventory", "orange_card_collection", "card_collection", "orange_loadout", "orange_starter_deck_selection", "orange_card_repair", "orange_card_rewards", "orange_deck_editor", "orange_card_detail"}:
        return "orange_menu"
    return value


def valid_bbox(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    try:
        x, y, w, h = map(float, box)
        return all(math.isfinite(v) for v in (x, y, w, h)) and min(x, y) >= 0 and min(w, h) > 0 and x+w <= 1.00001 and y+h <= 1.00001
    except (TypeError, ValueError):
        return False


def parse_value(text, field):
    """Only unambiguous real digit tokens; no OCR digit substitution or invention."""
    text = str(text).strip()
    if field == "stage":
        found = re.findall(r"(?<!\d)([1-9])\s*[-—–－]\s*([1-7])(?!\d)", text)
        values = {f"{a}-{b}" for a, b in found}
        return next(iter(values)) if len(values) == 1 else None
    prefixes = {"gold": r"(?:金币|金幣|GOLD)", "hp": r"(?:血量|生命值?|HP)", "level": r"(?:等级|等級|人口|LEVEL|LV)"}
    if field not in prefixes:
        return None
    found = re.findall(prefixes[field]+r"\s*[:：=]?\s*(\d{1,3})(?!\d)", text, re.I)
    if not found:
        bare = re.fullmatch(r"\s*(\d{1,3})\s*" + (r"(?:级|級)?" if field == "level" else ""), text)
        found = [bare[1]] if bare else []
    values = {int(x) for x in found}
    if len(values) != 1:
        return None
    value = next(iter(values))
    lo, hi = LIMITS[field]
    return value if lo <= value <= hi else None


def features(line, lines, image_shape, mode, screen_type):
    box = line.get("bbox")
    if not valid_bbox(box):
        raise ValueError("OCR line needs a valid normalized bbox")
    x, y, w, h = map(float, box)
    height, width = image_shape[:2]
    text = str(line.get("text", "")); compact = re.sub(r"\s+", "", text).lower()
    result = {"x": x, "y": y, "cx": x+w/2, "cy": y+h/2, "w": w, "h": h,
              "area": w*h, "line_aspect": min(20., w/max(h, .0001)), "image_aspect": width/max(height, 1),
              "pixel_height": h*height/100, "text_length": min(len(compact), 80)/80,
              "digits": sum(c.isdigit() for c in compact)/max(len(compact), 1),
              "ocr_confidence": float(line.get("confidence", 0)), "mode="+mode: 1., "screen="+normalize_screen_type(screen_type): 1.,
              "x_bucket="+str(min(9, int((x+w/2)*10))): 1., "y_bucket="+str(min(9, int((y+h/2)*10))): 1.}
    # No exact numeric value, hero identity or final result is encoded as a feature.
    for field in FIELDS:
        result["parseable_"+field] = float(parse_value(text, field) is not None)
    for name, keywords in WORDS.items():
        result["word_"+name] = float(any(k.lower() in compact for k in keywords))
        nearby = []
        for other in lines:
            if other is line or not valid_bbox(other.get("bbox")):
                continue
            ox, oy, ow, oh = other["bbox"]
            if abs(ox+ow/2-x-w/2) < .16 and abs(oy+oh/2-y-h/2) < .10:
                nearby.append(str(other.get("text", "")).lower())
        result["near_"+name] = float(any(k.lower() in s for k in keywords for s in nearby))
    return result


def calibrated_probabilities(classifier, matrix, temperature=1.):
    raw = np.clip(classifier.predict_proba(matrix), 1e-9, 1.)
    logits = np.log(raw)/max(float(temperature), .05)
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp/exp.sum(axis=1, keepdims=True)


def artifact_key(mode, patch):
    if mode not in {"nature", "orange", "shared"} or not re.fullmatch(r"[A-Za-z0-9.]{1,30}", str(patch)):
        raise ValueError("Unsupported mode or patch")
    return hashlib.sha256(f"{mode}:{patch}:{FEATURE_VERSION}".encode()).hexdigest()[:24]


def predict_artifact(artifact, meta, lines, image_shape, mode, screen_type, thresholds=None):
    valid = [line for line in lines if isinstance(line, dict) and valid_bbox(line.get("bbox")) and line.get("text")]
    if not valid:
        return []
    matrix = artifact["vectorizer"].transform([features(line, valid, image_shape, mode, screen_type) for line in valid])
    probabilities = calibrated_probabilities(artifact["classifier"], matrix, artifact.get("temperature", 1.))
    classes = list(artifact["classifier"].classes_)
    thresholds = thresholds or meta.get("thresholds", {})
    candidates = []
    for line, scores in zip(valid, probabilities):
        index = int(np.argmax(scores)); field = str(classes[index]); score = float(scores[index])
        if field not in FIELDS or score < float(thresholds.get(field, 1.000001)):
            continue
        value = parse_value(line["text"], field)
        if value is None:
            continue
        candidates.append({"field": field, "kind": "supervised_ocr_field", "value": value,
                           "text": line["text"], "bbox": list(map(float, line["bbox"])),
                           "confidence": round(score, 6), "model_score": round(score, 6),
                           "requires_confirmation": True,
                           "calibration": {"method": meta.get("calibration_method", "none"),
                                           "validated": bool(meta.get("deployable")), "score_is_win_probability": False},
                           "provenance": {"model_id": meta.get("model_id"), "artifact_sha256": meta.get("artifact_sha256"),
                                          "feature_version": FEATURE_VERSION, "mode": mode, "patch": meta.get("patch"),
                                          "status": meta.get("status"), "value_source": "parseable_OCR_text"}})
    # Contradicting OCR candidates for one field cause abstention, never averaging.
    accepted = []
    for field in FIELDS:
        matches = [c for c in candidates if c["field"] == field]
        if matches and len({str(c["value"]) for c in matches}) == 1:
            accepted.append(max(matches, key=lambda c: c["model_score"]))
    return accepted


class FieldModel:
    def __init__(self, model_dir, mode="nature", patch="18.6"):
        self.model_dir = Path(model_dir)
        self.mode, self.patch = mode, patch
        self._cache = {}

    def predict(self, lines, image_shape, mode, screen_type):
        try:
            if mode not in {"nature", "orange"}:
                return []
            key = artifact_key(mode, self.patch)
            meta_path = self.model_dir/(key+".json")
            model_path = self.model_dir/(key+".joblib")
            if not meta_path.is_file() or not model_path.is_file():
                key = artifact_key("shared", self.patch)
                meta_path = self.model_dir/(key+".json")
                model_path = self.model_dir/(key+".joblib")
                if not meta_path.is_file() or not model_path.is_file():
                    return []
            meta_bytes = meta_path.read_bytes(); meta = json.loads(meta_bytes)
            mode_allowed = meta.get("mode") == mode or (meta.get("mode") == "shared" and mode in meta.get("validated_modes", []))
            if (meta.get("status") != "ready" or meta.get("deployable") is not True or not mode_allowed
                    or meta.get("patch") != self.patch or meta.get("feature_version") != FEATURE_VERSION):
                return []
            artifact_bytes = model_path.read_bytes()
            digest = hashlib.sha256(artifact_bytes).hexdigest()
            if digest != meta.get("artifact_sha256"):
                return []
            cache_key = (key, hashlib.sha256(meta_bytes).hexdigest(), digest)
            artifact = self._cache.get(cache_key)
            if artifact is None:
                artifact = joblib.load(model_path)
                if artifact.get("feature_version") != FEATURE_VERSION:
                    return []
                self._cache = {cache_key: artifact}
            return predict_artifact(artifact, meta, lines, image_shape, mode, screen_type)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, EOFError):
            return []
