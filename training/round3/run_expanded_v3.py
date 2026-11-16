"""Candidate-only fit: frozen old38 plus seven explicitly named development images.

No round3 sealed file or annotation is an input to this program.
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import sys
import time
import argparse

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "outputs/jcc-expert"
OUT = ROOT / "work/round3_training/expanded_v3"
OLD = ROOT / "work/round3_training/annotations_consumed38.json"
NEW = ROOT / "work/round3_screens/nature/annotations.json"
sys.path.insert(0, str(PROJECT))
from app.vision import ScreenshotRecognizer


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', choices=['expanded_v3', 'expanded_v4'], default='expanded_v3')
    args = parser.parse_args()
    OUT = OUT.parent / args.experiment
    old_hash = sha(OLD)
    new_hash = sha(NEW)
    old = json.loads(OLD.read_text())["samples"]
    incoming = json.loads(NEW.read_text())["samples"]
    if len(old) != 38 or len(incoming) != 7:
        raise ValueError("Expected the frozen old38 and the authorized seven development inputs")
    new_plan = {"bili_BV1uCti6oEk7": "calibration", "taptap_840465181304686223": "train", "wanplus_507000": "train"}
    samples = deepcopy(old)
    ids = {s["id"] for s in samples}
    for original in incoming:
        if original.get("split") != "development" or original.get("evaluation_role") != "development" or original.get("sealed_test"):
            raise ValueError("Only the specifically authorized development annotation is accepted")
        sample = deepcopy(original)
        if sample["id"] in ids or sample["group_id"] not in new_plan:
            raise ValueError("Unexpected or repeated development identity")
        ids.add(sample["id"])
        image = Path(sample["file"])
        sample["file"] = str((NEW.parent / image).resolve() if not image.is_absolute() else image.resolve())
        part = new_plan[sample["group_id"]]
        sample.update(split=part, partition=part, evaluation_role="consumed_round3_development")
        samples.append(sample)
    plan = {s["group_id"]: s["partition"] for s in samples}
    plan_document = {"created_before_new_OCR_and_fit": datetime.now(timezone.utc).isoformat(),
        "scope": "Old38 consumed development plus seven explicitly authorized new development screenshots; no round3 sealed input",
        "source_plan": plan, "new_source_plan": new_plan, "old_validation_groups_unchanged": True,
        "input_hashes": {str(OLD): old_hash, str(NEW): new_hash}, "target_precision": .98, "minimum_validation_answers_per_mode": 20,
        "validation_reuse_experiments": ["baseline_v1", "enhanced_v2", "expanded_v3"] + (["expanded_v4"] if args.experiment == 'expanded_v4' else []),
        "extra_experiment_reason": "Fix discarded exact OCR values when manual digit ROIs are narrower than rows containing icons or level suffix; selected only from development alignment audit" if args.experiment == 'expanded_v4' else None,
        "validation_is_independent_final_evidence": False, "candidate_activation_allowed": False}
    dump(OUT / "experiment_plan.json", plan_document)
    dump(OUT / "annotations_consumed45.json", {"purpose": plan_document["scope"], "samples": samples})
    records = {}
    for split in ("development", "sealed"):
        folder = ROOT / "work/expanded_eval" / split
        old_runs = json.loads((folder / "optimized/report.json").read_text())["runs"]
        for run in old_runs:
            if run.get("track") != "default":
                continue
            rawpath = folder / "optimized" / run["raw_file"]
            raw = json.loads(rawpath.read_text())["recognition"]
            lines = [{"text": r["text"], "confidence": r["confidence"], "bbox": r["bbox"]} for r in raw.get("evidence", []) if r.get("kind") == "ocr_text"]
            size = raw["image_size"]
            records[run["sample_id"]] = {"lines": lines, "shape": (size["height"], size["width"], 3),
                "raw_sha256": sha(rawpath), "provenance": {"source": "frozen_old38_raw_OCR", "raw_file": str(rawpath)}}
    # Only _ocr is called: no recognize, layout profile, labels, or learned-model prediction.
    recognizer = ScreenshotRecognizer(PROJECT / "app/data", PROJECT / "app/assets", field_model_dir=OUT / "disabled_models")
    method_source = inspect.getsource(recognizer._ocr) + inspect.getsource(recognizer._ocr_small_ui)
    method_sha = hashlib.sha256(method_source.encode()).hexdigest()
    seen_pixels = {}
    from PIL import Image, ImageOps
    for sample in samples:
        with Image.open(sample["file"]) as image:
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            pixel_sha = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
        if pixel_sha in seen_pixels:
            raise ValueError("Repeated image pixels under different training identities")
        seen_pixels[pixel_sha] = sample["id"]
    for sample in samples[38:]:
        image_hash = sha(sample["file"])
        cache = OUT.parent / 'expanded_v3' / "ocr_cache" / (image_hash + ".json")
        if cache.is_file():
            payload = json.loads(cache.read_text())
            if payload.get("image_sha256") != image_hash or payload.get("ocr_method_source_sha256") != method_sha:
                raise ValueError("Stale current-production OCR cache")
        else:
            image = recognizer._read_image(Path(sample["file"]))
            start = time.perf_counter()
            lines, error = recognizer._ocr(image)
            payload = {"image_sha256": image_hash, "lines": lines, "shape": list(image.shape), "error": error,
                "backend": recognizer._last_ocr_engine, "ocr_method_source_sha256": method_sha,
                "elapsed_seconds": time.perf_counter() - start, "created_at": datetime.now(timezone.utc).isoformat(),
                "manual_profile_used": False, "field_model_used": False}
            dump(cache, payload)
        if payload.get("error"):
            raise ValueError("New development OCR failed: " + str(payload["error"]))
        records[sample["id"]] = {"lines": payload["lines"], "shape": payload["shape"],
            "provenance": {"cache": str(cache), "cache_sha256": sha(cache), "image_sha256": image_hash,
            "backend": payload["backend"], "ocr_method_source_sha256": method_sha}}
        print("OCR complete:", sample["id"], "lines", len(payload["lines"]), flush=True)
    if sha(OLD) != old_hash or sha(NEW) != new_hash:
        raise ValueError("An input annotation changed during the experiment")
    trainer_path = OUT / 'trainer_snapshot.py'
    spec = importlib.util.spec_from_file_location("r3_expanded_candidate_trainer", trainer_path)
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    # The saved trainer snapshot lives under work/, so reset its project path.
    trainer.ROOT = PROJECT
    report = trainer.train(samples, records, "shared", "18.6", OUT / "model", target_precision=.98, min_validation_answers=20)
    report.update(experiment="Round3 " + args.experiment + ": frozen old38 plus seven new development images",
        scope=plan_document["scope"], new_round3_sealed_accessed=False, independent_test_evidence=False,
        validation_is_independent_final_evidence=False, validation_reuse_experiments=plan_document["validation_reuse_experiments"],
        old_validation_groups_unchanged=True, input_annotations_sha256=sha(OUT / "annotations_consumed45.json"),
        image_counts_by_partition=dict(Counter(s["partition"] for s in samples)),
        ocr_provenance={sid: record["provenance"] for sid, record in records.items()},
        input_hashes=plan_document["input_hashes"], frozen_old_annotations_verified_after=sha(OLD) == old_hash,
        feature_code_sha256=sha(PROJECT / "app/field_model.py"), trainer_sha256=sha(trainer_path),
        candidate_change_reason=plan_document['extra_experiment_reason'])
    dump(OUT / "model/training_report.json", report)
    versions = json.loads((OUT.parent / "comparison.json").read_text())["results"]
    if args.experiment == 'expanded_v4':
        versions['expanded_v3'] = json.loads((OUT.parent / 'expanded_v3/model/training_report.json').read_text())
    versions[args.experiment] = report
    summary = {}
    for name, value in versions.items():
        metrics = value["validation_metrics"]
        summary[name] = {"status": value["status"], "deployable": value["deployable"],
            "training_rows": value["n_training_rows"], "supervised_class_counts": value["supervised_class_counts"],
            "thresholds": value["thresholds"], "validation_metrics": {key: val for key, val in metrics.items() if key != "details"},
            "artifact_sha256": value["artifact_sha256"]}
    dump(OUT / "comparison.json", {"new_round3_sealed_accessed": False,
        "validation_reused_development_not_independent_final_evidence": True, "results": summary})
    print(json.dumps(summary[args.experiment], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
