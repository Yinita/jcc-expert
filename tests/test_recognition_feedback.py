import io,json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app


def test_feedback_requires_manual_truth_and_deduplicates_images(tmp_path):
    app=create_app(Path(__file__).resolve().parents[1]/'app/data',tmp_path)
    client=TestClient(app)
    blob=io.BytesIO();Image.new('RGB',(640,360),'#233040').save(blob,'PNG')
    with patch('app.main.ScreenshotRecognizer.recognize',return_value={'state':{'mode':'nature','patch':'18.6'},'evidence':[]}):
        result=client.post('/api/recognize',data={'mode':'nature'},files={'file':('screen.png',blob.getvalue(),'image/png')}).json()
    state=result['state'];state.update(gold=50,match_id='game-a')
    profile={'aspect_ratio':640/360,'slots':[{'field':'gold','bbox':[.8,.7,.1,.1]}]}
    payload={'state':state,'layout_profile':profile}
    assert client.post('/api/recognition/feedback',json=payload).status_code==422
    state['confirmed']=True
    assert client.post('/api/recognition/feedback',json=payload).status_code==200
    assert client.post('/api/recognition/feedback',json=payload).status_code==200
    labels=list((tmp_path/'recognition_labels').glob('*.json'));assert len(labels)==1
    saved=json.loads(labels[0].read_text())['samples'][0]
    assert saved['labels']=={'gold':50} and saved['group_id']=='user:game-a'
    assert saved['not_win_probability_training'] is True
    assert client.get('/api/history').json()['total']==0
    state['match_id']='game-b'
    assert client.post('/api/recognition/feedback',json=payload).status_code==422
    state.update(match_id='game-a',is_demo=True)
    assert client.post('/api/recognition/feedback',json=payload).status_code==422


def test_no_known_scalar_or_wrong_aspect_is_rejected(tmp_path):
    app=create_app(Path(__file__).resolve().parents[1]/'app/data',tmp_path);client=TestClient(app)
    blob=io.BytesIO();Image.new('RGB',(640,360),'#233040').save(blob,'PNG')
    with patch('app.main.ScreenshotRecognizer.recognize',return_value={'state':{'mode':'nature','patch':'18.6'},'evidence':[]}):
        result=client.post('/api/recognize',data={'mode':'nature'},files={'file':('screen.png',blob.getvalue(),'image/png')}).json()
    state=result['state'];state['confirmed']=True
    profile={'slots':[{'field':'gold','bbox':[.8,.7,.1,.1]}]}
    assert client.post('/api/recognition/feedback',json={'state':state,'layout_profile':profile}).status_code==422
    state['gold']=50;profile['aspect_ratio']=1.
    assert client.post('/api/recognition/feedback',json={'state':state,'layout_profile':profile}).status_code==422

# Protocol fixtures below are synthetic images, never real training observations.
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from PIL.PngImagePlugin import PngInfo
from app.storage import EventStore

DATA_DIR = Path(__file__).resolve().parents[1] / 'app/data'
PROFILE = {'aspect_ratio': 640/360, 'slots': [{'field': 'gold', 'bbox': [.8, .7, .1, .1]}]}


def _picture(encoding='PNG', metadata=False):
    image = Image.new('RGB', (640, 360), '#233040')
    blob = io.BytesIO()
    if encoding == 'WEBP':
        image.save(blob, 'WEBP', lossless=True)
    else:
        info = PngInfo()
        if metadata:
            info.add_text('description', 'different encoding metadata, identical RGB pixels')
        image.save(blob, 'PNG', pnginfo=info, compress_level=0 if metadata else 9)
    return blob.getvalue()


def _upload(client, blob=None, encoding='PNG'):
    value = {'state': {'mode': 'nature', 'patch': '18.6'}, 'evidence': []}
    with patch('app.main.ScreenshotRecognizer.recognize', return_value=value):
        response = client.post('/api/recognize', data={'mode': 'nature'}, files={
            'file': ('screen.' + encoding.lower(), blob or _picture(encoding), 'image/' + encoding.lower())})
    assert response.status_code == 200, response.text
    state = response.json()['state']
    state.update(confirmed=True, is_demo=False, stage='3-2', hp=80, gold=50, level=5,
                 board=[{'hero_id': '11500', 'stars': 1, 'item_ids': []}])
    return state


def _feedback(client, state, match_id, gold=50):
    state = deepcopy(state)
    state.update(match_id=match_id, gold=gold)
    return client.post('/api/recognition/feedback', json={'state': state, 'layout_profile': PROFILE})


def _outcome(client, state, match_id):
    state = deepcopy(state)
    state['match_id'] = match_id
    return client.post('/api/matches/events', json={'state': state, 'match_id': match_id, 'placement': 2})


