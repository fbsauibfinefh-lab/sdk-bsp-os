# 操作级语义排序、可靠性边界与模型优化方案

## 1. 本轮目标

本轮把原先的“能力级候选恢复”细化为 19 个规范化操作的排序问题。系统不再只回答某个函数是否与 UART、GPIO 或 TIMER 相关，而是分别判断它是否适合 `uart.write`、`gpio.attach_irq`、`timer.stop` 等具体后端契约。这样可以直接评价生成绑定是否选对了操作，而不是用“同属一个外设能力”替代语义正确性。

语义排序与构建闭包、编译诊断、RT-Thread 后端和 Zephyr 后端保持模块边界。排序器输出仍是带实体 ID、分数、证据和 `target_operations` 的解析结果；闭包和后端不需要理解排序模型内部实现。

## 2. 数据协议

### 2.1 开发语料

`experiments/operation-ranking/manifest.json` 固定了 22 套开发 SDK，按厂商或共同上游合并为 20 个独立性分组：

| SDK | 厂商/生态 | 独立性分组 |
| --- | --- | --- |
| pico-sdk | Raspberry Pi | raspberry-pi |
| nrfx | Nordic | nordic |
| esp-idf | Espressif | espressif |
| mcux-sdk | NXP | nxp |
| mspm0-sdk | Texas Instruments | ti |
| simplelink-lowpower-f2-sdk | Texas Instruments | ti |
| renesas-fsp | Renesas | renesas |
| arduino-renesas-core | Renesas | renesas |
| microchip-csp | Microchip | microchip |
| no-OS | Analog Devices | analog-devices |
| spresense-sdk | Sony | sony |
| SiFli-SDK | SiFli | sifli |
| bouffalo-sdk | Bouffalo Lab | bouffalo |
| WCH HAL | WCH | wch |
| Nuclei SDK | Nuclei | nuclei |
| libopencm3 | 社区多厂商 HAL | libopencm3 |
| Mbed OS | Arm | arm-mbed |
| Telink HAL | Telink | telink |
| Alif HAL | Alif Semiconductor | alif |
| Silicon Labs HAL | Silicon Labs | silicon-labs |
| HPM SDK | HPMicro | hpmicro |
| Nuvoton BSP | Nuvoton | nuvoton |

开发语料生成 391 个弱监督操作查询组。每组保留高置信正例、60 个困难负例和最多 20 个固定随机种子负例，合计 37,808 个候选和 3,012 个弱正例。这里的有效样本单位是“独立 SDK 中的操作查询组”，不能把同一 SDK 的数万个函数当作数万个独立样本。

### 2.2 外部测试

K210、STM32F103 和 PSoC E84 三套实际板卡 SDK 只用于源码审计外部测试，不进入弱标签生成、模型训练或参数选择。最终协议包含 50 个适用操作组；函数接口无法表达的宏操作、回调覆写和不支持操作标为 `not-supported`，不计入分母。

当前真值状态是单人源码审计。投稿前必须由第二位标注者独立复核，报告一致性和裁决结果。测试板 SDK 可以用于工程调试和最终上板，但不能回流训练后仍被称为“未见 SDK 泛化结果”。

## 3. 操作级方法

### 3.1 候选恢复

候选池由 SDK IR 中的函数实体构成，使用能力名称、动作词、源码路径、签名、包含关系、调用关系、宏上下文和解析置信度进行初筛。每个候选保留源文件、行号、实体 ID 和解析前端，便于人工复核。

### 3.2 操作契约特征

操作排序新增以下通用证据：

- 操作词的完整 token 命中与子串命中；
- 能力词与操作词的规范顺序；
- 参数、返回类型和调用上下文中的动作提示；
- 公开 API、HAL 抽象层和中断控制器 API 证据；
- 私有实现、测试样例和反义动作惩罚；
- 参数化开关识别，例如 `set_enable(..., bool)` 可同时满足 start/stop 或 enable/disable；
- 反向 OS 适配识别，例如 SDK 端口层函数内部调用 `rt_pin_write`，不能再被选择为 SDK 硬件实现；
- 操作冲突约束，例如 UART 发送候选不能由 receive/read 动作主导；
- 可选代码语义嵌入余弦分数。

这些规则不包含三块测试板的目标函数白名单。板卡真值只在评测阶段转成标签。

### 3.3 弱监督学习

LightGBM LambdaRank 使用 20 个独立性分组进行留一验证。弱标签由高精度操作词、公开驱动路径、签名和冲突排除产生。该方法扩大了数据量，但标签与静态规则同源，因此训练内验证接近饱和并不代表真实泛化。外部结果显示，纯弱监督模型明显弱于可审计静态方法，当前不应作为默认解析器。

### 3.4 语义嵌入消融

