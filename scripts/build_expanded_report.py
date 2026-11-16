#!/usr/bin/env python3
"""Build an honest static summary from completed paired screenshot evaluations.

Does not run recognition, change annotations, copy source screenshots, or train.
Both paired folders must contain baseline/report.json and optimized/report.json.
Root copies their per-image HTML/raw results into the corresponding output paths.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = ("baseline", "optimized")
MODES = ("nature", "orange")
SCALARS = ("stage", "gold", "hp", "level")
CN_MODE = {"nature": "自然之力", "orange": "大橘大利", "all": "全部"}
CN_SPLIT = {"development": "开发集（已消费）", "sealed": "新来源组留出"}
CN_REV = {"baseline": "基线 v0.1.1", "optimized": "冻结优化版"}


def read_json(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"评测尚未就绪，缺少：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def has_output(value):
    """A five-slot list of null is empty; numeric 0 is a real output."""
    if value is None:
        return False
    if isinstance(value, list):
        return any(has_output(v) for v in value)
    if isinstance(value, dict):
        return any(has_output(v) for v in value.values())
    if isinstance(value, str):
        return bool(value.strip())
    return True


def metrics(runs):
    outcomes = [o for run in runs for o in run.get("outcomes", [])]
    counts = Counter(o["outcome"] for o in outcomes)
    labelled = sum(counts[k] for k in ("correct", "wrong", "abstain"))
    answered = counts["correct"]+counts["wrong"]
    return {"images": len(runs), "source_groups": len({r["group_id"] for r in runs}),
            "labelled": labelled, "correct": counts["correct"], "wrong": counts["wrong"],
            "abstain": counts["abstain"], "unlabelled": counts["unlabelled"],
            "coverage": answered/labelled if labelled else None,
            "precision": counts["correct"]/answered if answered else None,
            "end_to_end_correct_rate": counts["correct"]/labelled if labelled else None,
            "recognition_errors": sum(r.get("status") == "error" for r in runs),
            "safety_contract_failures": sum(r.get("contract_check", {}).get("passed") is False for r in runs)}


def valid_box(box):
    return isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box) and min(box[2:]) > 0


def in_region(candidate, region):
    if not valid_box(candidate) or not valid_box(region):
        return False
    x,y,w,h=candidate; a,b,c,d=region
    area=max(0.,min(x+w,a+c)-max(x,a))*max(0.,min(y+h,b+d)-max(y,b))
    return (a<=x+w/2<=a+c and b<=y+h/2<=b+d) or area/(w*h)>=.5


def labelled_regions(sample):
    rows = sample.get("card_boxes") or sample.get("labels", {}).get("entities", [])
    regions, seen, unlocalized = [], set(), 0
    for row in rows:
        if not isinstance(row, dict): continue
        entity_id = row.get("entity_id") or row.get("card_id") or row.get("id")
        kind = row.get("entity_type") or row.get("kind") or "card"
        box = row.get("bbox") or row.get("object_bbox") or row.get("title_bbox")
        if not entity_id: continue
        if not valid_box(box):
            unlocalized += 1; continue
        key = (str(entity_id), tuple(box))
        if key in seen: continue
        seen.add(key)
        regions.append({"entity_id": str(entity_id), "kind": kind, "name": row.get("name"), "bbox": box})
    return regions, unlocalized


def diagnostics(samples, runs, folder):
    by_id={s["id"]:s for s in samples}
    absence=Counter(); absent_field=defaultdict(Counter); absent_records=[]
    candidates=Counter(); candidate_records=[]; safety=Counter()
    for run in runs:
        sample=by_id[run["sample_id"]]
        raw=read_json(folder/run["raw_file"]) if run.get("raw_file") else {}
        recognition=raw.get("recognition", {}); state=recognition.get("state")
        if not isinstance(state, dict):
            absence["state_unavailable_images"]+=1
            continue
        safety["states"]+=1
        safety["unconfirmed"]+=state.get("confirmed") is False
        model=raw.get("probability_model", {})
        recommendation=raw.get("recommendation", {})
        safety["null_personal_probability"]+=("state_probability" in model and model["state_probability"] is None and "state_probability" in recommendation and recommendation["state_probability"] is None)
        safety["recommendation:"+str(recommendation.get("status", "unknown"))]+=1
        absent=(set(sample.get("expected_absent_current_state_fields", []))
                | set(sample.get("known_absent_fields", [])) | set(sample.get("absent_fields", [])))
        if absent: absence["images_with_explicit_absence"]+=1
        image_bad=False
        for field in sorted(absent):
            absence["field_checks"]+=1; absent_field[field]["checks"]+=1
            bad=has_output(state.get(field))
            absence["false_outputs"]+=bad; absent_field[field]["false_outputs"]+=bad
            if bad:
                image_bad=True
                absent_records.append({"sample_id":sample["id"],"field":field,"output":state.get(field)})
        absence["images_with_false_output"]+=image_bad
        regions, unlocalized=labelled_regions(sample)
        candidates["unlocalized_annotations_excluded"]+=unlocalized
        if regions: candidates["annotated_images"]+=1
        evidence=[e for e in recognition.get("evidence", []) if isinstance(e, dict) and e.get("entity_id") and valid_box(e.get("bbox"))]
        for region in regions:
            candidates["labelled_regions"]+=1
            local=[e for e in evidence if in_region(e["bbox"],region["bbox"]) and (not e.get("entity_type") or e["entity_type"]==region["kind"])]
            hit=any(str(e["entity_id"])==region["entity_id"] for e in local)
            elsewhere=any(str(e["entity_id"])==region["entity_id"] for e in evidence)
            candidates["same_id_in_region"]+=hit
            candidates["same_id_anywhere"]+=elsewhere
            candidates["region_has_any_candidate"]+=bool(local)
            candidate_records.append({"sample_id":sample["id"],"entity_id":region["entity_id"],"name":region["name"],"expected_bbox":region["bbox"],"same_id_in_region":hit,"same_id_anywhere":elsewhere,"candidate_ids_in_region":sorted({str(e["entity_id"])for e in local}),"candidate_evidence_in_region":[{k:e.get(k)for k in ['entity_id','entity_type','name','text','bbox','kind','confidence']}for e in local]})
    return {"explicit_absence":{**dict(absence),"per_field":{k:dict(v)for k,v in absent_field.items()},"records":absent_records},
            "incomplete_candidate_diagnostic":{**dict(candidates),"records":candidate_records,"is_precision":False,"is_full_recall":False},
            "safety":dict(safety)}


def load_pair(folder, annotations, freeze_sha, require_freeze=False, frozen_modules=None):
    folder=Path(folder); folder=folder.parent if folder.is_file() else folder
    annotation=read_json(annotations); samples=annotation.get("samples", [])
    by_id={s["id"]:s for s in samples}
    if len(by_id)!=len(samples):raise ValueError("标注图片ID重复")
    pair={}
    for revision in REVISIONS:
        report_file=folder/revision/"report.json"; report=read_json(report_file)
        if report["metadata"]["annotations_sha256"]!=digest(annotations):raise ValueError("结果与当前标注SHA不一致")
        bound=report["metadata"].get("freeze_sha256")
        if bound is not None and bound!=freeze_sha:raise ValueError("结果绑定的冻结清单不一致")
        if require_freeze and bound!=freeze_sha:raise ValueError("新来源组留出结果未绑定指定冻结清单")
        runs=[r for r in report["runs"] if r.get("track")=="default"]
        if len(runs)!=len(samples) or {r["sample_id"]for r in runs}!=set(by_id):raise ValueError("paired结果尚未完整或图片ID不同")
        if report["metadata"].get("default_only") is not True:raise ValueError("主表仅接受默认识别，无人工区域")
        measured=metrics(runs); reported=report["tracks"]["default"]
        for key in ["correct","wrong","abstain","labelled"]:
            if measured[key]!=reported[key]:raise ValueError(f"{revision} {key}不能从逐图分布复算")
        detail={"all":{**measured,**diagnostics(samples,runs,folder/revision)}}
        for mode in MODES:
            selected=[r for r in runs if r["mode"]==mode]
            detail[mode]={**metrics(selected),**diagnostics(samples,selected,folder/revision)}
        per_field={}
        for field in (*SCALARS,*(f"shop[{i}]"for i in range(5))):
            field_runs=[dict(r,outcomes=[o for o in r.get("outcomes",[])if o["field"]==field])for r in runs]
            per_field[field]=metrics(field_runs)
        recorded_module=report["metadata"].get("recognizer_module")
        matches=bool(frozen_modules and frozen_modules.get(recorded_module)==report["metadata"].get("recognizer_sha256"))
        pair[revision]={"by_mode":detail,"per_field":per_field,"metadata":report["metadata"],"report_sha256":digest(report_file),"recognizer_matches_frozen_source":matches}
    comparison=read_json(folder/"comparison.json")
    if require_freeze and comparison.get("freeze_verified_before_and_after") is not True:
        raise ValueError("新来源组留出paired报告未确认评测前后冻结核验")
    return {"images":len(samples),"source_groups":len({s["group_id"]for s in samples}),"revisions":pair,
            "freeze_verified_before_and_after":comparison.get("freeze_verified_before_and_after") is True},samples


def build_summary(args):
    freeze=read_json(args.freeze); freeze_sha=digest(args.freeze)
    frozen_modules={row['file']:row['sha256']for row in freeze.get('files',[])}
    dev, dev_samples=load_pair(args.development_paired,args.development_annotations,freeze_sha,False,frozen_modules)
    sealed, sealed_samples=load_pair(args.sealed_paired,args.sealed_annotations,freeze_sha,True,frozen_modules)
    ids_dev={s["id"]for s in dev_samples}; ids_sealed={s["id"]for s in sealed_samples}
    groups_dev={s["group_id"]for s in dev_samples}; groups_sealed={s["group_id"]for s in sealed_samples}
    if ids_dev&ids_sealed or groups_dev&groups_sealed:raise ValueError("开发与新来源组留出存在ID或来源组重叠")
    corpus={"images":len(dev_samples)+len(sealed_samples),"source_groups":len(groups_dev|groups_sealed),
            "development_images":len(dev_samples),"development_groups":len(groups_dev),
            "sealed_images":len(sealed_samples),"sealed_groups":len(groups_sealed)}
    expected={"images":38,"source_groups":11,"development_images":27,"development_groups":7,"sealed_images":11,"sealed_groups":4}
    if corpus!=expected:raise ValueError(f"本轮语料数量与冻结计划不同：{corpus}")
    field=read_json(args.field_training_report); roman=read_json(args.roman_report)
    field_summary={k:field.get(k)for k in ["status","deployable","n_supervised_rows","n_training_rows","supervised_class_counts","group_partitions","validation_metrics","target_precision","min_validation_answers","experiment","artifact_sha256"]}
    roman_summary={k:roman.get(k)for k in ["status","real_counts","source_group_split","synthetic_counts","synthetic_validation","real_training_evaluation","real_group_validation"]}
    # Do not re-publish per-title training crops or their original screenshots.
    for key in ["real_training_evaluation","real_group_validation"]:
        if isinstance(roman_summary.get(key),dict):roman_summary[key]={k:v for k,v in roman_summary[key].items()if k!="records"}
    samples=dev_samples+sealed_samples
    dev_base=dev['revisions']['baseline']['by_mode']['all'];dev_opt=dev['revisions']['optimized']['by_mode']['all']
    sealed_base=sealed['revisions']['baseline']['by_mode']['all'];sealed_opt=sealed['revisions']['optimized']['by_mode']['all']
    return {"schema_version":"1.0","date":"2026-11-11","created_at":datetime.now(timezone.utc).isoformat(),
            "corpus":corpus,"splits":{"development":dev,"sealed":sealed},"freeze":{"frozen_at":freeze.get("frozen_at"),"sha256":freeze_sha},
            "source_scope":{"server_status_counts":dict(Counter(str(s.get("server_status","unknown"))for s in samples)),"capture_patch_counts":dict(Counter(str(s.get("patch"))for s in samples)),"formal_patch_18_6_validation":False},
            "training":{"field":field_summary,"roman":roman_summary,"candidates_enabled":False,"winrate_training_performed":False},
            "observed_deltas":{"development_correct":dev_opt['correct']-dev_base['correct'],"sealed_correct":sealed_opt['correct']-sealed_base['correct'],"sealed_wrong":sealed_opt['wrong']-sealed_base['wrong'],"sealed_coverage":sealed_opt['coverage']-sealed_base['coverage']},
            "definitions":{"metrics_scope":"stage/gold/hp/level四个标量及五个有人工标注的商店槽值；缺失/null标签不计正确。",
                           "coverage":"(correct+wrong)/(correct+wrong+abstain)","precision":"correct/(correct+wrong)，须与样本量及弃答共同呈现。",
                           "absence":"仅明确标记不存在的当前字段做误输出检查；[null,null,null,null,null]视为无商店输出，0视为已输出数值。",
                           "candidate_hit":"有框的不完整人工注记中，主候选ID相同且候选中心落框内或至少一半候选面积在框内；每个标注区域最多计1次。",
                           "candidate_not_precision":"没有穷尽标注；该诊断既不是候选精确率，也不是完整召回率，不等同于实际携带的卡片。",
                           "new_source_holdout":"新来源组留出，不是独立对局或独立作者证明。共享媒体素材及同一录像不能排除。"},
            "limitations":["语料含测试服、体验文章、低分辨率及弹层截图，不能当作正式服18.6实机准确率验证。",
                           "开发集已消费；新来源组留出在冻结实现后首次评测，本轮不按其结果调参。",
                           "开发评测早于冻结启动、未传freeze，不能称开发运行前后冻结核验；新来源组留出传入了冻结清单并完成前后核验。",
                           "语料无精确重复且来源组不跨开发/留出；pHash≤12仍有4对跨角色相似UI，SSIM不能证明同帧，共享媒体素材或录像无法排除。",
                           "来源组数不是独立对局数，截图正确率不是第一率提升。当前没有胜率训练或前瞻吃鸡收益验证。",
                           "两支监督学习候选均未启用；主表整体差异不能归因于候选模型已经部署。",
                           "paired评测共用固定OCR运行时，但启动、预处理与缓存路径不同；延迟不作速度提升或公平性能比较。"],
            "timing_comparison_eligible":False,
            "provenance":{"development_annotations_sha256":digest(args.development_annotations),"sealed_annotations_sha256":digest(args.sealed_annotations),
                          "field_training_report_sha256":digest(args.field_training_report),"roman_report_sha256":digest(args.roman_report),
                          "corpus_audit_sha256":digest(args.corpus_audit)if args.corpus_audit.is_file()else None,"builder_sha256":digest(__file__)}}


def render(summary):
    esc=lambda x:html.escape(str(x),quote=True)
    pct=lambda x:"—"if x is None else f"{x*100:.1f}%"
    def table(headers,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join(f'<th>{esc(x)}</th>'for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{esc(x)}</td>'for x in row)+'</tr>'for row in rows)+'</tbody></table></div>'
    rows=[];absent_rows=[];candidate_rows=[];field_rows=[]
    for split,pair in summary["splits"].items():
        for mode in ["all",*MODES]:
            for revision in REVISIONS:
                m=pair["revisions"][revision]["by_mode"][mode]
                rows.append([CN_SPLIT[split],CN_MODE[mode],CN_REV[revision],m["images"],m["labelled"],m["correct"],m["wrong"],m["abstain"],pct(m["coverage"]),pct(m["precision"])])
                a=m["explicit_absence"];c=m["incomplete_candidate_diagnostic"]
                absent_rows.append([CN_SPLIT[split],CN_MODE[mode],CN_REV[revision],a.get("images_with_explicit_absence",0),a.get("field_checks",0),a.get("false_outputs",0),a.get("images_with_false_output",0)])
                candidate_rows.append([CN_SPLIT[split],CN_MODE[mode],CN_REV[revision],c.get("annotated_images",0),c.get("labelled_regions",0),c.get("same_id_in_region",0),c.get("same_id_anywhere",0),c.get("unlocalized_annotations_excluded",0)])
        for revision in REVISIONS:
            for name,m in pair["revisions"][revision]["per_field"].items():
                field_rows.append([CN_SPLIT[split],CN_REV[revision],name,m["labelled"],m["correct"],m["wrong"],m["abstain"],pct(m["coverage"])])
    field=summary["training"]["field"];roman=summary["training"]["roman"];v=field.get("validation_metrics",{})
    db=summary['splits']['development']['revisions']['baseline']['by_mode']['all'];do=summary['splits']['development']['revisions']['optimized']['by_mode']['all']
    sb=summary['splits']['sealed']['revisions']['baseline']['by_mode']['all'];so=summary['splits']['sealed']['revisions']['optimized']['by_mode']['all']
    observed=f"开发集正确值从{db['correct']}增至{do['correct']} / {do['labelled']}个已标注值；新来源组留出为{sb['correct']}→{so['correct']} / {so['labelled']}，本轮未观察到新增正确值。" if sb['correct']==so['correct'] else f"开发集正确值{db['correct']}→{do['correct']} / {do['labelled']}；新来源组留出正确值{sb['correct']}→{so['correct']} / {so['labelled']}。"
    rr=roman.get("real_counts",{});sr=roman.get("synthetic_counts",{});rv=roman.get("real_group_validation",{})
    frozen=datetime.fromisoformat(summary["freeze"]["frozen_at"]).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S 北京时间")
    links=''.join(f'<a href="{split}/{rev}/report.html">{esc(CN_SPLIT[split])} · {esc(CN_REV[rev])}逐图结果 ↗</a>'for split in summary['splits']for rev in REVISIONS)
    safety=[];false_cases=[]
    for split,pair in summary['splits'].items():
        for rev in REVISIONS:
            m=pair['revisions'][rev]['by_mode']['all'];s=m['safety']
            safety.append([CN_SPLIT[split],CN_REV[rev],s.get('states',0),s.get('unconfirmed',0),s.get('null_personal_probability',0),m['safety_contract_failures'],m['recognition_errors']])
            for r in m['explicit_absence']['records']:false_cases.append([CN_SPLIT[split],CN_REV[rev],r['sample_id'],r['field'],json.dumps(r['output'],ensure_ascii=False)])
    body=f'''<section class="hero"><div class="eyebrow">JCC · FROZEN EVALUATION / 2026.11.11</div><h1>把正确、错误和弃答<br>一起放进报告。</h1><p>38张真实公开界面，按来源保留开发与新留出。报告比较冻结的基线和优化版；学习候选保留为研究工件。</p><div class="badges"><span>默认识别 · 无人工ROI</span><span>两支训练候选未启用</span><span>非正式服18.6验证</span></div><div class="numbers"><div><strong>38</strong><span>真实截图</span></div><div><strong>11</strong><span>来源组</span></div><div><strong>27 / 7</strong><span>开发图 / 组</span></div><div><strong>11 / 4</strong><span>新留出图 / 组</span></div></div></section>
    <nav><a href="#scores">主结果</a><a href="#absence">不存在字段</a><a href="#candidates">候选区域诊断</a><a href="#training">真实训练</a><a href="#scope">边界与复现</a></nav>
    <div class="notice"><strong>{esc(observed)}</strong><br>本报告衡量截图识别。第一名概率和吃鸡收益没有在这批截图上训练或验证。新来源组留出也不是独立对局、独立作者或媒体素材独立性的证明。</div>
    <section id="scores"><div class="eyebrow">01 / VALUES & DENOMINATORS</div><h2>先看分母，再看覆盖率</h2><p>已标注值包括四种标量及有人工标签的五格商店；null标签不计正确，已标注但无输出计弃答。开发集已被反复使用，请优先单独阅读新来源组留出。</p>{table(['数据角色','玩法','版本','图片','已标注值N','正确','错误','弃答','覆盖率','已答精确率'],rows)}<p class="help">覆盖率＝（正确＋错误）/ N；已答精确率＝正确/（正确＋错误）。零回答时精确率为“—”。不能用大量弃答换来的少量全对宣称总体100%。</p><details><summary>逐字段与商店槽位</summary>{table(['角色','版本','字段','N','正确','错误','弃答','覆盖率'],field_rows)}</details><div class="report-links">{links}</div></section>
    <section id="absence"><div class="eyebrow">02 / FALSE OUTPUTS</div><h2>局外字段不存在，输出也要被检查</h2><p>仅对人工明确标记不存在的当前字段做单独诊断。局外金橘、卡片生效回合和奖励价值不能作为当前金币或回合；五格全null列表视为无商店输出，数值0属于实际输出。</p>{table(['角色','玩法','版本','有明确缺席标注的图','字段检查数','误输出数','发生误输出的图'],absent_rows)}<p class="help">这些正确拒绝不加入主表的正字段正确数。未标注字段也没有被自动当作负例。</p><details><summary>展开误输出逐项记录（如有）</summary>{table(['角色','版本','图片ID','字段','实际输出'],false_cases)if false_cases else '<p>本次明确不存在字段检查中没有记录到误输出。</p>'}</details></section>
    <section id="candidates"><div class="eyebrow">03 / INCOMPLETE ANNOTATIONS</div><h2>候选命中是诊断，不是精确率</h2><p>优先使用card_boxes，否则使用labels.entities中有框的注记。主候选ID一致且位置落入注记区域才计“区域内同ID命中”。卡册、预设或奖励卡片的命中不表示它们已被带入本局。</p>{table(['角色','玩法','版本','有区域注记的图','标注区域数','区域内同ID命中','同ID出现在图中','无框注记未计'],candidate_rows)}<p class="help">标注没有穷尽所有实体，不能计算候选精确率或完整召回率；“未见同ID命中”也不能直接判定整张图识别错误。手工框近似位置会影响此诊断。</p></section>
    <section id="training"><div class="eyebrow">04 / REAL SUPERVISED EXPERIMENTS</div><h2>训练了模型，也保留了未部署结论</h2><div class="training-grid"><article><span class="tag">字段分类 · {esc(field.get('status'))}</span><h3>OCR行 → stage / gold / hp / level / other</h3><p>25张开发图提供{field.get('n_supervised_rows')}条可靠监督行；V3实际拟合{field.get('n_training_rows')}行，其中stage14、gold9、hp2、level13、other82。DictVectorizer和逻辑回归权重已保存。</p><p>复用开发验证6字段：{v.get('correct')}正确 / {v.get('wrong')}错误 / {v.get('abstain')}弃答，仅stage回答2/2；20次明确不存在字段的正确拒绝单列。验证第三次复用，不是新的独立最终证据。</p><p>每模式至少20次验证回答和98%精确率等门槛未过；deployable=false。目标值仍须由OCR原文解析，模型分数不是胜率。</p><a href="../../training/field-v3/training_report.json">字段训练原始报告 ↗</a><a href="../../training/field_training_audit.md">字段训练审计 ↗</a></article><article><span class="tag">罗马数字 · {esc(roman.get('status'))}</span><h3>时间卡标题的I—V后缀候选</h3><p>真实拟合裁片{rr.get('train')}个、真实开发验证{rr.get('validation')}个；另有{sr.get('train')}个合成拟合字形和{sr.get('validation')}个合成验证字形。两类数量分开，不能写成600张真实截图。</p><p>真实拟合仅I两例、II一例，全部来自同一截图；真实开发验证只有I一例。另2个同卡名跨组裁片已剔除。合成验证72/120，衡量理想裁片分类，不能替代完整截图识别。</p><p>五个one-vs-rest线性SVM已保存。真实覆盖不足、II拟合例仍会弃答；approved_for_use=false、safe_to_apply=false，不自动校正卡片ID。</p><a href="../../training/card-tier-candidate/report.json">罗马数字训练报告 ↗</a><a href="../../training/card_training_audit.md">罗马数字训练审计 ↗</a></article></div><p class="help">两支候选均未启用，因此主表整体改善不能归因为候选模型已投入使用。本轮没有胜率模型训练。</p></section>
    <section><h2>未确认状态与个人概率守卫</h2>{table(['角色','版本','有状态结果','保持未确认','明确空个人概率','契约失败','识别运行错误'],safety)}<p>无来牌时可返回insufficient_data；有候选且未确认时返回needs_confirmation。守卫通过不等于阵容推荐有因果收益。</p></section>
    <section id="scope"><div class="eyebrow">05 / SCOPE & REPRODUCIBILITY</div><h2>如何理解这次新来源组留出</h2><p>冻结时间：{esc(frozen)}。11张新留出来自4个此前未用于本轮训练调参的来源组；新留出的配对运行在前后核验冻结清单。开发运行早于冻结启动，未传freeze，单独记录这一差别。本轮看完新留出结果后，未修改冻结的识别算法、阈值或候选权重。</p><ul>{''.join('<li>'+esc(x)+'</li>'for x in summary['limitations'])}</ul><p>语料审计无精确重复、无同来源组跨角色；pHash≤12有4对相似UI，SSIM不能确认同帧。仍无法排除不同发布者共享媒体素材或同一录像。<a href="corpus_audit.md">查看语料审计 ↗</a></p><p>本轮两个revision共用固定OCR运行时；启动、预处理和缓存路径不一致，不能从延迟差额计算“快了几倍”。逐图延时仅作当次运行记录。</p><details><summary>来源服别、补丁与输入指纹</summary><pre>{esc(json.dumps({'source_scope':summary['source_scope'],'freeze':summary['freeze'],'provenance':summary['provenance']},ensure_ascii=False,indent=2))}</pre></details><div class="report-links"><a href="summary.json">完整summary.json ↗</a><a href="FREEZE.json">冻结清单 ↗</a><a href="all-annotations.json">38图标签、来源与图片校验值 ↗</a><a href="live-smoke.json">实际HTTP验证记录 ↗</a><a href="../../training/">训练工件目录 ↗</a></div></section><footer>金铲铲截图专家系统 · 2026-11-11 · 不嵌入来源截图大图</footer>'''
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>38张真实截图 · 冻结评测与训练记录</title><style>
    :root{font:15px/1.85 system-ui,-apple-system,'Noto Sans SC',sans-serif;color:#25363c;background:#f1f4f1}*{box-sizing:border-box}body{margin:0}main{max-width:1410px;margin:auto;padding:50px 38px}a{color:#276c55;text-decoration:none}a:hover{text-decoration:underline}.hero{padding-bottom:22px}.eyebrow{font-size:10px;letter-spacing:2px;color:#6c847a;font-weight:700}h1{font-size:clamp(33px,5vw,59px);line-height:1.25;letter-spacing:-1.5px;margin:21px 0}h2{font-size:27px;line-height:1.5;margin:12px 0 20px}h3{font-size:19px;line-height:1.6}p{color:#607269}.hero>p{max-width:790px;font-size:17px}.badges{display:flex;flex-wrap:wrap;gap:9px;margin-top:22px}.badges span,.tag{display:inline-block;border:1px solid #c4d3c7;border-radius:5px;padding:5px 9px;color:#4f6c5c;font-size:11px}.numbers{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-top:35px;padding:23px 0;border-top:1px solid #cdd8ce;border-bottom:1px solid #cdd8ce}.numbers strong{font-size:36px;font-weight:600;display:block;line-height:1.4}.numbers span{color:#7e8e82;font-size:12px}nav{display:flex;gap:20px;flex-wrap:wrap;padding:12px 0 25px;font-size:12px}.notice{border:1px solid #d6c797;background:#f3ecd6;padding:17px 20px;border-radius:9px;color:#806a34}section{padding-top:38px;scroll-margin-top:20px}.scroll{overflow:auto;border:1px solid #ccd8ce;border-radius:8px;background:#fff}table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}th,td{padding:12px 14px;text-align:left;border-bottom:1px solid #e3e9e3}th{background:#e5eee7;color:#53735c;font-weight:600}tbody tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#f8faf7}.help{font-size:12px;color:#869287;line-height:1.9}details{margin-top:18px;border:1px solid #d4dfd4;border-radius:7px;padding:14px 17px}summary{cursor:pointer;font-size:13px;color:#57725d}details .scroll{margin-top:15px}.report-links{display:flex;gap:19px;flex-wrap:wrap;font-size:12px;margin-top:21px}.training-grid{display:grid;grid-template-columns:1fr 1fr;gap:23px}.training-grid article{padding:25px;border:1px solid #ccd9cd;background:#fff;border-radius:11px}.training-grid p{font-size:14px}.training-grid a{display:block;font-size:12px;margin-top:10px}li{color:#687c6d;margin-bottom:9px}pre{font-size:11px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere;color:#697b6e}footer{font-size:11px;color:#92a095;padding-top:40px;margin-top:38px;border-top:1px solid #d3ddd2}@media(max-width:700px){main{padding:30px 19px}.numbers{grid-template-columns:1fr 1fr;gap:20px}.training-grid{grid-template-columns:1fr}h2{font-size:23px}.hero>p{font-size:15px}nav{gap:12px}.numbers strong{font-size:29px}.notice{font-size:13px}.training-grid article{padding:20px}}
    </style></head><body><main>'''+body+'''</main></body></html>'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-paired",type=Path,required=True)
    parser.add_argument("--development-annotations",type=Path,required=True)
    parser.add_argument("--sealed-paired",type=Path,required=True)
    parser.add_argument("--sealed-annotations",type=Path,required=True)
    parser.add_argument("--field-training-report",type=Path,default=ROOT/"training/field-v3/training_report.json")
    parser.add_argument("--roman-report",type=Path,default=ROOT/"training/card-tier-candidate/report.json")
    parser.add_argument("--corpus-audit",type=Path,default=Path("work/expanded_eval/corpus_audit.md"))
    parser.add_argument("--freeze",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"validation/expanded-screens-2026-11-11")
    args=parser.parse_args(argv)
    summary=build_summary(args)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (args.output/"index.html").write_text(render(summary),encoding="utf-8")
    print(json.dumps({"output":str(args.output.resolve()),"corpus":summary['corpus'],"complete":True},ensure_ascii=False))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,KeyError)as exc:
        print(f"无法生成完整报告：{exc}",file=sys.stderr)
        raise SystemExit(2)
