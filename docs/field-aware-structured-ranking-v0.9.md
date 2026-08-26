# 字段感知迟交互、API 组合约束解码与编译反馈校准

## 1. 文档定位

本文档说明 BSPForge v0.9 的操作级语义排序方案。系统要解决的问题是：给定 SDK Migration IR 和一个规范化设备操作，例如 `uart.write`，在同一 SDK 的函数实体中找出适合生成 RTOS 绑定代码的 API，并判断该结果是否足以自动接受。

该方案不生成任意源码，不以编译通过代替功能正确，也不把神经模型作为唯一裁决者。模型负责补充跨命名风格的语义证据；静态契约、API 组合约束、编译与上板验证分别承担不同层次的保证。

## 2. 输入与输出

### 2.1 输入

每个查询由以下字段构成：

- `sdk_id`：SDK 标识；
- `capability`：`clock`、`interrupt`、`uart`、`gpio` 或 `timer`；
- `operation`：例如 `configure`、`write`、`read`、`start`；
- `query_text`：与厂商无关的操作契约描述；
- `candidate_text`：由函数 IR 序列化得到的 `symbol`、`signature`、`calls`、`file`、`includes` 五个字段；
- 静态特征：操作词、能力词、签名提示、调用上下文、API 层级、解析器置信度和冲突证据等。

候选始终使用 IR 中稳定的 `entity_id` 关联，符号名只用于展示和证据计算。

### 2.2 输出

每个规范化操作输出：

- 排序后的候选及静态、语义、约束、编译反馈分项分数；
- `selected_entity_id` 与 `selected_symbol`；
- 第一名和次优不同符号之间的 `confidence_margin`；
- 自动接受或弃权状态；
- 约束证据和编译反馈状态。

运行结束后，编译反馈写入 `08b-semantic-compile-feedback.json`。该文件可作为同一 SDK 后续运行的校准输入。

## 3. 高质量分级真值

### 3.1 四级标签

训练 SDK 不再使用“命中任一操作词即为正例”的二元弱标签，而采用可审计的四级标签：

| 标签 | 含义 | 最低证据 |
| ---: | --- | --- |
| 3 | 强相关、适合作为迁移绑定候选 | 操作词、能力词、API 层级和调用契约同时成立 |
| 2 | 相关、可作为绑定候选 | 操作词与能力词成立，且层级或契约至少一项成立 |
| 1 | 弱相关、只用于补充召回 | 操作词成立，但能力或契约证据不完整 |
| 0 | 不相关或冲突 | 反义操作、语义冲突、反向 OS 适配、测试代码或真正私有 API |

每条标签同时保存 `label_evidence` 和 `label_confidence`。例如，`exact-operation-token`、`signature-contract` 和 `hal-layer` 是正证据，`reject:opposite-action` 是拒绝证据。

公共头文件中的 `static inline *_internal` 可能是宏的实际可调用实现，不能仅凭 `internal` 字样判为私有；而安全服务内部入口的 `_impl_s`、测试目录和由 SDK 反向调用 RTOS 的适配层仍会被拒绝。

### 3.2 数据隔离

训练数据包含 22 套 SDK、20 个独立性组。开发集按 SDK 上游或厂商分组，不允许同一独立性组跨训练和开发。K210、STM32F103 和 PSoC E84 三套实际板卡 SDK 只使用源码审计真值进行外部测试，不进入训练、困难负例挖掘或参数选择。

`scripts/audit_graded_operation_truth.py` 检查标签分布、证据分布、强正例覆盖、外部标签来源和独立性组泄漏。正式论文前仍应由第二名标注者独立复核板卡真值，并报告 Cohen's kappa 或 Krippendorff's alpha。

## 4. 字段感知迟交互

### 4.1 基础模型

基础编码器为固定提交版本的 `sentence-transformers/all-MiniLM-L6-v2`。其规模约 22.7M 参数，普通 CPU 可运行。系统直接读取 Transformer token embedding，不把整个函数压缩成单个句向量后再比较。

### 4.2 字段专用查询

不同 IR 字段承载的信息不同，因此每个字段使用独立查询：

- `symbol`：强化能力同义词和操作别名，抑制通用 `init/get/set` 的支配；
- `signature`：加入操作契约和参数、返回值提示；
- `calls`：强调被调函数中的能力和动作线索；
- `file`：强调驱动、HAL、外设和能力目录；
- `includes`：强调头文件和能力归属。

例如 `uart.write` 的符号查询包含 `uart/uarths/serial/usart/sci` 与 `write/send/put/transmit`，签名查询还包含“发送字节”和 `buffer/size/len` 等契约提示。

### 4.3 Token 级 MaxSim

设字段查询 token 向量为 `Q_f={q_i}`，候选字段 token 向量为 `D_f={d_j}`。字段分数为：

```text
s_f(q, d) = mean_i max_j cosine(q_i, d_j)
```

空字段不参与该候选的权重归一化。五个字段的初始权重为：

