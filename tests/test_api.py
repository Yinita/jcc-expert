import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    data = Path(__file__).resolve().parents[1] / 'app' / 'data'
    return TestClient(create_app(data, tmp_path))


def image_bytes():
    buffer = io.BytesIO()
    Image.new('RGB', (640, 360), '#263641').save(buffer, format='PNG')
    return buffer.getvalue()


def test_api_catalog_demo_and_no_fabricated_model(client):
    assert client.get('/api/health').json()['ok']
    for mode in ['nature', 'orange']:
        catalog = client.get('/api/catalog', params={'mode': mode}).json()
        assert catalog['heroes']
        cached_icon = next((h['icon_url'] for h in catalog['heroes'] if h.get('icon_url')), None)
        if cached_icon:
            assert cached_icon.startswith('/assets/')
            assert client.get(cached_icon).status_code == 200
        demo = client.get('/api/demo', params={'mode': mode}).json()
        assert demo['is_demo'] and not demo['confirmed']
        result = client.post('/api/recommend', json=demo)
        assert result.status_code == 200
        assert result.json()['state_probability'] is None
    result = client.post('/api/model/train', json={'mode': 'nature', 'patch': '18.6'})
    assert result.json()['status'] == 'insufficient_data'


def test_upload_validation_and_mode_isolation(client):
    assert client.post('/api/recognize', files={'file': ('bad.png', b'not an image', 'image/png')}).status_code == 422
    response = client.post('/api/recognize', data={'mode': 'nature'}, files={'file': ('s.png', image_bytes(), 'image/png')})
    assert response.status_code == 200
    data = response.json()
    assert data['state']['confirmed'] is False
    assert client.get(data['image_url']).status_code == 200
    changed = dict(data['state'], mode='orange')
    assert client.post('/api/recommend', json=changed).status_code == 422


def test_result_confirmation_dedup_and_demo_exclusion(client):
    upload = client.post('/api/recognize', data={'mode': 'nature'}, files={'file': ('s.png', image_bytes(), 'image/png')}).json()
    state = client.get('/api/demo', params={'mode': 'nature'}).json()
    state.update(screenshot_id=upload['screenshot_id'], match_id='game-1', stage='3-2')
    event = {'state': state, 'placement': 2, 'match_id': 'game-1'}
    assert client.post('/api/matches/events', json=event).status_code == 422
    state.update(is_demo=False, confirmed=True)
    assert client.post('/api/matches/events', json=event).status_code == 200
    assert client.post('/api/matches/events', json=event).status_code == 200
    assert client.get('/api/history').json()['total'] == 1
    event['match_id'] = state['match_id'] = 'game-2'
    assert client.post('/api/matches/events', json=event).status_code == 422
    state['match_id'] = event['match_id'] = 'game-1'
    second = client.post('/api/recognize', data={'mode': 'nature'}, files={'file': ('same.png', image_bytes(), 'image/png')}).json()
    state['screenshot_id'] = second['screenshot_id']
    assert client.post('/api/matches/events', json=event).status_code == 200
    assert client.get('/api/history').json()['total'] == 1
    state['board'][0]['hero_id'] = '2' + state['board'][0]['hero_id'][1:]
    assert client.post('/api/matches/events', json=event).status_code == 200
    saved = client.app.state.events.dataset('nature', '18.6')[0]['state']
    assert saved['board'][0]['hero_id'].startswith('1')
    event['placement'] = 1
    assert client.post('/api/matches/events', json=event).status_code == 422


def test_cross_site_writes_and_profile_bounds(client):
    assert client.post('/api/model/train', headers={'Origin': 'https://example.com'}, json={'mode': 'nature'}).status_code == 403
    assert client.post('/api/layout-profiles', json={'name': 'bad', 'mode': 'nature', 'profile': {'slots': [{'field': 'board', 'bbox': [-1, 0, 2, 1]}]}}).status_code == 422


def test_actual_profile_shop_http_contract(client):
    root = Path(__file__).resolve().parents[1]
    manifest = root / 'app/assets/manifest.json'
    if not manifest.exists():
        pytest.skip('Official image cache not available')
    entry = next(x for x in json.loads(manifest.read_text())['assets'] if x['mode'] == 'nature' and x['kind'] == 'hero')
    image = Image.new('RGB', (640, 360), '#263641')
    icon = Image.open(root / 'app/assets' / entry['path']).convert('RGB').resize((64, 64))
    image.paste(icon, (100, 80))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    profile = {'slots': [{'field': 'shop', 'bbox': [100 / 640, 80 / 360, 64 / 640, 64 / 360]}]}
    result = client.post('/api/recognize', data={'mode': 'nature', 'layout_profile': json.dumps(profile)},
                         files={'file': ('synthetic.png', buffer.getvalue(), 'image/png')})
    assert result.status_code == 200
    shop = result.json()['state']['shop']
    assert len(shop) == 5 and shop[0] == entry['entity_id']
    assert all(x is None for x in shop[1:])
