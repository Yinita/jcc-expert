"""Trainable observational state forecast, isolated by mode and patch.

Never interprets heuristic scores or external terminal comp rates as personal odds.
Training/calibration/evaluation sets are disjoint by match, with equal match weights.
"""
import hashlib
import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import GroupShuffleSplit

FEATURE_VERSION = 'snapshot-1'


def features(state):
    f = {}
    for key, scale in [('gold', 100), ('hp', 100), ('level', 10), ('xp', 100)]:
        value = state.get(key)
        f[key + '_unknown'] = float(value is None)
        if value is not None:
            f[key] = float(value) / scale
    stage = state.get('stage')
    if stage:
        parts = stage.split('-')
        f['stage'] = int(parts[0]) / 10
        f['round'] = int(parts[1]) / 10
    else:
        f['stage_unknown'] = 1.
    for zone in ['board', 'bench']:
        units = state.get(zone, [])
        f[zone + '_size'] = len(units) / 10
        for u in units:
            hero = str(u['hero_id'])
            f[zone + ':hero:' + hero] = f.get(zone + ':hero:' + hero, 0.) + 1.
            if u.get('stars') is not None:
                f[zone + ':star:' + hero] = f.get(zone + ':star:' + hero, 0.) + u['stars'] / 4
            for item in u.get('item_ids', []):
                f['equipped:' + str(item)] = f.get('equipped:' + str(item), 0.) + 1.
    for field in ['item_ids', 'augment_ids', 'orange_card_ids']:
        for value in state.get(field, []):
            f[field + ':' + str(value)] = f.get(field + ':' + str(value), 0.) + 1.
    if state.get('portal'):
        f['portal:' + state['portal']] = 1.
    # No placement, chosen terminal lineup, result timestamp or selected-candidate label.
    return f


def match_weights(rows):
    counts = Counter(r['match_id'] for r in rows)
    return np.array([1 / counts[r['match_id']] for r in rows])


