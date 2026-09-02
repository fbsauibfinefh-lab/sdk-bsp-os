# 操作条件效果切片与多视图语义排序 v0.3

## 1. 研究目的与边界

v0.3 针对 v0.2 在同一 API 家族动作混淆、长函数无关代码稀释和小样本过拟合三个问题继续优化。输入仍是 SDK Migration IR 和 19 个能力操作，输出仍是每个 `sdk_id + operation_id` 下的函数候选排序。本轮不改变 SDK Ingestor、Closure Solver、Build Diagnoser 和 OS Backend，也不处理 `no_public_api` 的宏、配置项、回调槽和 API 序列目标。

H02 中 `label > 0` 表示已标注正函数，`label == 0` 表示未标注函数而非确定负例。训练只建立同查询内正函数优先于采样未标注函数的偏好。281 个具有可达函数正例的训练角色查询按 18 个独立厂商或上游来源做五折外层验证；50 个三板卡查询只作外部诊断，不参与参数、配置或权重选择。

## 2. 完整数据流

1. 从 `hardware-effect-h02-v0.1.json` 读取查询、候选、分级标签、源码角色、签名、调用图和寄存器效果特征。
2. 从 v0.2 缓存读取 19 个操作查询和 22,932 个唯一函数实体的冻结 Jina 代码向量。
3. 根据当前操作对每个函数体执行效果语句选择，生成“操作条件化局部视图”。
4. 使用同一冻结 Jina 模型编码 29,904 个查询-候选局部视图，得到 768 维 `float16` 向量。
5. 分别尝试多视图神经偏好排序和分级 LambdaMART。所有外层测试厂商只用于一次 OOF 评测。
6. 由全代码零样本、q4 结构通道和硬件效果图三个无标签通道构造 Top-K 并集。
7. 对短名单构造查询-候选联合文本并冻结编码，再训练轻量联合重排头。
8. 输出每种固定配置、严格嵌套选择、外部板卡诊断、配对 bootstrap 和逐查询排序记录。

## 3. 操作条件化效果切片

### 3.1 输入

切片器读取当前 `operation_id`、候选符号、签名、归一化函数体、源码角色、跨过程效果路径、寄存器标识和调用目标。它不读取候选标签。

### 3.2 语句级打分

函数体先按语句边界拆分。每条语句的保留分数由以下证据相加：

- 当前能力及动作词，例如 UART 的 send/receive、GPIO 的 set/get、timer 的 start/stop；
- 寄存器宏、结构体寄存器字段和 MMIO 标识；
- 已恢复效果路径上的调用目标；
- 赋值、位运算、读写和返回值证据；
- 与高分语句相邻的上下文语句。

排序后最多保留 10 条核心语句，并加入相邻上下文。最终局部文档包含符号、签名、源码角色、效果路径、寄存器 ID 和相关代码切片。该方法让同一个候选面对 `uart.write` 与 `uart.read` 时形成不同输入，同时控制长函数中的无关中间件逻辑。

### 3.3 缓存

`scripts/cache_multiview_effect_embeddings.py` 使用冻结的 `jina-embeddings-v2-base-code`、192 token 和 32 批大小编码全部局部视图。缓存共 29,904 条、768 维，IR 实体缺失为 0，首次 CPU 编码耗时 5,649.9 秒。向量文件可由元数据、固定模型提交和脚本重建，因此不提交 Git。

## 4. 多视图证据

每个候选形成四个互补通道：

| 通道 | 内容 | 主要目的 |
| --- | --- | --- |
| 全代码语义 | 操作查询与完整候选文档余弦 | 保留 API 名称、签名和完整实现语境 |
| 局部效果语义 | 操作查询与效果切片余弦 | 突出寄存器效果和当前动作相关语句 |
| 硬件效果图 | 22 维直接/传播效果特征 | 提供跨过程寄存器路径与距离证据 |
| 结构特征 | 19 个数值化 IR/契约特征 | 表示源码角色、层级、签名和通用操作适配度 |

此外保留动作硬约束。对修改状态的操作，如果候选只是 `is/has/status/check/ready/running` 查询且没有直接写、位运算或 MMIO 证据，则施加强惩罚；对读取操作则抑制明显修改状态的候选。硬约束不根据 SDK 真值拟合。

## 5. 尝试一：多视图神经偏好排序

### 5.1 模型

模型包含秩受限查询适配、局部视图适配、22 维图分支、19 维结构分支、操作门控和四通道融合头，共 25,196 个可训练参数。冻结 Jina 主干不参与训练。

### 5.2 训练变化

本轮系统比较以下因素：

