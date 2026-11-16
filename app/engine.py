"""Versioned, evidence-traceable recommendations. Scores are heuristics, never probabilities."""
from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCORE_SEMANTICS = {
    "kind": "heuristic_fit_score",
    "range": [0, 100],
    "is_probability": False,
    "description": "0—100为当前资源与候选路线的启发式适配分，不是吃鸡率、前四率或战斗胜率。外部终局统计不参与此评分。",
    "nature_weights": {"roster": 40, "items": 25, "traits": 15, "augments": 10, "transition": 10},
    "orange_weights": {"cards": 50, "roster": 20, "items": 10, "traits": 10, "transition": 10},
}


class ExpertEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data = {
            "nature": self._load("nature_facts.json"),
            "orange": self._load("orange_base_facts.json"),
        }
        self.orange_research = self._load("orange_research.json")
        self.external = self._load("statistics_external.json")
        self.indices = {}
        for mode, data in self.data.items():
            all_heroes = {str(h["official_id"]): h for h in data["champion_star_form_records"]}
            # Canonical IDs are official one-star IDs. Keep forms distinct, and never join across modes.
            heroes = {k: v for k, v in all_heroes.items() if v["observed_star_level"] == 1}
            self.indices[mode] = {
                "all_heroes": all_heroes,
                "heroes": heroes,
                "items": {str(x["id"]): x for x in data["items"]},
                "augments": {str(x["id"]): x for x in data["augments"]},
                "traits": {str(x["id"]): x for x in data["traits"]},
                "cards": {str(x["id"]): x for x in data.get("time_cards", [])},
                "sources": {x["source_key"]: x for x in data["sources"]},
            }

    def _load(self, name: str) -> dict:
        with (self.data_dir / name).open(encoding="utf-8") as handle:
            return json.load(handle)

    def catalog(self, mode: str) -> dict:
        if mode not in self.indices:
            raise ValueError("mode必须为nature或orange")
        ix = self.indices[mode]
        heroes = []
        for hid, h in ix["heroes"].items():
            if h.get("cost", 0) <= 0:
                continue
            heroes.append({"id": hid, "name": h["name"], "cost": h["cost"],
                           "icon_url": h.get("icon_url"), "trait_ids": h["origin_ids"] + h["class_ids"],
                           "trait_names":[ix["traits"].get(t,{}).get("name",str(t))
                                          for t in h["origin_ids"]+h["class_ids"]],
                           "gallery_visible": h.get("shows_in_official_gallery", False)})
        cards = [{"id": c["id"], "name": c["name_zh"], "rarity_tier": c["rarity_tier"],
                  "category": c.get("category"), "icon_url": c.get("icon_url"),
                  "energy_assumption": c.get("deck_energy_assuming_tier_mapping"),
                  "energy_verified": False} for c in ix["cards"].values()]
        return {"mode": mode, "patch": self.data[mode]["scope"]["user_patch"],
                "official_config_version": self.data[mode]["scope"]["official_version"],
                "heroes": sorted(heroes, key=lambda h: (h["cost"], h["name"], h["id"])),
                "items": [{"id": i["id"], "name": i["name"], "type": i.get("type"),
                           "components": i.get("components", [])} for i in ix["items"].values()],
                "augments": [{"id": a["id"], "name": a["name"], "tier": a.get("tier")} for a in ix["augments"].values()],
                "traits": [{"id": t["id"], "name": t["name"], "breakpoints": t.get("breakpoints", [])} for t in ix["traits"].values()],
                "cards": cards, "score_semantics": copy.deepcopy(SCORE_SEMANTICS),
                "template_count": len(self.data[mode].get("official_published_lineups", self.orange_research["recipes"])),
                "portals": ["稳定", "波动", "未知"] if mode == "orange" else [],
                "portal_rules_verified": False}

    def demo_state(self, mode: str = "nature") -> dict:
        state = {"mode": mode, "patch": "18.6", "hp": 82, "gold": 38, "level": 6,
                 "stage": "3-2", "board": [], "bench": [], "shop": [], "item_ids": [],
                 "augment_ids": [], "offered_augment_ids": [], "orange_card_ids": [],
                 "portal": None, "confirmed": True, "screenshot_id": None}
        if mode == "nature":
            state.update(board=[{"hero_id": "12508", "stars": 2, "item_ids": ["2001"]},
                                {"hero_id": "12507", "stars": 2, "item_ids": []},
                                {"hero_id": "12501", "stars": 1, "item_ids": []},
                                {"hero_id": "11504", "stars": 2, "item_ids": []}],
                         bench=[{"hero_id": "12508", "stars": 1, "item_ids": []}],
                         shop=["12508", "12501", "11500", None, "13506"],
                         item_ids=["1001", "1009", "1005"], augment_ids=["2069"])
        elif mode == "orange":
            ix = self.indices[mode]
            name_ids = {h["name"]: hid for hid, h in ix["heroes"].items() if h.get("shows_in_official_gallery")}
            ids = [name_ids[n] for n in ["奥恩", "布兰德", "阿利斯塔"] if n in name_ids]
            state.update(board=[{"hero_id": h, "stars": 1, "item_ids": []} for h in ids],
                         shop=ids[:2] + [None] * 3, orange_card_ids=["7220018", "7240019", "7230072"],
                         item_ids=["1001", "1005"], portal="稳定")
        else:
            raise ValueError("mode必须为nature或orange")
        return state

    def _canonical_hero(self, mode: str, value: Any) -> str | None:
        hid = str(value)
        ix = self.indices[mode]
        if hid not in ix["all_heroes"]:
            return None
        first = "1" + str(ix["all_heroes"][hid]["base_form_id"])
        return first if first in ix["heroes"] else None

    @staticmethod
    def _ids(value: Any) -> list[str]:
        if not value:
            return []
        return [x for x in re.split(r"[,|]", str(value)) if x]

    def _normalize_state(self, raw: dict) -> tuple[dict, list[str], list[str]]:
        state = copy.deepcopy(raw)
        errors, warnings = [], []
        mode = state.get("mode")
        if mode not in self.indices:
            return state, ["未知模式；请选择自然之力或大橘大利。"], warnings
        ix = self.indices[mode]
        expected = self.data[mode]["scope"]["user_patch"]
        if str(state.get("patch", "")) != expected:
            errors.append(f"补丁不匹配：当前规则资料对应{expected}，请核对客户端实际补丁；较新公告不代表已同步完整规则。")
        for field, lo, hi in [("hp", 0, 1000), ("gold", 0, 10000), ("level", 1, 20)]:
            value = state.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < lo or value > hi):
                errors.append(f"{field}必须为空或{lo}—{hi}之间的有限数字。")
        if state.get("level") is not None and isinstance(state.get("level"), (int, float)) and state["level"] % 1:
            errors.append("level必须是整数。")
        for group in ["board", "bench"]:
            value = state.get(group) or []
            if not isinstance(value, list):
                errors.append(f"{group}必须为列表。")
                state[group] = []
                continue
            normalized = []
            for unit in value:
                if not isinstance(unit, dict):
                    errors.append(f"{group}中存在无效弈子对象。")
                    continue
                hid = self._canonical_hero(mode, unit.get("hero_id"))
                if hid is None:
                    errors.append(f"{group}弈子ID {unit.get('hero_id')}不属于此模式的当前配置。")
                    continue
                stars = unit.get("stars", 1)
                if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 4:
                    errors.append(f"{ix['heroes'][hid]['name']}星级必须为1—4。")
                    continue
                item_ids = self._validate_ids(unit.get("item_ids") or [], ix["items"], "装备", errors)
                if len(item_ids) > 3:
                    warnings.append(f"{ix['heroes'][hid]['name']}有超过3个装备记录；请确认召唤/特殊槽位规则。")
                normalized.append({"hero_id": hid, "stars": stars, "item_ids": item_ids})
            state[group] = normalized
        state["shop"] = []
        raw_shop = raw.get("shop") or []
        if not isinstance(raw_shop, list):
            errors.append("shop必须为列表。")
            raw_shop = []
        for hid in raw_shop:
            canonical = self._canonical_hero(mode, hid) if hid is not None else None
            if hid is not None and canonical is None:
                errors.append(f"商店弈子ID {hid}不属于此模式的当前配置。")
            state["shop"].append(canonical)
        for field, table, label in [("item_ids", "items", "装备"), ("augment_ids", "augments", "已选强化"),
                                    ("offered_augment_ids", "augments", "备选强化"), ("orange_card_ids", "cards", "时间卡片")]:
            state[field] = self._validate_ids(state.get(field) or [], ix[table], label, errors)
        if mode == "nature" and state["orange_card_ids"]:
            errors.append("自然之力模式不能使用大橘大利时间卡片。")
        if mode == "orange":
            cards = state["orange_card_ids"]
            if len(cards) > 3 or len(set(cards)) != len(cards):
                errors.append("带入时间卡片需至多3张互不重复卡；完整构筑需要3张。")
        if state.get("confirmed") is not True:
            warnings.append("截图或输入尚未确认；以下只是预览，请逐项核对后再执行。")
        missing = [f for f in ["hp", "gold", "level"] if state.get(f) is None]
        if missing:
            warnings.append("缺少" + "、".join(missing) + "；不提供精确搜牌预算或固定回合操作。")
        if state.get("level") is not None and len(state["board"]) > state["level"]:
            warnings.append("场上记录数量超过等级；可能包含召唤物或额外人口，请核对。")
        return state, errors, list(dict.fromkeys(warnings))

    @staticmethod
    def _validate_ids(values: Any, table: dict, label: str, errors: list) -> list[str]:
        if not isinstance(values, list):
            errors.append(f"{label}ID必须为列表。")
            return []
        result = []
        for value in values:
            key = str(value)
            if key not in table:
                errors.append(f"未知{label}ID：{key}。")
            else:
                result.append(key)
        return result

    def recommend(self, state: dict) -> dict:
        if not isinstance(state, dict):
            return {"status": "blocked", "errors": ["状态必须为对象。"], "warnings": [], "candidates": [], "state_probability": None,
                    "score_semantics": copy.deepcopy(SCORE_SEMANTICS)}
        state, errors, warnings = self._normalize_state(state)
        result = {"mode": state.get("mode"), "patch": state.get("patch"), "status": "blocked" if errors else "ok",
                  "errors": errors, "warnings": warnings, "state_probability": None,
                  "score_semantics": copy.deepcopy(SCORE_SEMANTICS), "candidates": [],
                  "missing_inputs": [k for k in ["hp", "gold", "level", "stage"] if state.get(k) is None],
                  "normalized_state": state}
        if errors:
            return result
        if not any(state.get(k) for k in ["board", "bench", "shop", "item_ids", "augment_ids", "offered_augment_ids", "orange_card_ids"]):
            result["status"] = "insufficient_data"
            result["warnings"].append("尚无来牌、装备、强化或卡组信息，不能据此区分可达路线。")
            return result
        mode = state["mode"]
        if mode == "nature":
            result["candidates"] = self._nature_candidates(state)
            result["template_count_considered"] = len(self.data["nature"]["official_published_lineups"])
        else:
            result["candidates"] = self._orange_candidates(state)
            result["warnings"].append("大橘大利门能量上限和全局增益卡限制未完成客户端核验；构筑合法性为待核验，不把社区8/10/15当硬规则。")
            result["unresolved_recipe_aliases"] = [
                {"name": r["name"], "aliases": r["alias_resolution_required"]}
                for r in self.orange_research["recipes"] if r.get("alias_resolution_required")]
        if not result["candidates"]:
            result["status"] = "insufficient_data"
        elif state.get("confirmed") is not True:
            result["status"] = "needs_confirmation"
        return result

    def _holdings(self, state: dict) -> tuple[dict, Counter]:
        units = defaultdict(list)
        items = Counter(state["item_ids"])
        for unit in state["board"] + state["bench"]:
            units[unit["hero_id"]].append(unit)
            items.update(unit["item_ids"])
        return units, items

    def _board(self, mode: str, source_board: list, three_star_ids: set | None = None) -> list[dict]:
        ix = self.indices[mode]
        result = []
        for unit in source_board or []:
            hid = self._canonical_hero(mode, unit.get("hero_id"))
            if hid is None:
                continue
            hero = ix["heroes"][hid]
            if unit.get("type") == "pet" or hero.get("cost", 0) <= 0:
                continue
            items = [str(i) for i in unit.get("item_ids", []) if str(i) in ix["items"]]
            result.append({"hero_id": hid, "name": hero["name"], "cost": hero["cost"],
                           "position": unit.get("position"), "item_ids": items,
                           "item_names": [ix["items"][i]["name"] for i in items],
                           "is_carry": bool(unit.get("is_carry")),
                           "target_stars": 3 if hid in (three_star_ids or set()) else 2})
        return result

    def _trait_counts(self, mode: str, hero_ids: list[str]) -> Counter:
        ix, names, counts = self.indices[mode], set(), Counter()
        for hid in hero_ids:
            hero = ix["heroes"].get(hid)
            if not hero or hero["name"] in names or hero.get("cost", 0) <= 0:
                continue
            names.add(hero["name"])
            # Unique named heroes count once; special multi-count rules need a rule interpreter.
            counts.update(set(hero["origin_ids"] + hero["class_ids"]))
        return counts

    def _active_traits(self, mode: str, counts: Counter) -> set[str]:
        return {tid for tid, n in counts.items()
                if tid in self.indices[mode]["traits"] and any(n >= b for b in self.indices[mode]["traits"][tid].get("breakpoints", []))}

    def _items_plan(self, state: dict, board: list[dict]) -> tuple[list, float]:
        ix = self.indices[state["mode"]]
        loose = Counter(state["item_ids"])
        on_hero = defaultdict(Counter)
        for unit in state["board"] + state["bench"]:
            on_hero[unit["hero_id"]].update(unit["item_ids"])
        plan, fit = [], []
        for unit in sorted(board, key=lambda u: not u.get("is_carry")):
            for iid in unit.get("item_ids", []):
                item = ix["items"][iid]
                required = Counter(item.get("components", []))
                component_rows = [{"id": k, "name": ix["items"][k]["name"], "owned": loose[k], "required": n}
                                  for k, n in required.items() if k in ix["items"]]
                if on_hero[unit["hero_id"]][iid]:
                    on_hero[unit["hero_id"]][iid] -= 1
                    status, value, note = "equipped", 1., "已在目标弈子上。"
                elif loose[iid]:
                    loose[iid] -= 1
                    status, value, note = "owned", 1., "备件区已有；先确认主C与主坦的分配。"
                elif required and all(loose[k] >= n for k, n in required.items()):
                    loose.subtract(required)
                    status, value, note = "craftable", .9, "现有散件可合成；按此计划分配后不重复计数。"
                elif required and any(loose[k] for k in required):
                    # Reserve partial components so one loose component cannot support every desired item.
                    available = sum(min(loose[k], n) for k, n in required.items())
                    for k, n in required.items():
                        loose[k] -= min(loose[k], n)
                    status, value, note = "partial", .45 * available / sum(required.values()), "仅部分散件满足；等后续资源，避免为理想装损失当前战力。"
                else:
                    status, value, note = "missing", 0., "尚缺；其他弈子身上的装备不视为可直接搬移。"
                weight = 2 if unit.get("is_carry") else 1
                fit.extend([value] * weight)
                plan.append({"hero_id": unit["hero_id"], "hero_name": unit["name"], "item_id": iid,
                             "item_name": item["name"], "status": status, "components": component_rows, "note": note})
        return plan, sum(fit) / len(fit) if fit else 0.

    def _augment_choices(self, state: dict, desired: set[str], target_traits: set[str]) -> list:
        ix = self.indices[state["mode"]]
        result = []
        for aid in state["offered_augment_ids"]:
            aug = ix["augments"][aid]
            if aid in desired:
                score, reason, source = 100, "此候选官方模板明确推荐；仍需核对当前效果、资源与同轮选项。", "template"
            elif target_traits.intersection(aug.get("linked_trait_ids", [])):
                score, reason, source = 65, "关联目标羁绊；只按关联字段评估，未证明其本局胜率更高。", "trait_heuristic"
            else:
                score, reason, source = 25, "缺少此组合的机制验证，请对照客户端完整效果再选。", "unverified_fit"
            result.append({"id": aid, "name": aug["name"], "score": score, "reason": reason, "source": source})
        return sorted(result, key=lambda a: (-a["score"], a["id"]))

    def _actions(self, state: dict, board: list[dict], three: set[str]) -> dict:
        ix = self.indices[state["mode"]]
        held, _ = self._holdings(state)
        target = {u["hero_id"]: u for u in board}
        buy = []
        remaining_gold = state.get("gold")
        for hid, n in Counter(h for h in state["shop"] if h and h in target).items():
            current_copies = sum(3 ** (u["stars"] - 1) for u in held.get(hid, []))
            wanted = 9 if hid in three else 3
            n = min(n, max(0, wanted - current_copies))
            if remaining_gold is not None and ix["heroes"][hid]["cost"] > 0:
                n = min(n, int(remaining_gold // ix["heroes"][hid]["cost"]))
                remaining_gold -= n * ix["heroes"][hid]["cost"]
            if n:
                buy.append({"hero_id": hid, "name": ix["heroes"][hid]["name"], "count": n,
                            "reason": "商店已见且属于此路线；以保留战力与经济为前提。" if state.get("gold") is not None else "商店已见且属于此路线；金币未确认，先核对能否购买。",
                            "conditional": state.get("gold") is None})
        hold = [{"hero_id": hid, "name": ix["heroes"][hid]["name"], "count": len(units),
                 "reason": "属于此候选路线；保留成对或高星质量，先观察同行与后续来牌。"}
                for hid, units in held.items() if hid in target]
        sell = []
        for group in ["bench", "board"]:
            for unit in state[group]:
                hid = unit["hero_id"]
                if hid in target or unit["stars"] >= 2 or unit["item_ids"] or len(held[hid]) >= 2:
                    continue
                sell.append({"hero_id": hid, "name": ix["heroes"][hid]["name"], "count": 1,
                             "reason": "仅在明确选择此路线且不影响当前战力后可考虑出售。" if group == "bench" else "仅完成场上替换后再考虑出售；当前不能直接拆掉过渡前排或输出。",
                             "conditional": True, "location": group})
        if any(state.get(k) is None for k in ["hp", "gold", "level"]):
            roll = {"mode": "conditional", "max_gold_spend": None, "gold_floor": None,
                    "stop_conditions": ["先补齐血量、金币和等级，再决定搜牌或升级。", "当前阵容或血量无法确认时不安排固定回合梭哈。"],
                    "note": "输入不完整；没有估计搜中概率，也不推断缺失金币/血量。"}
        else:
            hp, gold = state["hp"], int(remaining_gold)
            # Explicit, conservative policy caps, not estimates of expected roll cost.
            budget = min(gold, 20) if hp <= 30 else max(0, gold - 50)
            roll = {"mode": "stabilize" if hp <= 30 else "economy", "max_gold_spend": budget,
                    "gold_floor": gold - budget,
                    "stop_conditions": ["购买上述已见目标后，后续搜牌达到此次预算即停；搜到后买牌也从此预算扣除。", "关键主C或前排达到本次保血质量后停，观察对手再追加投入。", "同行大量持有关键牌、战力已足够或需攒钱升级时，重新比较路线。"],
                    "note": "这是显式保守策略：先扣除上述商店购买，血量≤30后续最多投入20金币，否则优先留50；不含商店概率、卡池和下轮掉血预测，不是最优期望花费。"}
        visible_cost = sum(ix["heroes"][b["hero_id"]]["cost"] * b["count"] for b in buy)
        return {"buy": buy, "hold": hold, "sell_candidates": sell, "roll_plan": roll,
                "visible_shop_purchase_cost": visible_cost if state.get("gold") is not None else None,
                "level_plan": self._level_plan(state, board, three)}

    def _level_plan(self, state: dict, board: list[dict], three: set[str], target_level: int | None = None) -> dict:
        """State the template population goal without inventing XP tables or exact upgrade spend."""
        held, _ = self._holdings(state)
        target_level = target_level if target_level is not None else len(board) or None
        requirements = []
        important = [u for u in board if u.get("is_carry") or u["hero_id"] in three]
        front = next((u for u in board if str(u.get("position") or "").startswith("1,")), None)
        if front and front not in important:
            important.append(front)
        for unit in important[:5]:
            requirements.append({"hero_id": unit["hero_id"], "name": unit["name"],
                                 "target_stars": 3 if unit["hero_id"] in three else 2,
                                 "current_best_stars": max([h["stars"] for h in held.get(unit["hero_id"], [])] or [0])})
        missing_state = any(state.get(k) is None for k in ["hp", "gold", "level"])
        incomplete = any(q["current_best_stars"] < q["target_stars"] for q in requirements)
        if missing_state:
            action = "wait_for_information"
        elif three and incomplete:
            action = "hold_level_for_reroll"
        elif state.get("hp", 100) <= 30 and incomplete:
            action = "stabilize_before_leveling"
        elif target_level and state["level"] < target_level:
            action = "consider_leveling_after_quality"
        else:
            action = "maintain_or_improve_quality"
        return {"current_level": state.get("level"), "target_level": target_level, "action": action,
                "upgrade_cost": None, "xp_needed": None, "quality_requirements": requirements,
                "note": "目标人口来自候选模板；升级前先比较上述主C/前排质量与当前对手。当前经验和版本升级经验表未接入，不估算精确升级金币，不强制某回合升级。"}

    def _external_prior(self, board: list[dict]) -> dict | None:
        names = {u["name"] for u in board}
        rows = self.external.get("comp_list_rows", [])
        best, similarity = None, 0.
        for row in rows:
            other = {h["heroName"] for h in row.get("heroes", []) if h.get("heroType", 0) == 0}
            sim = len(names & other) / len(names | other) if names | other else 0
            if sim > similarity:
                best, similarity = row, sim
        if best is None or similarity < .7:
            return None
        return {"kind": "external_terminal_prior", "source_name": self.external["metadata"]["source_name"],
                "source_url": self.external["metadata"]["source_url"] + "comp/" + str(best["compId"]),
                "comp_name": best["name"], "top4_rate": best.get("top4Rate"), "first_rate": best.get("topRate"),
                "avg_placement": best.get("avgPlacement"), "sample_count": best.get("sampleCount"),
                "match_method": "终局阵容英雄集合近似匹配", "roster_jaccard": round(similarity, 3),
                "used_in_score": False,
                "warning": "非官方历史成型阵容统计；抽样与队列未披露。存在成型选择偏差，不能解释为当前状态或执行此操作后的胜率。"}

    def _nature_candidates(self, state: dict) -> list:
        ix, held_data = self.indices["nature"], self._holdings(state)[0]
        held = set(held_data)
        current_traits = self._active_traits("nature", self._trait_counts("nature", [u["hero_id"] for u in state["board"]]))
        candidates = []
        for template in self.data["nature"]["official_published_lineups"]:
            three = {self._canonical_hero("nature", i) for i in self._ids(template.get("three_star_targets"))} - {None}
            board = self._board("nature", template.get("main_board", []), three)
            if not board:
                continue
            targets = {u["hero_id"] for u in board}
            weighted, weight = 0., 0.
            for unit in board:
                w = 2 if unit["is_carry"] else 1
                quality = max([u["stars"] for u in held_data.get(unit["hero_id"], [])] or [0])
                weighted += w * (0.65 + .35 * min(quality / unit["target_stars"], 1) if quality else 0)
                weight += w
            roster = weighted / weight
            plan, item_fit = self._items_plan(state, board)
            target_traits = self._active_traits("nature", self._trait_counts("nature", list(targets)))
            trait_fit = len(current_traits & target_traits) / len(target_traits) if target_traits else 0.
            desired = set()
            for v in (template.get("augment_recommendations") or {}).values():
                desired.update(i for i in self._ids(v) if i in ix["augments"])
            augment_fit = len(set(state["augment_ids"]) & desired) / len(state["augment_ids"]) if state["augment_ids"] else 0.
            missing_cost = sum(u["cost"] for u in board if u["hero_id"] not in held)
            retain = len(targets & held) / max(len(held), 1)
            transition = .5 * retain + .5 * max(0., 1 - missing_cost / max(sum(u["cost"] for u in board), 1))
            breakdown = {"roster": round(40 * roster, 2), "items": round(25 * item_fit, 2),
                         "traits": round(15 * trait_fit, 2), "augments": round(10 * augment_fit, 2),
                         "transition": round(10 * transition, 2)}
            sources = [{"name": "官方掌盟阵容模板", "url": template["source_url"], "template_id": template["id"],
                        "author": template.get("source_author"), "published_at": template.get("published_at"),
                        "submitted_at": template.get("submitted_at"), "verified_strength_patch": None,
                        "note": "配置已切当前版本；攻略原内容和强度可能较旧。"}]
            mismatch = [f"{level}级模板含{len(self._board('nature', b, three))}个英雄" for level, b in (template.get("boards_by_level") or {}).items()
                        if str(level).isdigit() and len(self._board("nature", b, three)) != int(level)]
            actions = self._actions(state, board, three)
            population_refs = [int(k) for k in (template.get("boards_by_level") or {}) if str(k).isdigit()]
            if population_refs:
                actions["level_plan"] = self._level_plan(state, board, three, max(population_refs))
            candidates.append({"id": "nature-" + template["id"], "name": template["name"],
                               "score": round(sum(breakdown.values()), 2), "score_breakdown": breakdown,
                               "state_probability": None,
                               "reasons": [f"已持有目标{len(targets & held)}/{len(targets)}种；装备适配{item_fit:.0%}为资源匹配程度。",
                                           f"缺失目标一星购入价格下界{missing_cost}金币；不含刷新、升级和追星费用，且不代表可刷到。"],
                               "main_board": board,
                               "transition_boards": [{"level": int(k), "label": f"官方{k}人口过渡参考", "units": self._board("nature", v, three)}
                                                     for k, v in (template.get("boards_by_level") or {}).items() if str(k).isdigit() and v],
                               "items_plan": plan, "augment_choices": self._augment_choices(state, desired, target_traits),
                               "actions": actions, "sources": sources,
                               "template_warnings": mismatch + ["羁绊仅按唯一英雄基础计数；拉克丝等特殊计数未模拟。"],
                               "transition_cost": {"missing_one_star_purchase_lower_bound": missing_cost, "roll_cost": None, "xp_cost": None},
                               "external_terminal_prior": self._external_prior(board),
                               "operation_timing_reference": template.get("operation_timing_tokens", {}),
                               "timing_reference_note": "旧攻略节奏索引；不是对当前状态的固定回合指令。",
                               "filtered_stale_references": self._stale_references(template)})
        return self._top_distinct(candidates)

    def _stale_references(self, template: dict) -> list:
        ix = self.indices["nature"]
        valid_charms = {c["id"] for c in self.data["nature"]["charm_variant_records"]}
        missing = []
        for v in (template.get("augment_recommendations") or {}).values():
            missing += ["augment:" + x for x in self._ids(v) if x not in ix["augments"]]
        for entry in template.get("charms_by_stage") or []:
            missing += ["charm:" + x for x in entry.get("adventure", []) if x not in valid_charms]
        return sorted(set(missing))

    @staticmethod
    def _top_distinct(candidates: list) -> list:
        result, seen = [], set()
        for candidate in sorted(candidates, key=lambda x: (-x["score"], x["id"])):
            signature = tuple(sorted(u["hero_id"] for u in candidate["main_board"]))
            if signature in seen:
                continue
            seen.add(signature)
            result.append(candidate)
            if len(result) == 3:
                break
        return result

    def _unlock_chains(self, mode: str, core_names: set[str]) -> list:
        groups = self.data[mode].get("champion_unlock_task_groups", [])
        by_name = {x["hero_name"]: x for x in groups}
        source = self.indices[mode]["sources"].get("missionurl", {}).get("url")
        queue, seen, result = list(sorted(core_names)), set(), []
        while queue and len(result) < 8:
            name = queue.pop(0)
            if name in seen or name not in by_name:
                continue
            seen.add(name)
            group = by_name[name]
            tasks = []
            for task in group["tasks"]:
                mentions = task.get("entity_mentions", [])
                tasks.append({"task_id": task["id"], "task_type": task.get("task_type_source"),
                              "entity_mentions": mentions, "numeric_tokens": task.get("condition_numeric_tokens", []),
                              "progress": "unknown", "condition_verified": False,
                              "note": "这些是官方任务检索字段，数字未绑定完整条件；请在客户端核对触发、进度和解锁顺序。"})
                queue.extend(n for n in mentions if n not in seen)
            result.append({"hero_id": group["hero_id"], "hero_name": name, "tasks": tasks,
                           "source_url": source, "relation": "task_mentions_not_executable_trigger_chain"})
        return result

    def _orange_candidates(self, state: dict) -> list:
        ix = self.indices["orange"]
        held, _ = self._holdings(state)
        held_names = {ix["heroes"][h]["name"] for h in held}
        selected = set(state["orange_card_ids"])
        name_ids = {}
        for hid, hero in ix["heroes"].items():
            if hero.get("shows_in_official_gallery"):
                name_ids.setdefault(hero["name"], hid)
        candidates = []
        for i, recipe in enumerate(self.orange_research["recipes"]):
            card_ids = recipe["card_ids_exact_match"]
            if len(card_ids) != 3 or None in card_ids or len(set(card_ids)) != 3 or not all(c in ix["cards"] for c in card_ids):
                continue
            text = recipe["name"] + " " + recipe["logic_summary_ours"] + " ".join(recipe["card_names_as_published"])
            core_names = {name for name in name_ids if len(name) >= 2 and name in text}
            # Unnamed generic recipes retain the player's current core rather than inventing a fixed lineup.
            suggested_names = core_names or held_names
            core = [{"hero_id": name_ids[n], "name": n, "cost": ix["heroes"][name_ids[n]]["cost"],
                     "position": None, "item_ids": [], "item_names": [], "is_carry": False, "target_stars": None}
                    for n in sorted(suggested_names) if n in name_ids][:6]
            card_fit = len(selected & set(card_ids)) / 3
            roster_fit = len(held_names & core_names) / len(core_names) if core_names else .25 if held_names else 0
            current_traits = self._active_traits("orange", self._trait_counts("orange", [u["hero_id"] for u in state["board"]]))
            target_traits = self._active_traits("orange", self._trait_counts("orange", [u["hero_id"] for u in core]))
            trait_fit = len(current_traits & target_traits) / len(target_traits) if target_traits else 0
            # No item build templates exist for these seeds; never award synthetic equipment fit.
            breakdown = {"cards": round(50 * card_fit, 2), "roster": round(20 * roster_fit, 2),
                         "items": 0., "traits": round(10 * trait_fit, 2),
                         "transition": round(10 * len(held_names & suggested_names) / max(len(held_names), 1), 2)}
            deck_change = bool(selected and selected != set(card_ids))
            cards = [{"id": c, "name": ix["cards"][c]["name_zh"], "owned": c in selected,
                      "rarity_tier": ix["cards"][c]["rarity_tier"],
                      "energy_assumption": ix["cards"][c].get("deck_energy_assuming_tier_mapping"),
                      "activation_rounds": ix["cards"][c].get("activation_rounds", [])} for c in card_ids]
            source = self.orange_research["sources"][recipe["source_id"]]
            actions = self._actions(state, core, set())
            # A core-only seed cannot identify which other units are expendable.
            actions["sell_candidates"] = []
            actions["hold"] = [{"hero_id": h, "name": ix["heroes"][h]["name"], "count": len(units),
                                "reason": "完整目标棋盘未知，先保留现有过渡单位；不可因未出现在核心列表中就出售。"}
                               for h, units in held.items()]
            actions["level_plan"] = {"current_level": state.get("level"), "target_level": None,
                                      "action": "need_full_lineup", "upgrade_cost": None, "xp_needed": None,
                                      "quality_requirements": [],
                                      "note": "只有卡组与解锁核心，目标人口和完整过渡棋盘尚未知；保留现有单位，先补齐对局及任务进度，不据此给精确升级或卖牌指令。"}
            # A deck that differs from the cards already brought cannot drive live purchases or roll spending.
            if deck_change:
                actions["buy"] = []
                actions["visible_shop_purchase_cost"] = None
                actions["roll_plan"] = {
                    "mode": "conditional", "max_gold_spend": None, "gold_floor": None,
                    "stop_conditions": ["此卡组与已填带入卡片不同，仅作下一局战前备选。"],
                    "note": "局内不能据此更换带入卡片；当前对局操作不沿用这套构筑。"}
            candidates.append({"id": f"orange-{i}", "name": recipe["name"], "score": round(sum(breakdown.values()), 2),
                               "score_breakdown": breakdown, "state_probability": None,
                               "reasons": [recipe["logic_summary_ours"], f"与已填带入卡片匹配{len(selected & set(card_ids))}/3张。",
                                           "只有构筑与任务核心资料，没有完整终局棋盘和装备样本。"],
                               "main_board": core, "board_status": "core_only_no_full_board_template", "transition_boards": [],
                               "items_plan": [], "augment_choices": self._augment_choices(state, set(), target_traits),
                               "orange_cards": cards, "deck_change_required": deck_change,
                               "use_timing": "pre_match_only" if deck_change else "verify_current_cards_then_use",
                               "legality": {"status": "pending_client_rules", "three_distinct_known_cards": True,
                                            "portal_energy_verified": False, "global_buff_limit_verified": False,
                                            "energy_sum_assumption": sum(c["energy_assumption"] or 0 for c in cards),
                                            "note": "三张卡ID已确认且不重复；能量和全局增益限制未核验，尚不能宣称完全合法。"},
                               "unlock_chains": self._unlock_chains("orange", core_names), "actions": actions,
                               "sources": [{"name": "构筑资料", **source},
                                           {"name": "官方卡片配置", "url": ix["sources"].get("cardurl", {}).get("url")}],
                               "template_warnings": ["卡组效果及强度未实机验证；解锁条件不能只看数字或实体名称。"],
                               "external_terminal_prior": None, "recipe_validation_status": recipe["validation_status"]})
        # Generic cores can coincide, but distinct deck choices remain meaningful.
        return sorted(candidates, key=lambda c: (-c["score"], c["deck_change_required"], c["id"]))[:3]
