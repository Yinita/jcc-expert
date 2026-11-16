import json
import hashlib
import os
import uuid
import warnings
import threading
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import ExpertEngine
from .models import GameState, ResultEvent, TrainRequest, RecognitionFeedback
from .probability import ProbabilityModel
from .storage import EventStore
from .vision import ScreenshotRecognizer, validate_layout_profile
from .recognition_feedback import build_feedback_annotation, merge_feedback_sample
from .tablet_access import allowed_hosts, access_response

BASE = Path(__file__).resolve().parent
MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


def create_app(data_dir=None, var_dir=None):
    data_dir = Path(data_dir or BASE / 'data')
    var_dir = Path(var_dir or os.environ.get('JCC_VAR_DIR', BASE.parent / 'var'))
    uploads = var_dir / 'screenshots'
    profiles = var_dir / 'profiles'
    recognition_labels = var_dir / 'recognition_labels'
    for path in [uploads, profiles, recognition_labels]:
        path.mkdir(parents=True, exist_ok=True)
    engine = ExpertEngine(data_dir)
    patch_watch_path=data_dir/'patch_watch.json'
    patch_watch=json.loads(patch_watch_path.read_text()) if patch_watch_path.is_file() else {}
    recognizer = ScreenshotRecognizer(data_dir, BASE / 'assets', var_dir / 'recognition_models')
    events = EventStore(var_dir / 'events.sqlite3', feedback_dir=recognition_labels)
    events.backfill_screenshot_hashes(uploads)
    probability = ProbabilityModel(var_dir / 'models')
    feedback_lock=threading.Lock()
    lan_token=os.environ.get('JCC_LAN_ACCESS_TOKEN','')
    if lan_token and len(lan_token)<24:
        raise ValueError('LAN access token must contain at least 24 characters; use run-tablet.sh to generate it')
    trusted_hosts=allowed_hosts(os.environ.get('JCC_ALLOWED_HOSTS',''))
    app = FastAPI(title='金铲铲截图决策助手', version='0.3.1')
    app.state.engine, app.state.events, app.state.probability = engine, events, probability

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        if request.method not in ['GET', 'HEAD', 'OPTIONS']:
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': '只接受本应用页面提交的修改。'}, status_code=403)
        denied=await access_response(request,lan_token)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'version': '0.3.1', 'patch': '18.6',
                'runtime': 'local', 'data_as_of': '2026-11-10', 'live_validated': False,
                'version_watch':patch_watch}

    @app.get('/api/catalog')
    def catalog(mode: str = Query('nature', pattern='^(nature|orange)$')):
        result = engine.catalog(mode)
        result['version_watch']=patch_watch
        manifest_path = BASE / 'assets' / 'manifest.json'
        if manifest_path.exists():
            assets = json.loads(manifest_path.read_text()).get('assets', [])
            cached = {(r['kind'], r['entity_id']): r['path'] for r in assets if r['mode'] == mode}
            for field, kind in [('heroes', 'hero'), ('cards', 'card')]:
                for row in result.get(field, []):
                    local = cached.get((kind, row['id']))
                    row['icon_url'] = '/assets/' + local if local else None
        return result

    @app.get('/api/demo')
    def demo(mode: str = Query('nature', pattern='^(nature|orange)$')):
        result = engine.demo_state(mode)
        result.update(is_demo=True, confirmed=False, screenshot_id=None)
        return result

    @app.post('/api/recognize')
    async def recognize(file: UploadFile = File(...), mode: str = Form('nature'),
                        layout_profile: str | None = Form(None),
                        patch: str = Form('18.6',min_length=1,max_length=30,pattern=r'^[A-Za-z0-9.\-]+$')):
        if mode not in ['nature', 'orange']:
            raise HTTPException(422, '未知玩法。')
        profile = None
        if layout_profile:
            try:
                profile = json.loads(layout_profile)
                validate_layout_profile(profile)
            except (ValueError, TypeError, KeyError):
                raise HTTPException(422, '布局配置无效，请检查区域坐标和字段。')
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD:
                raise HTTPException(413, '图片超过10MB，请压缩后上传。')
        if not content:
            raise HTTPException(422, '图片为空。')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                image = Image.open(BytesIO(content))
                if image.format not in ['PNG', 'JPEG', 'WEBP']:
                    raise ValueError('仅支持PNG、JPEG或WebP图片。')
                if image.width * image.height > MAX_PIXELS or min(image.size) < 100:
                    raise ValueError('截图尺寸应至少100×100，且不超过2000万像素。')
                image.load()
                image = ImageOps.exif_transpose(image).convert('RGB')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(422, '无法解码图片，请使用PNG或JPEG截图。')
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        screenshot_id = uuid.uuid4().hex
        path = uploads / (screenshot_id + '.png')
        image.save(path, 'PNG')
        events.register_screenshot(screenshot_id, mode, events.image_content_hash(image))
        try:
            result = await run_in_threadpool(recognizer.recognize, path, mode, profile,patch)
        except (ValueError, RuntimeError, OSError) as exc:
            return JSONResponse(status_code=422, content={'detail': '截图识别未完成，请重新上传或校正状态。',
                'error_type': type(exc).__name__, 'screenshot_id': screenshot_id,
                'image_url': '/uploads/' + screenshot_id + '.png'})
        state = result.setdefault('state', {})
        state.update(screenshot_id=screenshot_id, confirmed=False, is_demo=False, mode=mode,patch=patch)
        # Normalize the recognition boundary; preserve original observations in evidence.
        state = GameState.model_validate(state).model_dump()
        result.update(state=state, screenshot_id=screenshot_id,
                      image_url='/uploads/' + screenshot_id + '.png',
                      image_size={'width': image.width, 'height': image.height})
        return result

    @app.post('/api/recommend')
    async def recommend(state: GameState):
        payload = state.model_dump()
        if payload['screenshot_id'] and events.screenshot_mode(payload['screenshot_id']) != payload['mode']:
            raise HTTPException(422, '截图模式与当前玩法不一致，请重新识别。')
        result = await run_in_threadpool(engine.recommend, payload)
        payload = result.get('normalized_state', payload)
        if result.get('status') == 'blocked':
            result['probability_model'] = {'status': 'blocked', 'state_probability': None,
                                         'reason': '状态不合法，无法生成概率预测。'}
        else:
            rows = events.dataset(state.mode, state.patch)
            result['probability_model'] = await run_in_threadpool(probability.predict, payload, rows)
        result['state_probability'] = result['probability_model'].get('state_probability')
        result['screenshot_id'] = state.screenshot_id
        result['is_demo'] = state.is_demo
        return result

    @app.post('/api/matches/events')
    def save_event(event: ResultEvent):
        payload = event.model_dump()
        checked = engine.recommend(payload['state'])
        if checked.get('status') == 'blocked':
            raise HTTPException(422, checked.get('errors', ['状态不合法。']))
        payload['state'] = checked.get('normalized_state', payload['state'])
        if not payload['state']['board'] or not payload['state']['stage']:
            raise HTTPException(422, '记录训练样本前，请补齐当前回合与棋盘。')
        try:
            return events.add(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get('/api/history')
    def history():
        return events.history()

    @app.post('/api/recognition/feedback')
    def recognition_feedback(payload: RecognitionFeedback):
        state=payload.state.model_dump()
        if not state['confirmed'] or state['is_demo'] or not state['screenshot_id']:
            raise HTTPException(422,'识别训练样本需要真实上传截图、人工确认和手动数值区域。')
        if not state['match_id'] or not state['match_id'].strip():
            raise HTTPException(422,'请先填写非空的对局编号，再保存识别纠错。')
        state['match_id']=state['match_id'].strip()
        if events.screenshot_mode(state['screenshot_id'])!=state['mode']:
            raise HTTPException(422,'截图不存在或玩法不一致。')
        if state['patch']!='18.6':
            raise HTTPException(422,'当前识别训练契约仅支持已登记的18.6规则包。')
        try:
            profile=validate_layout_profile(payload.layout_profile)
        except (ValueError,TypeError,KeyError):
            raise HTTPException(422,'数值区域格式不正确。')
        try:
            annotation=build_feedback_annotation(state,profile,
                negative_regions=[r.model_dump() for r in payload.negative_regions],
                absent_fields=payload.absent_fields,all_fields_reviewed=payload.all_fields_reviewed)
        except ValueError as exc:
            raise HTTPException(422,'纠错标注无效：'+str(exc))
        image=uploads/(state['screenshot_id']+'.png')
        if not image.is_file():
            raise HTTPException(422,'截图文件不存在。')
        with Image.open(image) as picture:
            ratio=picture.width/picture.height
            content_hash=events.image_content_hash(picture)
        if profile.get('aspect_ratio') and abs(ratio/profile['aspect_ratio']-1)>.08:
            raise HTTPException(422,'区域布局与当前截图比例不一致。')
        image_hash=hashlib.sha256(image.read_bytes()).hexdigest()
        group='user:'+state['match_id']
        sample={'id':'user_'+content_hash.split(':',1)[-1][:20],'file':str(image.resolve()),'mode':state['mode'],'patch':state['patch'],
                'group_id':group,'split':'development','evaluation_role':'human_corrected_development',
                **annotation,'source_url':'local_user_upload',
                'image_sha256':image_hash,'content_hash':content_hash,'annotation_method':'user_confirmed_manual_regions',
                'not_win_probability_training':True}
        with feedback_lock:
            try:
                bound=events.bind_screenshot(state['screenshot_id'],state['match_id'],state['mode'],state['patch'])
            except ValueError as exc:
                raise HTTPException(422,str(exc))
            # Keep an existing legacy label file and its source identity. New
            # samples use a pixel hash so metadata/encoding changes deduplicate.
            path=Path(bound['feedback_path']) if bound['feedback_path'] else recognition_labels/(content_hash.split(':',1)[-1]+'.json')
            old=None
            if path.exists():
                old=json.loads(path.read_text())['samples'][0]
                if old['group_id']!=group or old['mode']!=state['mode'] or old.get('patch')!=state['patch']:
                    raise HTTPException(422,'同一截图已有其他对局分组，不能重新分组增加独立样本。')
                # Earlier feedback predates pixel hashes. The shared binding
                # above has already verified this exact source identity.
                old={**old,'content_hash':old.get('content_hash') or content_hash}
            try:
                sample=merge_feedback_sample(old,sample,replace_annotations=payload.replace_annotations)
            except ValueError as exc:
                raise HTTPException(422,'纠错合并失败：'+str(exc))
            temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps({'samples':[sample]},ensure_ascii=False,indent=2))
            temporary.replace(path)
        return {'saved':True,'fields':list(sample['field_boxes']),
                'annotation_quality':sample['annotation_quality'],'feedback_revision':sample['feedback_revision'],
                'message':f"已保存{len(sample['field_boxes'])}个数值区域、{len(sample['negative_boxes'])}个排除区域；仅用于识别纠错，不会自动训练或计入名次模型。"}

    @app.get('/api/model/status')
    def model_status(mode: str = Query('nature', pattern='^(nature|orange)$'), patch: str = '18.6'):
        return probability.status(mode, patch, events.dataset(mode, patch))

    @app.post('/api/model/train')
    async def train(payload: TrainRequest):
        if payload.patch != '18.6':
            raise HTTPException(422, '当前知识库只支持18.6，请先更新规则数据。')
        return await run_in_threadpool(probability.train, payload.mode, payload.patch,
                                      events.dataset(payload.mode, payload.patch))

    @app.get('/api/layout-profiles')
    def layout_profiles(mode: str = Query('nature', pattern='^(nature|orange)$')):
        records = []
        for path in sorted(profiles.glob('*.json')):
            try:
                record = json.loads(path.read_text())
                if record['mode'] == mode:
                    records.append(record)
            except (ValueError, KeyError, OSError):
                continue
        return {'profiles': records}

    @app.post('/api/layout-profiles')
    def save_layout_profile(payload: dict):
        name = payload.get('name', '')
        mode = payload.get('mode')
        if not isinstance(name, str) or not 1 <= len(name) <= 80 or mode not in ['nature', 'orange']:
            raise HTTPException(422, '布局需要名称和玩法。')
        profile = payload.get('profile')
        if not isinstance(profile, dict):
            raise HTTPException(422, '布局需要profile对象。')
        try:
            profile = validate_layout_profile(profile)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, '布局区域格式不正确。')
        record = {'id': uuid.uuid4().hex, 'name': name, 'mode': mode, 'profile': profile}
        (profiles / (record['id'] + '.json')).write_text(json.dumps(record, ensure_ascii=False))
        return record

    app.mount('/uploads', StaticFiles(directory=uploads), name='uploads')
    (BASE / 'assets').mkdir(exist_ok=True)
    app.mount('/assets', StaticFiles(directory=BASE / 'assets'), name='assets')
    app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
    validation_dir = BASE.parent / 'validation'
    validation_dir.mkdir(exist_ok=True)
    app.mount('/validation', StaticFiles(directory=validation_dir, html=True), name='validation')
    training_dir = BASE.parent / 'training'
    training_dir.mkdir(exist_ok=True)
    app.mount('/training', StaticFiles(directory=training_dir, html=True), name='training')

    @app.get('/')
    def home():
        return FileResponse(BASE / 'static' / 'index.html')

    # Apply host validation outside access-code handling as well as API routes.
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=trusted_hosts)
    return app


app = create_app()
