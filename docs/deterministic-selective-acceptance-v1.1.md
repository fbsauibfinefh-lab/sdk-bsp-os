# 无 SDK 训练的语义排序与确定性自动接受（v1.1）

> 历史方案：当前 v1.2 已取消选择性接受、拒答和覆盖率指标。本文件仅保留版本演进记录，现行方法见 `docs/deterministic-ranking-low-score-diagnostics-v1.2.md`。

## 1. 边界

当前项目和论文主线不包含 SDK 监督训练、训练真值构造和学习式字段门控。冻结的 `all-MiniLM-L6-v2` 只负责五字段语义表示；其参数不使用项目 SDK 更新。源码角色、操作契约、通用操作适配度、层级回退、API 家族解码和自动接受证书均为确定性方法。分级真值仅用于离线计算 P@1、Recall@K、MAP、nDCG 和选择性精度。

历史学习实验继续保留在 `research-status.md`，用于说明版本演进，不进入当前论文方法、贡献列表或主结果。

## 2. 0.38 覆盖率不等于上板通过率

旧自动接受覆盖率 0.38 表示 50 个操作中只有 19 个被旧置信阈值直接写入绑定计划，其余 31 个选择弃权并保留候选。它不表示只有 38% 的功能正确，也不表示另外 62% 上板一定失败。弃权项可能首位正确、Top5 中存在正确实现，或者在人工确认后可正常生成代码。

上板通过还取决于四类后续条件：函数参数和返回值适配是否正确；时钟、引脚复用和中断初始化顺序是否正确；头文件、源码、宏、链接脚本和启动文件闭包是否完整；外设实例与实物连线是否匹配。因此，排序/接受指标衡量的是“能否可靠选择 SDK API”，编译衡量“工程资产是否闭合”，实板回归才衡量“行为是否正确”。三者不能互相替代。

## 3. 旧置信度问题

旧方法在 q4 解码产生的合成名次分数上计算首二差值。该分数表示候选位置，不是原始语义决策分数；候选数量变化会改变归一化间隔，使同一证据在不同 SDK 上得到不同置信度。旧阈值还依赖开发集校准，容易受弱真值口径影响。

v1.1 改为在真正决定首位的连续分数上计算唯一符号间隔：

```text
S_precision = 0.50 * S_static + 0.50 * S_field
S_hierarchy = 0.25 * (S_static + S_field + S_contract + S_layer)
S_certified = S_hierarchy + 0.16 * S_generic + 0.05 * S_role
margin = S_decision(top1) - max S_decision(other unique symbols)
```

未触发回退时 `S_decision=S_precision`，触发契约回退时 `S_decision=S_certified`。

## 4. 通用操作适配度

RTOS 设备模型要求的是通用 UART、GPIO、定时器、时钟和中断操作，而 SDK 中同时存在大量专用模式 API。单纯语义相似会使 `HAL_TIMEx_PWMN_Start_DMA`、`HAL_TIMEx_HallSensor_Init`、`LL_USART_ClockInit` 或领域专用 IRQ handler 抢占通用实现。

`generic-operation-fit` 根据动作、能力根、控制器证据和专用模式计算固定分数：

- 动作证据：`init/config/setup`、`start/enable`、`register/vector` 等；
- 通用能力根：`clock/rcc/sysctl`、`timer/tim/base`、`plic/nvic/sysint` 等；
- 专用模式惩罚：PWM、Hall、Encoder、LPTimer、外设专用时钟、领域专用中断 handler；
- 可调用层证据：公共 HAL、SDK driver、vendor low-level 等源码角色。

当契约候选比纯精度候选具有显著更强的操作契约、通用适配度或公共层证据时，系统回退到 `S_certified`。回退门控使用固定差值和冲突检查，不从真值训练。

## 5. 确定性证据证书

系统对最终首位计算八个通道的首选：静态、字段语义、操作契约、层级路由、RRF、精度融合、证书层级和契约融合，并计算实体一致率与 API 家族一致率。

共识证书要求同时满足：

1. 源码角色先验不低于 0.78；
2. 操作契约不低于 0.45；
3. RRF 支持不低于 0.75；
4. 实体一致率不低于 0.375、家族一致率不低于 0.625或真实决策间隔不低于 0.005，三者至少一项成立。

强契约证书用于通道排名不一致但领域证据充分的情况，要求操作契约不低于 0.75、通用操作适配度不低于 0.80、源码角色不低于 0.90且 RRF 不低于 0.50。该证书可接受 `HAL_TIM_Base_Start` 一类契约明确但词法通道被众多专用模式分散的 API。

不满足证书时系统仍输出 Top5 和逐项证据，但状态为 `abstained`，不自动写入最终绑定。

## 6. 当前结果

以下表格保留 v1.1 当时按每套真值中全部可达查询组计算的历史结果；对应机器可读输出已由 v1.2 全量 Top1 报告替代。

| 真值 | SDK数 | 查询组 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 自动分级真值 | 25 | 450 | 0.662 | 0.495 | 0.557 | 0.623 |
| H01 | 23 | 328 | 0.381 | 0.552 | 0.460 | 0.517 |
| H02 | 23 | 331 | 0.414 | 0.522 | 0.476 | 0.525 |

| 真值 | 接受数/分母 | 覆盖率 | 已接受部分精度 |
| --- | ---: | ---: | ---: |
| 自动分级真值 | 191/450 | 0.424 | 0.702 |
| H01 | 168/328 | 0.512 | 0.446 |
| H02 | 169/331 | 0.511 | 0.473 |

三套板卡SDK的50组诊断子集得到P@1 1.000、Recall@5 0.936、MAP 0.923和nDCG@10 0.960，证书接受49/50。由于该子集直接参与过规则错误分析，它不能作为总体指标，也不能用50作为总体覆盖率分母。

## 7. 结果边界与投稿协议

全量结果表明当前方法尚未达到预设排序指标，证书也未达到0.95选择性精度。H01/H02可能没有穷举功能等价API，自动真值也可能存在规则偏差，但这些问题必须通过候选并集复核、双人仲裁和一致性统计解决，不能通过只报告板卡子集规避。真值修订后应重新冻结规则并增加一次性独立确认测试，完整报告排序指标、选择性精度—覆盖率、失败类型、编译结果和实板结果。

## 8. 历史复现说明

以下命令记录 v1.1 当时的数据生成入口。当前工作树已经移除选择性接受实现，直接运行现行评测器会生成 v1.2 的全量 Top1 与低分诊断口径。

```bash
cd /home/whk/RTT-porting/bspforge
conda activate AIoT-v1.0

python scripts/add_structured_retrieval_scores.py \
  --dataset experiments/generated/truth-set-rerun-20260828/fair-dataset-automatic-v0.9-field.json \
  --output experiments/generated/deterministic-no-training-v1.1-structured.json

python scripts/evaluate_deterministic_ranker.py \
  --dataset experiments/generated/deterministic-no-training-v1.1-structured.json \
  --role all \
  --output experiments/operation-ranking/historical-v1.1-automatic-all.json
```

历史运行时核心文件曾包括 `bspforge/structured_retrieval.py` 和已移除的 `bspforge/selective_acceptance.py`；现行实现见 `bspforge/ranking_diagnostics.py`。
