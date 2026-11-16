"""Tests of evaluation accounting; these are not game-image accuracy claims."""
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("screenshot_evaluation", ROOT / "scripts/evaluate_screenshots.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def test_unknown_labels_never_count_as_correct():
    outcomes = ev.evaluate_fields({"stage": None, "gold": 40, "shop": [None, "123"]},
                                  {"stage": None, "gold": None, "hp": 87, "shop": [None, "999"]})
    metrics = ev.summarize_outcomes(outcomes)
    assert metrics["correct"] == 0
    assert metrics["wrong"] == 1
    assert metrics["abstain"] == 1
    assert metrics["unlabelled"] == 7
    assert metrics["coverage"] == .5
    assert metrics["precision"] == 0


def test_all_abstentions_have_zero_coverage_and_undefined_precision():
    metrics = ev.summarize_outcomes(ev.evaluate_fields({"gold": 0, "hp": 87}, {}))
    assert metrics["labelled"] == 2
    assert metrics["abstain"] == 2
    assert metrics["coverage"] == 0
    assert metrics["precision"] is None
    assert metrics["end_to_end_correct_rate"] == 0


def test_zero_label_and_explicit_empty_are_not_unknown():
    metrics = ev.summarize_outcomes(ev.evaluate_fields({"gold": 0, "shop": [{"empty": True}]}, {"gold": 0, "shop": [None]}))
    assert metrics["correct"] == 1
    assert metrics["abstain"] == 1
    metrics = ev.summarize_outcomes(ev.evaluate_fields({"shop": [{"empty": True}]}, {"shop": [{"empty": True}]}))
    assert metrics["correct"] == 1


def test_invalid_prediction_is_wrong_instead_of_abstain():
    metrics = ev.summarize_outcomes(ev.evaluate_fields({"level": 6}, {"level": "six"}))
    assert metrics["wrong"] == 1
    assert metrics["abstain"] == 0


def test_duplicate_decode_and_group_cannot_cross_split(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (100, 100), "white").save(image)
    annotation = tmp_path / "a.json"
    annotation.write_text(json.dumps({"samples": [
        {"id": "a", "file": "a.png", "mode": "nature", "split": "development", "group_id": "a"},
        {"id": "b", "file": "a.png", "mode": "nature", "split": "holdout", "group_id": "b"}]}))
    with pytest.raises(ValueError, match="Exact decoded"):
        ev.load_annotations(annotation)


def test_crop_group_must_match_original(tmp_path):
    Image.new("RGB", (100, 100), "white").save(tmp_path / "a.png")
    Image.new("RGB", (40, 40), "white").save(tmp_path / "b.png")
    annotation = tmp_path / "a.json"
    annotation.write_text(json.dumps({"samples": [
        {"id": "a", "file": "a.png", "mode": "nature", "group_id": "original"},
        {"id": "b", "file": "b.png", "mode": "nature", "group_id": "crop", "crop_of": "a"}]}))
    with pytest.raises(ValueError, match="share group_id"):
        ev.load_annotations(annotation)


def test_fake_recognizer_tracks_raw_and_no_images_in_report(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (100, 100), "white").save(image)
    annotation = tmp_path / "annotations.json"
    annotation.write_text(json.dumps({"samples": [{"id": "<script>alert(1)</script>", "file": "a.png", "mode": "nature",
        "group_id": "screen-a", "source_url": "javascript:alert(1)", "labels": {"gold": 42, "hp": 80},
        "layout_profile": {"slots": []}}]}))
    _, samples = ev.load_annotations(annotation)

    class FakeRecognizer:
        def __init__(self, data_dir, assets_dir):
            pass

        def recognize(self, path, mode, profile):
            return {"state": {"mode": mode, "confirmed": False, "gold": 42 if profile is not None else None, "hp": 99},
                    "evidence": []}

    checker = lambda state: {"recognition_unconfirmed": True, "personal_probability_is_null": True,
                             "recommendation_status": "needs_confirmation", "passed": True}
    runs = ev.evaluate_samples(samples, FakeRecognizer, tmp_path, tmp_path, tmp_path / "out", checker)
    assert len(runs) == 2
    assert (tmp_path / "out" / runs[0]["raw_file"]).is_file()
    report = ev.build_report(samples, runs, {"recognizer_sha256": "test", "annotations_sha256": "test"})
    assert report["tracks"]["default"]["wrong"] == 1
    assert report["tracks"]["default"]["abstain"] == 1
    assert report["tracks"]["profile"]["correct"] == 1
    assert report["tracks"]["profile"]["wrong"] == 1
    output = ev.render_html(report)
    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;" in output
    assert "<img" not in output
    assert 'href="javascript:' not in output


def test_missing_profile_is_skipped_instead_of_repeating_default(tmp_path):
    run = {"status": "not_run_no_profile", "sample_id": "a", "group_id": "a", "outcomes": []}
    metrics = ev.summarize_runs([run])
    assert metrics["samples"] == 0
    assert metrics["precision"] is None
    assert metrics["labelled"] == 0
