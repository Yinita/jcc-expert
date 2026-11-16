# 棋子装备与站位资料

本页由 `scripts/build_hero_guide.py` 离线生成，浏览器读取 `app/static/guide-data.json`。GitHub Pages 使用相对资源路径，不依赖 FastAPI。

资料分三类：官方发布阵容中的实际装备与格子；根据官方技能、装备文本推导的条件性建议；第三方历史三件套统计。三类不混称为“最优出装”。

## 本次覆盖

- 自然之力：65 个普通棋子，64 个有官方发布阵容实例；158 件装备。
- 大橘大利：122 个普通棋子，另有 3 个特殊单位资料；207 件装备。没有同口径官方阵容模板或三件套统计，使用明确标注的机制建议。
- 特殊单位提伯斯、盛宴塔姆和迅捷蟹标价及出售价格为 0，可主动装备性未核验，不提供普通装备、神器、纹章建议。默认棋子列表排除它们。
- 自然之力第三方统计：42 个棋子、120 组三件套；22 个棋子没有达到门槛的可映射组合，另 1 个拉克丝形态未在来源中找到相同 ID，不借用同名英雄统计。

## 版本与来源

规则事实来自仓库的 `nature_facts.json`、`orange_base_facts.json`，规则标签为 18.6。`hero_guide_reference.json` 补充官方原配置中事实表未保存的技能与装备说明，并保存原始文件 SHA256、版本、生成日期和来源 URL。2026-11-16 再检查四个官方英雄/装备 URL，其版本和生成时间头仍与归档一致。

已有 18.6a 官方公告，尚未完成规则迁移。因此页面按旧版本参考显示，不声称当前实战最优。

`hero_guide_statistics.json` 来自金铲铲大数据公开英雄页及其相同站点的公开 Web 接口：

```text
https://www.dataj.cc/hero
https://www.dataj.cc/api/web/stats/hero/{heroId}/three-equip-combos?setId=18&gameVersion=18.6
```

每名英雄必须同时匹配公开表的 ID 与名字。每组必须恰有三件可映射装备，观测数至少 100；每英雄最多保存三组，按来源提供的第一率降序展示。百分数单位为 0–100，平均名次范围为 1–8。低样本的“100% 第一率”不会进入页面。

样本是来源站点的组合观测计数，具体队列、分段边界、时间窗、去重、星级混合口径未披露；统计未经独立核验。第一率与装备选择同时受到阵容、星级、成型时机等影响，不是装备带来因果胜率提升的证明。

每个已读取响应有 SHA256 和取得时间。完整响应仅保留在本机调用者指定的 cache 目录，本轮是开发工作区 `work/hero_guide_statistics_raw/`，不随网页发布；网页只发布上述少量筛选结果和来源信息。

## 重建与更新

使用当前归档重建，不访问网络：

```bash
python3 scripts/build_hero_guide.py
python3 -m pytest -q tests/test_hero_guide.py
```

主动更新公开统计快照（固定 setId 18、gameVersion 18.6；每次请求至少间隔 1 秒，最多 2 个并发）：

```bash
python3 scripts/fetch_hero_guide_statistics.py --cache var/hero-guide-source-cache
python3 scripts/fetch_hero_guide_statistics.py --cache var/hero-guide-source-cache --retry-unavailable
python3 scripts/build_hero_guide.py
python3 -m pytest -q tests/test_hero_guide.py
```

补丁变化时需要核验新英雄/装备 ID 与规则，再明确修改采集器的版本参数；不能只改页面版本文本。若来源不可访问或身份映射不唯一，保留无数据状态，不用别的英雄、单件装备数据或阵容整体胜率代替三件套统计。

## 站位与机制建议

格子坐标保留官方数据的 1–4 行、1–7 列：第一行为己方前排，第四行为后排；从画面左到右。官方示例与机制参考分别标注。来源中同一英雄可能有多个位置，频次是模板出现次数，不是实战位置胜率。

神器与纹章候选均附触发条件。原生羁绊纹章排除；无法力值被动棋子的机制建议排除回蓝装和魔蕴；“晕眩触发”的神器必须有明确晕眩文本，不能直接用击飞代替。阵容示例保留重复装备，不为去重破坏原三件套。

所有这些规则仍需结合当前棋盘、强化与对手调整。页面不是已验证的自动胜率优化器。
