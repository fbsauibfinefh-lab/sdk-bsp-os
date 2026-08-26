# 论文核心方法与整体工作梳理（v1.0）

## 1. 一句话主张

本文提出一种面向异构芯片 SDK 的**层级约束字段迟交互与 API 家族覆盖解码方法**：从 SDK Migration IR 中恢复函数的字段语义、源码抽象层和操作契约，在保持首位精度的同时补齐同一功能家族中的可迁移接口，并将结果送入 RTOS 原生后端、构建闭包和自动诊断闭环，生成可编译固件。

论文应始终围绕这句话展开，不要把所有工程模块写成相互独立的创新点。

## 2. 要解决的问题

输入 SDK 中同时存在公共 HAL、低层 PDL/LL、私有实现、RTOS 反向适配、示例、测试和第三方中间件。名称相似不代表满足同一迁移操作，例如：

- 基础硬件定时器与 PWM、Encoder、HallSensor、软件定时器名称相近；
- 系统中断控制器 API 与 SDIO、UART 等外设中断 API 都包含 `irq/register`；
- `set_enabled(bool)` 可同时承担 enable/disable 或 start/stop；
- 同一操作可能存在阻塞、中断、DMA、公共内联或不同驱动层实现；
- 正确 API 可能不在普通语义模型的 Top5 中，但位于高置信 API 的同一功能家族。

因此本文不是普通的“文本到函数语义搜索”，而是带有 SDK 层级、设备契约和组合覆盖约束的代码检索问题。

## 3. 输入与输出

### 3.1 输入

SDK Ingestor 将源码、头文件和构建资产转换为 Migration IR。排序阶段使用以下函数字段：

| 字段 | 内容 |
| --- | --- |
| `symbol` | 函数符号及其标识符子词 |
| `signature` | 返回类型、参数类型与参数名 |
| `calls` | 函数直接调用的 SDK 符号 |
| `file` | 源码相对路径 |
| `includes` | 直接包含的头文件 |
| 图关系 | caller、callee、declaration、definition 和 include 关系 |
| 构建证据 | 文件所属组件、构建规则和目标约束 |

查询由规范化的 `(capability, operation, contract)` 构成。当前覆盖 clock、interrupt、UART、GPIO 和 timer，共 19 个操作。

### 3.2 输出

每个操作输出排序候选、最终绑定和可审计证据：

```text
capability + operation
  -> selected SDK entity_id / symbol
  -> source role and API family
  -> field, contract, graph and layer evidence
  -> confidence and abstention state
```

绑定计划随后进入 OS Backend，生成 RT-Thread 或 Zephyr 原生设备工程。

## 4. 核心方法

核心方法只保留以下三个组成部分。

### 4.1 多通道字段迟交互召回

冻结的 all-MiniLM-L6-v2 分别编码 `symbol`、`signature`、`calls`、`file` 和 `includes`。每个字段使用专用操作查询，通过 token MaxSim 计算迟交互分数：

```text
S_f(q, d) = mean_i max_j cosine(q_f_i, d_f_j)
```

字段语义与静态操作匹配、符号子词、签名契约、源码角色和调用图邻域分别形成召回通道。各通道使用 RRF 合并，避免单个模型或单条规则控制全部候选。

本阶段目标是把正确 API 放入可重排候选集合，而不是直接作最终选择。

### 4.2 SDK 层级路由与操作契约

源码角色分类器把实体划分为：

- public HAL；
- vendor LL/PDL/driverlib；
- SDK driver/source/header；
- OS adapter；
- middleware；
- example/test/documentation。

操作契约进一步区分外设子模式、动作方向和参数化开关。例如基础 timer 对 PWM、Encoder 和软件 timer 施加冲突证据；系统 interrupt 对 SDIO/Wi-Fi/bus IRQ 施加冲突证据；`set_enabled(bool)` 不受简单反义词惩罚。

层级与契约分数定义为：

```text
S_h = 0.25 S_static + 0.25 S_field + 0.25 S_contract + 0.25 S_layer
```