```text
symbol 0.34, signature 0.28, calls 0.18, file 0.12, includes 0.08
```

系统同时保存 `field-symbol-maxsim` 等五个分项特征和聚合后的 `field-late-interaction`。分项特征可由 LambdaMART 在训练 SDK 上重新学习组合，既能展示模型调优工作，也能做字段消融。

### 4.4 与 ColBERT 的关系和区别

本方案采用了 ColBERT 已公开的 token 级迟交互和 MaxSim 思想，必须在论文中引用 ColBERT/ColBERTv2。BSPForge 的工作不是声称发明 MaxSim，而是把它改造成 Migration IR 的字段专用查询、非空字段归一化和操作契约特征，并把结果接入 API 组合及编译闭环。

## 5. API 组合约束解码

### 5.1 为什么不能逐操作独立选择

独立排序可能为 `timer.initialize` 选择通用定时器 API，却为 `timer.start` 选择 PWM、OS tick 或另一个外设族。每个函数单看都包含 `timer/start/init`，组合起来却无法共享句柄、配置结构或构建依赖。

### 5.2 一元契约约束

候选首先经过与厂商无关的准入调整：

- 缺少能力、控制器或 HAL 证据时降分；
- 缺少操作、参数化启停或签名契约时降分；
- 反义操作、语义冲突、反向 OS 适配、私有 API 和测试示例降分；
- `deinit` 不可作为初始化，PWM 启停不可直接替代通用硬件定时器启停。

该层是软约束而不是永久删除，以免 IR 不完整时把唯一可行候选提前剪掉。

### 5.3 成对兼容规则

同一能力内两个操作候选的兼容分数由以下证据组成：

| 规则 | 作用 |
| --- | --- |
| `parameterized-complement` | 同一带布尔/状态参数的函数可同时实现 enable/disable 或 start/stop |
| `unjustified-entity-reuse` | 无参数化证据时，禁止一个实体覆盖多个不同操作 |
| `shared-api-family` | 奖励共享 `HAL_TIM`、`sysctl`、`mtb_hal` 等 API 族 |
| `shared-source-directory` | 奖励来自同一驱动实现目录 |
| `shared-signature-type` | 奖励共享句柄、配置或回调类型 |
| `shared-hal-layer` | 奖励处于相同 HAL 抽象层 |

### 5.4 组合目标

设操作集合为 `O`，每个操作的候选为 `C_o`，一元分数为 `u(o,c)`，契约调整为 `a(o,c)`，成对兼容为 `p(c_i,c_j)`：

```text
y* = argmax_y Σ_o [u(o,y_o)+a(o,y_o)]
             + λ Σ_(i<j) p(y_i,y_j)
```

离线评测使用宽度 64、每操作 Top-10 的 beam search。运行时为控制延迟采用按规范化操作顺序的约束贪心，并把所有调整写入候选证据。`λ` 只能在开发 SDK 上选择。

## 6. 编译反馈校准

### 6.1 反馈状态

`create_compile_feedback()` 把最终构建结果映射到已选择绑定：

- `compiled-linked-and-artifact-verified`：整个工程编译、链接和固件检查通过，校准分数 1.0；
- `diagnostic-implicated`：诊断直接提到所选符号，分数 0.0；
- `build-failed-unattributed`：构建失败但不能归因到该符号，分数 0.35；
- `not-observed` 或 `abstained`：没有可靠观测，分数 0.5。

历史反馈可按以下方式与当前排序分数融合：

```text
score' = (1 - beta) * ranking_score + beta * compile_feedback_score
```

反馈键为 `(capability, operation, entity_id)`，只应在 SDK 摘要和工具链条件相容时复用。

### 6.2 保证边界

编译通过只能证明声明、类型、依赖、链接和固件结构在当前配置下成立，不能证明寄存器设置正确、中断触发正确或真实外设行为正确。因此反馈文件将 `semantic_correctness_proven` 固定为 `false`。运行语义必须由仿真或上板测试另行证明。

### 6.3 K210 编译闭环实例

最终配置 `examples/k210-rtthread/project-semantic.json` 对 19 个规范化操作生成绑定。第一次链接报告 `sys_register_getchar`、`sys_register_putchar`、`sys_getchar` 和 `sys_putchar` 未定义；Build Diagnoser 把诊断映射为提供者约束，并从 IR 中选择 `lib/bsp/syscalls.c` 加入闭包。第二次构建成功，停止原因为 `build-succeeded`。

产物验证得到 668,008 字节的 `rtthread.elf` 和 471,992 字节的 `rtthread.bin`，ELF Machine 为 RISC-V，且 8 个预期的 BSPForge 设备与验证符号全部参与链接。`08b-semantic-compile-feedback.json` 因而记录 19 条 `compiled-linked-and-artifact-verified`，但每条记录仍保持 `semantic_correctness_proven: false`。该实例说明编译反馈适合发现依赖闭包问题和淘汰不可链接候选，不能单独区分名称相近但方向相反的操作；后者仍需真值审计、组合约束和上板行为断言。

