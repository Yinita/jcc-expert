"""Synthetic contract/regression cases; these do not estimate real accuracy."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.card_title_reader import classify_card_screen, inspect_suffix_pixels, parse_roman_suffix, read_card_titles


CARDS = [{"id": str(i), "name": "测试卡 " + tier, "kind": "card"}
         for i, tier in enumerate(("I", "II", "III", "IV"), 1)]


def line(text, box=None):
    return {"text": text, "confidence": .98, "bbox": box or [.2, .3, .6, .2]}


def synthetic_title(count):
    image = np.zeros((200, 500, 3), np.uint8)
    image[65:90, 110:270] = (220, 220, 220)  # Explicit synthetic base-name stand-in.
    for i in range(count):
        image[68:90, 350+i*13:354+i*13] = 255
    return image


class CardTitleReaderTests(unittest.TestCase):
    def test_mixed_unicode_numeral_is_not_normalized_into_exact_iii(self):
        result = parse_roman_suffix("ⅡI")
        self.assertIsNone(result["tier"])
        self.assertEqual(set(result["possible"]), {"II", "III"})
        self.assertEqual(parse_roman_suffix("Ⅳ")["tier"], "IV")

    def test_pixels_resolve_mixed_ocr_without_guessing_from_art(self):
        result = read_card_titles(synthetic_title(2), [line("测试卡ⅡI")], CARDS)
        self.assertEqual([e["entity_id"] for e in result["evidence"]], ["2"])
        self.assertEqual(result["evidence"][0]["method"], "ocr_and_suffix_pixels")
        self.assertFalse(result["evidence"][0]["safe_to_apply"])
        self.assertNotIn("state", result)

    def test_ascii_tier_that_contradicts_pixels_abstains(self):
        result = read_card_titles(synthetic_title(2), [line("测试卡III")], CARDS)
        self.assertFalse(result["evidence"])
        self.assertEqual(result["uncertain"][0]["reason"], "suffix_evidence_conflict")

    def test_digit_alias_requires_pixels(self):
        good = read_card_titles(synthetic_title(1), [line("测试卡1")], CARDS)
        self.assertEqual(good["evidence"][0]["entity_id"], "1")
        blank = read_card_titles(np.zeros((200, 500, 3), np.uint8), [line("测试卡1")], CARDS)
        self.assertFalse(blank["evidence"])

    def test_prose_mentions_are_not_located_card_titles(self):
        cards = [{"id": "a", "name": "同盟药水"}]
        result = read_card_titles(None, [line("时获得1个【同盟药水】。"), line("同盟药水")], cards)
        self.assertEqual(len(result["evidence"]), 1)

    def test_unreadable_or_invalid_crop_abstains_safely(self):
        for crop in (None, np.zeros((3, 3, 3), np.uint8), np.zeros((40, 100), np.uint8)):
            self.assertIsNone(inspect_suffix_pixels(crop)["tier"])
        self.assertFalse(read_card_titles(None, [line("测试卡1", [float("nan"), 0, .2, .2])], CARDS)["evidence"])

    def test_detail_and_challenge_screens_do_not_require_missing_title(self):
        rows = [line(t, [.6, .4+i*.05, .2, .04]) for i, t in enumerate(("时间卡片价值：4000", "时间能量：5点", "尚未拥有这个卡片"))]
        self.assertEqual(classify_card_screen(rows)["menu_type"], "orange_card_detail")
        rows = [line(t) for t in ("维持原状", "接受挑战", "最终进入前3", "总价值")]
        self.assertEqual(classify_card_screen(rows)["context"], "orange_super_time")

    def test_starter_and_reward_menu_anchors(self):
        self.assertEqual(classify_card_screen([line("请选择一套卡组开启金橘之旅！", [.2, .02, .5, .05])])["context"], "orange_loadout")
        rows = [line("传说x1", [.3, .04, .1, .04]), line("史诗x1", [.5, .04, .1, .04]), line("确定", [.4, .85, .1, .05])]
        self.assertEqual(classify_card_screen(rows)["menu_type"], "orange_card_rewards")

    def test_editor_roles_depend_on_visible_boundary_anchor(self):
        rows = [line("出战卡组", [.1, .02, .2, .05]), line("筛选", [.3, .02, .1, .05]),
                line("搜索", [.4, .02, .1, .05]), line("保存", [.8, .02, .1, .05]),
                line("当前：能量×8", [.65, .8, .2, .04]), line("普通卡", [.2, .4, .2, .05]),
                line("普通卡", [.8, .4, .1, .05])]
        result = read_card_titles(None, rows, [{"id": "a", "name": "普通卡"}])
        self.assertEqual([e["role"] for e in result["evidence"]], ["catalog", "selected_deck_card"])

    def test_local_ocr_is_bounded_and_conflict_cannot_majority_vote(self):
        class Local:
            calls = 0
            def read(self, image):
                self.calls += 1
                return [{"text": "测试卡III", "confidence": .99}], None
        backend = Local()
        result = read_card_titles(synthetic_title(2), [line("测试卡ⅡI")], CARDS, backend)
        self.assertEqual(backend.calls, 1)
        self.assertFalse(result["evidence"])
        self.assertEqual(result["uncertain"][0]["reason"], "suffix_evidence_conflict")


if __name__ == "__main__":
    unittest.main()