- 普通 PU 偏好对与同 API 家族难负例；
- 正例分级和标注置信度加权；
- 12、24、36 个 epoch；
- listwise 权重 0、0.02 和 0.05；
- 六组固定证据融合配方；
- 仅在外折训练 SDK 内部选择配置和配方。

### 5.3 结果与结论

| 配置 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 12 轮同族难负例 | 0.427 | 0.564 | 0.483 | 0.557 |
| 24 轮同族难负例 | 0.399 | 0.545 | 0.465 | 0.537 |
| 36 轮同族难负例 | 0.381 | 0.554 | 0.465 | 0.534 |
| 24 轮、listwise 0.05 | **0.434** | **0.621** | **0.525** | **0.593** |
| 严格嵌套选择 | 0.395 | 0.572 | 0.483 | 0.559 |

严格嵌套结果相对 v0.2 四项均下降，配对 bootstrap 95% 区间均小于 0。训练损失在 24/36 轮继续下降，但未见厂商指标退化，说明当前样本规模下端到端学习四通道融合产生过拟合。listwise 0.05 能缓解但不能逆转。因此该路线保留为负向消融，不进入推荐方法。

## 6. 尝试二：分级多视图 LambdaMART

### 6.1 模型与特征

LambdaMART 直接使用 H02 的 0/1/2/3 分级相关性。输入包括四类多视图分数、候选全部数值特征、动作约束、状态查询标记和 19 维操作 one-hot。模型学习非线性阈值和特征交互，预测后再次应用固定动作硬约束。

### 6.2 容量与正则搜索

第一轮比较 9、15、25 叶模型，结果显示模型越大越容易过拟合。第二轮围绕该观察继续比较：

- 5 叶深度 3 的 tiny 模型；
- 7 叶、较强 L1/L2 的 small-reg；
- 原 9 叶 small；
- 9 叶、特征与样本子采样的 small-bagged；
- 13 叶、较强正则的 medium-reg。

每个外折在训练厂商中再留出独立来源选择模型。报告纯内层最优，也报告内层目标差不超过 0.01 时优先低复杂度的保守选择；两者都不读取外折标签。

### 6.3 结果

| 配置 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| tree-tiny | 0.648 | 0.741 | 0.676 | 0.740 |
| tree-small-reg | 0.644 | 0.749 | 0.680 | 0.741 |
| tree-small | 0.644 | 0.752 | 0.680 | 0.739 |
| tree-small-bagged | 0.648 | 0.757 | **0.685** | **0.747** |
| tree-medium-reg | 0.633 | **0.776** | 0.678 | 0.742 |
| 严格嵌套选择 | **0.651** | 0.748 | 0.681 | 0.743 |
| 嵌套简单模型优先 | 0.648 | 0.747 | 0.678 | 0.741 |

相对 v0.2 的 0.495/0.653/0.565/0.639，严格嵌套方案分别提高 0.157、0.095、0.117 和 0.103。固定 small-bagged 是探索性最优配置，不能代替一次新的确认集；正式论文主表优先使用严格嵌套结果。

四项提升的查询级配对 bootstrap 95% 区间分别为 P@1 `[0.093, 0.224]`、Recall@5 `[0.048, 0.143]`、MAP `[0.075, 0.159]` 和 nDCG@10 `[0.066, 0.141]`，均不跨 0。该统计只支持“相对当前 v0.2 基线有增量”，不支持“已达到工程可靠性阈值”。

三板卡 50 组诊断中，全训练集内选出的 small-bagged 为 0.620/0.836/0.667/0.754。该结果没有进入任何配置选择，也不能视为干净确认实验。

### 6.4 固定配置通道消融

为避免把树容量差异误认为新视图贡献，通道消融固定使用同一 small-bagged 参数和相同五折划分：

| 输入通道 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 完整代码 | 0.399 | 0.577 | 0.478 | 0.551 |
| 完整代码 + 局部效果切片 | 0.388 | 0.589 | 0.478 | 0.548 |
| 再加硬件效果图 | 0.520 | 0.708 | 0.605 | 0.677 |
| 再加全部结构契约 | **0.641** | **0.769** | **0.683** | **0.745** |

当前局部切片相对完整代码的四项差异为 -0.011/+0.012/-0.000/-0.003，配对区间均跨 0，不能主张切片本身有效。硬件效果图带来 0.132/0.120/0.127/0.128 的提升，全部区间不跨 0；结构契约进一步带来 0.121/0.061/0.078/0.068 的提升，区间也均不跨 0。

因此，本轮树模型的已验证贡献来自硬件效果图、结构契约和适合小数据的分级非线性交互。操作条件切片是已实现但尚未被独立验证的候选机制；只有联合编码或后续 AST/数据流切片取得稳定增益后，才能把它升级为论文核心方法。