def _legacy_state(screenshot_id, match_id):
    return {'mode': 'nature', 'patch': '18.6', 'screenshot_id': screenshot_id,
            'match_id': match_id, 'confirmed': True, 'is_demo': False,
            'stage': '3-2', 'hp': 80, 'gold': 50, 'level': 5,
            'board': [{'hero_id': '11500', 'stars': 1, 'item_ids': []}],
            'bench': [], 'shop': [], 'item_ids': [], 'augment_ids': []}


def _insert_legacy_event(store, screenshot_id, match_id):
    with store.connect() as db:
        db.execute('''INSERT INTO events
            (match_id,snapshot_key,mode,patch,placement,state_json,created_at)
            VALUES(?,?,?,?,?,?,?)''', (match_id, screenshot_id, 'nature', '18.6', 2,
                json.dumps(_legacy_state(screenshot_id, match_id)), '2026-11-11T00:00:00+00:00'))


def test_result_binding_is_respected_by_feedback_and_same_group_can_correct(tmp_path):
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    state = _upload(client)
    assert _outcome(client, state, 'game-a').status_code == 200
    assert _feedback(client, state, 'game-b').status_code == 422
    assert not list((tmp_path/'recognition_labels').glob('*.json'))
    assert _feedback(client, state, 'game-a').status_code == 200
    assert _feedback(client, state, 'game-a', gold=47).status_code == 200
    saved = json.loads(next((tmp_path/'recognition_labels').glob('*.json')).read_text())['samples'][0]
    assert saved['labels'] == {'gold': 47} and saved['group_id'] == 'user:game-a'
    assert client.get('/api/history').json()['total'] == 1


def test_feedback_binding_is_respected_by_outcome_without_creating_event(tmp_path):
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    state = _upload(client)
    assert _feedback(client, state, 'game-a').status_code == 200
    assert client.get('/api/history').json()['total'] == 0
    assert _outcome(client, state, 'game-b').status_code == 422
    assert _outcome(client, state, 'game-a').status_code == 200
    assert client.get('/api/history').json()['total'] == 1


@pytest.mark.parametrize('match_id', [None, '', '   '])
def test_feedback_rejects_missing_or_blank_match_id(tmp_path, match_id):
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    state = _upload(client)
    assert _feedback(client, state, match_id).status_code == 422
    assert not list((tmp_path/'recognition_labels').glob('*.json'))
    with app.state.events.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM screenshot_source_bindings').fetchone()[0] == 0


def test_reupload_same_pixels_different_metadata_and_encoding_keeps_one_source(tmp_path):
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    original = _upload(client)
    metadata = _upload(client, _picture(metadata=True))
    webp = _upload(client, encoding='WEBP')
    assert len({s['screenshot_id'] for s in [original, metadata, webp]}) == 3
    with app.state.events.connect() as db:
        hashes = {r['content_hash'] for r in db.execute('SELECT content_hash FROM screenshots')}
    assert len(hashes) == 1 and next(iter(hashes)).startswith('rgb-v1:')
    assert _feedback(client, original, 'game-a').status_code == 200
    assert _feedback(client, metadata, 'game-b').status_code == 422
    assert _outcome(client, webp, 'game-b').status_code == 422
    assert _feedback(client, webp, 'game-a', gold=48).status_code == 200
    assert len(list((tmp_path/'recognition_labels').glob('*.json'))) == 1
    assert _outcome(client, original, 'game-a').status_code == 200
    assert _outcome(client, webp, 'game-a').status_code == 200
    assert client.get('/api/history').json()['total'] == 1


def test_legacy_event_migrates_pixel_hash_and_blocks_conflicting_reupload(tmp_path):
    uploads = tmp_path/'screenshots'; uploads.mkdir()
    screenshot_id = 'a' * 32
    path = uploads/(screenshot_id+'.png'); path.write_bytes(_picture(metadata=True))
    store = EventStore(tmp_path/'events.sqlite3')
    old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    store.register_screenshot(screenshot_id, 'nature', old_hash)
    _insert_legacy_event(store, screenshot_id, 'legacy-game')
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    with app.state.events.connect() as db:
        migrated = db.execute('SELECT content_hash FROM screenshots WHERE id=?', (screenshot_id,)).fetchone()[0]
    assert migrated.startswith('rgb-v1:') and migrated != old_hash
    reuploaded = _upload(client, encoding='WEBP')
    assert _feedback(client, reuploaded, 'different-game').status_code == 422
    assert _outcome(client, reuploaded, 'different-game').status_code == 422
    assert _feedback(client, reuploaded, 'legacy-game').status_code == 200
    assert _outcome(client, reuploaded, 'legacy-game').status_code == 200
    assert client.get('/api/history').json()['total'] == 1


