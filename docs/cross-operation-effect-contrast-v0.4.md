# 跨操作效果对比与结构一致性探索 v0.4

## 1. 开发目的

v0.3 的 98 条 Top1 错误中有 26 条属于同一 API 家族内的动作混淆。典型情况是候选函数已经定位到 UART、GPIO 或 Timer，但 `read/write`、`enable/disable`、`start/stop` 的相对顺序错误。v0.4 沿寄存器效果图和结构契约路径继续开发，不修改 Migration IR、闭包求解或 OS Backend。

本轮提出两个相互独立的无标签结构信号：

1. 跨操作效果对比：同一 SDK 实体在目标操作和同能力竞争操作下分别计算效果强度，使用目标效果差、成对动作效果差和动作选择性描述相对语义。
2. API 家族一致性：恢复动作无关的 API 家族，统计家族覆盖操作、互补动作、公共边界、源码角色和专用模式风险。

所有统计只读取当前 SDK 的候选、源码图和 IR 特征，不读取 `label`、H02 真值或其他 SDK 的标签。测试 SDK 的无标签内部结构可以在部署时直接恢复，不构成训练测试泄漏。

## 2. 数据流

```text
v0.3 硬件效果数据集
  -> 以 (sdk_id, entity_id) 聚合 19 个操作下的效果画像
  -> 计算目标操作与竞争操作的效果差
  -> 恢复动作无关 API 家族并统计结构一致性
  -> 选择 effect-contrast / contrast / family / all 特征集
  -> 固定配置消融或厂商独立嵌套 LambdaMART
  -> 可选的两专家内层权重融合
```

核心实现为 `bspforge/cross_operation_coherence.py`。`scripts/add_cross_operation_coherence_features.py` 生成特征数据集，`scripts/evaluate_cross_operation_coherence_ablations.py` 执行固定配置消融，`scripts/evaluate_cross_operation_ensemble.py` 只在每个外折的内层验证 SDK 上选择融合权重。

## 3. 特征定义

### 3.1 已验证的效果对比

- `xop-effect-margin`：目标操作效果减去同能力最强竞争操作效果。
- `xop-paired-effect-margin`：目标操作效果减去显式互补操作效果。当前成对操作包括 UART/GPIO 读写、Clock/Interrupt 使能禁用、Timer 启停及 Timer 初始化/周期设置。
- `xop-action-selectivity`：目标操作效果占该实体同能力全部操作效果之比。

这三项不回答“函数是否属于 UART”，而回答“已经属于 UART 的函数更像写还是读”。

### 3.2 未进入最终方法的探索特征

多信号对比进一步计算契约、符号词法和通用适配度的目标-竞争差，以及四类信号的均值和一致比例。API 家族分支统计软/硬操作覆盖、互补动作支持、公共边界比例、角色一致性和专用模式风险。

这些特征在部分折上有效，但没有在严格嵌套评测中稳定超过 v0.3。原因是契约和词法差分会放大厂商命名习惯，家族恢复又可能把不同抽象层的完整 API 集合视为同等合理。因此它们只作为负向或探索性消融，不进入论文核心方法。

## 4. 实验结果

评测仍使用 H02 中 281 个具有可达函数正例的查询，外层按 18 个厂商或上游独立组五折划分。

### 4.1 固定 small-bagged 公平消融

| 方法 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| v0.3 同配置基线 | 0.637 | 0.767 | 0.680 | 0.747 |
| + 三项效果对比 | **0.662** | 0.756 | **0.690** | **0.752** |
| + API 家族一致性 | 0.655 | 0.764 | 0.689 | 0.753 |
| 两类全部加入 | 0.651 | 0.762 | 0.687 | 0.749 |

三项效果对比的 P@1 提升为 0.0249，查询级 bootstrap 95% 区间为 `[0.0036, 0.0498]`；MRR 提升 0.0141，区间为 `[0.0009, 0.0273]`。Recall@5 下降的区间跨 0。API 家族分支和全部组合的各项提升区间大多跨 0，不能声明稳定有效。

### 4.2 严格嵌套与融合

三项效果对比单独进入完整嵌套模型后为 `0.641/0.755/0.680/0.743`，没有超过 v0.3 的 `0.651/0.748/0.681/0.743`。增加契约和词法对比后进一步降至 `0.633/0.743/0.672/0.733`。

嵌套选择的秩百分位双专家融合相对同脚本 v0.3 固定基线从 `0.655/0.759/0.686/0.749` 微升至 `0.658/0.765/0.686/0.749`，但四项区间均跨 0。该融合不能升级为论文主结果。

## 5. 错误变化与结论

严格三项效果对比模型有 180/281 个 Top1 正确，错误 101 条；同族动作混淆为 27 条，并未稳定低于 v0.3 的 26 条。完整错误见 `docs/cross-operation-effect-contrast-error-report-v0.4.md`。

本轮开发得到的可靠结论是：跨操作效果差可以作为轻量纠错信号，在固定配置下显著提高 Top1；但小数据下的模型选择方差使该收益尚不能通过严格嵌套确认。当前论文主结果继续使用 v0.3。v0.4 适合作为“沿结构语义继续探索”的完整消融，不能表述为已经替换主方法的升级。

## 6. 复现命令

```bash
conda activate AIoT-v1.0

python scripts/add_cross_operation_coherence_features.py \
  --input experiments/generated/hardware-effect-h02-v0.1.json \
  --output experiments/generated/hardware-effect-h02-v0.4-effect-contrast.json \
  --feature-set effect-contrast

python scripts/evaluate_cross_operation_ensemble.py \
  --dataset experiments/generated/hardware-effect-h02-v0.4-effect-contrast.json \
  --base-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --base-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --focused-metadata experiments/generated/jina-multiview-effect-h02-v0.3.json \
  --focused-vectors experiments/generated/jina-multiview-effect-h02-v0.3.npz \
  --output experiments/operation-ranking/results-cross-operation-ensemble-h02-v0.4.json
```