工程提供 `scripts/add_code_embedding_scores.py`，支持固定模型版本、角色选择、归一化嵌入和 CPU/GPU 运行。本轮受本机算力限制，使用轻量 `all-MiniLM-L6-v2` 对外部候选执行零样本语义消融；它不是本文拟采用的最终 SOTA 模型。`CodeRankEmbed` 的固定版本入口已实现，但本机 CPU 对 2 万个训练候选的预计运行时间过长，未生成完整训练嵌入结果。

## 4. 当前结果

主表在 3 套完全外部板卡 SDK、50 个适用操作组上计算：

| 方法 | P@1 | Recall@3 | Recall@5 | MRR | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 词法 | 0.220 | 0.350 | 0.460 | 0.388 | 0.346 | 0.432 |
| 操作级静态证据 | 0.540 | 0.530 | 0.595 | 0.601 | 0.554 | 0.590 |
| 纯弱监督 LambdaRank | 0.200 | 0.360 | 0.520 | 0.346 | 0.327 | 0.386 |
| 静态与弱学习融合 | 0.520 | 0.520 | 0.595 | 0.579 | 0.537 | 0.562 |
| 轻量语义嵌入 | 0.240 | 0.380 | 0.580 | 0.402 | 0.382 | 0.473 |
| 静态与语义等权融合 | 0.600 | 0.630 | 0.685 | 0.671 | 0.628 | 0.652 |

静态与语义等权融合相对静态方法的 MAP 平均增加 0.075，10,000 次分组 bootstrap 的 95% 区间为 `[0.012, 0.146]`。P@1 的区间仍跨越 0，且等权融合属于当前敏感性分析，投稿主结果应在独立开发集上预先确定权重后重新测试，不能按测试集最优权重报告。

从早期能力级嵌套融合的 P@1 0.176、MAP 0.275 到当前操作级静态方法的 P@1 0.540、MAP 0.554，查询定义、真值分母和方法均发生变化，因此该对比只能说明评估与方法已明显收敛，不能当作单一特征的因果增益。最终论文应保留同一数据协议下的消融。

## 5. 编译通过为什么不等于固件有用

编译和链接只能证明类型、符号、构建资产与 ABI 在静态层面闭合。错误 API 仍可能顺利进入 ELF，成熟 RTOS BSP 的既有驱动也可能让固件启动，从而掩盖自动绑定没有真正生效。以下问题通常不会由编译器发现：

- 外设实例、管脚复用、时钟门控或复位顺序错误；
- 枚举、单位、极性、波特率分频和定时周期语义不一致；
- 句柄、上下文和初始化生命周期错误；
- 中断向量、优先级、控制器、回调约定或清中断顺序错误；
- DMA、缓存一致性、对齐和并发访问约束缺失；
- 条件编译选择了相近但不同的芯片变体；
- 板级晶振、内存布局、启动顺序和勘误要求不匹配；
- 返回码、超时和阻塞/异步语义映射错误。

因此当前 P@1 0.600 不能支撑“全部操作无人值守自动生成且基本可靠”的结论。更准确的系统契约是：高置信候选自动进入生成链，低置信候选拒答并保留人工确认；所有结果继续接受编译、静态绑定追踪、仿真和实板回归。

### 5.1 建议可靠性门槛

下列值不是 CCF 或期刊统一标准，而是投稿前建议的工程发布门槛：

| 层次 | 建议下限 |
| --- | --- |
| 候选池可检索性 | Recall@50 不低于 0.95 |
| 外部 SDK 首选操作 | P@1 不低于 0.80，目标 0.85 |
| 外部 SDK 候选覆盖 | Recall@5 不低于 0.90 |
| 排序整体质量 | MAP、nDCG@10 不低于 0.80 |
| 自动接受结果 | 选择性精度不低于 0.95，校准误差 ECE 不高于 0.10 |
| 类型与绑定契约检查 | 通过率 100% |
| 独立工程构建 | 成功率不低于 95% |
| 关键实板操作 | 建议全部通过；重复启动成功率不低于 99% |

当前静态方法在分差 0.05 时覆盖 24% 操作，选择性精度为 91.7%；等权语义融合在同一分差时覆盖 12%，选择性精度为 83.3%。这说明分差并未经过校准，不能直接跨方法复用同一阈值；投稿前应在独立开发集上学习阈值，再冻结到板卡测试集。

## 6. 下一阶段模型方案

### 6.1 推荐主线：代码检索器加结构化重排序

优先采用两阶段架构：代码专用双编码器召回候选，结构与构建证据重排前 20 至 50 个候选。可比较的近期模型包括：

