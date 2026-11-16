#!/usr/bin/env python3
"""Build the portable, source-attributed hero equipment guide.

Official lineup loadouts and positions are examples published by their authors;
they are never interpreted as hero/item win rates. Mechanic suggestions are
explicit, conditional rules, not statistical rankings. No live API is required.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROLE_LABELS = {"tank": "前排承伤", "fighter": "近战输出", "ad": "物理后排", "ap": "法术输出", "support": "辅助施法"}


def clean(text):
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&nbsp;", " ").strip()


def position(value):
    try:
        row, col = map(int, str(value).split(","))
        return {"row": row, "col": col} if 1 <= row <= 4 and 1 <= col <= 7 else None
    except (TypeError, ValueError):
        return None


def infer_role(hero, raw, traits):
    """Conservative, explained archetype; this is not an official role label."""
    names = {t["name"] for t in traits}
    desc = clean(raw.get("skillDesc"))
    attack_range = float(hero.get("stats", {}).get("attack_range") or 1)
    front = attack_range <= 2
    protects_allies = bool(re.search(r"友军.{0,24}(治疗|护盾|攻击速度)|为.{0,12}友军", desc))
    defensive_trait = bool(names & {"护卫", "重装战士", "主宰", "斗士"})
    physical_trait = bool(names & {"迅捷射手", "猎人", "枪手", "狙神", "征服者"})
    fighter_trait = bool(names & {"狂战士", "迅击战士", "裁决战士"})
    magic = "魔法伤害" in desc
    physical = "物理伤害" in desc
    if protects_allies and not defensive_trait:
        role, reason = "support", "技能文本包含对友军的治疗、护盾或增益；优先保证施法和存活。"
    elif front and defensive_trait and not fighter_trait:
        role, reason = "tank", "近战射程及承伤羁绊提示前排职责；装备方向先考虑生命、抗性和持续作战。"
    elif front and (fighter_trait or physical):
        role, reason = "fighter", "近战射程与输出技能提示近战作战；输出装需要搭配续航或生存。"
    elif not front and (physical_trait or (physical and not magic)):
        role, reason = "ad", "远程射程与物理输出线索提示后排普攻/物理输出方向。"
    elif front and ("护盾" in desc or "治疗自身" in desc):
        role, reason = "tank", "近战且技能提供自身生存手段，先以承伤和反复施法为参考。"
    elif magic:
        role, reason = "ap", "技能明确造成魔法伤害，可考虑法强、施法频率及技能增伤。"
    elif front:
        role, reason = "fighter", "近战射程；缺少可靠角色专属出装时，以输出与生存平衡作为参考。"
    else:
        role, reason = "support", "技能机制不适合仅凭面板判定主输出；以施法和保护站位作为参考。"
    return {"id": role, "label": ROLE_LABELS[role], "reason": reason, "frontline": front, "kind": "mechanic"}


def item_category(row):
    typ = row.get("type", "")
    return {"基础装备": "component", "成型装备": "standard", "神器装备": "artifact", "转职纹章": "emblem", "光明武器": "radiant", "辅助装备": "support"}.get(typ, "other")


def mechanic_source(mode, reference, key="equipurl"):
    row = reference["modes"][mode][key]
    return {"title": "官方装备配置" if key == "equipurl" else "官方英雄配置", "url": row["source_url"], "published_at": row["generated_at"], "patch": row["version"], "kind": "official_configuration"}


def build_items(mode, facts, reference, assets):
    result = []
    raw_items = reference["modes"][mode]["equipurl"]["data"]
    for fact in facts["items"]:
        row = raw_items.get(str(fact["id"]), {})
        name = clean(fact["name"])
        traits = list(fact.get("linked_trait_ids", []))
        if item_category(row) == "emblem":
            target = name.removesuffix("纹章")
            traits.extend(t["id"] for t in facts["traits"] if t["name"] == target)
        result.append({"id": str(fact["id"]), "name": name, "type": fact["type"], "category": item_category(row),
                       "icon": assets.get((mode, "item", str(fact["id"]))), "description": clean(row.get("desc")),
                       "base_stats": clean(row.get("basicDesc")), "components": list(fact.get("components", [])),
                       "trait_ids": sorted(set(traits)), "source": mechanic_source(mode, reference)})
    return result


def fallback_build(hero, items, source):
    names = {r["name"]: r["id"] for r in items if r["category"] == "standard"}
    role = hero["role"]["id"]
    choices = {
        "tank": (["石像鬼石板甲", "狂徒铠甲", "巨龙之爪"], "承伤参考：生命配抗性；敌方以物理为主时可改棘刺背心，能持续治疗时再考虑振奋盔甲。"),
        "fighter": (["汲取剑", "泰坦的坚决", "斯特拉克的挑战护手"], "近战参考：续航、叠层输出和低血保护。纯法术近战应改用法强装备，别机械追求物理装。"),
        "ad": (["鬼索的狂暴之刃", "无尽之刃", "最后的轻语"], "普攻/物理参考：攻速、暴击与破甲。队伍已有稳定破甲时可替换轻语；依赖技能的物理英雄还需回蓝。"),
        "ap": (["朔极之矛", "珠光护手", "班克斯的魔法帽"], "法术参考：施法频率配技能增伤。技能机制、当前强化和已有法强会改变回蓝装及第三件选择。"),
        "support": (["朔极之矛", "适应性头盔", "大天使之杖"], "辅助施法参考：先保证能反复施法，再依据技能是否受法强加成选择第三件；不应抢走主C核心散件。"),
    }
    wanted, reason = choices[role]
    if role == "ap" and hero["role"]["frontline"]:
        wanted = ["正义之手", "珠光护手", "冕卫"]
        reason = "近战法术参考：续航、技能增伤与开战保护。需要接近敌人，不能照搬后排法师的三件纯输出装。"
    if role == "ap" and not hero["stats"].get("max_mana"):
        wanted = ["鬼索的狂暴之刃", "纳什之牙", "班克斯的魔法帽"]
        reason = "无法力值的普攻/被动法术参考：攻速与法强方向；回蓝装备不能解决不存在的法力需求。需核对各星级或形态的实际伤害加成。"
    return {"id": "mechanic-" + role, "title": "按机制选择的装备骨架", "kind": "mechanic", "item_ids": [names[n] for n in wanted if n in names],
            "reason": reason, "conditions": ["未根据对局统计排序；需结合实际技能、对手、强化和现有装备调整。"], "source": source, "position": None, "board": []}


def refine_role_from_builds(role, builds, items):
    """Use author loadouts as extra evidence without claiming an official role."""
    if not builds:
        return role
    by_id = {i["id"]: i for i in items}
    carry = [b for b in builds if "标为主C" in b["reason"] and len(b["item_ids"]) >= 2]
    sample = carry or [b for b in builds if len(b["item_ids"]) >= 2]
    if not sample:
        return role
    types = {"tank": {"石像鬼石板甲", "狂徒铠甲", "巨龙之爪", "棘刺背心", "振奋盔甲", "坚定之心", "圣盾使的誓约"},
             "ap": {"珠光护手", "班克斯的魔法帽", "大天使之杖", "虚空之杖", "蓝霸符"},
             "ad": {"无尽之刃", "最后的轻语", "海妖之怒", "锐利之刃", "强袭者的链枷"}}
    counts = Counter()
    for build in sample:
        for item_id in build["item_ids"]:
            name = by_id[item_id]["name"]
            for key, names in types.items():
                if name in names:
                    counts[key] += 1
    if not counts:
        return role
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return role
    kind = ranked[0][0]
    if kind == "ad" and role["frontline"]:
        kind = "fighter"
    return {**role, "id": kind, "label": ROLE_LABELS[kind],
            "reason": f"已发布阵容的{'主C' if carry else '完整'}出装中，{ROLE_LABELS[kind]}方向的装备更常出现；这是出装证据归纳，仍需按具体阵容分工调整。"}


def artifact_suggestions(hero, items, raw, source):
    by_id = {i["id"]: i for i in items if i["category"] == "artifact"}
    suggestions = []
    role, front = hero["role"]["id"], hero["role"]["frontline"]
    text = clean(raw.get("skillDesc"))
    mana = float(hero["stats"].get("max_mana") or 0)
    def add(item_id, reason, condition):
        if item_id in by_id and item_id not in {s["item_id"] for s in suggestions}:
            suggestions.append({"item_id": item_id, "kind": "mechanic", "reason": reason, "conditions": [condition], "source": source})
    if "晕眩" in text:
        add("6079", "技能明确包含晕眩，可触发视界专注的晕眩伤害效果。", "需要实际施加晕眩；免疫控制的目标及触发间隔会影响收益。")
    if "护盾" in text and front:
        add("6076", "技能含护盾，禁忌雕像可将部分护盾转化为最大生命值。", "确认护盾实际施加给携带者；护盾转生命会改变承伤方式。")
    if role == "tank":
        add("6085", "光盾徽章利用护甲和魔抗生成友军护盾，与前排抗性方向相容。", "携带者需要足够抗性；它偏保护，不等于最高单体伤害。")
        add("6092", "黎明圣盾从近邻敌人获取护甲并回复生命，适合持续近战承伤。", "需要接近敌人并存活；对方重伤和魔法爆发会降低适配。")
        add("6093", "黄昏圣盾从近邻敌人获取魔抗并造成伤害。", "需要持续处于敌人附近；可与黎明圣盾组成有明确机制的双盾组合。")
    elif role == "fighter":
        add("6054", "死亡之蔑提供物理加成、抗性和全能吸血，并延后部分承伤。", "适合有持续输出和治疗机会的近战；纯法术输出需比较其他神器。")
        if "物理伤害" in text:
            add("6073", "暗行者之爪提供物理与暴击，并在击杀后转移目标。", "需要能可靠完成击杀，且冲刺后的站位不能使携带者立即被集火。")
        add("6090", "巨型九头蛇把生命值与物理加成转为普攻溅射伤害。", "需要经常普攻并有生命/物理加成，技能型法术近战不应仅凭近战标签选它。")
    elif role == "ad":
        add("6065", "投机者之刃的攻速和普攻掉金币机制适合持续普攻方向。", "存款达到装备条件且有足够攻击次数时才更有价值。")
        add("6080", "疾射火炮提供攻速与射程，可能改善远程输出的接敌安全。", "需要普攻收益；增加射程仍不能防住跳后排或全屏技能。")
        add("6087", "纳沃利烁刃随攻击叠攻速并周期提供物理与法术加成。", "需要长时间持续攻击；攻速锁定或收益转换机制须单独核对。")
    elif role == "ap":
        if front:
            add("6084", "探索者的护臂将参与击败转为法强与双抗，并提供全能吸血。", "需要近战或持续作战并参与击败；启动前仍可能被集火。")
        if mana > 0:
            add("6058", "魔蕴在首次施法后回复法力，有利于后续技能循环。", "需要能正常施法并从法力回复受益；首次启动仍要单独解决。")
        elif "攻击" in text or "普攻" in text:
            add("6075", "智慧末刃提供攻速与普攻额外魔法伤害，适合无法力值的普攻输出方向。", "需要持续普攻；它的治疗依赖实际造成的魔法伤害。")
            add("6087", "纳沃利烁刃随攻击叠加攻速与双加成，不要求回复法力。", "需要持续攻击，具体伤害取决于当前形态的加成。")
        if 0 < mana <= 70:
            add("6086", "巫妖之祸强化每次施法后的第一次普攻，低法力技能更容易反复触发。", "施法后必须能接普攻；纯被动或不能正常攻击的形态不适用。")
        if "魔法伤害" in text:
            add("6083", "枯萎珠宝在造成魔法伤害时削减魔抗。", "频繁、多段或持续魔法伤害更容易叠效果；并非所有法术英雄都等收益。")
        add("6060", "中娅悖论提供法强与一次免伤窗口，可处理关键爆发。", "属于生存选择；能否因此多放一次技能取决于对手与实际站位。")
    else:
        if mana > 0:
            add("6058", "魔蕴可支持辅助英雄首次施法后的后续循环。", "先确认法力回复与该英雄技能机制兼容。")
        add("6098", "永恒契约可与高生命友军联动，提供法力与护盾。", "需核对开战时契约对象，避免错误绑定；收益依赖该友军施法与存活。")
    return suggestions[:4]


def emblem_suggestions(hero, items, source):
    native = {t["id"] for t in hero["traits"]}
    native_names = {t["name"] for t in hero["traits"]}
    role = hero["role"]["id"]
    wanted = {
        "tank": {"斗士", "护卫", "重装战士", "主宰"},
        "fighter": {"狂战士", "迅击战士", "裁决战士", "斗士"},
        "ad": {"迅捷射手", "猎人", "枪手", "狙神"},
        "ap": {"法师", "神谕", "神谕者", "耀光使"},
        "support": {"神谕", "神谕者", "神盾使"},
    }[role]
    result = []
    for item in items:
        name = item["name"].removesuffix("纹章")
        if item["category"] != "emblem" or name not in wanted or name in native_names or native.intersection(item["trait_ids"]):
            continue
        result.append({"item_id": item["id"], "kind": "mechanic", "reason": f"{name}方向与{hero['role']['label']}存在机制匹配，可作为外援补羁绊的候选。",
                       "conditions": [f"仅在本局正在构筑{name}、纹章能跨关键档位时考虑。", "携带者原本不具有该羁绊；还需比较它占用的装备槽价值。"], "source": source})
    return result[:4]


def official_builds(hero_id, lineups, item_ids):
    builds = []
    for lineup in lineups:
        board = lineup.get("main_board", [])
        unit = next((u for u in board if str(u.get("hero_id")) == hero_id), None)
        if not unit:
            continue
        equipment = [str(i) for i in unit.get("item_ids", []) if str(i) in item_ids]
        source = {"title": lineup["name"], "url": lineup.get("source_url"), "published_at": lineup.get("published_at"),
                  "author": lineup.get("source_author"), "patch": lineup.get("simulator_edition_source"), "kind": "official_lineup"}
        builds.append({"id": str(lineup["id"]), "title": lineup["name"], "kind": "official_lineup", "item_ids": equipment,
                       "reason": "该阵容中作者为此棋子配置的装备与站位。" + ("在此阵容中标为主C。" if unit.get("is_carry") else ""),
                       "conditions": ["与该阵容、星级目标和队伍分工一起参考；不是装备组合胜率或当前版本最优证明。"],
                       "source": source, "position": position(unit.get("position")),
                       "board": [{"hero_id": str(u["hero_id"]), **p} for u in board if (p := position(u.get("position")))]})
    builds.sort(key=lambda b: (bool(b["item_ids"]), b["source"].get("published_at") or ""), reverse=True)
    return builds


def build_guide(base=BASE):
    reference = json.loads((base / "app/data/hero_guide_reference.json").read_text())
    manifest = json.loads((base / "app/assets/manifest.json").read_text())
    assets = {(r["mode"], r["kind"], str(r["entity_id"])): "assets/" + r["path"] for r in manifest["assets"]}
    watch = json.loads((base / "app/data/patch_watch.json").read_text())
    stat_path = base / "app/data/hero_guide_statistics.json"
    statistics = json.loads(stat_path.read_text()) if stat_path.is_file() else None
    output = {"schema_version": "hero-guide-v1", "generated_at": "2026-11-16", "meta": {
        "rules_patch": "18.6", "data_as_of": "2026-11-10", "latest_announced_patch": watch.get("latest_announced_patch"),
        "notice": "规则与官方阵容为18.6资料快照；已发现18.6a公告，尚未完成全量规则迁移。下列搭配供版本参考。",
        "statistics_status": "自然之力提供第三方18.6历史三件套观察，每组至少100样本；大橘大利没有可用的同口径组合统计。" if statistics else "没有可核验的英雄×三件套对局样本；不展示装备组合胜率，也不按未经验证的胜率排序。",
        "statistics_checked_on": "2026-11-16", "statistics_external_url": "https://www.dataj.cc/hero",
        "statistics_external_notice": "外部自然之力页面于2026-11-16可访问，站点自报18.6、更新时间2026-11-15。仅收录ID与名称对应、每组合至少100样本的有限历史三件套观察；样本口径未独立核验。",
        "position_convention": "4行×7列，行1为己方前排（靠敌方），行4为己方后排；列1至7按画面左到右。推荐格仅为阵容示例或角色参考，需按对手调整。",
        "sources": [{"title": "金铲铲之战官网", "url": "https://jcc.qq.com/"},
                    {"title": "18.6a官方公告观察记录", "url": watch.get("source_url")}],
        "rules_method": "官方阵容逐棋子提取；缺少阵容时按可见技能、射程与羁绊作条件性建议。机制建议不是模型预测或统计最优。"}, "modes": {}}
    for mode, filename in [("nature", "nature_facts.json"), ("orange", "orange_base_facts.json")]:
        facts = json.loads((base / "app/data" / filename).read_text())
        items = build_items(mode, facts, reference, assets)
        item_ids = {i["id"] for i in items}
        traits_by_id = {str(t["id"]): {"id": str(t["id"]), "name": t["name"], "breakpoints": t.get("breakpoints", [])} for t in facts["traits"]}
        heroes = []
        for fact in facts["champion_star_form_records"]:
            if fact.get("observed_star_level") != 1 or not fact.get("shows_in_official_gallery"):
                continue
            hero_id = str(fact["official_id"])
            raw = reference["modes"][mode]["herourl"]["data"].get(hero_id, {})
            traits = [traits_by_id[str(t)] for t in fact.get("origin_ids", []) + fact.get("class_ids", []) if str(t) in traits_by_id]
            hero = {"id": hero_id, "name": fact["name"], "cost": fact["cost"], "icon": assets.get((mode, "hero", hero_id)),
                    "traits": traits, "stats": fact.get("stats", {}), "skill": {"name": fact.get("skill_name"), "description": clean(raw.get("skillDesc")),
                    "scaling": clean(raw.get("skillValueDesc")), "source": mechanic_source(mode, reference, "herourl")},
                    "statistics": None, "statistics_url": "https://www.dataj.cc/hero" if mode == "nature" else None}
            regular = (float(raw.get("price") or 0) > 0 and raw.get("heroType") == "0")
            hero["regular_shop_unit"] = regular
            hero["equipment_eligibility"] = "regular_unit" if regular else "unverified_special_unit"
            hero["equipment_note"] = "特殊单位：官方配置标价/出售价格为0，可装备性与获取机制未核验，因此不提供普通装备、神器或纹章建议。" if not regular else None
            hero["role"] = infer_role(fact, raw, traits)
            builds = official_builds(hero_id, facts.get("official_published_lineups", []), item_ids)
            hero["role"] = refine_role_from_builds(hero["role"], builds, items)
            hero["builds"] = builds[:6] + [fallback_build(hero, items, mechanic_source(mode, reference))]
            hero["official_build_count"] = len(builds)
            hero["artifacts"] = artifact_suggestions(hero, items, raw, mechanic_source(mode, reference))
            hero["emblems"] = emblem_suggestions(hero, items, mechanic_source(mode, reference))
            hero["emblem_note"] = "纹章候选按机制与羁绊档位筛选，不是通用优先级；本来具有的羁绊已排除。" if hero["emblems"] else "没有足够依据推荐额外纹章；优先保证已有装备与实际阵容，勿为凑纹章占用装备槽。"
            positions = Counter((b["position"]["row"], b["position"]["col"]) for b in builds if b["position"])
            cells = [{"row": r, "col": c, "kind": "official_lineup", "count": count} for (r, c), count in positions.most_common(6)]
            front = hero["role"]["frontline"]
            fallback_row = 1 if front else 4
            if not cells:
                cells = [{"row": fallback_row, "col": c, "kind": "mechanic"} for c in ([3, 4, 5] if front else [2, 6])]
            hero["positioning"] = {"summary": "优先参考下方阵容站位" if positions else ("前排承伤 / 近战接敌" if front else "后排保护 / 保留输出空间"),
                "reason": "格子来自官方发布阵容；相同棋子在不同阵容中的位置可能不同。" if positions else hero["role"]["reason"],
                "kind": "official_lineup" if positions else "mechanic", "recommended_cells": cells,
                "sources": [b["source"] for b in builds[:3]],
                "adjustments": ["观察对手主C、切后排与范围技能，避免关键单位被直接集火。", "依赖邻格、独立站位或射程的装备，要同时满足其站位条件。"]}
            if not regular:
                hero["builds"], hero["artifacts"], hero["emblems"] = [], [], []
                hero["positioning"] = {"summary": "特殊单位站位机制待核验", "reason": hero["equipment_note"], "kind": "unknown", "recommended_cells": [], "sources": [], "adjustments": []}
            if mode == "nature" and statistics:
                record = statistics["heroes"].get(hero_id)
                if record:
                    hero["statistics"] = {"kind": "third_party_observational", "source": {**statistics["source"], "url": record.get("source_url", statistics["source"]["url"])},
                        "minimum_sample_count": statistics["minimum_sample_count"], "combos": record["combos"], "status": record["status"],
                        "reason": record.get("reason"), "notice": statistics["notice"]}
                    if record.get("retrieved_at"):
                        hero["statistics"]["source"]["retrieved_at"] = record["retrieved_at"]
            heroes.append(hero)
        heroes.sort(key=lambda h: (h["cost"], h["id"]))
        output["modes"][mode] = {"id": mode, "name": facts["scope"]["mode"], "official_version": facts["scope"]["official_version"],
            "heroes": heroes, "items": items, "traits": list(traits_by_id.values()), "sources": [mechanic_source(mode, reference, k) for k in ("herourl", "equipurl")],
            "coverage": {"heroes": len(heroes), "regular_shop_units": sum(h["regular_shop_unit"] for h in heroes), "heroes_with_official_builds": sum(bool(h["official_build_count"]) for h in heroes), "items": len(items), "missing_hero_icons": sum(not h["icon"] for h in heroes),
                         "heroes_with_statistics": sum(bool(h["statistics"] and h["statistics"]["combos"]) for h in heroes)}}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "app/static/guide-data.json")
    args = parser.parse_args()
    guide = build_guide()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(guide, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({m: d["coverage"] for m, d in guide["modes"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