class ProbabilityModel:
    def __init__(self, model_dir: Path, min_matches=240, min_per_rank=15):
        self.model_dir = model_dir
        model_dir.mkdir(parents=True, exist_ok=True)
        self.min_matches = min_matches
        self.min_per_rank = min_per_rank
        self.lock = threading.Lock()

    def paths(self, mode, patch):
        # Model keys never become arbitrary file paths.
        key = hashlib.sha256((mode + ':' + patch).encode()).hexdigest()[:24]
        return self.model_dir / (key + '.joblib'), self.model_dir / (key + '.json')

    def eligibility(self, rows):
        matches = {}
        for r in rows:
            old = matches.get(r['match_id'])
            if old is not None and old != r['placement']:
                return False, '同一对局名次冲突。'
            matches[r['match_id']] = r['placement']
        counts = Counter(matches.values())
        if len(matches) < self.min_matches:
            return False, f'需要至少{self.min_matches}场独立对局；当前{len(matches)}场。这是初始训练门槛，不代表样本已足以证明提升。'
        if any(counts[i] < self.min_per_rank for i in range(1, 9)):
            return False, f'每个名次需要至少{self.min_per_rank}场独立对局，当前名次分布为{dict(sorted(counts.items()))}。'
        return True, None

    def status(self, mode, patch, rows):
        model_path, meta_path = self.paths(mode, patch)
        eligible, reason = self.eligibility(rows)
        result = {'mode': mode, 'patch': patch, 'observations': len(rows),
                  'unique_matches': len({r['match_id'] for r in rows}),
                  'minimum_matches': self.min_matches, 'can_train': eligible,
                  'status': 'not_trained', 'reason': reason or '数据达到初始训练门槛，可开始训练。',
                  'live_validated': False, 'state_probability': None, 'is_calibrated': False}
        if model_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if hashlib.sha256(model_path.read_bytes()).hexdigest() != meta['artifact_sha256']:
                    result.update(status='artifact_invalid', reason='模型文件校验失败，请重新训练。')
                else:
                    result.update(status=meta['status'], model=meta,
                                  is_calibrated=meta['status'] == 'trained_retrospective_only',
                                  reason=('留出测试未同时优于频率基线，暂停概率输出，请继续采集。' if meta['status'] == 'heldout_underperformed'
                                          else '已完成独立分组留出评估；尚未进行真实对局前瞻验证。'))
            except (OSError, ValueError, KeyError):
                result.update(status='artifact_invalid', reason='模型元数据不可读取。')
        return result

    def train(self, mode, patch, rows):
        eligible, reason = self.eligibility(rows)
        if not eligible:
            return {'status': 'insufficient_data', 'reason': reason, 'state_probability': None}
        if not self.lock.acquire(blocking=False):
            return {'status': 'busy', 'reason': '已有训练正在运行。'}
        try:
            # Reject mixed partitions, demos and unconfirmed states even when used outside HTTP.
            if any(r['state'].get('mode') != mode or r['state'].get('patch') != patch or
                   not r['state'].get('confirmed') or r['state'].get('is_demo') for r in rows):
                return {'status': 'invalid_data', 'reason': '训练数据混入其他模式、版本、未确认或演示状态。'}
            y = np.array([r['placement'] for r in rows])
            groups = np.array([r['match_id'] for r in rows])
            split = None
            for seed in range(50):
                train_idx, remaining = next(GroupShuffleSplit(n_splits=1, test_size=.4, random_state=seed).split(y, y, groups))
                cal_local, test_local = next(GroupShuffleSplit(n_splits=1, test_size=.5, random_state=seed + 100).split(remaining, y[remaining], groups[remaining]))
                cal_idx, test_idx = remaining[cal_local], remaining[test_local]
                if len(set(y[train_idx])) == 8 and all(sum(y[z] == 1) >= 4 and sum(y[z] != 1) >= 4 for z in [cal_idx, test_idx]):
                    split = train_idx, cal_idx, test_idx
                    break
            if split is None:
                return {'status': 'insufficient_data', 'reason': '分组后训练、校准或测试名次覆盖不足，请继续采集。'}
            train_idx, cal_idx, test_idx = split
            partitions = [set(groups[idx]) for idx in split]
            overlap = any(partitions[a] & partitions[b] for a, b in [(0, 1), (0, 2), (1, 2)])
            if overlap:
                raise RuntimeError('Match-group leakage detected')
            vectorizer = DictVectorizer()
            X = vectorizer.fit_transform([features(rows[i]['state']) for i in train_idx])
            classifier = LogisticRegression(C=.5, max_iter=1000)
            weights = match_weights(rows)
            classifier.fit(X, y[train_idx], sample_weight=weights[train_idx])
            first_col = list(classifier.classes_).index(1)

            def raw_predict(indices):
                return classifier.predict_proba(vectorizer.transform([features(rows[i]['state']) for i in indices]))

            raw_cal = raw_predict(cal_idx)
            raw_first = np.clip(raw_cal[:, first_col], 1e-6, 1 - 1e-6)
            calibration = LogisticRegression(C=1., max_iter=1000)
            calibration.fit(np.log(raw_first / (1 - raw_first)).reshape(-1, 1), (y[cal_idx] == 1).astype(int), sample_weight=weights[cal_idx])
            raw_test = raw_predict(test_idx)
            distribution = self.calibrate(raw_test, calibration, first_col)
            baseline = np.array([sum(weights[train_idx][y[train_idx] == k]) for k in classifier.classes_])
            baseline = baseline / baseline.sum()
            truth = (y[test_idx] == 1).astype(int)
            brier = brier_score_loss(truth, distribution[:, first_col], sample_weight=weights[test_idx])
            baseline_brier = brier_score_loss(truth, np.full(len(test_idx), baseline[first_col]), sample_weight=weights[test_idx])
            test_loss = log_loss(y[test_idx], distribution, labels=classifier.classes_, sample_weight=weights[test_idx])
            baseline_loss = log_loss(y[test_idx], np.tile(baseline, (len(test_idx), 1)), labels=classifier.classes_, sample_weight=weights[test_idx])
            eligible_prediction = brier <= baseline_brier and test_loss <= baseline_loss
            stages = sorted({r['state'].get('stage') for r in rows if r['state'].get('stage')})
            stage_coverage = {stage: {name: len({rows[i]['match_id'] for i in indices
                                      if rows[i]['state'].get('stage') == stage})
                                    for name, indices in zip(['train', 'calibration', 'test'], split)} for stage in stages}
            meta = {'status': 'trained_retrospective_only' if eligible_prediction else 'heldout_underperformed',
                    'kind': 'observational_current_state_forecast_not_action_value', 'mode': mode, 'patch': patch,
                    'feature_version': FEATURE_VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'n_observations': len(rows), 'n_unique_matches': len(set(groups)),
                    'split_matches': {name: len(set(groups[idx])) for name, idx in zip(['train', 'calibration', 'test'], split)},
                    'split_group_overlap': overlap, 'equal_match_weights': True,
                    'stage_coverage': stage_coverage,
                    'calibration': 'heldout_first_place_Platt', 'other_placements_calibrated': False,
                    'metrics': {'first_brier': float(brier), 'baseline_first_brier': float(baseline_brier),
                                'placement_log_loss': float(test_loss), 'baseline_placement_log_loss': float(baseline_loss)},
                    'prediction_eligible': bool(eligible_prediction), 'live_validated': False,
                    'limitation': '仅第一率做留出校准，其余名次按原始模型比例分配；这是观察性当前状态预测，不是选择路线的因果收益。'}
            artifact = {'vectorizer': vectorizer, 'classifier': classifier, 'calibration': calibration,
                        'first_col': first_col, 'feature_version': FEATURE_VERSION}
            model_path, meta_path = self.paths(mode, patch)
            tmp = model_path.with_suffix('.tmp')
            joblib.dump(artifact, tmp)
            meta['artifact_sha256'] = hashlib.sha256(tmp.read_bytes()).hexdigest()
            os.replace(tmp, model_path)
            tmp_meta = meta_path.with_suffix('.tmp.json')
            tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
            os.replace(tmp_meta, meta_path)
            return {'status': meta['status'], 'model': meta, 'reason': '训练与分组留出评估完成，尚未做真实对局前瞻验证。'}
        finally:
            self.lock.release()

    @staticmethod
    def calibrate(raw, calibrator, first_col):
        raw = np.asarray(raw, dtype=float)
        first = np.clip(raw[:, first_col], 1e-6, 1 - 1e-6)
        p = calibrator.predict_proba(np.log(first / (1 - first)).reshape(-1, 1))[:, 1]
        result = raw * ((1 - p) / np.maximum(1 - raw[:, first_col], 1e-9))[:, None]
        result[:, first_col] = p
        return result / result.sum(axis=1, keepdims=True)

    def predict(self, state, rows):
        status = self.status(state['mode'], state['patch'], rows)
        if not state.get('confirmed'):
            return {'status': 'needs_confirmation', 'state_probability': None, 'reason': '请先确认识别状态。'}
        if state.get('is_demo'):
            return {'status': 'demo', 'state_probability': None, 'reason': '演示状态不输出真实对局概率。'}
        if any(state.get(k) is None for k in ['stage', 'hp', 'gold', 'level']):
            return {'status': 'incomplete_state', 'state_probability': None, 'reason': '概率预测需要已确认的回合、血量、金币和等级。'}
        if status['status'] != 'trained_retrospective_only':
            return {'status': status['status'], 'state_probability': None, 'reason': status['reason']}
        coverage = status['model'].get('stage_coverage', {}).get(state['stage'], {})
        if not coverage or min(coverage.values()) < 5:
            return {'status': 'unsupported_stage', 'state_probability': None,
                    'reason': '当前回合未在训练、校准、测试中分别覆盖至少5场独立对局，暂不跨回合外推。'}
        model_path, _ = self.paths(state['mode'], state['patch'])
        artifact = joblib.load(model_path)  # Only this process's hash-checked local training output.
        if artifact['feature_version'] != FEATURE_VERSION:
            return {'status': 'incompatible', 'state_probability': None, 'reason': '特征版本变化，需要重新训练。'}
        raw = artifact['classifier'].predict_proba(artifact['vectorizer'].transform([features(state)]))
        distribution = self.calibrate(raw, artifact['calibration'], artifact['first_col'])[0]
        return {'status': 'retrospective_forecast', 'state_probability': float(distribution[artifact['first_col']]),
                'is_calibrated': True, 'calibration_scope': 'first_place_only',
                'placement_distribution': {str(k): float(v) for k, v in zip(artifact['classifier'].classes_, distribution)},
                'kind': 'observational_current_state_forecast_not_action_value', 'live_validated': False,
                'model': status['model'], 'reason': status['model']['limitation']}
