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
ROLE_LABELS = {"tank": "承伤与生存", "fighter": "近战持续作战", "ad": "普攻 / 物理加成", "ap": "法强 / 技能增伤", "support": "辅助与施法"}
ROLE_REVIEW_SOURCE_HASHES = {
    "nature": "e5723a64c6a0eb87984e633d2a0bc1c5d23845d29167849d3e151d3b09215260",
    "orange": "64092922d8a5c2e05020d3a9dd3f152b1274d756797effa965544b8a23dcf56c",
}

# Development review of concrete official skill text. These are equipment
# directions, not replacements for the game's actual class/origin metadata.
ROLE_REVIEWS = {
    ("nature", "11500"): ("tank", False, "奥恩技能先获得自身护盾，近战护卫以承伤为明确职责；魔法伤害不等于法师职业。"),
    ("nature", "14503"): ("tank", False, "阿木木持续自我回复、近身范围伤害与控制，按承伤和反复施法参考。"),
    ("nature", "12512"): ("ap", False, "凯尔没有法力值，普攻附带法术加成魔法伤害；按法术普攻参考，不使用回蓝装。"),
    ("nature", "12514"): ("ap", False, "提莫的蘑菇技能明确为法术加成魔法伤害，按施法增伤参考。"),
    ("nature", "14505"): ("tank", True, "瑟提具有生命/物理加成的物理伤害和生命/法术加成的自疗；这是混合加成，不等于混合伤害。承伤与输出分工依阵容而变。"),
    ("nature", "11506"): ("ap", True, "阿卡丽造成物理伤害，同时有物理与法术加成的魔战士分支；官方阵容有法强出装，不能据此归为官方法师或强推统一三件套。"),
    ("orange", "11406"): ("ap", False, "克格莫技能为法术加成魔法伤害；狙神职业不能作为物理出装的充分证据。"),
    ("orange", "12407"): ("ap", False, "提莫的命中和持续中毒均为法术加成魔法伤害；狙神不改变这段伤害类型。"),
    ("orange", "15271"): ("ap", False, "吉格斯的普攻已替换为魔法炸弹，主动也造成魔法伤害；需要区分魔法普攻与纯施法路线。"),
    ("orange", "12404"): ("ap", False, "崔斯特没有法力值，普攻与每三次攻击的卡牌均为法术加成魔法伤害。"),
    ("orange", "15404"): ("ap", False, "易在冥想后普攻附带法术加成魔法伤害并自疗，按近战法术普攻参考，不能因裁决战士就强推物理三件套。"),
    ("orange", "15405"): ("ad", True, "凯尔无蓝条，早期神阶为物理加成真伤/物伤，后期剑雨为法术加成魔伤；阶段和成型时间影响装备，保留混合普攻歧义。"),
    ("orange", "14352"): ("tank", False, "布隆的技能含伤害减免、拦截弹体与护甲反伤，抗性承伤是明确的机制方向。"),
    ("orange", "14343"): ("tank", False, "内瑟斯窃取生命、获得双抗，持续伤害按生命上限；优先生命与承伤，不按魔法伤害字样强推纯法强。"),
    ("orange", "15285"): ("tank", True, "加里奥的魔法伤害按魔抗/双抗，且有团队护盾；抗性输出、承伤与保护职责并存，通用三件套待核验。"),
    ("orange", "15402"): ("fighter", True, "杰斯的主攻击为攻击力加成物理伤害，锻炉另有友军护盾；不能把一段团队护盾当作纯法术辅助。"),
    ("orange", "15279"): ("ap", False, "本模式瑟提的抓摔为法术加成魔法伤害，与自然之力瑟提的物理伤害及自疗机制不同。"),
    ("orange", "15412"): ("tank", False, "阿木木为近战大范围控制单位；技能魔法伤害不消除其承伤和启动需求。"),
    ("orange", "15413"): ("support", False, "迦娜轮换友军护盾、攻速、群体治疗和控制，按团队保护与施法参考。"),
}


def clean(text):
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&nbsp;", " ").strip()


def position(value):
    try:
        row, col = map(int, str(value).split(","))
        return {"row": row, "col": col} if 1 <= row <= 4 and 1 <= col <= 7 else None
    except (TypeError, ValueError):
        return None


