#!/usr/bin/env python3
"""Paired default-only evaluation. Both revisions share the pinned OCR runtime.

The baseline retains its own preprocessing/postprocessing; its subprocess startup
time is deliberately not reconstructed. Latency is descriptive, not a speedup
benchmark. An optional frozen manifest prevents tuning during a sealed run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import evaluate_screenshots as ev


def verify_freeze(path):
    payload = json.loads(path.read_text())
    for entry in payload["files"]:
        if ev.sha256_file(entry["file"]) != entry["sha256"]:
            raise ValueError(f"Frozen artifact changed: {entry['file']}")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    frozen = verify_freeze(args.freeze) if args.freeze else None
    payload, samples = ev.load_annotations(args.annotations)
    if not all(s["grouping_explicit"] for s in samples):
        raise ValueError("All samples need explicit source groups")
    for sample in samples:
        sample.pop("layout_profile", None)
    revisions = {"baseline": args.baseline, "optimized": ROOT / "app/vision.py"}
    recognizers = {key: ev.load_recognizer(module)(ROOT / "app/data", ROOT / "app/assets")
                   for key, module in revisions.items()}
    runs = {key: [] for key in revisions}
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jcc-expanded-") as temporary:
        check = ev.create_contract_checker(ROOT / "app/data", Path(temporary) / "models")
        for sample in samples:
            for revision in revisions:
                factory = lambda *_args, instance=recognizers[revision]: instance
                runs[revision].extend(ev.evaluate_samples([sample], factory, ROOT / "app/data",
                                                        ROOT / "app/assets", args.output / revision, check))
                (args.output / "checkpoint.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    reports = {}
    for revision, module in revisions.items():
        metadata = {"recognizer_module": str(module.resolve()), "recognizer_sha256": ev.sha256_file(module),
                    "annotations_sha256": ev.sha256_file(args.annotations), "sample_count": len(samples),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "annotation_metadata": {k: v for k, v in payload.items() if k != "samples"},
                    "paired_shared_ocr_runtime": True, "default_only": True,
                    "performance_comparison_eligible": False,
                    "freeze_sha256": ev.sha256_file(args.freeze) if frozen else None,
                    "runtime": ev.environment_metadata()}
        reports[revision] = ev.build_report(samples, runs[revision], metadata)
        folder = args.output / revision
        (folder / "report.json").write_text(json.dumps(reports[revision], ensure_ascii=False, indent=2))
        (folder / "report.html").write_text(ev.render_html(reports[revision]))
    if args.freeze:
        verify_freeze(args.freeze)
    summary = {"images": len(samples), "source_groups": len({s["group_id"] for s in samples}),
               "freeze_verified_before_and_after": bool(frozen),
               "revisions": {key: report["tracks"]["default"] for key, report in reports.items()}}
    (args.output / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({key: {k: m[k] for k in ("correct", "wrong", "abstain", "recognition_errors")}
                      for key, m in summary["revisions"].items()}, ensure_ascii=False))
    return int(any(r["tracks"]["default"]["recognition_errors"] or
                   r["tracks"]["default"]["safety_contract_failures"] for r in reports.values()))


if __name__ == "__main__":
    raise SystemExit(main())
