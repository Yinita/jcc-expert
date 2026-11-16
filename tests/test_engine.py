"""Behavior checks for evidence boundaries and resource feasibility, using the shipped snapshots."""
import copy
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app.engine import ExpertEngine


class ExpertEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ExpertEngine(PROJECT / "app" / "data")

    def test_nature_uses_all_official_templates_and_normalizes_star_ids(self):
        state = self.engine.demo_state("nature")
        state["board"][0]["hero_id"] = "22508"
        result = self.engine.recommend(state)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["normalized_state"]["board"][0]["hero_id"], "12508")
        self.assertEqual(result["template_count_considered"], 64)
        template_ids = {"nature-" + t["id"] for t in self.engine.data["nature"]["official_published_lineups"]}
        self.assertEqual(len(result["candidates"]), 3)
        self.assertTrue(all(c["id"] in template_ids for c in result["candidates"]))
        self.assertTrue(any("狼" in c["name"] for c in result["candidates"]))
        self.assertTrue(all(c["sources"][0]["url"].startswith("https://game.gtimg.cn/") for c in result["candidates"]))

    def test_mode_isolation_and_no_nature_prior_in_orange(self):
        nature_ids = set(self.engine.indices["nature"]["heroes"])
        orange_ids = set(self.engine.indices["orange"]["heroes"])
        unique_nature = next(iter(nature_ids - orange_ids))
        state = self.engine.demo_state("orange")
        state["board"] = [{"hero_id": unique_nature, "stars": 1, "item_ids": []}]
        result = self.engine.recommend(state)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["candidates"], [])
        result = self.engine.recommend(self.engine.demo_state("orange"))
        self.assertTrue(all(c["id"].startswith("orange-") for c in result["candidates"]))
        self.assertTrue(all(c["external_terminal_prior"] is None for c in result["candidates"]))
        self.assertTrue(all(not c["transition_boards"] for c in result["candidates"]))

    def test_patch_and_invalid_ids_block_before_ranking(self):
        for patch in ["18.5", "18.18.1", None]:
            state = self.engine.demo_state("nature")
            state["patch"] = patch
            result = self.engine.recommend(state)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["candidates"], [])
        state = self.engine.demo_state("nature")
        state["offered_augment_ids"] = ["16461"]
        self.assertEqual(self.engine.recommend(state)["status"], "blocked")
        state = self.engine.demo_state("nature")
        state["item_ids"] = ["unknown-item"]
        self.assertEqual(self.engine.recommend(state)["status"], "blocked")

    def test_missing_state_never_invents_roll_budget(self):
        for field in ["hp", "gold", "level"]:
            state = self.engine.demo_state("nature")
            state[field] = None
            result = self.engine.recommend(state)
            self.assertEqual(result["status"], "ok")
            for candidate in result["candidates"]:
                plan = candidate["actions"]["roll_plan"]
                self.assertIsNone(plan["max_gold_spend"])
                self.assertIsNone(plan["gold_floor"])
                self.assertEqual(plan["mode"], "conditional")
        state = self.engine.demo_state("nature")
        state["gold"] = None
        buys = [b for c in self.engine.recommend(state)["candidates"] for b in c["actions"]["buy"]]
        self.assertTrue(buys)
        self.assertTrue(all(b["conditional"] for b in buys))

    def test_equipment_recipe_consumes_components_once(self):
        state = self.engine.demo_state("nature")
        state["board"], state["bench"] = [], []
        item = self.engine.indices["nature"]["items"]["2001"]
        self.assertEqual(len(item["components"]), 2)
        state["item_ids"] = list(item["components"])
        board = [{"hero_id": "12508", "name": "沃里克", "is_carry": True,
                  "item_ids": ["2001", "2001"]}]
        plans, _ = self.engine._items_plan(state, board)
        self.assertEqual(plans[0]["status"], "craftable")
        self.assertEqual(plans[1]["status"], "missing")
        self.assertTrue(all(c["name"] for c in plans[0]["components"]))
        # An item attached to another hero is not free inventory.
        state["item_ids"] = []
        state["board"] = [{"hero_id": "12501", "stars": 1, "item_ids": ["2001"]}]
        plans, _ = self.engine._items_plan(state, board)
        self.assertTrue(all(p["status"] == "missing" for p in plans))

    def test_no_sell_of_equipped_pair_or_upgraded_hero(self):
        state = self.engine.demo_state("nature")
        state["bench"] = [{"hero_id": "11500", "stars": 2, "item_ids": []},
                          {"hero_id": "11501", "stars": 1, "item_ids": ["1001"]},
                          {"hero_id": "11502", "stars": 1, "item_ids": []},
                          {"hero_id": "11502", "stars": 1, "item_ids": []}]
        target = [{"hero_id": "12508", "name": "沃里克", "item_ids": [], "is_carry": True}]
        actions = self.engine._actions(state, target, {"12508"})
        self.assertFalse(any(s["hero_id"] in ["11500", "11501", "11502"] for s in actions["sell_candidates"]))
        self.assertTrue(all(s["conditional"] for s in actions["sell_candidates"]))

    def test_score_not_probability_and_external_stats_do_not_change_rank(self):
        state = self.engine.demo_state("nature")
        before = self.engine.recommend(state)
        self.assertIsNone(before["state_probability"])
        self.assertFalse(before["score_semantics"]["is_probability"])
        original = self.engine.external
        try:
            self.engine.external = copy.deepcopy(original)
            for row in self.engine.external["comp_list_rows"]:
                row["topRate"] = 99.9
                row["avgPlacement"] = 1.01
            after = self.engine.recommend(state)
        finally:
            self.engine.external = original
        self.assertEqual([(c["id"], c["score"]) for c in before["candidates"]],
                         [(c["id"], c["score"]) for c in after["candidates"]])
        for candidate in after["candidates"]:
            self.assertIsNone(candidate["state_probability"])
            self.assertAlmostEqual(candidate["score"], sum(candidate["score_breakdown"].values()), places=2)
            self.assertTrue(0 <= candidate["score"] <= 100)
            prior = candidate["external_terminal_prior"]
            if prior:
                self.assertFalse(prior["used_in_score"])
                self.assertEqual(prior["kind"], "external_terminal_prior")

    def test_unconfirmed_screenshot_is_preview_and_input_is_not_mutated(self):
        state = self.engine.demo_state("nature")
        state["confirmed"] = False
        state["screenshot_id"] = "sample"
        original = copy.deepcopy(state)
        result = self.engine.recommend(state)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertTrue(result["candidates"])
        self.assertEqual(state, original)

    def test_orange_unverified_energy_not_used_as_hard_cap(self):
        state = self.engine.demo_state("orange")
        state["orange_card_ids"] = ["7250036", "7240093", "7250046"]  # tier sum 14
        state["portal"] = "稳定"  # current portal energy cap remains unknown
        result = self.engine.recommend(state)
        self.assertEqual(result["status"], "ok")
        candidate = next(c for c in result["candidates"] if c["name"] == "七费降临流")
        self.assertEqual(candidate["legality"]["status"], "pending_client_rules")
        self.assertFalse(candidate["legality"]["portal_energy_verified"])
        self.assertFalse(candidate["legality"]["global_buff_limit_verified"])
        self.assertFalse(candidate["deck_change_required"])
        self.assertTrue(result["unresolved_recipe_aliases"])
        self.assertFalse(any(c["name"] in ["灵活定阵流", "多地区瑞兹流"] for c in result["candidates"]))

    def test_other_orange_decks_are_pre_match_only_and_tasks_not_marked_done(self):
        state = self.engine.demo_state("orange")
        result = self.engine.recommend(state)
        self.assertEqual(result["candidates"][0]["name"], "奥恩神器流")
        for candidate in result["candidates"]:
            self.assertEqual(candidate["actions"]["sell_candidates"], [])
            self.assertEqual({h["hero_id"] for h in candidate["actions"]["hold"]},
                             {h["hero_id"] for h in state["board"] + state["bench"]})
            self.assertIsNone(candidate["actions"]["level_plan"]["target_level"])
            if candidate["deck_change_required"]:
                self.assertEqual(candidate["use_timing"], "pre_match_only")
                self.assertEqual(candidate["actions"]["buy"], [])
                self.assertIsNone(candidate["actions"]["roll_plan"]["max_gold_spend"])
            for chain in candidate["unlock_chains"]:
                for task in chain["tasks"]:
                    self.assertEqual(task["progress"], "unknown")
                    self.assertFalse(task["condition_verified"])

    def test_budget_conservation_and_no_invented_upgrade_cost(self):
        state = self.engine.demo_state("nature")
        state.update(gold=60, hp=20)
        result = self.engine.recommend(state)
        for candidate in result["candidates"]:
            actions = candidate["actions"]
            self.assertLessEqual(actions["visible_shop_purchase_cost"] + actions["roll_plan"]["max_gold_spend"], state["gold"])
            self.assertEqual(actions["roll_plan"]["gold_floor"], state["gold"] - actions["visible_shop_purchase_cost"] - actions["roll_plan"]["max_gold_spend"])
            level = actions["level_plan"]
            self.assertIsNotNone(level["target_level"])
            self.assertIsNone(level["upgrade_cost"])
            self.assertIsNone(level["xp_needed"])
        state["level"] = None
        result = self.engine.recommend(state)
        self.assertTrue(all(c["actions"]["level_plan"]["action"] == "wait_for_information" for c in result["candidates"]))

    def test_empty_state_is_insufficient_and_nonfinite_values_block(self):
        empty = {"mode": "nature", "patch": "18.6", "confirmed": True}
        self.assertEqual(self.engine.recommend(empty)["status"], "insufficient_data")
        for bad in [float("nan"), float("inf"), -1, "50"]:
            state = self.engine.demo_state("nature")
            state["gold"] = bad
            self.assertEqual(self.engine.recommend(state)["status"], "blocked")

    def test_stale_template_references_are_filtered_and_exposed(self):
        template = next(t for t in self.engine.data["nature"]["official_published_lineups"] if t["id"] == "4932")
        self.assertIn("augment:16461", self.engine._stale_references(template))
        state = self.engine.demo_state("nature")
        state["offered_augment_ids"] = ["2069", "2021"]
        result = self.engine.recommend(state)
        self.assertTrue(all(a["id"] != "16461" for c in result["candidates"] for a in c["augment_choices"]))


if __name__ == "__main__":
    unittest.main()
