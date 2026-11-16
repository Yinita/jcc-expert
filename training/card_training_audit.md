# 时间卡罗马数字分类器复核

复核日期：2026-11-11。只读检查 `outputs/jcc-expert/app/card_tier_model.py`、`scripts/train_card_tier.py`、`var/models/card-tier-candidate/{manifest,report}.json` 和五个权重文件；另对 development 标注文件计算 SHA-256。未读取任何 sealed_test_annotations、封存图片或封存标签，未改动识别器或模型。

结论：这是实际拟合并保存权重的候选实验，证据不足以启用自动卡片 ID 校正。不能将一例真实开发验证成功写成“真实准确率 100%”，也不能将 600 个字体渲染样本写成 600 张真实截图。

| 数据用途 | 真实标题裁片数 | 合成字形数 | 说明 |
| --- | ---: | ---: | --- |
| 拟合 | 3 | 480 | 真实 I 两例、II 一例；合计 483 行特征供每个二分类 SVM 拟合 |
| 开发验证 | 1 | 120 | 真实只有 I 一例；合成来自未用于拟合的 Liberation Serif 字体族 |
| 因同卡名跨组而剔除 | 2 | 0 | 两例“扩军令 I”，既不拟合也不计验证 |

真实罗马后缀标题共 6 例（3+1+2），不是独立对局数。3 个拟合裁片全部来自同一张 `orange_exp_01` 截图；验证裁片来自 `orange_exp_04`。五类中 III、IV、V 没有真实拟合或验证样本。

实际模型为 338 维 HOG、投影与几何特征，五个 one-vs-rest 线性 SVM，C=2；并非仅给规则改名。五个 XML 合计 254,627 字节，实测 SHA-256 均与 report 一致。development 标注 SHA-256 与 manifest 的 `training_annotations_sha256` 一致：`17f6232aab9499bf15baa7136d12506d523bddecd5fefa46801d1cc99ed4b9f1`。

真实拟合数据回代为 2 正确、1 弃答；唯一 II 例即使在拟合集中仍低于阈值而弃答。不同来源的真实开发验证为 1 正确 / 1，仅能说明该 I 裁片通过。合成验证为 72 / 120（60%），衡量的是理想裁好的字形 argmax 分类，绕过了完整标题分割及 0.65 的弃答门限，不能与真实端到端结果等同，更不是实机识别率。

划分控制：真实按来源组切分，训练为 `source_chuapp_291737`、验证为 `source_taptap_867251881297052929`；再剔除验证中出现的完整卡名，报告中的训练/验证卡名交集为空。合成训练为 DejaVu Sans、Liberation Sans，验证为 Liberation Serif；同字体增强不随机跨组。加载器发现 sealed_test 或 holdout 输入会在读取图片前拒绝。

残余风险：真实仅两个来源、一张训练截图和一张验证截图；验证类别只有 I，无法评价 I/II 混淆或其他等级。不同发布者仍可能共享游戏字体、界面素材，来源拆分不等于独立对局证明。合成数是有限字体、字号、描边和模糊扰动的渲染数量，不保证唯一字形，更不代表真实样本量。该验证属于开发过程，未提供新的独立盲测结果；分割规则、0.65 阈值和 SVM 分数均未经过统计校准。

未启用原因与保护：manifest 为 `approved_for_use:false`，报告为 `candidate_not_integrated`；模型所有返回路径均为 `safe_to_apply:false`，通过门限也只返回 `candidate_only`。confidence 是两类间隔的 `gap/(1+gap)` 启发分数，不是正确概率。当前真实覆盖不足、II 拟合例仍弃答且字体外推仅 60%，因此应保留为候选，不宣称改善了现有卡片识别准确率。