首位仍由高精度静态/字段融合提供；只有首位契约弱、来源层较低或存在更强公共 HAL 候选时，才回退到层级路由结果。

### 4.3 API 家族覆盖解码

函数标识符被归一为 API 家族，例如 `HAL_TIM_Base_*`、`HAL_TIMEx_*`、`mtb_hal_clock_*` 和 `sysctl_clock_*`。解码器固定保留首位候选，再按以下顺序填充 Top5：

1. 首位家族中的高契约兄弟；
2. 更高抽象层的兼容家族代表；
3. 补位家族的一个高契约兄弟；
4. 多通道层级融合的剩余候选。

最终 q4 策略允许首位家族最多提供 4 个候选。该策略解决一个操作存在多个首选/替代接口时，普通 pointwise 排序只返回一个名称最相近函数的问题。

## 5. 轻量学习模块的定位

本轮实现了 461 参数的能力/操作自适应字段门控器。它使用：

- 五字段 query gate；
- capability/operation adapter；
- graded listwise loss；
- 从易到难的同族负例课程；
- 冻结基线上的有界残差。

该模型在自动分级开发真值上达到很高指标，但跨板卡 SDK 泛化不及最终确定性解码方法，说明自动弱真值仍包含规则偏差。因此：

- 它应作为“学习门控未能跨域泛化”的负向消融；
- 不应作为论文最终方法的性能来源；
- 人工真值完成后可以重新训练并判断是否转为正向组件；
- 当前论文主方法仍包含冻结 MiniLM 迟交互，但不包含训练后的 461 参数门控分数。

## 6. 原型系统的定位

原型仍由六个工程模块构成，但它们不是六个并列创新点。

| 模块 | 论文定位 |
| --- | --- |
| SDK Ingestor | 为方法提供统一 Migration IR 输入 |
| IR Store | 保存版本、实体 ID 和证据位置 |
| Semantic Resolver | 承载本文三个核心算法组成部分 |
| Closure Solver | 形成可编译工程所需的构建资产闭包 |
| Build Diagnoser | 将真实工具链错误转成闭包约束并自动迭代 |
| OS Backend | 生成 RT-Thread/Zephyr 原生工程和设备注册代码 |

论文方法贡献集中在 Semantic Resolver；其他模块共同证明方法不是脱离构建系统的离线排序实验。

## 7. 实验结果

三套板卡 SDK 保持 external-test 角色，共 50 个源码审计操作组。当前结果属于多轮错误分析后的探索性外部测试。

| 方法 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 操作静态规则 | 0.640 | 0.679 | 0.632 | 0.680 |
| 字段迟交互 | 0.660 | 0.772 | 0.668 | 0.728 |
| 层级契约融合 | 0.780 | 0.832 | 0.781 | 0.832 |
| 完整 q4 方法 | **0.820** | **0.926** | **0.815** | **0.873** |

相对静态方法，完整方法提高：

- P@1：+0.180，bootstrap 95% CI `[0.060, 0.300]`；
- Recall@5：+0.248，95% CI `[0.131, 0.362]`；
- MAP：+0.183，95% CI `[0.094, 0.274]`；
- nDCG@10：+0.193，95% CI `[0.107, 0.280]`。

开发集冻结阈值后，外部集自动接受 19/50 个操作，覆盖率 0.38，选择性精度 1.00，达到 0.95 目标。

## 8. 工程闭环证据

K210/RT-Thread 使用 `operation-structured` 运行时方法：

- 生成 19 个操作绑定；
- 首轮链接发现 `sys_register_getchar` 等缺失符号；
- Build Diagnoser 从 IR 定位并补入 `lib/bsp/syscalls.c`；
- 第二轮构建成功；
- 输出 RISC-V ELF/BIN；
- 19/19 绑定得到编译、链接和产物验证反馈。

完整运行耗时 259.67 秒，其中语义解析 120.39 秒、两轮构建 105.71 秒。编译成功仍不证明外设运行语义，三块板卡回归需要单独报告。

## 9. 论文贡献的推荐写法

论文贡献建议收敛为三点：

