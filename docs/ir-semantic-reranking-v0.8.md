# IR 感知轻量语义排序方案 v0.8

## 1. 目标与当前结论

本方案解决规范化 RTOS 操作到异构 SDK 函数实体的排序问题。输入不是任意源码文本，而是 SDK Ingestor 已生成的 Migration IR；输出是每个规范化操作的候选顺序、分项分数、置信差和可追溯实体 ID。模型不负责生成代码，也不替代静态证据、闭包求解和编译验证。

最终实现选用固定版本的 `sentence-transformers/all-MiniLM-L6-v2`，基础模型为 22,713,216 参数，本地缓存约 88 MiB，Apache-2.0 许可。模型主体完全冻结，新增秩为 16 的查询残差适配器，共 12,288 个可训练参数，占基础模型参数的 0.0541%，适配器文件约 52 KiB。

运行时采用三路融合：

```text
最终分数 = 0.30 × 静态操作证据
         + 0.20 × 基础 MiniLM 简洁查询相似度
         + 0.50 × IR 查询适配相似度
```

默认均衡模式在 50 个板卡操作组上得到 P@1 0.620、Recall@5 0.650、MAP 0.635 和 nDCG@10 0.663。Top-10 精排模式得到 P@1 0.640、Recall@5 0.640、MAP 0.626。相对 v0.7 等权融合，均衡模式的 MAP 增量为 0.0063，Bootstrap 95% 区间为 `[-0.0386, 0.0538]`，尚不能声明统计显著优越。

本轮开发过程中已经反复查看三块板卡的聚合结果，因此这些结果属于探索性外部评估。正式论文应使用新增的源码审计开发集预先固定适配器和融合参数，再对未查看的新 SDK 或保留板卡执行一次性确认测试。

## 2. 为什么选择 MiniLM

候选模型必须满足四个约束：能够比较操作契约和代码 IR；开放权重与许可；普通 CPU 可运行；能够进行可展示的内部调优。

| 模型 | 参数/本地体积 | 特点 | 本机外部集表现 | 结论 |
| --- | ---: | --- | --- | --- |
| all-MiniLM-L6-v2 | 22.7M / 88 MiB | 通用句向量，384 维，CPU 成熟 | 基础语义 MAP 0.382；与静态融合 MAP 0.628 | 最终基础模型 |
| BGE-small-en-v1.5 | 33.4M / 129 MiB | MIT，检索模型 | 语义 MAP 0.362；最佳融合 MAP 0.605；外部编码约 98 秒 | 精度未超过 MiniLM |
| Granite embedding small English R2 | 47M / 95 MiB | Apache-2.0，2025 年发布，公开报告包含代码检索 | 192 token 时约 19 秒/批，完整测试预计十余分钟 | 当前 CPU 实现不满足效率目标 |
| MS MARCO MiniLM-L6 cross-encoder | 22.7M | 查询和候选联合编码，交互更充分 | 未调优外部 MAP 0.428；弱监督调优后降至 0.320 | 域过拟合，保留为负向消融 |

模型固定版本如下：

- MiniLM：`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`；
- BGE-small：`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`；
- Granite R2 small：`2ab6fa8ea2d674564defd37171ae19079b864b33`；
- MS MARCO MiniLM cross-encoder：`233902d25c440f23af6f7d6e94d2946bac0bee0a`。

