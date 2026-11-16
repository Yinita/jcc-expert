(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const arr = (value) => Array.isArray(value) ? value : [];
  const state = { data: null, mode: 'nature', heroId: '', tab: 'standard', positionBuild: '', items: new Map(), heroes: new Map(), traits: new Map() };
  const costColors = ['#8b9ba6', '#8b9ba6', '#78af82', '#71a6c9', '#b692ce', '#d8ae68', '#e68b7d', '#e68b7d'];
  const categoryNames = { component: '基础散件', standard: '常规装备', artifact: '神器', emblem: '纹章', radiant: '光明装备', support: '辅助装备', other: '特殊装备' };
  const tabs = [ ['standard', '装备组合'], ['artifacts', '神器适配'], ['emblems', '纹章选择'], ['profile', '技能与羁绊'] ];
  const statsNames = { max_hp: '生命值', attack_damage: '攻击力', attack_speed: '攻击速度', armor: '护甲', magic_resist: '魔抗', attack_range: '攻击距离', initial_mana: '初始法力', max_mana: '最大法力', crit_percent: '暴击率' };
  const text = (value, fallback = '') => value == null ? fallback : String(value);

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value != null) element.textContent = String(value);
    return element;
  }

  function traitKind(trait) {
    if (['origin', 'race'].includes(trait?.kind)) return 'origin';
    if (['class', 'job'].includes(trait?.kind)) return 'class';
    return 'unknown';
  }

  function traitKey(trait) {
    return trait?.key || `${traitKind(trait)}:${trait?.id ?? ''}`;
  }

  function traitTypeName(trait) {
    return traitKind(trait) === 'class' ? '职业' : traitKind(trait) === 'origin' ? '特质' : '羁绊';
  }

  function orderedTraits(hero) {
    return arr(hero.traits).slice().sort((a, b) => Number(traitKind(b) === 'class') - Number(traitKind(a) === 'class'));
  }

  function traitCopy(trait) {
    return `${traitTypeName(trait)}：${trait.name ?? `ID ${trait.id} · 待核验`}`;
  }

  function professionCopy(hero) {
    return hero.profession_status === 'none' ? '无常规职业' : '职业待核验';
  }

  function directionCopy(hero) {
    return hero.role?.ambiguous
      ? '出装方向参考：待核验'
      : `出装方向参考（推断）：${hero.role?.label ?? '待核验'}`;
  }

  function itemTraitName(id) {
    const matches = [...state.traits.values()].filter((trait) => String(trait.id) === String(id));
    return matches.length === 1 ? matches[0].name : `羁绊 ID ${id} · 待核验`;
  }

  function safeLink(url) {
    try { const parsed = new URL(url); return parsed.protocol === 'https:' ? parsed.href : null; }
    catch { return null; }
  }

  function iconUrl(path) {
    if (!path || typeof path !== 'string') return null;
    if (path.startsWith('https://game.gtimg.cn/')) return path;
    const clean = path.replace(/^\.?\/?assets\//, '');
    if (!/^(nature|orange)\/(heros|heroes|items|cards)\/[A-Za-z0-9_.-]+\.(png|jpg|webp)$/i.test(clean)) return null;
    return new URL(`../assets/${clean}`, window.location.href).href;
  }

  function icon(className, record, alt = '') {
    const wrapper = node('span', className, text(record?.name, '?').slice(0, 1));
    const url = iconUrl(record?.icon ?? record?.icon_url);
    if (url) {
      const img = document.createElement('img');
      img.alt = alt;
      img.loading = 'lazy';
      img.decoding = 'async';
      img.src = url;
      img.addEventListener('error', () => img.remove(), { once: true });
      wrapper.replaceChildren(img);
      img.addEventListener('error', () => { wrapper.textContent = text(record?.name, '?').slice(0, 1); }, { once: true });
    }
    return wrapper;
  }

  function sourceLine(source, prefix = '来源') {
    if (!source) return null;
    const sources = Array.isArray(source) ? source : [source];
    const line = node('div', 'source-line');
    line.append(node('span', '', `${prefix}：`));
    sources.forEach((entry, index) => {
      if (!entry) return;
      if (index) line.append(node('span', '', '·'));
      const title = text(entry.title ?? entry.name ?? entry.source_title, '资料记录');
      const url = safeLink(entry.url ?? entry.source_url);
      if (url) {
        const link = node('a', '', `${title} ↗`);
        link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        line.append(link);
      } else line.append(node('span', '', title));
      if (entry.patch) line.append(node('span', '', `版本 ${entry.patch}`));
      if (entry.published_at) line.append(node('span', '', `发布于 ${String(entry.published_at).slice(0, 10)}`));
    });
    return line.childNodes.length > 1 ? line : null;
  }

  function evidenceTag(kind) {
    return node('span', `evidence-tag${kind === 'official_lineup' ? ' official' : ''}`, kind === 'official_lineup' ? '官方收录阵容' : '机制适配建议');
  }

  function conditionList(conditions) {
    const values = arr(conditions).filter(Boolean);
    if (!values.length) return null;
    const list = node('ul', 'conditions');
    values.forEach((value) => list.append(node('li', '', typeof value === 'object' ? value.text ?? value.description ?? '' : value)));
    return list;
  }

  function panel(title, kicker) {
    const element = node('section', 'panel');
    const heading = node('div', 'section-header');
    heading.append(node('h3', '', title));
    if (kicker) heading.append(node('span', 'eyebrow', kicker));
    element.append(heading);
    return element;
  }

  function itemButton(id, showName = true) {
    const item = state.items.get(String(id)) ?? { id, name: `装备 ${id}`, category: 'other' };
    const button = node('button', 'item-button');
    button.type = 'button';
    button.dataset.itemId = String(id);
    button.dataset.category = item.category ?? 'other';
    button.setAttribute('aria-label', `查看${item.name}的装备详情`);
    button.title = `${item.name}${item.base_stats ? ` · ${item.base_stats}` : ''} · 点击查看详情`;
    button.append(icon('item-icon', item));
    if (showName) button.append(node('span', '', item.name));
    return button;
  }

  function itemStrip(ids, plus = false) {
    const strip = node('div', 'build-items');
    arr(ids).forEach((id, index) => {
      if (plus && index) strip.append(node('span', 'item-plus', '+'));
      strip.append(itemButton(typeof id === 'object' ? id.item_id ?? id.id : id));
    });
    return strip;
  }

  function fillSelect(id, values, allLabel) {
    const field = $(id);
    field.replaceChildren(new Option(allLabel, ''));
    values.forEach(([value, label]) => field.add(new Option(label, value)));
  }

  function selectMode(mode, requestedHero = '', updateHash = true) {
    if (!state.data?.modes?.[mode]) return;
    state.mode = mode;
    state.positionBuild = '';
    state.items = new Map(arr(state.data.modes[mode].items).map((item) => [String(item.id), item]));
    state.heroes = new Map(arr(state.data.modes[mode].heroes).map((hero) => [String(hero.id), hero]));
    state.traits = new Map(arr(state.data.modes[mode].traits).map((trait) => [traitKey(trait), trait]));
    document.body.dataset.mode = mode;
    document.querySelectorAll('[data-mode]').forEach((button) => {
      const selected = button.dataset.mode === mode;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    resetFilters(false);
    const heroes = [...state.heroes.values()];
    const costs = [...new Set(heroes.map((hero) => Number(hero.cost)).filter(Number.isFinite))].sort((a, b) => a - b);
    const roles = new Map(heroes.filter((hero) => hero.role?.id && !hero.role.ambiguous).map((hero) => [hero.role.id, hero.role.label]));
    if (heroes.some((hero) => hero.role?.ambiguous)) roles.set('__unverified__', '方向待核验');
    const traits = new Map();
    heroes.forEach((hero) => arr(hero.traits).forEach((trait) => traits.set(traitKey(trait), `${trait.name} · ${traitTypeName(trait)}`)));
    fillSelect('cost-filter', costs.map((cost) => [String(cost), `${cost} 费`]), '全部费用');
    fillSelect('role-filter', [...roles.entries()], '全部参考方向');
    fillSelect('trait-filter', [...traits.entries()].sort((a, b) => a[1].localeCompare(b[1], 'zh-CN')), '全部羁绊');
    state.heroId = state.heroes.has(String(requestedHero)) ? String(requestedHero) : String(heroes[0]?.id ?? '');
    if (!requestedHero) state.heroId = String(heroes.find((hero) => hero.regular_shop_unit !== false)?.id ?? state.heroId);
    $('special-units').checked = state.heroes.get(state.heroId)?.regular_shop_unit === false;
    renderRoster();
    renderDetail();
    if (updateHash) writeHash();
  }

  function resetFilters(render = true) {
    ['hero-search', 'cost-filter', 'role-filter', 'trait-filter'].forEach((id) => { $(id).value = ''; });
    $('special-units').checked = false;
    if (render) renderRoster();
  }

  function renderRoster() {
    const query = $('hero-search').value.trim().toLocaleLowerCase();
    const cost = $('cost-filter').value;
    const role = $('role-filter').value;
    const trait = $('trait-filter').value;
    const heroes = [...state.heroes.values()].filter((hero) => {
      const haystack = [hero.name, hero.id, hero.role?.ambiguous ? '方向待核验' : hero.role?.label, ...arr(hero.traits).map((entry) => entry.name)].join(' ').toLocaleLowerCase();
      return (!query || haystack.includes(query)) && (!cost || String(hero.cost) === cost)
        && (!role || (role === '__unverified__' ? hero.role?.ambiguous : !hero.role?.ambiguous && hero.role?.id === role))
        && (!trait || arr(hero.traits).some((entry) => traitKey(entry) === trait))
        && ($('special-units').checked || hero.regular_shop_unit !== false);
    }).sort((a, b) => (Number(a.cost) - Number(b.cost)) || String(a.name).localeCompare(String(b.name), 'zh-CN'));
    $('hero-count').textContent = `${heroes.length} / ${state.heroes.size} 位`;
    const list = $('hero-list');
    list.replaceChildren();
    heroes.forEach((hero) => {
      const selected = String(hero.id) === state.heroId;
      const button = node('button', `hero-choice${selected ? ' selected' : ''}`);
      button.type = 'button'; button.dataset.heroId = String(hero.id);
      button.style.setProperty('--cost-color', costColors[Math.max(0, Math.min(7, Number(hero.cost) || 0))]);
      button.setAttribute('aria-pressed', String(selected));
      const officialTraits = orderedTraits(hero);
      const professionPrefix = officialTraits.some((trait) => traitKind(trait) === 'class') ? '' : `${professionCopy(hero)}，`;
      button.setAttribute('aria-label', `${hero.name}，${hero.cost}费，${professionPrefix}${officialTraits.map(traitCopy).join('，') || '特质资料未提供'}`);
      button.append(icon('portrait', hero));
      const copy = node('span', 'hero-choice-text');
      const traitsText = `${professionPrefix}${officialTraits.map(traitCopy).join(' · ') || '特质资料未提供'}`;
      const traitsLabel = node('small', '', traitsText); traitsLabel.title = traitsText;
      copy.append(node('strong', '', hero.name), traitsLabel);
      button.append(copy, node('span', 'cost-pip', hero.cost));
      list.append(button);
    });
    $('empty-roster').hidden = heroes.length > 0;
    list.hidden = !heroes.length;
  }

  function renderHeroHeader(hero) {
    const summary = node('header', 'hero-summary');
    summary.style.setProperty('--cost-color', costColors[Math.max(0, Math.min(7, Number(hero.cost) || 0))]);
    summary.append(icon('portrait', hero));
    const identity = node('div', 'hero-identity');
    identity.append(node('p', 'eyebrow', `${state.data.modes[state.mode].name} / CHAMPION ${hero.id}`));
    const title = node('div', 'hero-title-line');
    title.append(node('h2', '', hero.name));
    const classes = arr(hero.traits).filter((trait) => traitKind(trait) === 'class');
    if (classes.length) classes.forEach((trait) => title.append(node('span', `class-tag${trait.verified === false ? ' unverified' : ''}`, `职业 · ${trait.name}`)));
    else title.append(node('span', `class-tag${hero.profession_status === 'none' ? '' : ' unverified'}`, professionCopy(hero)));
    identity.append(title);
    const traits = node('div', 'traits');
    arr(hero.traits).filter((trait) => traitKind(trait) !== 'class').forEach((trait) => {
      const chip = node('span', `trait-chip${trait.verified === false ? ' unverified' : ''}`, `${traitTypeName(trait)} · ${trait.name}`);
      traits.append(chip);
    });
    identity.append(traits); summary.append(identity);
    identity.append(node('p', `role-reference${hero.role?.ambiguous ? ' uncertain' : ''}`, directionCopy(hero)));
    const meta = node('div', 'hero-summary-meta');
    meta.append(node('strong', '', `${hero.cost} 费`), node('small', '', '依据阵容与机制选择装备'));
    summary.append(meta);
    return summary;
  }

  function renderBuilds(hero) {
    const element = panel('推荐装备组合', 'BUILD THE CORE');
    element.append(node('p', 'section-note', '先看适用阵容与承担的角色，再选择组合。点击装备查看属性、效果与合成路径。'));
    const builds = arr(hero.builds).filter((build) => arr(build.item_ids).length > 0);
    if (!builds.length) element.append(node('p', 'empty-note', hero.recommendation_note || '暂缺可核验的装备组合，当前保持待核验；这不表示没有适配装备。'));
    else if (hero.role?.ambiguous && hero.recommendation_note) element.append(node('p', 'section-note', hero.recommendation_note));
    builds.forEach((build) => {
      const card = node('article', 'build-card');
      const title = node('div', 'build-title');
      title.append(node('h4', '', build.title || '装备组合'), evidenceTag(build.kind));
      card.append(title, itemStrip(build.item_ids));
      if (build.reason) card.append(node('p', 'build-reason', build.reason));
      const conditions = conditionList(build.conditions); if (conditions) card.append(conditions);
      const source = sourceLine(build.source); if (source) card.append(source);
      element.append(card);
    });
    return element;
  }

  function renderCombinationStats(hero) {
    const element = panel('历史三件套表现', 'OBSERVED RESULTS');
    const statistics = hero.statistics;
    const minimum = Math.max(100, Number(statistics?.minimum_sample_count) || 100);
    const rows = arr(statistics?.combos).filter((combo) =>
      Number(combo.sample_count) >= minimum && arr(combo.item_ids).length === 3
      && ['first_rate', 'top4_rate'].every((key) => Number.isFinite(Number(combo[key])) && Number(combo[key]) >= 0 && Number(combo[key]) <= 100)
      && Number.isFinite(Number(combo.avg_placement)) && Number(combo.avg_placement) >= 1 && Number(combo.avg_placement) <= 8);
    if (!rows.length) {
      element.append(node('p', 'empty-note', statistics?.reason || '暂无满足展示条件的英雄三件套统计；不以机制建议替代真实胜率。'));
      element.append(node('p', 'stats-note', `组合需有至少${minimum}条样本及可核对来源。没有数据显示不等于组合无效。`));
    } else {
      const patch = statistics.source?.patch ?? '未披露';
      element.append(node('p', 'section-note', `第三方自报 · ${patch} 版本历史快照。展示满足样本门槛的组合，不代表当前版本最优。`));
      rows.forEach((combo, index) => {
        const card = node('article', 'stats-combo');
        const heading = node('div', 'build-title');
        heading.append(node('h4', '', `三件套 ${String(index + 1).padStart(2, '0')}`), node('span', 'sample-count', `${Number(combo.sample_count).toLocaleString('zh-CN')} 样本`));
        card.append(heading, itemStrip(combo.item_ids));
        const metrics = node('div', 'combo-metrics');
        [['第一率', `${Number(combo.first_rate).toFixed(1)}%`], ['前四率', `${Number(combo.top4_rate).toFixed(1)}%`], ['平均名次', Number(combo.avg_placement).toFixed(2)]].forEach(([label, value]) => {
          const metric = node('div'); metric.append(node('span', '', label), node('strong', '', value)); metrics.append(metric);
        });
        card.append(metrics); element.append(card);
      });
      element.append(node('p', 'stats-note', statistics.notice || '第三方历史观察，样本口径未独立核验。持有这些装备与较好名次相关，不证明换装本身带来胜率提升。'));
      if (statistics.source?.retrieved_at) element.append(node('p', 'stats-note', `采集日期：${String(statistics.source.retrieved_at).slice(0, 10)} · 每组至少${minimum}样本`));
    }
    const source = sourceLine(statistics?.source); if (source) element.append(source);
    const external = safeLink(hero.statistics_url);
    if (external) {
      const link = node('a', 'source-line', '打开外部英雄统计页面 ↗');
      link.href = external; link.target = '_blank'; link.rel = 'noopener noreferrer'; element.append(link);
    }
    return element;
  }

  function renderItemRecommendations(hero, kind) {
    const isArtifact = kind === 'artifacts';
    const element = panel(isArtifact ? '适合考虑的神器' : '纹章与转职选择', isArtifact ? 'ARTIFACT FIT' : 'TRAIT OPTIONS');
    element.append(node('p', 'tab-summary', isArtifact
      ? '神器会改变棋子的输出或生存方式。以下选择附带适用条件，优先核对技能机制与整套装备。'
      : '纹章价值取决于全队羁绊断点。先确认目标羁绊与棋子职责，再考虑把纹章交给谁。'));
    const list = node('div', 'recommendation-list');
    const rows = arr(hero[kind]);
    if (!rows.length) list.append(node('p', 'empty-note', hero.recommendation_note || (isArtifact ? '这位棋子的神器适配尚待核验；没有条目不表示不存在适配选择。' : '这位棋子的纹章适配尚待核验；仅有纹章名称不能证明适合携带。')));
    rows.forEach((row) => {
      const item = state.items.get(String(row.item_id));
      const card = node('article', 'item-recommendation');
      card.append(itemButton(row.item_id));
      const copy = node('div');
      copy.append(node('h4', '', item?.name ?? row.name ?? `装备 ${row.item_id}`));
      if (row.reason) copy.append(node('p', 'item-reason', row.reason));
      const conditions = conditionList(row.conditions); if (conditions) copy.append(conditions);
      copy.append(evidenceTag(row.kind));
      const source = sourceLine(row.source); if (source) copy.append(source);
      card.append(copy); list.append(card);
    });
    element.append(list);
    return element;
  }

  function normalizedCell(value) {
    if (!value || !Number.isInteger(value.row) || !Number.isInteger(value.col)) return null;
    if (value.row < 1 || value.row > 4 || value.col < 1 || value.col > 7) return null;
    return { row: value.row - 1, col: value.col - 1 };
  }

  function renderPositioning(hero) {
    const element = panel('站位参考', 'POSITIONING');
    const positioning = hero.positioning ?? {};
    const officialBuilds = arr(hero.builds).filter((build) => build.kind === 'official_lineup' && arr(build.board).length && normalizedCell(build.position));
    const officialBuild = officialBuilds.find((build) => String(build.id) === state.positionBuild) ?? officialBuilds[0];
    const cells = officialBuild ? [] : arr(positioning.recommended_cells).map(normalizedCell).filter(Boolean);
    if (officialBuilds.length > 1) {
      const label = node('label', 'trait-filter', '选择阵容示例');
      const select = document.createElement('select'); select.dataset.positionBuild = 'true';
      officialBuilds.forEach((build) => select.add(new Option(build.title, String(build.id))));
      select.value = String(officialBuild.id); label.append(select); label.style.marginBottom = '12px'; element.append(label);
    } else if (officialBuild) element.append(node('p', 'section-note', officialBuild.title));
    const board = officialBuild ? arr(officialBuild.board).flatMap((unit) => {
      const cell = normalizedCell(unit);
      return cell ? [{ ...unit, ...cell }] : [];
    }) : [];
    const highlighted = new Set(cells.map((cell) => `${cell.row}:${cell.col}`));
    const officialCell = normalizedCell(officialBuild?.position);
    if (officialCell) highlighted.add(`${officialCell.row}:${officialCell.col}`);
    if (highlighted.size) {
      const stage = node('div', 'board-stage');
      stage.append(node('div', 'board-label', '对手方向 ↑'));
      for (let row = 0; row < 4; row += 1) {
        const line = node('div', 'hex-row');
        for (let col = 0; col < 7; col += 1) {
          const selected = highlighted.has(`${row}:${col}`);
          const occupied = board.find((unit) => unit.row === row && unit.col === col);
          const occupant = occupied ? state.heroes.get(String(occupied.hero_id)) : null;
          const cell = node('div', `hex-cell${selected ? ' recommended' : occupied ? ' occupied' : ''}`);
          cell.setAttribute('role', 'img');
          cell.setAttribute('aria-label', `第${row + 1}排第${col + 1}格${selected ? `，${hero.name}参考位置` : occupant ? `，${occupant.name}` : ''}`);
          cell.title = `第${row + 1}排 · 第${col + 1}格${selected ? ` · ${hero.name}参考位置` : occupant ? ` · ${occupant.name}` : ''}`;
          if (selected) cell.append(node('span', '', '◎'));
          else if (occupant && iconUrl(occupant.icon)) {
            const img = document.createElement('img'); img.alt = occupant.name; img.src = iconUrl(occupant.icon); img.loading = 'lazy';
            img.addEventListener('error', () => img.remove(), { once: true }); cell.append(img);
          } else cell.append(node('span', '', '·'));
          line.append(cell);
        }
        stage.append(line);
      }
      const facing = node('div', 'board-facing'); facing.append(node('span', '', '前排 ↑'), node('span', '', '↓ 后排')); stage.append(facing);
      element.append(stage);
      const legend = node('div', 'board-legend');
      const target = node('span'); target.append(node('i', 'legend-dot'), document.createTextNode(`${hero.name}参考位置`)); legend.append(target);
      if (board.length) { const teammate = node('span'); teammate.append(node('i', 'legend-dot secondary'), document.createTextNode('阵容其他单位')); legend.append(teammate); }
      element.append(legend);
    } else element.append(node('p', 'empty-note', '暂无已核验的具体格子，先参考下方站位原则。'));
    if (positioning.summary) element.append(node('p', 'position-summary', positioning.summary));
    if (positioning.reason) element.append(node('p', 'position-help', positioning.reason));
    element.append(node('p', 'position-help', '对手站位、切入、控制与范围伤害会改变最优位置。图中格子是参考，不是固定答案。'));
    if (positioning.kind || cells.length || officialBuild) element.append(evidenceTag(officialBuild ? 'official_lineup' : positioning.kind));
    const source = sourceLine(officialBuild?.source ?? (positioning.sources?.length ? positioning.sources : null)); if (source) element.append(source);
    return element;
  }

  function renderStats(hero) {
    const element = panel('基础属性', 'ONE STAR');
    const grid = node('div', 'stat-grid');
    Object.entries(statsNames).forEach(([key, label]) => {
      const value = hero.stats?.[key];
      if (value == null) return;
      const cell = node('div', 'stat-cell');
      cell.append(node('span', '', label), node('strong', '', `${value}${key === 'crit_percent' ? '%' : ''}`));
      grid.append(cell);
    });
    if (grid.childNodes.length) element.append(grid);
    else element.append(node('p', 'empty-note', '暂无完整基础属性。'));
    return element;
  }

  function renderSkill(hero, full = false) {
    const element = panel('技能与出装方向', 'KNOW YOUR UNIT');
    element.append(node('h4', 'skill-name', hero.skill?.name ?? '技能资料待补充'));
    element.append(node('p', 'skill-description', hero.skill?.description || '暂无完整技能描述，请以客户端技能说明为准。'));
    if (hero.skill?.scaling) {
      const details = node('details', 'skill-scaling');
      details.append(node('summary', '', '查看星级成长数值'), node('p', 'skill-description', String(hero.skill.scaling).replaceAll('|', '\n')));
      element.append(details);
    }
    if (hero.role?.reason) element.append(node('p', 'role-reason', `${directionCopy(hero)}。${hero.role.reason}`));
    const skillSource = sourceLine(hero.skill?.source); if (skillSource) element.append(skillSource);
    if (full && arr(hero.traits).length) {
      const heading = node('div', 'section-header'); heading.style.marginTop = '25px'; heading.append(node('h3', '', '官方职业与特质')); element.append(heading);
      const list = node('div', 'related-traits');
      orderedTraits(hero).forEach((entry) => {
        const trait = state.traits.get(traitKey(entry)) ?? entry;
        const card = node('article', 'trait-detail');
        card.append(node('h4', '', `${traitTypeName(trait)} · ${trait.name}`), node('p', '', trait.description || trait.effect || trait.desc || (trait.verified === false ? '官方特质列表尚未提供此 ID 的名称，暂不推测。' : '具体效果与断点以客户端当前版本为准。')));
        if (arr(trait.breakpoints).length) card.append(node('p', 'trait-breakpoints', `激活档位：${trait.breakpoints.join(' / ')}`));
        list.append(card);
      });
      element.append(list);
    }
    return element;
  }

  function renderDetail() {
    const hero = state.heroes.get(state.heroId);
    if (!hero) { $('hero-detail').replaceChildren(node('div', 'detail-placeholder', '这个玩法暂时没有可显示的棋子。')); return; }
    document.title = `${hero.name} · 装备与站位 · 弈策`;
    const detail = $('hero-detail'); detail.replaceChildren(renderHeroHeader(hero));
    if (hero.equipment_eligibility === 'unverified_special_unit') detail.append(node('p', 'special-unit-notice', '特殊单位 · 装备可用性尚未核验，暂不提供通用出装、神器或纹章建议。'));
    const navigation = node('div', 'detail-tabs'); navigation.setAttribute('role', 'tablist'); navigation.setAttribute('aria-label', `${hero.name}的资料类别`);
    tabs.forEach(([id, name]) => {
      const button = node('button', `detail-tab${state.tab === id ? ' selected' : ''}`, name);
      button.type = 'button'; button.dataset.tab = id; button.id = `tab-${id}`;
      button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(state.tab === id));
      button.setAttribute('aria-controls', 'detail-tab-panel'); button.tabIndex = state.tab === id ? 0 : -1;
      navigation.append(button);
    }); detail.append(navigation);
    const columns = node('div', 'content-columns'); columns.id = 'detail-tab-panel'; columns.setAttribute('role', 'tabpanel'); columns.setAttribute('aria-labelledby', `tab-${state.tab}`);
    const primary = node('div', 'primary-column');
    if (state.tab === 'standard') primary.append(renderCombinationStats(hero), renderBuilds(hero));
    else if (state.tab === 'artifacts' || state.tab === 'emblems') primary.append(renderItemRecommendations(hero, state.tab));
    else primary.append(renderSkill(hero, true), renderStats(hero));
    const side = node('div', 'side-column'); side.append(renderPositioning(hero));
    if (state.tab !== 'profile') side.append(renderStats(hero), renderSkill(hero));
    columns.append(primary, side); detail.append(columns);
  }

  function showItem(id) {
    const item = state.items.get(String(id));
    if (!item) return;
    const body = $('item-dialog-body'); body.replaceChildren();
    const heading = node('div', 'dialog-item-heading'); heading.append(icon('item-icon', item));
    const title = node('div'); const name = node('h2', '', item.name); name.id = 'item-dialog-title';
    title.append(name, node('small', '', categoryNames[item.category] ?? item.type ?? '装备')); heading.append(title); body.append(heading);
    if (item.base_stats) body.append(node('p', 'item-base-stats', item.base_stats));
    body.append(node('p', 'item-description', item.description || '暂无完整效果说明，请以客户端为准。'));
    if (arr(item.components).length) { body.append(node('h3', 'components-heading', '合成路径'), itemStrip(item.components, true)); }
    if (item.trait_ids?.length) body.append(node('p', 'dialog-note', `关联羁绊：${item.trait_ids.map(itemTraitName).join('、')}`));
    const source = sourceLine(item.source); if (source) body.append(source);
    body.append(node('p', 'dialog-note', `装备 ID ${item.id} · 规则资料 ${state.data.meta?.rules_patch ?? '18.6'}。不同玩法和补丁中的效果可能不同。`));
    if (!$('item-dialog').open) $('item-dialog').showModal();
  }

  function writeHash() {
    const next = `#${encodeURIComponent(state.mode)}/${encodeURIComponent(state.heroId)}/${encodeURIComponent(state.tab)}`;
    if (location.hash !== next) history.replaceState(null, '', next);
  }

  function readHash() {
    const [rawMode, rawHero, rawTab] = location.hash.slice(1).split('/');
    const decode = (value) => { try { return decodeURIComponent(value ?? ''); } catch { return ''; } };
    const mode = decode(rawMode); const hero = decode(rawHero); const tab = decode(rawTab);
    state.tab = tabs.some(([id]) => id === tab) ? tab : 'standard';
    selectMode(state.data.modes[mode] ? mode : 'nature', hero, false);
  }

  function initEvents() {
    document.querySelectorAll('[data-mode]').forEach((button) => button.addEventListener('click', () => selectMode(button.dataset.mode)));
    $('hero-search').addEventListener('input', renderRoster);
    ['cost-filter', 'role-filter', 'trait-filter'].forEach((id) => $(id).addEventListener('change', renderRoster));
    $('special-units').addEventListener('change', renderRoster);
    $('reset-filters').addEventListener('click', () => resetFilters());
    $('hero-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-hero-id]');
      if (!button) return;
      state.heroId = button.dataset.heroId; state.positionBuild = ''; renderRoster(); renderDetail(); writeHash();
    });
    $('hero-detail').addEventListener('click', (event) => {
      const button = event.target.closest('[data-tab]');
      if (!button) return;
      state.tab = button.dataset.tab; renderDetail(); writeHash(); $(`tab-${state.tab}`).focus({ preventScroll: true });
    });
    $('hero-detail').addEventListener('change', (event) => {
      if (!event.target.matches('[data-position-build]')) return;
      state.positionBuild = event.target.value; renderDetail();
    });
    $('hero-detail').addEventListener('keydown', (event) => {
      const button = event.target.closest('[data-tab]');
      if (!button || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = tabs.findIndex(([id]) => id === state.tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      state.tab = tabs[next][0]; renderDetail(); writeHash(); $(`tab-${state.tab}`).focus();
    });
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-item-id]');
      if (button) showItem(button.dataset.itemId);
    });
    $('close-item').addEventListener('click', () => $('item-dialog').close());
    $('item-dialog').addEventListener('click', (event) => {
      if (event.target !== $('item-dialog')) return;
      const rect = $('item-dialog').getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $('item-dialog').close();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) && !$('item-dialog').open) { event.preventDefault(); $('hero-search').focus(); }
    });
    window.addEventListener('hashchange', readHash);
  }

  async function start() {
    initEvents();
    try {
      const response = await fetch(new URL('./guide-data.json', window.location.href), { cache: 'no-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
      if (!state.data?.modes?.nature || !state.data?.modes?.orange) throw new Error('资料结构不完整');
      const meta = state.data.meta ?? {};
      $('version-badge').textContent = `${meta.rules_patch ?? '18.6'} · 历史规则资料`;
      $('data-notice').textContent = meta.notice || '当前为历史规则资料；请核对实际客户端版本。搭配建议不等于同版本胜率排名。';
      $('data-as-of').textContent = meta.data_as_of ? `资料快照 ${meta.data_as_of}` : '';
      $('load-message').hidden = true; $('guide-workspace').hidden = false;
      readHash(); writeHash();
    } catch (error) {
      const message = $('load-message'); message.className = 'load-message error';
      message.replaceChildren(node('strong', '', '棋子资料暂时无法打开'), node('span', '', '请检查网络后重试。如果刚刚发布，资料可能仍在同步。'));
      const retry = node('button', 'text-button', '重新载入'); retry.type = 'button'; retry.addEventListener('click', () => location.reload()); message.append(retry);
      $('version-badge').textContent = '资料未载入'; $('data-notice').textContent = '尚未加载装备、英雄与站位资料。';
      console.error('Guide data load failed:', error);
    }
  }

  start();
})();
