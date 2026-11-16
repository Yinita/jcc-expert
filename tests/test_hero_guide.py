import copy
import importlib.util
import json
from pathlib import Path
import unittest

_path = Path(__file__).resolve().parents[1] / "scripts/build_hero_guide.py"
_spec = importlib.util.spec_from_file_location("hero_guide_builder", _path)
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)
BASE, artifact_suggestions, build_guide, position = (_builder.BASE, _builder.artifact_suggestions,
                                                   _builder.build_guide, _builder.position)
_fetch_spec = importlib.util.spec_from_file_location("hero_guide_fetcher", _path.with_name("fetch_hero_guide_statistics.py"))
_fetcher = importlib.util.module_from_spec(_fetch_spec)
_fetch_spec.loader.exec_module(_fetcher)


class HeroGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = build_guide()

    def test_all_gallery_base_forms_are_present_and_no_star_duplicates(self):
        for mode, filename in [("nature", "nature_facts.json"), ("orange", "orange_base_facts.json")]:
            facts = json.loads((BASE / "app/data" / filename).read_text())
            expected = {str(h["official_id"]) for h in facts["champion_star_form_records"]
                        if h.get("observed_star_level") == 1 and h.get("shows_in_official_gallery")}
            heroes = self.guide["modes"][mode]["heroes"]
            self.assertEqual(expected, {h["id"] for h in heroes})
            self.assertEqual(len(expected), len(heroes))

    def test_official_loadouts_keep_repeated_items_and_own_position(self):
        facts = json.loads((BASE / "app/data/nature_facts.json").read_text())
        heroes = {h["id"]: h for h in self.guide["modes"]["nature"]["heroes"]}
        checked_duplicate = False
        for lineup in facts["official_published_lineups"]:
            for unit in lineup["main_board"]:
                if unit["hero_id"] not in heroes:
                    continue
                actual = next((b for b in heroes[unit["hero_id"]]["builds"]
                               if b["kind"] == "official_lineup" and b["id"] == str(lineup["id"])), None)
                if actual is None:  # UI intentionally caps the number of examples.
                    continue
                self.assertEqual(unit["item_ids"], actual["item_ids"])
                self.assertEqual(position(unit["position"]), actual["position"])
                self.assertEqual(lineup["source_url"], actual["source"]["url"])
                if len(set(unit["item_ids"])) != len(unit["item_ids"]):
                    checked_duplicate = True
        self.assertTrue(checked_duplicate)

    def test_every_referenced_item_exists_and_native_emblems_excluded(self):
        for data in self.guide["modes"].values():
            items = {i["id"]: i for i in data["items"]}
            for hero in data["heroes"]:
                native = {t["id"] for t in hero["traits"]}
                names = {t["name"] for t in hero["traits"]}
                for build in hero["builds"]:
                    self.assertTrue(set(build["item_ids"]) <= items.keys())
                for pick in hero["artifacts"] + hero["emblems"]:
                    self.assertIn(pick["item_id"], items)
                    self.assertTrue(pick["conditions"])
                    self.assertTrue(pick["reason"])
                for pick in hero["emblems"]:
                    item = items[pick["item_id"]]
                    self.assertEqual(item["category"], "emblem")
                    self.assertFalse(native.intersection(item["trait_ids"]))
                    self.assertNotIn(item["name"].removesuffix("纹章"), names)

    def test_position_rejects_invalid_and_preserves_one_based_rows(self):
        self.assertEqual(position("1,7"), {"row": 1, "col": 7})
        for value in ("0,1", "5,1", "1,8", "1,0", "wrong", None):
            self.assertIsNone(position(value))
        for data in self.guide["modes"].values():
            for hero in data["heroes"]:
                for cell in hero["positioning"]["recommended_cells"]:
                    self.assertIn(cell["row"], range(1, 5))
                    self.assertIn(cell["col"], range(1, 8))

    def test_control_artifact_requires_explicit_stun_and_no_invented_rates(self):
        data = self.guide["modes"]["nature"]
        hero = copy.deepcopy(data["heroes"][0])
        hero["role"] = {"id": "ap", "frontline": False}
        no_stun = artifact_suggestions(hero, data["items"], {"skillDesc": "将敌人击飞，造成魔法伤害。"}, {})
        explicit = artifact_suggestions(hero, data["items"], {"skillDesc": "将敌人晕眩，造成魔法伤害。"}, {})
        self.assertNotIn("6079", {r["item_id"] for r in no_stun})
        self.assertIn("6079", {r["item_id"] for r in explicit})
        for mode in self.guide["modes"].values():
            for h in mode["heroes"]:
                if h["regular_shop_unit"] and not h["role"].get("ambiguous"):
                    self.assertTrue(h["builds"])
                elif h["regular_shop_unit"]:
                    self.assertFalse(any(b["kind"] == "mechanic" for b in h["builds"]))
                    self.assertFalse(h["emblems"])
                else:
                    self.assertFalse(h["builds"])
                    self.assertFalse(h["artifacts"])
                    self.assertFalse(h["emblems"])
                self.assertNotIn("win_rate", h)
                if h["statistics"]:
                    self.assertEqual(h["statistics"]["kind"], "third_party_observational")
                    for combo in h["statistics"]["combos"]:
                        self.assertGreaterEqual(combo["sample_count"], 100)
                        self.assertGreaterEqual(combo["first_rate"], 0)
                        self.assertLessEqual(combo["first_rate"], 100)

    def test_local_icons_are_existing_portable_assets(self):
        for mode in self.guide["modes"].values():
            for entity in mode["heroes"] + mode["items"]:
                if entity["icon"]:
                    self.assertTrue(entity["icon"].startswith("assets/"))
                    self.assertTrue((BASE / "app" / entity["icon"]).is_file())

    def test_no_mana_passive_carries_do_not_get_mana_engine(self):
        for mode in self.guide["modes"].values():
            for hero in mode["heroes"]:
                if hero["regular_shop_unit"] and not hero["stats"].get("max_mana"):
                    for build in hero["builds"]:
                        if build["kind"] == "mechanic":
                            self.assertNotIn("2004", build["item_ids"])
                            self.assertNotIn("2022", build["item_ids"])
                            self.assertNotIn("2014", build["item_ids"])
                    self.assertNotIn("6058", {a["item_id"] for a in hero["artifacts"]})

    def test_fifteen_real_hero_role_regressions(self):
        # Expectations come from each concrete official skill, not profession
        # names. Same-name units are intentionally tested in both modes.
        cases = [
            ("nature", "11500", "奥恩", "tank", "magic", False),
            ("nature", "14503", "阿木木", "tank", "magic", False),
            ("nature", "12512", "凯尔", "ap", "magic", False),
            ("nature", "12514", "提莫", "ap", "magic", False),
            ("nature", "14505", "瑟提", "tank", "physical", True),
            ("orange", "12407", "提莫", "ap", "magic", False),
            ("orange", "11406", "克格莫", "ap", "magic", False),
            ("orange", "15271", "吉格斯", "ap", "magic", False),
            ("orange", "12404", "崔斯特", "ap", "magic", False),
            ("orange", "15404", "易", "ap", "magic", False),
            ("orange", "15405", "凯尔", "ad", "mixed", True),
            ("orange", "14352", "布隆", "tank", "magic", False),
            ("orange", "14343", "内瑟斯", "tank", "magic", False),
            ("orange", "15279", "瑟提", "ap", "magic", False),
            ("orange", "15412", "阿木木", "tank", "magic", False),
        ]
        for mode, id, name, role, damage, ambiguous in cases:
            with self.subTest(mode=mode, hero=id):
                hero = next(h for h in self.guide["modes"][mode]["heroes"] if h["id"] == id)
                self.assertEqual(hero["name"], name)
                self.assertEqual(hero["role"]["id"], role)
                self.assertEqual(hero["role"]["damage_profile"], damage)
                self.assertEqual(hero["role"]["ambiguous"], ambiguous)
                if damage == "magic":
                    for build in hero["builds"]:
                        if build["kind"] == "mechanic":
                            self.assertNotIn("2037", build["item_ids"])

    def test_profession_kind_and_none_are_preserved_and_missing_trait_kept(self):
        for mode, file in [("nature", "nature_facts.json"), ("orange", "orange_base_facts.json")]:
            facts = json.loads((BASE / "app/data" / file).read_text())
            trait_map = {(t["kind"], str(t["id"])): t for t in facts["traits"]}
            for hero in self.guide["modes"][mode]["heroes"]:
                if hero["official_class_raw"] in ("0", "-1"):
                    self.assertEqual(hero["profession_status"], "none")
                    self.assertFalse([t for t in hero["traits"] if t["kind"] == "class"])
                for trait in hero["traits"]:
                    expected = trait_map.get((trait["kind"], trait["id"]))
                    if expected:
                        self.assertTrue(trait["verified"])
                        self.assertEqual(trait["name"], expected["name"])
                    else:
                        self.assertFalse(trait["verified"])
                        self.assertIn(trait["id"], trait["name"])
        orange = {h["id"]: h for h in self.guide["modes"]["orange"]["heroes"]}
        self.assertIn(("origin", "482", False), [(t["kind"], t["id"], t["verified"]) for t in orange["15404"]["traits"]])
        self.assertIn(("origin", "483", False), [(t["kind"], t["id"], t["verified"]) for t in orange["15405"]["traits"]])

    def test_no_cast_synergy_emblems_for_manaless_passives(self):
        for data in self.guide["modes"].values():
            items = {i["id"]: i for i in data["items"]}
            for hero in data["heroes"]:
                if not hero["stats"].get("max_mana"):
                    for entry in hero["emblems"]:
                        self.assertNotIn(items[entry["item_id"]]["name"].removesuffix("纹章"), {"法师", "神谕", "神谕者", "耀光使"})

    def test_review_does_not_apply_to_a_new_source_snapshot(self):
        reference = json.loads((BASE / "app/data/hero_guide_reference.json").read_text())
        facts = json.loads((BASE / "app/data/orange_base_facts.json").read_text())
        hero = next(h for h in facts["champion_star_form_records"] if h["official_id"] == "12407")
        raw = reference["modes"]["orange"]["herourl"]["data"]["12407"]
        result = _builder.infer_role(hero, raw, [], mode="orange", source_sha256="a-different-snapshot")
        self.assertFalse(result["reviewed"])
        self.assertTrue(result["ambiguous"])
        self.assertIsNone(result["review_snapshot_sha256"])

    def test_control_trigger_distinguishes_applying_from_benefiting(self):
        heroes = {h["id"]: h for h in self.guide["modes"]["nature"]["heroes"]}
        for id in ["11502", "12501"]:
            self.assertIn("6079", {i["item_id"] for i in heroes[id]["artifacts"]})
        elise = next(h for h in self.guide["modes"]["orange"]["heroes"] if h["id"] == "14366")
        self.assertNotIn("6079", {i["item_id"] for i in elise["artifacts"]})
        jayce = next(h for h in self.guide["modes"]["orange"]["heroes"] if h["id"] == "15402")
        self.assertNotIn("6076", {i["item_id"] for i in jayce["artifacts"]})

    def test_statistical_snapshot_rejects_rare_and_unmapped_equipment(self):
        def row(id, ids, n, rate):
            return {"id": id, "equips": [{"id": i} for i in ids], "sampleCount": n,
                    "topRate": rate, "top4Rate": 60, "avgPlacement": 3.8}
        rows = [row("rare", [1, 2, 3], 2, 100), row("mapped", [1, 2, 3], 500, 15),
                row("bad_item", [1, 2, 9], 1000, 80), row("duplicate", [1, 1, 2], 150, 20),
                row("bad_percent", [1, 2, 3], 500, 120), row("inconsistent_rates", [1, 2, 3], 500, 80),
                {**row("boolean_placement", [1, 2, 3], 500, 30), "avgPlacement": True}]
        chosen = _fetcher.select_combos(rows, {"1", "2", "3"})
        self.assertEqual([r["id"] for r in chosen], ["duplicate", "mapped"])
        self.assertEqual(chosen[0]["item_ids"], ["1", "1", "2"])


if __name__ == "__main__":
    unittest.main()
