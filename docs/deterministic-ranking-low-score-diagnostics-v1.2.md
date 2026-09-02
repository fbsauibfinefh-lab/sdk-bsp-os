# 无 SDK 训练的确定性排序与低分诊断（v1.2）

## 1. 当前决策边界

当前论文任务预先定义 clock、interrupt、UART、GPIO 和 timer 五类通用能力的19个操作，并假设目标 SDK 对这些操作提供至少一个可调用实现。系统不再用置信阈值拒绝操作：能力候选池非空时，`operation-structured` 始终输出最终分数最高的 Top1，并将其写入规范化绑定计划。

低最终分数、弱操作契约、较低源码层证据、弱多通道支持或决策共识不足只会产生 `ranking_evidence` 诊断，不会把操作改成 `abstained`。候选池为空仍属于输入或前端可达性问题，记录为 `missing`。

## 2. 排序方法

系统以冻结的 `all-MiniLM-L6-v2` 对 `symbol`、`signature`、`calls`、`file` 和 `includes` 五个 IR 字段进行 token 级迟交互，得到字段语义分数。随后融合静态操作证据、源码角色、操作契约、调用图、API 家族和多通道 RRF。

首位默认由高精度融合分数决定：

```text
S_precision = 0.50 * S_static + 0.50 * S_field
```

当纯精度首位存在弱契约、专用设备子模式或较低源码层，而其他候选具有显著更强的通用操作证据时，系统使用固定规则回退到：

```text
S_hierarchy = 0.25 * (S_static + S_field + S_contract + S_layer)
S_certified = S_hierarchy + 0.16 * S_generic + 0.05 * S_role
```

排序首位确定后，q4 API 家族覆盖解码只安排第2至第5名，以保留阻塞、中断、DMA 或不同公共抽象层的可追溯替代实现。最终选择仍是第1名。

## 3. 低分与弱证据诊断

`bspforge/ranking_diagnostics.py` 对实际 Top1 记录以下字段：

- `final_ranking_score`：真正用于最终排序的分数；
- `decision_margin`：Top1 与其他唯一符号的连续决策分差；
- `entity_agreement`、`family_agreement`：八个通道对实体和 API 家族的首位一致率；
- `field_semantic_score`、`contract`、`generic_operation_fit`、`rrf`、`role`：首位的关键证据；
- `low_score_reasons`：固定判据产生的复核原因；
- `channel_top_symbols`：各证据通道的首选符号。

当前原因包括 `low-final-ranking-score`、`low-field-semantic-score`、`weak-operation-contract`、`low-callable-layer-evidence`、`weak-multi-channel-retrieval` 和 `weak-decision-consensus`。这些判据不读取 SDK 真值，也不改变排序、绑定或指标分母。

## 4. 可靠性评测口径

覆盖率和选择性精度已从当前方法中删除。可靠性按每套平行真值中所有可达查询组计算：

- P@1：Top1 落入可接受真值集合的查询比例，可解释为操作级 Top1 准确率；
- Recall@3/5：前3/5名覆盖分级相关 API 的程度；
- MRR：第一个相关 API 的倒数排名；
- MAP：对全部相关 API 排序质量的平均；
- nDCG@10：考虑0至3级相关度的前10名排序质量。

低分诊断组仍完整计入上述分母，不能通过标记低分来删除错误样本。自动真值、H01 和 H02 是三套平行口径，不合并为一个分数。

| 真值 | SDK数 | 查询组 | P@1 | Recall@5 | MAP | nDCG@10 | 低分/弱证据组 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 自动分级真值 | 25 | 450 | 0.662 | 0.495 | 0.557 | 0.623 | 237 |
| H01 | 23 | 328 | 0.381 | 0.552 | 0.460 | 0.517 | 150 |
| H02 | 23 | 331 | 0.414 | 0.522 | 0.476 | 0.525 | 153 |

这些全量结果尚未达到项目预设的 P@1≥0.80、Recall@5≥0.90、MAP/nDCG@10≥0.80，因此当前不能声称系统已经在所有已有真值 SDK 上达到高可靠语义选择。

## 5. 三块板卡诊断子集

三套拟上板 SDK 共50个可达操作组，P@1、Recall@5、MAP 和 nDCG@10 分别为1.000、0.936、0.923和0.960；其中 STM32F103 `interrupt.initialize` 被标为弱操作契约证据。该子集参与过规则错误分析，只用于准备实板实验和定位问题，不替代全量主结果。

三块板卡与两个 OS 后端的逐操作对照见 `docs/board-six-combination-operation-comparison.md`。同一 SDK 在 RT-Thread 和 Zephyr 下共享 SDK 侧语义选择，后端差异发生在设备对象、注册代码、配置和构建资产生成阶段。板卡部分的 H01/H02 当前继承同一套 `source-audited` 真值，不能解释为两位工程师对板卡样本的独立重复标注。

## 6. 运行时输出

每个 `operation_rankings` 条目包括：

```text
operation
selected_entity_id / selected_symbol
confidence_margin
ranking_evidence
candidates (TopK)
```

为兼容旧版下游结构，`abstained` 字段暂时保留；在 `operation-structured` 且候选非空时其值恒为 `false`。Binding Planner 消费 `selected_entity_id`，Closure Solver 以绑定实体为种子求解源码、头文件、宏、链接和启动资产，两个 OS Backend 再生成各自原生工程。

## 7. 复现

```bash
cd /home/whk/RTT-porting/bspforge
conda activate AIoT-v1.0

python scripts/evaluate_deterministic_ranker.py \
  --dataset experiments/generated/deterministic-no-training-v1.1-h01-structured.json \
  --role all \
  --output experiments/operation-ranking/results-deterministic-no-training-v1.2-h01-all.json

python scripts/generate_board_truth_comparison.py \
  --system experiments/generated/deterministic-no-training-v1.1-structured.json \
  --h01 experiments/generated/deterministic-no-training-v1.1-h01-structured.json \
  --h02 experiments/generated/deterministic-no-training-v1.1-h02-structured.json \
  --output docs/board-six-combination-operation-comparison.md
```

机器可读的三真值汇总保存在 `experiments/operation-ranking/results-deterministic-no-training-v1.2-all-truth-summary.json`。核心运行文件为 `bspforge/structured_retrieval.py`、`bspforge/ranking_diagnostics.py` 和 `bspforge/semantic_resolver/resolver.py`。
