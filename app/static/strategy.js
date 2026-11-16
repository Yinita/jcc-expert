(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const arr = (value) => Array.isArray(value) ? value : [];
  const state = { data: null, mode: 'nature', index: 'traits', traitKey: '', compId: '', phaseId: '', moreComps: false, heroes: new Map(), extraHeroes: new Map(), traits: new Map(), comps: new Map(), items: new Map() };
  const costColors = ['#8b9ba6', '#8b9ba6', '#78af82', '#71a6c9', '#b692ce', '#d8ae68', '#e68b7d', '#e68b7d'];
  const kindName = (kind) => kind === 'class' ? '职业' : kind === 'origin' ? '特质' : '羁绊';
  const traitKey = (trait) => trait.key || `${trait.kind}:${trait.id}`;
  const isSource = (kind) => ['source', 'official_lineup'].includes(kind);
  const planStyle = (value) => ({ quality_reroll: '关键回合搜质量', slow_roll: '留经济慢搜 / 低费追星', card_conditional: '卡片兑现与核心解锁', upgrade_and_stabilize: '提人口后稳质量' }[value] ?? (/^[a-z_]+$/i.test(String(value)) ? '运营条件待核验' : value ?? '运营条件待补充'));
  const textOf = (value) => typeof value === 'object' && value !== null ? value.text ?? value.description ?? value.action ?? value.reason ?? '' : value;

  function el(tag, className = '', text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    return element;
  }

  function guideUrl(heroId = '') {
    const base = location.pathname.includes('/static/') ? './guide.html' : '../guide/';
    return new URL(`${base}${heroId ? `#${state.mode}/${encodeURIComponent(heroId)}/standard` : ''}`, location.href).href;
  }

  function safeLink(value) {
    try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
  }

  function iconUrl(value) {
    if (!value || typeof value !== 'string') return null;
    if (value.startsWith('https://game.gtimg.cn/')) return value;
    const path = value.replace(/^\.?\/?assets\//, '');
    if (!/^(nature|orange)\/(heros|heroes|items|cards)\/[\w.-]+\.(png|jpg|webp)$/i.test(path)) return null;
    return new URL(`../assets/${path}`, location.href).href;
  }

  function icon(record, className = 'unit-portrait') {
    const wrapper = el('span', className, String(record?.name || '?').slice(0, 1));
    const url = iconUrl(record?.icon ?? record?.icon_url);
    if (url) {
      const image = document.createElement('img'); image.src = url; image.alt = ''; image.loading = 'lazy'; image.decoding = 'async';
      image.addEventListener('error', () => { wrapper.textContent = String(record?.name || '?').slice(0, 1); }, { once: true });
      wrapper.replaceChildren(image);
    }
    return wrapper;
  }

  function sourceLine(source) {
    const sources = Array.isArray(source) ? source : source ? [source] : [];
    const line = el('div', 'source-line');
    sources.forEach((entry, index) => {
      if (!entry) return;
      if (index) line.append(el('span', '', '·'));
      const title = entry.title ?? entry.name ?? '来源记录'; const url = safeLink(entry.url ?? entry.source_url);
      if (url) { const link = el('a', '', `${title} ↗`); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; line.append(link); }
      else line.append(el('span', '', title));
      if (entry.version ?? entry.patch) line.append(el('span', '', `版本 ${entry.version ?? entry.patch}`));
      if (entry.author) line.append(el('span', '', entry.author));
      if (entry.published_at) line.append(el('span', '', String(entry.published_at).slice(0, 10)));
    });
    return line.childNodes.length ? line : null;
  }

  function evidence(kind, sourceLabel = '来源模板', conditionalLabel = '条件性推导') {
    return el('span', `evidence-tag ${isSource(kind) ? 'official' : 'conditional'}`, isSource(kind) ? sourceLabel : conditionalLabel);
  }

  function panel(title, kicker = '') {
    const section = el('section', 'panel'); const heading = el('div', 'section-heading'); heading.append(el('h3', '', title));
    if (kicker) heading.append(el('span', 'eyebrow', kicker)); section.append(heading); return section;
  }

  function bullets(values, className = 'detail-bullets') {
    const list = el('ul', className);
    arr(values).filter(Boolean).forEach((value) => list.append(el('li', '', textOf(value))));
    return list.childNodes.length ? list : null;
  }

  function heroRecord(value) {
    const id = String(typeof value === 'object' && value !== null ? value.hero_id ?? value.id : value);
    if (state.heroes.has(id)) return state.heroes.get(id);
    const record = { id, name: value?.hero_name ?? value?.name ?? state.extraHeroes.get(id)?.name ?? `单位 ${id}`, cost: null, traits: [], is_pet: Boolean(value?.is_pet || value?.type === 'pet') };
    state.extraHeroes.set(id, record); return record;
  }

  function heroCard(value, role = '') {
    const hero = heroRecord(value); const button = el('button', 'unit-card'); button.type = 'button'; button.dataset.heroId = hero.id;
    if (/目标核心|候选体系/.test(role)) button.classList.add('unverified');
    button.style.setProperty('--cost-color', costColors[Math.max(0, Math.min(7, Number(hero.cost) || 0))]);
    button.append(icon(hero)); const copy = el('span', 'unit-copy'); copy.append(el('strong', '', hero.name));
    const classes = arr(hero.traits).filter((trait) => trait.kind === 'class').map((trait) => trait.name);
    copy.append(el('small', 'cost', `${hero.cost == null ? '特殊单位' : `${hero.cost}费`}${classes.length ? ` · ${classes.join(' / ')}` : ''}`));
    if (role) copy.append(el('small', 'unit-role', role));
    if (hero.template_only_form || hero.availability === 'conditional_form') copy.append(el('small', 'conditional-form', '条件形态 · 需核对'));
    button.append(copy); return button;
  }

  function heroGrid(ids, role = '') {
    const grid = el('div', 'unit-grid'); arr(ids).forEach((id) => grid.append(heroCard(id, role))); return grid;
  }

  function itemButton(id) {
    const item = state.items.get(String(id)) ?? { id, name: `装备 ${id}` };
    const button = el('button', 'item-button'); button.type = 'button'; button.dataset.itemId = String(id);
    button.append(icon(item, 'item-icon'), el('span', '', item.name)); return button;
  }

  function setMode(mode, selected = {}) {
    if (!state.data.modes[mode]) return;
    state.mode = mode; state.phaseId = ''; state.moreComps = false; state.extraHeroes = new Map();
    const data = state.data.modes[mode];
    state.heroes = new Map(arr(data.heroes).map((hero) => [String(hero.id), hero]));
    state.items = new Map(arr(data.items).map((item) => [String(item.id), item]));
    state.traits = new Map(arr(data.traits).map((trait) => [traitKey(trait), trait]));
    state.comps = new Map(arr(data.comps).map((comp) => [String(comp.id), comp]));
    state.traitKey = state.traits.has(selected.trait) ? selected.trait : state.traits.keys().next().value ?? '';
    state.compId = state.comps.has(String(selected.comp)) ? String(selected.comp) : '';
    state.index = selected.index === 'comps' ? 'comps' : 'traits';
    $('strategy-search').value = ''; $('trait-kind').value = '';
    document.body.dataset.mode = mode;
    document.querySelectorAll('button[data-mode]').forEach((button) => { const active = button.dataset.mode === mode; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
    $('guide-link').href = guideUrl();
    renderDetail(); renderIndex();
  }

  function heroNames(ids) { return arr(ids).map((id) => heroRecord(id).name).join(' '); }

  function cardNames(ids) {
    const cards = arr(state.data.modes[state.mode].cards);
    return arr(ids).map((id) => cards.find((card) => String(card.id) === String(id))?.name ?? '名称待核验的来源卡片').join('、');
  }

  function compText(comp) {
    return [comp.name, comp.summary, heroNames([...arr(comp.core_ids), ...arr(comp.carry_ids), ...arr(comp.frontline_ids), ...arr(comp.flex_ids)]), ...arr(comp.trait_keys).map((key) => state.traits.get(key)?.name ?? '')].join(' ').toLocaleLowerCase();
  }

  function renderIndex() {
    const query = $('strategy-search').value.trim().toLocaleLowerCase(); const kind = $('trait-kind').value;
    document.querySelectorAll('[data-index]').forEach((button) => { const active = button.dataset.index === state.index; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
    $('index-title').textContent = state.index === 'traits' ? '羁绊索引' : '阵容总览';
    const values = state.index === 'traits' ? [...state.traits.values()].filter((trait) => (!kind || trait.kind === kind)
      && (!query || [trait.name, trait.id, heroNames(trait.native_hero_ids), ...arr(trait.linked_comp_ids).map((id) => state.comps.get(String(id))?.name ?? '')].join(' ').toLocaleLowerCase().includes(query)))
      : [...state.comps.values()].filter((comp) => (!query || compText(comp).includes(query)) && (!kind || arr(comp.trait_keys).some((key) => state.traits.get(key)?.kind === kind)));
    $('index-count').textContent = `${values.length} 条`;
    const list = $('strategy-index'); list.replaceChildren();
    values.forEach((value) => {
      const isTrait = state.index === 'traits'; const id = isTrait ? traitKey(value) : String(value.id);
      const button = el('button', `index-entry${id === (isTrait ? state.traitKey : state.compId) ? ' selected' : ''}`); button.type = 'button';
      button.dataset[isTrait ? 'traitKey' : 'compId'] = id;
      button.setAttribute('aria-pressed', String(id === (isTrait ? state.traitKey : state.compId)));
      button.append(el('span', `index-symbol${isTrait && value.kind === 'origin' ? ' origin' : ''}`, isTrait ? value.kind === 'class' ? '职' : '特' : '阵'));
      const copy = el('span', 'index-copy'); copy.append(el('strong', '', value.name));
      const subtitle = isTrait ? `${kindName(value.kind)} · ${arr(value.native_hero_ids).length} 位原生棋子${value.strategy_type === 'unique' ? ' · 独有挂件' : ''}`
        : `${value.kind === 'official_lineup' ? '官方收录阵容' : '卡组条件构筑'} · ${planStyle(value.roll_plan?.style)}`;
      copy.append(el('small', '', subtitle)); button.append(copy, el('span', 'index-arrow', '↗')); list.append(button);
    });
    $('index-empty').hidden = values.length > 0; list.hidden = !values.length;
  }

  function traitHero(trait) {
    const header = el('header', 'trait-hero'); header.append(el('p', 'eyebrow', `${state.data.modes[state.mode].name} / TRAIT ${trait.id}`));
    const title = el('div', 'trait-title'); title.append(el('h2', '', trait.name), el('span', `type-tag${trait.kind === 'origin' ? ' origin' : ''}`, kindName(trait.kind)));
    if (trait.verified === false) title.append(el('span', 'type-tag warning', '名称待核验'));
    if (trait.strategy_type === 'unique') {
      const units = arr(trait.native_hero_ids).map(heroRecord);
      const highCost = units.length > 0 && units.every((hero) => Number(hero.cost) >= 4);
      title.append(el('span', 'type-tag warning', highCost ? '独有 / 高费挂件' : '独有机制 / 单卡补强'));
    }
    else if (trait.strategy_type === 'splash') title.append(el('span', 'type-tag', '补强与混搭'));
    else if (trait.strategy_type === 'vertical') title.append(el('span', 'type-tag', '可追纵向体系'));
    header.append(title, el('p', 'trait-summary', trait.summary || trait.description || '当前资料不足，保留待核验。'));
    if (trait.strategy_type === 'unique') header.append(el('p', 'trait-use', '独有羁绊主要描述该棋子的专属机制。它不自动构成一套可从前期起手的阵容。'));
    const thresholds = arr(trait.breakpoints).length ? trait.breakpoints : arr(trait.tiers).map((tier) => tier.count);
    if (thresholds.length) { const row = el('div', 'breakpoint-row'); thresholds.forEach((count) => { const pill = el('span', 'breakpoint-pill'); pill.append(el('strong', '', count), document.createTextNode(' 激活档位')); row.append(pill); }); header.append(row); }
    const source = sourceLine(trait.source); if (source) header.append(source); return header;
  }

  function linkedComps(trait) {
    return arr(trait.linked_comp_ids).map((id) => state.comps.get(String(id))).filter(Boolean);
  }

  function compPreview(comp) {
    const button = el('button', `comp-preview${state.compId === String(comp.id) ? ' selected' : ''}`); button.type = 'button'; button.dataset.compId = String(comp.id);
    const title = el('div', 'comp-preview-title'); title.append(el('h4', '', comp.name), evidence(comp.kind, '官方收录阵容', '条件卡组构筑'));
    if (comp.source_status === 'provisional_recipe') title.append(el('span', 'evidence-tag conditional', '配方来源待核验'));
    button.append(title);
    if (comp.summary) button.append(el('p', '', comp.summary));
    const relation = arr(comp.trait_links).find((link) => link.key === state.traitKey);
    if (relation) {
      const full = relation.full_breakpoint ?? relation.active_breakpoint;
      const native = relation.native_breakpoint;
      const required = Number(relation.required_emblems_for_full) || 0;
      const forms = arr(relation.conditional_form_ids);
      const conditions = [];
      if (required > 0) conditions.push(`模板 ${full} 档需要至少 ${required} 个纹章；${native ? `不含纹章时达到 ${native} 档` : '不含纹章时尚未成档'}。`);
      if (forms.length && relation.status === 'conditional') conditions.push(`该档还需指定条件形态（${[...new Set(forms.map((id) => heroRecord(id).name))].join('、')}）或其额外计数，不能用同名基础形态替代。`);
      if (arr(relation.requires_card_ids).length) {
        conditions.push(`需${cardNames(relation.requires_card_ids)}实际触发${Number(relation.card_bonus_count) > 0 ? `，卡片净增 ${relation.card_bonus_count} 个计数` : ''}。`);
        if (relation.note) conditions.push(relation.note);
      }
      if (!conditions.length && relation.status === 'conditional') conditions.push('模板档位依赖额外条件，需核对该方案的形态、装备与触发说明。');
      if (!conditions.length) conditions.push(relation.status === 'activated'
        ? `模板含 ${relation.native_unit_count ?? relation.native_count} 个不同原生棋子，达到 ${native ?? full} 档；不代表当前实战已激活。`
        : '此路线仅有关联棋子，模板未达到本羁绊起始档。');
      button.append(el('p', 'relation-note', conditions.join('')));
    }
    const roster = el('div', 'mini-roster');
    const ids = [...new Set([...arr(comp.carry_ids), ...arr(comp.frontline_ids), ...arr(comp.core_ids)])].slice(0, 7);
    ids.forEach((id) => { const hero = heroRecord(id); const unit = el('span', 'mini-unit'); unit.style.setProperty('--cost-color', costColors[Math.max(0, Math.min(7, Number(hero.cost) || 0))]); unit.append(icon(hero), el('span', '', hero.name)); roster.append(unit); });
    button.append(roster);
    const tags = el('div', 'tag-row'); arr(comp.trait_keys).slice(0, 4).forEach((key) => { const trait = state.traits.get(key); if (trait) tags.append(el('span', 'small-tag', `${kindName(trait.kind)} · ${trait.name}`)); }); button.append(tags);
    return button;
  }

  function renderTraitDetail(trait) {
    const root = $('strategy-detail'); root.replaceChildren(traitHero(trait));
    const grid = el('div', 'detail-grid'); const main = el('div', 'main-column'); const side = el('div', 'side-column');
    const natives = panel('原生体系牌', 'NATIVE UNITS');
    natives.append(el('p', 'section-note', '这些棋子原生拥有此职业或特质。纹章外援与召唤物不混入原生名单。'));
    if (arr(trait.native_hero_ids).length) natives.append(heroGrid(trait.native_hero_ids)); else natives.append(el('p', 'empty-note', '当前官方快照未解析到原生棋子，暂不猜测。'));
    if (trait.stage_pools && Object.values(trait.stage_pools).some((pool) => arr(pool).length)) {
      const pools = el('details', 'pool-details'); pools.append(el('summary', '', '按阶段看可选池 · 费用参考'));
      pools.append(el('p', 'section-note', '这是按费用划分的来牌候选池，不是已验证的过渡棋盘，也不表示必须购买所有棋子。'));
      [['early', '前期可选池'], ['mid', '中期可选池'], ['late', '后期补强池']].forEach(([key, title]) => {
        if (!arr(trait.stage_pools[key]).length) return; pools.append(el('h4', 'role-heading', title), heroGrid(trait.stage_pools[key]));
      }); natives.append(pools);
    }
    main.append(natives);
    const related = panel('关联阵容与运营路线', 'FOLLOW THE PLAN'); const comps = linkedComps(trait);
    if (!comps.length) related.append(el('p', 'empty-note', trait.strategy_type === 'unique' ? '当前没有独立成套模板。先将这张独有棋子作为已有阵容的条件补强，核对费用、解锁要求和上场价值。' : '当前没有来源明确的完整阵容模板；原生名单与激活断点仍可作为搭配依据。'));
    else {
      related.append(el('p', 'section-note', '选择一套阵容，在本页展开核心牌、过渡棋盘、搜牌条件、装备与站位。'));
      const list = el('div', 'comp-list'); const shown = state.moreComps ? comps : comps.slice(0, 6); shown.forEach((comp) => list.append(compPreview(comp))); related.append(list);
      if (comps.length > 6) { const toggle = el('button', 'text-button', state.moreComps ? '收起其余阵容 ↑' : `展开其余 ${comps.length - 6} 套阵容 ↓`); toggle.type = 'button'; toggle.dataset.moreComps = 'true'; toggle.style.marginTop = '13px'; related.append(toggle); }
    }
    main.append(related);
    const tiers = panel('关键断点', 'TRAIT BREAKPOINTS'); const tierList = el('div', 'breakpoint-details');
    arr(trait.tiers).forEach((tier) => { const block = el('article', 'breakpoint-detail'); block.append(el('h4', '', `${tier.count} ${trait.name}`), el('p', '', tier.effect || '具体效果尚未收录。')); tierList.append(block); });
    if (tierList.childNodes.length) tiers.append(tierList); else tiers.append(el('p', 'empty-note', '暂无完整档位效果，请以实际客户端为准。')); side.append(tiers);
    const notes = panel('组队条件与取舍', 'WHEN IT FITS');
    if (trait.description && trait.description !== trait.summary) notes.append(el('p', 'section-note', trait.description));
    const play = bullets(trait.play_notes); const conditions = bullets(trait.conditions); if (play) notes.append(play); if (conditions) notes.append(conditions);
    if (!play && !conditions && !trait.description) notes.append(el('p', 'empty-note', '没有足够资料支持固定运营路线。')); side.append(notes);
    const relatedOnly = arr(trait.related_comp_ids).filter((id) => !arr(trait.linked_comp_ids).map(String).includes(String(id))).map((id) => state.comps.get(String(id))).filter(Boolean);
    if (relatedOnly.length) {
      const splash = panel('作为挂件的关联方案', 'INCIDENTAL LINKS');
      splash.append(el('p', 'section-note', '这些方案只有关联棋子，未达到本羁绊起始档。它们不属于追满此羁绊的成套路线。'));
      relatedOnly.forEach((comp) => { const button = el('button', 'trait-reference', comp.name); button.type = 'button'; button.dataset.compId = String(comp.id); splash.append(button); }); side.append(splash);
    }
    grid.append(main, side); root.append(grid);
    const selected = [...comps, ...relatedOnly].find((comp) => String(comp.id) === state.compId);
    if (selected) {
      if (!comps.some((comp) => String(comp.id) === state.compId)) root.append(el('p', 'callout', '当前展开的是挂件关联方案，模板未激活本羁绊的起始档，不应作为本羁绊成套运营。'));
      root.append(renderComp(selected));
    }
  }

  function validCell(unit) { return Number.isInteger(unit.row) && Number.isInteger(unit.col) && unit.row >= 1 && unit.row <= 4 && unit.col >= 1 && unit.col <= 7; }

  function renderBoard(units, comp) {
    const stage = el('div', 'board-stage'); stage.append(el('div', 'board-label', '对手方向 ↑ · 己方四排七列'));
    const core = new Set([...arr(comp.core_ids), ...arr(comp.carry_ids)].map(String));
    for (let row = 1; row <= 4; row += 1) {
      const line = el('div', 'hex-row');
      for (let col = 1; col <= 7; col += 1) {
        const occupants = arr(units).filter((unit) => unit.row === row && unit.col === col);
        const unit = occupants[0]; const hero = unit ? heroRecord(unit) : null;
        const cell = el(unit ? 'button' : 'span', `hex-cell${unit ? ` occupied ${unit.is_pet || unit.type === 'pet' ? 'pet' : core.has(String(unit.hero_id)) ? 'core' : 'support'}` : ''}`);
        const label = `第${row}排第${col}格${hero ? ` · ${hero.name}${occupants.length > 1 ? `（此格有${occupants.length}个来源条目，需核对）` : ''}` : ' · 空格'}`;
        cell.title = label; cell.setAttribute('aria-label', label);
        if (unit) {
          cell.type = 'button'; cell.dataset.heroId = String(unit.hero_id);
          const url = iconUrl(hero.icon); if (url) { const image = document.createElement('img'); image.src = url; image.alt = ''; image.loading = 'lazy'; image.addEventListener('error', () => { cell.replaceChildren(el('span', '', hero.name.slice(0, 1))); }, { once: true }); cell.append(image); }
          else cell.append(el('span', '', hero.name.slice(0, 1)));
        } else cell.append(el('span', '', '·'));
        line.append(cell);
      }
      stage.append(line);
    }
    const legend = el('div', 'board-legend'); [['', '核心 / 输出'], ['support', '配套单位'], ['pet', '召唤物']].forEach(([kind, label]) => { const entry = el('span'); entry.append(el('i', `legend-mark ${kind}`), document.createTextNode(label)); legend.append(entry); }); stage.append(legend); return stage;
  }

  function phasePanel(comp) {
    const section = panel('过渡与成型棋盘', 'BUILD THROUGH THE GAME');
    const phases = arr(comp.phases);
    if (!phases.length) { section.append(el('p', 'empty-note', '来源没有提供可核验的过渡棋盘，不能从终局阵容反推一条固定前期路线。')); return section; }
    const phase = phases.find((entry) => String(entry.id) === state.phaseId) ?? phases[0]; state.phaseId = String(phase.id);
    const tabs = el('div', 'phase-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', '选择过渡阶段');
    phases.forEach((entry) => { const button = el('button', entry.id === phase.id ? 'selected' : '', entry.label); button.type = 'button'; button.dataset.phaseId = String(entry.id); button.setAttribute('aria-pressed', String(entry.id === phase.id)); tabs.append(button); }); section.append(tabs);
    const populationLabel = phase.board_status === 'source_subset'
      ? (phase.source_population ? `来源图 ${phase.source_population} 人口 · 部分体系牌` : '部分体系牌')
      : phase.board_status === 'source_invalid_population'
        ? `来源人口标注待核验${phase.actual_unit_count ? ` · 可见 ${phase.actual_unit_count} 个棋子` : ''}`
        : phase.board_status === 'source_partial_population'
          ? `来源 ${phase.population ?? '?'} 人口图 · 实列 ${phase.actual_unit_count ?? '?'} 个普通单位`
          : phase.board_status === 'core_only' ? '目标核心 · 非当前棋盘'
        : phase.population ? `来源标注 ${phase.population} 人口` : '人口依局面';
    const heading = el('div', 'board-phase-heading'); heading.append(el('h4', '', phase.label), el('span', '', populationLabel)); section.append(heading);
    section.append(evidence(phase.provenance, '来源棋盘 / 说明', '条件性阶段参考'));
    if (phase.board_status === 'core_only') section.append(el('p', 'callout', '目标核心 · 需要先解锁或满足卡片兑现条件。这不是当前棋盘，也不确认该核心在本阶段已经可购买。'));
    const units = arr(phase.board); const hasCoordinates = phase.board_status !== 'core_only' && units.length > 0 && units.some(validCell);
    if (hasCoordinates) section.append(renderBoard(units.filter(validCell), comp));
    if (units.length) {
      const list = el('div', 'unit-row'); units.forEach((unit) => list.append(heroCard(unit,
        phase.board_status === 'core_only' ? '目标核心 · 条件未确认'
          : unit.is_pet || unit.type === 'pet' ? '召唤物'
            : phase.board_status === 'source_subset' ? '候选体系牌'
              : arr(comp.carry_ids).map(String).includes(String(unit.hero_id)) ? '输出核心' : '体系单位'))); section.append(list);
    } else section.append(el('p', 'empty-note', '此阶段没有提供具体棋盘名单，按下方条件处理来牌。'));
    if (phase.focus) section.append(el('p', 'phase-notes', phase.focus));
    const actions = bullets(phase.actions); if (actions) section.append(actions);
    const conditions = bullets(phase.conditions); if (conditions) section.append(conditions);
    if (phase.board_status === 'source_subset') section.append(el('p', 'callout', '这是来源棋盘中的部分体系牌，不能直接当作完整过渡板。其他位置按当前强度和羁绊补齐。'));
    else if (phase.board_status === 'source_invalid_population') section.append(el('p', 'callout', '来源棋盘的可见英雄数量与人口标注不一致。保留原始名单供审视，不能直接照搬为可执行过渡板。'));
    else if (phase.board_status === 'source_partial_population') section.append(el('p', 'callout', '来源图没有填满其人口标签。未指定的位置保持未知，不表示实战应空置这些位置。'));
    else if (phase.board_status === 'not_provided') section.append(el('p', 'phase-footnote', '来源未提供完整过渡棋盘；当前阶段文字属于条件性参考。'));
    const validation = bullets(phase.validation_notes); if (validation) section.append(validation);
    section.append(el('p', 'phase-footnote', '棋子与召唤物可能同时出现在棋盘上。站位来自示例时仍需按对手切入、控制与范围伤害调整。'));
    return section;
  }

  function planPanel(comp) {
    const section = panel('什么时候 D / 升级 / 停手', 'ECONOMY & ROLL'); const plan = comp.roll_plan ?? {};
    if (plan.style) section.append(el('p', 'section-note', planStyle(plan.style))); section.append(evidence(plan.provenance, '来源运营说明', '条件性运营参考'));
    const groups = [['01', '行动条件', plan.actions], ['02', '停手条件', plan.stop_conditions], ['03', '转型与退出条件', plan.pivot_conditions]];
    groups.forEach(([number, title, values]) => { const card = el('article', 'operation-card'); const heading = el('h4'); heading.append(el('span', 'operation-number', number), document.createTextNode(title)); card.append(heading); const list = bullets(values); if (list) card.append(list); else card.append(el('p', '', '来源没有提供明确条件，暂不编造固定回合或金币阈值。')); section.append(card); });
    return section;
  }

  function corePanel(comp) {
    const section = panel('核心牌与挂件分工', 'TEAM ROLES'); const grid = el('div', 'comp-core-grid');
    const groups = [['核心体系 / 输出', [...new Set([...arr(comp.carry_ids), ...arr(comp.core_ids)])], '核心体系'], ['前排与功能补强', [...new Set([...arr(comp.frontline_ids), ...arr(comp.utility_ids), ...arr(comp.flex_ids)])].filter((id) => !arr(comp.core_ids).map(String).includes(String(id)) && !arr(comp.carry_ids).map(String).includes(String(id))), '承伤 / 功能 / 可换位']];
    groups.forEach(([title, ids, role]) => { const column = el('div'); column.append(el('h4', 'role-heading', title)); if (ids.length) column.append(heroGrid(ids, role)); else column.append(el('p', 'empty-note', '来源未明确列出此类分工。')); grid.append(column); }); section.append(grid);
    if (arr(comp.three_star_ids).length) section.append(el('p', 'support-note', `追三星目标：${heroNames(comp.three_star_ids)}。是否继续追需结合数量、同行和血量。`));
    const note = bullets(comp.notes); if (note) section.append(note); return section;
  }

  function equipmentPanel(comp) {
    const section = panel('装备分配', 'WHO HOLDS WHAT');
    arr(comp.equipment).forEach((entry) => {
      if (!arr(entry.item_ids).length) return;
      const hero = heroRecord(entry.hero_id); const block = el('article', 'equipment-group'); const heading = el('div', 'equipment-owner'); heading.append(icon(hero), el('strong', '', hero.name)); block.append(heading);
      const row = el('div', 'item-row'); entry.item_ids.forEach((id) => row.append(itemButton(id))); block.append(row);
      if (entry.role || entry.reason) block.append(el('p', 'support-note', [entry.role, entry.reason].filter(Boolean).join(' · '))); section.append(block);
    });
    if (section.childNodes.length === 1) section.append(el('p', 'empty-note', '来源未明确给出装备归属，暂不把通用出装强配给某个单位。'));
    return section;
  }

  function replacementsPanel(comp) {
    const section = panel('替代与补强', 'FLEX YOUR BOARD');
    arr(comp.replacements).forEach((entry) => {
      const block = el('article', 'substitution'); block.append(el('h4', '', `${heroRecord(entry.from_id).name}的替换候选`));
      if (arr(entry.to_ids).length) block.append(heroGrid(entry.to_ids));
      if (entry.reason) block.append(el('p', '', entry.reason)); section.append(block);
    });
    if (section.childNodes.length === 1) section.append(el('p', 'empty-note', '当前没有可核验的替换关系。相同职业不等于可以直接替换，还需检查费用、装备和羁绊断点。'));
    return section;
  }

  function renderComp(comp) {
    const section = el('section', 'comp-section'); section.id = 'selected-comp'; section.tabIndex = -1;
    const header = el('header', 'comp-header'); header.append(el('p', 'eyebrow', 'COMPOSITION / GAME PLAN'), el('h2', '', comp.name));
    const meta = el('div', 'comp-heading-meta'); meta.append(evidence(comp.kind, '官方收录阵容模板', '大橘卡组条件构筑'));
    if (comp.source_status === 'provisional_recipe') meta.append(el('span', 'evidence-tag conditional', '机制组合参考 · 配方来源待核验'));
    header.append(meta);
    if (comp.source_status === 'provisional_recipe') header.append(el('p', 'callout', '这组配方的发布来源尚未完成核验；当前仅作为机制组合参考，不作为已核实的完整配方。'));
    if (comp.summary) header.append(el('p', '', comp.summary));
    const tags = el('div', 'tag-row'); arr(comp.trait_keys).forEach((key) => {
      const trait = state.traits.get(key); if (!trait) return;
      const relation = arr(comp.trait_links).find((link) => link.key === key);
      const full = relation?.full_breakpoint ?? relation?.active_breakpoint;
      const required = Number(relation?.required_emblems_for_full) || 0;
      const conditionalForms = relation?.status === 'conditional' && arr(relation.conditional_form_ids).length > 0;
      let suffix = required > 0 ? ` · ${full ?? ''}档需纹章${conditionalForms ? '与指定形态' : ''}`
        : conditionalForms ? ` · ${full ?? ''}档需指定形态`
          : relation?.status === 'conditional' ? ` · ${full ?? ''}档有额外条件` : full ? ` · 模板${full}档` : '';
      if (arr(relation?.requires_card_ids).length) suffix = required > 0 || conditionalForms
        ? `${suffix}，并需${cardNames(relation.requires_card_ids)}实际触发`
        : ` · ${full ?? ''}档需${cardNames(relation.requires_card_ids)}实际触发`;
      const button = el('button', 'trait-reference', `${kindName(trait.kind)} · ${trait.name}${suffix}`); button.type = 'button'; button.dataset.traitKey = key;
      if (relation?.note) button.title = relation.note; tags.append(button);
    }); header.append(tags);
    arr(comp.trait_links).filter((relation) => arr(relation.requires_card_ids).length && relation.note).forEach((relation) => header.append(el('p', 'callout', relation.note)));
    const source = sourceLine(comp.source); if (source) header.append(source); section.append(header);
    const layout = el('div', 'operation-layout'); const main = el('div', 'operation-main'); const side = el('div', 'operation-sidebar');
    main.append(corePanel(comp), phasePanel(comp), planPanel(comp), replacementsPanel(comp));
    side.append(equipmentPanel(comp));
    const positioning = panel('站位与对位调整', 'POSITIONING');
    if (arr(comp.positioning?.board).some(validCell)) positioning.append(renderBoard(comp.positioning.board.filter(validCell), comp));
    if (comp.positioning?.summary) positioning.append(el('p', 'phase-notes', comp.positioning.summary));
    const notes = bullets(comp.positioning?.notes); if (notes) positioning.append(notes);
    if (!notes && !comp.positioning?.summary) positioning.append(el('p', 'empty-note', '来源未给出具体对位说明，不设固定最优格子。')); side.append(positioning);
    if (arr(comp.card_ids).length || arr(comp.augment_ids).length || arr(comp.published_card_names).length || arr(comp.unresolved_card_names).length) {
      const choices = panel('卡片与强化条件', 'MODE CONDITIONS');
      if (arr(comp.published_card_names).length) choices.append(el('p', 'section-note', `来源配方卡名：${comp.published_card_names.join('、')}`));
      if (arr(comp.card_ids).length) {
        choices.append(el('p', 'section-note', `已匹配的时间卡片：${[...new Set(arr(comp.card_ids).map((id) => state.data.modes[state.mode].cards?.find((card) => String(card.id) === String(id))?.name ?? '来源卡名待核验'))].join('、')}`));
        comp.card_ids.forEach((id) => {
          const card = arr(state.data.modes[state.mode].cards).find((entry) => String(entry.id) === String(id)); if (!card) return;
          const block = el('article', 'condition-card'); block.append(el('h4', '', card.name));
          if (arr(card.activation_rounds).length) block.append(el('p', '', `配置启用回合：${card.activation_rounds.join(' / ')}。启用不等于任务奖励已经到账。`));
          block.append(el('p', 'card-effect', card.description || '效果条件尚待核验，请核对来源卡面与本页运营说明。'));
          const conditions = bullets(card.trigger_conditions); if (conditions) block.append(conditions); choices.append(block);
        });
      }
      if (arr(comp.augment_ids).length) choices.append(el('p', 'section-note', `强化：${[...new Set(arr(comp.augment_ids).map((id) => state.data.modes[state.mode].augments?.find((augment) => String(augment.id) === String(id))?.name ?? '来源强化名称待核验'))].join('、')}`));
      choices.append(el('p', 'support-note', '卡片与强化的持有、等级和触发条件需成立；不同模式的运营不能直接套用。')); side.append(choices);
      const unresolved = arr(comp.unresolved_card_names).length ? comp.unresolved_card_names : comp.unresolved_cards;
      if (arr(unresolved).length) choices.append(el('p', 'callout', `仍待核验的卡片：${unresolved.map((card) => typeof card === 'object' ? card.name ?? card.title ?? card.reason ?? '卡片后缀或等级' : card).join('、')}。这些条目不能视为已确认持有或已生效。`));
      if (comp.portal_claim) choices.append(el('p', 'dialog-note', `来源标注的适用传送门：${comp.portal_claim}；当前可用性仍需核对实际玩法。`));
    }
    layout.append(main, side); section.append(layout); return section;
  }

  function renderDetail() {
    if (state.index === 'comps') {
      const comp = state.comps.get(state.compId) ?? state.comps.values().next().value;
      if (comp) { state.compId = String(comp.id); $('strategy-detail').replaceChildren(renderComp(comp)); document.title = `${comp.name} · 羁绊与运营 · 弈策`; }
      else $('strategy-detail').replaceChildren(el('p', 'empty-note', '该模式暂无来源明确的阵容模板。'));
      return;
    }
    const trait = state.traits.get(state.traitKey);
    if (trait) { renderTraitDetail(trait); document.title = `${trait.name} · 羁绊与运营 · 弈策`; }
    else $('strategy-detail').replaceChildren(el('p', 'empty-note', '该模式暂无可显示的羁绊资料。'));
  }

  function writeHash() {
    const mode = encodeURIComponent(state.mode);
    const hash = state.index === 'comps' ? `#${mode}/comp/${encodeURIComponent(state.compId)}` : `#${mode}/trait/${encodeURIComponent(state.traitKey)}${state.compId ? `/comp/${encodeURIComponent(state.compId)}` : ''}`;
    history.replaceState(null, '', hash);
  }

  function readHash() {
    const parts = location.hash.slice(1).split('/').map((value) => { try { return decodeURIComponent(value); } catch { return ''; } });
    const [mode, type, id, extra, comp] = parts;
    setMode(state.data.modes[mode] ? mode : 'nature', { index: type === 'comp' ? 'comps' : 'traits', trait: type === 'trait' ? id : '', comp: type === 'comp' ? id : extra === 'comp' ? comp : '' });
  }

  function showUnit(id) {
    const hero = state.heroes.get(String(id)) ?? state.extraHeroes.get(String(id));
    if (!hero) return;
    const body = $('unit-dialog-body'); body.replaceChildren(); const heading = el('div', 'dialog-title'); heading.append(icon(hero));
    const copy = el('div'); const title = el('h2', '', hero.name); title.id = 'unit-dialog-title';
    const professions = arr(hero.traits).filter((trait) => trait.kind === 'class').map((trait) => trait.name);
    copy.append(title, el('small', '', hero.cost == null ? '来源棋盘的召唤物 / 特殊单位' : `${hero.cost}费 · ${professions.length ? `职业：${professions.join(' / ')}` : hero.profession_status === 'none' ? '无常规职业' : '职业待核验'}`)); heading.append(copy); body.append(heading);
    const traits = arr(hero.traits).map((trait) => `${kindName(trait.kind)} · ${trait.name}`).join(' / '); if (traits) body.append(el('p', 'dialog-description', traits));
    if (hero.skill?.description) body.append(el('p', 'dialog-description', hero.skill.description));
    if (hero.guide_available === false || hero.template_only_form || hero.availability === 'conditional_form') {
      body.append(el('p', 'callout', '这是来源模板引用的条件形态，不能按同名替换为其他羁绊形态。本形态装备参考见当前阵容，独立装备图鉴尚未收录。'));
    } else if (state.heroes.has(String(id))) {
      body.append(el('p', 'dialog-note', '该棋子的具体装备、神器、纹章与历史三件套统计可在装备图鉴中查看。'));
      const link = el('a', 'dialog-link', '查看这位棋子的装备图鉴 ↗'); link.href = guideUrl(hero.id); body.append(link);
    } else body.append(el('p', 'dialog-note', '这是来源棋盘中的召唤物或特殊单位。它不计入原生可购买棋子的名单，具体生成机制需要核对所属英雄或羁绊。'));
    if (!$('unit-dialog').open) $('unit-dialog').showModal();
  }

  function showItem(id) {
    const item = state.items.get(String(id)); if (!item) return;
    const body = $('unit-dialog-body'); body.replaceChildren(); const heading = el('div', 'dialog-title'); heading.append(icon(item, 'item-icon'));
    const copy = el('div'); const title = el('h2', '', item.name); title.id = 'unit-dialog-title'; copy.append(title, el('small', '', item.type ?? '装备')); heading.append(copy); body.append(heading);
    if (item.base_stats) body.append(el('p', 'dialog-description', item.base_stats));
    body.append(el('p', 'dialog-description', item.description || '暂无完整效果说明，请核对实际客户端版本。'));
    if (arr(item.components).length) { body.append(el('p', 'dialog-note', '合成配方')); const row = el('div', 'item-row'); item.components.forEach((component) => row.append(itemButton(component))); body.append(row); }
    if (!$('unit-dialog').open) $('unit-dialog').showModal();
  }

  function initEvents() {
    $('guide-link').href = guideUrl();
    document.querySelectorAll('button[data-mode]').forEach((button) => button.addEventListener('click', () => { setMode(button.dataset.mode); writeHash(); }));
    document.querySelectorAll('[data-index]').forEach((button) => button.addEventListener('click', () => { state.index = button.dataset.index; renderDetail(); renderIndex(); writeHash(); }));
    $('strategy-search').addEventListener('input', renderIndex); $('trait-kind').addEventListener('change', renderIndex);
    $('reset-search').addEventListener('click', () => { $('strategy-search').value = ''; $('trait-kind').value = ''; renderIndex(); });
    document.addEventListener('click', (event) => {
      const target = event.target.closest('button'); if (!target) return;
      if (target.dataset.traitKey) { state.traitKey = target.dataset.traitKey; state.index = 'traits'; state.compId = ''; state.phaseId = ''; state.moreComps = false; renderDetail(); renderIndex(); writeHash(); return; }
      if (target.dataset.compId) {
        state.compId = target.dataset.compId; state.phaseId = ''; renderDetail(); renderIndex(); writeHash();
        if (!target.closest('#strategy-index')) requestAnimationFrame(() => { $('selected-comp')?.focus({ preventScroll: true }); $('selected-comp')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }); return;
      }
      if (target.dataset.phaseId) { state.phaseId = target.dataset.phaseId; renderDetail(); document.querySelector('.phase-tabs .selected')?.focus({ preventScroll: true }); return; }
      if (target.dataset.moreComps) { state.moreComps = !state.moreComps; renderDetail(); return; }
      if (target.dataset.itemId) { showItem(target.dataset.itemId); return; }
      if (target.dataset.heroId) showUnit(target.dataset.heroId);
    });
    $('close-unit').addEventListener('click', () => $('unit-dialog').close());
    $('unit-dialog').addEventListener('click', (event) => { if (event.target !== $('unit-dialog')) return; const rect = $('unit-dialog').getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $('unit-dialog').close(); });
    document.addEventListener('keydown', (event) => { if (event.key === '/' && !event.ctrlKey && !event.metaKey && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName) && !$('unit-dialog').open) { event.preventDefault(); $('strategy-search').focus(); } });
    window.addEventListener('hashchange', readHash);
  }

  async function start() {
    initEvents();
    try {
      const response = await fetch(new URL('./strategy-data.json', location.href), { cache: 'no-cache' }); if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json(); if (!state.data?.modes?.nature || !state.data?.modes?.orange) throw new Error('资料结构不完整');
      const meta = state.data.meta ?? {}; $('version-badge').textContent = `${meta.rules_patch ?? '18.6'} · 历史规则资料`;
      $('version-notice').textContent = meta.notice || '当前为历史规则资料。官方收录阵容与条件性推导分别展示，请核对客户端版本。';
      $('load-message').hidden = true; $('strategy-workspace').hidden = false; readHash(); writeHash();
    } catch (error) {
      const message = $('load-message'); message.className = 'load-message error'; message.replaceChildren(el('strong', '', '羁绊与阵容资料暂时无法打开'), el('span', '', '请检查网络后重试。刚发布的资料可能仍在同步。'));
      const retry = el('button', 'text-button', '重新载入'); retry.type = 'button'; retry.addEventListener('click', () => location.reload()); message.append(retry); $('version-badge').textContent = '资料未载入'; console.error('Strategy data load failed:', error);
    }
  }
  start();
})();