def skill_mechanics(hero, raw):
    text = clean(raw.get("skillDesc"))
    # Explanatory glossary definitions are not damage dealt by this hero.
    text = re.split(r"\s{2,}(?:灼烧|重伤|冰冷|护甲击碎|魔抗击碎|缓速)[：:]", text, maxsplit=1)[0]
    damage_types = [key for word, key in [("物理伤害", "physical"), ("魔法伤害", "magic"), ("真实伤害", "true")] if word in text]
    profile = "mixed" if len(damage_types) > 1 else damage_types[0] if damage_types else "none" if text else "unknown"
    damage_clauses = [clause for clause in re.split(r"[。；\n]", text) if any(word in clause for word in ["物理伤害", "魔法伤害", "真实伤害"])]
    damage_text = "。".join(damage_clauses)
    scaling = [key for words, key in [(["【物理加成】", "【攻击力】"], "physical"), (["【法术加成】"], "ability"),
               (["【生命上限】", "【最大生命值】"], "health"), (["【护甲】", "【魔抗】", "【双抗】"], "resistance")]
               if any(word in damage_text for word in words)]
    on_hit = bool(re.search(r"普攻|普通攻击|攻击(?:造成|会|被替换|额外)|每第.{0,4}次攻击|每.{0,4}次攻击|下.{0,4}次攻击", text))
    ally = bool(re.search(r"友军.{0,40}(?:回复|治疗|护盾|攻击速度|增益)|(?:回复|治疗|护盾).{0,20}友军", text))
    survival = bool(re.search(r"(?:获得|回复|窃取|治疗自身|为自身).{0,45}(?:生命|护盾|护甲|魔抗)|伤害减免|减伤|拦截.{0,10}(?:弹|攻击)", text))
    return {"damage_profile": profile, "damage_types": damage_types, "damage_scaling": scaling,
            "attack_pattern": "on_hit" if on_hit else "caster" if damage_types else "utility",
            "has_normal_mana": float(hero.get("stats", {}).get("max_mana") or 0) > 0,
            "ally_support": ally, "self_survival": survival,
            "evidence": [f"技能伤害类型：{','.join(damage_types) or '未标明'}", f"伤害加成：{','.join(scaling) or '未标明'}",
                         "明确普攻/攻击特效文本" if on_hit else "未据职业名称假定普攻伤害类型"]}


