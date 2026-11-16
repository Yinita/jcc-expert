import importlib.util
import json
from pathlib import Path
import unittest

_path = Path(__file__).resolve().parents[1] / "scripts/build_strategy_guide.py"
_spec = importlib.util.spec_from_file_location("strategy_builder", _path)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


class StrategyGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = builder.build_strategy()

    def test_all_known_typed_traits_and_unresolved_references_preserved(self):
        hero_guide = json.loads((builder.BASE / "app/static/guide-data.json").read_text())
        for mode, data in self.data["modes"].items():
            expected = {(t["kind"], t["id"]): t for t in hero_guide["modes"][mode]["traits"]}
            actual = {(t["kind"], t["id"]): t for t in data["traits"]}
            self.assertEqual(set(expected), set(actual))
            for key, trait in actual.items():
                self.assertEqual(trait["name"], expected[key]["name"])
                self.assertEqual(trait["verified"], expected[key]["verified"])
                if not trait["verified"]:
                    self.assertFalse(trait["breakpoints"])
                    self.assertFalse(trait["tiers"])
                    self.assertFalse(trait["linked_comp_ids"])
        self.assertEqual(sum(t["verified"] for m in self.data["modes"].values() for t in m["traits"]), 102)

    def test_native_stage_pools_are_optional_and_exclude_conditional_forms(self):
        for mode in self.data["modes"].values():
            heroes = {h["id"]: h for h in mode["heroes"]}
            for trait in mode["traits"]:
                pools = trait["stage_pools"]
                self.assertEqual(set(trait["native_hero_ids"]), set(pools["early"] + pools["mid"] + pools["late"]))
                for stage, values in pools.items():
                    for id in values:
                        hero = heroes[id]
                        self.assertFalse(hero.get("template_only_form"))
                        self.assertTrue(any(t["key"] == trait["key"] for t in hero["traits"]))
                        self.assertTrue(hero["cost"] <= 2 if stage == "early" else hero["cost"] == 3 if stage == "mid" else hero["cost"] >= 4)
                self.assertTrue(trait["conditions"])

    def test_population_guards_preserve_all_source_units(self):
        nature = self.data["modes"]["nature"]
        counts = {}
        for comp in nature["comps"]:
            for phase in comp["phases"]:
                counts[phase["board_status"]] = counts.get(phase["board_status"], 0) + 1
                expected = sum(not u["is_pet"] for u in phase["board"])
                self.assertEqual(expected, phase["actual_unit_count"])
                if phase["board_status"] == "source_invalid_population":
                    self.assertGreater(expected, phase["population"])
        self.assertEqual(counts["source_partial_population"], 85)
        self.assertEqual(counts["source_invalid_population"], 1)
        comp = next(c for c in nature["comps"] if c["id"] == "4800")
        late = next(p for p in comp["phases"] if p["id"] == "late")
        self.assertEqual(late["population"], 9)
        self.assertEqual(late["actual_unit_count"], 10)
        self.assertEqual(len([u for u in late["board"] if not u["is_pet"]]), 10)

    def test_pets_do_not_count_as_population_or_required_core(self):
        comp = next(c for c in self.data["modes"]["nature"]["comps"] if c["id"] == "4932")
        phase = next(p for p in comp["phases"] if p["id"] == "stage3")
        self.assertEqual(phase["actual_unit_count"], 6)
        self.assertEqual(phase["pet_count"], 3)
        self.assertTrue(all(u["hero_name"] for u in phase["board"] if u["is_pet"]))
        self.assertFalse(set(comp["core_ids"]) & {u["hero_id"] for u in phase["board"] if u["is_pet"]})

    def test_early_phase_is_a_pool_and_not_a_truncated_executable_board(self):
        for comp in self.data["modes"]["nature"]["comps"]:
            phase = comp["phases"][0]
            self.assertEqual(phase["id"], "stage2")
            self.assertIsNone(phase["population"])
            self.assertIn(phase["board_status"], ("source_subset", "not_provided"))
            self.assertEqual(phase["provenance"], "editorial_source_pool")
            self.assertIn("source_early_board", comp)

    def test_exact_forms_and_star_normalization_do_not_merge_names(self):
        nature = self.data["modes"]["nature"]
        facts = json.loads((builder.BASE / "app/data/nature_facts.json").read_text())
        records = {h["official_id"]: h for h in facts["champion_star_form_records"]}
        heroes = {h["id"]: h for h in nature["heroes"]}
        self.assertEqual(builder.canonical_id("21500", records, heroes), ("11500", True))
        self.assertEqual(builder.canonical_id("15464", records, heroes), ("15464", True))
        self.assertNotEqual(builder.canonical_id("15464", records, heroes)[0], "15459")
        self.assertNotEqual(builder.canonical_id("14514", records, heroes)[0], "14501")
        for id in ("15464", "14514", "15460"):
            self.assertTrue(heroes[id]["template_only_form"])
            self.assertFalse(heroes[id]["guide_available"])

    def test_lux_selected_trait_has_two_counts_with_explicit_condition(self):
        comp = next(c for c in self.data["modes"]["nature"]["comps"] if c["id"] == "4838")
        link = next(l for l in comp["trait_links"] if l["key"] == "origin:450")
        self.assertEqual(link["native_unit_count"], 6)
        self.assertEqual(link["count"], 7)
        self.assertEqual(link["status"], "conditional")
        self.assertIn("15464", link["conditional_form_ids"])
        self.assertTrue(any(e["hero_id"] == "15464" and e["contribution"] == 2 for e in link["counting_evidence"]))

    def test_emblem_crosses_higher_breakpoint_without_double_counting(self):
        trait = {"id": "1", "key": "class:1", "breakpoints": [2, 4, 6], "verified": True}
        heroes = {str(i): {"traits": [{"key": "class:1", "verified": True}]} for i in range(1, 6)}
        heroes["6"] = {"traits": []}
        board = [{"hero_id": str(i), "is_pet": False, "item_ids": []} for i in range(1, 7)]
        board[-1]["item_ids"] = ["E", "E"]
        board[0]["item_ids"] = ["E"]  # Native trait cannot get another count.
        board.append(dict(board[0]))  # Same hero copy cannot add a unique trait.
        link = builder.trait_links(board, heroes, {"E": {"trait_ids": ["1"]}}, [trait])[0]
        self.assertEqual(link["native_count"], 5)
        self.assertEqual(link["emblem_count"], 1)
        self.assertEqual(link["count"], 6)
        self.assertEqual(link["native_breakpoint"], 4)
        self.assertEqual(link["full_breakpoint"], 6)
        self.assertEqual(link["status"], "conditional")

    def test_orange_has_cores_not_fabricated_full_boards(self):
        for comp in self.data["modes"]["orange"]["comps"]:
            self.assertFalse(comp["positioning"]["board"])
            for phase in comp["phases"]:
                self.assertIsNone(phase["population"])
                self.assertIn(phase["board_status"], ("core_only", "not_provided"))
                self.assertEqual({u["hero_id"] for u in phase["board"]}, set(comp["core_ids"]))
        flexible = next(c for c in self.data["modes"]["orange"]["comps"] if c["name"] == "灵活定阵流")
        self.assertIn("强力盟友", flexible["unresolved_card_names"])
        self.assertNotIn("7230050", flexible["card_ids"])  # Missing suffix cannot become I.

    def test_card_conditions_are_not_arrival_rounds_or_streaks(self):
        data = self.data["modes"]["orange"]
        cards = {c["id"]: c for c in data["cards"]}
        self.assertEqual(cards["7230072"]["activation_rounds"], ["1-2"])
        self.assertIn("首次合成8件成装", cards["7230072"]["description"])
        self.assertIn("首次赢得10场玩家对战", cards["7240021"]["description"])
        self.assertNotIn("连胜", cards["7240021"]["description"])
        win = next(c for c in data["comps"] if c["name"] == "连胜杰作流")
        self.assertEqual(win["source_status"], "provisional_recipe")
        twilight = next(c for c in data["comps"] if c["name"] == "暮光试炼流")
        link = next(l for l in twilight["trait_links"] if l["key"] == "class:299")
        self.assertEqual(link["native_count"], 1)
        self.assertEqual(link["count"], 2)
        self.assertEqual(link["requires_card_ids"], ["7240061"])

    def test_references_resolve_and_assets_exist(self):
        for mode in self.data["modes"].values():
            heroes = {h["id"] for h in mode["heroes"]}
            items = {i["id"] for i in mode["items"]}
            augments = {a["id"] for a in mode["augments"]}
            cards = {c["id"]: c for c in mode["cards"]}
            for comp in mode["comps"]:
                self.assertTrue(set(comp["core_ids"]) <= heroes)
                self.assertTrue(set(comp["augment_ids"]) <= augments)
                for equipment in comp["equipment"]:
                    self.assertTrue(set(equipment["item_ids"]) <= items)
                for card_id in comp["card_ids"]:
                    self.assertIn(card_id, cards)
                    self.assertTrue(cards[card_id]["description"])
            for entity in mode["heroes"] + mode["items"] + mode["cards"]:
                if entity.get("icon"):
                    self.assertTrue((builder.BASE / "app" / entity["icon"]).is_file())

    def test_incidental_membership_never_appears_as_an_activated_trait_route(self):
        for mode in self.data["modes"].values():
            comp_ids = {c["id"] for c in mode["comps"]}
            for trait in mode["traits"]:
                self.assertTrue(set(trait["linked_comp_ids"] + trait["related_comp_ids"]) <= comp_ids)
                for link in trait["trait_link_details"]:
                    field = "related_comp_ids" if link["status"] == "incidental" else "linked_comp_ids"
                    self.assertIn(link["comp_id"], trait[field])


if __name__ == "__main__":
    unittest.main()
