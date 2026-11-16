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
import os
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
    def __init__(self, data_dir: Path, assets_dir: Path, field_model_dir=None):
        # Large screenshots otherwise oversubscribe OpenCV's default CPU pool.
        # A small fixed pool also bounds concurrent local upload workloads.
        try:
            threads = max(1, min(4, int(os.environ.get("JCC_CV_THREADS", "2"))))
        except ValueError:
            threads = 2
        cv2.setNumThreads(threads)
        self._ocr_backend = None
        if os.environ.get("JCC_OCR_BACKEND", "auto") != "tesseract":
            try:
                from app.ocr_backend import get_ocr_backend
                self._ocr_backend = get_ocr_backend()
            except (ImportError, OSError):
                pass
        self._last_ocr_engine = "tesseract chi_sim+eng"
        from app.field_model import FieldModel
        self._field_model = FieldModel(field_model_dir or Path(__file__).resolve().parents[1]/"var/recognition_models")
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
        if self._ocr_backend is not None:
            lines, error = self._ocr_backend.read(image)
            if not error:
                self._last_ocr_engine = self._ocr_backend.name
                return self._ocr_small_ui(image, lines), None
        self._last_ocr_engine = "tesseract chi_sim+eng"
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
                                  env={**os.environ, "OMP_THREAD_LIMIT": "1"},
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

    def _ocr_small_ui(self, image, whole_lines):
        """Bounded extra passes for small phone HUD text, without manual boxes.

        These regions are fixed UI search areas; they do not use ground-truth
        values. All resulting coordinates return to the original image frame.
        """
        h,w=image.shape[:2]
        if self._ocr_backend is None or h<300 or w<700 or w>1600 or not 1.85<=w/h<=2.6:
            return whole_lines
        merged=list(whole_lines)
        for x,y,bw,bh in ((.25,0.,.50,.20),(0.,.70,.20,.30),(.80,.68,.20,.32)):
            left,top=int(x*w),int(y*h);right,bottom=round((x+bw)*w),round((y+bh)*h)
            crop=image[top:bottom,left:right]
            scale=min(3.,1100/max(1,crop.shape[1]))
            crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            rows,error=self._ocr_backend.read(crop)
            if error:
                continue
            for row in rows:
                b=row["bbox"]
                mapped={**row,"bbox":[left/w+b[0]*(right-left)/w,top/h+b[1]*(bottom-top)/h,
                                       b[2]*(right-left)/w,b[3]*(bottom-top)/h],"pass":"automatic_small_ui"}
                duplicate=None
                for index,old in enumerate(merged):
                    if _normal_text(old["text"])!=_normal_text(mapped["text"]):continue
                    a=old["bbox"];bb=mapped["bbox"]
                    ix=max(0.,min(a[0]+a[2],bb[0]+bb[2])-max(a[0],bb[0]));iy=max(0.,min(a[1]+a[3],bb[1]+bb[3])-max(a[1],bb[1]))
                    if ix*iy/max(min(a[2]*a[3],bb[2]*bb[3]),1e-9)>.5:
                        duplicate=index;break
                if duplicate is None:merged.append(mapped)
                elif mapped["confidence"]>merged[duplicate]["confidence"]:merged[duplicate]=mapped
        return merged

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

    def _numeric_region(self, image, field):
        """Read an explicitly user-calibrated numeric ROI with two OCR passes.

        This does not locate numbers or infer their meaning from the full image.
        Agreement is a rejection guard, not a calibrated accuracy guarantee.
        """
        if not shutil.which("tesseract") or field not in SCALAR_FIELDS:
            return [], "numeric_ocr_unavailable"
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        scale = min(5., max(2., 120. / max(1, gray.shape[0])))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        if float(np.median(gray)) < 128:
            gray = cv2.bitwise_not(gray)
        ok, encoded = cv2.imencode(".png", gray)
        if not ok:
            return [], "image_encoding_failed"
        outputs = []
        for psm in ("7", "8"):
            try:
                proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", psm,
                                       "-c", "tessedit_char_whitelist=0123456789-", "tsv"],
                                      input=encoded.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=5, env={**os.environ, "OMP_THREAD_LIMIT": "1"}, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return [], "numeric_ocr_failed"
            words = []
            for row in csv.DictReader(StringIO(proc.stdout.decode("utf-8", "replace")), delimiter="\t"):
                try:
                    if row.get("text", "").strip() and float(row.get("conf", -1)) >= 0:
                        words.append((row["text"].strip(), float(row["conf"]) / 100))
                except (TypeError, ValueError):
                    continue
            text = "".join(w[0] for w in words)
            if not words or not re.fullmatch(r"[1-9]-[1-7]" if field == "stage" else r"\d{1,3}", text):
                return [], "numeric_ocr_no_unique_value"
            confidence = min(w[1] for w in words)
            if confidence < .60:
                return [], "numeric_ocr_low_confidence"
            outputs.append((text, confidence))
        if outputs[0][0] != outputs[1][0]:
            return [], "numeric_ocr_disagreement"
        return [{"text": outputs[0][0], "compact_text": outputs[0][0],
                 "confidence": min(x[1] for x in outputs), "bbox": [0., 0., 1., 1.],
                 "method": "user_roi_two_pass_numeric_ocr"}], None

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
            if exhaustive and entry.get("kind")=="card":
                widths += [112,128,144,160]
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
            if len(key) >= 2 or (len(key) == 1 and row["kind"] == "hero"):
                names[key].append(row)
        evidence = []
        for line in lines:
            if line["confidence"] < .60:
                continue
            compact = _normal_text(line["compact_text"])
            # Longer names take precedence over their shorter substrings.
            selected = []
            for name in sorted(names, key=len, reverse=True):
                if len(name) == 1 and (compact != name or line["confidence"] < .97):
                    continue
                # Do not reinterpret a longer Roman numeral as a shorter card tier.
                start = compact.find(name)
                after = compact[start+len(name):start+len(name)+1] if start >= 0 else ""
                if name.endswith("I") and after in ("I", "V", "X"):
                    continue
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
    def _complete_shop_grid(lines, entity_evidence):
        """Five exact names plus XP/refresh controls can identify a top shop too.

        All five slots must be observed. Four-name rows use the separately
        guarded bottom-layout rule, so a missing first slot never shifts IDs.
        """
        def side_control(row, text):
            return text in _normal_text(row["text"]) and (row["bbox"][0] < .25 or row["bbox"][0] > .75)
        if not any(side_control(r,"购买经验") for r in lines) or not any(side_control(r,"刷新") for r in lines):
            return [], []
        names=[r for r in entity_evidence if r["entity_type"]=="hero" and not r.get("alternatives")
               and r["confidence"]>=.92 and _normal_text(r["text"])==_normal_text(r["name"])]
        for anchor in names:
            row=sorted([r for r in names if abs(r["bbox"][1]-anchor["bbox"][1])<.035],key=lambda r:r["bbox"][0])
            row=list({tuple(round(v,3) for v in r["bbox"]):r for r in row}.values())
            if len(row)!=5:
                continue
            xs=[r["bbox"][0] for r in row];gaps=np.diff(xs)
            if min(gaps)<.07 or max(gaps)>.23 or max(gaps)/min(gaps)>1.16:
                continue
            if xs[0]<.08 or xs[-1]+row[-1]["bbox"][2]>.99:
                continue
            return ([{"hero_id":r["entity_id"],"slot":i} for i,r in enumerate(row)],
                    [{**r,"field":"shop","kind":"complete_shop_name_grid","slot":i,
                      "requires_confirmation":True,"position_inferred_from_ui_grid":True} for i,r in enumerate(row)])
        return [], []

    @staticmethod
    def _bottom_shop_grid(lines, entity_evidence):
        """Read a strongly anchored bottom UI grid; unreadable slots stay unknown."""
        xp = [r for r in lines if "购买经验" in _normal_text(r["text"])
              and r["bbox"][0] < .30 and r["bbox"][1] > .70]
        refresh = [r for r in lines if _normal_text(r["text"]) == "刷新"
                   and r["bbox"][0] < .30 and r["bbox"][1] > .75]
        if not xp or not refresh:
            return [], []
        names = [r for r in entity_evidence if r["entity_type"] == "hero" and not r.get("alternatives")
                 and r["confidence"] >= .92 and r["bbox"][1] > .80
                 and _normal_text(r["text"]) == _normal_text(r["name"])]
        for anchor in names:
            row = sorted([r for r in names if abs(r["bbox"][1]-anchor["bbox"][1]) < .025], key=lambda r:r["bbox"][0])
            row = list({tuple(round(v, 3) for v in r["bbox"]):r for r in row}.values())
            if not 3 <= len(row) <= 5:
                continue
            xs = [r["bbox"][0] for r in row]
            pitch = float(min(np.diff(xs)))
            if not .07 <= pitch <= .20:
                continue
            indices = [round((x-xs[0])/pitch) for x in xs]
            if len(set(indices)) != len(indices) or max(indices) > 4:
                continue
            if any(abs((x-xs[0])/pitch-i) > .12 for x,i in zip(xs,indices)):
                continue
            if not any(.65 <= (xs[0]-a["bbox"][0])/pitch <= 1.4 for a in xp):
                continue  # A missing first slot would make the offset ambiguous.
            verified, evidence = [], []
            for r, slot in zip(row, indices):
                verified.append({"hero_id":r["entity_id"], "slot":slot})
                evidence.append({**r, "field":"shop", "kind":"anchored_shop_name_ocr", "slot":slot,
                                 "position_inferred_from_ui_grid":True, "requires_confirmation":True})
            return verified, evidence
        return [], []

    @staticmethod
    def _bottom_gold(lines):
        """Support the bare counter only beside a verified bottom shop header."""
        levels = [r for r in lines if re.fullmatch(r"\d{1,2}级", _normal_text(r["text"]))
                  and r["bbox"][0] < .35 and r["bbox"][1] > .65]
        xp = any("购买经验" in _normal_text(r["text"]) and r["bbox"][0] < .30
                 and r["bbox"][1] > .70 for r in lines)
        if not levels or not xp:
            return []
        candidates = [r for r in lines if re.fullmatch(r"\d{1,3}", r["text"].strip())
                      and r["confidence"] >= .95 and .42 <= r["bbox"][0] <= .56
                      and any(abs(r["bbox"][1]-lv["bbox"][1]) < .035 for lv in levels)]
        if len(candidates) != 1:
            return []
        r = candidates[0]
        return [{**r, "field":"gold", "kind":"anchored_bottom_gold_ocr", "value":int(r["text"]),
                 "requires_confirmation":True, "position_inferred_from_ui_grid":True}]

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
                if not match and key == "level":
                    suffix = re.fullmatch(r"\s*(\d{1,2})\s*级\s*", line["text"])
                    x, y, bw, bh = line["bbox"]
                    nearby_xp = any("购买经验" in _normal_text(r["text"])
                                    and abs(r["bbox"][0] - x) < .15
                                    and 0 < r["bbox"][1] - y < .20 for r in lines)
                    if suffix and (allow_bare or (x < .40 and y > .60 and nearby_xp)):
                        match = suffix
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

    @staticmethod
    def _global_templates(templates, context, evidence, lines):
        """Focus visual search when text already locates a menu or a card row."""
        strong={r["entity_id"] for r in evidence if r.get("confidence",0)>=.90 and not r.get("alternatives")}
        cards_context=context in ("orange_loadout","inventory")
        if cards_context:
            text=" ".join(_normal_text(r["text"]) for r in lines)
            for entry in templates:
                if entry.get("kind")!="card":continue
                base=re.sub(r"[IVX]+$","",_normal_text(entry.get("name","")))
                if len(base)>=3 and base in text:strong.add(entry["entity_id"])
            relevant=[t for t in templates if t.get("kind")=="card" and t["entity_id"] in strong]
            return relevant[:80] if relevant else [t for t in templates if t.get("kind")=="card"][:160]
        if len(strong)>=3:
            relevant=[t for t in templates if t["entity_id"] in strong]
            if relevant:return relevant[:80]
        priorities={"hero":0,"card":1,"item":2,"augment":3}
        return sorted(templates,key=lambda t:priorities.get(t["kind"],9))[:160]

    @staticmethod
    def _screen_context(lines, mode):
        header = " ".join(_normal_text(r["text"]) for r in lines if r["bbox"][1] < .25)
        text = " ".join(_normal_text(r["text"]) for r in lines)
        if mode == "orange":
            if any(word in header for word in ("卡组方案", "出战卡组", "初始卡组", "编辑卡组", "选择卡组")):
                return "orange_loadout"
            if any(word in header for word in ("时间卡册", "卡册", "卡片修复", "修复卡片", "卡片详情")):
                return "inventory"
            if "超级时间" in text:
                return "orange_super_time"
        if any(word in header for word in ("选择强化", "强化选择")):
            return "augment_selection"
        return "unknown"

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
        context = self._screen_context(lines, mode)
        evidence = [{"field": "text", "kind": "ocr_text", "text": r["text"], "confidence": round(r["confidence"], 4), "bbox": r["bbox"]} for r in lines]
        uncertain = [{"field": "state", "reason": "截图识别尚未确认；相似度和OCR分数不是校准后的准确率。"}]
        if error:
            uncertain.append({"field": "ocr", "reason": error})
        scalar = self._scalar_candidates(lines)
        if not any(r["field"] == "gold" for r in scalar):
            scalar.extend(self._bottom_gold(lines))
        learned=[]
        if context not in ("orange_loadout","inventory"):
            learned_context="board" if context=="unknown" and any(r["field"]=="stage" for r in scalar) else context
            learned=self._field_model.predict(lines,image.shape,mode,learned_context)
            scalar.extend(learned)
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
                    slot_lines, slot_error = self._numeric_region(crop, field)
                    if not slot_lines:
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
            scanned_templates = self._global_templates(templates,context,entity_evidence,lines)
            matches = self._match_region(image, scanned_templates, exhaustive=True)
            for match in matches[:30]:
                evidence.append({**match, "field": "candidates", "kind": "template_candidate", "text": match["name"],
                                 "alternatives": [], "requires_confirmation": True})
            automatic_shop, shop_evidence = self._automatic_shop(image, lines, entity_evidence, templates)
            if not automatic_shop:
                automatic_shop, shop_evidence = self._complete_shop_grid(lines, entity_evidence)
            if not automatic_shop:
                automatic_shop, shop_evidence = self._bottom_shop_grid(lines, entity_evidence)
            for verified in automatic_shop:
                position = verified.get("slot")
                if isinstance(position, int) and 0 <= position < 5:
                    state["shop"][position] = str(verified["hero_id"])
            evidence.extend(shop_evidence)
            if automatic_shop:
                uncertain.append({"field": "shop", "reason": "根据界面锚点和可见名字定位商店；槽位及未识别内容仍需确认。"})
        if not templates:
            uncertain.append({"field": "templates", "reason": "本机尚无该模式图标缓存；可运行scripts/download_assets.py。"})
        if profile and not any(s["field"] == "shop" for s in profile["slots"]):
            # A numeric-only calibration must not disable independent shop OCR.
            automatic_shop, shop_evidence = self._automatic_shop(image, lines, entity_evidence, templates)
            if not automatic_shop:
                automatic_shop, shop_evidence = self._complete_shop_grid(lines, entity_evidence)
            if not automatic_shop:
                automatic_shop, shop_evidence = self._bottom_shop_grid(lines, entity_evidence)
            for verified in automatic_shop:
                position = verified.get("slot")
                if isinstance(position, int) and 0 <= position < 5:
                    state["shop"][position] = str(verified["hero_id"])
            evidence.extend(shop_evidence)
        if not profile:
            uncertain.append({"field": "board", "reason": "未设置棋盘/商店区域；识别到的名字和图标仅列候选，请手动加入并确认。"})
        if context in ("orange_loadout", "inventory"):
            for field in SCALAR_FIELDS:
                state[field] = None
            state["shop"] = [None] * 5
            uncertain.append({"field":"state", "reason":"这是局外卡片页面；卡片生效回合和金橘不能当作当前对局回合或金币。"})
        text_all = " ".join(r["text"] for r in lines)
        screen_type = context if context != "unknown" else ("board" if state["stage"] else "unknown")
        return {"state": state, "evidence": evidence, "uncertain": uncertain, "screen_type": screen_type,
                "image_size": {"width": w, "height": h},
                "capabilities": {"offline": True, "ocr_engine": self._last_ocr_engine,
                                 "template_assets_cached": len(templates), "layout_profile_used": bool(profile),
                                 "global_template_scan_limit": 160,
                                 "automatic_shop_rules": ["five_names_three_icons", "complete_top_or_bottom_name_grid", "anchored_bottom_name_grid"],
                                 "automatic_star_detection": False, "automatic_item_attachment": False,
                                 "supervised_field_predictions": len(learned),
                                 "hidden_information": False, "scores_are_calibrated_probabilities": False}}
