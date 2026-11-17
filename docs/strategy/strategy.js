(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const arr = (value) => Array.isArray(value) ? value : [];
  const state = { data: null, mode: 'nature', index: 'traits', traitKey: '', compId: '', phaseId: '', moreComps: false, heroes: new Map(), extraHeroes: new Map(), traits: new Map(), comps: new Map(), items: new Map() };
  const costColors = ['#8b9ba6', '#8b9ba6', '#78af82', '#71a6c9', '#b692ce', '#d8ae68', '#e68b7d', '#e68b7d'];
  const kindName = (kind) => kind === 'class' ? '职业' : kind === 'origin' ? '特质' : '羁绊';
  const traitKey = (trait) => trait.key || `${trait.kind}:${trait.id}`;
  const isSource = (kind) => ['source', 'official_lineup', 'official_published_author_lineup', 'human_reviewed_author_image', 'human_reviewed_source_image'].includes(kind);
  const compSourceLabel = (comp) => comp.kind === 'official_published_author_lineup' ? '官方号收录作者条件实例' : comp.kind === 'official_lineup' ? '官方收录阵容模板' : '卡组条件构筑';
  const planStyle = (value) => ({ quality_reroll: '关键回合搜质量', slow_roll: '留经济慢搜 / 低费追星', card_conditional: '卡片兑现与核心解锁', upgrade_and_stabilize: '提人口后稳质量' }[value] ?? (/^[a-z_]+$/i.test(String(value)) ? '运营条件待核验' : value ?? '运营条件待补充'));
  const textOf = (value) => typeof value === 'object' && value !== null ? value.text ?? value.description ?? value.action ?? value.reason ?? '' : value;

  function el(tag, className = '', text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = readableText(String(text));
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

  function heroDisplayName(hero) {
    if (!hero?.template_only_form && hero?.availability !== 'conditional_form') return hero?.name ?? '未知单位';
    const selected = state.traits.get(state.traitKey);
    const traits = arr(hero.traits).filter((trait) => trait.verified !== false && trait.name !== '大元素使');
    const selectedName = selected && traits.some((trait) => traitKey(trait) === traitKey(selected)) ? selected.name : '';
    const prefix = selectedName || traits.map((trait) => trait.name).join(' / ');
    return prefix ? `${prefix}·${hero.name}` : `${hero.name}（条件形态）`;
  }

  function readableText(value) {
    if (!/形态|同名/.test(value) || !/\d{5}/.test(value)) return value;
    let result = value;
    state.heroes.forEach((hero) => {
      if (!hero.template_only_form && hero.availability !== 'conditional_form') return;
      const id = String(hero.id); const name = heroDisplayName(hero);
      result = result.replace(new RegExp(`(?:精确形态|精确ID|形态|ID)[：:\\s]*${id}`, 'g'), `指定${name}形态`);
      result = result.replace(new RegExp(`(?<=[：:、，\\s])${id}(?=[、，。\\s]|$)`, 'g'), `${name}形态`);
      result = result.replaceAll(`${name}形态（${hero.name}）`, `${name}形态`);
    }); return result;
  }

  function heroCard(value, role = '') {
    const hero = heroRecord(value); const button = el('button', 'unit-card'); button.type = 'button'; button.dataset.heroId = hero.id;
    if (/目标核心|候选体系/.test(role)) button.classList.add('unverified');
    button.style.setProperty('--cost-color', costColors[Math.max(0, Math.min(7, Number(hero.cost) || 0))]);
    button.append(icon(hero)); const copy = el('span', 'unit-copy'); copy.append(el('strong', '', heroDisplayName(hero)));
    const classes = arr(hero.traits).filter((trait) => trait.kind === 'class').map((trait) => trait.name);
    copy.append(el('small', 'cost', `${hero.cost == null ? '特殊单位' : `${hero.cost}费`}${classes.length ? ` · ${classes.join(' / ')}` : ''}`));
    if (role) copy.append(el('small', 'unit-role', role));
    if (typeof value === 'object' && value !== null && Number.isFinite(Number(value.slots_consumed))) {
      if (Number(value.slots_consumed) > 1) copy.append(el('small', 'slot-cost', `占 ${value.slots_consumed} 人口`));
      else if (Number(value.slots_consumed) === 0 && value.slots_consumed != null) copy.append(el('small', 'slot-cost', '本图不占场上人口'));
    }
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
    if (!state.data?.modes?.[mode]) return;
    state.mode = mode; state.phaseId = ''; state.moreComps = false; state.extraHeroes = new Map();
    const data = state.data.modes[mode];
    state.heroes = new Map(arr(data.heroes).map((hero) => [String(hero.id), hero]));
    state.items = new Map(arr(data.items).map((item) => [String(item.id), item]));
    state.traits = new Map(arr(data.traits).map((trait) => [traitKey(trait), trait]));
    state.comps = new Map(arr(data.comps).map((comp) => [String(comp.id), comp]));
    state.traitKey = state.traits.has(selected.trait) ? selected.trait : state.traits.keys().next().value ?? '';
    state.compId = state.comps.has(String(selected.comp)) ? String(selected.comp) : '';
    state.index = selected.index === 'comps' ? 'comps' : 'traits';
    $('strategy-search').value = ''; $('trait-kind').value = ''; $('coverage-filter').value = ''; $('prismatic-only').checked = false;
    document.body.dataset.mode = mode;
    document.querySelectorAll('button[data-mode]').forEach((button) => { const active = button.dataset.mode === mode; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
    $('guide-link').href = guideUrl();
    renderCoverageSummary(); renderDetail(); renderIndex();
  }

  function heroNames(ids) { return arr(ids).map((id) => heroDisplayName(heroRecord(id))).join(' '); }

  function cardNames(ids) {
    const cards = arr(state.data.modes[state.mode].cards);
    return arr(ids).map((id) => cards.find((card) => String(card.id) === String(id))?.name ?? '名称待核验的来源卡片').join('、');
  }

  function compText(comp) {
    const unitIds = [...arr(comp.core_ids), ...arr(comp.carry_ids), ...arr(comp.frontline_ids), ...arr(comp.flex_ids), ...arr(comp.phases).flatMap((phase) => arr(phase.board).map((unit) => unit.hero_id))];
    return [comp.name, comp.summary, heroNames(unitIds), ...unitIds.map((id) => state.heroes.get(String(id))?.form_note ?? ''), ...arr(comp.trait_keys).map((key) => state.traits.get(key)?.name ?? ''), cardNames(comp.card_ids), ...arr(comp.published_card_names), ...arr(comp.unresolved_card_names)].join(' ').toLocaleLowerCase();
  }

  function compCoverage(comp) {
    if (comp.kind === 'orange_recipe') return 'core';
    const late = arr(comp.phases).find((phase) => phase.id === 'late');
    return late?.board_status === 'source' ? 'full' : 'partial';
  }

  function prismaticTiers(trait) {
    return arr(trait.tiers).filter((tier) => tier.is_prismatic === true || Number(tier.style) === 4);
  }

  function traitCoverage(trait) {
    const values = linkedComps(trait);
    const full = values.filter((comp) => compCoverage(comp) === 'full').length;
    const partial = values.filter((comp) => compCoverage(comp) === 'partial').length;
    const core = values.filter((comp) => compCoverage(comp) === 'core').length;
    const mechanism = arr(trait.mechanism_comp_ids).length;
    return { full, partial, core, mechanism, kind: full ? 'full' : partial ? 'partial' : core ? 'core' : 'mechanism' };
  }

  function coverageLabel(value) {
    return { full: '完整终局图', partial: '不完整棋盘', core: '卡片核心路线', mechanism: '机制 / 计数参考' }[value] ?? '资料待核验';
  }

  function coverageCopy(trait) {
    const coverage = traitCoverage(trait); const pieces = [];
    if (coverage.full) pieces.push(`完整终局 ${coverage.full}`);
    if (coverage.partial) pieces.push(`不完整棋盘 ${coverage.partial}`);
    if (coverage.core) pieces.push(`核心路线 ${coverage.core}`);
    if (coverage.mechanism) pieces.push(`机制条件接入 ${coverage.mechanism}`);
    return pieces.length ? pieces.join(' · ') : '机制 / 计数参考 · 无已成档来源阵容';
  }

  function renderCoverageSummary() {
    const data = state.data.modes[state.mode]; const counts = { full: 0, partial: 0, core: 0 };
    arr(data.comps).forEach((comp) => { counts[compCoverage(comp)] += 1; });
    const mechanism = arr(data.traits).filter((trait) => traitCoverage(trait).kind === 'mechanism').length;
    const summary = $('coverage-summary'); summary.replaceChildren();
    [[counts.full, '份完整终局图'], [counts.partial, '份不完整棋盘'], [counts.core, '条卡片核心路线'], [mechanism, `/${arr(data.traits).length} 个羁绊无来源阵容`]].forEach(([count, label]) => {
      const value = el('span', 'coverage-metric'); value.append(el('strong', '', count), el('span', '', label)); summary.append(value);
    });
    summary.append(el('p', '', '完整终局仅指来源人数与人口标注一致，不代表过渡、运营或当前版本已完整验证。'));
    summary.hidden = false;
    const prismatic = arr(data.traits).filter((trait) => prismaticTiers(trait).length);
    $('capstone-entry').hidden = !prismatic.length; $('prismatic-toggle').hidden = !prismatic.length;
    $('capstone-summary').textContent = `${prismatic.length} 个羁绊有官方棱彩档位 · 查人口、条件形态、纹章与承载位的计数路线`;
  }

  function clearFilters() {
    $('strategy-search').value = ''; $('trait-kind').value = ''; $('coverage-filter').value = ''; $('prismatic-only').checked = false; renderIndex();
  }

  function jumpTo(id) {
    const target = $(id); if (!target) return;
    if (target.tagName === 'DETAILS') target.open = true;
    if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  function renderIndex() {
    const query = $('strategy-search').value.trim().toLocaleLowerCase(); const kind = $('trait-kind').value; const coverage = $('coverage-filter').value; const prismaticOnly = $('prismatic-only').checked;
    document.querySelectorAll('[data-index]').forEach((button) => { const active = button.dataset.index === state.index; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
    $('prismatic-toggle').hidden = state.index !== 'traits' || ![...state.traits.values()].some((trait) => prismaticTiers(trait).length);
    $('index-title').textContent = state.index === 'traits' ? '羁绊索引' : '阵容总览';
    const values = state.index === 'traits' ? [...state.traits.values()].filter((trait) => (!kind || trait.kind === kind) && (!coverage || traitCoverage(trait).kind === coverage) && (!prismaticOnly || prismaticTiers(trait).length)
      && (!query || [trait.name, trait.id, heroNames(trait.native_hero_ids), ...[...arr(trait.linked_comp_ids), ...arr(trait.mechanism_comp_ids)].map((id) => state.comps.get(String(id))).filter(Boolean).map(compText)].join(' ').toLocaleLowerCase().includes(query)))
      : [...state.comps.values()].filter((comp) => (!query || compText(comp).includes(query)) && (!coverage || compCoverage(comp) === coverage) && (!kind || arr(comp.trait_keys).some((key) => state.traits.get(key)?.kind === kind)) && (!prismaticOnly || arr(comp.trait_keys).some((key) => prismaticTiers(state.traits.get(key) ?? {}).length)));
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
        : `${compSourceLabel(value)} · ${planStyle(value.roll_plan?.style)}`;
      copy.append(el('small', '', subtitle));
      copy.append(el('span', `index-coverage ${isTrait ? traitCoverage(value).kind : compCoverage(value)}`, isTrait ? coverageCopy(value) : coverageLabel(compCoverage(value))));
      if (isTrait && prismaticTiers(value).length) copy.append(el('span', 'index-prismatic', `◈ 棱彩 ${prismaticTiers(value).map((tier) => tier.count).join(' / ')} 档`));
      button.append(copy, el('span', 'index-arrow', '↗')); list.append(button);
    });
    $('index-empty').hidden = values.length > 0; list.hidden = !values.length;
    const selectedId = state.index === 'traits' ? state.traitKey : state.compId;
    const selectedName = state.index === 'traits' ? state.traits.get(selectedId)?.name : state.comps.get(selectedId)?.name;
    const selectedVisible = values.some((value) => (state.index === 'traits' ? traitKey(value) : String(value.id)) === selectedId);
    const showNotice = Boolean(selectedName && !selectedVisible);
    $('selection-notice').hidden = !showNotice;
    if (showNotice) $('selection-notice-text').textContent = values.length
      ? `下方仍在查看「${selectedName}」，它不在当前筛选结果中。`
      : `筛选没有匹配结果。下方保留的是「${selectedName}」资料，并不是搜索结果。`;
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
    const coverage = traitCoverage(trait);
    header.append(el('p', `trait-coverage ${coverage.kind}`, `当前收录：${coverageCopy(trait)}${coverage.kind === 'core' ? '。核心路线不等于完整终局棋盘。' : coverage.kind === 'mechanism' ? '。当前没有本羁绊已成档的来源模板，以下是机制、计数与条件接入参考。' : '。来源图的完整度与过渡/运营完整度分别判断。'}`));
    if (arr(trait.capstone_routes).length || prismaticTiers(trait).length) { const button = el('button', 'capstone-jump', '◈ 查看高阶 / 棱彩计数路线 ↓'); button.type = 'button'; button.dataset.scrollTarget = 'trait-capstone'; header.append(button); }
    if (trait.strategy_type === 'unique') header.append(el('p', 'trait-use', '独有羁绊主要描述该棋子的专属机制。它不自动构成一套可从前期起手的阵容。'));
    const thresholds = arr(trait.breakpoints).length ? trait.breakpoints : arr(trait.tiers).map((tier) => tier.count);
    if (thresholds.length) { const row = el('div', 'breakpoint-row'); thresholds.forEach((count) => { const isPrismatic = prismaticTiers(trait).some((tier) => Number(tier.count) === Number(count)); const pill = el('span', `breakpoint-pill${isPrismatic ? ' prismatic' : ''}`); pill.append(el('strong', '', count), document.createTextNode(isPrismatic ? ' 棱彩档位' : ' 激活档位')); row.append(pill); }); header.append(row); }
    const source = sourceLine(trait.source); if (source) header.append(source); return header;
  }

  function linkedComps(trait) {
    return arr(trait.linked_comp_ids).map((id) => state.comps.get(String(id))).filter(Boolean);
  }

  function mechanismPanel(trait, folded = false) {
    const plan = trait.mechanism_plan; if (!plan) return null;
    const section = folded ? el('details', 'panel mechanism-panel') : panel('机制阶段打法', 'CONDITIONAL REFERENCE');
    section.id = 'trait-mechanism';
    if (folded) section.append(el('summary', '', '机制阶段打法 · 条件参考'));
    section.append(el('p', 'section-note', plan.summary || '按来源机制检查接入条件。'));
    section.append(el('p', 'callout', plan.status === 'unresolved' ? '机制尚待核验，不能据此生成固定运营路线。' : '以下为官方规则的条件性解读，不是完整实战棋盘，也不是已验证的最优运营。'));
    if (plan.status !== 'unresolved') [['early', '前期接入'], ['mid', '中期检查'], ['late', '后期补强']].forEach(([key, title]) => {
      const phase = plan[key]; if (!phase) return;
      const block = el('details', 'mechanism-phase'); block.open = key === 'early';
      block.append(el('summary', '', `${title} · ${arr(phase.candidate_ids).length} 位候选`));
      const actions = bullets(phase.actions); if (actions) block.append(actions);
      const conditions = bullets(phase.conditions); if (conditions) block.append(conditions);
      if (arr(phase.candidate_ids).length) block.append(heroGrid(phase.candidate_ids, '候选体系牌 · 条件参考'));
      if (arr(phase.partial_combinations).length) {
        const combinations = el('div', 'partial-combinations'); combinations.append(el('p', 'support-note', '局部组合参考，不是满人口棋盘：'));
        phase.partial_combinations.forEach((combination) => {
          const item = el('article', 'substitution');
          if (combination.label || combination.title || combination.name) item.append(el('h4', '', combination.label ?? combination.title ?? combination.name));
          const ids = combination.hero_ids ?? combination.unit_ids ?? []; if (arr(ids).length) item.append(heroGrid(ids, '局部组合'));
          const explanation = combination.reason ?? combination.description ?? combination.note; if (explanation) item.append(el('p', '', explanation));
          if (combination.native_count != null) item.append(el('p', '', `原生计数 ${combination.native_count}${combination.active_breakpoint ? ` · 达到 ${combination.active_breakpoint} 档` : ' · 未达到起始档'}`));
          const conditions = bullets(combination.conditions); if (conditions) item.append(conditions);
          if (item.childNodes.length) combinations.append(item);
        }); block.append(combinations);
      }
      section.append(block);
    });
    if (arr(plan.unlock_hero_ids).length) {
      section.append(el('h4', 'role-heading', '需核对的解锁目标'), el('p', 'support-note', '点击查看普通任务记录。时间卡直接解锁与普通任务是不同路径，不能把目标当作当前已可购买。'), heroGrid(plan.unlock_hero_ids, '核对解锁条件'));
    }
    [['停手与退出条件', plan.stop_conditions], ['站位取舍', plan.position_notes]].forEach(([title, values]) => { const list = bullets(values); if (list) section.append(el('h4', 'role-heading', title), list); });
    const source = sourceLine(plan.sources); if (source) section.append(source); return section;
  }

  function capstonePanel(trait) {
    const preferred = (route) => arr(route.conditional_form_ids).length > 0 && Number(route.population_required) <= 10;
    const routes = arr(trait.capstone_routes).slice().sort((a, b) => Number(preferred(b)) - Number(preferred(a)) || Number(a.target_count) - Number(b.target_count) || Number(a.population_required) - Number(b.population_required) || Number(a.emblem_count) - Number(b.emblem_count));
    const hasPreferred = routes.some(preferred);
    if (!routes.length && !prismaticTiers(trait).length) return null;
    const section = el('details', 'panel capstone-panel'); section.id = 'trait-capstone'; section.open = !state.compId;
    section.append(el('summary', '', `◈ 高阶 / 棱彩路线 · ${routes.length} 条计数方案`));
    section.append(el('p', 'section-note', '优先展示10人口内的指定形态路线，其他方案可展开对照。这里是规则计数，不是胜率排序或已验证的最优阵容。'));
    if (!routes.length) section.append(el('p', 'empty-note', '官方资料中存在棱彩档位，但当前尚未收录可核验的达成路线；不把原生池自动补成满人口棋盘。'));
    routes.forEach((route) => {
      const collapsed = Number(route.population_required) > 10 || hasPreferred && !preferred(route);
      const card = el(collapsed ? 'details' : 'article', `capstone-route${route.is_prismatic ? ' prismatic' : ''}${collapsed ? ' alternative-route' : ''}`);
      if (collapsed) card.append(el('summary', '', `${route.label || `${route.target_count} ${trait.name}`} · ${route.population_required}人口 / ${route.emblem_count}纹章${Number(route.population_required) > 10 ? ' · 需额外人口来源' : ' · 备选'}`));
      const heading = el('div', 'capstone-route-heading'); heading.append(el('h3', '', route.label || `${route.target_count} ${trait.name}`), el('span', 'evidence-tag conditional', route.is_prismatic ? '棱彩档位 · 条件计数' : '高阶断点 · 条件计数')); card.append(heading);
      if (Number(route.population_required) > 10) card.append(el('p', 'route-unavailable', `需要 ${route.population_required} 人口，额外人口来源尚未满足时不可执行；不能作为普通升到10人口的路线。`));
      const metrics = el('div', 'capstone-metrics');
      [[route.population_required, '所需人口'], [route.native_count, '原生羁绊计数'], [route.emblem_count, '额外纹章计数'], [route.total_count, '总计数']].forEach(([value, label]) => { const cell = el('span'); cell.append(el('strong', '', value ?? '待核验'), el('small', '', label)); metrics.append(cell); }); card.append(metrics);
      if (Number(route.emblem_count) > 0 && arr(route.emblem_item_ids).length) {
        card.append(el('h4', 'role-heading', `纹章需求 · ${route.emblem_count} 枚（点击查看效果与合成）`));
        const row = el('div', 'item-row'); route.emblem_item_ids.forEach((id) => row.append(itemButton(id))); card.append(row);
      }
      const details = el('details', 'capstone-route-detail'); details.append(el('summary', '', '查看体系牌与计数明细'));
      const forms = new Set(arr(route.conditional_form_ids).map(String));
      const nativeIds = arr(route.hero_ids).filter((id) => !forms.has(String(id)));
      if (forms.size) card.append(el('p', 'capstone-form-check', `需指定${[...forms].map((id) => heroDisplayName(heroRecord(id))).join('、')}形态；按下方明细核对额外计数。`));
      const unitWithSlots = (id) => ({ hero_id: id, slots_consumed: arr(route.counting_evidence).find((entry) => String(entry.hero_id) === String(id))?.population_cost });
      if (nativeIds.length) details.append(el('h4', 'role-heading', `${nativeIds.length} 位普通原生棋子`), heroGrid(nativeIds.map(unitWithSlots), '原生计数单位'));
      if (forms.size) { details.append(el('h4', 'role-heading', '指定条件形态 · 不能用同名基础形态替代'), heroGrid([...forms].map(unitWithSlots), '指定形态 · 核对额外计数')); }
      const evidenceList = el('ul', 'detail-bullets'); arr(route.counting_evidence).forEach((entry) => evidenceList.append(el('li', '', `${heroDisplayName(heroRecord(entry.hero_id))}：贡献 ${entry.contribution} 个羁绊计数${entry.population_cost != null ? `，占 ${entry.population_cost} 人口` : ''}。${entry.reason || ''}`))); if (evidenceList.childNodes.length) details.append(evidenceList);
      if (Number(route.emblem_holder_slots) > 0) {
        details.append(el('h4', 'role-heading', '非原生纹章承载位 · 人选仍待选择'));
        const holders = el('div', 'emblem-holder-slots'); for (let index = 0; index < Number(route.emblem_holder_slots); index += 1) holders.append(el('span', '', `◇ 1人口非原生承载位 ${index + 1}`)); details.append(holders);
        details.append(el('p', 'support-note', '承载位人口预算按每位1人口计算；若选择占2人口的单位，需要重新核对总人口。'));
      }
      if (Number(route.emblem_count) > 0 && route.emblem_holder_requirement) details.append(el('p', 'adoption-check', route.emblem_holder_requirement));
      if (route.named_units_population != null) details.append(el('p', 'support-note', `已指定单位占 ${route.named_units_population} 人口；另需 ${route.emblem_holder_slots ?? 0} 个非原生纹章承载位。这是该方案所需的最低人口预算，继续升级获得的新人口可以另作补强。`));
      const conditions = bullets(route.conditions); if (conditions) details.append(conditions);
      const source = sourceLine(route.source); if (source) details.append(source); card.append(details); section.append(card);
    }); return section;
  }

  function compPreview(comp) {
    const button = el('button', `comp-preview${state.compId === String(comp.id) ? ' selected' : ''}`); button.type = 'button'; button.dataset.compId = String(comp.id);
    const title = el('div', 'comp-preview-title'); title.append(el('h4', '', comp.name), evidence(comp.kind, compSourceLabel(comp), '条件卡组构筑'));
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
    const capstone = capstonePanel(trait); if (capstone) root.append(capstone);
    const grid = el('div', 'detail-grid'); const main = el('div', 'main-column'); const side = el('div', 'side-column');
    const natives = el('details', 'panel native-panel');
    natives.append(el('summary', '', `原生体系牌与阶段池 · ${arr(trait.native_hero_ids).length} 位可选棋子`));
    natives.append(el('p', 'section-note', '这些棋子原生拥有此职业或特质。纹章外援与召唤物不混入原生名单。'));
    if (arr(trait.native_hero_ids).length) natives.append(heroGrid(trait.native_hero_ids)); else natives.append(el('p', 'empty-note', '当前官方快照未解析到原生棋子，暂不猜测。'));
    if (trait.stage_pools && Object.values(trait.stage_pools).some((pool) => arr(pool).length)) {
      const pools = el('details', 'pool-details'); pools.append(el('summary', '', '按阶段看可选池 · 费用参考'));
      pools.append(el('p', 'section-note', '这是按费用划分的来牌候选池，不是已验证的过渡棋盘，也不表示必须购买所有棋子。'));
      [['early', '前期可选池'], ['mid', '中期可选池'], ['late', '后期补强池']].forEach(([key, title]) => {
        if (!arr(trait.stage_pools[key]).length) return; pools.append(el('h4', 'role-heading', title), heroGrid(trait.stage_pools[key]));
      }); natives.append(pools);
    }
    const related = panel('关联阵容与运营路线', 'FOLLOW THE PLAN'); related.id = 'trait-routes'; const comps = linkedComps(trait);
    if (!comps.length) related.append(el('p', 'empty-note', trait.strategy_type === 'unique' ? '当前没有独立成套模板。先将这张独有棋子作为已有阵容的条件补强，核对费用、解锁要求和上场价值。' : '当前没有来源明确的完整阵容模板；原生名单与激活断点仍可作为搭配依据。'));
    else {
      related.append(el('p', 'section-note', '选择一套阵容，在本页展开核心牌、过渡棋盘、搜牌条件、装备与站位。'));
      const list = el('div', 'comp-list'); const shown = state.moreComps ? comps : comps.slice(0, 6); shown.forEach((comp) => list.append(compPreview(comp))); related.append(list);
      if (comps.length > 6) { const toggle = el('button', 'text-button', state.moreComps ? '收起其余阵容 ↑' : `展开其余 ${comps.length - 6} 套阵容 ↓`); toggle.type = 'button'; toggle.dataset.moreComps = 'true'; toggle.style.marginTop = '13px'; related.append(toggle); }
    }
    const mechanic = mechanismPanel(trait, comps.length > 0);
    if (mechanic && !comps.length) main.append(mechanic);
    main.append(related);
    if (mechanic && comps.length) main.append(mechanic);
    main.append(natives);
    const tiers = panel('关键断点', 'TRAIT BREAKPOINTS'); const tierList = el('div', 'breakpoint-details');
    arr(trait.tiers).forEach((tier) => { const block = el('article', 'breakpoint-detail'); block.append(el('h4', '', `${tier.count} ${trait.name}`), el('p', '', tier.effect || '具体效果尚未收录。')); tierList.append(block); });
    if (tierList.childNodes.length) tiers.append(tierList); else tiers.append(el('p', 'empty-note', '暂无完整档位效果，请以实际客户端为准。')); side.append(tiers);
    const notes = panel('组队条件与取舍', 'WHEN IT FITS');
    if (trait.description && trait.description !== trait.summary) notes.append(el('p', 'section-note', trait.description));
    const play = bullets(trait.play_notes); const conditions = bullets(trait.conditions); if (play) notes.append(play); if (conditions) notes.append(conditions);
    if (!play && !conditions && !trait.description) notes.append(el('p', 'empty-note', '没有足够资料支持固定运营路线。')); side.append(notes);
    const relatedOnly = arr(trait.related_comp_ids).filter((id) => !arr(trait.linked_comp_ids).map(String).includes(String(id))).map((id) => state.comps.get(String(id))).filter(Boolean);
    const mechanismComps = arr(trait.mechanism_comp_ids).filter((id) => ![...arr(trait.linked_comp_ids), ...arr(trait.related_comp_ids)].map(String).includes(String(id))).map((id) => state.comps.get(String(id))).filter(Boolean);
    if (mechanismComps.length) {
      const references = el('details', 'panel mechanism-routes'); references.id = 'trait-mechanism-routes'; references.open = !comps.length;
      references.append(el('summary', '', `机制条件接入路线 · ${mechanismComps.length} 条（不是已成档模板）`));
      references.append(el('p', 'section-note', '这些来源路线的卡片、任务或核心机制可供条件接入参考，并没有自动激活本羁绊，更不是完整体系棋盘。'));
      const list = el('div', 'comp-list'); mechanismComps.forEach((comp) => list.append(compPreview(comp))); references.append(list); main.prepend(references);
    }
    if (relatedOnly.length) {
      const splash = el('details', 'panel incidental-panel'); splash.append(el('summary', '', `挂件关联方案 · ${relatedOnly.length} 条（未成档）`));
      splash.append(el('p', 'section-note', '这些方案只有关联棋子，未达到本羁绊起始档。它们不属于追满此羁绊的成套路线。'));
      relatedOnly.forEach((comp) => { const button = el('button', 'trait-reference', comp.name); button.type = 'button'; button.dataset.compId = String(comp.id); splash.append(button); }); side.append(splash);
    }
    grid.append(main, side); grid.id = 'trait-reference';
    const selected = [...comps, ...relatedOnly, ...mechanismComps].find((comp) => String(comp.id) === state.compId);
    if (selected) {
      if (mechanismComps.some((comp) => String(comp.id) === state.compId)) root.append(el('p', 'callout', '当前展开的是机制条件接入路线，源配方并未激活本羁绊；还需按当前棋盘补牌和核对条件，不能当成已成档来源模板。'));
      else if (!comps.some((comp) => String(comp.id) === state.compId)) root.append(el('p', 'callout', '当前展开的是挂件关联方案，模板未激活本羁绊的起始档，不应作为本羁绊成套运营。'));
      root.append(renderComp(selected));
    } else state.compId = '';
    root.append(grid);
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
    const section = panel('过渡与成型棋盘', 'BUILD THROUGH THE GAME'); section.id = 'comp-phases';
    const phases = arr(comp.phases);
    if (!phases.length) { section.append(el('p', 'empty-note', '来源没有提供可核验的过渡棋盘，不能从终局阵容反推一条固定前期路线。')); return section; }
    const phase = phases.find((entry) => String(entry.id) === state.phaseId) ?? phases[0]; state.phaseId = String(phase.id);
    const tabs = el('div', 'phase-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', '选择过渡阶段');
    phases.forEach((entry) => { const button = el('button', entry.id === phase.id ? 'selected' : '', entry.label); button.type = 'button'; button.dataset.phaseId = String(entry.id); button.setAttribute('aria-pressed', String(entry.id === phase.id)); tabs.append(button); }); section.append(tabs, el('p', 'phase-switch-help', '阶段可横向滑动切换，后期在右侧 →'));
    const actualPopulation = phase.actual_population_cost ?? phase.slots_consumed;
    const populationLabel = phase.board_status === 'source_subset'
      ? (phase.source_population ? `来源图 ${phase.source_population} 人口 · 部分体系牌` : '部分体系牌')
      : phase.board_status === 'source_invalid_population'
        ? `来源人口标注待核验${actualPopulation != null ? ` · 实占 ${actualPopulation} 人口` : ''}`
        : phase.board_status === 'source_partial_population'
          ? `来源 ${phase.population ?? '?'} 人口图 · 实占 ${actualPopulation ?? '?'} 人口`
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
    if (actualPopulation != null && !['core_only', 'not_provided'].includes(phase.board_status)) section.append(el('p', 'phase-footnote', `${phase.board_status === 'source_subset' ? '当前显示的局部体系牌若同时上场占用' : '来源图所列条目占用'} ${actualPopulation} 人口${phase.actual_unit_count != null ? `，有 ${phase.actual_unit_count} 个普通单位条目` : ''}。特殊单位可能占2人口、处于备战席或不占场上人口，不能用实体个数代替人口。`));
    section.append(el('p', 'phase-footnote', '棋子与召唤物可能同时出现在棋盘上。站位来自示例时仍需按对手切入、控制与范围伤害调整。'));
    return section;
  }

  function planPanel(comp) {
    const section = panel('什么时候 D / 升级 / 停手', 'ECONOMY & ROLL'); section.id = 'comp-plan'; const plan = comp.roll_plan ?? {};
    if (plan.style) section.append(el('p', 'section-note', planStyle(plan.style))); section.append(evidence(plan.provenance, '来源运营说明', '条件性运营参考'));
    const groups = [['01', '行动条件', plan.actions], ['02', '停手条件', plan.stop_conditions], ['03', '转型与退出条件', plan.pivot_conditions]];
    groups.forEach(([number, title, values]) => { const card = el('article', 'operation-card'); const heading = el('h4'); heading.append(el('span', 'operation-number', number), document.createTextNode(title)); card.append(heading); const list = bullets(values); if (list) card.append(list); else card.append(el('p', '', '来源没有提供明确条件，暂不编造固定回合或金币阈值。')); section.append(card); });
    return section;
  }

  function corePanel(comp) {
    const section = panel('核心牌与挂件分工', 'TEAM ROLES'); section.id = 'comp-core'; const grid = el('div', 'comp-core-grid');
    const groups = [['核心体系 / 输出', [...new Set([...arr(comp.carry_ids), ...arr(comp.core_ids)])], '核心体系'], ['前排与功能补强', [...new Set([...arr(comp.frontline_ids), ...arr(comp.utility_ids), ...arr(comp.flex_ids)])].filter((id) => !arr(comp.core_ids).map(String).includes(String(id)) && !arr(comp.carry_ids).map(String).includes(String(id))), '承伤 / 功能 / 可换位']];
    groups.forEach(([title, ids, role]) => { const column = el('div'); column.append(el('h4', 'role-heading', title)); if (ids.length) column.append(heroGrid(ids, role)); else column.append(el('p', 'empty-note', '来源未明确列出此类分工。')); grid.append(column); }); section.append(grid);
    if (arr(comp.three_star_ids).length) section.append(el('p', 'support-note', `追三星目标：${heroNames(comp.three_star_ids)}。是否继续追需结合数量、同行和血量。`));
    const note = bullets(comp.notes); if (note) section.append(note); return section;
  }

  function equipmentPanel(comp) {
    const section = panel('装备分配', 'WHO HOLDS WHAT'); section.id = 'comp-equipment';
    if (comp.equipment_slot_note) section.append(el('p', 'equipment-slot-warning', comp.equipment_slot_note));
    arr(comp.equipment).forEach((entry) => {
      if (!arr(entry.item_ids).length) return;
      const hero = heroRecord(entry.hero_id); const block = el('article', 'equipment-group'); const heading = el('div', 'equipment-owner'); heading.append(icon(hero), el('strong', '', hero.name)); block.append(heading);
      const row = el('div', 'item-row'); entry.item_ids.forEach((id) => row.append(itemButton(id))); block.append(row);
      if (entry.slot_note || arr(entry.item_ids).length > 3) {
        block.append(el('p', 'equipment-slot-warning', entry.slot_note ? `${String(entry.slot_note).split('；')[0]}。这是来源条件实例，不代表普通单位通用四格。` : `来源列出 ${entry.item_ids.length} 件装备；槽位条件尚待核验，不能当作普通三槽出装。`));
        if (arr(entry.requires_card_ids).length) block.append(el('p', 'support-note', `采用前核对：${cardNames(entry.requires_card_ids)}相关条件已实际成立。`));
        const details = el('details', 'slot-condition-details'); details.append(el('summary', '', '查看完整槽位条件与来源边界'));
        if (entry.slot_note) details.append(el('p', 'support-note', entry.slot_note)); const conditions = bullets([...new Set(arr(entry.conditions).filter((value) => value !== entry.slot_note))]); if (conditions) details.append(conditions); block.append(details);
      } else { const conditions = bullets(entry.conditions); if (conditions) block.append(conditions); }
      if (arr(entry.alternative_item_ids).length) {
        block.append(el('p', 'support-note', '来源列出的备选 · 需按效果替换，不是额外同时装备'));
        const alternatives = el('div', 'item-row'); entry.alternative_item_ids.forEach((id) => alternatives.append(itemButton(id))); block.append(alternatives);
      }
      if (entry.role || entry.reason) block.append(el('p', 'support-note', [entry.role, entry.reason].filter(Boolean).join(' · '))); section.append(block);
    });
    if (section.childNodes.length === 1) section.append(el('p', 'empty-note', '来源未明确给出装备归属，暂不把通用出装强配给某个单位。'));
    return section;
  }

  function replacementsPanel(comp) {
    const section = panel('替代与补强', 'FLEX YOUR BOARD'); section.id = 'comp-replacements';
    arr(comp.replacements).forEach((entry) => {
      const block = el('article', 'substitution'); block.append(el('h4', '', `${heroRecord(entry.from_id).name}的替换候选`));
      if (arr(entry.to_ids).length) block.append(heroGrid(entry.to_ids));
      if (entry.reason) block.append(el('p', '', entry.reason)); section.append(block);
    });
    if (section.childNodes.length === 1) section.append(el('p', 'empty-note', '当前没有可核验的替换关系。相同职业不等于可以直接替换，还需检查费用、装备和羁绊断点。'));
    return section;
  }

  function actionSummary(comp) {
    const section = panel('先看行动摘要', 'DECISION CHECK'); section.id = 'comp-overview';
    section.append(el('p', 'section-note', `${coverageLabel(compCoverage(comp))} · ${planStyle(comp.roll_plan?.style)}。以下只提取本方案已有条件，完整说明见运营区。`));
    const requiredCards = arr(comp.published_card_names).length ? comp.published_card_names.join('、') : cardNames(comp.card_ids);
    if (requiredCards) section.append(el('p', 'adoption-check', `采用前先核对卡片：${requiredCards}。卡片持有、等级与实际触发需成立。`));
    if (comp.equipment_slot_note) section.append(el('p', 'equipment-slot-warning', comp.equipment_slot_note));
    const unlockIds = [...new Set([...arr(comp.core_ids), ...arr(comp.carry_ids)])].filter((id) => state.heroes.get(String(id))?.unlock_requirements?.status === 'task_recorded');
    if (unlockIds.length) {
      const checks = el('div', 'unlock-quick-check'); checks.append(el('span', '', '核对核心解锁：'));
      unlockIds.forEach((id) => { const button = el('button', 'text-button', heroRecord(id).name); button.type = 'button'; button.dataset.heroId = String(id); checks.append(button); });
      checks.append(el('small', '', '普通任务或卡片路径需按当前局确认')); section.append(checks);
    }
    const conflictIds = [...new Set([...arr(comp.core_ids), ...arr(comp.carry_ids), ...arr(comp.frontline_ids), ...arr(comp.utility_ids), ...arr(comp.flex_ids), ...arr(comp.phases).flatMap((phase) => arr(phase.board).map((unit) => unit.hero_id))])].filter((id) => arr(state.heroes.get(String(id))?.unlock_requirements?.source_conflicts).length);
    if (conflictIds.length) {
      const alert = el('div', 'source-conflict-alert'); alert.append(el('strong', '', '解锁条件存在来源冲突 · 采用前核对'));
      conflictIds.forEach((id) => { const button = el('button', 'text-button', `${heroRecord(id).name}：查看两种证据 ↗`); button.type = 'button'; button.dataset.heroId = String(id); alert.append(button); }); section.append(alert);
    }
    const grid = el('div', 'action-summary-grid');
    [['路线重点', textOf(arr(comp.roll_plan?.actions)[0]) || comp.summary], ['停手检查', textOf(arr(comp.roll_plan?.stop_conditions)[0])], ['转型信号', textOf(arr(comp.roll_plan?.pivot_conditions)[0])]].forEach(([title, value]) => {
      const card = el('article', 'action-summary-card'); card.append(el('h3', '', title), el('p', '', value || '来源未给出明确条件，保留待核验。')); grid.append(card);
    }); section.append(grid); return section;
  }

  function compNavigation(comp) {
    const nav = el('nav', 'comp-quick-nav'); nav.setAttribute('aria-label', '本阵容页内导航');
    const links = [['comp-overview', '行动摘要'], ['comp-core', '核心分工'], ['comp-phases', '阶段棋盘'], ['comp-plan', '搜牌 / 升级'], ['comp-equipment', '装备'], ['comp-position', '站位'], ['comp-replacements', '替代']];
    if (arr(comp.card_ids).length || arr(comp.augment_ids).length || arr(comp.published_card_names).length) links.push(['comp-conditions', '卡片 / 强化']);
    if (state.index === 'traits') links.push(['trait-routes', '更换路线']);
    links.forEach(([id, label]) => { const button = el('button', '', label); button.type = 'button'; button.dataset.scrollTarget = id; nav.append(button); }); return nav;
  }

  function renderComp(comp) {
    const section = el('section', 'comp-section'); section.id = 'selected-comp'; section.tabIndex = -1;
    const header = el('header', 'comp-header'); header.append(el('p', 'eyebrow', 'COMPOSITION / GAME PLAN'), el('h2', '', comp.name));
    const meta = el('div', 'comp-heading-meta'); meta.append(evidence(comp.kind, compSourceLabel(comp), '大橘卡组条件构筑'));
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
    if (state.index === 'traits') {
      const trait = state.traits.get(state.traitKey);
      const label = el('label', 'route-picker', `当前羁绊：${trait?.name ?? ''} · 更换关联方案`); const select = document.createElement('select'); select.dataset.compPicker = 'true';
      [['成套 / 条件来源路线', trait?.linked_comp_ids], ['机制条件接入 · 源配方未激活本羁绊', trait?.mechanism_comp_ids], ['仅挂件关联 · 未达到该羁绊起始档', trait?.related_comp_ids]].forEach(([name, ids]) => {
        const group = document.createElement('optgroup'); group.label = name;
        arr(ids).forEach((id) => { const entry = state.comps.get(String(id)); if (entry) group.append(new Option(`${entry.name} · ${coverageLabel(compCoverage(entry))}`, String(id))); }); if (group.childNodes.length) select.append(group);
      }); select.value = String(comp.id); label.append(select); header.append(label);
    }
    section.append(compNavigation(comp), actionSummary(comp));
    const layout = el('div', 'operation-layout'); const main = el('div', 'operation-main'); const side = el('div', 'operation-sidebar');
    main.append(corePanel(comp), phasePanel(comp), planPanel(comp), replacementsPanel(comp));
    side.append(equipmentPanel(comp));
    const positioning = panel('站位与对位调整', 'POSITIONING'); positioning.id = 'comp-position';
    if (arr(comp.positioning?.board).some(validCell)) positioning.append(renderBoard(comp.positioning.board.filter(validCell), comp));
    if (comp.positioning?.summary) positioning.append(el('p', 'phase-notes', comp.positioning.summary));
    const notes = bullets(comp.positioning?.notes); if (notes) positioning.append(notes);
    if (!notes && !comp.positioning?.summary) positioning.append(el('p', 'empty-note', '来源未给出具体对位说明，不设固定最优格子。')); side.append(positioning);
    if (arr(comp.card_ids).length || arr(comp.augment_ids).length || arr(comp.published_card_names).length || arr(comp.unresolved_card_names).length) {
      const choices = panel('卡片与强化条件', 'MODE CONDITIONS'); choices.id = 'comp-conditions';
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
      if (arr(comp.augment_ids).length) {
        const row = el('div', 'augment-choices'); row.append(el('p', 'support-note', '来源强化 · 点击查看效果'));
        let hasUnknown = false;
        comp.augment_ids.forEach((id) => {
          const augment = arr(state.data.modes[state.mode].augments).find((entry) => String(entry.id) === String(id));
          if (!augment) { hasUnknown = true; return; }
          const button = el('button', 'augment-chip', augment.name); button.type = 'button'; button.dataset.augmentId = String(id); row.append(button);
        }); if (hasUnknown) row.append(el('p', 'dialog-note', '部分来源强化名称待核验。')); choices.append(row);
      }
      choices.append(el('p', 'support-note', '卡片与强化的持有、等级和触发条件需成立；不同模式的运营不能直接套用。')); side.append(choices);
      const unresolved = arr(comp.unresolved_card_names).length ? comp.unresolved_card_names : comp.unresolved_cards;
      if (arr(unresolved).length) choices.append(el('p', 'callout', `仍待核验的卡片：${unresolved.map((card) => typeof card === 'object' ? card.name ?? card.title ?? card.reason ?? '卡片后缀或等级' : card).join('、')}。这些条目不能视为已确认持有或已生效。`));
      if (comp.portal_claim) choices.append(el('p', 'dialog-note', `来源标注的适用传送门：${comp.portal_claim}；当前可用性仍需核对实际玩法。`));
    }
    layout.append(main, side); section.append(layout); return section;
  }

  function renderDetail() {
    if (state.index === 'comps') {
      const comp = state.comps.get(state.compId);
      if (comp) { $('strategy-detail').replaceChildren(renderComp(comp)); document.title = `${comp.name} · 羁绊与运营 · 弈策`; }
      else {
        const empty = panel('从索引选择一条路线', 'CHOOSE A PLAN');
        empty.append(el('p', 'section-note', '搜索只筛选索引，不会替你选择无关阵容。先选择左侧条目，再在本页查看行动摘要、过渡与运营。'));
        if (!state.comps.size) empty.append(el('p', 'empty-note', '该模式暂无来源明确的阵容模板，仍可从羁绊索引查看机制与原生池。'));
        $('strategy-detail').replaceChildren(empty); document.title = '选择阵容路线 · 弈策';
      }
      return;
    }
    const trait = state.traits.get(state.traitKey);
    if (trait) { renderTraitDetail(trait); document.title = `${trait.name} · 羁绊与运营 · 弈策`; }
    else $('strategy-detail').replaceChildren(el('p', 'empty-note', '该模式暂无可显示的羁绊资料。'));
  }

  function writeHash(push = false) {
    const mode = encodeURIComponent(state.mode);
    const hash = state.index === 'comps' ? `#${mode}/comp/${encodeURIComponent(state.compId)}` : `#${mode}/trait/${encodeURIComponent(state.traitKey)}${state.compId ? `/comp/${encodeURIComponent(state.compId)}` : ''}`;
    if (location.hash !== hash) history[push ? 'pushState' : 'replaceState'](null, '', hash);
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
    const copy = el('div'); const title = el('h2', '', heroDisplayName(hero)); title.id = 'unit-dialog-title';
    const professions = arr(hero.traits).filter((trait) => trait.kind === 'class').map((trait) => trait.name);
    copy.append(title, el('small', '', hero.cost == null ? '来源棋盘的召唤物 / 特殊单位' : `${hero.cost}费 · ${professions.length ? `职业：${professions.join(' / ')}` : hero.profession_status === 'none' ? '无常规职业' : '职业待核验'}`)); heading.append(copy); body.append(heading);
    const traits = arr(hero.traits).map((trait) => `${kindName(trait.kind)} · ${trait.name}`).join(' / '); if (traits) body.append(el('p', 'dialog-description', traits));
    if (hero.skill?.description) body.append(el('p', 'dialog-description', hero.skill.description));
    const unlock = hero.unlock_requirements;
    if (unlock) {
      const section = el('section', 'unlock-details'); section.append(el('h3', '', '解锁任务记录'));
      if (arr(unlock.source_conflicts).length) {
        section.append(el('p', 'source-conflict-alert', '来源条件存在冲突，实际客户端确认前不合并、不静默选用其中一方。'));
        unlock.source_conflicts.forEach((conflict) => {
          const block = el('article', 'unlock-conflict'); block.append(el('h4', '', '作者图与官方归档对照'));
          block.append(el('p', '', `作者图：${conflict.description || '描述待核验'}`), el('p', '', `官方归档：${conflict.archive_description || '描述待核验'}`));
          if (conflict.handling) block.append(el('p', 'conflict-handling', conflict.handling));
          const source = sourceLine(conflict.source); if (source) block.append(source); section.append(block);
        });
      }
      section.append(el('h4', 'role-heading', '普通任务配置 · 归档记录'));
      if (unlock.status === 'task_recorded') {
        section.append(el('p', 'dialog-note', '以下保留任务原文。分号或多条记录可能代表星级、模式或条件变体，不默认要求全部同时完成。'));
        arr(unlock.tasks).forEach((task) => {
          const entry = el('article', 'condition-card'); entry.append(el('p', 'card-effect', task.description_source || '这条任务未解析出完整描述。'));
          if (Number(task.minimum_level) > 0) entry.append(el('p', '', `配置最低等级：${task.minimum_level}。需核对这条变体是否适用于当前局。`));
          if (task.conditions_ambiguous) entry.append(el('p', '', '这条记录的条件存在歧义，暂不将分支合并为同时完成的要求。'));
          section.append(entry);
        });
      } else section.append(el('p', 'dialog-note', unlock.status === 'not_listed' ? '官方快照未列出普通解锁任务；未列出不表示无条件可购买。' : '当前解锁要求尚未核验。'));
      if (unlock.notice) section.append(el('p', 'callout', unlock.notice));
      const source = sourceLine(unlock.source); if (source) section.append(source); body.append(section);
      if (arr(unlock.direct_unlock_cards).length) {
        const direct = el('section', 'direct-unlock-cards'); direct.append(el('h3', '', '时间卡直接解锁 · 独立路径'));
        direct.append(el('p', 'dialog-note', '这是与普通任务不同的路径，不把两者合并成必须同时完成的条件。卡片持有、等级和实际触发仍需确认。'));
        unlock.direct_unlock_cards.forEach((card) => {
          const block = el('article', 'condition-card'); block.append(el('h4', '', `${card.name || '来源卡名待核验'} · 时间卡`), el('p', 'card-effect', card.description_source || '解锁效果尚待核验。'));
          const round = String(card.args_source || '').match(/(?:^|\^)round=([^\^]+)/)?.[1];
          if (round) block.append(el('p', '', `配置启用回合：${round}。这只表示启用时点，不代表无条件立即解锁或奖励到账。`));
          const record = arr(state.data.modes[state.mode].cards).find((entry) => String(entry.id) === String(card.id)); const source = sourceLine(card.source ?? record?.source); if (source) block.append(source); direct.append(block);
        }); body.append(direct);
      }
    }
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

  function showAugment(id) {
    const augment = arr(state.data.modes[state.mode].augments).find((entry) => String(entry.id) === String(id)); if (!augment) return;
    const body = $('unit-dialog-body'); body.replaceChildren(); const title = el('h2', '', augment.name); title.id = 'unit-dialog-title'; body.append(title);
    body.append(el('p', 'dialog-description', augment.description || '当前资料没有完整强化效果，需核对客户端与来源。'));
    const source = sourceLine(augment.source); if (source) body.append(source);
    body.append(el('p', 'dialog-note', '出现在来源阵容中不等于当前已获得；实际可选内容与适配条件仍需成立。'));
    if (!$('unit-dialog').open) $('unit-dialog').showModal();
  }

  function initEvents() {
    $('guide-link').href = guideUrl();
    document.querySelectorAll('button[data-mode]').forEach((button) => button.addEventListener('click', () => { setMode(button.dataset.mode); writeHash(true); }));
    document.querySelectorAll('[data-index]').forEach((button) => button.addEventListener('click', () => { state.index = button.dataset.index; if (state.index === 'comps') $('prismatic-only').checked = false; renderDetail(); renderIndex(); writeHash(true); }));
    $('strategy-search').addEventListener('input', renderIndex); $('trait-kind').addEventListener('change', renderIndex); $('coverage-filter').addEventListener('change', renderIndex);
    $('prismatic-only').addEventListener('change', renderIndex);
    $('show-prismatic').addEventListener('click', () => {
      state.index = 'traits'; $('strategy-search').value = ''; $('trait-kind').value = ''; $('coverage-filter').value = ''; $('prismatic-only').checked = true;
      renderDetail(); renderIndex(); writeHash(true); jumpTo('index-panel');
    });
    $('reset-search').addEventListener('click', clearFilters); $('clear-active-filter').addEventListener('click', clearFilters);
    $('strategy-detail').addEventListener('change', (event) => {
      if (!event.target.matches('[data-comp-picker]')) return;
      state.compId = event.target.value; state.phaseId = ''; renderDetail(); renderIndex(); writeHash(true); requestAnimationFrame(() => jumpTo('selected-comp'));
    });
    document.addEventListener('click', (event) => {
      const target = event.target.closest('button'); if (!target) return;
      if (target.dataset.scrollTarget) { jumpTo(target.dataset.scrollTarget); return; }
      if (target.dataset.traitKey) { state.traitKey = target.dataset.traitKey; state.index = 'traits'; state.compId = ''; state.phaseId = ''; state.moreComps = false; renderDetail(); renderIndex(); writeHash(true); if (window.matchMedia('(max-width:760px)').matches) requestAnimationFrame(() => jumpTo('strategy-detail')); return; }
      if (target.dataset.compId) {
        state.compId = target.dataset.compId; state.phaseId = ''; renderDetail(); renderIndex(); writeHash(true);
        requestAnimationFrame(() => jumpTo('selected-comp')); return;
      }
      if (target.dataset.phaseId) { state.phaseId = target.dataset.phaseId; renderDetail(); document.querySelector('.phase-tabs .selected')?.focus({ preventScroll: true }); return; }
      if (target.dataset.moreComps) { state.moreComps = !state.moreComps; renderDetail(); return; }
      if (target.dataset.itemId) { showItem(target.dataset.itemId); return; }
      if (target.dataset.augmentId) { showAugment(target.dataset.augmentId); return; }
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
      const hadHash = Boolean(location.hash);
      $('load-message').hidden = true; $('strategy-workspace').hidden = false; $('return-to-index').hidden = false; readHash(); writeHash();
      if (hadHash && window.matchMedia('(max-width:760px)').matches) requestAnimationFrame(() => jumpTo(state.compId ? 'selected-comp' : 'strategy-detail'));
    } catch (error) {
      const message = $('load-message'); message.className = 'load-message error'; message.replaceChildren(el('strong', '', '羁绊与阵容资料暂时无法打开'), el('span', '', '请检查网络后重试。刚发布的资料可能仍在同步。'));
      const retry = el('button', 'text-button', '重新载入'); retry.type = 'button'; retry.addEventListener('click', () => location.reload()); message.append(retry); $('version-badge').textContent = '资料未载入'; console.error('Strategy data load failed:', error);
    }
  }
  start();
})();
