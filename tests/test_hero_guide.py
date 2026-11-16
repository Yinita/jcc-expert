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
                if h["regular_shop_unit"]:
                    self.assertTrue(h["builds"])
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
                    self.assertNotIn("6058", {a["item_id"] for a in hero["artifacts"]})

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