def infer_role(hero, raw, traits, mode=None, source_sha256=None):
    """Skill-first equipment direction, never the game's official profession."""
    names = {t["name"] for t in traits if t.get("verified", True)}
    front = float(hero.get("stats", {}).get("attack_range") or 1) <= 2
    m = skill_mechanics(hero, raw)
    defensive_trait = bool(names & {"护卫", "重装战士", "主宰", "斗士", "神盾使"})
    ambiguous = False
    review = ROLE_REVIEWS.get((mode, str(hero.get("official_id"))))
    review_matches = source_sha256 == ROLE_REVIEW_SOURCE_HASHES.get(mode) and source_sha256 is not None
    reviewed = review if review_matches else None
    if reviewed:
        role, ambiguous, reason = reviewed
    elif m["damage_profile"] == "unknown":
        role, ambiguous, reason = "support", True, "技能资料不足，无法确定出装方向；不据职业名补猜。"
    elif front and ("resistance" in m["damage_scaling"] or "health" in m["damage_scaling"]) and m["self_survival"]:
        role, reason = "tank", "近战生存机制与生命/抗性伤害加成共同支持承伤方向；魔法伤害不等于法强最优。"
    elif front and defensive_trait and m["self_survival"] and m["attack_pattern"] != "on_hit":
        role, reason = "tank", "近战、自身生存技能与承伤羁绊共同支持承伤方向。"
    elif m["ally_support"]:
        role, reason = "support", "技能明确保护、治疗或增益友军，按团队施法与存活参考。"
        ambiguous = bool(m["damage_types"])
        if ambiguous:
            reason += "同时具有伤害，辅助与输出分工依阵容而变，暂停泛用出装。"
    elif m["damage_profile"] == "magic" and "ability" in m["damage_scaling"]:
        role, reason = "ap", "技能明确为法术加成魔法伤害；不因狙神、枪手等职业名改判为物理。"
        if m["attack_pattern"] == "on_hit":
            reason += "包含普攻法伤，需按攻击频率而非只按回蓝考虑。"
        if front and m["self_survival"] and defensive_trait:
            ambiguous = True
            reason += "也有承伤与自保线索，分工待核验。"
    elif m["damage_profile"] == "physical" and "physical" in m["damage_scaling"]:
        role = "fighter" if front else "ad"
        reason = "技能明确含物理伤害与攻击/物理加成，结合射程作为输出方向参考。"
        ambiguous = "ability" in m["damage_scaling"]
        if ambiguous:
            reason += "同段伤害也有法术加成，不能仅凭伤害类型确定物理装优先级。"
    elif m["damage_profile"] in ("mixed", "true"):
        role = "fighter" if front else "ad"
        ambiguous, reason = True, "技能有混合/真实伤害或多种加成，单一物理/法强分类不足；保留候选方向，暂停泛用出装。"
    elif front and m["self_survival"]:
        role, ambiguous, reason = "tank", True, "有近战生存线索，但输出与承伤分工证据不足，暂停泛用出装。"
    else:
        role, ambiguous, reason = "support", True, "现有技能证据不能唯一支持某类出装，保留待核验状态。"
    if review and not review_matches:
        ambiguous = True
        reason += "旧开发校准与当前官方英雄快照hash不一致，旧校准未应用，通用出装待重新核验。"
    return {"id": role, "label": ROLE_LABELS[role], "reason": reason, "frontline": front, "kind": "mechanic",
            "ambiguous": ambiguous, "reviewed": bool(reviewed), "review_snapshot_sha256": source_sha256 if reviewed else None, **m}


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
    if hero["role"].get("ambiguous"):
        return None
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
    if role == "ap" and hero["role"].get("attack_pattern") == "on_hit":
        wanted = ["鬼索的狂暴之刃", "纳什之牙", "班克斯的魔法帽"]
        reason = "普攻附带法术伤害参考：攻速与法强方向。若无法力值，不用回蓝装解决不存在的法力需求；有主动技能时还需另核启动。"
        if hero["role"]["frontline"]:
            wanted = ["鬼索的狂暴之刃", "正义之手", "珠光护手"]
            reason = "近战法术普攻参考：攻速、法强与续航需要兼顾；不能按职业名直接给物理穿甲或血手三件套。"
        elif not hero["stats"].get("max_mana"):
            wanted = ["鬼索的狂暴之刃", "班克斯的魔法帽", "巨人捕手"]
            reason = "无法力值的法术普攻参考：攻速、法强和通用增伤。当前纳什之牙的核心效果是普攻回蓝，已与朔极之矛、蓝霸符一并排除。"
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
    evidence = f"官方发布阵容的{'主C' if carry else '完整'}出装偏向{ROLE_LABELS[kind]}。"
    if kind != role["id"]:
        return {**role, "ambiguous": True, "lineup_direction": kind,
                "reason": role["reason"] + evidence + "与技能方向存在差异，通用出装暂停，保留具体阵容实例。",
                "evidence": role.get("evidence", []) + [evidence]}
    return {**role, "evidence": role.get("evidence", []) + [evidence]}


def applies_stun(text):
    """Require applying stun, rather than benefiting from already-stunned foes."""
    for clause in re.split(r"[。；]", text):
        if not re.search(r"晕眩|眩晕", clause):
            continue
        if re.search(r"(?:对抗|攻击|命中).{0,8}被(?:晕眩|眩晕)|免疫.{0,5}(?:晕眩|眩晕)", clause):
            continue
        if re.search(r"(?:使|令|将)(?:其|目标|敌人|敌方|所有|命中|这些|附近|当前|生命).{0,70}(?:晕眩|眩晕)|(?:造成|施加).{0,90}(?:晕眩|眩晕)|(?:晕眩|眩晕)(?:目标|敌人|命中)", clause):
            return True
    return False


