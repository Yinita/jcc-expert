import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps


class EventStore:
    def __init__(self, path: Path, feedback_dir: Path | None = None):
        self.path = path
        self.feedback_dir = Path(feedback_dir) if feedback_dir is not None else None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    snapshot_key TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    patch TEXT NOT NULL,
                    placement INTEGER NOT NULL CHECK(placement BETWEEN 1 AND 8),
                    state_json TEXT NOT NULL,
                    selected_candidate_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(match_id, mode, patch, snapshot_key)
                );
                CREATE TABLE IF NOT EXISTS screenshots (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS screenshot_source_bindings (
                    binding_key TEXT PRIMARY KEY,
                    screenshot_id TEXT NOT NULL,
                    match_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    patch TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            ''')
            if 'content_hash' not in {r['name'] for r in db.execute('PRAGMA table_info(screenshots)')}:
                db.execute('ALTER TABLE screenshots ADD COLUMN content_hash TEXT')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def register_screenshot(self, screenshot_id, mode, content_hash=None):
        with self.connect() as db:
            db.execute('INSERT INTO screenshots(id,mode,created_at,content_hash) VALUES(?,?,?,?)',
                       (screenshot_id, mode, datetime.now(timezone.utc).isoformat(), content_hash))

    def screenshot_mode(self, screenshot_id):
        with self.connect() as db:
            row = db.execute('SELECT mode FROM screenshots WHERE id=?', (screenshot_id,)).fetchone()
        return row['mode'] if row else None

    @staticmethod
    def image_content_hash(image):
        """Hash oriented RGB pixels and dimensions, independent of image encoding."""
        picture = ImageOps.exif_transpose(image).convert('RGB')
        digest = hashlib.sha256()
        digest.update(b'jcc-rgb-v1\0')
        digest.update(picture.width.to_bytes(8, 'big'))
        digest.update(picture.height.to_bytes(8, 'big'))
        digest.update(picture.tobytes())
        return 'rgb-v1:' + digest.hexdigest()

    def backfill_screenshot_hashes(self, uploads: Path):
        """Upgrade older PNG-byte hashes before accepting reuploads of old events."""
        with self.connect() as db:
            rows = db.execute('SELECT id,content_hash FROM screenshots').fetchall()
        updates = []
        for row in rows:
            path = Path(uploads) / (row['id'] + '.png')
            if not path.is_file():
                continue
            try:
                with Image.open(path) as image:
                    content_hash = self.image_content_hash(image)
            except (OSError, ValueError):
                continue
            if row['content_hash'] != content_hash:
                updates.append((content_hash, row['id']))
        if updates:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.executemany('UPDATE screenshots SET content_hash=? WHERE id=?', updates)

    def _legacy_feedback(self, db, screenshot_ids, content_hash):
        """Respect labels written before centralized SQLite binding existed."""
        if self.feedback_dir is None or not self.feedback_dir.exists():
            return []
        matches = []
        for path in sorted(self.feedback_dir.glob('*.json')):
            try:
                document = json.loads(path.read_text())
                for sample in document.get('samples', []):
                    old_id = Path(sample.get('file', '')).stem
                    same_pixels = bool(content_hash and sample.get('content_hash') == content_hash)
                    if old_id not in screenshot_ids and not same_pixels:
                        continue
                    group = sample.get('group_id', '')
                    if not isinstance(group, str) or not group.startswith('user:'):
                        raise ValueError('同一截图的旧纠错来源分组无效，请先人工核对，不能自动重新分组。')
                    match_id = group[len('user:'):]
                    if not match_id:
                        raise ValueError('同一截图的旧纠错缺少来源分组，不能自动重新分组。')
                    matches.append((path, (match_id, sample.get('mode'), sample.get('patch'))))
            except (OSError, json.JSONDecodeError, TypeError, AttributeError):
                # A damaged unrelated label cannot be identified as this screenshot.
                # Identified labels with invalid groups above fail closed.
                continue
        return matches

    def _bind_in_transaction(self, db, screenshot_id, match_id, mode, patch):
        if not isinstance(match_id, str) or not match_id.strip():
            raise ValueError('请先填写非空的对局编号，再保存截图来源。')
        match_id = match_id.strip()
        current = db.execute('SELECT id,mode,content_hash FROM screenshots WHERE id=?',
                             (screenshot_id,)).fetchone()
        if not current or current['mode'] != mode:
            raise ValueError('截图不存在或截图模式与当前状态不一致。')
        content_hash = current['content_hash']
        linked = db.execute('''SELECT id FROM screenshots WHERE id=? OR
            (? IS NOT NULL AND content_hash=?)''',
            (screenshot_id, content_hash, content_hash)).fetchall()
        linked_ids = {row['id'] for row in linked}
        placeholders = ','.join('?' for _ in linked_ids)
        requested = (match_id, mode, patch)
        events = db.execute(f'''SELECT match_id,mode,patch,snapshot_key FROM events
            WHERE snapshot_key IN ({placeholders}) ORDER BY id''', tuple(linked_ids)).fetchall()
        binding_key = 'content:' + content_hash if content_hash else 'id:' + screenshot_id
        bindings = db.execute(f'''SELECT * FROM screenshot_source_bindings
            WHERE binding_key=? OR screenshot_id IN ({placeholders}) ORDER BY created_at''',
            (binding_key, *linked_ids)).fetchall()
        legacy = self._legacy_feedback(db, linked_ids, content_hash)
        constraints = [(row['match_id'], row['mode'], row['patch']) for row in [*events, *bindings]]
        constraints += [identity for _, identity in legacy]
        if any(identity != requested for identity in constraints):
            raise ValueError('同一截图已绑定其他对局、模式或版本，不能重新分组或重复计为独立样本。')
        # Reuse the first source screenshot so an identical reupload also updates
        # the same event row, rather than creating another observation.
        canonical_id = events[0]['snapshot_key'] if events else bindings[0]['screenshot_id'] if bindings else screenshot_id
        db.execute('''INSERT OR IGNORE INTO screenshot_source_bindings
            (binding_key,screenshot_id,match_id,mode,patch,created_at) VALUES(?,?,?,?,?,?)''',
            (binding_key, canonical_id, match_id, mode, patch, datetime.now(timezone.utc).isoformat()))
        return {'match_id': match_id, 'mode': mode, 'patch': patch,
                'content_hash': content_hash, 'snapshot_id': canonical_id,
                'feedback_path': str(legacy[0][0]) if legacy else None}

    def bind_screenshot(self, screenshot_id, match_id, mode, patch):
        """Atomically share one source binding between result and OCR feedback."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._bind_in_transaction(db, screenshot_id, match_id, mode, patch)

    def add(self, event: dict):
        state = event['state']
        if not state.get('confirmed'):
            raise ValueError('请先确认截图状态，再记录结果。')
        if state.get('is_demo'):
            raise ValueError('演示数据不能进入真实对局训练集。')
        if not state.get('screenshot_id'):
            raise ValueError('训练记录必须关联实际上传的截图。')
        match_id = event.get('match_id')
        if not isinstance(match_id, str) or not match_id.strip():
            raise ValueError('请先填写非空的对局编号。')
        match_id = match_id.strip()
        if state.get('match_id') and state['match_id'].strip() != match_id:
            raise ValueError('状态与结果的对局编号不一致。')
        if self.screenshot_mode(state['screenshot_id']) != state['mode']:
            raise ValueError('截图不存在或截图模式与当前状态不一致。')
        serialized = json.dumps(dict(state, match_id=match_id), ensure_ascii=False, sort_keys=True)
        snapshot_key = state['screenshot_id']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            bound = self._bind_in_transaction(db, snapshot_key, match_id, state['mode'], state['patch'])
            snapshot_key = bound['snapshot_id']
            existing = db.execute('SELECT placement FROM events WHERE match_id=? AND mode=? AND patch=? LIMIT 1',
                                  (match_id, state['mode'], state['patch'])).fetchone()
            if existing and existing['placement'] != event['placement']:
                raise ValueError('同一对局的最终名次必须一致，请核对对局编号。')
            cursor = db.execute('''INSERT INTO events
                (match_id,snapshot_key,mode,patch,placement,state_json,selected_candidate_id,created_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(match_id,mode,patch,snapshot_key) DO UPDATE SET
                state_json=excluded.state_json, selected_candidate_id=excluded.selected_candidate_id''',
                (match_id, snapshot_key, state['mode'], state['patch'], event['placement'],
                 serialized, event.get('selected_candidate_id'), datetime.now(timezone.utc).isoformat()))
        return {'saved': True, 'match_id': match_id, 'snapshot_id': snapshot_key}

    def dataset(self, mode: str, patch: str):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE mode=? AND patch=? ORDER BY id', (mode, patch)).fetchall()
        return [{'match_id': r['match_id'], 'placement': r['placement'],
                 'state': json.loads(r['state_json']), 'id': r['id']} for r in rows]

    def history(self, limit=50):
        with self.connect() as db:
            rows = db.execute('''SELECT id,match_id,mode,patch,placement,created_at,selected_candidate_id,
                json_extract(state_json,'$.stage') AS stage FROM events ORDER BY id DESC LIMIT ?''', (limit,)).fetchall()
            n = db.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n']
        return {'total': n, 'events': [dict(r) for r in rows]}
