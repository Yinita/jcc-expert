"""Conservative Orange card-title candidates, with independent suffix pixels.

No card is added to match state. OCR scores and pixel-agreement scores are not
calibrated probabilities. In particular NFKC must not turn mixed ``ⅡI`` into a
confident ``III``: that OCR spelling is ambiguous until suffix pixels resolve it.
The experimental card_tier_model is deliberately not used here.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict

import cv2
import numpy as np

TIERS = ("I", "II", "III", "IV", "V")
_UNICODE_ROMAN = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
                  "ⅰ": "I", "ⅱ": "II", "ⅲ": "III", "ⅳ": "IV", "ⅴ": "V"}


def _text(value):
    return re.sub(r"\s+", "", str(value or "")).strip()


def _box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = map(float, value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(n) for n in (x, y, w, h)):
        return None
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1.001 or y+h > 1.001:
        return None
    return [x, y, min(w, 1-x), min(h, 1-y)]


def _clean_lines(lines):
    result = []
    for row in list(lines or [])[:500]:
        if not isinstance(row, dict):
            continue
        box = _box(row.get("bbox"))
        try:
            confidence = float(row.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if box is None or not math.isfinite(confidence) or confidence < .60:
            continue
        result.append({"text": str(row.get("text", ""))[:300], "bbox": box,
                       "confidence": min(1., max(0., confidence))})
    return result


def classify_card_screen(lines):
    """Classify menu semantics from visible text anchors, never image identity.

    ``context`` intentionally uses vision's existing broad inventory/loadout
    names. ``menu_type`` is finer-grained and suitable for evidence/UI display.
    """
    rows = _clean_lines(lines)
    header = " ".join(_text(r["text"]) for r in rows if r["bbox"][1] < .25)
    all_text = " ".join(_text(r["text"]) for r in rows)
    result = {"context": "unknown", "menu_type": "unknown", "anchors": []}

    def found(context, menu, anchors):
        return {"context": context, "menu_type": menu, "anchors": anchors}

    # A visible risk/reward modal is super-time even if its title is not OCR'd.
    paired_challenge = ("维持原状" in all_text and "接受挑战" in all_text
                        and "最终进入前" in all_text
                        and ("挑战失败" in all_text or "总价值" in all_text))
    if "超级时间" in all_text or paired_challenge:
        return found("orange_super_time", "orange_super_time",
                     ["超级时间"] if "超级时间" in all_text else ["维持原状", "接受挑战", "最终进入前"])
    if "时间卡片价值" in all_text and "时间能量" in all_text and any(
            a in all_text for a in ("一键配卡", "尚未拥有", "时空召唤", "收藏")):
        return found("inventory", "orange_card_detail", ["时间卡片价值", "时间能量"])
    if any(a in header for a in ("卡片修复", "修复卡片")):
        return found("inventory", "orange_card_repair", ["卡片修复"])
    if ("请选择" in header and "一套卡组" in header) or "初始卡组" in header:
        return found("orange_loadout", "orange_starter_deck_selection", ["选择一套卡组"])
    if any(a in header for a in ("卡组方案", "出战卡组", "编辑卡组", "选择卡组")):
        if "筛选" in header and "搜索" in header and any(a in header for a in ("保存", "一键配卡")):
            return found("orange_loadout", "orange_deck_editor", ["出战卡组", "筛选", "搜索"])
        return found("orange_loadout", "orange_loadout", [a for a in ("卡组方案", "出战卡组", "编辑卡组", "选择卡组") if a in header])
    if "卡册" in header and any(a in all_text for a in ("筛选", "搜索", "时间熔炉", "卡背")):
        return found("inventory", "orange_card_collection", ["卡册"])
    # Reward counts must occur in the header; an arbitrary card effect does not
    # become a reward page merely by mentioning a rarity and a number.
    rarity_counts = sum(bool(re.search(a+r"[xX×]\d", header)) for a in ("传说", "史诗", "王者", "勇士", "基础"))
    if rarity_counts >= 2 and any("确定" == _text(r["text"]) and r["bbox"][1] > .75 for r in rows):
        return found("inventory", "orange_card_rewards", ["顶部多品阶数量", "确定"])
    return result


def parse_roman_suffix(raw):
    """Return exact/ambiguous spelling information without destructive NFKC."""
    raw = _text(raw)
    if raw in TIERS:
        return {"tier": raw, "status": "exact", "possible": [raw]}
    if raw in _UNICODE_ROMAN:
        tier = _UNICODE_ROMAN[raw]
        return {"tier": tier, "status": "exact_unicode", "possible": [tier]}
    if raw in ("1", "!", "！", "|", "l", "Ｉ", "ｌ"):
        return {"tier": None, "status": "glyph_alias", "possible": ["I"]}
    if raw and all(c in _UNICODE_ROMAN or c in "IV" for c in raw):
        normalized = "".join(_UNICODE_ROMAN.get(c, c) for c in raw)
        possible = {normalized} if normalized in TIERS else set()
        # Mixed character systems can duplicate a stroke in OCR. The original
        # Unicode numeral is another hypothesis, not a forced correction.
        possible.update(_UNICODE_ROMAN[c] for c in raw if c in _UNICODE_ROMAN)
        return {"tier": None, "status": "mixed_roman_ambiguous", "possible": sorted(possible, key=lambda s: TIERS.index(s))}
    return {"tier": None, "status": "unreadable", "possible": []}


def _stem_vote(crop, threshold):
    """Count only aligned, separated narrow upright glyphs at the right edge.

    This deliberately only supports I/II/III. V and broken Chinese strokes are
    refused. Threshold agreement is checked by the caller; no Roman numeral is
    inferred from a card illustration, rarity colour, effect or expected tier.
    """
    h, w = crop.shape[:2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] >= threshold) & (hsv[:, :, 1] <= 120)).astype(np.uint8)*255
    mask[:round(h*.12)] = 0
    mask[round(h*.90):] = 0
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    pieces = []
    for i, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
        if x < .45*w or ch < max(5, .18*h) or ch > .78*h or cw > 1.25*ch or area < 4:
            continue
        pieces.append((int(x), int(y), int(cw), int(ch), int(area), i))
    pieces.sort(key=lambda p: p[0]+p[2], reverse=True)
    if not pieces:
        return None
    last = pieces[0]
    # A clipped suffix or a title crop missing the right edge is not evidence.
    if last[0]+last[2] >= w-1 or last[0] < .65*w:
        return None
    selected = [last]
    for p in pieces[1:]:
        gap = min(z[0] for z in selected)-(p[0]+p[2])
        if gap < 0:
            continue
        if (gap > .55*last[3] or not .78 <= p[3]/last[3] <= 1.28
                or abs((p[1]+p[3]/2)-(last[1]+last[3]/2)) > .18*last[3]):
            break
        selected.append(p)
        if len(selected) > 3:
            return None
    for x, y, cw, ch, area, i in selected:
        if cw/ch > .60:
            return None
        m = labels[y:y+ch, x:x+cw] == i
        middle = m[round(ch*.2):round(ch*.8)]
        _, xs = np.where(middle)
        if not len(xs) or np.quantile(xs, .9)-np.quantile(xs, .1) > .38*ch:
            return None
    return len(selected)


def inspect_suffix_pixels(crop):
    if crop is None or not hasattr(crop, "shape") or len(crop.shape) != 3 or crop.shape[2] != 3:
        return {"tier": None, "status": "invalid_crop", "votes": []}
    h, w = crop.shape[:2]
    if h < 12 or w < 25 or h > 512 or w > 2048:
        return {"tier": None, "status": "crop_dimensions_outside_limit", "votes": []}
    votes = [_stem_vote(crop, threshold) for threshold in (180, 210, 235)]
    counts = Counter(v for v in votes if v is not None)
    if not counts or counts.most_common(1)[0][1] < 2:
        return {"tier": None, "status": "unstable_suffix_pixels", "votes": votes}
    count, agree = counts.most_common(1)[0]
    return {"tier": "I"*count, "status": "aligned_stems", "votes": votes,
            "agreement_count": agree, "confidence": .86 if agree == 2 else .90}


def _title_crop(image, bbox):
    if image is None or not hasattr(image, "shape") or len(image.shape) != 3 or image.shape[2] != 3:
        return None
    ih, iw = image.shape[:2]
    x, y, w, h = bbox
    pad = h*.25
    left, right = max(0, round((x-pad*.4)*iw)), min(iw, round((x+w+pad*.4)*iw))
    top, bottom = max(0, round((y-pad)*ih)), min(ih, round((y+h+pad)*ih))
    crop = image[top:bottom, left:right]
    return crop if crop.size and crop.shape[0] <= 512 and crop.shape[1] <= 2048 else None


def _role(menu, bbox, lines):
    roles = {"orange_starter_deck_selection": "preset_option", "orange_card_repair": "repair_inventory",
             "orange_card_rewards": "reward_obtained", "orange_card_detail": "detail_preview",
             "orange_card_collection": "collection_card_not_deck_confirmation", "orange_loadout": "displayed_deck_card"}
    if menu == "orange_deck_editor":
        boundaries = [r["bbox"][0] for r in lines if "当前" in r["text"] and "能量" in r["text"]
                      and r["bbox"][0] > .4 and r["bbox"][1] > .65]
        if boundaries:
            return "selected_deck_card" if bbox[0] >= min(boundaries) else "catalog"
        return "deck_card_unassigned"
    return roles.get(menu, "visible_card_title")


def _catalog(entities):
    index = defaultdict(list)
    for row in entities or []:
        if row.get("kind", row.get("entity_type", "card")) != "card":
            continue
        identity = row.get("id", row.get("entity_id"))
        name = str(row.get("name", row.get("name_zh", "")))
        if identity is None or not name:
            continue
        match = re.fullmatch(r"(.+?)\s+(I|II|III|IV|V)", name)
        base, tier = (match[1], match[2]) if match else (name, None)
        index[_text(base)].append({"id": str(identity), "name": name, "tier": tier})
    return index


def read_card_titles(image, lines, card_entities, ocr_backend=None, context=None, max_local_ocr_calls=8):
    """Return candidates and scene evidence; never return or mutate GameState.

    Integration: remove generic OCR ``entity_type=card`` candidates before adding
    these candidates, otherwise its NFKC Roman mistake remains alongside a fix.
    ``ocr_backend`` may be the existing local backend exposing read(BGR). It is
    optional; calls are restricted to padded, known-base title crops. The same
    OCR at different scales is not treated as independent evidence.
    """
    rows = _clean_lines(lines)
    scene = classify_card_screen(rows)
    if scene["context"] == "unknown" and context:
        scene["context"] = str(context)
    catalog = _catalog(card_entities)
    evidence, uncertain = [], []
    calls = 0
    budget = max(0, min(16, int(max_local_ocr_calls)))
    seen = []
    for line in rows:
        text = _text(line["text"])
        # Full-title matching avoids names mentioned within card effect prose.
        base = next((b for b in sorted(catalog, key=len, reverse=True) if text.startswith(b)
                     and len(text)-len(b) <= 5), None)
        if base is None or line["confidence"] < .72:
            continue
        variants = catalog[base]
        tail = text[len(base):]
        plain = [r for r in variants if r["tier"] is None]
        pixel, reread, choice = None, [], None
        method = "exact_title_ocr"
        if plain:
            if tail or len(plain) != 1:
                continue
            choice = plain[0]
        else:
            spelling = parse_roman_suffix(tail)
            crop = _title_crop(image, line["bbox"])
            if crop is not None:
                pixel = inspect_suffix_pixels(crop)
            tier = spelling["tier"]
            # Exact IV/V are allowed from explicit text; I/II/III must not
            # contradict stable pixels. Ambiguous aliases always need pixels.
            if tier and pixel and pixel.get("tier") and tier != pixel["tier"]:
                tier = None
                method = "suffix_evidence_conflict"
            elif not tier and pixel and pixel.get("tier") in spelling["possible"]:
                tier = pixel["tier"]
                method = "ocr_and_suffix_pixels"
            # Optional second OCR can repair a punctuation error or confirm the
            # base; it may veto disagreement but cannot majority-vote a tier.
            if spelling["status"] not in ("exact", "exact_unicode") and ocr_backend is not None and crop is not None and calls < budget:
                calls += 1
                try:
                    scale = min(4., 1536/max(crop.shape[:2]))
                    local = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                    local_rows, error = ocr_backend.read(local)
                    for r in local_rows or []:
                        t = _text(r.get("text"))
                        if float(r.get("confidence", 0)) >= .75 and t.startswith(base):
                            p = parse_roman_suffix(t[len(base):])
                            reread.append({"text": str(r["text"]), "confidence": round(float(r["confidence"]), 4), "suffix_status": p["status"]})
                            if p["tier"] and tier and p["tier"] != tier:
                                tier = None
                                method = "suffix_evidence_conflict"
                except (ValueError, TypeError, OSError, RuntimeError, cv2.error):
                    pass
            choices = [r for r in variants if r["tier"] == tier] if tier else []
            if len(choices) == 1:
                choice = choices[0]
            else:
                uncertain.append({"field": "candidates", "kind": "card_title_ambiguous", "base_name": base,
                                  "text": line["text"], "bbox": line["bbox"], "reason": method if method == "suffix_evidence_conflict" else "roman_suffix_not_resolved",
                                  "suffix_spelling": spelling, "suffix_pixels": pixel, "local_ocr": reread,
                                  "alternatives": [{"entity_id": r["id"], "name": r["name"], "entity_type": "card"} for r in variants],
                                  "requires_confirmation": True})
                continue
        if choice is None:
            continue
        # The evidence box locates the title, not an invented full card panel.
        bx, by, bw, bh = line["bbox"]
        if any(identity == choice["id"] and abs(x-bx) < .015 and abs(y-by) < .015 for identity, x, y in seen):
            continue
        seen.append((choice["id"], bx, by))
        confidence = min(line["confidence"], pixel.get("confidence", 1.)) if method == "ocr_and_suffix_pixels" else line["confidence"]
        evidence.append({"field": "candidates", "kind": "card_title_candidate", "entity_type": "card",
                         "entity_id": choice["id"], "name": choice["name"], "text": line["text"], "bbox": line["bbox"],
                         "title_bbox": line["bbox"], "bbox_semantics": "observed_title_text",
                         "confidence": round(confidence, 4), "method": method, "suffix_pixels": pixel, "local_ocr": reread,
                         "role": _role(scene["menu_type"], line["bbox"], rows), "menu_type": scene["menu_type"],
                         "alternatives": [], "requires_confirmation": True, "safe_to_apply": False})
    return {**scene, "evidence": evidence, "uncertain": uncertain,
            "capabilities": {"local_title_ocr_calls": calls, "local_title_ocr_budget": budget,
                             "suffix_pixels_supported": ["I", "II", "III"], "confidence_calibrated": False,
                             "card_ownership_inferred": False, "experimental_tier_svm_used": False}}