def artifact_suggestions(hero, items, raw, source):
    by_id = {i["id"]: i for i in items if i["category"] == "artifact"}
    suggestions = []
    role, front = hero["role"]["id"], hero["role"]["frontline"]
    text = clean(raw.get("skillDesc"))
    mana = float(hero["stats"].get("max_mana") or 0)
    def add(item_id, reason, condition):
        if item_id in by_id and item_id not in {s["item_id"] for s in suggestions}:
            suggestions.append({"item_id": item_id, "kind": "mechanic", "reason": reason, "conditions": [condition], "source": source})
    if applies_stun(text):
        add("6079", "技能明确包含晕眩，可触发视界专注的晕眩伤害效果。", "需要实际施加晕眩；免疫控制的目标及触发间隔会影响收益。")
    self_shield = False
    for clause in re.split(r"[。；，]", text):
        if re.search(r"为(?:自身|自己|这个单位|【" + re.escape(hero.get("name", "")) + r"】).{0,65}护盾", clause):
            self_shield = True
        for match in re.finditer(r"获得.{0,65}护盾", clause):
            # '3名友军获得护盾' is not evidence that this hero receives it.
            if not re.search(r"友军|他们|友方", clause[:match.start()]):
                self_shield = True
    if self_shield and front:
        add("6076", "技能含护盾，禁忌雕像可将部分护盾转化为最大生命值。", "确认护盾实际施加给携带者；护盾转生命会改变承伤方式。")
    if hero["role"].get("ambiguous"):
        return suggestions
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
    if hero["role"].get("ambiguous"):
        return []
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
        if not hero["stats"].get("max_mana") and name in {"法师", "神谕", "神谕者", "耀光使"}:
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
        traits_by_key = {(t["kind"], str(t["id"])): {"id": str(t["id"]), "kind": t["kind"],
            "key": f'{t["kind"]}:{t["id"]}', "name": t["name"], "verified": True,
            "breakpoints": t.get("breakpoints", [])} for t in facts["traits"]}
        heroes = []
        for fact in facts["champion_star_form_records"]:
            if fact.get("observed_star_level") != 1 or not fact.get("shows_in_official_gallery"):
                continue
            hero_id = str(fact["official_id"])
            raw = reference["modes"][mode]["herourl"]["data"].get(hero_id, {})
            traits = []
            for kind, ids in [("origin", fact.get("origin_ids", [])), ("class", fact.get("class_ids", []))]:
                for trait_id in ids:
                    key = (kind, str(trait_id))
                    if key not in traits_by_key:
                        traits_by_key[key] = {"id": str(trait_id), "kind": kind, "key": f"{kind}:{trait_id}",
                            "name": f"{'特质' if kind == 'origin' else '职业'} ID {trait_id} · 待核验", "verified": False,
                            "breakpoints": [], "source": mechanic_source(mode, reference, "herourl")}
                    traits.append(traits_by_key[key])
            hero = {"id": hero_id, "name": fact["name"], "cost": fact["cost"], "icon": assets.get((mode, "hero", hero_id)),
                    "traits": traits, "stats": fact.get("stats", {}), "skill": {"name": fact.get("skill_name"), "description": clean(raw.get("skillDesc")),
                    "scaling": clean(raw.get("skillValueDesc")), "source": mechanic_source(mode, reference, "herourl")},
                    "statistics": None, "statistics_url": "https://www.dataj.cc/hero" if mode == "nature" else None}
            hero["official_class_raw"] = raw.get("class")
            hero["official_origin_raw"] = raw.get("species")
            hero["official_class_ids"] = [str(t) for t in fact.get("class_ids", [])]
            hero["official_origin_ids"] = [str(t) for t in fact.get("origin_ids", [])]
            hero["profession_status"] = ("none" if str(raw.get("class", "")).strip() in ("0", "-1") else
                "known" if hero["official_class_ids"] and all(traits_by_key[("class", t)]["verified"] for t in hero["official_class_ids"]) else "unresolved")
            regular = (float(raw.get("price") or 0) > 0 and raw.get("heroType") == "0")
            hero["regular_shop_unit"] = regular
            hero["equipment_eligibility"] = "regular_unit" if regular else "unverified_special_unit"
            hero["equipment_note"] = "特殊单位：官方配置标价/出售价格为0，可装备性与获取机制未核验，因此不提供普通装备、神器或纹章建议。" if not regular else None
            hero["role"] = infer_role(fact, raw, traits, mode=mode,
                source_sha256=reference["modes"][mode]["herourl"]["original_file_sha256"])
            hero["role"]["source"] = mechanic_source(mode, reference, "herourl")
            builds = official_builds(hero_id, facts.get("official_published_lineups", []), item_ids)
            hero["role"] = refine_role_from_builds(hero["role"], builds, items)
            fallback = fallback_build(hero, items, mechanic_source(mode, reference))
            hero["builds"] = builds[:6] + ([fallback] if fallback else [])
            hero["recommendation_note"] = ("出装方向存在歧义或证据冲突，暂停泛用三件套与泛用纹章；保留官方阵容实例、历史统计和明确技能触发证据。" if hero["role"]["ambiguous"] else
                "出装方向是按当前技能资料作的参考，不能代替官方职业或证明最优。")
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
            "heroes": heroes, "items": items, "traits": list(traits_by_key.values()), "sources": [mechanic_source(mode, reference, k) for k in ("herourl", "equipurl")],
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
