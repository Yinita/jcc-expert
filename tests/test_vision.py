"""Functional synthetic tests. These do not measure real-game accuracy."""
from pathlib import Path
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.vision import ScreenshotRecognizer, validate_layout_profile


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.assets = self.root / "assets"
        self.data.mkdir()
        self.assets.mkdir()
        facts = {"champion_star_form_records": [{"official_id": "11111", "name": "Annie", "observed_star_level": 1,
                                                 "shows_in_official_gallery": True}], "items": [], "augments": []}
        (self.data / "nature_facts.json").write_text(json.dumps(facts))
        self.recognizer = ScreenshotRecognizer(self.data, self.assets)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, size=(640, 360)):
        path = self.root / "screen.png"
        Image.new("RGB", size, (24, 28, 35)).save(path)
        return path

    def add_template(self, entity_id="11111", raw=None):
        if raw is None:
            rng = np.random.default_rng(2026)
            raw = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
            cv2.circle(raw, (30, 30), 20, (255, 0, 10), 4)
        Image.fromarray(raw).save(self.assets / "icon.png")
        (self.assets / "manifest.json").write_text(json.dumps({"assets": [{"mode": "nature", "kind": "hero",
            "entity_id": entity_id, "name": "Annie", "path": "icon.png"}]}))
        return raw

    def test_profile_rejects_invalid_boundaries(self):
        for bbox in ([-.1, 0, .2, .2], [.9, .9, .2, .2], [0, 0, 0, .2], [0, 0, float("nan"), .2]):
            with self.assertRaises(ValueError):
                validate_layout_profile({"slots": [{"field": "board", "bbox": bbox}]})

    def test_unsupported_mode_and_tiny_image_rejected(self):
        with self.assertRaises(ValueError):
            self.recognizer.recognize(self.image(), "pc-tft")
        with self.assertRaises(ValueError):
            self.recognizer.recognize(self.image((16, 16)), "nature")

    def test_names_anywhere_do_not_become_board(self):
        lines = [{"text": "Annie", "compact_text": "Annie", "confidence": .98, "bbox": [.2, .2, .1, .1]}]
        with patch.object(self.recognizer, "_ocr", return_value=(lines, None)):
            result = self.recognizer.recognize(self.image(), "nature")
        self.assertEqual(result["state"]["board"], [])
        self.assertFalse(result["state"]["confirmed"])
        self.assertEqual([r["entity_id"] for r in result["evidence"] if r["kind"] == "ocr_entity_candidate"], ["11111"])

    def test_conflicting_scalar_not_invented(self):
        lines = [{"text": text, "compact_text": text, "confidence": .98, "bbox": [0, i*.1, .3, .05]}
                 for i, text in enumerate(["GOLD: 35", "GOLD: 80", "HP: 99", "LEVEL: 7", "STAGE 3-2"])]
        with patch.object(self.recognizer, "_ocr", return_value=(lines, None)):
            result = self.recognizer.recognize(self.image(), "nature")
        self.assertIsNone(result["state"]["gold"])
        self.assertEqual(result["state"]["hp"], 99)
        self.assertEqual(result["state"]["stage"], "3-2")

    def test_card_effect_round_is_not_current_stage(self):
        lines = [{"text": "1-4", "compact_text": "1-4", "confidence": .98, "bbox": [.3, .5, .1, .1]}]
        with patch.object(self.recognizer, "_ocr", return_value=(lines, None)):
            result = self.recognizer.recognize(self.image(), "nature")
        self.assertIsNone(result["state"]["stage"])

    def test_template_slot_sets_hero_but_not_stars(self):
        raw = self.add_template()
        im = Image.open(self.image())
        im.paste(Image.fromarray(raw), (100, 80))
        im.save(self.root / "screen.png")
        profile = {"aspect_ratio": 640/360, "slots": [{"field": "board", "bbox": [100/640, 80/360, 64/640, 64/360]}]}
        with patch.object(self.recognizer, "_ocr", return_value=([], None)):
            result = self.recognizer.recognize(self.root / "screen.png", "nature", profile)
        self.assertEqual(result["state"]["board"][0]["hero_id"], "11111")
        self.assertIsNone(result["state"]["board"][0]["stars"])
        self.assertEqual(result["state"]["board"][0]["item_ids"], [])

    def test_global_template_is_clickable_candidate_only(self):
        raw = self.add_template()
        im = Image.open(self.image())
        im.paste(Image.fromarray(raw), (100, 80))
        im.save(self.root / "screen.png")
        with patch.object(self.recognizer, "_ocr", return_value=([], None)):
            result = self.recognizer.recognize(self.root / "screen.png", "nature")
        self.assertFalse(result["state"]["board"])
        matches = [r for r in result["evidence"] if r["kind"] == "template_candidate"]
        self.assertEqual(matches[0]["entity_id"], "11111")
        self.assertGreater(matches[0]["confidence"], .95)

    def test_profile_aspect_mismatch_does_not_assign_board(self):
        self.add_template()
        profile = {"aspect_ratio": 1, "slots": [{"field": "board", "bbox": [.1, .1, .2, .2]}]}
        with patch.object(self.recognizer, "_ocr", return_value=([], None)):
            result = self.recognizer.recognize(self.image(), "nature", profile)
        self.assertFalse(result["capabilities"]["layout_profile_used"])
        self.assertFalse(result["state"]["board"])

    def test_shop_contract_keeps_unknown_profile_slots_and_relative_order(self):
        raw = self.add_template()
        im = Image.open(self.image())
        im.paste(Image.fromarray(raw), (100, 80))
        im.paste(Image.fromarray(raw), (300, 80))
        path = self.root / "screen.png"
        im.save(path)
        slots = [{"field": "board", "bbox": [.8, .6, .1, .1]}]
        for x in (100, 200, 300):
            slots.append({"field": "shop", "bbox": [x/640, 80/360, 64/640, 64/360]})
        with patch.object(self.recognizer, "_ocr", return_value=([], None)):
            result = self.recognizer.recognize(path, "nature", {"slots": slots})
        self.assertEqual(result["state"]["shop"], ["11111", None, "11111", None, None])

    def test_shop_contract_keeps_automatic_positions(self):
        verified = [{"hero_id": "11111", "slot": 1}, {"hero_id": "22222", "slot": 3}, {"hero_id": "33333", "slot": 4}]
        with patch.object(self.recognizer, "_ocr", return_value=([], None)), \
             patch.object(self.recognizer, "_automatic_shop", return_value=(verified, [])):
            result = self.recognizer.recognize(self.image(), "nature")
        self.assertEqual(result["state"]["shop"], [None, "11111", None, "22222", "33333"])

    def test_automatic_shop_requires_names_layout_and_icons(self):
        image = np.full((600, 1000, 3), 25, dtype=np.uint8)
        templates, names = [], []
        for i in range(5):
            icon = np.random.default_rng(i+10).integers(0, 255, (64, 64, 3), dtype=np.uint8)
            center = 180+i*160
            image[440:504, center-32:center+32] = icon
            templates.append({"entity_id": str(i), "name": f"Hero{i}", "kind": "hero", "gray": cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)})
            names.append({"entity_id": str(i), "name": f"Hero{i}", "entity_type": "hero", "alternatives": [],
                          "text": f"Hero{i}", "confidence": .99, "bbox": [(center-30)/1000, 520/600, .06, .04]})
        labels = [{"text": "SHOP", "confidence": .99, "bbox": [0, .9, .1, .05]}]
        shop, evidence = self.recognizer._automatic_shop(image, labels, names, templates)
        self.assertEqual([r["hero_id"] for r in shop], [str(i) for i in range(5)])
        self.assertEqual(len(evidence), 5)
        self.assertEqual(self.recognizer._automatic_shop(image, [], names, templates), ([], []))

    @unittest.skipUnless(shutil.which("tesseract"), "requires local tesseract")
    def test_real_tesseract_synthetic_labeled_text(self):
        fonts = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")]
        font_path = next((p for p in fonts if p.exists()), None)
        if not font_path:
            self.skipTest("No suitable test font installed")
        font = ImageFont.truetype(str(font_path), 55)
        im = Image.new("RGB", (1000, 450), "white")
        draw = ImageDraw.Draw(im)
        for i, text in enumerate(["GOLD: 45", "HP: 87", "LEVEL: 6", "STAGE 3-2"]):
            draw.text((40, 15+i*100), text, font=font, fill="black")
        path = self.root / "ocr.png"
        im.save(path)
        result = self.recognizer.recognize(path, "nature")
        if any(r.get("reason") == "ocr_failed_or_language_pack_missing" for r in result["uncertain"]):
            self.skipTest("Tesseract language pack missing")
        self.assertEqual({k: result["state"][k] for k in ("gold", "hp", "level", "stage")},
                         {"gold": 45, "hp": 87, "level": 6, "stage": "3-2"})

    def test_official_portrait_synthetic_composite(self):
        manifest_path = ROOT / "app/assets/manifest.json"
        if not manifest_path.exists():
            self.skipTest("Run download_assets.py to cache official test portraits")
        entries = json.loads(manifest_path.read_text()).get("assets", [])
        row = next((r for r in entries if r["kind"] == "hero" and r["mode"] == "nature"), None)
        if not row:
            self.skipTest("No official nature portrait cached")
        raw = np.asarray(Image.open(ROOT / "app/assets" / row["path"]).convert("RGB").resize((64, 64)))
        self.add_template(row["entity_id"], raw)
        im = Image.open(self.image())
        im.paste(Image.fromarray(raw), (100, 80))
        im.save(self.root / "screen.png")
        with patch.object(self.recognizer, "_ocr", return_value=([], None)):
            result = self.recognizer.recognize(self.root / "screen.png", "nature", {"slots": [
                {"field": "shop", "bbox": [100/640, 80/360, 64/640, 64/360]}]})
        self.assertEqual(result["state"]["shop"], [row["entity_id"], None, None, None, None])
        self.assertFalse(result["state"]["confirmed"])

    def test_asset_downloader_rejects_untrusted_urls(self):
        spec = importlib.util.spec_from_file_location("asset_downloader", ROOT / "scripts/download_assets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for url in ("http://game.gtimg.cn/images/lol/act/jkzlk/x.png", "https://example.com/x.png",
                    "https://game.gtimg.cn@evil.test/images/lol/act/jkzlk/x.png", "file:///tmp/x.png"):
            with self.assertRaises(ValueError):
                module.validate_url(url)


if __name__ == "__main__":
    unittest.main()
