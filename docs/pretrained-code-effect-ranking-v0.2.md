# 冻结预训练代码模型增强的硬件效果排序 v0.2

## 1. 目标与实验边界

本方案用于回答一个限定问题：给定规范化能力操作，例如 `uart.write` 或 `timer.set_interval`，能否在陌生芯片 SDK 的函数候选中，把 H02 认可的可迁移 API 排到前面。它是相对于 v0.1 寄存器效果图方案的独立升级分支，不读取现有 q4 字段软分数，也没有替换当前 Resolver 运行时默认方法。

本轮暂不处理“一个操作没有单一稳定公共函数”的接口形态。H02 的 418 个训练角色操作组中，137 个 `no_public_api` 组被数据构建阶段排除；主实验只评估 281 个具有可达函数正例的训练角色查询。三套拟上板 SDK 的 50 个查询保持外部诊断角色，不参与训练、嵌套校准或主指标。

## 2. 为什么选择该模型

冻结编码器使用 `jinaai/jina-embeddings-v2-base-code`：

- 权重提交：`516f4baf13dec4ddddda8631e019b5737c8bc250`；
- 远程模型代码提交：`3baf9e3ac750e76e8edd3019170176884695fb94`；
- 主干约 1.61 亿参数，输出 768 维向量；
- Apache-2.0 许可，权重不复制进本仓库；
- 模型面向自然语言与代码嵌入，适合直接编码 C/C++ 函数体和操作描述；
- 本项目把最大长度限制为 256 token，并在普通 CPU 上离线运行。

模型主页和许可见 <https://huggingface.co/jinaai/jina-embeddings-v2-base-code>。下载脚本固定权重和远程代码版本，避免上游更新改变实验结果。当前远程模型代码与 Transformers 5.x 不兼容，因此 `pyproject.toml` 将可选依赖固定为 `transformers>=4.34,<5` 和 `sentence-transformers>=3.0,<4`。

## 3. 完整数据流

```text
H02 函数级真值 + hardware-effect H02 数据集
                    |
                    v
      SDK Migration IR + SDK 原始源码
                    |
                    v
       查询序列化 / 候选函数序列化
                    |
                    v
       冻结 Jina 代码编码器（仅离线）
                    |
                    v
     19 个查询向量 + 22,932 个实体向量缓存
                    |
                    v
   低秩查询适配 + 22 维硬件效果图分支
                    |
                    v
  H02 正例-未标注查询内偏好训练（PU ranking）
                    |
                    v
  训练 SDK 内部验证选择代码/图融合比例
                    |
                    v
       厂商独立五折 OOF 排序与错误报告
```

向量缓存键为 `sdk_id::entity_id`。同一个 SDK 函数即使出现在多个操作候选池中也只编码一次；查询缓存键为 19 个规范化 `operation_id`。标签只进入偏好对构造和离线指标计算，不进入文本序列化或冻结编码器。

## 4. IR 感知输入序列化

### 4.1 操作查询

查询由能力、动作、别名和 API 选择偏好组成。例如 `uart.write` 包含：

- 能力语义：UART、串行端口、波特率、帧格式和 FIFO；
- 动作语义：写入或发送负载数据；
- IR 契约别名；
- 选择约束：优先稳定公共 C/C++ SDK API，避开示例、状态查询、相反动作和中间件入口。

这不是只用操作名做向量检索，而是把 Migration IR 中的规范操作契约转成模型可处理的自然语言查询。

### 4.2 候选函数文档

每个候选由下列字段组成：

| 字段 | 来源 | 作用 |
| --- | --- | --- |
| `symbol` | IR 函数实体 | 保留厂商 API 命名线索 |
| `signature` | IR 函数实体 | 区分读写方向、回调、开关和配置参数 |
| `file/source_role` | IR 与图特征 | 区分公共 HAL、底层驱动、示例、测试和适配器 |
| `calls` | IR 调用边 | 表示候选向下调用的效果实现 |
| `includes` | IR 包含关系 | 补充模块和设备族上下文 |
| `register identifiers` | 硬件效果图 | 提供寄存器、字段和外设类型锚点 |
| `normalized function body` | SDK 源码 | 让模型读取实际实现，而不只看暴露名称 |

函数体先删除注释，再把字符串、字符、十六进制常量和数值字面量替换为稳定占位符，压缩空白并截断到 2,200 字符；编码器最终按 256 token 截断。该归一化降低芯片地址和常量值对跨 SDK 表示的干扰，但保留控制流、被调函数和寄存器标识。