@pytest.mark.parametrize('legacy_match', ['legacy-game', 'unassigned'])
def test_existing_feedback_json_group_is_never_reassigned(tmp_path, legacy_match):
    uploads = tmp_path/'screenshots'; labels = tmp_path/'recognition_labels'
    uploads.mkdir(); labels.mkdir()
    screenshot_id = 'b' * 32
    image = uploads/(screenshot_id+'.png'); image.write_bytes(_picture(metadata=True))
    old_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    store = EventStore(tmp_path/'events.sqlite3')
    store.register_screenshot(screenshot_id, 'nature', old_hash)
    legacy_path = labels/(old_hash+'.json')
    document = {'samples': [{'id': 'old-label', 'file': str(image.resolve()), 'mode': 'nature',
        'patch': '18.6', 'group_id': 'user:'+legacy_match, 'labels': {'gold': 50},
        'field_boxes': {'gold': [.8, .7, .1, .1]}}]}
    legacy_path.write_text(json.dumps(document)); original_json = legacy_path.read_bytes()
    app = create_app(DATA_DIR, tmp_path)
    client = TestClient(app)
    state = _upload(client, encoding='WEBP')
    assert _feedback(client, state, 'new-game').status_code == 422
    assert _outcome(client, state, 'new-game').status_code == 422
    assert legacy_path.read_bytes() == original_json
    if legacy_match != 'unassigned':
        assert _feedback(client, state, legacy_match, gold=45).status_code == 200
        assert len(list(labels.glob('*.json'))) == 1
        updated = json.loads(legacy_path.read_text())['samples'][0]
        assert updated['group_id'] == 'user:legacy-game' and updated['labels'] == {'gold': 45}
        assert _outcome(client, state, legacy_match).status_code == 200


def test_missing_legacy_screenshot_does_not_break_startup_or_erase_binding(tmp_path):
    store = EventStore(tmp_path/'events.sqlite3'); screenshot_id = 'c' * 32
    store.register_screenshot(screenshot_id, 'nature', 'legacy-byte-hash')
    _insert_legacy_event(store, screenshot_id, 'legacy-game')
    app = create_app(DATA_DIR, tmp_path)
    assert TestClient(app).get('/api/health').status_code == 200
    with pytest.raises(ValueError):
        app.state.events.bind_screenshot(screenshot_id, 'new-game', 'nature', '18.6')
    assert app.state.events.bind_screenshot(screenshot_id, 'legacy-game', 'nature', '18.6')['match_id'] == 'legacy-game'


def test_storage_binding_rejects_match_mode_patch_conflicts(tmp_path):
    store = EventStore(tmp_path/'events.sqlite3')
    for sid, mode in [('a', 'nature'), ('b', 'nature'), ('c', 'orange')]:
        store.register_screenshot(sid, mode, 'same-pixels')
    store.bind_screenshot('a', 'game-a', 'nature', '18.6')
    for sid, match, mode, version in [('b', 'game-b', 'nature', '18.6'),
            ('b', 'game-a', 'nature', '18.5'), ('c', 'game-a', 'orange', '18.6')]:
        with pytest.raises(ValueError):
            store.bind_screenshot(sid, match, mode, version)
    with pytest.raises(ValueError):
        store.bind_screenshot('b', '  ', 'nature', '18.6')
    assert store.bind_screenshot('b', 'game-a', 'nature', '18.6')['snapshot_id'] == 'a'


def test_two_store_instances_concurrently_bind_only_one_group(tmp_path):
    path = tmp_path/'events.sqlite3'; first, second = EventStore(path), EventStore(path)
    first.register_screenshot('a', 'nature', 'same-pixels')
    first.register_screenshot('b', 'nature', 'same-pixels')
    barrier = threading.Barrier(2)
    def attempt(store, sid, match):
        barrier.wait()
        try:
            store.bind_screenshot(sid, match, 'nature', '18.6')
            return 'saved'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, first, 'a', 'game-a'), pool.submit(attempt, second, 'b', 'game-b')]
        assert sorted(f.result(timeout=15) for f in futures) == ['conflict', 'saved']
    with first.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM screenshot_source_bindings').fetchone()[0] == 1


def test_api_feedback_and_result_concurrent_different_groups_cannot_both_succeed(tmp_path):
    app = create_app(DATA_DIR, tmp_path)
    with TestClient(app) as client:
        state = _upload(client); barrier = threading.Barrier(2)
        def feedback():
            barrier.wait()
            return _feedback(client, state, 'feedback-game').status_code
        def outcome():
            barrier.wait()
            return _outcome(client, state, 'outcome-game').status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(feedback), pool.submit(outcome)]
            assert sorted(f.result(timeout=20) for f in futures) == [200, 422]
    with app.state.events.connect() as db:
        bound = db.execute('SELECT match_id FROM screenshot_source_bindings').fetchall()
    assert len(bound) == 1
    label_files = list((tmp_path/'recognition_labels').glob('*.json'))
    if label_files:
        assert json.loads(label_files[0].read_text())['samples'][0]['group_id'] == 'user:'+bound[0]['match_id']