### 6.5 特征重要性边界

全训练集最终 small-bagged 模型按 gain 排名前八的特征为能力基线、完整代码余弦、局部代码余弦、符号特异性、调用者入度、多通道 RRF、公共 API 边界和源码角色。完整表已写入 `final_model.feature_importance`。

重要性只能说明模型使用了某项特征，不能证明该特征提供独立增益。局部代码余弦的重要性较高，但固定通道消融没有显著提升，说明它可能与完整代码或结构特征发生替代。论文的贡献判断以通道消融和配对区间为主，特征重要性只用于解释模型决策。

## 7. 尝试三：Top-K 查询-候选联合编码

### 7.1 无标签短名单

短名单取三个运行时可用通道的并集：完整代码零样本、q4 结构排序和硬件效果图启发式。每通道取 15 个时，平均并集大小为 31.673；281 个训练查询中 97.5% 至少包含一个正符号，全部已标注正符号召回率为 0.916。50 个板卡查询的短名单正例覆盖为 1.0。

短名单统计会读取标签计算上限，但短名单选择函数本身不接收标签，缓存键也只由查询、候选 IR 与无标签通道得分决定。

### 7.2 联合输入与轻量重排

联合文本把操作查询放在效果切片候选之前，使冻结编码器在同一次前向中看到二者。重排头包含 768->32 联合分支、操作 FiLM 和 10 个标量证据，训练同族难负例、12/24/36 轮和两个 listwise 权重。联合分支与标量分支比例只在外折训练厂商内部选择。

### 7.3 结果

| 配置 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 12 轮 pairwise | 0.448 | 0.648 | 0.527 | 0.602 |
| 24 轮 pairwise | 0.423 | 0.641 | 0.518 | 0.597 |
| 36 轮 pairwise | 0.413 | 0.644 | 0.518 | 0.599 |
| 24 轮、listwise 0.05 | **0.488** | **0.674** | **0.562** | **0.638** |
| 严格嵌套选择 | 0.431 | 0.628 | 0.520 | 0.602 |

所有内层验证均选择联合分支权重的下限 0.5；联合权重提高到 0.7/0.85/1.0 时持续退化。严格嵌套相对 v0.2 的差异为 -0.064/-0.026/-0.044/-0.038，其中 MAP 区间完全小于 0，其余区间跨 0。三板卡诊断为 0.400/0.677/0.491/0.595。

该结果说明把查询和候选拼接后交给冻结的通用嵌入模型，不等同于经过排序任务微调的交叉编码器。26,002 参数重排头仍主要依赖标量证据，联合向量没有学到稳定的动作细分。因此该路线保留为负向消融；已生成的 10,439 条联合缓存可以复用于后续真正的小型 cross-encoder/LoRA 实验。

## 8. 当前推荐方法

在取得新的未查看确认 SDK 前，推荐把“寄存器效果锚定的多视图证据 + 分级 LambdaMART + 动作硬约束”作为 v0.3 候选方法。它的核心不是树模型本身，而是将函数实现、寄存器效果路径、IR 层级和操作契约组织为可复现证据，并在厂商独立分组下学习非线性交互。当前操作条件切片继续作为待改进视图，不单独列为已证实创新点。

多视图神经融合和冻结联合编码均作为负向消融，不与推荐方法并列写成多个论文创新点。q4 仍是当前工程 Resolver 默认路径；v0.3 在新增确认集稳定前不替换固件生成默认方法。

## 9. 尚未实施但预期有效的改进

以下路线本轮没有完成，按预期收益和工程代价排序：

1. **真实 AST/CFG/PDG 反向切片**：当前语句选择主要依赖词法、寄存器和调用路径。基于 def-use、控制依赖和指针别名的跨过程切片能减少长函数噪声，是最优先升级。
2. **字段级多向量迟交互**：分别缓存符号、签名、路径、寄存器和代码语句向量，使用 MaxSim 或可学习字段门控，避免单个 768 维向量压缩全部证据。
3. **局部异构图网络**：只在 Top-K 子图上运行轻量 R-GCN/GAT，节点包括函数、宏、寄存器、结构体字段和构建目标，边包括调用、展开、读写和定义。
4. **小型代码交叉编码器微调**：使用开源小型 CodeBERT、GraphCodeBERT 或 CodeT5 编码器，在短名单上做 LoRA/adapter 排序；需要独立确认 SDK 和多随机种子控制过拟合。
5. **层级能力-动作分解**：先识别 UART/GPIO/timer 等能力，再在能力内区分 initialize/read/write/start/stop，以降低跨能力无关候选和同族动作混淆。
6. **操作专家与共享主干**：共享代码表示，每个动作仅训练极小专家头；适合数据增大后解决不同操作证据尺度冲突。
7. **编译与类型可行性反馈**：把签名可封装性、必需上下文、链接可达性和最小调用探针作为后排序约束，而不是只使用文本和图证据。
8. **难负例主动复核**：优先人工复核模型高分但 H02 为 0、H02 正例未进入 Top-5 的候选并集。该步骤改善真值完整性，但必须与测试集冻结和确认集隔离。
9. **多随机种子与一次性确认集**：对最终配置至少运行 5 个种子，并在从未参与开发的新厂商 SDK 上只评测一次。该步骤不提高开发分数，但决定论文结论可信度。
10. **非单函数目标扩展**：在用户当前边界放开后，将宏、配置项、回调槽和 API 序列统一建模为可排序实体；不得把它们混入当前函数级分母。

