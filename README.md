# 弈策：金铲铲截图专家系统 v0.3.1

本地截图辅助原型：上传对局画面、校正已知信息，再比较自然之力阵容或大橘大利卡组，查看装备与运营建议。适配评分是可解释的资源匹配分，不是吃鸡概率。没有真实名次训练数据时，个人概率保持null。

规则数据快照仍为2026-11-10的18.6。2026-11-12已核验18.6a官方公告，但25份官网静态配置未更新，王国后裔仍有与公告不一致的旧数值。应用显示版本提示，允许填写实际补丁；不匹配时暂停阵容建议和该版本训练记录。截图识别仍可查看，但不会假装读出了图片的客户端补丁。详见本轮报告的补丁审计。

## 在线棋子装备与站位图鉴

[打开在线工具箱](https://yinita.github.io/jcc-expert/) · [直接进入棋子图鉴](https://yinita.github.io/jcc-expert/guide/)

[羁绊与阵容运营](https://yinita.github.io/jcc-expert/strategy/) 将体系牌、核心与挂件、前中后期过渡、搜牌和升级条件、替代转型、装备与站位放在一个页面中。职业与特质分别查询；完整阵容模板、卡组路线和条件性建议分别标记。

[灵魂莲华高阶路线](https://yinita.github.io/jcc-expert/strategy/#nature/trait/origin%3A452) 展示指定形态拉克丝的双计数，以及9莲华、11莲华所需的普通人口和纹章承载位。高阶羁绊的算术条件与推荐战斗阵容分别展示；巨龙等特殊单位的实际人口消耗单独计算。大橘大利的机制参考同时展示英雄解锁任务及分阶段接入条件。独立批评、复现步骤和修复验收见 [RED_TEAM_REVIEW.md](RED_TEAM_REVIEW.md)。

图鉴可以在电脑或平板浏览器中直接使用，支持自然之力与大橘大利棋子搜索、费用/羁绊筛选、装备组合、神器、纹章和站位查询。官方阵容模板与技能规则推断分别标注；没有英雄与装备组合样本的内容不标为高胜率。资料版本及来源在页面中展示。

截图工作台侧栏也有图鉴入口。GitHub Pages托管静态图鉴；截图识别、数据库和训练仍由下述本地服务运行。静态发布目录只包含精选静态资料和英雄/装备/卡片图标，不包含用户截图、访问码或运行数据。

更新资料后重新生成并提交发布目录：

```bash
python3 scripts/build_hero_guide.py
python3 scripts/build_strategy_guide.py
python3 scripts/build_pages.py
```

GitHub仓库 `Settings → Pages` 选择 `Deploy from a branch`、`main`、`/docs`。发布入口为 `docs/index.html`，棋子图鉴位于 `docs/guide/index.html`，阵容运营位于 `docs/strategy/index.html`，资源使用相对路径以适配 `/jcc-expert/` 项目站点。

## 平板访问

运行 `./run-tablet.sh`，让平板与电脑处于可互通的局域网，再使用启动器显示的二维码或完整链接。电脑负责识别，平板使用浏览器。入口有访问码，详细设置与排障见 [TABLET.md](TABLET.md)。

## 安装和启动

环境：Python 3.10或更高。以下示例适用于Debian/Ubuntu，首次克隆后安装依赖：

```bash
git clone git@github.com:Yinita/jcc-expert.git
cd jcc-expert
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
# 可选：安装本地神经OCR模型
./scripts/install_ocr.sh
./run.sh
```

打开 http://127.0.0.1:8765 。默认只监听本机，可用 `JCC_PORT=8766 ./run.sh` 改端口。启动器默认限制数值计算库为1线程，可用JCC_BLAS_THREADS调整；OpenCV默认2线程。以后进入项目目录、激活虚拟环境，再执行 `./run.sh` 或 `./run-tablet.sh`。

仓库包含源码、依赖清单、官网参考图缓存，以及公开截图的评测和未启用训练候选。`var/`、用户上传、数据库、访问码、二维码及本机运行环境不入Git。历史评测、训练报告中的绝对路径是原实验的来源记录；跨机器复现使用下文的专用脚本。

RapidOCR是可选本地模型，未安装时回退Tesseract。模型随固定版本官方wheel安装，约31.75MB，不放入源码ZIP。推理禁用网络，不需要API key，也不上传截图。固定依赖记录在requirements-ocr.txt和requirements-ocr.lock.txt，可用JCC_RAPIDOCR_PYTHON指定独立OCR环境。

390张官网参考图已缓存；大橘英雄18352的头像404缺口保留在manifest。重新下载：

```bash
python3 scripts/download_assets.py --mode all --kind all --limit 0
```

## 使用

1. 选择玩法，核对实际对局补丁，上传PNG/JPEG/WebP截图。建议保留完整棋盘、商店、资源栏。
2. 核对回合、金币、血量、等级、商店槽位及实体候选。名字和头像不能自动证明棋盘位置、星级或装备归属；未知字段保留空白。
3. 用“校准截图布局”框出单位图标或数值区域。商店最多五槽，声明顺序决定槽位；没有读到不能当作真正空槽。
4. 手工确认卡片等级和持有关系，再加入出战卡片。卡册、预设、修复、奖励卡片均有角色标签；同一插画不能证明卡片等级。卡片区域校准也不会绕过这个要求。
5. 确认当前信息与补丁后生成建议。修改任何局面字段都会撤销确认及旧建议。结算后，同一局保持相同对局编号，记录真实名次。

自然之力的64套官方模板用于比较持牌、装备、羁绊、强化与转型成本。装备合成消耗实际库存，同一散件不会重复分配；搜牌预算与购买价格共同计入金币。升级经验表和未来刷牌结果未核验，精确升级费用保持未知。大橘构筑只有卡组和任务核心，缺完整棋盘时不会让玩家拆卖过渡单位；不同于本局带入卡片的构筑仅作下一局战前备选。外部终局统计单列，不参与当前适配评分。

## v0.3.0截图优化与实测

新增圆形手游HUD识别：要求真实XP按钮、圆环及可解析数字共同成立；利息、刷新费和经验价格不会当作金币。顶部商店可在首槽锚点明确时保留中间缺格；同名不同羁绊形态（例如拉克丝）仍不凭名字或头像选择形态，手选英雄时展示羁绊和ID。

大橘卡名保留Roman原始字形，并结合标题末尾像素证据，避免将混合“ⅡI”强行归一成III。全图和手动卡片区域均不凭共享插画自动写入出战卡片。局外金橘、卡片生效回合、奖励价值不作为当前对局资源。

本轮共52张真实公开画面、17个文章/原录像/帖子来源组：

| 范围 | 已标字段 | 基线正确 | 优化正确 | 优化错误 | 优化弃答 |
|---|---:|---:|---:|---:|---:|
| 45张消费开发图/14组 | 124 | 57 | 96 | 0 | 28 |
| 7张新来源留出/3组 | 22 | 12 | 12 | 0 | 10 |

开发评测回放实际历史whole-image OCR，再运行当前后处理与必要HUD局部OCR；不是完整OCR模型的独立提升。新7张在冻结后首次执行完整OCR流程，未观察到增量。旧38张及此前留出全部已消费，不再当独立测试。图片数不代表独立对局，服别/补丁未知仍保持未知；未用本批训练胜率模型。

完整报告：`validation/round3-2026-11-12/index.html`，应用中访问 `/validation/round3-2026-11-12/`。历史报告保留在`validation/expanded-screens-2026-11-11/`及`validation/real-screens-2026-11-11/`。默认识别、人工ROI辅助、字段缺席检查和不完整实体区域诊断分别统计，不把未标注或弃答计正确；区域命中不是全量召回率或精确率。配对耗时受缓存和执行路径影响，不计算加速倍数。

## 识别纠错与训练

上传真实截图并填写对局编号，框出正确数值，确认后可保存识别纠错。也可以在“补充识别纠错区域”中框出经验价格、倒计时、奖励等容易混淆的内容；每个排除框都必须人工确认它不属于当前回合/金币/血量/等级。未知文字不会自动变成负例。

纠错按同图增量合并，保留此前数值和排除框；需要删除错误旧框时，可明确勾选替换本图已存标注。换图后排除区域需重新核对。纠错和结算共用SQLite事务，按RGB像素、尺寸、玩法、补丁及对局编号绑定来源；换图片编码或重上传不能重分组增加样本。纠错不会写入名次events，也不会自动训练或替换模型。

```bash
python3 scripts/train_field_model.py \
  --annotations var/recognition_labels/*.json \
  --ocr-cache-dir var/recognition_ocr_cache \
  --output var/recognition_candidates --mode both
```

只有正框不够拟合other类，脚本会要求明确的排除区域/完整字段标注。训练和推理共用OCR推导上下文，重复OCR监督去重；过窄数字框只在解析值与人工值相同、范围及基线受限时关联，错误OCR不被当作负例。

本轮实际fit四个候选，均未启用：原受控和上下文修复候选的复用开发验证均为5正确/0错/5弃答；扩大开发并修复数值框对齐后的V4实际fit268行，验证2正确/0错/8弃答。恢复12条训练监督不等于新增12项识别正确。每模式至少20次验证回答、98%精确率与来源组门槛不降低。监督候选目录不放入`var/recognition_models/`；实验型Roman SVM仍未接入。

真实权重、原始输入、训练报告与快照在`training/round3/`。可不依赖原workspace路径，用打包的相同OCR记录复现V4实际拟合：

```bash
python3 scripts/reproduce_field_experiment.py --output var/reproduced-field-v4
```

本机复现的权重SHA256与原候选一致。该命令重现已消费开发实验，不是新的独立验证，也不会激活模型。

## 截图数据与评测复现

源码包不含用户上传、数据库、运行环境或来源截图。原开发工作区另有独立的`jcc-screenshots-v0.3.0.zip`（未随Git仓库提交）：52份原始图像字节、标签、来源链接、原视频时间戳、来源分组与hash，方便检查真实失败。视频原文件与未入选宣传材料不随数据包分发。

将截图数据包解压到项目的`var/`，得到`var/jcc-screenshot-dataset/`，然后：

```bash
python3 scripts/evaluate_expanded.py \
  --annotations var/jcc-screenshot-dataset/sealed-annotations.json \
  --baseline validation/round3-2026-11-12/baseline-source/vision_v020.py \
  --output var/reproduced-round3
```

原始FREEZE.json保留首次测试时的绝对路径与hash；换机器应核对相同相对源文件后重建本机冻结清单。模型/知识库不会因为复现而自动更新。旧轮静态图片也可使用fetch_validation_samples.py按source_image_url下载并校验；本轮视频帧优先使用独立数据包。

## 名次概率模型

已实现按玩法/补丁隔离的逻辑回归名次预测器、整局分组、校准和留出评估。目前没有真实对局数据，未训练，输出null。初始门槛为240场独立对局、每名次至少15场；每个可预测回合须在训练/校准/测试各至少5场。第一率Brier及八名次对数损失须同时胜过训练频率基线，否则不开启。

即使这些工程门槛通过，仍然只是历史行为下的观察性状态预测，不能证明某条阵容路线带来因果胜率提升，还需要真实对局的前瞻验证。

## 开发与文件

`app/vision.py`为识别编排，`hud.py`为视觉HUD，`card_title_reader.py`为卡名/场景/后缀；`field_model.py`为门控学习候选，`recognition_feedback.py`为标注协议；`engine.py`为资源匹配建议，`probability.py`为名次模型，`storage.py`负责来源与结果绑定。`app/data`保留官方来源与版本，`app/assets`为参考图，`training`和`validation`为可审查工件，`var`为本机数据。

API文档：http://127.0.0.1:8765/docs 。本轮127项Python测试通过；Node24语法和静态DOM引用通过；已执行真实截图HTTP流程。浏览器拖拽/点击未完成自动化验证。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m pytest -q
node --check app/static/app.js  # Node.js 18或更高
```
