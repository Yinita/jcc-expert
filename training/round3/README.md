# 识别训练闭环审计与受控候选实验

本轮只使用此前已经消费的 38 张截图、11 个来源组。它们全部属于开发材料；没有读取 round3 新封存测试的截图、标签或预测。这里的数字不能代表新测试准确率，也不代表获胜率提升。

## 错误分类

`error_audit.json` 逐项核查了旧版 optimized 默认识别输出与既有人工标签、区域框：

| 分类 | 数量 | 解释 |
|---|---:|---|
| 标量字段识别正确 | 25 | stage、gold、hp、level 四类 |
| 正确 OCR 文本已在人工区域内，但 state 弃答 | 27 | 可供后续字段定位改进；没有把所有 OCR 数字直接当成当前值 |
| 人工区域内没有匹配真值的 OCR 行 | 1 | 字段模型无法凭分类分数补造值 |
| 标量真值有标注，但缺可靠人工区域 | 7 | 不产生几何监督正例 |
| 商店槽弃答 | 13 | 不属于本字段分类器的四类标量范围 |

共有 25/38 张图的人工页型与实际推理上下文不一致；原先 11 个来源组中，9 个没有显式 `negative_boxes`。完整审阅且明确当前四个字段都不存在的菜单图，可另形成可靠 other 监督；未知字段不作为负例。

## 实现的改变

- `app/field_model.py` 的 v2 特征用同一个 OCR-only 上下文提取器完成训练和推理。人工 `screen_type` 只保留为诊断输入；改变此参数不会改变同一 OCR 的特征。特征版本更新后，v1 权重不会被生产加载器误用。
- `app/recognition_feedback.py` 提供正区域、明确负区域、明确不存在字段的验证与增量合并协议。负区域必须人工确认它不是当前 stage、gold、hp、level 中任何一类；只保存正区域不会自动创造 other 标签。未知不等于不存在。支持单独补充负区域，保留同一来源此前的部分校正；来源身份与 group 不可改变。截图授权、同源绑定和原子写入仍由调用方负责。
- 训练去除同一画面同一标量的重复 OCR 监督行；来自放大 HUD 和全图的重复识别不会被重复计数。other 只合并文本相同且框重叠的行。
- 校温按来源组等权；没有显式 other 校准行时不锐化温度、不选择上线阈值。训练/校准的来源门槛按实际贡献监督行的来源计。
- 不降低发布门槛：至少 2 个训练来源、1 个校准来源、2 个开发验证来源；至少 20 个验证回答、精确率目标 98%；共享模式还需自然/橘分别满足数量与精确率要求。候选模型继续关闭。

## 受控真训练

先在 `experiment_plan.json` 固定来源分组，再分别调用旧 trainer 与新 trainer 的真实 `DictVectorizer + LogisticRegression.fit`。两个实验使用相同旧图、OCR 行、人工标签和来源分组：25 图/4 来源训练，4 图/3 来源校准，9 图/4 来源开发验证。由于有无可靠标注及 OCR 可读性不同，不是每图都贡献监督行。

| 指标 | baseline v1 | enhanced v2 |
|---|---:|---:|
| 全分区监督行 | 374 | 371 |
| fit 训练行 | 258 | 255 |
| stage / gold / hp / level / other 训练行 | 14 / 9 / 2 / 13 / 220 | 11 / 9 / 2 / 13 / 220 |
| 开发验证正确 / 错误 / 弃答 | 5 / 0 / 5 | 5 / 0 / 5 |
| 已标注且存在的标量分母 | 10 | 10 |
| 覆盖率 | 50% | 50% |
| 回答精确率 | 5/5 | 5/5 |
| 明确不存在字段：正确不输出 / 误输出 | 12 / 0 | 12 / 0 |
| deployable | false | false |

验证中 stage 为 5 正确；gold 为 2 弃答、level 为 3 弃答、hp 没有已标注存在的验证值。自然模式为 3 正确/0 错误/4 弃答（7 个值），橘模式为 2/0/1（3 个值）。原始上下文与实际推理上下文的两种开发验证结果均相同。上述 12 个明确不存在字段单列，不混入 10 个存在字段分母，也不把弃答当准确。

增强版去掉 3 条 stage 重复监督，降低计数膨胀；开发验证覆盖没有提升。其四类标量的有效训练正例仍只来自 Sohu 一个来源组，金币、等级校准有效正例不足，门槛将相应字段阈值保留在不输出值。小样本校准 NLL 变化不是独立提升证据。`validated_modes=[]`，不存在可部署的本轮学习模型。

## 复现与文件

在工作区根目录运行：

```sh
python3 work/round3_training/run_experiment.py
python3 -m pytest outputs/jcc-expert/tests/test_field_model.py outputs/jcc-expert/tests/test_recognition_annotation_protocol.py -q
```

实验脚本只读取旧 `work/expanded_eval/development.json`、旧 `sealed.json` 以及对应旧 optimized OCR raw；旧 sealed 已在上一轮消费，本轮显式改为消费开发数据。脚本校验旧图片文件 SHA256 和 decoded image 去重，保存原 raw SHA256。新 round3 sealed 不在任何输入路径中。