## 5. 冻结编码与缓存

编码器不参与 H02 训练。对 token 隐状态执行 attention-mask mean pooling，再进行 L2 归一化：

```text
e(x) = normalize(sum_t mask_t * h_t / sum_t mask_t)
```

全量缓存结果：

| 项目 | 数值 |
| --- | ---: |
| SDK | 23 |
| 唯一函数实体 | 22,932 |
| 操作查询 | 19 |
| 向量维度 | 768 |
| 未匹配 IR 实体 | 0 |
| 首次 CPU 编码耗时 | 6,351.642 秒 |
| 缓存后完整嵌套五折评测 | 137.650 秒 |
| 压缩向量文件 | 约 32 MiB |
| 元数据文件 | 约 2.6 MiB |

向量以 `float16` 保存，加载后恢复为 `float32` 参与排序。元数据记录数据集 SHA-256、权重 SHA-256、每个序列化文档的 SHA-256、模型提交、维度、长度和耗时。首次编码是离线建库成本；调学习率、适配器或融合结构时直接复用缓存。

## 6. 轻量任务适配

### 6.1 低秩查询残差

冻结候选向量不变，只对 19 类操作查询学习秩 8 残差：

```text
q' = normalize(q + W_up tanh(W_down q))
s_code = cosine(q', d)
```

其中 `W_down` 为 `768 x 8`，`W_up` 为 `8 x 768`。`W_up` 零初始化，因此训练起点严格等于零样本编码器。低秩适配只改变“如何表达 SDK 操作需求”，不会为每个 SDK 保存专用向量。

### 6.2 硬件效果图分支

v0.1 生成的 22 维图特征继续复用，包括直接/跨过程寄存器效果、锚点距离、公共 API 边界、签名契约、操作冲突、复合入口、示例/测试/OS 适配角色等。图分支为 `22 -> 12 -> 1` 的 Tanh 网络，并保留相反动作、反向适配、测试示例等硬约束惩罚。

### 6.3 操作门控与参数规模

模型还包含 19 类操作的三路门控和一个线性融合头。全部可训练参数为 12,636：

| 部分 | 参数量 |
| --- | ---: |
| 秩 8 查询残差 | 12,288 |
| 22->12->1 图分支 | 288 |
| 19x3 操作门控 | 57 |
| 三路融合 | 3 |
| 合计 | 12,636 |

预训练主干约 1.61 亿参数全部冻结，训练和交叉验证不需要重新加载主干。最终全量轻量头训练为 15.203 秒；包含五个内部校准模型、五个外折模型、最终模型、逐查询打分和配对统计的完整缓存后评测为 137.650 秒。

## 7. 正例-未标注偏好训练

对同一查询，H02 中 `label > 0` 的函数 A 是正例，`label == 0` 的函数 B 只视为未标注。训练目标是 A 应排在 B 前，而不是声明 B 一定是语义负例：

```text
L_pair = w(A, B) * softplus(-(s(A) - s(B)))
```

每个正例最多与 8 个图启发式高分难例和 8 个确定性随机未标注项组成偏好对。高分未标注项更可能是 H02 漏标的功能等价 API，因此其约束权重较低。全量训练角色数据形成 9,872 个偏好对，批大小 192，AdamW 学习率 0.0035，默认训练 32 轮。

这种 PU 目标能降低“不完整真值被强制当作负例”的风险，但不能保证真值只要准确就不会偏差：正例覆盖不足仍会影响难例采样和评测，跨厂商结构差异、候选层级、函数体截断和模型表征上限也会造成误排。

## 8. 嵌套校准融合

直接联合学习的图融合在部分外折过拟合。为此，最终 v0.2 不直接使用学习融合分数，而是对每个查询分别标准化适配代码分数与受硬约束保护的图分数：

```text
s_final = alpha * z(s_code) + (1 - alpha) * z(s_graph)
```

`alpha` 只能从 `{0.50, 0.65, 0.80, 0.90, 1.00}` 选择。对每个外层五折，系统只在该折的训练 SDK 内再按独立厂商组划分内部验证集，以 `mean(P@1, Recall@5, MAP, nDCG@10)` 选择 `alpha`，然后用外层训练数据训练模型并评估从未参与选择的外折。