- `CodeRankEmbed`：137M 参数、8K 上下文、MIT 许可，模型卡报告 CodeSearchNet MRR 77.9、CoIR nDCG@10 60.1，并提供配套 `CodeRankLLM` 重排器。
- `jina-code-embeddings-0.5b/1.5b`：2025 年代码专用嵌入模型，可作为较强代码语义教师模型。
- `Qwen3-Embedding-0.6B` 与 `Qwen3-Reranker-0.6B`：Apache 2.0，支持多种编程语言和自定义任务指令，适合“中文操作描述到 C SDK API”的跨语言检索。
- `SFR-Embedding-Code-400M_R`：面向代码检索并提供量化 ONNX，但许可证为 CC BY-NC 4.0，适合论文实验，不宜直接作为商业默认依赖。
- `jina-reranker-v3.5`：2026 年 0.6B listwise 重排器，适合对一个操作的候选列表联合重排；它不是代码专用模型，应先做领域适配和独立消融。

模型信息来源：[CodeRankEmbed 模型卡](https://huggingface.co/nomic-ai/CodeRankEmbed)、[Jina Code Embeddings](https://huggingface.co/collections/jinaai/jina-code-embeddings)、[Qwen3 Embedding 官方说明](https://qwenlm.github.io/blog/qwen3-embedding/)、[SFR Code 模型卡](https://huggingface.co/Salesforce/SFR-Embedding-Code-400M_R)、[jina-reranker-v3.5 模型卡](https://huggingface.co/jinaai/jina-reranker-v3.5)。

### 6.2 面向本任务的调优

可把模型创新集中在“操作契约与 SDK 程序结构联合排序”，而不是通用自然语言代码搜索：

1. 查询编码加入能力、动作、同步/异步、输入输出、生命周期和目标 RTOS 契约。
2. 候选编码组合函数名、签名、头文件路径、调用者/被调用者、条件宏和构建目标。
3. 使用同一能力内的反义操作、不同抽象层 API、端口层反向适配和相邻芯片变体作为困难负例。
4. 用人工真值执行 InfoNCE 或多负例排序损失；弱标签只用于预训练，不用于最终校准。
5. 将 AST、调用图、包含图和构建图编码为关系特征，与代码嵌入执行门控融合或小型 GNN 重排。
6. 用较强 reranker/代码嵌入模型产生软分数，再蒸馏到 100M 至 600M 的本地模型。
7. 使用温度缩放或保序回归校准置信度，以 95% 选择性精度为目标学习拒答阈值。

如果图结构融合、参数化开关识别和适配方向约束能在独立 SDK 上显著提升 P@1、Recall@5 与选择性精度，它们可以成为论文核心创新，而不仅是工程优化。近期代码仓库研究也在强调结构化检索，例如 [CodexGraph（NAACL 2025）](https://aclanthology.org/2025.naacl-long.7/) 和 [Code Graph Model（NeurIPS 2025）](https://proceedings.neurips.cc/paper_files/paper/2025/hash/178ae4ba29022eb7bf509c2e27bc8ab8-Abstract-Conference.html)。

## 7. 模块独立性

只优化语义排序原则上不需要改动 SDK Ingestor、Closure Solver、Build Diagnoser 或 OS Backend。必须保持的接口只有：

- 输入仍是版本化 SDK IR 和规范化操作集合；
- 输出仍包含候选实体 ID、符号、分数、证据和 `target_operations`；
- 无高置信候选时明确输出 `missing/abstained`，不能用任意低分函数填充；
- Binding Planner 继续把操作选择转换为统一绑定计划。

本轮只对 Binding Planner 增加了向后兼容的 `target_operations` 消费路径，并为 Resolver 增加 `operation_min_margin`。闭包与两个后端的核心逻辑未因排序模型改变。任何排序器替换后仍应重跑 3 芯片乘 2 RTOS 构建矩阵，因为输出分布变化可能暴露原有后端假设。

## 8. 复现

```bash
./scripts/bootstrap_evaluation_sdks.sh
conda run -n AIoT-v1.0 python scripts/ingest_operation_corpus.py \
  --manifest experiments/operation-ranking/manifest.json \
  --ir-root workspace/operation-ir
conda run -n AIoT-v1.0 python scripts/build_operation_dataset.py \
  --manifest experiments/operation-ranking/manifest.json \
  --ir-root workspace/operation-ir \
  --output experiments/generated/operation-ranking-dataset.json
conda run -n AIoT-v1.0 python scripts/evaluate_operation_ranker.py \
  --dataset experiments/generated/operation-ranking-dataset.json \
  --output experiments/generated/operation-ranking-results.json
```

轻量语义消融：

```bash
conda run -n AIoT-v1.0 python scripts/add_code_embedding_scores.py \
  --dataset experiments/generated/operation-ranking-dataset.json \
  --output experiments/generated/operation-ranking-dataset-embedded.json \
  --model sentence-transformers/all-MiniLM-L6-v2 \
  --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --roles external-test --device cpu
```

大体积数据集由清单和脚本重建，不提交 Git；语料报告、最终指标、真值、脚本和固定依赖说明提交仓库。
