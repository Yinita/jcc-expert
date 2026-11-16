'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const arr = (v) => Array.isArray(v) ? v : [];
  const idOf = (v) => v == null ? '' : String(typeof v === 'object' ? (v.id ?? v.hero_id ?? v.entity_id ?? '') : v);
  const textOf = (v) => {
    if (v == null) return '';
    if (typeof v !== 'object') return String(v);
    return v.note ?? v.reason ?? v.message ?? v.text ?? v.name ?? v.label ?? JSON.stringify(v);
  };
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const finite = (v) => v !== '' && v !== null && v !== undefined && Number.isFinite(Number(v)) ? Number(v) : null;
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const emptyState = (mode = 'nature') => ({ mode, patch: '18.6', stage: null, hp: null, gold: null, level: null, board: [], bench: [], shop: [null, null, null, null, null], item_ids: [], augment_ids: [], offered_augment_ids: [], orange_card_ids: [], portal: null, confirmed: false, screenshot_id: null, match_id: '', is_demo: false });
  const app = { mode: 'nature', state: emptyState(), catalog: { heroes: [], items: [], augments: [], cards: [] }, maps: {}, evidence: [], uncertain: [], result: null, demo: false, revision: 0, catalogToken: 0, recognizeToken: 0, recommendationToken: 0, recognizing: false, recommending: false, picker: null, selectedCandidateId: '', imageObjectUrl: null, lastFile: null, layout: {name:'我的截图布局',slots:[]}, savedLayouts: [], drawing: false, drawStart: null, activePointerId: null, drawTarget: 'layout', negativeRegions: [] };

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('json') ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof data === 'object' ? (data.detail ?? data.error ?? data.message ?? data) : data;
      const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(textOf).join('；') : JSON.stringify(detail);
      throw new Error(message || `服务返回 ${response.status}`);
    }
    return data;
  }
  const jsonOptions = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function notify(message, error = false) {
    const node = $('app-message');
    node.replaceChildren(el('span', '', message));
    node.className = `notice${error ? ' notice-error' : ''}`;
  }
  let toastTimer;
  function toast(message) {
    $('toast').textContent = message;
    $('toast').classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 4200);
  }
  function normalizeState(raw = {}) {
    const base = emptyState(app.mode);
    const unit = (u) => ({ hero_id: idOf(u.hero_id ?? u.entity_id ?? u.id), stars: finite(u.stars), item_ids: arr(u.item_ids).map(idOf).filter(Boolean) });
    return { ...base, mode: app.mode, patch: String(raw.patch ?? '18.6'), stage: raw.stage == null ? null : String(raw.stage), hp: finite(raw.hp), gold: finite(raw.gold), level: finite(raw.level), board: arr(raw.board).map(unit), bench: arr(raw.bench).map(unit), shop: arr(raw.shop).slice(0, 5).map(idOf).map(x => x || null), item_ids: arr(raw.item_ids).map(idOf).filter(Boolean), augment_ids: arr(raw.augment_ids).map(idOf).filter(Boolean), offered_augment_ids: arr(raw.offered_augment_ids).map(idOf).filter(Boolean), orange_card_ids: arr(raw.orange_card_ids).map(idOf).filter(Boolean).slice(0, 3), portal: raw.portal == null ? null : String(raw.portal), confirmed: false, screenshot_id: raw.screenshot_id ?? null, match_id: String(raw.match_id ?? ''), is_demo: raw.is_demo === true };
  }
  function itemName(id, type = 'items') { return app.maps[type]?.get(String(id))?.name || `未匹配 ID ${id}`; }
  function updateWorkflow(step) {
    ['upload', 'confirm', 'recommend', 'save'].forEach((name, index) => {
      const node = $(`step-${name}`);
      node.classList.toggle('completed', index < step);
      node.classList.toggle('current', index === step);
    });
  }
  function syncConfirmation() {
    const confirmed = Boolean(app.state.confirmed);
    $('confirm-state').checked = confirmed;
    $('state-status').textContent = confirmed ? '已人工确认' : '待人工核对';
    $('state-status').className = `tag${confirmed ? ' positive' : ''}`;
    $('recommend-button').disabled = !confirmed || app.recognizing || app.recommending;
    $('save-result').disabled = app.demo || !app.state.screenshot_id || !confirmed;
    $('recommend-button').firstElementChild.textContent = app.recommending ? '正在计算候选路线…' : confirmed ? '生成当前局面的三条路线' : '确认后生成路线';
  }
  function markChanged() {
    app.revision += 1;
    app.state.confirmed = false;
    app.selectedCandidateId = '';
    syncConfirmation();
    updateWorkflow(app.state.screenshot_id || app.demo || app.state.board.length ? 1 : 0);
    if (app.result) {
      $('recommendation-snapshot').textContent = '局面已更新 · 需要重算';
      $('recommendation-snapshot').className = 'tag warning';
      $('candidate-grid').classList.add('stale');
      document.querySelectorAll('.candidate-select').forEach(button => { button.disabled = true; button.textContent = '局面已更新，请重新生成'; });
      $('selected-candidate').value = '';
      $('state-probability').textContent = '局面已更新';
    }
  }
  function clearRecommendations() {
    app.result = null;
    app.selectedCandidateId = '';
    $('candidate-grid').classList.remove('stale');
    const blank = el('div', 'recommendation-empty');
    blank.append(el('div', 'empty-grid-icon', '◇'), el('h3', '', '你的下一步，从当前信息开始'), el('p', '', '上传截图或手动填写。系统会给出候选阵容、装备计划、搜牌预算与停手条件。'), el('span', '', '当前没有生成推荐'));
    $('candidate-grid').replaceChildren(blank);
    $('recommendation-messages').replaceChildren();
    $('recommendation-snapshot').className = 'tag';
    $('recommendation-snapshot').textContent = '等待输入';
    $('state-probability').textContent = '尚不可用';
    $('probability-reason').textContent = '未训练并校准的模型不输出个人吃鸡概率。规则评分用于比较候选，不代表胜率。';
    $('selected-candidate').replaceChildren(new Option('未采用 / 未记录', ''));
  }
  function addUnknownOption(select, value, label) {
    if (value && !Array.from(select.options).some(o => o.value === value)) select.add(new Option(label || `未匹配 ID ${value}`, value));
    select.value = value || '';
  }
  function heroSelect(value, emptyLabel = '选择单位 / 未知') {
    const select = el('select');
    select.setAttribute('aria-label', '单位');
    select.add(new Option(emptyLabel, ''));
    app.catalog.heroes.forEach(h => select.add(new Option(`${h.cost != null ? `${h.cost}费 · ` : ''}${h.name}`, h.id)));
    addUnknownOption(select, value);
    return select;
  }
  function renderUnits(field) {
    const list = $(`${field}-units`);
    list.replaceChildren();
    app.state[field].forEach((unit, index) => {
      const row = el('div', 'unit-row');
      const hero = heroSelect(unit.hero_id);
      hero.addEventListener('change', () => { unit.hero_id = hero.value; markChanged(); });
      const stars = el('select');
      stars.setAttribute('aria-label', '单位星级');
      stars.add(new Option('? 星', ''));
      [1, 2, 3, 4].forEach(n => stars.add(new Option(`${n} 星`, String(n))));
      addUnknownOption(stars, unit.stars == null ? '' : String(unit.stars), `${unit.stars} 星`);
      stars.addEventListener('change', () => { unit.stars = finite(stars.value); markChanged(); });
      const itemsButton = el('button', 'button unit-items-button', `装备 ${unit.item_ids.length}`);
      itemsButton.type = 'button';
      itemsButton.addEventListener('click', () => openPicker({ title: `${itemName(unit.hero_id, 'heroes')} · 携带装备`, type: 'items', values: unit.item_ids, max: 3, multiset: true, onApply: ids => { unit.item_ids = ids; markChanged(); renderUnits(field); } }));
      const remove = el('button', 'remove-unit', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', `移除第 ${index + 1} 个${field === 'board' ? '棋盘' : '备战'}单位`);
      remove.addEventListener('click', () => { app.state[field].splice(index, 1); markChanged(); renderUnits(field); });
      row.append(hero, stars, itemsButton, remove);
      if (unit.item_ids.length) row.append(el('div', 'unit-items-label', unit.item_ids.map(x => itemName(x)).join(' / ')));
      list.append(row);
    });
    $('bench-count').textContent = app.state.bench.length;
  }
  function renderShop() {
    $('shop-units').replaceChildren();
    for (let i = 0; i < 5; i += 1) {
      const select = heroSelect(app.state.shop[i], `第 ${i + 1} 格 · 未知 / 空`);
      select.setAttribute('aria-label', `商店第${i + 1}格`);
      select.addEventListener('change', () => { app.state.shop[i] = select.value || null; markChanged(); });
      $('shop-units').append(select);
    }
  }
  const chipConfig = {
    item_ids: { container: 'inventory-chips', type: 'items', title: '未分配装备 / 散件', max: 40, multiset: true },
    augment_ids: { container: 'augment-chips', type: 'augments', title: '已选强化符文', max: 10 },
    offered_augment_ids: { container: 'offered-augment-chips', type: 'augments', title: '本轮可选强化', max: 3 },
    orange_card_ids: { container: 'orange-card-chips', type: 'cards', title: '出战时间卡片', max: 3 }
  };
  function renderChips(field) {
    const cfg = chipConfig[field];
    const root = $(cfg.container);
    root.replaceChildren();
    app.state[field].forEach((id, index) => {
      const chip = el('span', 'chip');
      chip.append(el('span', '', itemName(id, cfg.type)));
      const remove = el('button', '', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', `移除${itemName(id, cfg.type)}`);
      remove.addEventListener('click', () => { app.state[field].splice(index, 1); markChanged(); renderChips(field); });
      chip.append(remove);
      root.append(chip);
    });
  }
  function renderEditor() {
    ['stage', 'hp', 'gold', 'level', 'patch'].forEach(key => { $(key).value = app.state[key] ?? ''; });
    $('match-id').value = app.state.match_id || '';
    addUnknownOption($('portal'), app.state.portal || '', app.state.portal);
    $('orange-editor').classList.toggle('hidden', app.mode !== 'orange');
    renderUnits('board'); renderUnits('bench'); renderShop();
    Object.keys(chipConfig).forEach(renderChips);
    syncConfirmation();
    $('demo-banner').classList.toggle('hidden', !app.demo);
    $('save-result').disabled = app.demo || !app.state.screenshot_id || !app.state.confirmed;
    $('result-message').textContent = app.demo ? '演示状态不能作为真实对局保存。' : !app.state.screenshot_id ? '训练记录需要关联实际上传的截图；纯手工局面可生成规则建议。' : '核对截图状态并确认后，记录真实最终名次。同一局的截图请使用相同对局标识。';
  }
  function normalizeCatalog(raw) {
    const result = {};
    ['heroes', 'items', 'augments', 'cards'].forEach(type => {
      const seen = new Set();
      result[type] = arr(raw[type]).map(x => ({ ...x, id: idOf(x), name: String(x.name ?? x.hero_name ?? x.id ?? '未命名实体'), cost: x.cost ?? x.price ?? null, icon_url: x.icon_url ?? x.picture ?? x.icon ?? null })).filter(x => x.id && !seen.has(x.id) && seen.add(x.id));
    });
    return result;
  }
  async function loadCatalog() {
    const token = ++app.catalogToken;
    $('catalog-status').textContent = '读取资料中';
    try {
      const raw = await api(`/api/catalog?mode=${app.mode}`);
      if (token !== app.catalogToken) return;
      app.catalog = normalizeCatalog(raw.catalog || raw);
      app.maps = Object.fromEntries(Object.entries(app.catalog).map(([key, values]) => [key, new Map(values.map(x => [x.id, x]))]));
      $('catalog-status').textContent = `${app.catalog.heroes.length} 单位 · ${app.catalog.items.length} 装备`;
      renderEditor();
    } catch (error) { if (token === app.catalogToken) { $('catalog-status').textContent = '资料读取失败'; notify(`无法读取实体资料：${error.message}`, true); } }
  }
  async function changeMode(mode) {
    if (mode === app.mode) return;
    app.recognizeToken += 1; app.recommendationToken += 1;
    app.mode = mode; app.state = emptyState(mode); app.demo = false; app.revision += 1; app.recognizing = false; app.recommending = false;
    app.evidence = []; app.uncertain = []; app.lastFile = null; app.negativeRegions=[]; $('negative-reviewed').checked=false; app.layout = {name:'我的截图布局',slots:[]}; setDrawing(false); renderLayout(); loadLayouts(); loadModelStatus();
    clearImage(); clearRecommendations(); renderEvidence();
    $('app-message').classList.add('hidden');
    $('recognition-progress').classList.add('hidden');
    $('recognition-capabilities').textContent = '尚未调用识别服务。识别能力与不确定项会在上传后显示。';
    document.body.classList.toggle('orange-mode', mode === 'orange');
    document.querySelectorAll('[data-mode]').forEach(button => { const selected = button.dataset.mode === mode; button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected)); });
    renderEditor(); updateWorkflow(0); await loadCatalog();
    toast(`已切换到${mode === 'nature' ? '自然之力' : '大橘大利'}，当前输入已清空`);
  }

  function clearImage() {
    if (app.imageObjectUrl) { URL.revokeObjectURL(app.imageObjectUrl); app.imageObjectUrl = null; }
    $('image-container').classList.add('hidden');
    $('upload-zone').classList.remove('hidden');
    $('screenshot-image').removeAttribute('src');
    $('evidence-overlay').replaceChildren();
    $('screenshot-file').value = '';
    $('screen-type').textContent = '等待截图';
    $('recognize-layout').disabled = true;
  }
  function setImage(url, filename) {
    $('image-container').classList.remove('hidden');
    $('upload-zone').classList.add('hidden');
    $('screenshot-image').src = url;
    $('image-filename').textContent = filename || '当前截图';
  }
  const screenNames = { board: '常规备战', augment_selection: '强化选择', scouting: '对手侦察', orange_loadout: '大橘出战', inventory: '卡片查看', orange_super_time: '超级时间', result: '对局结算', unknown: '页面类型待确认' };
  async function recognizeFile(file) {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { notify('请选择 PNG、JPG 或 WebP 图片。', true); return; }
    if (file.size > 10 * 1024 * 1024) { notify('图片超过 10 MB，请缩小后重新上传。', true); return; }
    const token = ++app.recognizeToken;
    const mode = app.mode;
    const previousMatchId=$('match-id').value.trim();
    const requestedPatch=$('patch').value.trim() || app.state.patch;
    app.state=emptyState(mode); app.state.match_id=previousMatchId; app.state.patch=requestedPatch;
    if(file !== app.lastFile){app.negativeRegions=[];$('negative-reviewed').checked=false;$('replace-recognition-annotations').checked=false;}
    app.recognizing = true; app.demo = false; app.lastFile = file; app.state.is_demo = false; markChanged(); clearRecommendations(); setDrawing(false); renderEditor();
    app.evidence = []; app.uncertain = []; renderEvidence();
    if (app.imageObjectUrl) URL.revokeObjectURL(app.imageObjectUrl);
    app.imageObjectUrl = URL.createObjectURL(file);
    setImage(app.imageObjectUrl, file.name);
    $('recognition-progress').classList.remove('hidden');
    $('screen-type').textContent = '识别中';
    $('app-message').classList.add('hidden');
    const form = new FormData(); form.append('file', file); form.append('mode', mode); form.append('patch',requestedPatch);
    if (app.layout.slots.length) form.append('layout_profile', JSON.stringify({...app.layout,name:$('layout-name').value.trim() || '我的截图布局'}));
    try {
      const result = await api('/api/recognize', { method: 'POST', body: form });
      if (token !== app.recognizeToken || mode !== app.mode) return;
      const matchId = $('match-id').value.trim();
      const currentPatch=$('patch').value.trim() || requestedPatch;
      app.state = normalizeState(result.state || {});
      app.state.patch=currentPatch;
      app.state.screenshot_id = result.screenshot_id ?? app.state.screenshot_id;
      app.state.match_id = matchId || app.state.match_id;
      app.revision += 1;
      app.evidence = Array.isArray(result.evidence) ? result.evidence : Object.entries(result.evidence || {}).map(([field, value]) => ({ field, ...(typeof value === 'object' ? value : { text: value }) }));
      app.uncertain = arr(result.uncertain ?? result.uncertainties);
      if (result.image_url) setImage(result.image_url, file.name);
      $('screen-type').textContent = screenNames[result.screen_type] || String(result.screen_type || '页面类型待确认');
      $('recognition-capabilities').textContent = describeCapabilities(result.capabilities);
      renderEditor(); renderEvidence(); renderLayout(); updateWorkflow(1);
      notify('识别已完成。请逐项核对；候选图标可以手动加入棋盘，低置信度与未识别字段需要校正。');
    } catch (error) {
      if (token !== app.recognizeToken) return;
      $('screen-type').textContent = '识别未完成';
      $('recognition-capabilities').textContent = '未取得可用识别结果。请手动录入当前局面，或更换清晰截图重试。';
      notify(`截图识别失败：${error.message}`, true);
    } finally {
      if (token === app.recognizeToken) { app.recognizing = false; $('recognition-progress').classList.add('hidden'); $('recognize-layout').disabled = !app.lastFile || !app.layout.slots.length; syncConfirmation(); }
    }
  }
  function describeCapabilities(value) {
    if (value == null) return '服务未提供识别能力说明。截图结果必须人工核对。';
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(textOf).join(' · ');
    return Object.entries(value).map(([key, v]) => `${key}：${typeof v === 'boolean' ? (v ? '可用' : '不可用') : textOf(v)}`).join('；');
  }
  function evidenceLabel(e) { if(e.kind==='card_title_candidate'&&e.name)return e.name; return e.text ?? e.name ?? e.label ?? (e.entity_id ? itemName(e.entity_id, e.entity_type === 'item' ? 'items' : e.entity_type === 'augment' ? 'augments' : e.entity_type === 'card' ? 'cards' : 'heroes') : e.field ?? e.kind ?? '识别结果'); }
  function focusEvidence(index) {
    document.querySelectorAll('[data-evidence-index]').forEach(node => node.classList.toggle('highlighted', Number(node.dataset.evidenceIndex) === index));
    const row = $(`evidence-row-${index}`);
    if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function addEvidenceEntity(e, target) {
    const id = idOf(e.entity_id ?? e.id);
    if (!id) return;
    if (target === 'board' || target === 'bench') {
      app.state[target].push({ hero_id: id, stars: null, item_ids: [] }); renderUnits(target);
    } else if (target === 'shop') {
      let index = app.state.shop.findIndex(x => !x);
      if (index < 0) index = app.state.shop.length < 5 ? app.state.shop.length : -1;
      if (index < 0) { toast('五格商店已填满，请先清空其中一格'); return; }
      app.state.shop[index] = id; renderShop();
    } else {
      const max = chipConfig[target]?.max ?? 40;
      if (app.state[target].length >= max) { toast(`最多选择 ${max} 项`); return; }
      if (target !== 'item_ids' && app.state[target].includes(id)) { toast('该项已添加'); return; }
      app.state[target].push(id); renderChips(target);
    }
    markChanged(); toast(`已添加：${evidenceLabel(e)}。请继续核对星级与携带装备。`);
  }
  function renderEvidence() {
    $('evidence-overlay').replaceChildren(); $('evidence-list').replaceChildren();
    $('evidence-count').textContent = `${app.evidence.length} 条证据`;
    if (!app.evidence.length) $('evidence-list').append(el('p', 'empty-note', '截图中的识别结果将关联到原图位置。未知信息保持空白。'));
    app.evidence.forEach((e, index) => {
      const confidence = finite(e.confidence);
      const row = el('div', 'evidence-row');
      row.id = `evidence-row-${index}`; row.dataset.evidenceIndex = index;
      const indexButton = el('button', 'evidence-index', index + 1); indexButton.type = 'button'; indexButton.setAttribute('aria-label', `查看证据 ${index + 1}`); indexButton.addEventListener('click', () => focusEvidence(index));
      const roles={preset_option:'预设卡组选项',repair_inventory:'待修复卡片',reward_obtained:'奖励卡片',detail_preview:'卡片详情',collection_card_not_deck_confirmation:'卡册候选',displayed_deck_card:'展示卡组',selected_deck_card:'编辑区已选卡片',catalog:'卡片目录',deck_card_unassigned:'归属待核对',visible_card_title:'可见卡名'};
      const label = el('div', 'evidence-copy'); label.append(el('strong', '', evidenceLabel(e)), el('small', '', `${roles[e.role] ?? e.field ?? e.field_path ?? e.kind ?? '候选'}${e.entity_id ? ` · ID ${e.entity_id}` : ''}`));
      row.append(indexButton, label, el('span', `evidence-confidence${confidence !== null && confidence < 0.8 ? ' low' : ''}`, confidence === null ? '置信度未知' : `${Math.round(confidence * 100)}%`));
      const entityId = idOf(e.entity_id ?? e.id);
      const entityType = e.entity_type ?? (app.maps.heroes?.has(entityId) ? 'hero' : app.maps.items?.has(entityId) ? 'item' : app.maps.augments?.has(entityId) ? 'augment' : app.maps.cards?.has(entityId) ? 'card' : null);
      if (entityId && ['hero', 'item', 'augment', 'card'].includes(entityType)) {
        const choose = el('select', 'evidence-add');
        choose.setAttribute('aria-label', `添加${evidenceLabel(e)}到局面`);
        choose.add(new Option('加入…', ''));
        const targets = entityType === 'hero' ? [['board', '棋盘'], ['bench', '备战席'], ['shop', '商店']] : entityType === 'item' ? [['item_ids', '装备/散件']] : entityType === 'augment' ? [['augment_ids', '已选符文'], ['offered_augment_ids', '本轮选项']] : [['orange_card_ids', '出战卡片']];
        targets.forEach(([value, text]) => choose.add(new Option(text, value)));
        choose.addEventListener('change', () => { if (choose.value) addEvidenceEntity(e, choose.value); choose.value = ''; });
        row.append(choose);
      }
      $('evidence-list').append(row);
      const box = e.bbox ?? e.box;
      if (Array.isArray(box) && box.length === 4 && box.every(x => Number.isFinite(Number(x))) && box[2] > 0 && box[3] > 0 && box.every(x => x >= 0 && x <= 1) && box[0] + box[2] <= 1.001 && box[1] + box[3] <= 1.001) {
        const marker = el('button', `evidence-box${confidence !== null && confidence < 0.8 ? ' low' : ''}`);
        marker.type = 'button'; marker.dataset.evidenceIndex = index;
        marker.style.left = `${box[0] * 100}%`; marker.style.top = `${box[1] * 100}%`; marker.style.width = `${box[2] * 100}%`; marker.style.height = `${box[3] * 100}%`;
        marker.title = `${evidenceLabel(e)}${confidence !== null ? ` · ${Math.round(confidence * 100)}%` : ''}`;
        marker.setAttribute('aria-label', `证据 ${index + 1}：${evidenceLabel(e)}`);
        marker.append(el('span', '', index + 1)); marker.addEventListener('click', () => focusEvidence(index));
        $('evidence-overlay').append(marker);
      }
    });
    $('evidence-overlay').classList.toggle('hidden', !$('show-evidence').checked);
    $('uncertainty-panel').classList.toggle('hidden', !app.uncertain.length);
    $('uncertainty-list').replaceChildren(...app.uncertain.map(x => el('li', '', textOf(x))));
  }

  const layoutNames = {board:'棋盘单位',bench:'备战单位',shop:'商店单位',item_ids:'装备/散件',augment_ids:'已选符文',offered_augment_ids:'可选符文',orange_card_ids:'时间卡片',stage:'回合',hp:'生命',gold:'金币',level:'等级'};
  function setDrawing(active, target = 'layout') {
    app.drawing = active; app.drawStart = null; app.activePointerId = null; app.drawTarget = target;
    $('image-stage').classList.toggle('calibrating', active);
    $('draw-layout').textContent = active && target === 'layout' ? '取消框选' : '在截图上框选';
    $('draw-negative').textContent = active && target === 'negative' ? '取消框选' : '框选排除区域';
    $('draw-layout').classList.toggle('button-primary', active);
  }
  function renderLayout() {
    $('layout-overlay').replaceChildren(); $('layout-slots').replaceChildren();
    if (!app.layout.slots.length) $('layout-slots').append(el('p','empty-note','尚未设置区域。'));
    app.layout.slots.forEach((slot,index) => {
      const row = el('div','layout-slot');
      row.append(el('span','',`${index+1}. ${layoutNames[slot.field] || slot.field}`),el('small','',slot.bbox.map(x=>Number(x).toFixed(3)).join(' / ')));
      const remove=el('button','text-button','移除'); remove.type='button'; remove.addEventListener('click',()=>{app.layout.slots.splice(index,1);renderLayout();}); row.append(remove); $('layout-slots').append(row);
      const marker=el('div','layout-box'); marker.style.left=`${slot.bbox[0]*100}%`; marker.style.top=`${slot.bbox[1]*100}%`; marker.style.width=`${slot.bbox[2]*100}%`; marker.style.height=`${slot.bbox[3]*100}%`; marker.append(el('span','',`${index+1} ${layoutNames[slot.field]||slot.field}`)); $('layout-overlay').append(marker);
    });
    $('negative-regions-list').replaceChildren();
    app.negativeRegions.forEach((region,index)=>{
      const row=el('div','layout-slot');row.append(el('span','',`${index+1}. 已核对的排除区域`));
      const remove=el('button','text-button','移除');remove.type='button';remove.addEventListener('click',()=>{app.negativeRegions.splice(index,1);renderLayout();});row.append(remove);$('negative-regions-list').append(row);
      const marker=el('div','layout-box negative-region');marker.style.left=`${region.bbox[0]*100}%`;marker.style.top=`${region.bbox[1]*100}%`;marker.style.width=`${region.bbox[2]*100}%`;marker.style.height=`${region.bbox[3]*100}%`;marker.append(el('span','',`排除 ${index+1}`));$('layout-overlay').append(marker);
    });
    if(!app.negativeRegions.length)$('negative-regions-list').append(el('p','empty-note','本图尚未标记排除区域。'));
    $('recognize-layout').disabled=!app.lastFile || !app.layout.slots.length || app.recognizing;
    $('layout-message').textContent=app.lastFile ? (app.layout.slots.length ? `已配置 ${app.layout.slots.length} 个区域。重新识别会替换当前局面，之后仍须人工确认。`:'点击“在截图上框选”，然后在原图上拖出一个区域。'):'先上传截图，再添加识别区域。';
  }
  function drawPoint(event) {
    const rect=$('screenshot-image').getBoundingClientRect();
    return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
  }
  function drawBBox(start,end) {return [Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.abs(start[0]-end[0]),Math.abs(start[1]-end[1])];}
  function drawPreview(box) {
    let marker=$('layout-preview');
    if(!marker){marker=el('div','layout-box drawing-box');marker.id='layout-preview';$('layout-overlay').append(marker);}
    marker.style.left=`${box[0]*100}%`;marker.style.top=`${box[1]*100}%`;marker.style.width=`${box[2]*100}%`;marker.style.height=`${box[3]*100}%`;
  }
  async function loadLayouts() {
    const mode=app.mode;
    try {
      const result=await api(`/api/layout-profiles?mode=${mode}`); if(mode!==app.mode)return;
      app.savedLayouts=arr(result.profiles);$('saved-layout').replaceChildren(new Option('选择已保存布局',''));
      app.savedLayouts.forEach(p=>$('saved-layout').add(new Option(p.name,String(p.id))));
    }catch(error){$('layout-message').textContent=`已保存布局暂不可读：${error.message}`;}
  }
  async function saveLayout() {
    if(!app.layout.slots.length){toast('请先在截图上框选至少一个区域');return;}
    const name=$('layout-name').value.trim();if(!name){toast('请填写布局名称');return;}
    const image=$('screenshot-image');
    const profile={name,slots:copy(app.layout.slots)};
    if(image.naturalWidth&&image.naturalHeight)profile.aspect_ratio=image.naturalWidth/image.naturalHeight;
    $('save-layout').disabled=true;
    try {const saved=await api('/api/layout-profiles',jsonOptions({name,mode:app.mode,profile}));app.layout=profile;await loadLayouts();$('saved-layout').value=String(saved.id);toast('截图布局已保存到本地');}
    catch(error){toast(`布局保存失败：${error.message}`);}
    finally{$('save-layout').disabled=false;}
  }

  function openPicker(config) {
    app.picker = { ...config, values: [...config.values] };
    $('picker-title').textContent = config.title;
    $('picker-search').value = '';
    $('picker-limit').textContent = config.multiset ? `可重复选择，最多 ${config.max} 件` : `最多选择 ${config.max} 项`;
    renderPicker();
    $('entity-picker').showModal();
    $('picker-search').focus();
  }
  function renderPicker() {
    if (!app.picker) return;
    const p = app.picker;
    const query = $('picker-search').value.trim().toLowerCase();
    $('picker-selection').replaceChildren();
    p.values.forEach((id, index) => {
      const chip = el('span', 'chip'); chip.append(el('span', '', itemName(id, p.type)));
      const remove = el('button', '', '×'); remove.type = 'button'; remove.setAttribute('aria-label', `移除${itemName(id, p.type)}`); remove.addEventListener('click', () => { p.values.splice(index, 1); renderPicker(); }); chip.append(remove); $('picker-selection').append(chip);
    });
    if (!p.values.length) $('picker-selection').append(el('span', 'muted', '尚未选择'));
    $('picker-options').replaceChildren();
    const matches = app.catalog[p.type].filter(x => `${x.name} ${x.id}`.toLowerCase().includes(query));
    if (!matches.length) $('picker-options').append(el('p', 'empty-note', '没有匹配的实体。请检查当前玩法与关键词。'));
    matches.forEach(entity => {
      const count = p.values.filter(x => x === entity.id).length;
      const option = el('button', `picker-option${count ? ' selected' : ''}`);
      option.type = 'button'; option.setAttribute('aria-pressed', String(count > 0));
      if (entity.icon_url) {
        const image = el('img'); image.src = entity.icon_url; image.alt = ''; image.loading = 'lazy'; image.addEventListener('error', () => image.remove(), { once: true }); option.append(image);
      }
      option.append(el('span', '', entity.name), el('small', '', count ? `已选 ${count}` : p.type === 'cards' && entity.rarity_tier ? `品阶 ${entity.rarity_tier}` : p.type === 'heroes' ? `${entity.cost ?? '?'}费 · ${arr(entity.trait_names).join(' / ')} · ID ${entity.id}` : entity.type || ''));
      option.addEventListener('click', () => {
        if (!p.multiset && count) p.values = p.values.filter(id => id !== entity.id);
        else if (p.values.length < p.max) p.values.push(entity.id);
        else { toast(`最多选择 ${p.max} 项，请先移除已选项`); return; }
        renderPicker();
      });
      $('picker-options').append(option);
    });
  }

  function humanList(values, lookup = 'heroes') {
    return arr(values).map(v => typeof v === 'object' ? (v.name ?? v.hero_name ?? v.item_name ?? itemName(v.hero_id ?? v.item_id ?? v.id, lookup)) : (app.maps[lookup]?.has(String(v)) ? itemName(v, lookup) : String(v)));
  }
  function listBlock(parent, title, values, cls = 'candidate-list') {
    const lines = arr(values).map(textOf).filter(Boolean);
    if (!lines.length) return;
    parent.append(el('h4', 'candidate-label', title));
    const ul = el('ul', cls); lines.forEach(x => ul.append(el('li', '', x))); parent.append(ul);
  }
  function addHeroStrip(parent, units) {
    if (!arr(units).length) return;
    const strip = el('div', 'hero-strip');
    arr(units).forEach(u => {
      const id = typeof u === 'object' ? idOf(u.hero_id ?? u.id) : idOf(u);
      const name = typeof u === 'object' ? (u.name ?? u.hero_name ?? itemName(id, 'heroes')) : itemName(id, 'heroes');
      const stars = typeof u === 'object' ? u.target_stars ?? u.stars : null;
      strip.append(el('span', `hero-pill${u.is_carry ? ' core' : ''}`, `${name}${stars ? ` ${stars}★` : ''}`));
    });
    parent.append(strip);
  }
  function sourceLink(source) {
    const url = typeof source === 'string' ? source : source.url ?? source.source_url;
    const label = typeof source === 'string' ? source : source.name ?? source.title ?? source.label ?? url ?? textOf(source);
    if (!url || !/^https?:\/\//i.test(url)) return el('span', 'candidate-source', label);
    const a = el('a', 'candidate-source', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  }
  function formatRate(value) {
    if (value == null || !Number.isFinite(Number(value))) return '—';
    return `${Number(value).toFixed(2)}%`;
  }
  function renderPrior(card, prior) {
    if (!prior) {
      const box = el('div', 'stat-source-box'); box.append(el('h4', '', '外部终局统计'), el('p', '', app.mode === 'orange' ? '此玩法暂无可核实的同版本规模统计。当前规则评分不代表吃鸡率。' : '当前候选未匹配可用的同版本统计。规则评分不代表吃鸡率。')); card.append(box); return;
    }
    const box = el('div', 'stat-source-box'); box.append(el('h4', '', '第三方终局统计 · 非本局预测'));
    const metrics = el('div', 'stat-metrics');
    [['登顶率', formatRate(prior.first_rate ?? prior.topRate)], ['前四率', formatRate(prior.top4_rate ?? prior.top4Rate)], ['平均名次', finite(prior.avg_placement ?? prior.avgPlacement)?.toFixed(2) ?? '—']].forEach(([label, value]) => { const m = el('div'); m.append(el('strong', '', value), el('small', '', label)); metrics.append(m); });
    box.append(metrics, el('p', '', `${prior.comp_name || ''} · 行内样本 n=${prior.sample_count ?? prior.sampleCount ?? '未知'} · ${prior.source_name || '第三方来源'}`), el('p', '', prior.warning || '来源真实性与采样口径未独立验证；终局阵容相关性不能当作当前状态的个人吃鸡概率。'));
    if (prior.source_url) box.append(sourceLink({ url: prior.source_url, name: '查看统计来源 ↗' }));
    card.append(box);
  }
  function candidateCard(candidate, index) {
    const card = el('article', `candidate-card${index === 0 ? ' top-candidate' : ''}`);
    card.dataset.candidateId = String(candidate.id ?? index);
    const rank = el('div', 'candidate-rank'); rank.append(el('span', '', `ROUTE 0${index + 1}`), el('span', 'tag', ['优先比较', '备选路线', '第三候选'][index] || '候选路线'));
    card.append(rank, el('h3', '', candidate.name || `候选路线 ${index + 1}`));
    const score = el('div', 'candidate-score'); score.append(el('strong', '', finite(candidate.score)?.toFixed(1) ?? '—'));
    const scoreLabel = el('span', '', '规则匹配分'); scoreLabel.append(el('small', '', '不是本局吃鸡概率')); score.append(scoreLabel); card.append(score);
    listBlock(card, '为什么考虑这条路线', candidate.reasons, 'candidate-reasons');
    if (arr(candidate.main_board).length) { card.append(el('h4', 'candidate-label', '终局目标 · 随来牌调整')); addHeroStrip(card, candidate.main_board); }
    const actions = candidate.actions || {};
    const actionLines = [];
    const levelPlan=actions.level_plan;
    if(levelPlan){actionLines.push(`升级方向：${levelPlan.current_level??'?'} → ${levelPlan.target_level??'待完整阵容'}${levelPlan.note?`；${levelPlan.note}`:''}`);}
    if(candidate.deck_change_required)card.append(el('div','notice notice-amber','该构筑需要更换出战卡片，仅适用于下一局战前；本局不可直接换卡。'));
    if(candidate.board_status==='core_only_no_full_board_template')card.append(el('p','field-help','这里只列核心单位，尚无完整终局棋盘，不能按此直接补齐人口。'));
    [['buy', '买'], ['hold', '留'], ['sell_candidates', '可考虑出售']].forEach(([key, label]) => {
      const units = arr(actions[key]);
      if (units.length) actionLines.push(`${label}：${units.map(u => `${u.name || itemName(u.hero_id, 'heroes')}${u.count ? ` ×${u.count}` : ''}${u.reason ? `（${u.reason}）` : ''}`).join('；')}`);
    });
    const roll = actions.roll_plan;
    if (roll && typeof roll === 'object') {
      if (roll.max_gold_spend != null) actionLines.push(`本轮搜牌预算：最多 ${roll.max_gold_spend} 金币${roll.gold_floor != null ? `，保留 ${roll.gold_floor} 金币` : ''}`);
      if (roll.note) actionLines.push(String(roll.note));
    } else if (roll) actionLines.push(textOf(roll));
    if (actionLines.length) { card.append(el('h4', 'candidate-label', '现在做什么')); actionLines.forEach(line => card.append(el('div', 'action-block', line))); }
    const itemPlans = arr(candidate.items_plan ?? candidate.item_plan);
    const statusNames = { equipped: '已携带', owned: '已有', craftable: '可合成', partial: '部分散件', missing: '缺少' };
    listBlock(card, '装备计划', itemPlans.slice(0, 7).map(p => typeof p === 'string' ? p : `${p.hero_name || itemName(p.hero_id, 'heroes')} → ${p.item_name || itemName(p.item_id)}${p.status ? ` · ${statusNames[p.status] || p.status}` : ''}${p.note ? `；${p.note}` : ''}`));
    listBlock(card, '本轮强化选项', arr(candidate.augment_choices).slice(0, 3).map(a => `${a.name || itemName(a.id, 'augments')}${a.reason ? `：${a.reason}` : ''}`));
    listBlock(card, '停手 / 调整条件', [...arr(roll?.stop_conditions), ...arr(candidate.stop_conditions)]);
    if (arr(candidate.orange_cards).length) listBlock(card, '时间卡片构筑', candidate.orange_cards.map(c => `${c.name || itemName(c.id, 'cards')} · ${c.owned ? '已持有 / 已选择' : '未确认持有'}${c.energy_assumption != null ? ` · 能量${c.energy_assumption}（待实机核验）` : ''}`));
    renderPrior(card, candidate.external_terminal_prior);
    const details = el('details'); details.append(el('summary', '', '查看过渡、解锁与依据'));
    arr(candidate.transition_boards).forEach(t => { details.append(el('h4', 'candidate-label', t.label || `${t.level ?? '?'} 人口过渡`)); addHeroStrip(details, t.units ?? t.board); });
    arr(candidate.unlock_chains).slice(0, 5).forEach(u => listBlock(details, `解锁：${u.hero_name || itemName(u.hero_id, 'heroes')}`, arr(u.tasks).map(t => `${t.note || t.task_type || '任务'}${arr(t.entity_mentions).length ? ` · ${t.entity_mentions.join('、')}` : ''} · 进度待确认`)));
    if (candidate.score_breakdown && typeof candidate.score_breakdown === 'object') {
      const keyNames = { roster: '已持单位', items: '装备', traits: '羁绊', augments: '符文', transition: '过渡' };
      listBlock(details, '评分构成（非概率）', Object.entries(candidate.score_breakdown).map(([k, v]) => `${keyNames[k] || k}：${textOf(v)}`));
    }
    if (arr(candidate.sources).length) { details.append(el('h4', 'candidate-label', '来源')); candidate.sources.forEach(s => details.append(sourceLink(s))); }
    else details.append(el('p', 'field-help', '该候选未附具体来源条目，请结合当前版本实体规则人工复核。'));
    card.append(details);
    const select = el('button', 'button button-subtle candidate-select', '记录为实际采用路线'); select.type = 'button';
    select.addEventListener('click', () => {
      app.selectedCandidateId = String(candidate.id ?? index);
      $('selected-candidate').value = app.selectedCandidateId;
      document.querySelectorAll('.candidate-card').forEach(node => { const selected = node.dataset.candidateId === app.selectedCandidateId; node.classList.toggle('selected-route', selected); const btn = node.querySelector('.candidate-select'); if (btn) btn.textContent = selected ? '已选为实际采用路线 ✓' : '记录为实际采用路线'; });
      toast('已记录路线选择，比赛结束后可保存真实名次');
    });
    card.append(select); return card;
  }
  function renderRecommendations(result) {
    app.result = result;
    $('candidate-grid').classList.remove('stale');
    const candidates = arr(result.candidates).slice(0, 3);
    $('candidate-grid').replaceChildren();
    $('recommendation-messages').replaceChildren();
    const messages = [...arr(result.errors), ...arr(result.warnings)];
    if (messages.length) { const box = el('div', 'notice notice-amber'); const list = el('ul', 'message-list'); messages.forEach(m => list.append(el('li', '', textOf(m)))); box.append(list); $('recommendation-messages').append(box); }
    if (result.score_semantics) $('recommendation-subtitle').textContent = typeof result.score_semantics === 'object' ? (result.score_semantics.description || result.score_semantics.label || '候选按规则匹配分排序；得分不是胜率，未证明能提升第一率。') : textOf(result.score_semantics);
    else $('recommendation-subtitle').textContent = '候选按当前已确认信息的规则匹配分排序；得分不代表胜率或因果收益。';
    $('recommendation-snapshot').textContent = `${app.demo ? '演示 · ' : ''}${result.patch || app.state.patch} · 当前确认局面`;
    $('recommendation-snapshot').className = 'tag positive';
    $('selected-candidate').replaceChildren(new Option('未采用 / 未记录', ''));
    if (!candidates.length) { const blank = el('div', 'recommendation-empty'); blank.append(el('div', 'empty-grid-icon', '◇'), el('h3', '', result.status === 'needs_confirmation' ? '需要先确认信息' : result.status === 'blocked' ? '当前信息暂不可推荐' : '需要更多局面信息'), el('p', '', messages.map(textOf).join('；') || '请补充可见单位、来牌、装备与资源后重新生成。')); $('candidate-grid').append(blank); }
    candidates.forEach((candidate, index) => { $('candidate-grid').append(candidateCard(candidate, index)); $('selected-candidate').add(new Option(candidate.name || `候选 ${index + 1}`, String(candidate.id ?? index))); });
    renderStateProbability(result);
    updateWorkflow(candidates.length ? 2 : 1);
  }
  function renderStateProbability(result) {
    const model = result.probability_model || {};
    const probability = result.state_probability;
    const calibrated = model.is_calibrated === true || model.calibrated === true || (model.status === 'retrospective_forecast' && model.model?.prediction_eligible === true && model.model?.calibration === 'heldout_first_place_Platt');
    let p = null;
    if (calibrated && probability != null) {
      if (typeof probability === 'number') p = probability;
      else if (Array.isArray(probability)) p = probability[0];
      else p = probability.first_place_probability ?? probability.first_probability ?? probability.p_first ?? probability.first;
    }
    $('state-probability').textContent = p != null && Number.isFinite(Number(p)) && p >= 0 && p <= 1 ? `${(Number(p) * 100).toFixed(1)}%（留出校准，未实战验证）` : '尚不可用';
    $('probability-reason').textContent = model.reason || (p == null ? '未取得已训练并校准的本局概率。下方规则匹配分及终局统计不能替代个人吃鸡概率。' : '仅适用于当前输入及模型验证范围；与下方第三方终局统计分别展示。');
  }
  async function recommend(event) {
    event.preventDefault();
    if (!app.state.confirmed) { toast('请先核对并确认当前局面'); return; }
    const token = ++app.recommendationToken; const revision = app.revision;
    app.recommending = true; syncConfirmation();
    try {
      const payload = copy(app.state);
      payload.board = payload.board.filter(x => x.hero_id); payload.bench = payload.bench.filter(x => x.hero_id);
      const result = await api('/api/recommend', jsonOptions(payload));
      if (token !== app.recommendationToken || revision !== app.revision) return;
      renderRecommendations(result);
      $('recommendations').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) { if (token === app.recommendationToken) notify(`生成路线失败：${error.message}`, true); }
    finally { if (token === app.recommendationToken) { app.recommending = false; syncConfirmation(); } }
  }

  async function loadDemo() {
    const mode = app.mode; const revision = app.revision;
    $('load-demo').disabled = true;
    try {
      const result = await api(`/api/demo?mode=${mode}`);
      if (app.mode !== mode || app.revision !== revision) return;
      app.state = normalizeState(result.state || result); app.state.screenshot_id = null; app.state.is_demo = true; app.demo = true; app.lastFile = null; app.negativeRegions=[]; $('negative-reviewed').checked=false; app.revision += 1;
      app.evidence = []; app.uncertain = []; clearImage(); clearRecommendations(); renderEditor(); renderEvidence(); updateWorkflow(1);
      $('screen-type').textContent = '演示 · 无截图';
      $('recognition-capabilities').textContent = '当前为用户主动加载的演示数据，没有上传截图或产生识别结果。请确认示例后体验规则推荐。';
      notify('已加载演示输入。演示不进入真实对局训练集，也不证明推荐效果。');
    } catch (error) { notify(`演示输入加载失败：${error.message}`, true); }
    finally { $('load-demo').disabled = false; }
  }
  function clearDemo() {
    app.state = emptyState(app.mode); app.demo = false; app.lastFile = null; app.negativeRegions=[]; $('negative-reviewed').checked=false; app.revision += 1; app.evidence = []; app.uncertain = [];
    clearImage(); clearRecommendations(); renderEditor(); renderEvidence(); updateWorkflow(0);
    $('app-message').classList.add('hidden');
    $('recognition-capabilities').textContent = '尚未调用识别服务。识别能力与不确定项会在上传后显示。';
  }
  async function saveResult(event) {
    event.preventDefault();
    if (app.demo) { toast('演示输入不能保存为真实对局'); return; }
    if (!app.state.screenshot_id) { toast('保存训练记录需要关联实际上传的截图'); return; }
    const placement = finite($('placement').value);
    if (!placement || placement < 1 || placement > 8) { toast('请选择真实最终名次'); $('placement').focus(); return; }
    if (!app.state.confirmed) { toast('保存前请先核对并确认要记录的局面'); $('confirm-state').focus(); return; }
    if (!app.state.board.length && !app.state.bench.length && !app.state.item_ids.length && !app.state.augment_ids.length && !app.state.shop.some(Boolean)) { toast('当前没有可记录的局面，请补充实际对局状态'); return; }
    app.state.match_id = $('match-id').value.trim() || `match-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    $('match-id').value = app.state.match_id;
    const body = { state: copy(app.state), placement, match_id: app.state.match_id };
    const selected = $('selected-candidate').value;
    if (selected) body.selected_candidate_id = selected;
    $('save-result').disabled = true;
    try {
      const result = await api('/api/matches/events', jsonOptions(body));
      $('result-message').textContent = result.message || `已保存：${app.state.match_id} · 第 ${placement} 名。记录不等于模型已获得提升。`;
      toast('真实局面与名次已保存'); updateWorkflow(3); await Promise.allSettled([loadHistory(), loadModelStatus()]);
    } catch (error) { $('result-message').textContent = `保存失败：${error.message}`; notify(`记录保存失败：${error.message}`, true); }
    finally { syncConfirmation(); }
  }
  function modelMetric(parent, value, label) { const metric = el('div', 'model-metric'); metric.append(el('strong', '', value), el('span', '', label)); parent.append(metric); }
  function displayModelStatus(data) {
    const status = data.status || 'unknown';
    const calibrated = data.is_calibrated === true || data.calibrated === true || (status === 'trained_retrospective_only' && data.model?.prediction_eligible === true);
    const statusLabels = { not_trained: '未训练', insufficient_data: '样本不足', untrained: '未训练', ready: calibrated ? '已训练并校准' : '已训练 · 待校准', trained: calibrated ? '已训练并校准' : '已训练 · 待校准', no_model: '未训练', unavailable: '暂不可用', collecting: '积累样本中', blocked: '条件不足', trained_retrospective_only:'回顾性评估通过', heldout_underperformed:'留出评估未达标', artifact_invalid:'模型校验失败' };
    $('model-status-tag').textContent = statusLabels[status] || (calibrated ? '已校准' : '未确认校准');
    $('model-status-tag').className = `tag${calibrated ? ' positive' : ''}`;
    $('model-description').textContent = data.reason || data.message || '模型训练与校准状态需要明确验证后才能输出本局概率。';
    $('model-metrics').replaceChildren();
    const samples = data.observations ?? data.sample_count ?? data.n_samples ?? data.training_samples ?? data.samples;
    const matches = data.unique_matches ?? data.match_count ?? data.n_unique_matches;
    if (finite(samples) !== null) modelMetric($('model-metrics'), Number(samples), '已记录状态');
    if (finite(matches) !== null) modelMetric($('model-metrics'), Number(matches), '独立对局');
    if (finite(data.minimum_matches ?? data.minimum_samples ?? data.min_samples) !== null) modelMetric($('model-metrics'), data.minimum_matches ?? data.minimum_samples ?? data.min_samples, '最低独立对局条件');
    if (Array.isArray(data.requirements)) { const requirements = el('ul', 'candidate-list'); data.requirements.forEach(x => requirements.append(el('li', '', textOf(x)))); $('model-metrics').append(requirements); }
  }
  async function loadModelStatus() {
    const mode = app.mode;
    try { const data = await api(`/api/model/status?mode=${mode}&patch=${encodeURIComponent(app.state.patch)}`); if(mode === app.mode) displayModelStatus(data); }
    catch (error) { $('model-status-tag').textContent = '状态读取失败'; $('model-description').textContent = error.message; }
  }
  async function trainModel() {
    const mode=app.mode; const patch=app.state.patch;
    $('train-model').disabled = true; $('train-model').textContent = '正在检查并训练…';
    try {
      const result = await api('/api/model/train', jsonOptions({mode,patch}));
      if(mode!==app.mode)return;
      displayModelStatus(result);
      toast(result.reason || result.message || '训练检查已完成，请查看本地模型状态');
      await loadModelStatus();
    } catch (error) { $('model-description').textContent = `训练未完成：${error.message}`; toast(`训练未完成：${error.message}`); }
    finally { $('train-model').disabled = false; $('train-model').textContent = '检查样本并训练'; }
  }
  async function loadHistory() {
    try {
      const data = await api('/api/history');
      const records = Array.isArray(data) ? data : arr(data.events ?? data.items ?? data.history ?? data.matches ?? data.records);
      $('history-list').replaceChildren();
      if (!records.length) { $('history-list').append(el('p', 'empty-note', '还没有本地对局记录。真实记录会显示在这里，演示不计入训练样本。')); return; }
      const scroll = el('div', 'history-scroll'); const table = el('table', 'history-table');
      const head = el('thead'); const hr = el('tr'); ['记录时间', '对局 / 玩法', '决策回合', '最终名次', '采用路线'].forEach(x => hr.append(el('th', '', x))); head.append(hr); table.append(head);
      const body = el('tbody'); records.slice(0, 15).forEach(r => {
        const state = r.state || {}; const row = el('tr'); const time = r.created_at ?? r.timestamp ?? r.saved_at;
        const date = time ? new Date(time) : null; const formatted = date && !Number.isNaN(date.getTime()) ? date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '时间未记录';
        const mode = r.mode ?? state.mode;
        row.append(el('td', '', formatted), el('td', '', `${r.match_id ?? state.match_id ?? '未命名'} · ${mode === 'orange' ? '大橘大利' : mode === 'nature' ? '自然之力' : '玩法未知'}`), el('td', '', r.stage ?? state.stage ?? '未知'), el('td', 'history-place', r.placement != null ? `第 ${r.placement} 名` : '未记录'), el('td', '', r.selected_candidate_name ?? r.selected_candidate_id ?? '未采用 / 未记录'));
        body.append(row);
      }); table.append(body); scroll.append(table); $('history-list').append(scroll);
    } catch (error) { $('history-list').replaceChildren(el('p', 'empty-note', `记录暂不可读：${error.message}`)); }
  }
  function bindEvents() {
    document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => changeMode(button.dataset.mode)));
    document.querySelectorAll('[data-add-unit]').forEach(button => button.addEventListener('click', () => { const field = button.dataset.addUnit; if (app.state[field].length >= 20) { toast('最多录入 20 个单位，请检查重复项'); return; } app.state[field].push({ hero_id: '', stars: null, item_ids: [] }); markChanged(); renderUnits(field); }));
    document.querySelectorAll('[data-picker]').forEach(button => button.addEventListener('click', () => { const field = button.dataset.picker; const cfg = chipConfig[field]; openPicker({ ...cfg, values: app.state[field], onApply: values => { app.state[field] = values; markChanged(); renderChips(field); } }); }));
    ['stage', 'hp', 'gold', 'level'].forEach(key => $(key).addEventListener('input', () => { app.state[key] = key === 'stage' ? ($(key).value.trim() || null) : finite($(key).value); markChanged(); }));
    $('patch').addEventListener('input',()=>{app.state.patch=$('patch').value.trim();markChanged();});
    $('patch').addEventListener('change',loadModelStatus);
    $('match-id').addEventListener('input', () => { app.state.match_id = $('match-id').value.trim(); markChanged(); });
    $('portal').addEventListener('change', () => { app.state.portal = $('portal').value || null; markChanged(); });
    $('confirm-state').addEventListener('change', () => { app.state.confirmed = $('confirm-state').checked; syncConfirmation(); updateWorkflow(app.state.confirmed ? 2 : 1); });
    $('state-form').addEventListener('submit', recommend);
    $('upload-zone').addEventListener('click', () => $('screenshot-file').click());
    $('upload-zone').addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('screenshot-file').click(); } });
    $('replace-image').addEventListener('click', () => $('screenshot-file').click());
    $('screenshot-file').addEventListener('change', event => recognizeFile(event.target.files[0]));
    ['dragenter', 'dragover'].forEach(name => $('upload-zone').addEventListener(name, event => { event.preventDefault(); $('upload-zone').classList.add('dragging'); }));
    ['dragleave', 'drop'].forEach(name => $('upload-zone').addEventListener(name, event => { event.preventDefault(); $('upload-zone').classList.remove('dragging'); }));
    $('upload-zone').addEventListener('drop', event => recognizeFile(event.dataTransfer.files[0]));
    $('show-evidence').addEventListener('change', () => $('evidence-overlay').classList.toggle('hidden', !$('show-evidence').checked));
    $('draw-layout').addEventListener('click',()=>{if(!app.lastFile){toast('请先上传实际截图');return;}setDrawing(!(app.drawing && app.drawTarget==='layout'),'layout');if(app.drawing){$('layout-message').textContent=`现在在原图上拖出“${layoutNames[$('layout-field').value]}”区域。每次只框一个图标或数值。`;$('image-stage').scrollIntoView({block:'center',behavior:'smooth'});}});
    $('image-stage').addEventListener('pointerdown',event=>{if(!app.drawing||!app.lastFile||event.isPrimary===false||app.activePointerId!==null)return;event.preventDefault();app.activePointerId=event.pointerId;app.drawStart=drawPoint(event);$('image-stage').setPointerCapture(event.pointerId);drawPreview([app.drawStart[0],app.drawStart[1],0,0]);});
    $('image-stage').addEventListener('pointermove',event=>{if(app.drawing&&app.drawStart&&event.pointerId===app.activePointerId)drawPreview(drawBBox(app.drawStart,drawPoint(event)));});
    $('image-stage').addEventListener('pointerup',event=>{if(!app.drawing||!app.drawStart||event.pointerId!==app.activePointerId)return;const box=drawBBox(app.drawStart,drawPoint(event));const target=app.drawTarget;setDrawing(false);if(box[2]>.003&&box[3]>.003){if(target==='negative'){if(!$('negative-reviewed').checked){toast('请先核对本区域不含当前四项数值');renderLayout();return;}app.negativeRegions.push({bbox:box.map(x=>Number(x.toFixed(6))),reason:$('negative-reason').value,confirmed:true,not_fields:['stage','gold','hp','level']});toast('已添加本图排除区域');}else{app.layout.slots.push({field:$('layout-field').value,bbox:box.map(x=>Number(x.toFixed(6)))});toast('区域已添加；可继续框选，或使用当前区域重新识别');}}else toast('框选区域过小，请重新拖动');renderLayout();});
    $('image-stage').addEventListener('pointercancel',event=>{if(event.pointerId===app.activePointerId){setDrawing(false);renderLayout();}});
    $('image-stage').addEventListener('lostpointercapture',event=>{if(event.pointerId===app.activePointerId){setDrawing(false);renderLayout();}});
    $('draw-negative').addEventListener('click',()=>{if(!app.lastFile){toast('请先上传实际截图');return;}if(!$('negative-reviewed').checked){toast('请先核对此区域不是当前四项数值');return;}setDrawing(!(app.drawing&&app.drawTarget==='negative'),'negative');if(app.drawing){$('layout-message').textContent='在截图上框出已核对的排除区域';$('image-stage').scrollIntoView({block:'center',behavior:'smooth'});}});
    $('clear-negative-regions').addEventListener('click',()=>{app.negativeRegions=[];renderLayout();});
    $('save-layout').addEventListener('click',saveLayout);
    $('saved-layout').addEventListener('change',()=>{const saved=app.savedLayouts.find(p=>String(p.id)===$('saved-layout').value);if(saved){app.layout=copy(saved.profile);$('layout-name').value=saved.name;renderLayout();toast('已加载布局，请检查区域与当前截图是否对应');}});
    $('recognize-layout').addEventListener('click',()=>{if(app.lastFile)recognizeFile(app.lastFile);});
    $('load-demo').addEventListener('click', loadDemo); $('clear-demo').addEventListener('click', clearDemo);
    $('close-picker').addEventListener('click', () => $('entity-picker').close());
    $('picker-search').addEventListener('input', renderPicker);
    $('apply-picker').addEventListener('click', () => { if (app.picker) app.picker.onApply([...app.picker.values]); $('entity-picker').close(); });
    $('entity-picker').addEventListener('click', event => { if (event.target === $('entity-picker')) { const r = $('entity-picker').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('entity-picker').close(); } });
    $('result-form').addEventListener('submit', saveResult);
    $('selected-candidate').addEventListener('change', () => { app.selectedCandidateId = $('selected-candidate').value; document.querySelectorAll('.candidate-card').forEach(node => node.classList.toggle('selected-route', node.dataset.candidateId === app.selectedCandidateId)); });
    $('save-recognition-feedback').addEventListener('click',async()=>{
      if(app.demo||!app.state.screenshot_id||!app.state.confirmed){toast('请上传真实截图并先核对确认');return;}
      if(!app.state.match_id){toast('请先填写对局编号，同一局使用同一个编号，再核对确认');return;}
      const slots=app.layout.slots.filter(s=>['stage','gold','hp','level'].includes(s.field));
      if(!slots.length&&!app.negativeRegions.length){toast('请先框出已确认数值或已核对的排除区域');return;}
      const button=$('save-recognition-feedback');button.disabled=true;
      try{const result=await api('/api/recognition/feedback',jsonOptions({state:copy(app.state),layout_profile:{...app.layout,slots},negative_regions:copy(app.negativeRegions),replace_annotations:$('replace-recognition-annotations').checked}));$('recognition-feedback-message').textContent=result.message;toast('已保存识别纠错样本');}
      catch(error){$('recognition-feedback-message').textContent=error.message;}
      finally{button.disabled=false;}
    });
    $('train-model').addEventListener('click', trainModel);
    $('refresh-history').addEventListener('click', loadHistory);
    document.querySelectorAll('.nav-link').forEach(a => a.addEventListener('click', () => { document.querySelectorAll('.nav-link').forEach(x => x.classList.remove('active')); a.classList.add('active'); }));
  }
  async function init() {
    bindEvents(); renderEditor();
    await Promise.allSettled([
      api('/api/health').then(health => { $('service-status').textContent = '● 本地服务已连接'; if(health.version_watch?.notice_zh){const node=$('version-notice');node.classList.remove('hidden');node.replaceChildren(el('span','',health.version_watch.notice_zh));if(health.version_watch.source_url){const link=el('a','text-button',' 查看官方公告');link.href=health.version_watch.source_url;link.target='_blank';link.rel='noopener noreferrer';node.append(link);}} }).catch(error => { $('service-status').textContent = '本地服务未连接'; notify(`无法连接本地服务：${error.message}。请使用服务地址打开页面。`, true); }),
      loadCatalog(), loadModelStatus(), loadHistory(), loadLayouts()
    ]);
  }
  init();
})();
