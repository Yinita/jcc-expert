#!/usr/bin/env python3
"""Build the round3 report from completed paired outputs; never run inference.

This program reads sealed annotations only when explicitly called with them.
The caller must unseal first. It does not change models, annotations, rules,
OCR output, or source screenshots. Paired reports and linked artifacts are
copied by the caller; only index.html and summary.json are written here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import html
import json
from pathlib import Path
import sys

from build_expanded_report import digest, load_pair, read_json, REVISIONS, MODES

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
CN_MODE = {"all": "全部", "nature": "自然之力", "orange": "大橘大利"}
CN_REV = {"baseline": "改进前基线", "optimized": "本轮优化"}
CN_SPLIT = {"development": "开发 · 历史全图OCR回放", "sealed": "新来源 · 冻结端到端"}


def optional_json(path):
    return read_json(path) if path and Path(path).is_file() else None


def training_summary(path):
    raw = optional_json(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), dict):
        raise ValueError("训练摘要缺失或格式不完整；请传入 round3_training/final_summary.json")
    result = {}
    for name in ("baseline", "enhanced", "expanded_v3", "expanded_v4"):
        row = raw["results"].get(name)
        if not isinstance(row, dict) or not isinstance(row.get("validation_metrics"), dict):
            raise ValueError(f"训练摘要缺少候选：{name}")
        metric = row["validation_metrics"]
        for key in ("n_labelled", "correct", "wrong", "abstain"):
            if not isinstance(metric.get(key), int):
                raise ValueError(f"候选 {name} 缺少可审计的 {key}")
        if row.get("deployable") is not False:
            raise ValueError("本轮报告不接受已启用或门槛不明的训练候选")
        result[name] = row
    if raw.get("production_candidate_enabled") is not False or raw.get("win_probability_training") is not False:
        raise ValueError("训练摘要未明确候选关闭与未训练胜率模型")
    return {"results": result, "candidates_enabled": False, "winrate_training_performed": False,
            "independent_final_test_evidence": False, "test_result": raw.get("test_result"),
            "source_sha256": digest(path), "notes": raw.get("notes", [])}


def safe_delta(left, right):
    return None if left is None or right is None else right-left


def build_summary(args):
    freeze = read_json(args.freeze)
    freeze_sha = digest(args.freeze)
    frozen_modules = {r["file"]: r["sha256"] for r in freeze.get("files", [])}
    development, dev_samples = load_pair(args.development_paired, args.development_annotations,
                                        freeze_sha, False, frozen_modules)
    sealed, sealed_samples = load_pair(args.sealed_paired, args.sealed_annotations,
                                      freeze_sha, True, frozen_modules)
    ids = [{s["id"] for s in rows} for rows in (dev_samples, sealed_samples)]
    groups = [{s["group_id"] for s in rows} for rows in (dev_samples, sealed_samples)]
    if ids[0] & ids[1] or groups[0] & groups[1]:
        raise ValueError("开发与新来源留出存在重复ID或来源组，不能称新来源留出")
    if not dev_samples or not sealed_samples:
        raise ValueError("开发与新来源留出都必须有实际评测输入")
    all_samples = dev_samples + sealed_samples
    corpus = {"images": len(all_samples), "source_groups": len(groups[0] | groups[1]),
              "development_images": len(dev_samples), "development_groups": len(groups[0]),
              "sealed_images": len(sealed_samples), "sealed_groups": len(groups[1])}
    splits = {"development": development, "sealed": sealed}
    deltas = {}
    for split, pair in splits.items():
        deltas[split] = {}
        for mode in ("all", *MODES):
            before = pair["revisions"]["baseline"]["by_mode"][mode]
            after = pair["revisions"]["optimized"]["by_mode"][mode]
            deltas[split][mode] = {key: safe_delta(before.get(key), after.get(key))
                                  for key in ("correct", "wrong", "abstain", "coverage", "precision")}
    patch_audit = optional_json(args.patch_audit)
    return {
        "schema_version": "round3.1", "date": "2026-11-12", "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus, "splits": splits, "observed_deltas": deltas,
        "evaluation_protocol": {
            "development": {"kind": "historical_whole_OCR_replay_with_current_HUD_OCR_and_postprocessing", "end_to_end": False,
                "description": "回放实际历史whole OCR缓存，执行当前后处理及必要HUD局部OCR；不重跑全图OCR，不能作为统一端到端OCR提升。"},
            "sealed": {"kind": "frozen_new_source_group_end_to_end", "end_to_end": True,
                "freeze_verified_before_and_after": sealed["freeze_verified_before_and_after"],
                "description": "冻结后首次处理新来源组；包含实际OCR与后处理。来源组独立不证明对局、作者或媒体素材独立。"}},
        "freeze": {"frozen_at": freeze.get("frozen_at") or freeze.get("created_at"), "sha256": freeze_sha,
                   "sealed_bound_and_verified": sealed["freeze_verified_before_and_after"]},
        "source_scope": {
            "server_status_counts": dict(Counter(str(s.get("server_status", "unknown")) for s in all_samples)),
            "capture_patch_counts": dict(Counter(str(s.get("patch")) for s in all_samples)),
            "formal_current_patch_validation": False, "independence_unit": "source_group_not_match_or_author"},
        "training": training_summary(args.training_summary),
        "patch_watch": {"local_rules_patch": "18.6", "official_new_patch_announced": "18.6a",
                        "official_static_catalog_synchronized": False, "newer_patch_policy": "blocked",
                        "audit_loaded": patch_audit is not None, "audit": patch_audit},
        "definitions": {
            "labelled": "stage/gold/hp/level及有人工真值的商店槽；null或缺失标签不计正确，已标注而无输出为弃答。",
            "coverage": "(correct+wrong)/(correct+wrong+abstain)",
            "precision": "correct/(correct+wrong)；零回答时为null，必须同时读N和弃答。",
            "absence": "仅人工明确标注本图缺席的字段单列误输出；五格全null视为无商店输出，数值0是实际输出；不加入主正确值分母。",
            "candidate_diagnostic": "card_boxes优先，其次labels.entities；ID及局部位置命中，仅对不完整标注区域做诊断。既不是精确率，也不是完整召回率。",
            "first_place": "本报告衡量截图识别，未训练胜率模型，也无第一名收益或实战胜率提升证据。"},
        "limitations": [
            f"开发{len(dev_samples)}图与本轮候选验证均已消费，不能称独立最终测试。",
            "开发运行回放实际历史whole OCR缓存，并执行当前后处理及必要HUD局部OCR；只有新来源冻结评测才称端到端。",
            "新来源组留出不证明不同对局、作者或录像独立；相似UI、转载与共享媒体素材仍可能相关。",
            "来源截图包含体验、测试或补丁不明的公开材料，不构成当前正式服18.6或18.6a准确率验证。",
            "本轮HUD规则及其他已冻结后处理的差异，不能归因于未启用的监督学习候选。",
            "四候选复用开发验证，最终V4仍未达发布门槛；没有用本轮新封存测试挑选阈值或激活模型。",
            "paired运行的缓存、启动和预处理路径不同；不做速度倍数、加速或公平性能提升推断。"],
        "timing_comparison_eligible": False,
        "provenance": {"development_annotations_sha256": digest(args.development_annotations),
                       "sealed_annotations_sha256": digest(args.sealed_annotations),
                       "training_summary_sha256": digest(args.training_summary),
                       "patch_audit_sha256": digest(args.patch_audit) if args.patch_audit.is_file() else None,
                       "builder_sha256": digest(__file__)}}


def render(data):
    esc = lambda value: html.escape(str(value), quote=True)
    pct = lambda value: "—" if value is None else f"{value*100:.1f}%"
    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    score_rows, absence_rows, candidate_rows, safety_rows, field_rows, false_rows = [], [], [], [], [], []
    for split, pair in data["splits"].items():
        for mode in ("all", *MODES):
            for revision in REVISIONS:
                metric = pair["revisions"][revision]["by_mode"][mode]
                score_rows.append([CN_SPLIT[split], CN_MODE[mode], CN_REV[revision], metric["images"], metric["labelled"],
                                   metric["correct"], metric["wrong"], metric["abstain"], pct(metric["coverage"]), pct(metric["precision"])])
                absent = metric["explicit_absence"]
                absence_rows.append([CN_SPLIT[split], CN_MODE[mode], CN_REV[revision], absent.get("images_with_explicit_absence", 0),
                                     absent.get("field_checks", 0), absent.get("false_outputs", 0)])
                candidate = metric["incomplete_candidate_diagnostic"]
                candidate_rows.append([CN_SPLIT[split], CN_MODE[mode], CN_REV[revision], candidate.get("annotated_images", 0),
                    candidate.get("labelled_regions", 0), candidate.get("same_id_in_region", 0),
                    candidate.get("same_id_anywhere", 0), candidate.get("unlocalized_annotations_excluded", 0)])
        for revision in REVISIONS:
            record = pair["revisions"][revision]
            for name, metric in record["per_field"].items():
                field_rows.append([CN_SPLIT[split], CN_REV[revision], name, metric["labelled"], metric["correct"], metric["wrong"], metric["abstain"]])
            metric = record["by_mode"]["all"]
            safety = metric["safety"]
            safety_rows.append([CN_SPLIT[split], CN_REV[revision], safety.get("states", 0), safety.get("unconfirmed", 0),
                safety.get("null_personal_probability", 0), metric["safety_contract_failures"], metric["recognition_errors"]])
            for row in metric["explicit_absence"]["records"]:
                false_rows.append([CN_SPLIT[split], CN_REV[revision], row["sample_id"], row["field"], json.dumps(row["output"], ensure_ascii=False)])
    training_rows = []
    candidate_labels = {"baseline": "原受控 baseline", "enhanced": "上下文与监督去重", "expanded_v3": "追加7开发图 V3", "expanded_v4": "数字框对齐 V4"}
    for name, row in data["training"]["results"].items():
        metric = row["validation_metrics"]
        training_rows.append([candidate_labels[name], row["training_rows"], metric["n_labelled"], metric["correct"], metric["wrong"],
                              metric["abstain"], metric.get("correct_absence", 0), metric.get("false_positive_absent", 0), "关闭"])
    c = data["corpus"]
    before = data["splits"]["development"]["revisions"]["baseline"]["by_mode"]["all"]
    after = data["splits"]["development"]["revisions"]["optimized"]["by_mode"]["all"]
    sb = data["splits"]["sealed"]["revisions"]["baseline"]["by_mode"]["all"]
    so = data["splits"]["sealed"]["revisions"]["optimized"]["by_mode"]["all"]
    frozen = data["freeze"].get("frozen_at")
    try:
        frozen = datetime.fromisoformat(frozen.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S 北京时间')
    except (ValueError, TypeError, AttributeError):
        frozen = frozen or "冻结清单未提供时间"
    links = ''.join(f'<a href="{split}/{revision}/report.html">{esc(CN_SPLIT[split])} · {esc(CN_REV[revision])}逐图结果 ↗</a>' for split in data["splits"] for revision in REVISIONS)
    limitations = ''.join('<li>'+esc(v)+'</li>' for v in data["limitations"])
    source_json = esc(json.dumps({key: data[key] for key in ("source_scope", "freeze", "provenance")}, ensure_ascii=False, indent=2))
    body = f'''
<header><div class="eyebrow">JCC / ROUND 03 · 2026.11.12</div><h1>让识别改进<br>有分母，也有边界。</h1><p>开发材料回放用于定位问题；新来源截图在冻结后进行端到端评测。两种结果分开呈现，训练候选继续保留为研究工件。</p><div class="badges"><span>默认识别 · 无人工ROI</span><span>学习候选关闭</span><span>胜率未训练</span><span>非当前正式补丁验证</span></div><div class="numbers"><div><strong>{c['images']}</strong><span>公开界面截图</span></div><div><strong>{c['source_groups']}</strong><span>来源组，非对局数</span></div><div><strong>{c['development_images']} / {c['development_groups']}</strong><span>开发图 / 来源组</span></div><div><strong>{c['sealed_images']} / {c['sealed_groups']}</strong><span>新留出图 / 来源组</span></div></div></header>
<nav><a href="#scores">结果与分母</a><a href="#absence">误输出</a><a href="#candidate">候选区域</a><a href="#training">训练记录</a><a href="#patch">补丁状态</a><a href="#scope">复现边界</a></nav>
<div class="notice"><strong>开发回放：正确 {before['correct']} → {after['correct']} / {after['labelled']} 个已标值；新来源冻结端到端：{sb['correct']} → {so['correct']} / {so['labelled']}。</strong><br>截图识别成绩不是第一名概率，也不证明实战吃鸡收益。未启用的学习候选不能解释主表中的变化。</div>
<section id="scores"><div class="eyebrow">01 / TWO EVALUATION PROTOCOLS</div><h2>开发回放和新留出，分别判断</h2><p><b>开发：</b>回放实际历史whole OCR缓存，执行当前后处理及必要HUD局部OCR，不重跑全图OCR；用于开发诊断，不作为统一端到端OCR基准。<b>新留出：</b>冻结后实际执行OCR及后处理，前后核验冻结清单，属于本轮新来源组端到端评测。</p>{table(['数据角色','玩法','版本','图数','已标值N','正确','错误','弃答','覆盖率','已答精确率'], score_rows)}<p class="help">N包括四种标量及有人工真值的商店槽。null或缺失标签不计正确，已标注但无输出计弃答；明确标为空的商店槽无输出仍按评测器记弃答。覆盖率＝（正确＋错误）/ N；已答精确率＝正确/（正确＋错误），零回答显示“—”。少量全对不代表总体100%。</p><details><summary>展开逐字段、商店槽位</summary>{table(['角色','版本','字段','N','正确','错误','弃答'], field_rows)}</details><div class="links">{links}</div></section>
<section id="absence"><div class="eyebrow">02 / EXPLICIT ABSENCE</div><h2>字段不存在，误输出单独检查</h2><p>局外菜单的金橘、奖励数字、卡片生效回合不能充当本局金币或阶段。只对人工明确不存在的当前字段检查，五格全null商店列表视为没有输出，数值0属于实际输出。</p>{table(['角色','玩法','版本','有明确不存在标注的图','字段检查','误输出'], absence_rows)}<p class="help">正确不输出单列，不混入主表正字段正确数；未知字段不自动变成负例。</p><details><summary>展开误输出记录</summary>{table(['角色','版本','图片ID','字段','实际输出'], false_rows) if false_rows else '<p>本次明确不存在字段检查没有记录到误输出。</p>'}</details></section>
<section id="candidate"><div class="eyebrow">03 / PARTIAL ENTITY DIAGNOSTICS</div><h2>局部候选命中，不冒充精确率</h2><p>优先使用card_boxes，否则使用labels.entities的有框注记。候选ID和区域位置同时匹配才计局部命中；卡册、预设及奖励中的卡片命中不表示已携带进本局。</p>{table(['角色','玩法','版本','有框图','标注区域','区域内同ID','同ID出现在图中','无框未计'], candidate_rows)}<p class="help">注记未穷尽所有实体，因此既不是候选精确率，也不是完整召回率。逐项区域、候选ID和证据保存在summary.json中。</p></section>
<section id="training"><div class="eyebrow">04 / CANDIDATES REMAIN DISABLED</div><h2>真实拟合，也报告未达门槛</h2>{table(['学习候选','实际fit行','复用验证N','正确','错误','弃答','本图缺席：正确不输出','误输出','生产状态'], training_rows)}<p>原受控实验与上下文、重复监督修复后的结果均为5正确/0错误/5弃答；最终V4为2/0/8。V4恢复了12条被过窄数字框漏掉的真实监督行，不能当作新增12项识别正确。它只有等级字段通过保守校准输出，整体覆盖并未超过原受控候选。</p><p>这些都是OCR行到stage/gold/hp/level/other的分类模型，数值必须从OCR原文解析。验证集被多个候选反复查看，只算开发验证；至少20次回答、98%精确率及来源组、单玩法门槛保持不变。所有候选deployable=false，未复制为生产活动模型；本轮HUD规则改进不能归因于学习候选已部署。</p><p>本轮新增正区域与明确负区域反馈协议，未知不作other；训练和推理共用OCR上下文，去重监督并按来源校准。这是数据质量及训练通道改进，不是已证明的实战收益。</p><div class="links"><a href="../../training/round3/README.md">完整训练审计与复现 ↗</a><a href="../../training/round3/final_summary.json">四候选机器可读摘要 ↗</a><a href="../../training/round3/expanded_v4/model/training_report.json">最终V4实际训练报告 ↗</a></div></section>
<section id="patch"><div class="eyebrow">05 / PATCH WATCH</div><h2>已公告的新补丁，不能静默套旧规则</h2><p>官方已公告18.6a，官方CDN静态资料尚未同步；本地规则资料口径仍为18.6。较新补丁输入被blocked，不把旧静态数据冒称18.6a已验证。本次公开截图的服别与拍摄补丁并不统一，也不能证明当前正式服准确率。</p><div class="links"><a href="patch-audit.md">补丁核查说明 ↗</a><a href="patch-audit.json">补丁核查原始记录 ↗</a></div></section>
<section><div class="eyebrow">06 / CONFIRMATION GUARDS</div><h2>识别后仍需确认，个人概率保持空值</h2>{table(['角色','版本','有状态结果','保持未确认','明确空个人概率','契约失败','运行错误'], safety_rows)}<p>未确认局面不得被视作已验证状态；有阵容候选时应返回needs_confirmation，缺信息可返回insufficient_data。契约通过不证明阵容推荐产生因果收益。</p></section>
<section id="scope"><div class="eyebrow">07 / REPRODUCIBILITY</div><h2>冻结、来源与可复现记录</h2><p>冻结时间：{esc(frozen)}。新留出{c['sealed_images']}图来自{c['sealed_groups']}个与开发集不重叠的来源组，paired报告绑定冻结清单，并在评测前后核验。来源组不是独立对局、作者或素材独立性的保证。</p><ul>{limitations}</ul><p>逐图延时仅记录本次运行，不计算“快了几倍”。开发回放与新留出的协议不同，也不合并为一个端到端准确率。开发任务中断后，44份已完成原始结果保持原样，仅按相同代码与标签补齐最后1图。</p><details><summary>查看服别、拍摄补丁与输入指纹</summary><pre>{source_json}</pre></details><div class="links"><a href="summary.json">完整summary.json ↗</a><a href="all-annotations.json">52图标签、来源与校验值 ↗</a><a href="live-smoke.json">实际HTTP流程 ↗</a><a href="FREEZE.json">冻结清单 ↗</a><a href="corpus_audit.md">语料与去重审计 ↗</a></div></section>
<footer>金铲铲截图专家系统 · 2026-11-12 · 报告不嵌入来源截图大图</footer>'''
    css = """:root{font:15px/1.85 system-ui,-apple-system,'Noto Sans SC',sans-serif;color:#25383c;background:#f3f5f1}*{box-sizing:border-box}body{margin:0}main{max-width:1450px;margin:auto;padding:49px 38px}a{color:#246e57;text-decoration:none}a:hover{text-decoration:underline}.eyebrow{font-size:10px;letter-spacing:2px;color:#71887b;font-weight:700}h1{font-size:clamp(35px,5vw,60px);line-height:1.25;letter-spacing:-1.7px;margin:21px 0}header>p{font-size:17px;max-width:850px}h2{font-size:27px;line-height:1.5;margin:12px 0 20px}p{color:#607267}.badges,.links,nav{display:flex;flex-wrap:wrap;gap:12px}.badges span{font-size:11px;border:1px solid #c7d5c8;border-radius:5px;padding:5px 9px;color:#52715f}.numbers{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-top:34px;padding:23px 0;border-block:1px solid #ccd8ce}.numbers strong{display:block;font-size:36px;line-height:1.4;font-weight:600}.numbers span{color:#7f9184;font-size:12px}nav{font-size:12px;gap:22px;padding:23px 0}.notice{border:1px solid #d4c693;background:#f3ecd5;color:#7b6531;border-radius:9px;padding:18px 20px}section{padding-top:39px;scroll-margin-top:20px}.scroll{overflow:auto;background:#fff;border:1px solid #ccd8ce;border-radius:8px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12px}th,td{padding:12px 13px;border-bottom:1px solid #e3eae2;text-align:left}th{background:#e5eee6;color:#54735e;font-weight:600}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#f8faf6}.help{font-size:12px;color:#7a8c7e}details{margin-top:18px;border:1px solid #d3dfd3;border-radius:7px;padding:14px 17px}summary{font-size:13px;cursor:pointer;color:#57745e}details .scroll{margin-top:16px}.links{gap:19px;font-size:12px;margin-top:21px}li{color:#687d6d;margin-bottom:9px}pre{font-size:11px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere;color:#697d6d}footer{padding-top:35px;margin-top:37px;border-top:1px solid #d1ded2;color:#8b9b8e;font-size:11px}@media(max-width:720px){main{padding:29px 18px}.numbers{grid-template-columns:1fr 1fr}.numbers strong{font-size:30px}h2{font-size:23px}.notice{font-size:13px}header>p{font-size:15px}nav{gap:12px}}"""
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{c["images"]}张真实截图 · 第三轮冻结评测与训练记录</title><style>{css}</style></head><body><main>{body}</main></body></html>'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-paired", type=Path, required=True)
    parser.add_argument("--development-annotations", type=Path, required=True)
    parser.add_argument("--sealed-paired", type=Path, required=True)
    parser.add_argument("--sealed-annotations", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT/"validation/round3-2026-11-12")
    parser.add_argument("--training-summary", type=Path, default=PROJECT/"training/round3/final_summary.json")
    parser.add_argument("--patch-audit", type=Path)
    args = parser.parse_args(argv)
    args.patch_audit = args.patch_audit or args.output/"patch-audit.json"
    summary = build_summary(args)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output/"index.html").write_text(render(summary), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "corpus": summary["corpus"], "complete": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"无法生成完整第三轮报告：{exc}", file=sys.stderr)
        raise SystemExit(2)
