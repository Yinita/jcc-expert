#!/usr/bin/env python3
"""Train a real supervised OCR-line classifier; leave sealed_test unopened.

Only field_boxes + matching manual values, explicit negative_boxes, or a fully
annotated field layout can supervise lines. Missing labels never become other.
Old consumed_development groups are development data, never a new test set.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.field_model import (FIELDS, FEATURE_VERSION, artifact_key, calibrated_probabilities,
                             features, parse_value, predict_artifact, valid_bbox, inference_context, normalize_screen_type)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(line_box, region, minimum=.6):
    if not valid_bbox(line_box) or not valid_bbox(region):
        return False
    x, y, w, h = line_box; a, b, c, d = region
    area = max(0., min(x+w, a+c)-max(x, a))*max(0., min(y+h, b+d)-max(y, b))
    return a <= x+w/2 <= a+c and b <= y+h/2 <= b+d and area/(w*h) >= minimum


def positive_overlap(line_box, region):
    """A tight digit ROI may be narrower than its OCR row, which includes a label."""
    if inside(line_box, region):
        return True
    if not valid_bbox(line_box) or not valid_bbox(region): return False
    x,y,w,h=line_box; a,b,c,d=region
    overlap=max(0.,min(x+w,a+c)-max(x,a))*max(0.,min(y+h,b+d)-max(y,b))
    return overlap/(c*d)>=.8 and overlap/(w*h)>=.35 and abs(y+h/2-b-d/2)<max(h,d)*.4


def field_boxes(sample):
    raw = sample.get("field_boxes", {})
    boxes = {}
    if isinstance(raw, dict):
        for field, value in raw.items():
            box = value.get("bbox") if isinstance(value, dict) else value
            if field in FIELDS and valid_bbox(box):
                boxes[field] = list(map(float, box))
    # A manual scalar layout is also an explicit geometric field annotation.
    if not boxes and sample.get("profile_origin") == "per_sample_manual":
        for slot in sample.get("layout_profile", {}).get("slots", []):
            if slot.get("field") in FIELDS and valid_bbox(slot.get("bbox")):
                boxes[slot["field"]] = list(map(float, slot["bbox"]))
    return boxes


def supervised_rows(sample, lines, shape):
    labels = sample.get("labels", {}); boxes = field_boxes(sample)
    negatives = [row.get("bbox") if isinstance(row, dict) else row for row in sample.get("negative_boxes", [])]
    negatives = [box for box in negatives if valid_bbox(box)]
    complete = sample.get("field_annotation_complete") is True and all(
        (field in boxes and labels.get(field) is not None) or field in sample.get("known_absent_fields", []) for field in FIELDS)
    rows, ignored = [], Counter()
    for index, line in enumerate(lines):
        if not isinstance(line, dict) or not valid_bbox(line.get("bbox")) or not line.get("text"):
            ignored["invalid_ocr_line"] += 1; continue
        matches = []
        in_positive_region = False
        for field, box in boxes.items():
            if positive_overlap(line["bbox"], box):
                in_positive_region = True
                expected = labels.get(field)
                value = parse_value(line["text"], field)
                if expected is not None and value is not None and str(value) == str(expected):
                    matches.append(field)
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            ignored["ambiguous_positive"] += 1; continue
        elif in_positive_region:
            # OCR wrong values inside a real field are not other-class negatives.
            ignored["unreadable_or_mismatching_positive"] += 1; continue
        elif any(inside(line["bbox"], region) for region in negatives) or complete:
            target = "other"
        else:
            ignored["unlabelled_line"] += 1; continue
        rows.append({"sample_id": sample["id"], "group_id": sample["group_id"], "mode": sample["mode"],
                     "line_index": index, "label": target, "text": str(line["text"]), "bbox": line["bbox"],
                     "features": features(line, lines, shape, sample["mode"], sample.get("screen_type", "unknown"))})
    # Full-image and automatic small-HUD OCR can describe the same field twice.
    # One source-image scalar should not inflate its class or calibration count.
    unique=[]
    for row in sorted(rows,key=lambda r:float(lines[r['line_index']].get('confidence',0)),reverse=True):
        duplicate=any(row['label']==old['label']and(row['label']in FIELDS or
                      (row['text'].strip()==old['text'].strip()and positive_overlap(row['bbox'],old['bbox'])))for old in unique)
        if duplicate:ignored['duplicate_supervision_removed']+=1
        else:unique.append(row)
    return sorted(unique,key=lambda r:r['line_index']), dict(ignored)


def assign_partitions(samples, seed=20261111):
    explicit = {}; pool = set()
    for sample in samples:
        split = sample.get("split", "consumed_development")
        group = sample["group_id"]
        if split in {"train", "calibration", "validation"}:
            if group in explicit and explicit[group] != split:
                raise ValueError("Source group cannot cross train/calibration/validation")
            explicit[group] = split
        elif split in {"development", "holdout", "consumed_development"}:
            pool.add(group)
        else:
            raise ValueError(f"Unsupported nonsealed split: {split}")
    pool -= set(explicit)
    ordered = sorted(pool, key=lambda g: hashlib.sha256(f"{seed}:{g}".encode()).hexdigest())
    need_cal = "calibration" not in explicit.values(); need_val = "validation" not in explicit.values()
    # Keep at least one training group; insufficient groups remain candidate-only.
    desired_val=max(0,2-list(explicit.values()).count("validation"))
    desired_cal=max(0,1-list(explicit.values()).count("calibration"))
    desired_train=max(0,2-list(explicit.values()).count("train"))
    if len(ordered)>=desired_val+desired_cal+desired_train:
        for _ in range(desired_val):explicit[ordered.pop()]="validation"
        for _ in range(desired_cal):explicit[ordered.pop()]="calibration"
    elif len(ordered) >= 1 + need_cal + need_val:
        if need_val: explicit[ordered.pop()] = "validation"
        if need_cal: explicit[ordered.pop()] = "calibration"
    explicit.update({g: "train" for g in ordered})
    for sample in samples:
        sample["partition"] = explicit[sample["group_id"]]
    return explicit


def load_samples(annotation_paths, mode):
    result, skipped, ids = [], 0, set()
    for path in annotation_paths:
        path = Path(path).resolve(); document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document.get("samples", []):
            # Do not resolve/read the file, inspect labels, run OCR, or retain the
            # ID of a sealed sample. Prefer separate sealed annotation files.
            if (entry.get("split") == "sealed_test" or entry.get("evaluation_role") == "sealed_test"
                    or entry.get("sealed_test") is True):
                skipped += 1; continue
            if entry.get("mode") not in {"nature", "orange"} or (mode != "both" and entry["mode"] != mode):
                continue
            sample = dict(entry)
            if not sample.get("group_id"):
                raise ValueError("Training requires explicit source group_id")
            sid = str(sample.get("id", ""))
            if not sid or sid in ids:
                raise ValueError("Training sample IDs must be unique")
            ids.add(sid)
            value = sample.get("file") or sample.get("image_path") or sample.get("path")
            if not value:
                raise ValueError(f"{sid}: file is required")
            image = Path(value); image = image if image.is_absolute() else path.parent/image
            sample.update(file=str(image.resolve()), annotation_file=str(path), annotation_sha256=digest(path))
            if sample.get("ocr_cache"):
                cache = Path(sample["ocr_cache"])
                sample["ocr_cache"] = str(cache if cache.is_absolute() else path.parent/cache)
            result.append(sample)
    return result, skipped


def read_lines(sample, cache_dir):
    from PIL import Image
    image_path = Path(sample["file"]); image_sha = digest(image_path)
    with Image.open(image_path) as image:
        width, height = image.size
    shape = (height, width, 3)
    cache = Path(sample.get("ocr_cache") or cache_dir/(image_sha+".json"))
    if cache.is_file():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("image_sha256") and payload["image_sha256"] != image_sha:
            raise ValueError("OCR cache image SHA256 mismatch")
        provenance = {"cache": str(cache), "cache_sha256": digest(cache), "image_sha256": image_sha,
                      "backend": payload.get("backend", "externally_cached_OCR"),
                      "cache_image_hash_verified": payload.get("image_sha256") == image_sha}
        if payload.get("error"):
            raise ValueError("Cached OCR error: "+str(payload["error"]))
        return payload.get("lines", []), shape, provenance
    from app.ocr_backend import get_ocr_backend
    backend = get_ocr_backend()
    if backend is None:
        raise ValueError("RapidOCR runtime unavailable and no supplied OCR cache")
    from app.vision import ScreenshotRecognizer
    recognizer = ScreenshotRecognizer(ROOT/"app/data", ROOT/"app/assets")
    image = recognizer._read_image(image_path)
    shape = image.shape
    lines, error = backend.read(image)
    if not error:
        lines = recognizer._ocr_small_ui(image, lines)
    payload = {"lines": lines, "error": error, "image_sha256": image_sha, "backend": backend.name,
               "preprocess_sha256": digest(ROOT/"app/vision.py")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if error:
        raise ValueError("OCR failed: "+str(error))
    return lines, shape, {"cache": str(cache), "cache_sha256": digest(cache), "image_sha256": image_sha,
                          "backend": backend.name, "cache_image_hash_verified": True}


def temperature_fit(artifact, rows):
    if not rows:
        return 1., {"status": "unavailable", "reason": "No separate calibration groups"}
    classes = list(artifact["classifier"].classes_)
    known = [row for row in rows if row["label"] in classes]
    if not known:
        return 1., {"status": "unavailable", "reason": "Calibration classes unavailable"}
    if not any(row['label']=='other'for row in known):
        return 1., {"status":"unavailable_no_explicit_other","reason":"Positive-only calibration cannot validate rejection or justify a sharper temperature","rows":len(known)}
    matrix = artifact["vectorizer"].transform([r["features"] for r in known])
    labels = np.array([classes.index(r["label"]) for r in known])
    counts=Counter(r['group_id']for r in known)
    weights=np.array([1/counts[r['group_id']]for r in known])
    choices = []
    for temperature in np.geomspace(.3, 3., 61):
        p = calibrated_probabilities(artifact["classifier"], matrix, temperature)
        loss = float(np.average(-np.log(np.clip(p[np.arange(len(labels)), labels], 1e-9, 1.)),weights=weights))
        choices.append((float(loss), float(temperature)))
    loss, temperature = min(choices)
    return temperature, {"status": "development_temperature_fit", "rows": len(known), "nll": loss,
                         "equal_source_group_weights":True,
                         "groups": sorted({r["group_id"] for r in known})}


def evaluate_images(artifact, meta, samples, records, thresholds):
    counts = Counter(); per_field = {f: Counter() for f in FIELDS}; per_mode = defaultdict(Counter); details = []
    for sample in samples:
        if sample["id"] not in records:
            continue
        record = records[sample["id"]]
        predicted = predict_artifact(artifact, meta, record["lines"], record["shape"], sample["mode"], sample.get("screen_type", "unknown"), thresholds)
        by_field = {row["field"]: row for row in predicted}; boxes = field_boxes(sample)
        for field in FIELDS:
            expected = sample.get("labels", {}).get(field)
            if expected is None:
                if field in sample.get("known_absent_fields",[]):
                    outcome="false_positive_absent" if field in by_field else "correct_absence"
                    counts[outcome]+=1;per_field[field][outcome]+=1;per_mode[sample["mode"]][outcome]+=1
                    details.append({"sample_id":sample["id"],"group_id":sample["group_id"],"field":field,"expected":"explicitly_absent","predicted":by_field.get(field,{}).get("value"),"outcome":outcome})
                continue
            pred = by_field.get(field)
            outcome = "abstain" if pred is None else "correct" if (str(pred["value"]) == str(expected) and (field not in boxes or positive_overlap(pred["bbox"], boxes[field]))) else "wrong"
            counts[outcome] += 1; per_field[field][outcome] += 1; per_mode[sample["mode"]][outcome] += 1
            details.append({"sample_id": sample["id"], "group_id": sample["group_id"], "field": field,
                            "expected": expected, "predicted": pred.get("value") if pred else None, "outcome": outcome})
    def metrics(counter):
        n=counter["correct"]+counter["wrong"]+counter["abstain"]
        answered=counter["correct"]+counter["wrong"]
        all_answers=answered+counter["false_positive_absent"]
        return {"n_labelled": n, "correct": counter["correct"], "wrong": counter["wrong"]+counter["false_positive_absent"], "abstain": counter["abstain"],
                "false_positive_absent":counter["false_positive_absent"],"correct_absence":counter["correct_absence"],
                "coverage": answered/n if n else None, "precision": counter["correct"]/all_answers if all_answers else None}
    return {**metrics(counts), "per_field": {k: metrics(v) for k, v in per_field.items()},
            "per_mode": {k: metrics(v) for k, v in per_mode.items()}, "details": details}


def train(samples, records, mode, patch, output, target_precision=.98, min_validation_answers=20):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    all_rows, annotation_stats = [], {}
    for sample in samples:
        if sample["id"] not in records: continue
        record = records[sample["id"]]
        rows, ignored = supervised_rows(sample, record["lines"], record["shape"])
        for row in rows: row["partition"] = sample["partition"]
        all_rows.extend(rows); annotation_stats[sample["id"]] = {"supervised_rows": len(rows), "labels": dict(Counter(r["label"] for r in rows)), "ignored": ignored,
            "annotation_context":sample.get('screen_type','unknown'),'effective_context':inference_context(record['lines'],sample['mode']),
            "context_mismatch_with_annotation":normalize_screen_type(sample.get('screen_type','unknown'))!=inference_context(record['lines'],sample['mode'])}
    train_rows = [r for r in all_rows if r["partition"] == "train"]
    calibration_rows = [r for r in all_rows if r["partition"] == "calibration"]
    groups = {part: sorted({s["group_id"] for s in samples if s["partition"] == part}) for part in ["train", "calibration", "validation"]}
    report = {"kind": "supervised_OCR_line_field_assignment_not_win_probability", "mode": mode, "patch": patch,
              "feature_version": FEATURE_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
              "group_partitions": groups, "annotation_stats": annotation_stats,
              "supervised_class_counts": dict(Counter(r["label"] for r in train_rows)),
              "n_supervised_rows": len(all_rows), "n_training_rows": len(train_rows),
              "context_policy":"OCR_only_context_derived_identically_for_training_and_serving; annotation.screen_type_is_diagnostic_only",
              "data_quality":{"positive_only_images":sum(bool(v['labels'])and 'other'not in v['labels']for v in annotation_stats.values()),
                  "source_groups_with_other":sorted({r['group_id']for r in all_rows if r['label']=='other'}),
                  "class_source_groups":{label:sorted({r['group_id']for r in train_rows if r['label']==label})for label in (*FIELDS,'other')},
                  "duplicate_rows_removed":sum(v['ignored'].get('duplicate_supervision_removed',0)for v in annotation_stats.values()),
                  "annotation_context_mismatch_images":sum(v['context_mismatch_with_annotation']for v in annotation_stats.values())},
              "limitations": ["Only explicitly annotated lines supervise training; unknown labels are not negatives.",
                              "Temperature and thresholds are selected on development calibration groups. Validation groups are not used to tune thresholds.",
                              "Old consumed holdout groups are development validation, not a new unseen test. sealed_test is never opened.",
                              "This model assigns OCR lines to UI fields; values must parse from OCR. It does not predict wins.",
                              "Small or source-limited validation cannot establish deployment accuracy or real-match benefits."]}
    classes = set(r["label"] for r in train_rows)
    if len(classes) < 2 or "other" not in classes or not (classes & set(FIELDS)):
        return {**report, "status": "insufficient_data", "deployable": False,
                "reason": "Need at least one reliably annotated scalar class and explicit other negatives in training groups; no weights fabricated."}
    vectorizer = DictVectorizer()
    matrix = vectorizer.fit_transform([r["features"] for r in train_rows])
    classifier = LogisticRegression(C=.5, max_iter=2000, class_weight="balanced", random_state=20261111)
    # Each source group contributes equal total fitting weight.
    group_counts = Counter(r["group_id"] for r in train_rows)
    weights = np.array([1/group_counts[r["group_id"]] for r in train_rows]); weights *= len(weights)/weights.sum()
    classifier.fit(matrix, [r["label"] for r in train_rows], sample_weight=weights)
    names = vectorizer.get_feature_names_out()
    learned = {}
    for i, label in enumerate(classifier.classes_):
        coefficients = classifier.coef_[i] if len(classifier.classes_) > 2 else classifier.coef_[0]*(1 if i else -1)
        top = np.argsort(np.abs(coefficients))[-10:][::-1]
        learned[str(label)] = [{"feature": str(names[j]), "coefficient": float(coefficients[j])} for j in top]
    artifact = {"vectorizer": vectorizer, "classifier": classifier, "feature_version": FEATURE_VERSION}
    temperature, calibration = temperature_fit(artifact, calibration_rows); artifact["temperature"] = temperature
    thresholds = {f: 1.000001 for f in FIELDS}
    meta = {"mode": mode, "patch": patch, "feature_version": FEATURE_VERSION, "model_id": artifact_key(mode, patch),
            "status": "candidate_unvalidated", "deployable": False, "calibration_method": "development_temperature_scaling" if calibration_rows else "none"}
    cal_samples = [s for s in samples if s["partition"] == "calibration"]
    threshold_selection = {}
    for field in FIELDS:
        best = None
        if not any(row['label']=='other'for row in calibration_rows):continue
        for threshold in [.5, .6, .7, .8, .85, .9, .93, .95, .97, .98, .99, .995]:
            current = dict(thresholds); current[field] = threshold
            metric = evaluate_images(artifact, meta, cal_samples, records, current)["per_field"][field]
            answered = metric["correct"]+metric["wrong"]
            if answered >= 2 and metric["precision"] >= target_precision:
                candidate = (metric["coverage"], threshold, metric)
                if best is None or candidate[0] > best[0]: best = candidate
        if best:
            thresholds[field] = best[1]; threshold_selection[field] = best[2]
    validation_samples = [s for s in samples if s["partition"] == "validation"]
    validation = evaluate_images(artifact, meta, validation_samples, records, thresholds)
    # Preview is explicitly unvalidated and never used to activate the model.
    preview_thresholds = {f: .5 for f in FIELDS}
    preview_validation = evaluate_images(artifact, meta, validation_samples, records, preview_thresholds)
    reasons = []
    if len({r['group_id']for r in train_rows}) < 2 or not {r['group_id']for r in calibration_rows} or len(groups["validation"]) < 2:
        reasons.append("Need >=2 train, >=1 calibration and >=2 validation source groups")
    answered = validation["correct"]+validation["wrong"]
    if answered < min_validation_answers or validation["precision"] is None or validation["precision"] < target_precision:
        reasons.append("Separate validation coverage/precision has not met the declared minimum")
    validated_modes = []
    for m in (["nature", "orange"] if mode == "shared" else [mode]):
        metric = validation["per_mode"].get(m, {})
        if metric.get("correct", 0)+metric.get("wrong", 0) >= min_validation_answers and metric.get("precision", 0) >= target_precision:
            validated_modes.append(m)
    if mode == "shared" and len(validated_modes) < 2:
        reasons.append("Shared recognition requires separate sufficient nature and orange validation")
    deployable = not reasons
    report.update(status="ready" if deployable else "candidate_unvalidated", deployable=deployable,
                  reason="; ".join(reasons) if reasons else "Declared development group gates passed; sealed test still pending",
                  calibration=calibration, temperature=temperature, thresholds=thresholds,
                  threshold_selection_calibration=threshold_selection, validation_metrics=validation,
                  unvalidated_preview_validation_metrics=preview_validation, min_validation_answers=min_validation_answers,
                  target_precision=target_precision, trained_classes=list(classifier.classes_), validated_modes=validated_modes)
    report["learned_feature_weights"] = learned
    key = artifact_key(mode, patch)
    model_path = output/(key+("" if deployable else ".candidate")+".joblib")
    joblib.dump(artifact, model_path)
    meta.update(report); meta.update(artifact_sha256=digest(model_path), model_id=key)
    meta_path = model_path.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report.update(artifact=str(model_path), artifact_sha256=meta["artifact_sha256"], metadata=str(meta_path))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ocr-cache-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["nature", "orange", "both"], default="both")
    parser.add_argument("--patch", default="18.6")
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--target-precision", type=float, default=.98)
    parser.add_argument("--min-validation-answers", type=int, default=20)
    args = parser.parse_args(argv)
    if not 0 < args.target_precision <= 1 or args.min_validation_answers < 1:
        raise ValueError("Precision must be in (0,1], and minimum validation answers positive")
    samples, sealed_skipped = load_samples(args.annotations, args.mode)
    partitions = assign_partitions(samples, args.seed)
    records, errors = {}, []
    for sample in samples:
        print(f"OCR training input: {sample['id']} / {sample['partition']}", file=sys.stderr, flush=True)
        try:
            lines, shape, provenance = read_lines(sample, args.ocr_cache_dir)
            records[sample["id"]] = {"lines": lines, "shape": shape, "provenance": provenance}
        except (OSError, ValueError) as exc:
            errors.append({"sample_id": sample["id"], "error": str(exc)})
    args.output.mkdir(parents=True, exist_ok=True)
    report = train(samples, records, "shared" if args.mode == "both" else args.mode, args.patch, args.output,
                   args.target_precision, args.min_validation_answers)
    report.update(sealed_samples_skipped_without_file_or_label_access=sealed_skipped,
                  input_errors=errors, group_split_plan=partitions,
                  source_annotations_sha256={str(path): digest(path) for path in args.annotations},
                  ocr_provenance={key: row["provenance"] for key, row in records.items()},
                  command=[sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])])
    (args.output/"training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ["status", "deployable", "reason", "artifact", "n_training_rows", "validation_metrics", "sealed_samples_skipped_without_file_or_label_access"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