- `error_audit.json`：旧 38 图逐项错误分类与来源覆盖。
- `annotations_consumed38.json`、`experiment_plan.json`：本轮输入与固定分组。
- `comparison.json`：完整并排结果、代码哈希、输入及 raw 哈希。
- `baseline/training_report.json`、`enhanced/training_report.json`：实际 fit 的类别权重、阈值、分组、每字段与每图结果。
- 两个目录中的 `.candidate.joblib` 和 `.candidate.json`：实际训练权重与元数据；不复制到生产模型目录。

增强候选权重 SHA256：`3dd26045ba8c998056e497bc0b332ca1ad4c6e90252f1a6c1b5878cd6ac577e1`。报告中的旧人工标签并未为这次实验重新改写。后续补充防回归测试后，针对 field_model 与负区域协议的测试为 **26 passed**；没有用测试代码制造截图准确率。

## 扩大开发实验 V3 与标注对齐修复 V4

随后仅追加根代理明确授权的 `work/round3_screens/nature/annotations.json` 中 7 张新 development 图。没有打开 round3 新 sealed。新增 3 个来源组中，两篇文章的 3 图进入 train，完整录像的 4 帧作为同一来源组进入 calibration；旧四个 validation 来源完全保留。因此共 45 图、14 来源组：28 图/6 组 train，8 图/4 组 calibration，9 图/4 组 validation。实际贡献监督行的来源组数量在模型报告另列，不把无可读标签的组算作拟合证据。

新增 OCR 缓存只调用当前生产 `_ocr`（含自动 small-UI pass），不调用 recognize、人工 profile 或字段模型，记录图片哈希、方法源码哈希、后端和耗时。旧 38 图继续使用原先冻结 OCR，旧输入哈希在训练后再次核验。两轮阈值均只使用固定 calibration 自动选择，未按 validation 结果调参。

V3 对齐审计发现：视频人工框围住数字，而 OCR 同一行会带阶段图标或后缀“级”。例如“息2-1”“3级”和金币“10”都可正确解析，却因数字框仅占 OCR 行面积 21–33%，被旧 35% 重叠规则丢弃。V4 的训练监督匹配保留以下约束：人工框至少 80% 被 OCR 包含、同一文字基线、OCR 框至多是人工框的 5 倍面积、4 倍宽和 2 倍高，且 OCR 解析值必须等于先前独立标注的真值。它恢复 12 条正例（11 校准、1 训练），不改变人工标签、原验证框匹配或发布门槛。OCR 错误值即使位于这些框内也不能变成 other。

| 指标 | 扩大 V3 | 标注对齐 V4 |
|---|---:|---:|
| 全分区监督行 | 390 | 402 |
| fit 训练行 | 267 | 268 |
| stage / gold / hp / level / other 训练行 | 14 / 10 / 2 / 15 / 226 | 15 / 10 / 2 / 15 / 226 |
| 复用开发验证正确 / 错误 / 弃答 | 2 / 0 / 8 | 2 / 0 / 8 |
| 明确不存在字段：正确不输出 / 误输出 | 12 / 0 | 12 / 0 |
| 覆盖率 | 20% | 20% |
| 回答精确率（样本极少） | 2/2 | 2/2 |
| deployable / validated_modes | false / [] | false / [] |

V3、V4 仅输出等级字段：两个等级正确，另外一个等级与五个阶段、两个金币均弃答。V3 等级阈值 .98，V4 .93；这两个值分别由固定 calibration 按同一精确率约束选择，阶段/金币/血量阈值均保留为不输出值。覆盖低于原受控实验的 50%，没有可宣称的总识别提升。

`expanded_v4/calibration_alignment_diagnostic.json` 另保留纯校准诊断：预览阈值 .5 时，8 个有人工真值的预测里，5 个值正确但原严格验证框规则拒绝较宽的 OCR 行。这是后续统一字段值评测与定位框评测的开发问题，未修改本轮指标。血量正例仍仅来自 Sohu 一个训练来源，需要更多独立开发来源与可靠 other 负例。此阶段 validation 已被多个候选反复查看，只是复用开发验证，不能充当独立最终证据。

复现命令（V3/V4 各保留自己的 trainer snapshot，避免覆盖旧实验）：

```sh
python3 work/round3_training/run_expanded_v3.py --experiment expanded_v3
python3 work/round3_training/run_expanded_v3.py --experiment expanded_v4
```

- `expanded_v3/model/training_report.json`、`expanded_v4/model/training_report.json`：新增开发实验。
- `expanded_v4/comparison.json`：四个候选的并排数字。
- `expanded_v3/ocr_cache/`：7 图当前生产 OCR 原文，仅 work 使用。
- `expanded_v4/model/3561bda113759e5137e2ffb9.candidate.joblib`：最终训练候选权重，SHA256 `2eface67c37fb60ef4943701c18a610ee6c99147cae8c71b236ea7f943bff2d0`。

所有候选均未复制到生产模型目录，未开启；它们是 OCR 字段分类器，不是胜率模型。本轮没有训练获胜率模型，也没有实战获胜提升证据。
