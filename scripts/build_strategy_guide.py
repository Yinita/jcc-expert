#!/usr/bin/env python3
"""Build the static trait/composition operation guide from attributed records."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]

TRAIT_NOTES = {
    ("nature", "origin:450"): "永恒之森提供可放置植物；树、花等pet不占普通人口。升级羁绊前同时比较核心质量与植物站位。",
    ("nature", "origin:451"): "黑荆棘要结合献祭对象与前排分工；替换单位时不能只数羁绊，需重新核对献祭、装备和站位。",
    ("nature", "origin:452"): "灵魂莲华与精灵/成长资源关联；追星与升级路线对资源的用途不同，依实际阵容核心决定。",
    ("nature", "origin:456"): "约德尔人常与低费质量联动；原生池不是所有牌一起追三的清单，先认所选路线的主C和主坦。",
    ("nature", "origin:458"): "地狱火相关的灼烧联动需要核对；同羁绊的不同技能与伤害加成，不能统一分配物理或法强装备。",
    ("nature", "origin:461"): "日月双蚀配置numList为0且没有原生棋子。本资料只展示其效果，不由名字补猜激活条件或编一套可购买的独立棋盘。",
    ("nature", "class:348"): "魔战士有不同加成分支。先核对技能与装备形成的实际分支，职业名不等于物理/魔法伤害类型。",
    ("nature", "class:350"): "神谕的实际激活档位会影响施法支持与回蓝需求；先看主C技能，再比较回蓝装和更多输出装。",
    ("nature", "class:351"): "召唤师要区分普通棋子与pet/召唤物。核心质量和保护一起核对，图上模型数量不能作为人口。",
    ("orange", "origin:340"): "比尔吉沃特以银蛇币和黑市为轴；核对当前收入与可买强化，再选择输出或前排承接者，不套用自然之力同ID资料。",
    ("orange", "origin:342"): "弗雷尔卓德横跨过渡与高费补强。奥恩神器卡组只有机制核心，一张奥恩不代表已开完整弗雷尔卓德。",
    ("orange", "origin:344"): "以绪塔尔要跟踪任务、奖励和科技钥匙进度。先用已解锁原生牌承接，不能预设岩宝、任务奖励或固定回合升级。",
    ("orange", "origin:346"): "皮尔特沃夫涉及科技与装备资源。辨认奖励是否真的到账、适合谁，再决定继续升档的投入。",
    ("orange", "origin:347"): "暗影岛需要结合战斗与灵魂进度理解，同样羁绊数不能代替实际触发状态。",
    ("orange", "origin:350"): "虚空包含需要解锁的高费/怪物单位。先用可买到的两星承接，不把纳什男爵当开局已有。",
    ("orange", "origin:351"): "约德尔人要区分低费质量与高费解锁。复制卡带来质量资源，不保证任意单位当场四星。",
    ("orange", "origin:352"): "祖安各原生棋子的伤害与功能不同；法术后排、物理普攻和前排承伤不共用一套装备判断。",
    ("orange", "origin:382"): "暗裔计数必须看棋子和装备实际提供的内容。恶魔降世额外给的是裁决战士，不能算成额外暗裔。",
    ("orange", "class:297"): "狙神不是物理输出同义词：本模式提莫、克格莫、吉格斯均有明确魔法伤害，需逐棋子配装。",
    ("orange", "class:298"): "迅击战士包含不同伤害与进化阶段。无蓝条凯尔不机械使用回蓝/需施法收益装备；普攻法伤也不是物理伤害。",
    ("orange", "class:299"): "裁决战士不统一等于物理出装。暮光路线接亚恒和亚托克斯，易的法术普攻需要另一种装备分工。",
    ("orange", "class:300"): "法师的原生牌、施法频率和技能加成分别核对；需要施法/回蓝的纹章收益不能机械套给无蓝条被动单位。",
}


def clean(value):
    return re.sub(r"<[^>]+>", "", str(value or "")).replace("&nbsp;", " ").strip()


def unique(values):
    return list(dict.fromkeys(values))


def ids(value):
    return [x for x in re.split(r"[,|]", str(value or "")) if x and x not in ("0", "-1")]


def canonical_id(source_id, records, heroes):
    source_id = str(source_id)
    if source_id in heroes:
        return source_id, True
    source = records.get(source_id)
    if not source:
        return source_id, False
    matches = [r for r in records.values() if r.get("observed_star_level") == 1
               and r.get("base_form_id") == source.get("base_form_id")
               and r["name"] == source["name"]
               and r.get("origin_ids", []) == source.get("origin_ids", [])
               and r.get("class_ids", []) == source.get("class_ids", [])]
    return (str(matches[0]["official_id"]), True) if len(matches) == 1 else (source_id, False)


def normalize_board(board, records, heroes):
    result = []
    for unit in board:
        raw_id = str(unit.get("hero_id", ""))
        hero_id, mapped = canonical_id(raw_id, records, heroes)
        record = records.get(raw_id, records.get(hero_id, {}))
        pet = unit.get("type", "hero") == "pet"
        row = {"hero_id": hero_id, "source_hero_id": raw_id,
               "hero_name": unit.get("hero_name") or heroes.get(hero_id, {}).get("name") or record.get("name") or f"ID {raw_id}",
               "type": "pet" if pet else "hero", "is_pet": pet, "is_carry": bool(unit.get("is_carry")),
               "item_ids": [str(i) for i in unit.get("item_ids", [])], "identity_mapped": mapped}
        try:
            r, c = map(int, str(unit.get("position", "")).split(","))
            if 1 <= r <= 4 and 1 <= c <= 7:
                row.update(row=r, col=c)
        except (TypeError, ValueError):
            pass
        result.append(row)
    return result


def validate_population(board, population=None):
    count = sum(not u["is_pet"] for u in board)
    notes = []
    status = "source" if board else "not_provided"
    if population is not None and count > population:
        status = "source_invalid_population"
        notes.append(f"源图标称{population}人口却列{count}个普通单位；需核对额外人口来源，不能按标准人口照抄。原图单位全部保留。")
    elif population is not None and count < population:
        status = "source_partial_population"
        notes.append(f"源图列{count}个普通单位/{population}人口；未指定的空位不自行补猜。")
    if any(u["is_pet"] for u in board):
        notes.append("pet/植物/召唤物单独显示，不计普通人口。")
    if any(not u.get("identity_mapped") and not u["is_pet"] for u in board):
        notes.append("有普通单位形态ID未能唯一规范化，不按同名合并。")
    return {"board_status": status, "actual_unit_count": count, "pet_count": sum(u["is_pet"] for u in board), "validation_notes": notes}


def names(values, heroes):
    return "、".join(heroes.get(str(v), {}).get("name", str(v)) for v in values)


def strategy_heroes(mode, facts, guide_mode, reference, assets):
    result = [{**h, "guide_available": True, "template_only_form": False, "native_pool_eligible": True}
              for h in guide_mode["heroes"]]
    lookup = {h["id"]: h for h in result}
    records = {str(h["official_id"]): h for h in facts["champion_star_form_records"]}
    trait_map = {(t["kind"], str(t["id"])): t for t in guide_mode["traits"]}
    used = set()
    for comp in facts.get("official_published_lineups", []):
        for board in [comp.get("main_board", []), comp.get("early_board", []), comp.get("mid_board", []),
                      *comp.get("boards_by_level", {}).values()]:
            used.update(str(u["hero_id"]) for u in board)
        for replace in comp.get("hero_replacements") or []:
            used.add(str(replace["hero_id"]))
            used.update(ids(replace.get("replace_heros")))
    for source_id in sorted(used):
        id, mapped = canonical_id(source_id, records, lookup)
        if not mapped or id in lookup:
            continue
        record = records.get(id, {})
        if record.get("hero_type_source") != "0":
            continue
        traits = [trait_map[(kind, str(t))] for kind, values in
                  [("origin", record.get("origin_ids", [])), ("class", record.get("class_ids", []))]
                  for t in values if (kind, str(t)) in trait_map]
        skill = reference.get("conditional_hero_skills", {}).get(mode, {}).get(id, {})
        h = {"id": id, "name": record["name"], "cost": record["cost"], "icon": assets.get((mode, "hero", id)),
             "traits": traits, "role": {"label": "来源中的条件形态", "ambiguous": True},
             "regular_shop_unit": True, "profession_status": "known" if record.get("class_ids") else "none",
             "guide_available": False, "template_only_form": True, "native_pool_eligible": False,
             "availability": "conditional_form", "skill": {"name": skill.get("name") or record.get("skill_name"),
             "description": clean(skill.get("description"))},
             "form_note": "仅按官方形态ID保留来源棋盘，不当作额外商店原生牌；不按同名映射到其他形态图鉴。"}
        lookup[id] = h
        result.append(h)
    return result


def make_phase(id, label, board, population, focus, actions, provenance="source"):
    return {"id": id, "label": label, "board": board, "population": population, "focus": focus,
            "actions": actions, "conditions": ["以当前血量、经济、来牌与同行为准，阶段图不是按回合必须买齐的指令。"],
            "provenance": provenance, **validate_population(board, population)}


def build_traits(mode, facts, guide_mode, reference):
    heroes = {h["id"]: h for h in guide_mode["heroes"]}
    result = []
    for row in reference["modes"][mode]["traits"]:
        key = row["kind"] + ":" + row["id"]
        native = [h for h in heroes.values() if h["regular_shop_unit"] and h.get("native_pool_eligible", True)
                  and any(t.get("key") == key and t.get("verified") for t in h["traits"])]
        native.sort(key=lambda h: (h["cost"], h["id"]))
        bp = row["breakpoints"]
        strategy_type = "unique" if (bp and max(bp) == 1) or not native else "splash" if bp and max(bp) <= 2 else "vertical"
        sr = next((s for s in facts["sources"] if s["source_key"] == row["source"]["source_key"]), {})
        effects = row["tier_effects_source"].split("|") if row["tier_effects_source"] else []
        tiers = [{"count": n, "effect": clean(effects[i]) if i < len(effects) else "该断点需对照来源。"} for i, n in enumerate(bp)]
        pool = {"early": [h["id"] for h in native if h["cost"] <= 2], "mid": [h["id"] for h in native if h["cost"] == 3], "late": [h["id"] for h in native if h["cost"] >= 4]}
        note = (f"用{names([h['id'] for h in native], heroes) or '对应机制'}接入已成型体系；独有能力不伪装为开局独立追满的终局。"
                if strategy_type == "unique" else f"先核对{bp[0] if bp else '起始'}档，再比较升档换人的代价；原生牌不是全部必拿。")
        notes = ([TRAIT_NOTES[(mode, key)]] if (mode, key) in TRAIT_NOTES else []) + [note]
        for stage, label in [("early", "低费过渡可选"), ("mid", "中期承接可选"), ("late", "高费补强可选")]:
            if pool[stage]:
                notes.append(label + "：" + names(pool[stage], heroes) + "；按来牌与当前功能选择，不要求全部上场。")
        result.append({"id": row["id"], "kind": row["kind"], "key": key, "name": row["name"], "verified": True,
                       "description": clean(row["prefix"]), "tiers": tiers, "breakpoints": bp,
                       "native_hero_ids": [h["id"] for h in native], "stage_pools": pool,
                       "conditional_hero_ids": [h["id"] for h in heroes.values() if h.get("template_only_form") and any(t.get("key") == key for t in h["traits"])],
                       "strategy_type": strategy_type, "summary": notes[0], "play_notes": notes,
                       "conditions": ["下列是本羁绊可选原生池，不是必须购买的清单或已验证棋盘。"],
                       "linked_comp_ids": [], "related_comp_ids": [], "trait_link_details": [],
                       "source": {"title": "官方特质配置" if row["kind"] == "origin" else "官方职业配置",
                                  "url": sr.get("url"), "version": row["source"]["version"],
                                  "generated_at": row["source"]["generated_at"], "sha256": row["source"]["original_file_sha256"]}})
    # Hero configuration references these IDs, but the official trait dictionary
    # has no definition. Preserve the existing guide's unresolved identity.
    for missing in guide_mode["traits"]:
        if missing.get("verified", True):
            continue
        key = missing["key"]
        native = [h for h in heroes.values() if any(t.get("key") == key for t in h["traits"])]
        pool = {"early": [h["id"] for h in native if h["cost"] <= 2], "mid": [h["id"] for h in native if h["cost"] == 3], "late": [h["id"] for h in native if h["cost"] >= 4]}
        result.append({"id": missing["id"], "kind": missing["kind"], "key": key, "name": missing["name"],
            "verified": False, "description": "官方英雄配置引用此ID，但当前特质字典没有定义；不猜名字、效果或断点。",
            "tiers": [], "breakpoints": [], "native_hero_ids": [h["id"] for h in native], "stage_pools": pool,
            "strategy_type": "unresolved", "summary": "保留原始ID与引用棋子，特质效果和打法待核验。",
            "play_notes": ["这里只是未解析ID的引用关系，不将其当作已知可激活体系。"],
            "conditions": ["未提供任何未知效果、断点或独立终局。"], "linked_comp_ids": [], "related_comp_ids": [],
            "trait_link_details": [], "source": missing.get("source", {})})
    return result


def trait_links(board, heroes, items, traits, mode=None):
    native, supplied = {}, {}
    for unit in board:
        if unit["is_pet"]:
            continue
        hero_id = unit["hero_id"]
        native_keys = {t["key"] for t in heroes.get(hero_id, {}).get("traits", []) if t.get("verified")}
        for key in native_keys:
            weight = 2 if mode == "nature" and "origin:469" in native_keys and key != "origin:469" else 1
            native.setdefault(key, {})[hero_id] = weight
        for item_id in unit["item_ids"]:
            for trait_id in items.get(item_id, {}).get("trait_ids", []):
                matches = [t["key"] for t in traits if t["id"] == str(trait_id)]
                if len(matches) == 1 and matches[0] not in native_keys:
                    supplied.setdefault(matches[0], set()).add(hero_id)
    result = []
    for trait in traits:
        if not trait.get("verified", True):
            continue
        key = trait["key"]
        n, e = sum(native.get(key, {}).values()), len(supplied.get(key, set()))
        if not n and not e:
            continue
        active = [v for v in trait["breakpoints"] if v <= n + e]
        native_active = [v for v in trait["breakpoints"] if v <= n]
        full_breakpoint = max(active) if active else None
        native_breakpoint = max(native_active) if native_active else None
        form_ids = [id for id in native.get(key, {}) if heroes.get(id, {}).get("template_only_form")]
        without_forms = sum(weight for id, weight in native.get(key, {}).items() if id not in form_ids)
        ordinary_breakpoint = max((v for v in trait["breakpoints"] if v <= without_forms), default=None)
        needs_emblems = bool(full_breakpoint and full_breakpoint > (native_breakpoint or 0))
        needs_form = bool(form_ids and full_breakpoint and full_breakpoint > (ordinary_breakpoint or 0))
        status = "conditional" if needs_emblems or needs_form else "activated" if full_breakpoint else "incidental"
        condition_notes = []
        if needs_emblems:
            condition_notes.append(f"原生仅到{native_breakpoint or 0}档；升至{full_breakpoint}档依赖模板纹章。")
        if needs_form:
            condition_notes.append("该档位依赖指定条件形态/其计数效果，不能拿同名基础形态代替：" + "、".join(form_ids) + "。")
        result.append({"key": key, "native_count": n, "emblem_count": e, "count": n + e,
                       "native_unit_count": len(native.get(key, {})), "counting_evidence": [
                           {"hero_id": id, "contribution": weight, "reason": "大元素使选定特质/职业提供2计数；独有大元素使自身仍计1。"}
                           for id, weight in native.get(key, {}).items() if weight != 1],
                       "active_breakpoint": full_breakpoint, "native_breakpoint": native_breakpoint,
                       "full_breakpoint": full_breakpoint, "required_emblems_for_full": max(0, (full_breakpoint or 0) - n), "status": status,
                       "conditional_form_ids": form_ids, "without_conditional_forms_breakpoint": ordinary_breakpoint,
                       "note": "来源模板达到起始档，不代表当前实战已激活。" if status == "activated" else
                               " ".join(condition_notes) if status == "conditional" else
                               "仅有关联原生牌，未达到起始档，不作为该羁绊成套路线。"})
    return result


def nature_comp(lineup, facts, reference, heroes, items, traits):
    records = {str(r["official_id"]): r for r in facts["champion_star_form_records"]}
    board = normalize_board(lineup["main_board"], records, heroes)
    regular = [u for u in board if not u["is_pet"]]
    target_ids = unique(canonical_id(t, records, heroes)[0] for t in ids(lineup.get("three_star_targets")))
    carry_ids = unique(u["hero_id"] for u in regular if u["is_carry"])
    front_ids = unique(u["hero_id"] for u in regular if u.get("row", 4) == 1)
    core_ids = unique(carry_ids + target_ids + [u["hero_id"] for u in regular if u["hero_id"] in front_ids and len(u["item_ids"]) >= 2])
    utility_ids = unique(u["hero_id"] for u in regular if u["hero_id"] not in core_ids and len(u["item_ids"]) <= 1
                         and (heroes.get(u["hero_id"], {}).get("cost", 9) <= 3 or u["hero_id"] not in front_ids))
    flex_ids = unique(u["hero_id"] for u in regular if u["hero_id"] not in core_ids and u["hero_id"] not in utility_ids)
    operation = reference["nature_operations"].get(str(lineup["id"]), {})
    reviewed = next((r for r in reference["reviewed_nature_summaries"] if r["lineup_id"] == str(lineup["id"])), {})
    carry_names = names(carry_ids, heroes) or "来源装备核心"
    front_names = names(front_ids, heroes) or "实际承伤单位"
    source = {"title": lineup["name"], "url": lineup["source_url"], "author": operation.get("author", lineup.get("source_author")),
              "published_at": operation.get("published_at", lineup.get("published_at")), "version": lineup.get("simulator_edition_source"),
              "kind": "official_published_author_template", "source_sha256": reference["nature_lineup_source"]["sha256"]}
    early = normalize_board(lineup.get("early_board", []), records, heroes)
    early_regular = [u for u in early if not u["is_pet"]]
    opening_pool = [u for u in early_regular if heroes.get(u["hero_id"], {}).get("cost", 9) <= 2]
    opening_names = names(unique(u["hero_id"] for u in opening_pool), heroes)
    phase2 = make_phase("stage2", "2阶段 · 打工与方向", opening_pool, None,
                        reviewed.get("opening") or f"观察来源早期名单中的{opening_names or '低费体系牌'}，围绕实际两星与装备过渡。",
                        ["这里只列源早期棋盘中的低费可选体系牌，不是四/五人口完整阵容。"], "editorial_source_pool")
    phase2.update(board_status="source_subset" if opening_pool else "not_provided", source_population=len(early_regular))
    stages = [phase2]
    for pid, label, level, summary_key in [("stage3", "3阶段 · 建立中期质量", "6", "midgame"),
                                            ("stage4", "4阶段 · 核心成型", "8", "endgame"),
                                            ("late", "后期 · 补强与对位", "9", "endgame")]:
        units = normalize_board(lineup.get("boards_by_level", {}).get(level, []), records, heroes)
        focus = reviewed.get(summary_key) or f"检查{carry_names}输出和{front_names}承伤；这里是作者{level}人口图，不代表该阶段必须升到此人口。"
        actions = [f"作者{level}人口示例只作阶段参考；实际是否升级要比较血量、金币与棋盘质量。"]
        if pid == "stage3" and target_ids:
            actions.append(f"来源追三星候选：{names(target_ids, heroes)}；先区分主要目标和顺带追的牌。")
        if pid == "stage4":
            actions.append(f"优先核对{carry_names}和{front_names}的关键质量，再分配追星或升级预算。")
        if pid == "late":
            actions.append("换高费之前重新数关键羁绊与功能；未两星的高费不自动优于已有成型单位。")
        stages.append(make_phase(pid, label, units, int(level), focus, actions))
    style = "slow_roll" if operation.get("slow_roll") else "upgrade_and_stabilize" if not target_ids else "quality_reroll"
    actions = []
    if operation.get("avoid_early_roll"):
        actions.append("作者倾向前期少搜/不搜；如果血量已难以承受，要先处理即时战力。")
    if operation.get("stage_mentions"):
        actions.append("作者参考时点：" + "、".join(operation["stage_mentions"]) + "；不保证准时成型。")
    if operation.get("level_mentions"):
        actions.append("作者运营文字涉及人口：" + " / ".join(map(str, operation["level_mentions"])) + "；不是必须逐项执行的升级表。")
    if operation.get("economy_mentions"):
        actions.append("作者提及保留经济：" + " / ".join(map(str, operation["economy_mentions"])) + "；血量和同行变化时重新评估。")
    if target_ids:
        actions.append(f"以{names(target_ids, heroes)}为追星候选；不要为所有候选同时锁死经济。")
    stops = [f"{carry_names}和{front_names}达到支撑后续战斗的质量后暂停消耗，重新比较升级收益。"]
    if operation.get("two_star_stop"):
        stops.insert(0, "作者给出体系二星后的停搜/升级节点，先核对实际关键牌是否到齐。")
    if target_ids:
        stops.append("同行占牌、追星张数不足或预算用完时停止无预算追三；来源不保证未来抽牌。")
    replacements = [{"from_id": canonical_id(r["hero_id"], records, heroes)[0],
                     "to_ids": [canonical_id(v, records, heroes)[0] for v in ids(r.get("replace_heros"))],
                     "reason": "作者替换候选；换牌后重算羁绊、分装与功能。", "provenance": "source"}
                    for r in (lineup.get("hero_replacements") or [])]
    links = trait_links(board, heroes, items, traits, mode="nature")
    position_notes = ["作者站位是示例，要根据敌方主C、切后排和范围技能调整。"]
    if operation.get("position_flags"):
        position_notes.append("作者对位要点：" + "、".join(operation["position_flags"]) + "；对象以来源与当前对手为准。")
    if reviewed.get("risk"):
        position_notes.append(reviewed["risk"])
    return {"id": str(lineup["id"]), "name": lineup["name"], "kind": "official_lineup",
            "summary": reviewed.get("opening") or f"围绕{carry_names}输出，配合{front_names}承伤，分别查看追星、人口和装备。",
            "core_ids": core_ids, "carry_ids": carry_ids, "frontline_ids": front_ids, "utility_ids": utility_ids, "flex_ids": flex_ids,
            "trait_keys": [r["key"] for r in links if r["status"] != "incidental"], "trait_links": links,
            "phases": stages, "source_early_board": early,
            "roll_plan": {"style": style, "actions": actions, "stop_conditions": stops,
                          "pivot_conditions": ([reviewed["risk"]] if reviewed.get("risk") else []) +
                          ["核心被同行占用或缺关键装备时，保留能转型的两星与装备，不按标题硬玩。"],
                          "provenance": "source_mentions_and_editorial_conditions"},
            "equipment": [{"hero_id": u["hero_id"], "hero_name": u["hero_name"], "item_ids": u["item_ids"],
                          "role": "主C" if u["is_carry"] else "来源分装", "reason": "作者指定装备，不是组合胜率。", "provenance": "source"}
                         for u in regular if u["item_ids"]],
            "positioning": {"summary": "作者主棋盘示例；植物与普通人口分别计算", "board": board, "notes": position_notes},
            "three_star_ids": target_ids, "replacements": replacements, "augment_ids": ids((lineup.get("augment_recommendations") or {}).get("recomm")),
            "card_ids": [], "source": source,
            "notes": ["分工由作者主C标记、追星目标、分装及站位整理，不等于原生牌全部必拿。", "没有使用收录S/A标签作为当前强度或胜率排序。"]}


def orange_comps(research, facts, reference, heroes, items, traits):
    results = []
    reviewed = {r["name"]: r for r in reference["orange_recipe_notes"]}
    for index, recipe in enumerate(research["recipes"]):
        if not recipe["validation_status"].startswith("recipe_source_verified"):
            continue
        note = reviewed.get(recipe["name"], {})
        core = note.get("core_hero_ids", [])
        if recipe["name"] == "月神厄斐琉斯流":
            core = ["12417"]
        sr = research["sources"][recipe["source_id"]]
        source = {"title": recipe["name"], "url": sr["url"], "published_at": sr.get("published"),
                  "author": "金铲铲之战（官方内容镜像）", "version": "18.6参考", "kind": sr["type"]}
        source_status = "published_recipe"
        if recipe["name"] == "连胜杰作流":
            source_status = "provisional_recipe"
            source = {"title": "官方账号搜索摘要支持；单帖全文未核验", "url": "https://www.sina.cn/media/7504806444",
                      "published_at": "2026-11-04", "author": "金铲铲之战官方账号（搜索摘要）",
                      "version": "18.6参考", "kind": "official_search_snippet_not_full_post"}
        board = [{"hero_id": id, "source_hero_id": id, "hero_name": heroes.get(id, {}).get("name", id),
                  "type": "hero", "is_pet": False, "is_carry": False, "item_ids": [], "identity_mapped": id in heroes} for id in core]
        card_ids = [c for c in recipe["card_ids_exact_match"] if c]
        caveat = note.get("caveat") or "卡片配方有来源，完整棋盘与逐阶段打法未建立可靠模板；跟随实际来牌。"
        if source_status == "provisional_recipe":
            caveat = "三卡组合仅有官方账号搜索摘要及二级攻略支持，单帖全文未核验；卡片具体效果以官方配置为据。凯旋是首次赢得10场玩家对战，不要求10连胜，也不是第10回合。"
        summary = note.get("summary_ours") or recipe["logic_summary_ours"]
        phases = []
        for pid, label, focus in [("stage2", "2阶段 · 卡片与解锁", summary),
                                  ("stage3", "3阶段 · 检查兑现", "检查卡片真正触发、核心解锁及实际两星，不能把启用时间当奖励到账。"),
                                  ("stage4", "4阶段 · 资源转质量", "资源到账后补主C与承伤质量，卡片奖励不等于已有完整终局。"),
                                  ("late", "后期 · 核心与补强", "按已解锁单位、装备与血量补强；来源没给固定八人棋盘。")]:
            phase = make_phase(pid, label, board if core else [], None, focus, [caveat], "source_recipe_core_only")
            stage_number = {"stage2": (1, 2), "stage3": (3,), "stage4": (4,), "late": (5, 6, 7)}[pid]
            for card_id in card_ids:
                card = next((c for c in facts.get("time_cards", []) if str(c["id"]) == card_id), {})
                rounds = card.get("activation_rounds", [])
                if any(str(r).split("-")[0].isdigit() and int(str(r).split("-")[0]) in stage_number for r in rounds):
                    description = reference.get("orange_card_reference", {}).get("cards", {}).get(card_id, {}).get("description")
                    if description:
                        phase["actions"].append(f"卡片{card.get('name_zh', card_id)}启用参考 {' / '.join(rounds)}：{clean(description)} 条件奖励须实际触发，不能当作即时到账。")
            phase.update(board_status="core_only" if core else "not_provided",
                         conditions=["只显示机制核心，不确认核心此阶段一定可获得，也不是完整可执行棋盘。"])
            phases.append(phase)
        links = trait_links(board, heroes, items, traits, mode="orange")
        # Source wording is total contribution 2, not +2 extra copies/count.
        demon = reference.get("orange_card_reference", {}).get("cards", {}).get("7240061", {})
        if "7240061" in card_ids and "15296" in core and "总计提供+2【裁决战士】" in demon.get("description", ""):
            link = next((r for r in links if r["key"] == "class:299"), None)
            if link:
                link["card_bonus_count"] = 1
                link["count"] += 1
                bp = next(t["breakpoints"] for t in traits if t["key"] == "class:299")
                link["full_breakpoint"] = max((v for v in bp if v <= link["count"]), default=None)
                link["active_breakpoint"] = link["full_breakpoint"]
                link["status"] = "conditional"
                link["required_emblems_for_full"] = 0
                link["requires_card_ids"] = ["7240061"]
                link["note"] = "恶魔降世实际触发后，亚托克斯总计提供2裁决战士（基础1加卡片净增1），不是额外2；两张同名牌不另计。"
        results.append({"id": f"orange-{index+1}", "name": recipe["name"], "kind": "orange_recipe", "source_status": source_status, "summary": summary,
                        "trait_keys": [r["key"] for r in links if r["status"] != "incidental"], "trait_links": links,
                        "core_ids": core, "carry_ids": core if recipe["name"] in ("月神厄斐琉斯流", "灼烧炼狱流") else [],
                        "frontline_ids": [], "utility_ids": [], "flex_ids": [], "phases": phases,
                        "roll_plan": {"style": "card_conditional", "actions": [summary, caveat],
                                      "stop_conditions": ["先核对已到账资源与核心质量；没有来源支持固定搜牌预算或保证升级回合。"],
                                      "pivot_conditions": ["关键卡片、解锁或来牌不成立时停止照搬，转向可落地的两星与羁绊。"],
                                      "provenance": "source_recipe_and_editorial_risk_conditions"},
                        "equipment": [], "positioning": {"summary": "未提供完整站位图", "board": [], "notes": ["只有配方/核心证据，不补造八人站位。"]},
                        "three_star_ids": [], "replacements": [], "augment_ids": [], "card_ids": card_ids,
                        "published_card_names": recipe["card_names_as_published"], "unresolved_card_names": recipe["alias_resolution_required"],
                        "card_timeline": note.get("card_timeline", {}), "portal_claim": recipe.get("portal_claim"), "source": source,
                        "notes": [caveat, "卡片启用回合不自动等于条件奖励到账回合；没有条件胜率或完整逐回合棋盘样本。"]})
    return results


def build_strategy(base=BASE):
    reference = json.loads((base / "app/data/strategy_reference.json").read_text())
    guide = json.loads((base / "app/static/guide-data.json").read_text())
    research = json.loads((base / "app/data/orange_research.json").read_text())
    manifest = json.loads((base / "app/assets/manifest.json").read_text())
    assets = {(r["mode"], r["kind"], str(r["entity_id"])): "assets/" + r["path"]
              for r in manifest["assets"] if (base / "app/assets" / r["path"]).is_file()}
    out = {"schema_version": "strategy-guide-v1", "generated_at": "2026-11-17",
           "meta": {"rules_patch": "18.6", "data_as_of": "2026-11-10",
                    "notice": "18.6规则与历史作者模板参考；已有18.6a公告，未证明适用当前补丁，也不保证吃鸡。",
                    "provenance_notice": "原始棋盘、卡片核心、局部体系牌与编辑条件分开标注。无完整模板不编满人口终局。",
                    "position_convention": "row1为己方前排、row4为后排；col1至7从左到右。",
                    "native_pool_notice": "原生池不是全部必拿；独有羁绊通常作为补强或挂件。",
                    "sources": reference["research_sources"]}, "modes": {}}
    for mode, filename in [("nature", "nature_facts.json"), ("orange", "orange_base_facts.json")]:
        facts = json.loads((base / "app/data" / filename).read_text())
        gm = dict(guide["modes"][mode])
        gm["heroes"] = strategy_heroes(mode, facts, gm, reference, assets)
        traits = build_traits(mode, facts, gm, reference)
        heroes = {h["id"]: h for h in gm["heroes"]}
        items = {i["id"]: i for i in gm["items"]}
        comps = ([nature_comp(r, facts, reference, heroes, items, traits) for r in facts.get("official_published_lineups", [])]
                 if mode == "nature" else orange_comps(research, facts, reference, heroes, items, traits))
        for trait in traits:
            for comp in comps:
                link = next((r for r in comp["trait_links"] if r["key"] == trait["key"]), None)
                if link:
                    trait["trait_link_details"].append({"comp_id": comp["id"], **link})
                    trait["related_comp_ids" if link["status"] == "incidental" else "linked_comp_ids"].append(comp["id"])
            if not trait["linked_comp_ids"]:
                trait["no_template_reason"] = "没有达到起始档的完整来源模板；使用原生阶段池查看接入条件，不编独立终局。"
        cards = [{"id": str(c["id"]), "name": c.get("name_zh", c.get("name")),
                  "icon": assets.get((mode, "card", str(c["id"]))),
                  "activation_rounds": c.get("activation_rounds", []), "parameters_raw": c.get("parameters_raw", {}),
                  "description": clean(reference.get("orange_card_reference", {}).get("cards", {}).get(str(c["id"]), {}).get("description")),
                  "trigger_conditions": [clean(s) for s in re.split(r"[。；]", reference.get("orange_card_reference", {}).get("cards", {}).get(str(c["id"]), {}).get("description", ""))
                                         if re.search(r"首次|每当|每回合|当|如果|累计|合成|低于|高于|击败|升级", s)][:3],
                  "source": {"title": "官方时间卡片配置", "url": reference.get("orange_card_reference", {}).get("source_url"),
                             "version": reference.get("orange_card_reference", {}).get("version"), "sha256": reference.get("orange_card_reference", {}).get("source_sha256")}}
                 for c in facts.get("time_cards", [])]
        out["modes"][mode] = {"id": mode, "name": facts["scope"]["mode"], "traits": traits, "comps": comps,
            "heroes": [{k: h[k] for k in ["id", "name", "cost", "icon", "traits", "role", "regular_shop_unit", "profession_status", "guide_available", "template_only_form"]}
                       | {k: h[k] for k in ["availability", "skill", "form_note"] if k in h} for h in gm["heroes"]],
            "items": [{k: i[k] for k in ["id", "name", "icon", "category", "description", "base_stats", "components"]} for i in gm["items"]],
            "augments": [{"id": str(a["id"]), "name": a["name"]} for a in facts.get("augments", [])],
            "cards": cards, "coverage": {"traits": len(traits), "verified_traits": sum(t["verified"] for t in traits),
            "unresolved_traits": sum(not t["verified"] for t in traits), "compositions": len(comps),
            "published_recipe_count": sum(c.get("source_status") == "published_recipe" for c in comps),
            "provisional_recipe_count": sum(c.get("source_status") == "provisional_recipe" for c in comps),
            "traits_with_linked_comps": sum(bool(t["linked_comp_ids"]) for t in traits),
            "traits_with_only_pools": sum(not t["linked_comp_ids"] for t in traits)}}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "app/static/strategy-data.json")
    args = parser.parse_args()
    data = build_strategy()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({m: r["coverage"] for m, r in data["modes"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