五个外折选择的代码权重依次为 0.80、0.80、0.90、0.65 和 0.80。最终全训练模型的内部验证选择 0.80。该步骤属于嵌套模型选择，不读取外层测试标签。

## 9. 评测协议

- 真值：仅 H02；
- 主数据：281 个训练角色函数查询；
- 分组：18 个独立厂商/上游组；
- 外层：五折 independence-group 交叉验证；
- 指标：P@1、Recall@3/5、MRR、MAP、nDCG@10；
- 统计：281 个 OOF 查询上的 4,000 次配对 bootstrap；
- 外部诊断：K210、STM32F103、PSoC E84 共 50 组，完全排除于训练和校准；
- 排除项：137 个 `no_public_api` 组，不进入本轮模型和分母。

这里的主指标是每个查询都由没有见过该独立厂商组的模型产生的 OOF 结果，不是把所有 SDK 混合随机切分。

## 10. 指标结果

### 10.1 主结果与消融

| 方法 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 现有 q4（同一 281 组） | 0.310 | 0.448 | 0.396 | 0.447 |
| v0.1 寄存器图 PU 残差 | 0.335 | 0.528 | 0.432 | 0.506 |
| Jina 零样本 | 0.399 | 0.568 | 0.480 | 0.549 |
| Jina + 低秩查询适配 | 0.427 | 0.610 | 0.517 | 0.583 |
| Jina + 联合学习图融合 | 0.427 | 0.628 | 0.508 | 0.590 |
| **Jina + 嵌套校准图融合** | **0.495** | **0.653** | **0.565** | **0.639** |

结果支持三个结论：

1. 零样本预训练代码表示已经明显好于从零训练的 728 参数图模型，说明读取实现内容具有独立价值。
2. 12,636 参数的任务适配使零样本 P@1、Recall@5、MAP 和 nDCG@10 分别提高 0.028、0.042、0.037 和 0.034。
3. 直接学习融合的 MAP 略低于仅适配模型；训练 SDK 内嵌套校准后四项均继续提高，说明图证据需要受控融合，不能假设联合训练自然泛化。

### 10.2 相对 v0.1 的配对提升

| 指标 | 平均增量 | 95% bootstrap CI | 胜/平/负查询 |
| --- | ---: | --- | --- |
| P@1 | +0.160 | [0.093, 0.228] | 72/182/27 |
| Recall@5 | +0.125 | [0.071, 0.178] | 89/150/42 |
| MAP | +0.133 | [0.090, 0.176] | 155/45/81 |
| nDCG@10 | +0.134 | [0.092, 0.175] | 146/65/70 |

四项区间均不跨 0，可以报告在当前 H02、当前候选池和该分组协议下相对 v0.1 的显著正向提升。结果仍未达到此前设定的 P@1 0.80、Recall@5 0.90、MAP/nDCG@10 0.80 目标，不能写成已经解决跨 SDK 语义定位。

### 10.3 外部板卡诊断

嵌套校准模型在 50 个板卡组上的 P@1/Recall@5/MAP/nDCG@10 为 0.320/0.676/0.443/0.539；零样本为 0.440/0.726/0.525/0.615。训练适配在该子集发生退化，而历史 q4 为 1.000/0.936/0.923/0.960。

这 50 组已被历史开发反复查看，不能作为干净确认集。当前结果说明 v0.2 尚不应直接替换三块板卡的 q4 运行路径，同时提示 H02 训练组与板卡 SDK 存在明显分布差异。正式论文应把厂商独立 OOF 作为主模型结果，把板卡组用于后续端到端和上板诊断。

## 11. 错误分析

v0.1 的 Top1 错误为 187/281，v0.2 降至 142/281：

| 归因 | v0.1 | v0.2 | 变化 |
| --- | ---: | ---: | ---: |
| 排序模型混淆 | 59 | 57 | -2 |
| 同 API 家族动作混淆 | 61 | 37 | -24 |
| 真值效果路径缺失 | 33 | 21 | -12 |
| 抽象层不匹配 | 16 | 15 | -1 |
| 复合入口过排 | 10 | 8 | -2 |
| 效果强度混淆 | 6 | 4 | -2 |

