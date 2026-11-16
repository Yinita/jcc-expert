#!/usr/bin/env python3
"""Reproducible screenshot evaluation, with abstentions and manual hints explicit.

Example:
  python scripts/evaluate_screenshots.py --annotations /path/annotations.json \
      --output /path/report --recognizer-module /path/vision_baseline.py

Paths in annotations are relative to that JSON file. This tool never downloads,
copies or embeds screenshots in reports, trains a model, or saves training events.
Missing/null labels are unannotated, not correct predictions. A shop null output
is an abstention, not evidence that a slot is empty. To annotate a known empty
slot, use {"empty": true}; it needs an explicit empty prediction to be correct.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import importlib.metadata
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIELDS = ("stage", "gold", "hp", "level", "shop[0]", "shop[1]", "shop[2]", "shop[3]", "shop[4]")
SCALARS = {"gold", "hp", "level"}
TRACK_NAMES = {"default": "默认识别（无人工区域）", "profile": "人工区域辅助识别"}
SPLITS = {"development", "holdout"}
MISSING = object()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_identity(path):
    """Detect exact decoded-image duplicates even after metadata/re-encoding changes."""
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        digest = hashlib.sha256(f"{image.width}x{image.height}:RGB:".encode() + image.tobytes()).hexdigest()
        return digest, {"width": image.width, "height": image.height}


def load_annotations(path):
    annotation_path = Path(path).resolve()
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(samples, list) or not samples:
        raise ValueError("annotations needs a nonempty samples array")
    seen_ids, prepared = set(), []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"sample {index} must be an object")
        sample = dict(sample)
        sample_id = str(sample.get("id", "")).strip()
        if not sample_id or sample_id in seen_ids:
            raise ValueError("Every sample needs a unique nonempty id")
        seen_ids.add(sample_id)
        if sample.get("mode") not in {"nature", "orange"}:
            raise ValueError(f"{sample_id}: mode must be nature or orange")
        if sample.get("split", "development") not in SPLITS:
            raise ValueError(f"{sample_id}: split must be development or holdout")
        sample["file"] = sample.get("file") or sample.get("image_path") or sample.get("path")
        if not isinstance(sample.get("file"), str) or not sample["file"]:
            raise ValueError(f"{sample_id}: file is required")
        file_path = Path(sample["file"])
        if not file_path.is_absolute():
            file_path = annotation_path.parent / file_path
        file_path = file_path.resolve()
        if not file_path.is_file():
            raise ValueError(f"{sample_id}: image file not found: {file_path}")
        labels = sample.get("labels", {})
        if not isinstance(labels, dict):
            raise ValueError(f"{sample_id}: labels must be an object")
        if labels.get("shop") is not None and (not isinstance(labels["shop"], list) or len(labels["shop"]) > 5):
            raise ValueError(f"{sample_id}: labels.shop must have at most five ordered slots")
        # Catch malformed labels before expensive OCR. Unknown values remain absent.
        for field in FIELDS:
            label = get_field(labels, field)
            if label is not MISSING and label is not None:
                normalize_label(label, field)
        if sample.get("layout_profile") is not None and not isinstance(sample["layout_profile"], dict):
            raise ValueError(f"{sample_id}: layout_profile must be an object")
        decoded_sha, size = image_identity(file_path)
        sample.update(id=sample_id, file=str(file_path), labels=labels,
                      split=sample.get("split", "development"), file_sha256=sha256_file(file_path),
                      decoded_image_sha256=decoded_sha, image_size=size,
                      group_id=str(sample.get("group_id") or sample.get("original_id") or f"image:{decoded_sha}"),
                      grouping_explicit=bool(sample.get("group_id") or sample.get("original_id")))
        prepared.append(sample)
    validate_groups(prepared)
    return payload, prepared


def validate_groups(samples):
    """No random image split: all declared original/crop groups stay together."""
    group_splits, image_splits = defaultdict(set), defaultdict(set)
    by_id = {s["id"]: s for s in samples}
    for sample in samples:
        group_splits[sample["group_id"]].add(sample["split"])
        image_splits[sample["decoded_image_sha256"]].add(sample["split"])
        if sample.get("crop_of"):
            parent = by_id.get(str(sample["crop_of"]))
            if parent:
                if sample["group_id"] != parent["group_id"] or sample["split"] != parent["split"]:
                    raise ValueError(f"Crop {sample['id']} must share group_id and split with {parent['id']}")
            elif not sample["grouping_explicit"]:
                raise ValueError(f"Crop {sample['id']} requires explicit group_id for its original source")
    if any(len(values) > 1 for values in group_splits.values()):
        raise ValueError("Original-image group appears in both development and holdout")
    if any(len(values) > 1 for values in image_splits.values()):
        raise ValueError("Exact decoded screenshot appears in both development and holdout")


def get_field(data, field):
    if field.startswith("shop["):
        index = int(field[5:-1])
        shop = data.get("shop")
        return shop[index] if isinstance(shop, list) and index < len(shop) else MISSING
    return data.get(field, MISSING)


def normalize_label(value, field):
    if field.startswith("shop["):
        if isinstance(value, dict):
            if value.get("empty") is True:
                return ("empty",)
            if value.get("hero_id") is not None:
                return ("hero", str(value["hero_id"]))
            raise ValueError(f"Invalid {field} label; use hero ID, null, or {{'empty': true}}")
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return ("hero", str(value))
        raise ValueError(f"Invalid {field} label")
    if field == "stage":
        if isinstance(value, str) and re.fullmatch(r"\d{1,2}-\d{1,2}", value.strip()):
            return value.strip()
        raise ValueError("stage label must be a string such as 3-2")
    if field in SCALARS:
        if isinstance(value, bool):
            raise ValueError(f"{field} label cannot be boolean")
        try:
            number = float(value)
            if math.isfinite(number) and number == int(number) and number >= 0:
                return int(number)
        except (TypeError, ValueError):
            pass
        raise ValueError(f"{field} label must be an integer or null")
    raise ValueError(f"Unsupported field {field}")


def evaluate_fields(labels, state):
    """Return one outcome per possible field; never reward missing ground truth."""
    outcomes = []
    for field in FIELDS:
        expected, predicted = get_field(labels, field), get_field(state, field)
        row = {"field": field, "expected": None if expected is MISSING else expected,
               "predicted": None if predicted is MISSING else predicted,
               "label_present": expected is not MISSING and expected is not None}
        if not row["label_present"]:
            row["outcome"] = "unlabelled"
        elif predicted is MISSING or predicted is None:
            row["outcome"] = "abstain"
        else:
            try:
                normalized_pred = normalize_label(predicted, field)
            except ValueError:
                normalized_pred = ("invalid_prediction", repr(predicted))
            row["outcome"] = "correct" if normalize_label(expected, field) == normalized_pred else "wrong"
        outcomes.append(row)
    return outcomes


def summarize_outcomes(outcomes):
    counts = Counter(row["outcome"] for row in outcomes)
    eligible = counts["correct"] + counts["wrong"] + counts["abstain"]
    answered = counts["correct"] + counts["wrong"]
    return {"labelled": eligible, "correct": counts["correct"], "wrong": counts["wrong"],
            "abstain": counts["abstain"], "unlabelled": counts["unlabelled"], "answered": answered,
            "coverage": answered / eligible if eligible else None,
            "precision": counts["correct"] / answered if answered else None,
            "end_to_end_correct_rate": counts["correct"] / eligible if eligible else None}


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    offset = (len(values) - 1) * fraction
    lo, hi = math.floor(offset), math.ceil(offset)
    return values[lo] + (values[hi] - values[lo]) * (offset - lo)


def summarize_runs(runs):
    executed = [r for r in runs if r["status"] != "not_run_no_profile"]
    outcomes = [o for run in executed for o in run.get("outcomes", [])]
    timings = [r["latency_ms"] for r in executed if r.get("latency_ms") is not None]
    metrics = summarize_outcomes(outcomes)
    metrics.update(samples=len(executed), recognition_errors=sum(r["status"] == "error" for r in executed),
                   unique_original_groups=len({r["group_id"] for r in executed}),
                   per_field={f: summarize_outcomes(o for o in outcomes if o["field"] == f) for f in FIELDS},
                   latency_ms={"n": len(timings), "mean": statistics.fmean(timings) if timings else None,
                               "p50": quantile(timings, .50), "p95": quantile(timings, .95)},
                   recommendation_status_counts=dict(Counter(r.get("contract_check", {}).get("recommendation_status", "not_checked") for r in executed)),
                   contract_checks_run=sum("contract_check" in r for r in executed),
                   unconfirmed_states=sum(r.get("contract_check", {}).get("recognition_unconfirmed") is True for r in executed),
                   null_personal_probability_checks=sum(r.get("contract_check", {}).get("personal_probability_is_null") is True for r in executed),
                   safety_contract_failures=sum(r.get("contract_check", {}).get("passed") is False for r in executed))
    groups = defaultdict(list)
    for run in executed:
        groups[run["group_id"]].extend(run.get("outcomes", []))
    group_metrics = [summarize_outcomes(group) for group in groups.values()]
    metrics["group_balanced_macro"] = {key: statistics.fmean(vals) if (vals := [g[key] for g in group_metrics if g[key] is not None]) else None
                                        for key in ["coverage", "precision", "end_to_end_correct_rate"]}
    return metrics


def load_recognizer(module_path):
    path = Path(module_path).resolve()
    name = "jcc_eval_recognizer_" + sha256_file(path)[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Could not load recognizer module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "ScreenshotRecognizer"):
        raise ValueError("Recognizer module must export ScreenshotRecognizer")
    return module.ScreenshotRecognizer


def environment_metadata():
    packages = {}
    for name in ["Pillow", "numpy", "opencv-python-headless", "opencv-python", "scikit-learn", "pydantic"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    try:
        result = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5, check=False)
        tesseract = (result.stdout or result.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        tesseract = None
    return {"python": sys.version, "packages": packages, "tesseract": tesseract}


def create_contract_checker(data_dir, model_dir):
    """Exercise actual engine/model guards without altering the observed state."""
    sys.path.insert(0, str(ROOT))
    from app.engine import ExpertEngine
    from app.probability import ProbabilityModel
    engine = ExpertEngine(Path(data_dir))
    probability = ProbabilityModel(Path(model_dir))

    def check(state):
        recommendation = engine.recommend(state)
        model = probability.predict(state, [])
        recognition_unconfirmed = state.get("confirmed") is False
        # Missing fields do not masquerade as an explicitly-null probability.
        probability_null = ("state_probability" in recommendation and recommendation["state_probability"] is None
                            and "state_probability" in model and model["state_probability"] is None)
        return {"recommendation_status": recommendation.get("status"),
                "recognition_unconfirmed": recognition_unconfirmed,
                "personal_probability_is_null": probability_null,
                "model_status": model.get("status"),
                "candidate_count": len(recommendation.get("candidates", [])),
                "passed": recognition_unconfirmed and probability_null,
                "recommendation": recommendation, "probability_model": model}
    return check


def evaluate_samples(samples, recognizer_factory, data_dir, assets_dir, output, contract_checker=None):
    output = Path(output)
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Independent instances give each track its own template-cache initialization.
    recognizers = {track: recognizer_factory(Path(data_dir), Path(assets_dir)) for track in TRACK_NAMES}
    runs = []
    for sample in samples:
        for track in TRACK_NAMES:
            run = {"sample_id": sample["id"], "group_id": sample["group_id"], "split": sample["split"],
                   "mode": sample["mode"], "track": track, "source_url": sample.get("source_url"),
                   "file_sha256": sample["file_sha256"], "decoded_image_sha256": sample["decoded_image_sha256"],
                   "profile_origin": sample.get("profile_origin", "unspecified"),
                   "labelled_fields": sum(o["label_present"] for o in evaluate_fields(sample["labels"], {}))}
            if track == "profile" and sample.get("layout_profile") is None:
                run.update(status="not_run_no_profile", latency_ms=None, outcomes=[])
                runs.append(run)
                continue
            profile = sample.get("layout_profile") if track == "profile" else None
            if profile is not None:
                run["profile_sha256"] = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            started = time.perf_counter()
            raw = {}
            print(f"[{sample['id']}] {TRACK_NAMES[track]}…", file=sys.stderr, flush=True)
            try:
                recognition = recognizers[track].recognize(Path(sample["file"]), sample["mode"], profile)
                run["latency_ms"] = (time.perf_counter() - started) * 1000
                if not isinstance(recognition, dict) or not isinstance(recognition.get("state"), dict):
                    raise ValueError("Recognizer did not return an object with a state object")
                raw["recognition"] = recognition
                run.update(status="ok", outcomes=evaluate_fields(sample["labels"], recognition["state"]),
                           evidence_count=len(recognition.get("evidence", [])))
                if contract_checker:
                    try:
                        check = contract_checker(recognition["state"])
                        raw["recommendation"] = check.pop("recommendation", None)
                        raw["probability_model"] = check.pop("probability_model", None)
                        run["contract_check"] = check
                    except Exception as exc:
                        run["contract_check"] = {"passed": False, "recommendation_status": "error", "error_type": type(exc).__name__, "error": str(exc)}
            except Exception as exc:
                run.update(status="error", latency_ms=(time.perf_counter() - started) * 1000,
                           outcomes=evaluate_fields(sample["labels"], {}), error_type=type(exc).__name__, error=str(exc))
                raw["error"] = {"type": type(exc).__name__, "message": str(exc)}
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", sample["id"])[:70] or "sample"
            suffix = hashlib.sha256(sample["id"].encode()).hexdigest()[:8]
            filename = f"{safe_id}-{suffix}-{track}.json"
            (raw_dir / filename).write_text(json.dumps({"run": run, **raw}, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            run["raw_file"] = f"raw/{filename}"
            runs.append(run)
            m = summarize_outcomes(run["outcomes"])
            print(f"[{sample['id']}] {track}: {run['status']}, correct={m['correct']} wrong={m['wrong']} abstain={m['abstain']}, {run['latency_ms']:.0f}ms", file=sys.stderr, flush=True)
    return runs


def build_report(samples, runs, metadata):
    profile_ids = {s["id"] for s in samples if s.get("layout_profile") is not None}
    default_runs = [r for r in runs if r["track"] == "default"]
    report = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
              "metadata": metadata, "definitions": {
                  "correct": "有人工标签且识别值与标签完全一致",
                  "wrong": "有人工标签且识别输出非空，但与标签不一致或格式无效",
                  "abstain": "有人工标签但识别值为null/缺失；运行失败也计弃答，另计错误数",
                  "unlabelled": "标签缺失或null，不加入正确、错误、弃答分母",
                  "coverage": "(correct+wrong)/(correct+wrong+abstain)",
                  "precision": "correct/(correct+wrong)，零回答时为null，不是100%",
                  "end_to_end_correct_rate": "correct/(correct+wrong+abstain)",
                  "group_balanced_macro": "先在同一原始画面组内计算指标，再平均非null组指标；不是独立样本置信区间",
                  "latency": "单次recognize总耗时，包含OCR/图标匹配；不含推荐检查。每track独立缓存，首次调用含冷启动。",
                  "shop_empty": "标签null为未标注；{empty:true}为已知空格，输出null仍是弃答而非正确。"},
              "limitations": [
                  "默认识别与人工区域辅助是不同任务；后者不能宣传为全自动识别准确率。",
                  "profile track仅覆盖提供区域的样本。配对比较应使用default_on_profile_subset，而非直接比较不同样本总体。",
                  "holdout由标注声明，不是自动独立验证；人工区域若针对每图调节，不能当作冻结布局泛化结果。",
                  "group_id只能依赖采集者诚实标注原始画面；工具另外检查解码后完全重复的图片，无法自动证明所有裁片同源关系。",
                  "按同一原始画面分组，不把原图与其裁片当独立评测证据。没有组声明的样本仅按相同像素去重，holdout独立性未确认。",
                  "没有完整实体标注时，不计算英雄候选全量召回率或把未标注候选判错。",
                  "needs_confirmation/空个人概率是交互安全契约检查。截图识别指标与比赛第一率提升无等价关系。",
                  "没有训练、保存对局或将识别结果自动置为confirmed；截图和标签不会进入用户训练数据库。"],
              "samples": [{k: v for k, v in s.items() if k not in {"labels", "layout_profile", "file"}} for s in samples],
              "grouping": {"unique_original_groups": len({s["group_id"] for s in samples}),
                           "all_groups_explicit": all(s["grouping_explicit"] for s in samples),
                           "holdout_groups_explicit": all(s["grouping_explicit"] for s in samples if s["split"] == "holdout"),
                           "declared_cross_split_or_exact_duplicate_leakage": False,
                           "split_counts": dict(Counter(s["split"] for s in samples))},
              "tracks": {track: summarize_runs([r for r in runs if r["track"] == track]) for track in TRACK_NAMES},
              "default_on_profile_subset": summarize_runs([r for r in default_runs if r["sample_id"] in profile_ids]),
              "by_split": {split: {track: summarize_runs([r for r in runs if r["track"] == track and r["split"] == split]) for track in TRACK_NAMES} for split in sorted(SPLITS)},
              "by_mode": {mode: {track: summarize_runs([r for r in runs if r["track"] == track and r["mode"] == mode]) for track in TRACK_NAMES} for mode in sorted({s["mode"] for s in samples})},
              "runs": runs}
    return report


def render_html(report):
    esc = lambda value: html.escape(str(value), quote=True)
    pct = lambda value: "—" if value is None else f"{value * 100:.1f}%"
    number = lambda value: "—" if value is None else f"{value:.0f}"
    def summary_row(label, metric):
        return "<tr>" + "".join(f"<td>{esc(x)}</td>" for x in [label, metric["samples"], metric["unique_original_groups"], metric["labelled"], metric["correct"], metric["wrong"], metric["abstain"], pct(metric["coverage"]), pct(metric["precision"]), pct(metric["end_to_end_correct_rate"]), number(metric["latency_ms"]["p50"])]) + "</tr>"
    summaries = "".join(summary_row(TRACK_NAMES[t], report["tracks"][t]) for t in TRACK_NAMES)
    summaries += summary_row("配对基线：默认识别 / 有区域的同批图", report["default_on_profile_subset"])
    fields = ""
    for track in TRACK_NAMES:
        for field, m in report["tracks"][track]["per_field"].items():
            fields += "<tr>" + "".join(f"<td>{esc(x)}</td>" for x in [TRACK_NAMES[track], field, m["labelled"], m["correct"], m["wrong"], m["abstain"], m["unlabelled"], pct(m["coverage"]), pct(m["precision"])]) + "</tr>"
    cases = ""
    for run in report["runs"]:
        metric = summarize_outcomes(run.get("outcomes", []))
        cells = [run["sample_id"], run["group_id"], run["split"], run["mode"], TRACK_NAMES[run["track"]], run["status"], metric["correct"], metric["wrong"], metric["abstain"], number(run.get("latency_ms")), run.get("contract_check", {}).get("recommendation_status", "未检查")]
        row = "".join(f"<td>{esc(x)}</td>" for x in cells)
        raw = f'<a href="{esc(run["raw_file"])}">逐图原始结果</a>' if run.get("raw_file") else "无区域，未运行"
        cases += f"<tr>{row}<td>{raw}</td></tr>"
    split_sections = ""
    for split, tracks in report["by_split"].items():
        rows = "".join(summary_row(f"{split} / {TRACK_NAMES[t]}", tracks[t]) for t in TRACK_NAMES)
        split_sections += f"<tbody>{rows}</tbody>"
    safety = []
    for track, m in report["tracks"].items():
        safety.append(f"{TRACK_NAMES[track]}：已执行契约检查 {m['contract_checks_run']} 次；状态分布 {m['recommendation_status_counts']}；未确认状态 {m['unconfirmed_states']}；明确空个人概率检查 {m['null_personal_probability_checks']}；契约失败 {m['safety_contract_failures']}。")
    sources = ""
    seen = set()
    for s in report["samples"]:
        url = s.get("source_url")
        if not isinstance(url, str) or url in seen or not re.match(r"^https?://", url, re.I):
            continue
        seen.add(url)
        sources += f'<li><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(s["id"])} · 原始来源</a></li>'
    limitations = "".join(f"<li>{esc(x)}</li>" for x in report["limitations"])
    definitions = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in report["definitions"].items())
    header = "<thead><tr>" + "".join(f"<th>{x}</th>" for x in ["识别条件", "图片", "原画面组", "已标字段", "正确", "错误", "弃答", "覆盖率", "已答精确率", "端到端正确率", "耗时P50/ms"]) + "</tr></thead>"
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>金铲铲真实截图评测</title><style>
    body{{font:14px/1.75 system-ui,sans-serif;margin:0;background:#10171d;color:#dce7ed}}main{{max-width:1500px;padding:35px;margin:auto}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:35px}}p,li,dd{{color:#a8bbc9}}.notice{{padding:16px;border:1px solid #80673a;background:#3c301e;border-radius:8px}}.scroll{{overflow:auto;border:1px solid #344754;border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}}td,th{{padding:10px 13px;border-bottom:1px solid #2a3d49;text-align:left}}th{{color:#a9cd98;background:#19242c}}a{{color:#b9dc95}}code{{overflow-wrap:anywhere}}dt{{font-weight:600;margin-top:12px}}dd{{margin-left:0}}.meta{{font-size:12px;color:#7e98a9}}@media(max-width:600px){{main{{padding:18px}}}}</style><main>
    <p class="meta">SCREENSHOT EVALUATION · {esc(report['created_at'])}</p><h1>截图识别评测 · 弃答也需要计数</h1>
    <div class="notice">识别正确不等于能提高吃鸡率。人工区域辅助识别不能作为全自动识别成绩；未标注字段不计正确，未识别已标字段计弃答。本报告不嵌入或复制来源截图。</div>
    <p class="meta">识别模块 SHA256：<code>{esc(report['metadata']['recognizer_sha256'])}</code><br>标注 SHA256：<code>{esc(report['metadata']['annotations_sha256'])}</code><br>分组：{esc(report['grouping'])}</p>
    <h2>整体与配对结果</h2><div class="scroll"><table>{header}<tbody>{summaries}</tbody></table></div>
    <h2>development / holdout 分开报告</h2><p>有无提供原始画面分组见上方。若人工区域按每张holdout图片调整，这仅是辅助识别评测。</p><div class="scroll"><table>{header}{split_sections}</table></div>
    <h2>逐字段结果</h2><div class="scroll"><table><thead><tr>{''.join(f'<th>{x}</th>' for x in ['识别条件','字段','已标注','正确','错误','弃答','未标注','覆盖率','已答精确率'])}</tr></thead><tbody>{fields}</tbody></table></div>
    <h2>推荐与概率契约</h2>{''.join(f'<p>{esc(x)}</p>' for x in safety)}<p>无可用来牌时可能返回insufficient_data；有候选且未确认时应返回needs_confirmation。此检查不证明推荐路线的因果收益。</p>
    <h2>逐图审计</h2><div class="scroll"><table><thead><tr>{''.join(f'<th>{x}</th>' for x in ['图片ID','原画面组','划分','模式','识别条件','运行状态','正确','错误','弃答','耗时/ms','推荐状态','原始结果'])}</tr></thead><tbody>{cases}</tbody></table></div>
    <h2>指标定义与复现</h2><dl>{definitions}</dl><pre class="meta">{esc(json.dumps(report['metadata'],ensure_ascii=False,indent=2))}</pre>
    <h2>原始来源</h2><ul>{sources or '<li>未提供可链接的来源URL。</li>'}</ul><h2>适用范围与限制</h2><ul>{limitations}</ul><p><a href="report.json">下载完整JSON报告</a></p></main></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recognizer-module", type=Path, default=ROOT / "app/vision.py")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "app/data")
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "app/assets")
    parser.add_argument("--split", choices=["all", "development", "holdout"], default="all")
    parser.add_argument("--skip-contract-checks", action="store_true", help="Only measure recognition; report recommendation checks as not_checked")
    parser.add_argument("--require-explicit-groups", action="store_true", help="Reject any sample missing group_id/original_id, rather than checking exact duplicate images only")
    args = parser.parse_args(argv)
    payload, all_samples = load_annotations(args.annotations)
    if args.require_explicit_groups and not all(s["grouping_explicit"] for s in all_samples):
        raise ValueError("Every sample requires an explicit group_id/original_id in strict grouping mode")
    samples = [s for s in all_samples if args.split == "all" or s["split"] == args.split]
    if not samples:
        raise ValueError("No samples match requested split")
    args.output.mkdir(parents=True, exist_ok=True)
    recognizer_class = load_recognizer(args.recognizer_module)
    metadata = {"recognizer_module": str(args.recognizer_module.resolve()),
                "recognizer_sha256": sha256_file(args.recognizer_module),
                "annotations_file": str(args.annotations.resolve()), "annotations_sha256": sha256_file(args.annotations),
                "data_dir": str(args.data_dir.resolve()), "assets_manifest_sha256": sha256_file(args.assets_dir / "manifest.json") if (args.assets_dir / "manifest.json").exists() else None,
                "split_filter": args.split, "contract_checks_enabled": not args.skip_contract_checks,
                "annotation_dataset_note": payload.get("note"), "annotation_metadata": {k: v for k, v in payload.items() if k != "samples"}, "sample_count": len(samples),
                "runtime": environment_metadata(),
                "data_sha256": {name: sha256_file(args.data_dir / name) for name in ["nature_facts.json", "orange_base_facts.json", "orange_official_facts.json", "orange_research.json", "statistics_external.json"] if (args.data_dir / name).is_file()},
                "contract_module_sha256": {name: sha256_file(ROOT / "app" / name) for name in ["engine.py", "probability.py"]} if not args.skip_contract_checks else {},
                "command": [sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]}
    with tempfile.TemporaryDirectory(prefix="jcc-eval-model-") as temp:
        checker = None if args.skip_contract_checks else create_contract_checker(args.data_dir, Path(temp) / "models")
        runs = evaluate_samples(samples, recognizer_class, args.data_dir, args.assets_dir, args.output, checker)
    report = build_report(samples, runs, metadata)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (args.output / "report.html").write_text(render_html(report), encoding="utf-8")
    print(json.dumps({"report": str((args.output / 'report.html').resolve()),
                      "tracks": {t: {k: report['tracks'][t][k] for k in ['samples', 'correct', 'wrong', 'abstain', 'coverage', 'precision', 'safety_contract_failures']} for t in TRACK_NAMES}}, ensure_ascii=False))
    return 1 if any(m["safety_contract_failures"] for m in report["tracks"].values()) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Evaluation input error: {exc}", file=sys.stderr)
        raise SystemExit(2)
