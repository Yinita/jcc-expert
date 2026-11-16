"""Conservative offline screenshot OCR and official-asset template matching.

There is no language-model prompt or network call in this module. Screenshot
text is data. A name seen anywhere on a screenshot is only a candidate: it is
never silently treated as a unit on the player's board. Profiles supply that
missing spatial context. Every returned state remains unconfirmed.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from io import BytesIO, StringIO
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MODES = {"nature", "orange"}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
FIELD_KIND = {"board": "hero", "bench": "hero", "shop": "hero", "item_ids": "item",
              "augment_ids": "augment", "offered_augment_ids": "augment", "orange_card_ids": "card"}
SCALAR_FIELDS = {"stage", "hp", "gold", "level"}


def _normal_text(value):
    return re.sub(r"[\s·•【】\[\]：:()（）]+", "", str(value)).replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")


def _bbox_union(rows):
    x = min(r["bbox"][0] for r in rows)
    y = min(r["bbox"][1] for r in rows)
    right = max(r["bbox"][0] + r["bbox"][2] for r in rows)
    bottom = max(r["bbox"][1] + r["bbox"][3] for r in rows)
    return [x, y, right - x, bottom - y]


def _valid_bbox(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    try:
        x, y, w, h = map(float, box)
        return all(math.isfinite(v) for v in (x, y, w, h)) and x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1.000001 and y + h <= 1.000001
    except (TypeError, ValueError):
        return False


def validate_layout_profile(profile):
    if profile is None:
        return None
    if not isinstance(profile, dict) or not isinstance(profile.get("slots", []), list):
        raise ValueError("layout_profile must contain a slots array")
    if len(profile.get("slots", [])) > 100:
        raise ValueError("At most 100 layout slots are allowed")
    ratio = profile.get("aspect_ratio")
    if ratio is not None and (not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio <= 0):
        raise ValueError("aspect_ratio must be a positive finite number")
    clean = {"name": str(profile.get("name", "manual"))[:80], "slots": []}
    if ratio:
        clean["aspect_ratio"] = ratio
    seen_scalars = set()
    shop_slots = 0
    for slot in profile.get("slots", []):
        if not isinstance(slot, dict) or slot.get("field") not in set(FIELD_KIND) | SCALAR_FIELDS or not _valid_bbox(slot.get("bbox")):
            raise ValueError("Each layout slot needs a supported field and an in-bounds normalized bbox")
        if slot["field"] in SCALAR_FIELDS:
            if slot["field"] in seen_scalars:
                raise ValueError("A numeric field may have only one calibrated region")
            seen_scalars.add(slot["field"])
        if slot["field"] == "shop":
            shop_slots += 1
            if shop_slots > 5:
                raise ValueError("A shop profile may contain at most five ordered slots")
        clean["slots"].append({"field": slot["field"], "bbox": list(map(float, slot["bbox"])),
                               "kind": FIELD_KIND.get(slot["field"]), "label": str(slot.get("label", ""))[:80]})
    return clean


class ScreenshotRecognizer:
    def __init__(self, data_dir: Path, assets_dir: Path):
        self.data_dir = Path(data_dir)
        self.assets_dir = Path(assets_dir)
        self._profiles = {}
        self.entities = {}
        self._templates_cache = None
        self._manifest_mtime = None
        for mode, filename in (("nature", "nature_facts.json"), ("orange", "orange_base_facts.json")):
            p = self.data_dir / filename
            facts = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            rows = []
            for hero in facts.get("champion_star_form_records", []):
                if hero.get("observed_star_level") == 1 and hero.get("shows_in_official_gallery"):
                    rows.append({"id": str(hero["official_id"]), "name": hero["name"], "kind": "hero"})
            for key, kind in (("items", "item"), ("augments", "augment"), ("time_cards", "card")):
                for row in facts.get(key, []):
                    rows.append({"id": str(row["id"]), "name": row.get("name", row.get("name_zh", "")), "kind": kind})
            if mode == "orange" and not any(r["kind"] == "card" for r in rows):
                cp = self.data_dir / "orange_official_facts.json"
                if cp.exists():
                    for row in json.loads(cp.read_text()).get("cards", []):
                        rows.append({"id": str(row["id"]), "name": row.get("name_zh", ""), "kind": "card"})
            self.entities[mode] = rows

    def register_layout_profile(self, mode: str, profile: dict):
        if mode not in MODES:
            raise ValueError("mode must be nature or orange")
        self._profiles[mode] = validate_layout_profile(profile)

    def _read_image(self, path):
        path = Path(path)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Screenshot file exceeds 20 MiB")
        try:
            with Image.open(path) as im:
                if im.width > 8192 or im.height > 8192 or im.width * im.height > MAX_PIXELS or min(im.size) < 32:
                    raise ValueError("Screenshot dimensions are outside supported limits")
                im = ImageOps.exif_transpose(im).convert("RGB")
                return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Screenshot is not a supported image") from exc

    def _ocr(self, image):
        if not shutil.which("tesseract"):
            return [], "tesseract_unavailable"
        h, w = image.shape[:2]
        scale = min(2.0, 1600 / max(w, h)) if max(w, h) < 1000 else min(1.0, 2400 / max(w, h))
        scaled = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if abs(scale - 1) > .01 else image
        # Tesseract is much more reliable on dark glyphs over a light surface.
        # Most game UIs use light glyphs over a dark background.
        ocr_surface = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        if float(np.median(ocr_surface)) < 128:
            ocr_surface = cv2.bitwise_not(ocr_surface)
        ok, encoded = cv2.imencode(".png", ocr_surface)
        if not ok:
            return [], "image_encoding_failed"
        try:
            proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", "chi_sim+eng", "--psm", "11", "tsv"],
                                  input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=22, check=False)
        except subprocess.TimeoutExpired:
            return [], "ocr_timeout"
        except OSError:
            return [], "ocr_failed"
        if proc.returncode:
            return [], "ocr_failed_or_language_pack_missing"
        sh, sw = scaled.shape[:2]
        lines = defaultdict(list)
        for row in csv.DictReader(StringIO(proc.stdout.decode("utf-8", "replace")), delimiter="\t"):
            try:
                text = row.get("text", "").strip()
                confidence = float(row.get("conf", -1)) / 100
                if not text or confidence < .35:
                    continue
                bbox = [int(row["left"]) / sw, int(row["top"]) / sh, int(row["width"]) / sw, int(row["height"]) / sh]
                lines[(row.get("page_num"), row.get("block_num"), row.get("par_num"), row.get("line_num"))].append(
                    {"text": text, "confidence": min(1., max(0., confidence)), "bbox": bbox})
            except (ValueError, KeyError, TypeError):
                continue
        result = []
        for words in lines.values():
            result.append({"text": " ".join(x["text"] for x in words), "compact_text": "".join(x["text"] for x in words),
                           "confidence": sum(x["confidence"] for x in words) / len(words), "bbox": _bbox_union(words)})
        # Sparse OCR may put an explicit label and its adjacent value into
        # different blocks. Only join known labels to an immediate number on
        # the same baseline, never arbitrary nearby screenshot text.
        additions = []
        for label in result:
            if not re.fullmatch(r"(?:金币|金幣|血量|生命值|等级|等級|人口|GOLD|HP|LEVEL|LV)[:：]?", _normal_text(label["text"]), re.I):
                continue
            lx, ly, lw, lh = label["bbox"]
            for number in result:
                nx, ny, nw, nh = number["bbox"]
                if (re.fullmatch(r"\s*[:：]?\s*\d{1,3}\s*", number["text"])
                        and 0 <= nx-(lx+lw) <= .10 and abs(ny+nh/2-ly-lh/2) < max(lh, nh)*.55):
                    text = label["text"] + " " + number["text"]
                    additions.append({"text": text, "compact_text": text.replace(" ", ""),
                                      "confidence": min(label["confidence"], number["confidence"]),
                                      "bbox": _bbox_union([label, number])})
        result.extend(additions)
        return result, None

    def _templates(self, mode):
        manifest = self.assets_dir / "manifest.json"
        stamp = manifest.stat().st_mtime_ns if manifest.exists() else None
        if self._templates_cache is None or stamp != self._manifest_mtime:
            result = []
            entries = json.loads(manifest.read_text()).get("assets", []) if manifest.exists() else []
            root = self.assets_dir.resolve()
            for row in entries:
                p = (self.assets_dir / row.get("path", "")).resolve()
                if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size > 4 * 1024 * 1024:
                    continue
                try:
                    with Image.open(p) as im:
                        if im.width * im.height > 16_000_000:
                            continue
                        rgb = im.convert("RGB")
                        gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
                    if gray.std() < 8:
                        continue
                    result.append({**row, "gray": gray})
                except (OSError, ValueError, Image.DecompressionBombError):
                    continue
            self._templates_cache = result
            self._manifest_mtime = stamp
        return [r for r in self._templates_cache if r.get("mode") == mode]

    @staticmethod
    def _match_region(image, templates, *, exhaustive=False):
        if not templates:
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scale = min(1., 960 / max(w, h))
        gray = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
        gh, gw = gray.shape
        matches = []
        for entry in templates:
            original = entry["gray"]
            aspect = original.shape[1] / original.shape[0]
            widths = [24, 32, 40, 48, 56, 64, 72, 80, 88, 96] if exhaustive else sorted(set(
                max(12, int(gw * r)) for r in (.20, .30, .40, .50, .65, .80, .92, 1.0)))
            if not exhaustive:
                widths = sorted(set(widths + [round(original.shape[1]*s*scale) for s in (.5, .75, 1., 1.25)]))
            best = None
            for tw in widths:
                th = max(8, round(tw / aspect))
                if tw > gw or th > gh or min(tw, th) < 12:
                    continue
                template = cv2.resize(original, (tw, th), interpolation=cv2.INTER_AREA)
                if template.std() < 8:
                    continue
                response = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, xy = cv2.minMaxLoc(response)
                if best is None or score > best["confidence"]:
                    best = {"entity_id": entry["entity_id"], "name": entry.get("name", ""), "entity_type": entry["kind"],
                            "confidence": round(float(score), 4), "bbox": [xy[0] / gw, xy[1] / gh, tw / gw, th / gh]}
            if best and best["confidence"] >= (.87 if exhaustive else .82):
                matches.append(best)
        return sorted(matches, key=lambda x: -x["confidence"])

    def _entity_candidates(self, lines, mode):
        names = defaultdict(list)
        for row in self.entities[mode]:
            key = _normal_text(row["name"])
            if len(key) >= 2:
                names[key].append(row)
        evidence = []
        for line in lines:
            if line["confidence"] < .60:
                continue
            compact = _normal_text(line["compact_text"])
            # Longer names take precedence over their shorter substrings.
            selected = []
            for name in sorted(names, key=len, reverse=True):
                if name in compact and not any(name in n for n in selected):
                    selected.append(name)
                    rows = names[name]
                    evidence.append({"field": "candidates", "kind": "ocr_entity_candidate", "entity_id": rows[0]["id"],
                                     "entity_type": rows[0]["kind"], "name": rows[0]["name"], "text": line["text"],
                                     "confidence": round(line["confidence"], 4), "bbox": line["bbox"],
                                     "alternatives": [{"entity_id": r["id"], "entity_type": r["kind"], "name": r["name"]} for r in rows[1:]],
                                     "requires_confirmation": True})
        return evidence[:100]

    def _automatic_shop(self, image, lines, entity_evidence, templates):
        """Require a shop label, five aligned names, and same-identity portraits.

        This deliberately misses many real UI skins. It never infers a shop
        merely because five icons happen to be visible on a screenshot.
        """
        h, w = image.shape[:2]
        if not 1.35 <= w / h <= 2.6:
            return [], []
        if not any(re.search(r"刷新|购买经验|商店|REFRESH|SHOP", r["text"], re.I)
                   and r["bbox"][1] > .60 for r in lines):
            return [], []
        names = [r for r in entity_evidence if r["entity_type"] == "hero" and not r["alternatives"]
                 and r["bbox"][1] >= .72 and r["confidence"] >= .75]
        for anchor in names:
            ay = anchor["bbox"][1] + anchor["bbox"][3] / 2
            group = [r for r in names if abs(r["bbox"][1] + r["bbox"][3] / 2 - ay) < .035]
            # A single OCR line mentioning five heroes cannot locate five slots.
            group = list({tuple(round(v, 3) for v in r["bbox"]): r for r in group}.values())
            if len(group) != 5:
                continue
            group.sort(key=lambda r: r["bbox"][0])
            centers = [r["bbox"][0] + r["bbox"][2] / 2 for r in group]
            gaps = np.diff(centers)
            if min(gaps) < .07 or max(gaps) > .25 or max(gaps) / min(gaps) > 1.35:
                continue
            verified, evidence = [], []
            for index, name in enumerate(group):
                left = max(0., centers[index] - float(np.median(gaps)) * .48)
                right = min(1., centers[index] + float(np.median(gaps)) * .48)
                top, bottom = max(.5, name["bbox"][1] - .24), min(1., name["bbox"][1] + name["bbox"][3])
                crop = image[int(top*h):math.ceil(bottom*h), int(left*w):math.ceil(right*w)]
                candidates = self._match_region(crop, [t for t in templates if t["kind"] == "hero"])
                if not candidates or candidates[0]["entity_id"] != name["entity_id"] or candidates[0]["confidence"] < .90:
                    continue
                best = candidates[0]
                if len(candidates) > 1 and best["confidence"] - candidates[1]["confidence"] < .035:
                    continue
                b = best["bbox"]
                evidence.append({**best, "field": "shop", "kind": "template_ocr_shop_agreement", "slot": index,
                                 "bbox": [left+b[0]*(right-left), top+b[1]*(bottom-top), b[2]*(right-left), b[3]*(bottom-top)],
                                 "text": name["text"], "requires_confirmation": True, "alternatives": []})
                verified.append({"hero_id": best["entity_id"], "stars": None, "item_ids": [], "slot": index})
            if len(verified) >= 3:
                return verified, evidence
        return [], []

    @staticmethod
    def _scalar_candidates(lines, field=None, allow_bare=False):
        result = []
        patterns = {"stage": r"(?<!\d)([1-9])\s*[-—–－]\s*([1-7])(?!\d)",
                    "gold": r"(?:金币|金幣|GOLD)\s*[:：=]?\s*(\d{1,3})(?!\d)",
                    "hp": r"(?:生命值|血量|HP)\s*[:：=]?\s*(\d{1,3})(?!\d)",
                    "level": r"(?:等级|等級|人口|LEVEL|LV)\s*[:：=]?\s*(\d{1,2})(?!\d)"}
        for line in lines:
            if line["confidence"] < .68:
                continue
            for key in ([field] if field else patterns):
                if (key == "stage" and not allow_bare and line["bbox"][1] > .25
                        and not re.search(r"阶段|階段|STAGE|ROUND", line["text"], re.I)):
                    continue
                match = re.search(patterns[key], line["text"], re.I) or re.search(patterns[key], line.get("compact_text", ""), re.I)
                if not match and allow_bare and key != "stage":
                    match = re.fullmatch(r"\s*(\d{1,3})\s*", line["text"])
                if not match:
                    continue
                value = f"{match[1]}-{match[2]}" if key == "stage" else int(match[1])
                if key == "level" and not 1 <= value <= 12:
                    continue
                if key == "hp" and not 0 <= value <= 200:
                    continue
                result.append({"field": key, "kind": "ocr_scalar", "value": value, "text": line["text"],
                               "confidence": round(line["confidence"], 4), "bbox": line["bbox"], "requires_confirmation": True})
        return result

    def recognize(self, image_path: Path, mode: str, layout_profile: dict | None = None) -> dict:
        if mode not in MODES:
            raise ValueError("mode must be nature or orange")
        image = self._read_image(image_path)
        h, w = image.shape[:2]
        profile = validate_layout_profile(layout_profile) if layout_profile is not None else self._profiles.get(mode)
        state = {"mode": mode, "patch": "18.6", "stage": None, "hp": None, "gold": None, "level": None,
                 "board": [], "bench": [], "shop": [None] * 5, "item_ids": [], "augment_ids": [], "offered_augment_ids": [],
                 "orange_card_ids": [], "confirmed": False}
        lines, error = self._ocr(image)
        evidence = [{"field": "text", "kind": "ocr_text", "text": r["text"], "confidence": round(r["confidence"], 4), "bbox": r["bbox"]} for r in lines]
        uncertain = [{"field": "state", "reason": "截图识别尚未确认；相似度和OCR分数不是校准后的准确率。"}]
        if error:
            uncertain.append({"field": "ocr", "reason": error})
        scalar = self._scalar_candidates(lines)
        evidence.extend(scalar)
        for field in SCALAR_FIELDS:
            values = {r["value"] for r in scalar if r["field"] == field}
            if len(values) == 1:
                state[field] = next(iter(values))
            elif len(values) > 1:
                uncertain.append({"field": field, "reason": "多个文字数值冲突，待人工选择。", "candidates": sorted(values)})
        entity_evidence = self._entity_candidates(lines, mode)
        evidence.extend(entity_evidence)
        templates = self._templates(mode)
        if profile and profile.get("aspect_ratio") and abs((w / h) / profile["aspect_ratio"] - 1) > .08:
            uncertain.append({"field": "layout_profile", "reason": "图片宽高比与校准模板不符，未使用区域定位。"})
            profile = None
        if profile:
            shop_slot_index = 0
            for index, slot in enumerate(profile["slots"]):
                x, y, sw, sh = slot["bbox"]
                left, top = max(0, int(x * w)), max(0, int(y * h))
                right, bottom = min(w, math.ceil((x + sw) * w)), min(h, math.ceil((y + sh) * h))
                crop = image[top:bottom, left:right]
                field = slot["field"]
                current_shop_slot = shop_slot_index if field == "shop" else None
                if field == "shop":
                    # Keep declaration order even when this slot is unreadable.
                    shop_slot_index += 1
                if min(crop.shape[:2]) < 12:
                    uncertain.append({"field": field, "slot": index, "reason": "区域过小，无法可靠识别。"})
                    continue
                if field in SCALAR_FIELDS:
                    slot_lines, slot_error = self._ocr(crop)
                    candidates = self._scalar_candidates(slot_lines, field, allow_bare=True)
                    for row in candidates:
                        b = row["bbox"]
                        row["bbox"] = [x + b[0] * sw, y + b[1] * sh, b[2] * sw, b[3] * sh]
                        row["slot"] = index
                    evidence.extend(candidates)
                    values = {r["value"] for r in candidates}
                    if len(values) == 1:
                        state[field] = next(iter(values))
                    else:
                        uncertain.append({"field": field, "slot": index, "reason": slot_error or "区域数字未能唯一识别。"})
                    continue
                matches = self._match_region(crop, [t for t in templates if t["kind"] == slot["kind"]])
                if not matches:
                    uncertain.append({"field": field, "slot": index, "reason": "区域内没有达到阈值的已缓存图标。"})
                    continue
                best = dict(matches[0])
                b = best["bbox"]
                best["bbox"] = [x + b[0] * sw, y + b[1] * sh, b[2] * sw, b[3] * sh]
                alternatives = [m for m in matches[1:5] if best["confidence"] - m["confidence"] < .035]
                best.update(field=field, kind="template_region", slot=current_shop_slot if field == "shop" else index,
                            profile_slot=index, text=best["name"],
                            alternatives=[{k: v for k, v in a.items() if k != "bbox"} for a in alternatives], requires_confirmation=True)
                evidence.append(best)
                if best["confidence"] < .88 or alternatives:
                    uncertain.append({"field": field, "slot": index, "reason": "图标候选相似或分数不足，未写入对局状态。"})
                    continue
                if field == "shop":
                    state["shop"][current_shop_slot] = str(best["entity_id"])
                elif field in ("board", "bench"):
                    state[field].append({"hero_id": best["entity_id"], "stars": None, "item_ids": [], "slot": index})
                    uncertain.append({"field": f"{field}.{len(state[field])-1}.stars", "reason": "头像不能确定星级；装备也需另行确认。"})
                else:
                    state[field].append(best["entity_id"])
        else:
            # Global matches are clickable candidates only. Spatial meaning is unknown.
            priorities = {"hero": 0, "card": 1, "item": 2, "augment": 3}
            scanned_templates = sorted(templates, key=lambda t: priorities.get(t["kind"], 9))[:160]
            matches = self._match_region(image, scanned_templates, exhaustive=True)
            for match in matches[:30]:
                evidence.append({**match, "field": "candidates", "kind": "template_candidate", "text": match["name"],
                                 "alternatives": [], "requires_confirmation": True})
            automatic_shop, shop_evidence = self._automatic_shop(image, lines, entity_evidence, templates)
            for verified in automatic_shop:
                position = verified.get("slot")
                if isinstance(position, int) and 0 <= position < 5:
                    state["shop"][position] = str(verified["hero_id"])
            evidence.extend(shop_evidence)
            if automatic_shop:
                uncertain.append({"field": "shop", "reason": "商店布局、5个名称与至少3个头像一致；仍需确认槽位、星级与未识别卡。"})
        if not templates:
            uncertain.append({"field": "templates", "reason": "本机尚无该模式图标缓存；可运行scripts/download_assets.py。"})
        if not profile:
            uncertain.append({"field": "board", "reason": "未设置棋盘/商店区域；识别到的名字和图标仅列候选，请手动加入并确认。"})
        text_all = " ".join(r["text"] for r in lines)
        screen_type = "augment_selection" if re.search("选择强化|强化符文|强化选择", text_all) else (
            "orange_cards" if "时间卡片" in text_all else "gameplay_candidate" if state["stage"] else "unknown")
        return {"state": state, "evidence": evidence, "uncertain": uncertain, "screen_type": screen_type,
                "image_size": {"width": w, "height": h},
                "capabilities": {"offline": True, "ocr_engine": "tesseract chi_sim+eng" if shutil.which("tesseract") else None,
                                 "template_assets_cached": len(templates), "layout_profile_used": bool(profile),
                                 "global_template_scan_limit": 160, "automatic_shop_requires_five_names_and_three_icons": True,
                                 "automatic_star_detection": False, "automatic_item_attachment": False,
                                 "hidden_information": False, "scores_are_calibrated_probabilities": False}}