参考模型页：[MiniLM](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)、[BGE-small](https://huggingface.co/BAAI/bge-small-en-v1.5)、[Granite R2 small](https://huggingface.co/ibm-granite/granite-embedding-small-english-r2)、[MS MARCO MiniLM cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)。

## 3. IR 输入表示

### 3.1 操作查询

一个查询组由 `sdk_id`、`independence_group`、`capability`、`operation` 和 `query_text` 组成。适配查询采用 `ir-operation-v1`：

```text
SDK migration operation
capability: uart
operation: write
contract: transmit bytes through a UART peripheral
```

基础语义分支使用同一 IR 中的 `query_text`，避免结构标签改变预训练相似度分布。两种查询均由 `operation_encoder_query()` 生成，不从文件名临时拼接。

### 3.2 候选实体

候选由 `candidate_code_text()` 从函数 IR 生成：

```text
file: drivers/uart.c
symbol: uart_send_data
signature: size_t uart_send_data(...)
includes: uart.h sysctl.h
calls: uart_channel_put ...
```

输入最长 128 token。候选向量只由冻结基础模型生成，可按 SDK 摘要和实体 ID 缓存；升级 52 KiB 查询适配器不需要重编码 SDK。

### 3.3 输出

`operation-semantic` 在原操作候选中增加：

- `operation_score`：可审计静态规则分数；
- `semantic_scores.base`：基础简洁查询相似度；
- `semantic_scores.adapted`：IR 查询经过低秩适配后的相似度；
- `semantic_candidate`：候选是否进入可选 Top-K 精排池；
- `score`：三路融合分数；
- `selected_entity_id`、`selected_symbol` 和 `confidence_margin`。

这些字段进入 `02-semantic-resolution.json`，Binding Planner 继续只消费稳定实体 ID 和操作契约，Closure Solver 与 OS Backend 无需了解神经模型。

## 4. 数据与隔离

数据清单包含 22 套开发 SDK，按共同厂商或上游合并为 20 个独立性组；另有 K210、STM32CubeF1 和 PSoC E84 三套板卡 SDK。操作本体包含 clock、interrupt、uart、gpio 和 timer 的 19 个操作。

| 数据角色 | 独立组 | 查询组 | 用途 |
| --- | ---: | ---: | --- |
| 训练 | 16 | 306 | 构造高置信正例和困难负例 |
| 开发 | 4 | 85 | 选择训练轮次，不更新参数 |
| 板卡外部评估 | 3 块板卡，3 个独立组 | 50 个适用操作 | 聚合探索评估与后续上板 |

训练与开发分组保存在 `experiments/operation-ranking/development-split.json`。三块板卡的 `label_source` 必须为 `source-audited`，训练脚本会检查并排除它们。训练候选总集为 391 个查询组、37,808 个候选和 3,012 个弱正例。

每个训练查询最多选择两个 `label >= 2` 的高置信正例。困难负例优先选择反义操作、语义冲突和静态高分错误候选，最终形成 992 个三元组。弱标签来自高精度结构规则，仍可能含噪声，这是交叉编码器域过拟合和外部增益受限的主要原因。

## 5. 模型内部调优

### 5.1 直接编码器调优

第一种方法解冻 MiniLM 最后两层，共 3,548,928 个参数，占 15.62%，使用余弦三元组间隔损失。开发集 MAP 从 0.3363 提高到 0.4987，相对提高 48.3%；外部语义单项从 MAP 0.4360 提高到 0.4568，P@1 从 0.30 提高到 0.32，Recall@5 从 0.56 提高到 0.60。但调优后的分数与静态规则相关性增加，线性融合反而低于基础简洁查询融合，因此不作为部署默认。

### 5.2 交叉编码器调优

第二种方法以 RankNet 成对损失调优 MS MARCO MiniLM 交叉编码器的最后两层和分类头，共 3,549,313 个参数。开发 MAP 从 0.4318 提高到 0.4763，相对提高 10.3%；外部 MAP 却从 0.4278 降至 0.3198。训练损失持续下降而跨 SDK 结果恶化，说明模型吸收了弱标签和开发厂商特征。该结果作为失败消融保留，不进入运行时。

### 5.3 低秩查询残差适配

最终方法冻结 MiniLM 的全部参数，只学习查询侧残差：

```text
q' = normalize(q + W_up(tanh(W_down q)))
```

其中 `q` 为 384 维基础 IR 查询向量，秩 `r=16`。`W_up` 零初始化，使模型从恒等映射开始。目标函数为：

```text
L = max(0, sim(q', d-) - sim(q', d+) + margin)
    + lambda × (1 - cos(q', q))
```

当前 `margin=0.12`、`lambda=0.35`、AdamW 学习率 `2e-3`、批量 64、最多 120 轮，每 5 轮在四个独立开发 SDK 组上评估。适配器实际训练约 4.5 秒；一次性基础向量编码约 256 秒。最佳轮次为 90，开发 MAP 从 0.3363 提高到 0.3739，相对提高 11.2%，Recall@5 从 0.2433 提高到 0.2849，相对提高 17.1%。

外部语义单项的 Recall@5 达到 0.650，但 P@1 为 0.220、MAP 为 0.425，说明适配器更适合提供互补召回，而不适合独立决定首位候选。因此系统保留静态和基础语义分支，并把适配器作为残差证据。

## 6. 融合与级联

### 6.1 均衡模式

在全部能力候选中计算三路分数，按 `0.30/0.20/0.50` 融合。该模式取得最高探索性 MAP 和 nDCG，适合论文主消融和需要完整候选排序的场景。

### 6.2 精度模式

先按静态规则保留 Top-10，再仅在池内执行三路重排，池外候选不能越过池内候选。精度模式使用 `0.40/0.30/0.30`，P@1 提高到 0.640，但 Recall@5 和 MAP 略低于均衡模式。配置项为 `semantic_candidate_top_k: 10`。

### 6.3 指标对比

| 方法 | P@1 | Recall@5 | MRR | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.220 | 0.460 | 0.388 | 0.346 | 0.432 |
| 操作静态规则 | 0.540 | 0.595 | 0.601 | 0.554 | 0.590 |
| v0.7 MiniLM + 静态等权 | 0.600 | 0.685 | 0.671 | 0.628 | 0.652 |
| v0.8 低秩适配三路均衡 | 0.620 | 0.650 | 0.686 | 0.635 | 0.663 |
| v0.8 Top-10 精度模式 | 0.640 | 0.640 | 0.685 | 0.626 | 0.646 |

均衡模式相对 v0.7 的 P@1、MAP 和 nDCG@10 分别增加 0.020、0.0063 和 0.0112，Recall@5 下降 0.035。对应 Bootstrap 区间均跨越 0，当前只能主张“提供可配置的精度/召回取舍和小幅正向趋势”，不能主张统计显著提升。要形成强论文证据，应增加高质量人工标注开发 SDK，并增加一次未参与本轮设计的新 SDK 确认测试。

## 7. 完整流水线验证

`examples/k210-rtthread/project-semantic.json` 已执行真实端到端回归：

- 摄取 201 个文件和 2,164 个函数；
- 五类能力全部解析，规范化计划包含 19/19 个操作；
- 闭包包含 67 个文件、10 条构建规则、启动和链接资产；
- 第一次链接发现四个 syscall 未定义符号，Build Diagnoser 定位 `lib/bsp/syscalls.c` 并增量修复；
- 第二次编译成功，生成 668,008 字节 ELF 和 471,992 字节 BIN；
- ELF 为 RISC-V，入口 `0x80000000`，生成的 UART/PIN/HWTIMER 操作表和验证入口全部存在；
- 端到端方法评估：宏平均 Precision 0.80、Recall 0.67、F1 0.7162、MRR 0.90，绑定召回和设备操作召回均为 1.0；
- 语义解析 47.95 秒，完整流水线 178.33 秒。

这证明新排序器能够进入 IR、绑定、闭包、自动诊断和固件生成链，而不是只存在于离线 notebook。该结果仍不是上板功能正确性的替代证据。

## 8. 文件职责

| 文件 | 职责 |
| --- | --- |
| `bspforge/operation_encoder.py` | 定义 IR 查询序列化和基础双编码器接口 |
| `bspforge/semantic_adapter.py` | 定义低秩残差适配器和运行时三路语义评分器 |
| `bspforge/semantic_resolver/resolver.py` | 实现 `operation-semantic`、融合、Top-K 和输出证据 |
| `scripts/train_operation_encoder.py` | 最后两层三元组调优消融 |
| `scripts/train_operation_reranker.py` | 交叉编码器 RankNet 失败消融 |
| `scripts/train_operation_query_adapter.py` | 冻结基础模型，训练并选择低秩适配器 |
| `scripts/add_code_embedding_scores.py` | 生成基础或完整调优模型的语义特征 |
| `scripts/add_query_adapter_scores.py` | 生成查询适配语义特征 |
| `scripts/evaluate_semantic_ensemble.py` | 固定网格、Top-K、配对 Bootstrap 和指标汇总 |
| `models/operation-query-adapter-ir-v1.pt` | 可直接加载的 52 KiB 最佳适配器 |
| `experiments/operation-ranking/development-split.json` | 16/4/3 独立分组协议 |
| `experiments/generated/operation-query-adapter-training.json` | 参数、曲线、耗时和模型哈希 |
| `experiments/generated/operation-ranking-results-adapter-ensemble.json` | 均衡模式全部权重网格和指标 |
| `experiments/generated/operation-ranking-results-adapter-cascade-k10.json` | Top-10 精度模式全部权重网格和指标 |

## 9. 复现命令

```bash
cd /home/whk/RTT-porting/bspforge
conda activate AIoT-v1.0
python -m pip install -e '.[retrieval,learning]'

python scripts/train_operation_query_adapter.py \
  --dataset experiments/generated/operation-ranking-dataset.json \
  --split experiments/operation-ranking/development-split.json \
  --output-adapter models/operation-query-adapter-ir-v1.pt \
  --report experiments/generated/operation-query-adapter-training.json

python scripts/add_query_adapter_scores.py \
  --dataset experiments/generated/operation-ranking-dataset.json \
  --output experiments/generated/operation-ranking-dataset-query-adapter.json \
  --adapter models/operation-query-adapter-ir-v1.pt \
  --roles external-test

python scripts/evaluate_semantic_ensemble.py \
  --base experiments/generated/operation-ranking-dataset-embedded.json \
  --tuned experiments/generated/operation-ranking-dataset-query-adapter.json \
  --output experiments/generated/operation-ranking-results-adapter-ensemble.json

python -m bspforge.cli pipeline \
  --config examples/k210-rtthread/project-semantic.json
```

大体积逐候选数据由脚本生成并被 `.gitignore` 排除；训练报告、紧凑指标、适配器和固定划分进入 Git。基础模型由名称和提交哈希下载。

## 10. 论文使用边界与下一步

可以作为论文贡献的内容包括：Migration IR 双域序列化、冻结小模型的查询侧低秩残差适配、静态/基础/适配三路可解释融合、候选级联和从排序证据到可编译固件的闭环验证。不能把模型输出或编译通过直接表述为外设语义正确。

下一步优先级如下：

1. 对至少 4 至 6 个开发 SDK 建立双人源码审计的操作真值，替换弱标签选模；
2. 固定全部参数后增加未查看 SDK，或把一块新增开发板作为一次性确认测试；
3. 报告 Cohen's kappa、分板卡指标、操作类别指标、显著性和错误类型；
4. 完成三块开发板的 UART/GPIO/定时器真实回归，分别报告排序、编译和运行结论。
