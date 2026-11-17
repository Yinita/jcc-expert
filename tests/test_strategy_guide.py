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
                    self.assertGreater(phase["actual_population_cost"], phase["population"])
        self.assertEqual(counts["source_partial_population"], 77)
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
            if comp.get("kind") == "official_published_author_lineup":
                continue
            self.assertFalse(comp["positioning"]["board"])
            for phase in comp["phases"]:
                self.assertIsNone(phase["population"])
                self.assertIn(phase["board_status"], ("core_only", "not_provided"))
                self.assertEqual({u["hero_id"] for u in phase["board"]}, set(comp["core_ids"]))
        flexible = next(c for c in self.data["modes"]["orange"]["comps"] if c["name"] == "灵活定阵流")
        self.assertIn("强力盟友", flexible["unresolved_card_names"])
        self.assertNotIn("7230050", flexible["card_ids"])  # Missing suffix cannot become I.

    def test_all_nature_templates_have_reviewed_action_relations(self):
        nature = self.data["modes"]["nature"]
        self.assertEqual(nature["coverage"]["human_reviewed_nature_operations"], 64)
        for comp in nature["comps"]:
            self.assertEqual(comp["roll_plan"]["provenance"], "human_reviewed_author_summary_and_editorial_guardrails")
            self.assertTrue(comp["roll_plan"]["actions"])
            self.assertTrue(comp["roll_plan"]["stop_conditions"])
        teemo = next(c for c in nature["comps"] if c["id"] == "4932")
        actions = " ".join(teemo["roll_plan"]["actions"])
        self.assertIn("3-2", actions)
        self.assertIn("30", actions)
        self.assertIn("两星", actions)
        self.assertIn("三星", actions)

    def test_melee_carries_are_not_automatically_tanks_or_stop_targets(self):
        heroes = {h["id"]: h for h in self.data["modes"]["nature"]["heroes"]}
        for id, carry_name in [("4830", "卡兹克"), ("4785", "易")]:
            comp = next(c for c in self.data["modes"]["nature"]["comps"] if c["id"] == id)
            self.assertNotIn(carry_name, [heroes[h]["name"] for h in comp["frontline_ids"]])
        comp = next(c for c in self.data["modes"]["nature"]["comps"] if c["id"] == "4765")
        phase3 = next(p for p in comp["phases"] if p["id"] == "stage3")
        self.assertNotIn("远古巨龙", " ".join(phase3["actions"]))
        self.assertTrue(all(heroes[id]["cost"] <= 3 for id in comp["three_star_ids"]))

    def test_later_roll_is_not_presented_as_a_stage3_action(self):
        comp = next(c for c in self.data["modes"]["nature"]["comps"] if c["id"] == "4838")
        phase3 = next(p for p in comp["phases"] if p["id"] == "stage3")
        phase4 = next(p for p in comp["phases"] if p["id"] == "stage4")
        self.assertNotIn("4-1升8", phase3["focus"])
        self.assertIn("4-1升8", phase4["focus"])

    def test_lotus_8_population_9_and_10_population_11_use_exact_lux(self):
        trait = next(t for t in self.data["modes"]["nature"]["traits"] if t["key"] == "origin:452")
        routes = trait["capstone_routes"]
        nine = next(r for r in routes if r["target_count"] == 9 and r["conditional_form_ids"])
        eleven = next(r for r in routes if r["target_count"] == 11 and r["conditional_form_ids"])
        self.assertEqual(nine["conditional_form_ids"], ["15462"])
        self.assertEqual((nine["population_required"], nine["native_count"], nine["emblem_count"]), (8, 9, 0))
        self.assertEqual((eleven["population_required"], eleven["total_count"], eleven["emblem_count"]), (10, 11, 2))
        self.assertEqual(len(eleven["hero_ids"]), 8)
        self.assertEqual(eleven["emblem_holder_slots"], 2)
        self.assertIn("41809", eleven["emblem_item_ids"])
        self.assertTrue(any(e["hero_id"] == "15462" and e["contribution"] == 2 for e in eleven["counting_evidence"]))
        excessive = next(r for r in routes if r["target_count"] == 11 and not r["conditional_form_ids"])
        self.assertIn("超出常规10人口", " ".join(excessive["conditions"]))

    def test_all_official_prismatic_tiers_have_arithmetic_routes(self):
        for mode in self.data["modes"].values():
            for trait in mode["traits"]:
                for tier in trait["tiers"]:
                    if tier["is_prismatic"]:
                        routes = [r for r in trait["capstone_routes"] if r["target_count"] == tier["count"]]
                        self.assertTrue(routes, (mode["id"], trait["key"]))
                        for route in routes:
                            self.assertEqual(route["total_count"], route["native_count"] + route["emblem_count"])
                            self.assertGreaterEqual(route["total_count"], route["target_count"])
                            self.assertEqual(route["population_required"], route["named_units_population"] + route["emblem_holder_slots"])

    def test_population_slots_and_trait_contribution_are_independent(self):
        nature = self.data["modes"]["nature"]
        heroes = {h["id"]: h for h in nature["heroes"]}
        dragon = heroes["15458"]
        self.assertEqual(builder.population_cost(dragon), 2)
        self.assertEqual(builder.contribution("nature", dragon, "origin:454"), 2)
        orange_heroes = {h["id"]: h for h in self.data["modes"]["orange"]["heroes"]}
        self.assertEqual(builder.population_cost(orange_heroes["15285"]), 0)
        self.assertEqual(builder.contribution("orange", orange_heroes["15285"], "origin:341"), 1)
        baron = next(h for h in orange_heroes.values() if any(t["key"] == "origin:369" for t in h["traits"]))
        self.assertEqual(builder.population_cost(baron), 2)
        self.assertEqual(builder.contribution("orange", baron, "origin:350"), 2)
        board = [{"is_pet": False, "population_cost": 2}, {"is_pet": False, "population_cost": 1},
                 {"is_pet": True, "population_cost": 0}]
        result = builder.validate_population(board, 2)
        self.assertEqual((result["actual_unit_count"], result["actual_population_cost"]), (2, 3))
        self.assertEqual(result["board_status"], "source_invalid_population")

    def test_unlock_tasks_preserve_exact_source_and_ambiguous_variants(self):
        heroes = {h["id"]: h for h in self.data["modes"]["orange"]["heroes"]}
        self.assertEqual(sum(h["unlock_requirements"]["status"] == "task_recorded" for h in heroes.values()), 55)
        brand = heroes["12422"]["unlock_requirements"]["tasks"][0]
        self.assertIn("非坦克", brand["description_source"])
        self.assertTrue(brand["requires_client_role_verification"])
        skarner = heroes["14337"]["unlock_requirements"]["tasks"][0]
        self.assertEqual(skarner["minimum_level"], 7)
        self.assertTrue(skarner["requires_client_role_verification"])
        alistar = heroes["13355"]["unlock_requirements"]["tasks"][0]
        self.assertIn("后2排", alistar["description_source"])
        singed = heroes["14338"]["unlock_requirements"]["tasks"][0]
        self.assertTrue(singed["conditions_ambiguous"])
        self.assertGreater(len(singed["clauses_source"]), 1)

    def test_cross_trait_eclipse_trigger_and_unknown_ids_remain_distinct(self):
        trait = next(t for t in self.data["modes"]["nature"]["traits"] if t["key"] == "origin:461")
        plan = trait["mechanism_plan"]
        self.assertEqual(plan["activation_requirements"], {"origin:459": 3, "origin:460": 3})
        self.assertEqual(len(plan["activation_hero_ids"]), 6)
        for trait in self.data["modes"]["orange"]["traits"]:
            if not trait["verified"]:
                self.assertEqual(trait["mechanism_plan"]["status"], "unresolved")
                self.assertFalse(trait["capstone_routes"])
                self.assertFalse(trait["mechanism_plan"]["partial_combinations"])

    def test_small_mechanism_combinations_do_not_invent_full_boards(self):
        for mode in self.data["modes"].values():
            heroes = {h["id"]: h for h in mode["heroes"]}
            for trait in mode["traits"]:
                plan = trait["mechanism_plan"]
                self.assertTrue(plan["not_a_complete_board"])
                for pair in plan["partial_combinations"]:
                    self.assertLessEqual(len(pair["hero_ids"]), 4)
                    self.assertTrue(set(pair["hero_ids"]) <= set(trait["native_hero_ids"]))
                    self.assertTrue(pair["not_a_complete_board"])
                    for id in pair["hero_ids"]:
                        if heroes[id].get("unlock_requirements", {}).get("tasks"):
                            self.assertIn(heroes[id]["name"], " ".join(pair["conditions"]))

    def test_internal_pipe_does_not_shift_oracle_breakpoint_effects(self):
        trait = next(t for t in self.data["modes"]["nature"]["traits"] if t["key"] == "class:350")
        self.assertEqual([t["count"] for t in trait["tiers"]], [2, 3, 4, 5])
        self.assertIn("8【法力回复】", trait["tiers"][-1]["effect"])

    def test_two_orange_author_examples_preserve_complete_image_units(self):
        data = self.data["modes"]["orange"]
        examples = [c for c in data["comps"] if c["kind"] == "official_published_author_lineup"]
        self.assertEqual(len(examples), 2)
        river = next(c for c in examples if c["id"] == "orange-author-river-tryndamere")
        zaun = next(c for c in examples if c["id"] == "orange-author-zaun-darius")
        self.assertEqual({u["hero_id"] for u in river["positioning"]["board"]},
                         {"15281", "14352", "13322", "12411", "14336", "14353", "12405", "13335", "12416"})
        self.assertEqual(len(zaun["positioning"]["board"]), 9)
        self.assertEqual(len(river["phases"][0]["board"]), 4)
        self.assertIsNone(river["phases"][0]["population"])
        self.assertTrue(river["positioning"]["unidentified_schematic_markers"])
        self.assertIn("物理射手", " ".join(river["roll_plan"]["actions"]))
        self.assertNotIn("神谕者单位", " ".join(river["roll_plan"]["actions"]))
        for comp in examples:
            self.assertTrue(comp["source"]["image_urls"])
            main = next(e for e in comp["equipment"] if e["hero_id"] == comp["carry_ids"][0])
            self.assertEqual(len(main["item_ids"]), 4)
            self.assertEqual(main["requires_card_ids"], ["7250056"])
            self.assertIn("主角选择器", main["slot_note"])

    def test_new_source_conflicts_and_card_reward_conditions_are_visible(self):
        data = self.data["modes"]["orange"]
        cards = {c["id"]: c for c in data["cards"]}
        self.assertIn("主角选择器", cards["7250056"]["description"])
        self.assertTrue(cards["7230114"]["description"])
        self.assertIn("河流之王纹章", cards["7230085"]["description"])
        heroes = {h["id"]: h for h in data["heroes"]}
        for id in ["14338", "14333"]:
            self.assertTrue(heroes[id]["unlock_requirements"]["source_conflicts"])
        galio_cards = heroes["15285"]["unlock_requirements"]["direct_unlock_cards"]
        self.assertIn("7250046", [c["id"] for c in galio_cards])
        prism = next(c for c in data["comps"] if c["id"] == "orange-prismatic")
        self.assertIn("迅捷蟹奇袭 I", prism["unresolved_card_names"])
        self.assertNotIn("7240069", prism["card_ids"])

    def test_author_stage_equipment_does_not_inherit_final_loadouts(self):
        examples = {c["id"]: c for c in self.data["modes"]["orange"]["comps"]}
        river = examples["orange-author-river-tryndamere"]
        early = {u["hero_id"]: u for u in river["phases"][0]["board"]}
        middle = {u["hero_id"]: u for u in river["phases"][1]["board"]}
        self.assertEqual(early["12405"]["item_ids"], ["41629"])
        self.assertEqual(middle["12405"]["item_ids"], ["41629", "2006", "2012"])
        for board in [early, middle]:
            self.assertFalse(board["13322"]["item_ids"])
            self.assertFalse(board["12416"]["item_ids"])
        zaun = examples["orange-author-zaun-darius"]
        for phase in zaun["phases"][:2]:
            self.assertTrue(all(not u["item_ids"] for u in phase["board"]))
        for comp in [river, zaun]:
            main_carry = next(u for u in comp["positioning"]["board"] if u["hero_id"] == comp["carry_ids"][0])
            self.assertEqual(len(main_carry["item_ids"]), 4)

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
