from copy import deepcopy

import numpy as np

from app.probability import ProbabilityModel, features, match_weights


def state(rank=1):
    return {'mode': 'nature', 'patch': '18.6', 'confirmed': True, 'stage': '3-2',
            'hp': 105 - rank * 10, 'gold': 90 - rank * 8, 'level': 10 - rank,
            'board': [{'hero_id': 'synthetic-' + str(rank), 'stars': 2, 'item_ids': []}],
            'bench': [], 'item_ids': [], 'augment_ids': []}


def test_untrained_never_invents_odds(tmp_path):
    m = ProbabilityModel(tmp_path)
    assert m.predict(state(), [])['state_probability'] is None
    assert m.train('nature', '18.6', [])['status'] == 'insufficient_data'


def test_no_future_fields_and_equal_match_weight():
    s = state()
    changed = dict(s, placement=1, selected_candidate_id='winner', final_items=['future'], screenshot_id='abc')
    assert features(s) == features(changed)
    weights = match_weights([{'match_id': 'a'}, {'match_id': 'a'}, {'match_id': 'b'}])
    assert np.allclose(weights, [.5, .5, 1.])


def test_end_to_end_grouped_training_and_artifact_integrity(tmp_path):
    # Synthetic separable data tests the machinery, never real-game performance.
    rows = []
    for i in range(320):
        rank = i % 8 + 1
        for checkpoint in range(2):
            s = state(rank)
            s['gold'] += checkpoint
            rows.append({'match_id': f'synthetic-{i}', 'placement': rank, 'state': s})
    m = ProbabilityModel(tmp_path)
    result = m.train('nature', '18.6', rows)
    assert result['status'] == 'trained_retrospective_only'
    meta = result['model']
    assert sum(meta['split_matches'].values()) == 320
    assert meta['n_observations'] == 640
    assert meta['split_group_overlap'] is False
    assert meta['live_validated'] is False
    prediction = m.predict(state(), rows)
    assert prediction['kind'] == 'observational_current_state_forecast_not_action_value'
    assert abs(sum(prediction['placement_distribution'].values()) - 1) < 1e-8
    assert prediction['state_probability'] > 0
    assert m.predict(dict(state(), is_demo=True), rows)['state_probability'] is None
    assert m.predict(dict(state(), hp=None), rows)['state_probability'] is None
    assert m.predict(dict(state(), stage='2-1'), rows)['status'] == 'unsupported_stage'
    path, _ = m.paths('nature', '18.6')
    path.write_bytes(b'corrupted artifact')
    assert m.predict(state(), rows)['status'] == 'artifact_invalid'


def test_training_rejects_mixed_modes(tmp_path):
    rows = [{'match_id': f'x{i}', 'placement': i % 8 + 1, 'state': state(i % 8 + 1)} for i in range(320)]
    rows[-1]['state']['mode'] = 'orange'
    assert ProbabilityModel(tmp_path).train('nature', '18.6', rows)['status'] == 'invalid_data'