错误下降主要来自同族动作区分和函数体语义补充，但 57 个一般排序混淆仍是最大类别。最弱操作包括 `timer.set_interval`（P@1 0.200）、`clock.initialize`（0.231）、`clock.enable`（0.333）和 `gpio.attach_irq`（0.375）；较强操作包括 `uart.read`（0.789）、`uart.configure`（0.765）和 `interrupt.enable`（0.692）。

完整 142 条错误逐项记录系统 Top1、Top5、H02 真值、正例名次、文件、图锚点和效果路径，见 `docs/pretrained-code-effect-error-report-v0.2.md` 与 `experiments/operation-ranking/results-pretrained-effect-h02-v0.2-errors.json`。

## 12. 工程文件职责

| 文件 | 职责 |
| --- | --- |
| `bspforge/code_effect_encoder.py` | 操作查询、函数文档序列化、代码归一化、冻结编码和缓存读取 |
| `bspforge/pretrained_effect_ranker.py` | 低秩查询适配、图分支、操作门控、融合网络和模型持久化 |
| `scripts/download_pretrained_code_model.py` | 固定提交下载模型并校验可加载性 |
| `scripts/cache_pretrained_code_embeddings.py` | 从数据集、IR 和源码建立唯一实体向量缓存及哈希元数据 |
| `scripts/evaluate_pretrained_effect_ranker.py` | PU 训练、厂商独立五折、嵌套校准、外部诊断、配对统计和模型保存 |
| `scripts/generate_hardware_effect_error_report.py` | 生成逐查询错误归因、操作/SDK 统计和机器记录 |
| `experiments/generated/jina-code-embeddings-h02-v0.2.json` | 模型、数据、序列化文本和向量文件的可审计元数据 |
| `experiments/generated/jina-code-embeddings-h02-v0.2.npz` | 19 个查询与 22,932 个唯一实体的压缩向量 |
| `models/pretrained-effect-h02-v0.2.pt` | 56 KiB 的最终轻量排序头、标准化量和缓存契约 |
| `experiments/operation-ranking/results-pretrained-effect-h02-v0.2.json` | 全部折、逐查询、统计和外部诊断结果 |

## 13. 复现命令

```bash
cd /home/whk/RTT-porting/bspforge
conda activate AIoT-v1.0

python scripts/download_pretrained_code_model.py \
  --output /home/whk/RTT-porting/models/jina-embeddings-v2-base-code

python scripts/cache_pretrained_code_embeddings.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --model /home/whk/RTT-porting/models/jina-embeddings-v2-base-code \
  --output-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --output-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --batch-size 16 --max-length 256 --threads 8

python scripts/evaluate_pretrained_effect_ranker.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --embedding-metadata experiments/generated/jina-code-embeddings-h02-v0.2.json \
  --embedding-vectors experiments/generated/jina-code-embeddings-h02-v0.2.npz \
  --v01-results experiments/operation-ranking/results-hardware-effect-pu-h02-v0.1.json \
  --output experiments/operation-ranking/results-pretrained-effect-h02-v0.2.json \
  --output-model models/pretrained-effect-h02-v0.2.pt

python scripts/generate_hardware_effect_error_report.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --results experiments/operation-ranking/results-pretrained-effect-h02-v0.2.json \
  --method pretrained-code-calibrated-fusion \
  --output docs/pretrained-code-effect-error-report-v0.2.md \
  --output-json experiments/operation-ranking/results-pretrained-effect-h02-v0.2-errors.json
```

## 14. 当前判断与下一步

该实验验证了建议模型和任务适配方向确有价值：预训练代码表示、函数体输入和低秩适配均带来可分离的提升，嵌套校准进一步修复了直接图融合的泛化不稳定。它比 v0.1 更适合作为论文中的模型方法候选，但当前绝对指标仍不足以独立承担“可靠自动绑定”的结论，且板卡诊断退化明显。

下一步优先级应为：

1. 针对计时器周期、时钟初始化和 GPIO 中断构造动作对比学习样本，强化同族细粒度操作边界；
2. 将 256-token 单段编码改为字段或代码块迟交互，避免长函数体和前缀争夺截断预算；
3. 对 Bouffalo、SiFli 和 Renesas 的错误做人工分层复核，区分模型错误、真值遗漏和候选层级不一致；
4. 在未参与本轮开发的新厂商 SDK 上执行一次性确认，之后再决定是否接入 Resolver 默认路径；
5. 后续单独扩展宏、配置对象、回调槽和 API 序列目标，不能把本轮函数排序指标外推到 `no_public_api` 组。