## 7. 选择性自动接受

自动接受置信度组合以下证据：排序间隔、静态/迟交互首位一致性、契约准入状态和首位分数。阈值仅在开发集上选择，目标选择性精度为 0.95，并在外部集原样使用。

如果开发集不存在满足目标的阈值，报告 `no-feasible-threshold`；如果外部集低于 0.95，系统必须降低自动覆盖率或全部转人工，不允许事后移动阈值。论文应同时报告选择性精度和覆盖率。

当前实现是经验性风险校准，不等同于有有限样本保证的 conformal risk control。后续若使用 conformal 方法，应单独划出校准集并明确交换性假设。

## 8. 实现文件

| 文件 | 职责 |
| --- | --- |
| `bspforge/operation_ranking.py` | 操作本体、静态特征、归一化和四级真值规则 |
| `bspforge/operation_dataset.py` | 训练/开发/外部数据构建及隔离 |
| `bspforge/field_late_interaction.py` | 字段专用查询、token MaxSim 和五字段特征 |
| `bspforge/operation_constraints.py` | 契约准入、API 族兼容与 beam 解码 |
| `bspforge/compile_feedback.py` | 构建结果到候选绑定的校准反馈 |
| `bspforge/semantic_adapter.py` | MiniLM、查询适配器和字段迟交互运行时封装 |
| `bspforge/semantic_resolver/resolver.py` | 分数融合、运行时组合约束、历史反馈和弃权 |
| `scripts/audit_graded_operation_truth.py` | 分级真值与数据泄漏审计 |
| `scripts/add_field_late_interaction_scores.py` | 离线生成字段级特征 |
| `scripts/evaluate_structured_operation_ranker.py` | 开发集选参、组合解码和选择性评测 |

## 9. 实验协议

主表至少报告 P@1、Recall@5、MRR、MAP、nDCG@10、选择性精度及覆盖率。消融顺序为：

1. BM25；
2. 静态操作规则；
3. 整句 MiniLM；
4. 字段迟交互；
5. 静态与字段融合；
6. 加入契约准入；
7. 加入 API 组合约束；
8. 加入编译反馈校准；
9. 完整系统及选择性接受。

指标必须按 SDK 独立性组做 bootstrap 或置换检验，不能把同一 SDK 内数千个函数候选当作独立样本。三块板卡的排序结果在此前开发中已多次查看，因此当前属于探索性外部评估；正式投稿应冻结代码和参数后增加未查看 SDK 做确认性测试。

### 9.1 v0.9 探索性结果

| 方法 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 静态规则 | 0.640 | 0.679 | 0.632 | 0.680 |
| 字段迟交互 | 0.660 | 0.772 | 0.668 | 0.728 |
| 静态 0.25 + 字段 0.75 | 0.780 | **0.772** | **0.723** | **0.767** |
| 静态 0.50 + 字段 0.50 | **0.800** | 0.744 | 0.712 | 0.759 |
| 分级真值 LambdaMART | 0.220 | 0.550 | 0.364 | 0.431 |
| 开发集选择的组合约束 | 0.600 | 0.675 | 0.633 | 0.680 |

字段迟交互相对静态方法提高了跨厂商召回和整体排序，P@1 达到既定 0.80 下限。Recall@5、MAP 和 nDCG@10 仍低于 0.90、0.80 和 0.80 目标。组合约束当前只带来很小 MAP 变化并降低 P@1，说明开发真值尚不足以稳定选择约束权重。

保守选择性校准在开发集只接受 1/86 个操作，外部集接受 0/50。当前不能声称自动接受部分达到 0.95 且具有实际覆盖；工程默认应对这些候选弃权。自动真值训练的 LambdaMART 明显退化，也必须作为负向结果报告。

## 10. 复现入口

```bash
conda activate AIoT-v1.0
cd /home/whk/RTT-porting/bspforge

python scripts/build_operation_dataset.py \
  --output experiments/generated/operation-ranking-dataset-v0.9.json

python scripts/audit_graded_operation_truth.py \
  --dataset experiments/generated/operation-ranking-dataset-v0.9.json \
  --output experiments/generated/operation-graded-truth-audit-v0.9.json

python scripts/add_field_late_interaction_scores.py \
  --dataset experiments/generated/operation-ranking-dataset-v0.9.json \
  --output experiments/generated/operation-ranking-dataset-v0.9-field-all.json \
  --roles train external-test

python scripts/evaluate_structured_operation_ranker.py \
  --dataset experiments/generated/operation-ranking-dataset-v0.9-field-all.json \
  --split experiments/operation-ranking/development-split.json \
  --output experiments/generated/operation-ranking-results-v0.9-structured.json
```

大体积候选数据由固定清单和脚本重建，不提交 Git；紧凑审计结果、最终指标、模型哈希和固定划分应提交，以便论文复核。