1. 提出层级约束的字段迟交互与 API 家族覆盖解码方法，解决异构 SDK 中抽象层混杂、设备子模式混淆和多实现漏召回问题。
2. 实现端到端 BSPForge 原型，将语义绑定与构建闭包、自动诊断和两种 RTOS 原生后端连接，生成可验证固件。
3. 构建跨 25 套 SDK 的操作级评估体系，在 20 个独立开发来源和三套板卡 SDK 上报告排序、选择性接受、编译、仿真与后续实板证据。

不要把四级真值、RRF、每条规则、每个后端或每个工具脚本分别列成创新点。它们是上述三项贡献中的实现与评估组成部分。

## 10. 论文结构映射

| 论文章节 | 内容 |
| --- | --- |
| 引言 | SDK 迁移成本、语义歧义和构建闭包问题 |
| 背景与动机 | 三类典型排序错误和现有代码检索不足 |
| 系统概览 | Migration IR 到 RTOS 固件的数据流 |
| 核心方法 | 字段迟交互、层级契约路由、API 家族覆盖解码 |
| 原型实现 | 六模块职责、双后端、自动诊断与反馈边界 |
| 实验 | 数据隔离、主表、消融、统计、耗时、编译与仿真 |
| 讨论 | 弱真值、确认测试、上板语义和适用边界 |

## 11. 当前结论边界

当前可以声称：在现有 50 组源码审计操作真值上，完整方法达到既定五项排序/选择性目标，并在 K210 运行时进入真实构建闭环。

当前不能声称：

- 对未见厂商已完成确认性泛化验证；
- 自动弱真值等同于人工金标准；
- 编译成功等同于设备运行正确；
- 三块板卡已经完成真实外设回归。

正式论文应冻结当前代码和 q4 参数，增加未用于错误分析的 SDK 做一次性确认测试，并完成第二人真值复核。

## 12. 实现文件与复现路径

| 文件 | 职责 |
| --- | --- |
| `bspforge/structured_retrieval.py` | 源码角色、操作契约、调用图、RRF、层级回退和 q4 家族覆盖解码 |
| `bspforge/adaptive_field_ranker.py` | 461 参数字段门控负向消融模型 |
| `bspforge/semantic_resolver/resolver.py` | 将最终方法接入 `operation-structured` 运行时解析 |
| `scripts/add_structured_retrieval_scores.py` | 从 v0.9 数据生成结构化通道特征 |
| `scripts/train_adaptive_field_ranker.py` | 按独立 SDK 分组训练自适应门控 |
| `scripts/evaluate_adaptive_structured_ranker.py` | 主表、消融、分组指标、bootstrap 和选择性校准 |
| `scripts/summarize_operation_v10.py` | 生成可提交的紧凑实验摘要 |
| `experiments/operation-ranking/results-v1.0-summary.json` | v1.0 主指标、分组结果、置信区间与工程证据 |

在已经完成 v0.9 字段迟交互打分的环境中执行：

```bash
cd /home/whk/RTT-porting/bspforge
conda activate AIoT-v1.0

python scripts/add_structured_retrieval_scores.py \
  --dataset experiments/generated/operation-ranking-dataset-v0.9-field-all.json \
  --output experiments/generated/operation-ranking-dataset-v1.0-structured.json

python scripts/train_adaptive_field_ranker.py \
  --dataset experiments/generated/operation-ranking-dataset-v1.0-structured.json \
  --split experiments/operation-ranking/development-split.json \
  --output-model models/adaptive-field-ranker-v1.pt \
  --report experiments/generated/adaptive-field-ranker-training-v1.json

python scripts/evaluate_adaptive_structured_ranker.py \
  --dataset experiments/generated/operation-ranking-dataset-v1.0-structured.json \
  --split experiments/operation-ranking/development-split.json \
  --model models/adaptive-field-ranker-v1.pt \
  --output experiments/generated/operation-ranking-results-v1.0.json
```

最终方法不读取候选标签，也不使用自适应门控输出。标签只在评测脚本中计算指标；运行时 Resolver 与离线评测调用同一个 `complete_structured_scores()`，避免论文算法和工程实现形成两套口径。
