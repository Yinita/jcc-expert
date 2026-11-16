"""Synthetic contracts for the learned field model; not screenshot accuracy."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import joblib
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.field_model import FieldModel, FEATURE_VERSION, artifact_key, parse_value, predict_artifact, normalize_screen_type

spec = importlib.util.spec_from_file_location("train_field_model", ROOT/"scripts/train_field_model.py")
trainer = importlib.util.module_from_spec(spec); spec.loader.exec_module(trainer)


def fixture_samples():
    boxes = {"stage": [.40,.01,.12,.05], "gold": [.47,.85,.08,.06], "hp": [.88,.14,.08,.05], "level": [.05,.83,.06,.06]}
    lines = [{"text": text, "bbox": boxes[field], "confidence": .99} for field, text in
             [("stage", "3-2"), ("gold", "36"), ("hp", "87"), ("level", "6")]]
    lines += [{"text": "总价值300", "bbox": [.50,.50,.20,.06], "confidence": .99}]
    samples, records = [], {}
    for i, partition in enumerate(["train", "train", "calibration", "calibration", "validation", "validation"]):
        sid = f"fixture-{i}"
        samples.append({"id":sid,"group_id":sid,"mode":"nature","partition":partition,"screen_type":"board",
                        "labels":{"stage":"3-2","gold":36,"hp":87,"level":6},"field_boxes":boxes,
                        "negative_boxes":[[.49,.49,.23,.09]]})
        records[sid] = {"lines": lines, "shape": (1000,1600,3)}
    return samples, records


def test_values_come_from_parseable_ocr_only():
    assert parse_value("GOLD: 36", "gold") == 36
    assert parse_value("6级", "level") == 6
    assert parse_value("3—2", "stage") == "3-2"
    assert parse_value("9999", "gold") is None
    assert parse_value("O6", "level") is None
    assert parse_value("300", "hp") is None
    assert parse_value("9", "level") == 9


def test_unreliable_labels_do_not_create_negatives():
    sample = {"id":"a","mode":"nature","group_id":"g","labels":{"gold":36}}
    rows, ignored = trainer.supervised_rows(sample,[{"text":"36","bbox":[.5,.8,.05,.05],"confidence":.99}],(100,160,3))
    assert rows == [] and ignored["unlabelled_line"] == 1


def test_wrong_ocr_inside_positive_box_is_not_other():
    sample = {"id":"a","mode":"nature","group_id":"g","labels":{"gold":36},"field_boxes":{"gold":[.5,.8,.05,.05]}}
    rows, ignored = trainer.supervised_rows(sample,[{"text":"38","bbox":[.5,.8,.05,.05],"confidence":.99}],(100,160,3))
    assert rows == [] and ignored["unreadable_or_mismatching_positive"] == 1


def test_repeated_full_image_and_crop_ocr_do_not_duplicate_scalar_supervision():
    sample = {"id":"a", "mode":"nature", "group_id":"g", "labels":{"stage":"3-2"},
              "field_boxes":{"stage":[.40,.01,.12,.05]}}
    lines = [{"text":"3-2", "bbox":[.40,.01,.12,.05], "confidence":.99},
             {"text":"3-2", "bbox":[.405,.012,.11,.045], "confidence":.97}]
    rows, ignored = trainer.supervised_rows(sample, lines, (100,160,3))
    assert len(rows) == 1 and rows[0]["label"] == "stage"
    assert ignored["duplicate_supervision_removed"] == 1


def test_tight_manual_digit_roi_accepts_matching_ocr_with_level_suffix():
    # Manually enclosed digit 3 is narrower than RapidOCR's complete "3级" row.
    digit = [.185938,.784722,.007812,.023611]
    line = {"text":"3级", "bbox":[.1828,.7764,.0258,.0333], "confidence":.99}
    sample = {"id":"a", "mode":"nature", "group_id":"g", "labels":{"level":3},
              "field_boxes":{"level":digit}}
    rows, ignored = trainer.supervised_rows(sample, [line], (720,1280,3))
    assert [row["label"] for row in rows] == ["level"]
    assert rows[0]["supervision_method"] == "tight_digit_roi"
    assert not trainer.positive_overlap(line["bbox"], digit)  # evaluation unchanged


def test_wrong_digit_in_tight_positive_roi_never_becomes_other():
    sample = {"id":"a", "mode":"nature", "group_id":"g", "labels":{"level":3},
              "field_boxes":{"level":[.185938,.784722,.007812,.023611]},
              "negative_boxes":[[.1,.7,.3,.2]]}
    rows, ignored = trainer.supervised_rows(sample,
        [{"text":"8级", "bbox":[.1828,.7764,.0258,.0333], "confidence":.99}], (720,1280,3))
    assert rows == [] and ignored["unreadable_or_mismatching_positive"] == 1


def test_positive_only_calibration_cannot_sharpen_or_enable_output(tmp_path):
    samples, records = fixture_samples()
    for sample in samples:
        if sample["partition"] == "calibration":
            sample["negative_boxes"] = []
    report = trainer.train(samples, records, "nature", "18.6", tmp_path)
    assert report["temperature"] == 1
    assert report["calibration"]["status"] == "unavailable_no_explicit_other"
    assert all(value > 1 for value in report["thresholds"].values())
    assert report["validation_metrics"]["correct"] == 0
    assert report["deployable"] is False


def test_sealed_sample_is_skipped_before_its_file_or_labels(tmp_path):
    path=tmp_path/"annotations.json"
    path.write_text(json.dumps({"samples":[{"split":"sealed_test","file":"/does-not-exist.png","labels":"not even a valid labels object"}]}))
    samples, skipped=trainer.load_samples([path],"both")
    assert samples == [] and skipped == 1


@pytest.mark.parametrize("seal", [{"split":"holdout","evaluation_role":"sealed_test"},
                                  {"split":"holdout","sealed_test":True}])
def test_role_or_boolean_only_seal_precedes_file_or_label_access(tmp_path,seal):
    path=tmp_path/"annotations.json"
    path.write_text(json.dumps({"samples":[{**seal,"file":"/does-not-exist.png","mode":"nature","labels":"invalid"}]}))
    samples,skipped=trainer.load_samples([path],"both")
    assert samples == [] and skipped == 1


def test_group_cannot_cross_partitions():
    with pytest.raises(ValueError):
        trainer.assign_partitions([{"group_id":"same","split":"train"},{"group_id":"same","split":"validation"}])


def test_five_source_groups_reserve_two_independent_validation_groups():
    samples=[{"group_id":f"source-{i}","split":"consumed_development"}for i in range(5)]
    plan=trainer.assign_partitions(samples)
    assert list(plan.values()).count("train")==2
    assert list(plan.values()).count("calibration")==1
    assert list(plan.values()).count("validation")==2


def test_ui_screen_aliases_share_training_features():
    assert all(normalize_screen_type(s)=="board" for s in ["board","gameplay","battle","preparation","gameplay_candidate"])
    assert normalize_screen_type("unknown")=="unknown"
    assert normalize_screen_type("inventory")==normalize_screen_type("orange_card_collection")


def test_small_data_trains_real_candidate_but_does_not_activate(tmp_path):
    samples, records=fixture_samples()
    report=trainer.train(samples,records,"nature","18.6",tmp_path,min_validation_answers=1000)
    assert report["status"] == "candidate_unvalidated"
    assert report["deployable"] is False
    artifact=joblib.load(report["artifact"])
    assert hasattr(artifact["classifier"],"coef_")
    assert len(artifact["classifier"].classes_) == 5
    assert report["n_training_rows"] == 10
    assert "validation_metrics" in report and "unvalidated_preview_validation_metrics" in report
    assert FieldModel(tmp_path).predict(records[samples[0]["id"]]["lines"],(1000,1600,3),"nature","board") == []


def test_hash_and_feature_isolation_and_ocr_provenance(tmp_path):
    samples,records=fixture_samples();report=trainer.train(samples,records,"nature","18.6",tmp_path,min_validation_answers=1000)
    artifact=joblib.load(report["artifact"])
    key=artifact_key("nature","18.6");model_path=tmp_path/(key+".joblib");joblib.dump(artifact,model_path)
    meta={"status":"ready","deployable":True,"mode":"nature","patch":"18.6","feature_version":FEATURE_VERSION,
          "model_id":"synthetic-test-only","artifact_sha256":hashlib.sha256(model_path.read_bytes()).hexdigest(),
          "thresholds":{f:0. for f in ["stage","gold","hp","level"]},"calibration_method":"synthetic_fixture"}
    meta_path=tmp_path/(key+".json");meta_path.write_text(json.dumps(meta))
    model=FieldModel(tmp_path);lines=records[samples[0]["id"]]["lines"]
    predicted=model.predict(lines,(1000,1600,3),"nature","board")
    assert predicted
    for row in predicted:
        assert row["value"] == parse_value(row["text"],row["field"])
        assert row["requires_confirmation"] is True
        assert row["provenance"]["value_source"] == "parseable_OCR_text"
        assert row["calibration"]["score_is_win_probability"] is False
    assert model.predict(lines,(1000,1600,3),"orange","board") == []
    model_path.write_bytes(b"tampered")
    assert model.predict(lines,(1000,1600,3),"nature","board") == []


def test_no_model_is_clean_abstention(tmp_path):
    assert FieldModel(tmp_path).predict([], (100,160,3), "nature", "board") == []


def test_new_feedback_uses_same_automatic_hud_preprocessing_and_cache(tmp_path, monkeypatch):
    from PIL import Image
    from app import ocr_backend
    class Backend:
        name="fixture-only"
        calls=0
        def read(self, image):
            self.calls+=1
            if self.calls==1:return [],None
            return [{"text":"3-2","confidence":.99,"bbox":[.1,.1,.2,.1]}],None
    backend=Backend()
    monkeypatch.setattr(ocr_backend,"get_ocr_backend",lambda:backend)
    path=tmp_path/"phone.png";Image.new("RGB",(1000,500)).save(path)
    sample={"file":str(path)}
    lines,shape,provenance=trainer.read_lines(sample,tmp_path/"cache")
    assert backend.calls==4 and len(lines)==3
    assert all(row["pass"]=="automatic_small_ui" for row in lines)
    assert tuple(shape)==(500,1000,3)
    assert trainer.read_lines(sample,tmp_path/"cache")[0]==lines
    assert backend.calls==4