## 10. 复现入口

| 文件 | 职责 |
| --- | --- |
| `bspforge/multiview_effect_encoder.py` | 操作条件效果切片、多视图与联合向量缓存接口 |
| `bspforge/multiview_effect_ranker.py` | 多视图神经排序与动作硬约束 |
| `bspforge/joint_shortlist.py` | 三通道无标签 Top-K 并集 |
| `bspforge/joint_pair_ranker.py` | 联合编码轻量重排头 |
| `scripts/cache_multiview_effect_embeddings.py` | 缓存操作条件局部向量 |
| `scripts/evaluate_multiview_effect_ranker.py` | 神经偏好、轮次、listwise 与配方嵌套评测 |
| `scripts/evaluate_multiview_lambdamart.py` | 分级树模型、正则和复杂度嵌套评测 |
| `scripts/evaluate_multiview_channel_ablations.py` | 固定树参数的完整代码、局部切片、硬件图和结构契约通道消融 |
| `scripts/analyze_joint_shortlist.py` | 短名单候选上限分析 |
| `scripts/cache_joint_pair_embeddings.py` | 缓存 Top-K 联合编码 |
| `scripts/evaluate_joint_pair_ranker.py` | 联合重排与嵌套校准 |

机器可读结果位于 `experiments/operation-ranking/results-*-h02-v0.3*.json`。所有主指标均以 281 个 OOF 查询为分母，不报告覆盖率，也不因低分删除查询。

在仓库根目录和 `AIoT-v1.0` 环境中运行：

```bash
python scripts/cache_multiview_effect_embeddings.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --manifest experiments/operation-ranking/manifest.json \
  --ir-root workspace/operation-ir \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --model /home/whk/RTT-porting/models/jina-embeddings-v2-base-code \
  --output-metadata experiments/generated/jina-multiview-effect-h02-v0.3.json \
  --output-vectors experiments/generated/jina-multiview-effect-h02-v0.3.npz

python scripts/evaluate_multiview_lambdamart.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --focused-metadata experiments/generated/jina-multiview-effect-h02-v0.3.json \
  --focused-vectors experiments/generated/jina-multiview-effect-h02-v0.3.npz \
  --v02-results experiments/operation-ranking/results-pretrained-effect-h02-v0.2.json \
  --output experiments/operation-ranking/results-multiview-lambdamart-h02-v0.3-tuned.json \
  --output-model models/multiview-lambdamart-h02-v0.3-tuned.txt

python scripts/evaluate_multiview_channel_ablations.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --focused-metadata experiments/generated/jina-multiview-effect-h02-v0.3.json \
  --focused-vectors experiments/generated/jina-multiview-effect-h02-v0.3.npz \
  --output experiments/operation-ranking/results-multiview-channel-ablations-h02-v0.3.json

python scripts/cache_joint_pair_embeddings.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --model /home/whk/RTT-porting/models/jina-embeddings-v2-base-code \
  --output-metadata experiments/generated/jina-joint-pair-h02-v0.3.json \
  --output-vectors experiments/generated/jina-joint-pair-h02-v0.3.npz \
  --per-channel 15 --max-length 256

python scripts/evaluate_joint_pair_ranker.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --focused-metadata experiments/generated/jina-multiview-effect-h02-v0.3.json \
  --focused-vectors experiments/generated/jina-multiview-effect-h02-v0.3.npz \
  --joint-metadata experiments/generated/jina-joint-pair-h02-v0.3.json \
  --joint-vectors experiments/generated/jina-joint-pair-h02-v0.3.npz \
  --v02-results experiments/operation-ranking/results-pretrained-effect-h02-v0.2.json \
  --output experiments/operation-ranking/results-joint-pair-h02-v0.3.json \
  --output-model models/joint-pair-h02-v0.3.pt
```
