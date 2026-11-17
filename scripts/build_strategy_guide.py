#!/usr/bin/env python3
"""Build the static trait/composition operation guide from attributed records."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
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
    ("nature", "origin:461"): "此羁绊没有直接原生棋子。官方月蚀骑士效果末尾明确：同时登场3日蚀骑士与3月蚀骑士，激活日月双蚀。",
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
        trait_keys = {t["key"] for t in heroes.get(hero_id, {}).get("traits", [])}
        row["population_cost"] = (0 if pet or "origin:367" in trait_keys else
                                  2 if trait_keys.intersection({"origin:471", "origin:369", "origin:475", "origin:476"}) else 1)
        row["slots_consumed"] = row["population_cost"]
        if "origin:367" in trait_keys:
            row["deployment_note"] = "正义巨像在备战区提供羁绊计数，由德玛西亚触发参战；不占普通战场人口。"
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
    slots = sum(u.get("population_cost", 0 if u["is_pet"] else 1) for u in board)
    notes = []
    status = "source" if board else "not_provided"
    if population is not None and slots > population:
        status = "source_invalid_population"
        notes.append(f"源图标称{population}人口，{count}个非pet单位实际消耗{slots}人口；需核对额外人口来源，不能按标准人口照抄。原图单位全部保留。")
    elif population is not None and slots < population:
        status = "source_partial_population"
        notes.append(f"源图列{count}个非pet单位，消耗{slots}/{population}人口；未指定的空位不自行补猜。")
    if any(u["is_pet"] for u in board):
        notes.append("pet/植物/召唤物单独显示，不计普通人口。")
    if any(not u.get("identity_mapped") and not u["is_pet"] for u in board):
        notes.append("有普通单位形态ID未能唯一规范化，不按同名合并。")
    if any(u.get("population_cost", 1) == 2 for u in board):
        notes.append("远古巨龙、纳什男爵、铁铠冥魂等明确占2栏位的单位按2人口计算；羁绊贡献另算。")
    return {"board_status": status, "actual_unit_count": count, "actual_population_cost": slots,
            "slots_consumed": slots, "pet_count": sum(u["is_pet"] for u in board), "validation_notes": notes}


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


def attach_unlock_requirements(mode, heroes, items, traits, reference):
    if mode != "orange":
        return
    archive = reference.get("orange_unlock_reference", {})
    source = {"title": "官方英雄解锁任务配置", "url": archive.get("source_url"),
              "version": archive.get("version"), "generated_at": archive.get("generated_at"),
              "sha256": archive.get("source_sha256"), "checked_at": archive.get("checked_at")}
    hero_names, item_names, trait_names = {}, {}, {}
    for h in heroes:
        hero_names.setdefault(h["name"], []).append(h["id"])
    for item in items:
        item_names.setdefault(item["name"], []).append(item["id"])
    for trait in traits:
        if trait.get("verified", True):
            trait_names.setdefault(trait["name"], []).append(trait["key"])
    for hero in heroes:
        entry = archive.get("tasks_by_hero", {}).get(hero["id"])
        tasks = []
        for task in (entry or {}).get("mission", []):
            desc = clean(task.get("desc"))
            clauses = unique(c.strip() for c in desc.split(";") if c.strip())
            entity_names = unique(re.findall(r"【([^】]+)】", desc))
            levels = unique(int(a or b or c) for a, b, c in re.findall(r"(?:(?:至少|达到)(\d+)级|(\d+)级起|(\d+)级或以上)", desc))
            tasks.append({"task_id": str(task.get("id")), "task_type": clean(task.get("tasktips")),
                          "description_source": desc, "clauses_source": clauses,
                          "minimum_level": levels[0] if len(levels) == 1 else None,
                          "conditions_ambiguous": len(clauses) > 1,
                          "mentioned_hero_ids": unique(hero_names[n][0] for n in entity_names if len(hero_names.get(n, [])) == 1),
                          "mentioned_item_ids": unique(item_names[n][0] for n in entity_names if len(item_names.get(n, [])) == 1),
                          "mentioned_trait_keys": unique(trait_names[n][0] for n in entity_names if len(trait_names.get(n, [])) == 1),
                          "ambiguous_hero_mentions": [{"name": n, "candidate_ids": hero_names[n]} for n in entity_names if len(hero_names.get(n, [])) > 1],
                          "requires_client_role_verification": bool(re.search(r"非坦克|术师|射手定位|角色定位", desc)),
                          "source_visible": task.get("show") == 1})
        direct_cards = [c for c in archive.get("direct_unlock_cards", {}).values()
                        if re.search(r"解锁(?:【" + re.escape(hero["name"]) + r"】|" +
                                     re.escape(hero["name"]) + r"(?=[。，；;]|$))", c["description_source"])
                        and len(hero_names[hero["name"]]) == 1]
        hero["unlock_requirements"] = {"status": "task_recorded" if tasks else "not_listed", "tasks": tasks,
            "source": source, "direct_unlock_cards": direct_cards,
            "notice": "普通任务与时间卡直接解锁是不同路径；任务未列出不表示任何阶段均可购买。分号有多段时不自动解释为同时或任选。"}


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
        # Some effects contain an internal "|" (team/self mana), so splitting
        # on every pipe silently assigns the wrong effect to later breakpoints.
        effects = re.split(r"\|\s*(?=\(\d+\))", row["tier_effects_source"]) if row["tier_effects_source"] else []
        styles = row.get("tier_styles_source", [])
        tiers = [{"count": n, "effect": clean(effects[i]) if i < len(effects) else "该断点需对照来源。",
                  "style": styles[i] if i < len(styles) else None,
                  "is_prismatic": i < len(styles) and styles[i] == "4"} for i, n in enumerate(bp)]
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
            weight = (2 if mode == "nature" and "origin:469" in native_keys and key != "origin:469"
                      or mode == "nature" and "origin:471" in native_keys and key == "origin:454"
                      or mode == "orange" and "origin:369" in native_keys and key == "origin:350" else 1)
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
                           {"hero_id": id, "contribution": weight, "reason": "大元素使选定羁绊、顶级掠食者峡谷野怪、纳什男爵虚空按官方原文提供2计数；独有羁绊自身仍计1。"}
                           for id, weight in native.get(key, {}).items() if weight != 1],
                       "active_breakpoint": full_breakpoint, "native_breakpoint": native_breakpoint,
                       "full_breakpoint": full_breakpoint, "required_emblems_for_full": max(0, (full_breakpoint or 0) - n), "status": status,
                       "conditional_form_ids": form_ids, "without_conditional_forms_breakpoint": ordinary_breakpoint,
                       "note": "来源模板达到起始档，不代表当前实战已激活。" if status == "activated" else
                               " ".join(condition_notes) if status == "conditional" else
                               "仅有关联原生牌，未达到起始档，不作为该羁绊成套路线。"})
    return result


def population_cost(hero):
    keys = {t["key"] for t in hero.get("traits", [])}
    return 0 if "origin:367" in keys else 2 if keys.intersection({"origin:471", "origin:369", "origin:475", "origin:476"}) else 1


def contribution(mode, hero, key):
    keys = {t["key"] for t in hero.get("traits", [])}
    if key not in keys:
        return 0
    return 2 if (mode == "nature" and "origin:469" in keys and key != "origin:469"
                 or mode == "nature" and "origin:471" in keys and key == "origin:454"
                 or mode == "orange" and "origin:369" in keys and key == "origin:350") else 1


def attach_capstone_routes(mode, traits, heroes, items):
    """Publish auditable arithmetic, not an invented final combat board."""
    for trait in traits:
        trait["capstone_routes"] = []
        if not trait["verified"]:
            continue
        targets = [t for t in trait["tiers"] if t["is_prismatic"] or mode == "nature" and t["count"] >= 9]
        if not targets:
            continue
        native = [heroes[id] for id in trait["native_hero_ids"]]
        forms = [heroes[id] for id in trait.get("conditional_hero_ids", [])
                 if contribution(mode, heroes[id], trait["key"]) == 2]
        for tier in targets:
            for form in [None] + forms:
                candidates = native + ([form] if form else [])
                # Choose actual distinct units with the most native contribution,
                # then avoid unnecessary population/high-cost units.
                candidates.sort(key=lambda h: (-contribution(mode, h, trait["key"]), population_cost(h), h["cost"], h["id"]))
                chosen, count = [], 0
                for h in candidates:
                    if count >= tier["count"]:
                        break
                    chosen.append(h)
                    count += contribution(mode, h, trait["key"])
                emblem_slots = max(0, tier["count"] - count)
                named_population = sum(population_cost(h) for h in chosen)
                pop = named_population + emblem_slots
                conditions = ["这是羁绊计数骨架，未给空缺承载者指定姓名、装备或固定升级回合；必须同时满足任务与持有条件。"]
                if form:
                    conditions.append(f"必须是{trait['name']}形态拉克丝，贡献2个{trait['name']}计数；基础拉克丝或其他形态不能替代。")
                if emblem_slots:
                    conditions.append(f"需{emblem_slots}枚对应纹章，各给1名不同的非原生单位；给已拥有该羁绊者或同名重复单位不增加独特计数。")
                if mode == "orange":
                    conditions.append("费用不表示已经可购：先完成所列原生牌的解锁任务，再按实际上阵/备战区规则计数。")
                if any(h["id"] == "15285" for h in chosen):
                    conditions.append("加里奥留在备战区提供德玛西亚计数，不占普通战场栏位，由德玛西亚重振旗鼓后加入。")
                if mode == "orange" and trait["key"] in ("origin:343", "origin:351") and tier["is_prismatic"]:
                    conditions.append("本配置需行走于棱彩之道在6-1解锁相应棱彩层级；十个计数本身不能替代解锁。")
                if pop > 10:
                    conditions.append(f"此算术方案需要{pop}人口，超出常规10人口；必须另有额外人口来源，否则不可执行。")
                trait["capstone_routes"].append({
                    "id": f"{trait['key']}:{tier['count']}:{form['id'] if form else 'native'}",
                    "label": f"{tier['count']}{trait['name']} · {'指定拉克丝' if form else '原生计数'}",
                    "target_count": tier["count"], "tier_style": tier["style"], "is_prismatic": tier["is_prismatic"],
                    "hero_ids": [h["id"] for h in chosen], "conditional_form_ids": [form["id"]] if form else [],
                    "emblem_count": emblem_slots, "emblem_holder_slots": emblem_slots,
                    "emblem_item_ids": [id for id, item in items.items() if trait["id"] in [str(t) for t in item.get("trait_ids", [])]
                                        and len([t for t in traits if t["id"] == trait["id"]]) == 1],
                    "emblem_holder_requirement": "每枚给不同的非原生可装备单位；不指定未经验证的承载者。",
                    "named_units_population": named_population, "population_required": pop, "spare_slots": 0,
                    "native_count": count, "total_count": count + emblem_slots,
                    "counting_evidence": [{"hero_id": h["id"], "contribution": contribution(mode, h, trait["key"]),
                        "population_cost": population_cost(h),
                        "reason": "大元素使选定羁绊双计数" if h.get("template_only_form") else
                                  "备战区提供计数，不占普通人口" if population_cost(h) == 0 else
                                  "官方占2栏位；原生羁绊贡献独立计算" if population_cost(h) == 2 else "独特原生单位计1"}
                        for h in chosen],
                    "requires_card_ids": ["7250029"] if mode == "orange" and trait["key"] in ("origin:343", "origin:351") and tier["is_prismatic"] else [],
                    "conditions": conditions, "provenance": "editorial_arithmetic_from_official_rules",
                    "source": trait["source"], "not_a_complete_board": True})
        trait["capstone_routes"].sort(key=lambda r: (r["target_count"], r["population_required"], r["emblem_count"]))


def attach_mechanism_plans(mode, traits, heroes):
    class_actions = {
        "斗士": ("以额外生命承接伤害，补第二名斗士时保留现有主C，不把整队都换成斗士。", "比较主坦星级、生命装与敌方百分比伤害；升高档不应让输出缺位。"),
        "护卫": ("用双抗保护前排；优先选能同时接现有特质的护卫，而非无装备硬上更多一星前排。", "观察敌方减抗与主坦存活；高档双抗不能替代血量和治疗。"),
        "主宰": ("围绕减伤与持续作战接入；先让主坦有质量，后排继续沿实际伤害类型出装。", "比较补第二承伤与提高主C输出，不为高档减伤放弃已有关键功能。"),
        "重装战士": ("围绕开战及半血护盾承伤，前排分担火力，给关键输出创造第二次施法时间。", "观察护盾能否撑过敌方爆发；高档升阶前检查输出是否够。"),
        "枪手": ("用有物理加成或普攻物伤收益的原生枪手承接输出装，前排另行补齐。", "每第4击收益依赖存活与攻速；不要把枪手物伤机制套给法伤棋子的全部技能。"),
        "狙神": ("优先给后排保留攻击距离并配承伤；提莫、克格莫、吉格斯等仍按自身技能分物法装备。", "换边避开突进与范围控制；距离增伤不等于必须角落挤在一起。"),
        "迅捷射手": ("围绕持续普攻叠攻速，保住输出不被开局集火；补射手时同时检查前排时长。", "比较多一名射手档位与更强承伤/控制，不用更多一星射手替掉成装主坦。"),
        "迅击战士": ("利用已损失生命目标获得攻速，持续集火；无蓝条凯尔/崔斯特不机械拿施法回蓝装备。", "按实际伤害分支分装，低血目标攻速机制不是所有单位都适合物理三件套。"),
        "法师": ("先找有法术加成收益且能稳定出手的核心，配前排承伤；原生池只表示可选。", "比较施法次数与存活；补高档时别把回蓝装转给无主动施法收益单位。"),
        "神谕者": ("围绕有蓝条、需要施法的主C或保护单位接入，保留额外法力的实际受益者。", "已经不缺法力时比较输出或承伤收益；不能按AP标签推断需要神谕。"),
        "神谕": ("让有蓝条核心获得持续法力回复，同时维持前排为第二轮技能争取时间。", "主C没有蓝条或不靠施法时先比较其他功能，不能按法伤直接推荐神谕。"),
        "裁决战士": ("用全能汲取支持近战持续作战，先确认核心的攻击/法术加成，易不套同一物理装备。", "低血收益需要存活兑现；不能为叠档让主C独自承受全部火力。"),
        "魔战士": ("装备会决定物理/法术加成更高的一侧，先确认目标形态，再选承接者。", "换装备后重新核对形态与技能效果，不以职业名字判定物理输出。"),
        "裁决使": ("技能暴击及额外伤害围绕原生核心兑现，先稳定出手与前排，再决定加深档位。", "检查技能已有暴击和装备覆盖，重复效果不能直接当额外收益相加。"),
        "征服者": ("以技能暴击和暴击伤害放大实际主C，物理或法术输出仍由技能决定。", "补暴击档位前比较现有装备是否已有暴击与前排是否能撑到技能。"),
        "猎人": ("围绕物理加成与连续锁定目标分装，避免输出频繁换目标丢失额外收益。", "观察主C目标与走位，不能只凭猎人数量推断已兑现伤害增幅。"),
        "狂战士": ("用吸血与对低生命目标的伤害支持近战收割，让有质量的前排分担第一轮。", "核心被控制或秒杀时先补生存，不能把吸血数值当必然能回满。"),
        "神盾使": ("利用首次75%和25%生命阈值的护盾持续作战，优先提高关键持盾单位质量。", "观察阈值能否实际触发两轮；不要把高档护盾等同即时治疗。"),
        "耀光使": ("让技能覆盖敌方关键输出以施加目眩；不是只凑数量，实际命中对象会影响减伤。", "对位时比较范围覆盖和保命，目眩并非所有敌人开局自动获得。"),
        "换形师": ("先决定前后排位置对应的技能和定位，再放装备；同一单位换排后重新检查角色。", "换位置前核对形态收益，别把前排承伤装与后排输出分支混用。"),
        "发明家": ("装备分享给距离最近的2名友军，优先把真正能用装备的单位放近。", "第二名发明家还要等3场战斗造锻造器；不能把入场视为立刻获得。"),
        "召唤师": ("先确认约里克、阿兹尔、锋喙鸟或婕拉的召唤物强化对象，再选择需要的两种效果。", "召唤物不算普通人口；升3档增强效果之前先核对主召唤者质量。"),
    }
    orange_origins = {
        "340": ("用低费比港尽早参与击败赚银蛇币；黑市升级前比较币量和当前战力。", "升5/7档是提高收入与商品层级，消费时按实际输出或承伤需求选属性。", "没有可用解锁牌就维持可达档，不为黑市高档空转搜牌。"),
        "341": ("娑娜、嘉文与赵信/已解锁波比可建立3德玛；带装备触发任务后再考虑高费承接。", "薇恩/拉克丝输出与盖伦承伤分工；队伍损失生命触发重振，不是开战即得到所有后续效果。", "加里奥只能备战区提供计数；冲11德玛前按人口与非原生纹章承载槽核算。"),
        "342": ("用艾希与瑟庄妮等原生牌接入，第三张实际到位才开冰塔；塔前承伤、塔后输出。", "5档增加第二座塔，先摆塔和核心再补人口，奥恩需任务或卡片解锁。", "不要把一张奥恩当整套弗雷尔卓德；高档冰塔被摧毁的控制须实际触发。"),
        "343": ("先用慎、烬、亚索/赵信等两星承接，3档即可检查超凡之路收益。", "凯南、阿狸与后续永恩/孙悟空等按实际解锁补入，不把所有原生牌都追三。", "10档棱彩需卡片6-1解锁与足够独特计数；高费路线依任务、经济和当前质量。"),
        "344": ("先把探险目标与已有奇亚娜、米利欧、妮蔻等可用牌对应，不因费用池就认为斯卡纳/奈德丽已可购买。", "完成探险后的下回合才给新目标；花太阳碎片前比较战利品能否稳住当前战力。", "5档回血与7档胜利碎片需达到对应档并实际参战/取胜；不能预支奖励。"),
        "345": ("用贝蕾亚、赛恩等过渡，满足任务再接德莱厄斯/乐芙兰；3档召唤依敌队先损失15%生命。", "厄塔汗强度随诺克单位星级，比较关键牌升星和多塞一名一星诺克的收益。", "莫德凯撒占2栏位；冲10档前把单位数、人口、纹章槽分开计算。"),
        "346": ("先用2皮城选模块；奥莉安娜须装备皮城单位完成任务，不按2费直接视为已有。", "4/6档增加模块选择；战斗8秒后启动，前排必须撑过启动窗口。", "升级模块前比较实际模块功能，不把科技名词当固定装备或终局。"),
        "347": ("先用佛耶戈接装备完成约里克任务，再看2暗影岛及战斗灵魂累计。", "灵魂会独特强化各自技能，格温任务还要求约里克配装与等级条件。", "卡莉丝塔、锤石等高费到位前保留能承接装备的两星，面板数量不代替灵魂进度。"),
        "348": ("恕瑞玛没有低费开局池，以其他可用两星过渡，先完成阿兹尔等任务。", "雷克顿/内瑟斯分别涉及带阿兹尔连续胜/负条件，不能把同一段任务当两者共用。", "4恕瑞玛棱彩按实际四名原生或替代纹章核数；每秒成长需要前排和存活兑现。"),
        "349": ("巨神峰不是普通的凑人数加属性羁绊；按厄斐琉斯、佐伊等单卡技能承接，不为显示人数档全上。", "先比较蕾欧娜等承伤与其他单卡的质量；配置明确说明这些单位没有常规职业，不能按名字补职业。", "只有龙王已解锁并登场时，才另外核对其独有铸星龙王与其他独特巨神峰的星尘联动；不预支星尘。"),
        "350": ("由已可用虚空单位开局，先看两场玩家对战激活条件再解锁峡谷先锋。", "选择突变要对应主C的技能与装备，前排、普攻法伤与后排不共用同一分支。", "男爵占2栏位且提供2虚空；升级前按消耗人口而非棋盘模型个数判断。"),
        "351": ("兰博、璐璐、崔丝塔娜、提莫等按来牌追关键质量；波比与可酷伯等要先满足任务。", "复制资源优先给选定核心；维迦任务需要约德尔带帽子，不能只凭4费池预设可购。", "10约德尔棱彩需行走于棱彩之道6-1解锁，再满足独特计数，不把解锁层级当直接凑满。"),
        "352": ("先用布里茨、蔚、艾克等实际可用牌过渡，蒙多承伤、金克丝与吉格斯伤害类型分开。", "带装备金克丝可推进沃里克解锁；高费吉格斯仍以其魔法技能配装，辛吉德任务另核对。", "升高档前比较实际单卡技能与钥匙是否已经取得，不统一分物理装备。"),
        "382": ("先核对实际暗裔棋子/暗裔装备持有者；一名原生暗裔已经有吸血起档。", "2档溢出治疗转盾，后续档位按实际受伤、治疗和对玩家伤害触发，不提前兑现。", "恶魔降世只使亚托克斯总计2裁决战士，不会额外给暗裔计数。"),
    }
    for trait in traits:
        pool = trait["stage_pools"]
        plan = {"status": "mechanic_reference", "summary": trait["description"], "not_a_complete_board": True,
                "provenance": "editorial_from_official_rules", "sources": [trait["source"]],
                "early": {"candidate_ids": pool["early"], "actions": [], "conditions": []},
                "mid": {"candidate_ids": pool["mid"], "actions": [], "conditions": []},
                "late": {"candidate_ids": pool["late"], "actions": [], "conditions": []},
                "partial_combinations": [], "stop_conditions": [], "position_notes": [],
                "unlock_hero_ids": [id for id in trait["native_hero_ids"] if heroes[id].get("unlock_requirements", {}).get("tasks")]}
        if not trait["verified"]:
            plan.update(status="unresolved", summary="缺少官方定义；只保留原始特质ID和引用单位，不据此生成运营。")
            trait["mechanism_plan"] = plan
            continue
        if trait["key"] == "origin:461" and mode == "nature":
            required = {"origin:459": 3, "origin:460": 3}
            ids_ = [h["id"] for h in heroes.values() if any(t["key"] in required for t in h["traits"]) and h.get("native_pool_eligible", True)]
            plan.update(status="cross_trait_activation", summary="同时登场3日蚀骑士与3月蚀骑士激活日月双蚀。",
                        activation_requirements=required, activation_hero_ids=ids_)
            plan["early"]["candidate_ids"] = [id for id in ids_ if heroes[id]["cost"] <= 2]
            plan["early"]["actions"] = ["低费3日蚀骑士可先成基础；日月双蚀仍未激活，保留两星质量过渡。"]
            plan["mid"]["actions"] = ["黛安娜到位后开始拼月蚀，注意月蚀与邻格友军的加成位置。"]
            plan["late"]["candidate_ids"] = [id for id in ids_ if heroes[id]["cost"] >= 4]
            plan["late"]["actions"] = ["厄斐琉斯与拉露恩补齐3月蚀，再同时检查3日蚀仍在场；不是购买6张任意骑士。"]
            plan["sources"].append({"title": "官方月蚀骑士跨羁绊激活原文", **next(t["source"] for t in traits if t["key"] == "origin:460")})
        elif mode == "orange" and trait["kind"] == "origin" and trait["id"] in orange_origins:
            actions = orange_origins[trait["id"]]
            for stage, action in zip(("early", "mid", "late"), actions):
                plan[stage]["actions"] = [action]
            plan["stop_conditions"] = [actions[-1]]
        elif trait["kind"] == "class" and trait["name"] in class_actions:
            action, check = class_actions[trait["name"]]
            plan["early"]["actions"] = [action]
            plan["mid"]["actions"] = [check]
            plan["late"]["actions"] = ["按上方真实断点与已成型路线比较补档收益；职业只描述机制，装备仍逐棋子核对。"]
            plan["stop_conditions"] = [check]
        else:
            plan["status"] = "unique_unit_integration" if trait["strategy_type"] == "unique" else "source_mechanism_reference"
            plan["early"]["actions"] = ([f"现有低费原生候选：{names(pool['early'], heroes)}；先以实际两星承接，下面效果只有条件达成才触发。"]
                                        if pool["early"] else ["本羁绊没有低费普通原生池；先用其他已成型两星过渡，不为等其独有牌提前消耗经济。"])
            plan["mid"]["actions"] = ["机制核对：" + trait["description"]]
            plan["late"]["actions"] = ["接入时核对：" + (trait["tiers"][-1]["effect"] if trait["tiers"] else trait["description"])]
        # Concrete small combinations show exact shared hooks. They are optional
        # native subsets, never advertised as a complete stage board.
        native = [heroes[id] for id in trait["native_hero_ids"]]
        scored = []
        for pair in combinations(native, 2):
            shared = {t["key"] for t in pair[0]["traits"] if t.get("verified")} & {t["key"] for t in pair[1]["traits"] if t.get("verified")}
            shared.discard(trait["key"])
            score = (sum(h["cost"] for h in pair), -len(shared), [h["id"] for h in pair])
            scored.append((score, pair, shared))
        for _, pair, shared in sorted(scored, key=lambda x: x[0])[:2]:
            n = sum(contribution(mode, h, trait["key"]) for h in pair)
            bp = max((b for b in trait["breakpoints"] if 0 < b <= n), default=None)
            conditions = []
            for h in pair:
                if h.get("unlock_requirements", {}).get("tasks"):
                    conditions.append(h["name"] + "需先核对并完成其解锁任务。")
            plan["partial_combinations"].append({"hero_ids": [h["id"] for h in pair],
                "label": names([h["id"] for h in pair], heroes), "native_count": n, "active_breakpoint": bp,
                "reason": (f"提供{n}个独特原生计数，" + (f"达到{bp}档。" if bp else "尚未达到起档，仍需其他原生或有效计数。")) +
                          ("同时共享：" + "、".join(next(t["name"] for t in traits if t["key"] == k) for k in sorted(shared)) + "；这些额外羁绊也须单独核对断点。" if shared else ""),
                "conditions": conditions, "not_a_complete_board": True})
        for stage in ("early", "mid", "late"):
            if mode == "orange":
                plan[stage]["conditions"].append("费用阶段只是可选池；任务未完成、特殊单位或条件形态不可视为已经可买。")
        trait["mechanism_plan"] = plan


def nature_comp(lineup, facts, reference, heroes, items, traits):
    records = {str(r["official_id"]): r for r in facts["champion_star_form_records"]}
    board = normalize_board(lineup["main_board"], records, heroes)
    regular = [u for u in board if not u["is_pet"]]
    target_ids = unique(canonical_id(t, records, heroes)[0] for t in ids(lineup.get("three_star_targets")))
    practical_target_ids = [id for id in target_ids if heroes.get(id, {}).get("cost", 99) <= 3]
    aspirational_target_ids = [id for id in target_ids if id not in practical_target_ids]
    carry_ids = unique(u["hero_id"] for u in regular if u["is_carry"])
    # A frontline row contains melee carries as well as tanks. Do not turn the
    # whole row into required two-star "tanks" or an automatic stop condition.
    tank_items = {"2028", "2034", "2031", "2027", "2025", "2040", "2023", "2018"}
    front_ids = unique(u["hero_id"] for u in regular if u.get("row", 4) <= 2 and (
        (heroes.get(u["hero_id"], {}).get("role", {}).get("id") == "tank"
         and not heroes.get(u["hero_id"], {}).get("role", {}).get("ambiguous"))
        or (not u["is_carry"] and len(tank_items.intersection(u["item_ids"])) >= 2)))
    core_ids = unique(carry_ids + practical_target_ids + [u["hero_id"] for u in regular if u["hero_id"] in front_ids and len(u["item_ids"]) >= 2])
    utility_ids = unique(u["hero_id"] for u in regular if u["hero_id"] not in core_ids and len(u["item_ids"]) <= 1
                         and (heroes.get(u["hero_id"], {}).get("cost", 9) <= 3 or u["hero_id"] not in front_ids))
    flex_ids = unique(u["hero_id"] for u in regular if u["hero_id"] not in core_ids and u["hero_id"] not in utility_ids)
    operation = reference["nature_operations"].get(str(lineup["id"]), {})
    reviewed = next((r for r in reference.get("nature_action_summaries", [])
                     if str(r.get("lineup_id", r.get("id"))) == str(lineup["id"])), None)
    reviewed = reviewed or next((r for r in reference["reviewed_nature_summaries"] if r["lineup_id"] == str(lineup["id"])), {})
    overrides = reviewed.get("role_overrides", {})
    if overrides:
        for field, current in [("carry_ids", carry_ids), ("frontline_ids", front_ids),
                               ("core_ids", core_ids), ("utility_ids", utility_ids), ("flex_ids", flex_ids)]:
            if field in overrides:
                values = unique(canonical_id(v, records, heroes)[0] for v in overrides[field])
                if field == "carry_ids":
                    carry_ids = values
                elif field == "frontline_ids":
                    front_ids = values
                elif field == "core_ids":
                    core_ids = values
                elif field == "utility_ids":
                    utility_ids = values
                else:
                    flex_ids = values
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
    matched_levels = [int(k) for k, v in lineup.get("boards_by_level", {}).items()
                      if str(k).isdigit() and v == lineup.get("early_board")]
    phase2.update(board_status="source_subset" if opening_pool else "not_provided",
                  source_population=min(matched_levels) if matched_levels else None,
                  source_unit_count=len(early_regular),
                  source_population_cost=sum(u["population_cost"] for u in early))
    phase_summary = reviewed.get("phases", {}).get("stage2")
    if phase_summary:
        phase2["focus"] = phase_summary if isinstance(phase_summary, str) else phase_summary.get("focus", phase_summary.get("summary", phase2["focus"]))
        if isinstance(phase_summary, dict) and phase_summary.get("actions"):
            phase2["actions"] = phase_summary["actions"]
    stages = [phase2]
    for pid, label, level, summary_key in [("stage3", "3阶段 · 建立中期质量", "6", "midgame"),
                                            ("stage4", "4阶段 · 核心成型", "8", "endgame"),
                                            ("late", "后期 · 补强与对位", "9", "endgame")]:
        units = normalize_board(lineup.get("boards_by_level", {}).get(level, []), records, heroes)
        midgame = reviewed.get("midgame", "")
        mid_is_late = bool(re.search(r"(?:4|5|6)-[1-7]|升[至到]?9|9级|九人口", midgame)) and not re.search(r"3-[1-7].*(?:搜|升)", midgame)
        focus = (("继续用开局两星与体系牌存钱过渡；下列高人口图是作者后续参考，不要求3阶段提前执行4阶段搜牌。" if mid_is_late else midgame)
                 if pid == "stage3" and midgame else
                 (midgame if pid == "stage4" and mid_is_late else reviewed.get(summary_key))) or \
                f"检查{carry_names}输出和{front_names}承伤；这里是作者{level}人口图，不代表该阶段必须升到此人口。"
        actions = [f"作者{level}人口示例只作阶段参考；实际是否升级要比较血量、金币与棋盘质量。"]
        if pid == "stage3" and practical_target_ids:
            actions.append(f"来源低费/三费追三星候选：{names(practical_target_ids, heroes)}；先区分主要目标和顺带追的牌。")
        if pid == "stage4":
            actions.append(f"优先核对{carry_names}和{front_names}的关键质量，再分配追星或升级预算。")
        if pid == "late":
            actions.append("换高费之前重新数关键羁绊与功能；未两星的高费不自动优于已有成型单位。")
            if aspirational_target_ids:
                actions.append(f"作者另列高费三星上限：{names(aspirational_target_ids, heroes)}；这是后期资源充裕的梦想，不是常规成型或早中期必须追的任务。")
        phase_summary = reviewed.get("phases", {}).get(pid)
        if phase_summary:
            focus = phase_summary if isinstance(phase_summary, str) else phase_summary.get("focus", phase_summary.get("summary", focus))
            if isinstance(phase_summary, dict) and phase_summary.get("actions"):
                actions = phase_summary["actions"]
        phase = make_phase(pid, label, units, int(level), focus, actions)
        phase["summary_provenance"] = "human_paraphrase_of_author_operation" if reviewed else "editorial_from_source_board"
        phase["source_fields"] = ["early_info", "d_time", "location_info"]
        stages.append(phase)
    style = "slow_roll" if operation.get("slow_roll") else "upgrade_and_stabilize" if not practical_target_ids else "quality_reroll"
    actions = []
    if operation.get("avoid_early_roll"):
        actions.append("作者倾向前期少搜/不搜；如果血量已难以承受，要先处理即时战力。")
    if operation.get("stage_mentions"):
        actions.append("作者参考时点：" + "、".join(operation["stage_mentions"]) + "；不保证准时成型。")
    if operation.get("level_mentions"):
        actions.append("作者运营文字涉及人口：" + " / ".join(map(str, operation["level_mentions"])) + "；不是必须逐项执行的升级表。")
    if operation.get("economy_mentions"):
        actions.append("作者提及保留经济：" + " / ".join(map(str, operation["economy_mentions"])) + "；血量和同行变化时重新评估。")
    if practical_target_ids:
        actions.append(f"以{names(practical_target_ids, heroes)}为追星候选；不要为所有候选同时锁死经济。")
    stops = [f"{carry_names}和{front_names}达到支撑后续战斗的质量后暂停消耗，重新比较升级收益。"]
    if operation.get("two_star_stop"):
        stops.insert(0, "作者给出体系二星后的停搜/升级节点，先核对实际关键牌是否到齐。")
    if practical_target_ids:
        stops.append("同行占牌、追星张数不足或预算用完时停止无预算追三；来源不保证未来抽牌。")
    if reviewed.get("roll_actions"):
        actions = reviewed["roll_actions"]
    if reviewed.get("stop_conditions"):
        stops = reviewed["stop_conditions"]
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
    if reviewed.get("position_notes"):
        position_notes = reviewed["position_notes"]
    return {"id": str(lineup["id"]), "name": lineup["name"], "kind": "official_lineup",
            "summary": reviewed.get("opening") or f"围绕{carry_names}输出，配合{front_names}承伤，分别查看追星、人口和装备。",
            "core_ids": core_ids, "carry_ids": carry_ids, "frontline_ids": front_ids, "utility_ids": utility_ids, "flex_ids": flex_ids,
            "trait_keys": [r["key"] for r in links if r["status"] != "incidental"], "trait_links": links,
            "phases": stages, "source_early_board": early,
            "roll_plan": {"style": style, "actions": actions, "stop_conditions": stops,
                          "pivot_conditions": reviewed.get("pivot_conditions") or ([reviewed["risk"]] if reviewed.get("risk") else []) +
                          ["核心被同行占用或缺关键装备时，保留能转型的两星与装备，不按标题硬玩。"],
                          "provenance": "human_reviewed_author_summary_and_editorial_guardrails",
                          "source_fields": {"actions": "author_summary", "stop_conditions": "author_summary_and_editorial_guardrails",
                                            "pivot_conditions": "editorial_guardrails"}},
            "equipment": [{"hero_id": u["hero_id"], "hero_name": u["hero_name"], "item_ids": u["item_ids"],
                          "role": "主C" if u["is_carry"] else "来源分装", "reason": "作者指定装备，不是组合胜率。", "provenance": "source"}
                         for u in regular if u["item_ids"]],
            "positioning": {"summary": "作者主棋盘示例；植物与普通人口分别计算", "board": board, "notes": position_notes},
            "three_star_ids": practical_target_ids, "source_three_star_ids": target_ids,
            "aspirational_three_star_ids": aspirational_target_ids,
            "replacements": replacements, "augment_ids": ids((lineup.get("augment_recommendations") or {}).get("recomm")),
            "card_ids": [], "source": source,
            "notes": ["分工由作者主C标记、追星目标、分装及站位整理，不等于原生牌全部必拿。", "没有使用收录S/A标签作为当前强度或胜率排序。"]}


def orange_comps(research, facts, reference, heroes, items, traits):
    results = []
    reviewed = {r["name"]: r for r in reference["orange_recipe_notes"]}
    recipes = list(research["recipes"])
    source_map = dict(research["sources"])
    for extra in reference.get("orange_supplemental_recipes", []):
        source_map[extra["id"]] = {"url": extra["url"], "published": extra["published_at"], "type": "official_account_mirror"}
        recipes.append({"name": extra["name"], "validation_status": "recipe_source_verified_official_mirror",
                        "source_id": extra["id"], "card_ids_exact_match": extra["card_ids"],
                        "card_names_as_published": extra["card_names"], "alias_resolution_required": extra["unresolved_card_names"],
                        "logic_summary_ours": extra["summary_ours"], "id": extra["id"],
                        "mechanism_trait_keys": extra.get("mechanism_trait_keys", [])})
        reviewed[extra["name"]] = extra
    for index, recipe in enumerate(recipes):
        if not recipe["validation_status"].startswith("recipe_source_verified"):
            continue
        note = reviewed.get(recipe["name"], {})
        core = note.get("core_hero_ids", [])
        if recipe["name"] == "月神厄斐琉斯流":
            core = ["12417"]
        sr = source_map[recipe["source_id"]]
        source = {"title": recipe["name"], "url": sr["url"], "published_at": sr.get("published"),
                  "author": "金铲铲之战（官方内容镜像）", "version": "18.6参考", "kind": sr["type"]}
        source_status = "published_recipe"
        if recipe["name"] == "连胜杰作流":
            source_status = "provisional_recipe"
            source = {"title": "官方账号搜索摘要支持；单帖全文未核验", "url": "https://www.sina.cn/media/7504806444",
                      "published_at": "2026-11-04", "author": "金铲铲之战官方账号（搜索摘要）",
                      "version": "18.6参考", "kind": "official_search_snippet_not_full_post"}
        board = [{"hero_id": id, "source_hero_id": id, "hero_name": heroes.get(id, {}).get("name", id),
                  "type": "hero", "is_pet": False, "is_carry": False, "item_ids": [], "identity_mapped": id in heroes,
                  "population_cost": population_cost(heroes[id]) if id in heroes else 1} for id in core]
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
        results.append({"id": recipe.get("id") or f"orange-{index+1}", "name": recipe["name"], "kind": "orange_recipe", "source_status": source_status, "summary": summary,
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
                        "mechanism_trait_keys": recipe.get("mechanism_trait_keys", []),
                        "notes": [caveat, "卡片启用回合不自动等于条件奖励到账回合；没有条件胜率或完整逐回合棋盘样本。"]})
    return results


def orange_author_comps(reference, heroes, items, traits):
    results = []
    for recipe in reference.get("orange_author_lineups", []):
        source = {"title": recipe["name"] + " · 作者投稿示例", "url": recipe["source"]["article_url"],
                  "author": recipe["source"]["publisher"], "published_at": recipe["source"]["published_at"],
                  "kind": "official_published_author_image_template", "version": "文章未注明强度补丁",
                  "image_urls": recipe["source"]["image_urls"], "attribution": recipe["source"]["content_attribution"],
                  "patch_status": recipe["source"]["patch_status"]}
        equipment = []
        for entry in recipe["equipment"]:
            slot_note = ("作者图示需把主角选择器给该核心后采用纹章+三成装实例；四格条件来自同一作者图，"
                         "官方时间卡配置只确认提供选择器，当前未取得20032道具完整规则，不能推广为普通单位通用四格。") if entry["emblem_item_ids"] else None
            equipment.append({"hero_id": entry["hero_id"], "hero_name": entry["hero_name"],
                "item_ids": entry["emblem_item_ids"] + entry["preferred_item_ids"],
                "alternative_item_ids": entry["alternative_item_ids"], "emblem_item_ids": entry["emblem_item_ids"],
                "role": "作者来源分装", "reason": "作者推荐图标逐项对照官方装备缓存；不是样本胜率或最优组合统计。",
                "provenance": "human_reviewed_source_image", "slot_note": slot_note,
                "requires_card_ids": ["7250056"] if entry["emblem_item_ids"] else [],
                "conditions": [slot_note] if slot_note else []})
        item_lookup = {e["hero_id"]: e["item_ids"] for e in equipment}

        def board(source_board, final=False):
            rows = []
            for unit in source_board:
                id = unit["hero_id"]
                cost = population_cost(heroes[id])
                rows.append({**unit, "source_hero_id": id, "hero_name": heroes[id]["name"], "type": "hero",
                    "is_carry": id in recipe["carry_ids"],
                    "item_ids": item_lookup.get(id, []) if final else list(unit.get("item_ids", [])),
                    "identity_mapped": True, "population_cost": cost, "slots_consumed": cost})
            return rows

        main_board = board(recipe["final_board"], final=True)
        reviewed = recipe["actions_reviewed"]
        phases = []
        group_map = {"stage2": ("opening", "level5_unlock", "card_2-7"),
                     "stage3": ("3-2_author_reference", "3-5_author_reference"),
                     "stage4": ("after_core_three_star",), "late": ("after_core_three_star",)}
        boards = {"stage2": board(recipe["early_board"]), "stage3": board(recipe["mid_board"]),
                  "stage4": main_board, "late": main_board}
        for stage, label in [("stage2", "2阶段 · 解锁与前期来源图"), ("stage3", "3阶段 · 追星准备"),
                             ("stage4", "4阶段 · 依追星进度成型"), ("late", "后期 · 作者终局与对位")]:
            actions = [r["condition"] + "：" + r["action"] for r in reviewed if r["stage"] in group_map[stage]]
            phase = make_phase(stage, label, boards[stage], None,
                               "作者按解锁、两星和三星进度推进；图中没有明确人口标签，不把图片阶段强制换成固定回合完整棋盘。",
                               actions, "human_reviewed_author_image")
            phase["source_entity_count"] = len(boards[stage])
            phase["conditions"] = ["来源图未标人口；已知英雄与位置完整保留，但不保证当前阶段每张都已解锁/搜到。"]
            if recipe.get("unidentified_schematic_markers"):
                phase["validation_notes"].append("来源还有未命名蓝色示意标记，身份不明；不映射假人ID，也不当成普通英雄。")
            phases.append(phase)
        links = trait_links(main_board, heroes, items, traits, mode="orange")
        conflict_notes = [r["image_summary"] + "；官方任务归档：" + r["official_mission_archive"] + "。两者冲突，需客户端确认。"
                          for r in recipe["unlock_evidence"] if r.get("conflict")]
        for evidence in recipe["unlock_evidence"]:
            if evidence.get("conflict") and evidence["hero_id"] in heroes:
                heroes[evidence["hero_id"]]["unlock_requirements"].setdefault("source_conflicts", []).append({
                    "description": evidence["image_summary"], "archive_description": evidence["official_mission_archive"],
                    "source": source, "handling": evidence["handling"]})
        results.append({"id": recipe["key"], "name": recipe["name"], "kind": "official_published_author_lineup",
            "source_status": "published_author_example", "summary": reviewed[0]["action"],
            "core_ids": recipe["core_ids"], "carry_ids": recipe["carry_ids"], "frontline_ids": recipe["frontline_ids"],
            "utility_ids": [], "flex_ids": [u["hero_id"] for u in main_board if u["hero_id"] not in recipe["core_ids"]],
            "trait_keys": [r["key"] for r in links if r["status"] != "incidental"], "trait_links": links,
            "phases": phases, "equipment": equipment, "equipment_slot_note": "主角选择器条件下的作者四装备实例；不当作通用普通三格规则。",
            "positioning": {"summary": "作者终局9个已命名英雄的精确位置；未命名示意标记另存。",
                            "board": main_board, "notes": recipe.get("identity_notes", []) + conflict_notes +
                            ["作者站位示例仍需按敌方控制/切入换边；未提供逐对手胜率。"],
                            "unidentified_schematic_markers": recipe.get("unidentified_schematic_markers", [])},
            "roll_plan": {"style": "source_author_reroll", "actions": [r["condition"] + "：" + r["action"] for r in reviewed],
                          "stop_conditions": ["按所选作者链先补关键两星，再追指定主力三星；达成后才将预算转为升级，不要求所有挂件同时三星。"],
                          "pivot_conditions": ["所需卡片、纹章、解锁或主力数量不成立时，停止按图硬追，用已有两星稳住战力。"] + conflict_notes,
                          "provenance": "human_reviewed_author_image_and_editorial_guardrails"},
            "three_star_ids": recipe["core_ids"] if recipe["key"] == "orange-author-river-tryndamere" else recipe["carry_ids"],
            "replacements": [], "augment_ids": [], "card_ids": recipe["card_ids"],
            "published_card_names": recipe["published_card_names"], "unresolved_card_names": [],
            "portal_claim": recipe["portal_claim"], "source": source,
            "notes": recipe["claims_not_supported"] + conflict_notes,
            "unlock_evidence": recipe["unlock_evidence"]})
    return results


def build_strategy(base=BASE):
    reference = json.loads((base / "app/data/strategy_reference.json").read_text())
    guide = json.loads((base / "app/static/guide-data.json").read_text())
    research = json.loads((base / "app/data/orange_research.json").read_text())
    manifest = json.loads((base / "app/assets/manifest.json").read_text())
    assets = {(r["mode"], r["kind"], str(r["entity_id"])): "assets/" + r["path"]
              for r in manifest["assets"] if (base / "app/assets" / r["path"]).is_file()}
    out = {"schema_version": "strategy-guide-v1", "generated_at": "2026-11-17",
           "meta": {"rules_patch": "18.6", "data_as_of": "2026-11-17",
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
        attach_unlock_requirements(mode, gm["heroes"], gm["items"], traits, reference)
        attach_mechanism_plans(mode, traits, heroes)
        attach_capstone_routes(mode, traits, heroes, items)
        comps = ([nature_comp(r, facts, reference, heroes, items, traits) for r in facts.get("official_published_lineups", [])]
                 if mode == "nature" else orange_comps(research, facts, reference, heroes, items, traits) +
                 orange_author_comps(reference, heroes, items, traits))
        for trait in traits:
            trait["mechanism_comp_ids"] = [comp["id"] for comp in comps if trait["key"] in comp.get("mechanism_trait_keys", [])]
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
                       | {k: h[k] for k in ["availability", "skill", "form_note", "unlock_requirements"] if k in h} for h in gm["heroes"]],
            "items": [{k: i[k] for k in ["id", "name", "icon", "category", "description", "base_stats", "components"]} for i in gm["items"]],
            "augments": [{"id": str(a["id"]), "name": a["name"]} for a in facts.get("augments", [])],
            "cards": cards, "coverage": {"traits": len(traits), "verified_traits": sum(t["verified"] for t in traits),
            "unresolved_traits": sum(not t["verified"] for t in traits), "compositions": len(comps),
            "published_recipe_count": sum(c.get("source_status") == "published_recipe" for c in comps),
            "provisional_recipe_count": sum(c.get("source_status") == "provisional_recipe" for c in comps),
            "author_complete_lineup_count": sum(c.get("source_status") == "published_author_example" for c in comps),
            "traits_with_linked_comps": sum(bool(t["linked_comp_ids"]) for t in traits),
            "traits_with_only_pools": sum(not t["linked_comp_ids"] for t in traits),
            "traits_with_mechanism_plans": sum(t["mechanism_plan"]["status"] != "unresolved" for t in traits),
            "traits_with_capstone_routes": sum(bool(t["capstone_routes"]) for t in traits),
            "capstone_routes": sum(len(t["capstone_routes"]) for t in traits),
            "heroes_with_unlock_tasks": sum(bool(h.get("unlock_requirements", {}).get("tasks")) for h in gm["heroes"]),
            "human_reviewed_nature_operations": len(reference.get("nature_action_summaries", [])) if mode == "nature" else 0}}
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
