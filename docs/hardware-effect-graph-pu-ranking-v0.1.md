# 寄存器效果锚定的跨过程语义图与正例-未标注偏好排序 v0.1

## 1. 方案定位

本方案针对仅依赖函数名、签名和文件路径时跨 SDK 泛化不足的问题，从函数实际执行内容恢复硬件效果。核心假设不是“反向调用图最顶层一定是目标 API”，而是：可迁移 SDK API 通常位于一条可解释的效果路径上，该路径由公共接口经过若干层调用到达寄存器、MMIO 或底层控制实体；候选所处的抽象层级、效果纯度和接口角色共同决定其是否适合作为操作绑定。

v0.1 作为独立实验方案实现和评估，不改写 `operation-structured` 的 q4 运行时决策，也不读取 q4 的软分数或字段迟交互分数。后续只有在独立结果和消融边界稳定后，才考虑把硬件效果图作为现有方法的新增证据通道。

从论文角度看，该方向比单纯调整函数名、路径和签名权重更有创新空间，因为它把判断依据推进到“代码最终产生什么硬件效果”，并能输出寄存器到公共 API 的证据路径。不过，当前实验只证明了 Recall@5 和 nDCG@10 的互补收益，尚未证明该方法在所有 SDK 上具有更高泛化性能。“理论上限更高”在本文中应表述为“表示能力上限更高”：函数暴露信息相同或混淆时，函数体、调用关系和寄存器效果仍可能区分候选；不能把它写成已经由当前指标证实的结论。

## 2. 输入与输出

### 2.1 输入

- SDK Migration IR：函数实体、源码位置、签名、调用边和包含关系。
- SDK 源码根目录：用于按 IR 行号回读完整函数体。
- 操作查询：`capability.operation`，当前覆盖五类能力的 19 个规范化操作。
- H02 人工真值：只在训练和评测阶段使用，不参与图特征生成。

### 2.2 中间结果

每个候选增加 `hardware_effect_evidence`：

```json
{
  "status": "analyzed",
  "effect_path": ["uart_send_data", "uart_channel_putc"],
  "register_hits": ["UART0->THR"],
  "anchor_depth": 1,
  "capability_effects": {"uart": 0.72, "gpio": 0.0}
}
```

同时增加 22 个 `hw-*` 数值特征，数据文件为 `experiments/generated/hardware-effect-h02-v0.1.json`。

### 2.3 输出

- 728 参数的轻量排序器：`models/hardware-effect-pu-h02-v0.1.pt`。
- 五折跨独立组结果：`experiments/operation-ranking/results-hardware-effect-pu-h02-v0.1.json`。
- 每个查询的 Top5、逐折结果、SDK 分项结果和相对 q4 的配对 bootstrap 区间。

## 3. 完整工作流程

### 3.1 阶段 A：输入固定与实验隔离

#### 步骤 A1：固定操作本体

系统从 `CAPABILITY_SCHEMA` 读取五类能力和 19 个规范化操作。每个查询使用 `capability.operation` 作为稳定 ID，例如 `uart.write`。操作本体只描述 SDK 侧需要恢复的硬件原语，不直接等同于某个 RTOS 驱动 API。

输入是能力、操作名和动作别名；输出是操作契约以及后续所有实体共用的查询 ID。若操作本体过粗，例如把一次性定时、周期定时和 PWM 都视为 `timer.set_interval`，后续模型即使正确理解代码也可能得到相互冲突的标签。因此操作本体是方法误差的第一层来源。

#### 步骤 A2：固定 SDK、源码版本和 IR

`manifest.json` 为每套 SDK 固定源码根目录、版本、厂商、独立性分组和实验角色。系统读取 `workspace/operation-ir/<sdk>/<digest>/sdk-ir.json`，并检查数据集中的 `entity_id` 能否回指该 IR。

输入是 manifest、源码树和版本化 IR；输出是 SDK 到源码、函数实体、文件实体和调用边的确定映射。源码版本或 IR digest 不一致时应停止，而不是在新源码上复用旧标签。

#### 步骤 A3：对齐 H02 正例和未标注候选

数据集中的 `label > 0` 映射为已审计正例，`label == 0` 映射为未标注。候选先按 `symbol` 去重，同名多定义优先保留标签等级高、硬件效果证据强且实体 ID 稳定的定义。H02 的 1/2/3 级只用于评测相关性，当前 PU 训练不学习三个等级之间的顺序。

输入是 H02 与候选实体；输出是每个查询的正例集合 `P_q` 和未标注集合 `U_q`。没有可达正例的 `no_public_api` 查询不进入函数排序指标，而是进入第 8 节的多实体定位问题。

### 3.2 阶段 B：标签无关的硬件效果恢复

#### 步骤 B1：回读函数体

系统使用 IR 中的文件、行号和名称在源码中定位定义，再通过识别注释、字符串和字符字面量的括号平衡扫描提取完整函数体。C++ 方法同时索引限定名和末段名称。函数体按实体缓存，任何 H02 标签都不参与该步骤。

输出包括函数体文本、标识符、成员访问、被调函数、赋值、位操作和 MMIO 证据。定位失败时保留空函数体和 `missing-body` 诊断，不能以函数名猜测补写函数体。

#### 步骤 B2：建立寄存器与动作目录

系统扫描候选相关头文件中的地址宏、位掩码、`volatile/__IO` 结构体字段、CMSIS-SVD 外设描述和函数原型。每个寄存器实体被映射到能力及更细的操作效果，例如 UART `THR/TDR/TXBUF` 对应发送，`RBR/RDR/RXBUF` 对应接收，`IER/IRQ` 对应中断控制。

输出是 `register -> {capability, action, evidence_source}` 目录和公共原型集合。目录未识别某个厂商命名时，后续真值路径可能为零；完整错误报告中的 `truth-path-missing` 主要来自此处及调用边缺失。

#### 步骤 B3：构建跨过程调用图

每个 IR 函数是图节点，函数调用是有向边。名称存在多个提供者时，按共同目录深度、同文件行号距离和稳定实体 ID 选择提供者。类方法同时解析 `Class::method` 和 `method`。函数指针、宏展开、条件编译后才出现的调用当前不能完整恢复，并作为已知限制记录。

输出是 `caller -> callee` 邻接表、反向调用计数、caller fan-in 和 callee fan-out。

#### 步骤 B4：计算直接硬件效果

对于候选函数 `f` 和操作 `q=(capability, action)`，系统组合能力证据、函数体动作、读写方向、寄存器锚点和寄存器动作类型得到 `E_direct(f,q)`。计算对全部 19 个操作执行，因此同一函数可同时具有 UART、中断或定时器等多种效果。

输出是每个函数对每个操作的直接效果、寄存器命中项和读写/位操作特征。一个函数写寄存器不等于满足任意写操作；寄存器动作目录用于避免将 UART 中断使能误当成 UART 数据发送。

#### 步骤 B5：传播跨过程效果

系统从候选沿 `callee` 方向最多搜索三层。每跨一层乘以 0.78 衰减，保留分数最高的证据路径。访问集合截断递归调用。

输出包括 `E_graph`、首次寄存器锚点深度和最多六个节点的 `effect_path`。例如公共 `uart_send_data` 自身不写寄存器，但可通过 `uart_channel_putc` 到达 TX 寄存器，因此获得非零传播效果。

#### 步骤 B6：识别 API 边界和图角色

系统不假定反向图顶层就是目标 API，而是同时计算公共头文件原型、锚点距离、签名契约、效果纯度、能力广度、内部回调、静态内部函数、示例、OS 适配层和复合入口等角色。

示例程序、应用初始化和中间件入口通常表现为能力广度高、扇出大或位于 example/application 路径；内部 ISR/handler 表现为特殊名称和静态角色；稳定公共包装通常具有公共声明、目标动作契约和适中的锚点距离。这些信息进入排序特征，而不是用单条规则直接删除候选。

### 3.3 阶段 C：PU 偏好训练

#### 步骤 C1：形成 22 维候选向量

每个查询-候选对序列化为 22 个 `hw-*` 特征，包括直接/传播效果、寄存器锚点、API 边界深度、能力/动作效果、纯度/广度、访问类型、图度数和角色特征。训练折计算均值和标准差，测试折只能使用训练折统计量。

#### 步骤 C2：构造查询内偏好对

对每个正例，从未标注集合中选取图启发式最高的 8 个困难候选和最多 8 个确定性随机候选，形成 `positive > unlabeled`。高图分未标注项更可能是漏标等价 API，其损失权重会降低，但不会被声明为确定负例。

本轮 281 个有效训练角色查询形成 9,872 个偏好对。随机种子同时包含查询 ID，保证某一 SDK 的候选变化不会改变其他 SDK 的随机负例。

#### 步骤 C3：训练轻量排序器

22 维标准化向量经过操作门控、线性分支和 12 单元非线性残差，使用加权 pairwise softplus 损失训练 36 轮。优化器为 AdamW，梯度范数限制为 2.0。

输出是 728 参数模型、特征均值/方差、损失历史和训练对统计。模型只学习查询内相对顺序，不学习某个绝对“正确概率”。

### 3.4 阶段 D：推理、保护和评测

#### 步骤 D1：候选推理

对一个新 SDK，B1 至 B6 在不需要标签的情况下生成特征，训练好的模型为每个候选给出 `s_PU`。查询内图启发式标准化后以 0.35 权重形成残差，避免小模型完全抹去硬件路径强度。

#### 步骤 D2：施加硬约束

反义操作、语义冲突、反向 OS 适配和测试示例的最大风险值乘以 4，从最终分数中扣除。硬约束只阻止已知错误方向，不能弥补真值路径缺失或操作本体不完整。

#### 步骤 D3：稳定排序与证据输出

候选按最终分数降序、实体 ID 升序排列，同名符号只保留最高项。输出 Top1、Top5、全部真值排名、效果路径、寄存器命中和锚点深度，可回溯到源码。

#### 步骤 D4：跨独立组五折评测

18 个 independence group 被均衡分到五折。同厂商或共同上游 SDK 不跨训练折和测试折。每折重新拟合标准化器和 728 参数模型；281 个查询的最终结果均为 out-of-fold 预测。三块板卡的 50 个查询不参与训练，只保留历史诊断。

## 4. 硬件效果图构建

### 4.1 函数体恢复

`SourceCorpus` 根据 IR 的文件、行号和函数名定位定义，使用识别字符串、字符字面量、行注释和块注释的括号平衡扫描恢复函数体。每个函数体最多保留 50,000 字符，并按实体缓存，避免 19 个操作重复读取源码。

### 4.2 寄存器目录

`RegisterCatalog` 从候选相关头文件提取：

1. 带十六进制地址、`BIT()`、`volatile` 或寄存器提示词的宏；
2. CMSIS 风格的 `__IO`、`__IOM`、`volatile` 结构体字段；
3. SDK 内存在的 CMSIS-SVD 外设和寄存器描述；
4. 头文件函数原型，用于识别公共 API 边界。

目录同时标注能力和操作效果。例如 UART 的 `THR/TDR/TXBUF` 支持发送效果，`RBR/RDR/RXBUF` 支持接收效果，`IER/IRQ/ISR` 支持中断效果。这样可避免把“修改 UART 中断使能寄存器”误判为 `uart.write`。

### 4.3 直接效果

对函数体提取成员访问、已知寄存器标识符、读写赋值、位操作和 MMIO 证据。对于查询 `q=(c,o)`，直接效果由能力匹配、函数体动作、访问方向、寄存器锚点和寄存器操作类型加权得到：

```text
E_direct(f,q) = C(f,c) * (0.48*A(f,o) + 0.17*Access(f,o)
                          + 0.15*Register(f) + 0.20*RegisterAction(f,o))
```

这些系数只用于构造独立启发式和初始先验，学习排序器会在标准化特征上重新学习偏好。

### 4.4 跨过程传播

IR 的 `calls` 名称按同目录接近度、同文件行号接近度和稳定实体 ID 解析到函数实体。效果最多向调用者传播三层，每层乘以 0.78 衰减：

C++ 类方法在本阶段不强制改写源码，而是作为带隐式 receiver 的可调用实体处理；解析器同时索引限定名和末段方法名。后端若要求 C ABI，再依据实体签名生成薄包装函数。

```text
E_graph(f,q,d) = max(E_direct(f,q), 0.78 * max E_graph(callee,q,d-1))
```

输出同时保存产生最大效果的调用路径和首次寄存器锚点深度。循环调用通过访问集合截断。

### 4.5 API 层级与角色

直接写寄存器的叶子并不天然优于公共 SDK API。v0.1 因此将“存在硬件效果”和“候选是否是迁移接口”分开建模：

- `hw-api-boundary-depth` 偏好距锚点 1 至 2 层的公共封装，并保留直接 HAL 作为可能答案；
- `hw-public-boundary` 来自头文件定义或原型；
- `hw-signature-contract` 检查接口名称和签名是否同时满足能力与动作契约；
- `hw-internal-callback-likelihood` 标识 handler、ISR、callback、dispatch 等内部角色；
- `hw-effect-purity` 和 `hw-effect-breadth` 区分单一能力 API 与复合初始化、示例和中间件入口；
- caller fan-in、callee fan-out、example/test、OS adapter 和 static internal 进一步描述图角色。

这也落实了“复合顶层函数本身是一种信息”的判断：同时覆盖多类硬件效果且扇出较大的候选会提高 breadth/composite 特征，而不会被简单认定为目标操作。

## 5. 正例-未标注偏好学习

### 5.1 标签解释

H02 中 `label > 0` 表示已审计正例，`label == 0` 在本方案中解释为未标注候选，不声明它在语义上必然错误。训练不使用 1/2/3 之间的等级顺序；同一查询内所有已标注正例具有相同正例身份。

用户提出的“正函数 A 应排在未标注函数 B 前面”总体正确，但需要补充：一旦构造 `A > B`，B 就在该训练对中承担弱负例作用。如果 B 实际是漏标的等价 API，该偏好就是噪声。因此“真值中的正例准确”是必要条件，但不是充分条件；还需要较好的等价正例覆盖、可达候选、独立数据划分和漏标鲁棒训练。

### 5.2 训练对构造

对每个查询先按符号去重，然后：

1. 取全部 `label > 0` 的正例；
2. 从 `label == 0` 中取图启发式最高的 8 个困难未标注候选；
3. 再确定性抽取最多 8 个随机未标注候选；
4. 构造查询内偏好对 `positive > unlabeled`；
5. 对图分数很高、较可能是漏标正例的未标注候选降低损失权重。

本轮 281 个训练角色查询产生 9,872 个偏好对。训练损失为带 PU 置信权重的 pairwise softplus：

```text
L = mean(w_pu * softplus(-(s_positive - s_unlabeled)))
```

### 5.3 当前模型与硬约束

网络由操作门控、22 维线性分支和 12 单元非线性残差组成，总参数量 728。模型仅消费硬件效果图特征。反义操作、语义冲突、反向 OS 适配和测试示例等高风险候选在最终分数上施加固定惩罚，学习过程不能抵消这些硬约束。

最终独立分数使用查询内标准化的图启发式作为 0.35 权重残差：

```text
s_final = s_PU + 0.35 * z(s_graph) - 4 * hard_conflict
```

该残差仍完全属于新方案，不使用 q4 的软分数。

### 5.4 当前模型究竟是什么

当前模型不是下载的预训练代码模型，而是使用 PyTorch 从零训练的任务专用轻量网络。728 个参数由以下部分组成：

- 19 个操作的 22 维门控嵌入：`19 × 22 = 418`；
- 22 到 12 的隐藏层及偏置：`22 × 12 + 12 = 276`；
- 12 到 1 的非线性输出：`12`；
- 22 到 1 的线性分支：`22`。

它的优点是模型小、CPU 推理成本接近常数、参数含义受 22 项图特征约束；缺点是没有从大规模代码中获得标识符、控制流和数据流先验。现有 281 个查询不足以让一个从零模型学习完整的 C/C++ 代码语义，这也是当前 P@1 偏低的重要原因。

“使用开源预训练模型一定更好”并不严格成立。预训练语料若不包含嵌入式 C/C++、寄存器访问和厂商 HAL，模型可能只强化名称相似性；但选用与代码检索、C/C++ 和长代码片段匹配的开源模型，通常比从零学习 token 语义更合理。

### 5.5 推荐的预训练模型路线

下一版优先建议评估 [`jinaai/jina-embeddings-v2-base-code`](https://huggingface.co/jinaai/jina-embeddings-v2-base-code)。其模型卡给出 161M 参数、Apache-2.0 许可，支持 C、C++、Assembly、CMake 等 30 种编程语言，并面向代码检索训练。原始 safetensors 约 322 MB，可通过 ONNX/INT8 在普通电脑 CPU 上运行。它比 728 参数模型大，但仍属于可本地部署的编码器，而不是需要服务器的大语言模型。

[`Salesforce/codet5-small`](https://huggingface.co/Salesforce/codet5-small) 约 60M 参数、Apache-2.0，适合作为低成本消融；但其主要 CodeSearchNet 预训练语言不覆盖嵌入式 C，因此不能预设它一定最好。[`microsoft/graphcodebert-base`](https://huggingface.co/microsoft/graphcodebert-base) 约 125M 参数，并显式利用数据流，适合作为结构模型对照或教师模型，但模型文件和计算成本高于 CodeT5-small。

论文中的专门优化不应只是“换一个模型”，可以形成以下完整方法：

1. 将操作契约编码为 query，将函数签名、规范化函数体、寄存器效果和 `API -> callee -> register` 路径序列化为多字段 document；
2. 冻结大部分代码编码器，只训练查询侧低秩适配器、图特征投影和排序头，限制可训练参数量；
3. 使用现有 IR 自动生成自监督对比样本：同一效果路径的包装函数与底层函数为结构相关对，不同寄存器能力和相反动作作为困难对照；
4. 在 H02 上继续使用 PU pairwise 损失，并用多实例袋建模降低漏标等价 API 的冲突；
5. 将预训练语义向量与 22 项硬件图特征通过操作条件门控融合，硬约束保持在学习器外部；
6. 最后蒸馏或 INT8 量化，报告模型大小、CPU 延迟和内存，而不是只报告准确率。

其中“寄存器效果路径序列化、自监督效果对比预训练、PU 多实例排序和硬约束保护”可以构成论文的模型适配创新；直接使用现成模型本身不能算核心创新。

## 6. 实验协议

- 数据：H02，23 套 SDK、331 个有效查询、29,904 个候选行。
- 图统计：22,932 个唯一候选实体，54,483 个寄存器目录项，14,168 个直接锚点，13,930 行存在效果路径。
- 主评测：281 个 `role=train` 查询，按 18 个 `independence_group` 分成五折；同一厂商或上游 SDK 不跨训练/测试折。
- 外部诊断：三套板卡的 50 个查询不进入训练，但因这些板卡已参与历史调参和错误分析，不作为未见测试集结论。
- 对照：函数体直接效果、跨过程图启发式、PU 排序器、PU+图残差和现有 q4。
- 指标：P@1、Recall@3、Recall@5、MRR、MAP、nDCG@10。
- 统计：以查询为配对单位执行 4,000 次 bootstrap，报告相对 q4 的均值差和 95% 区间。

## 7. 结果

### 7.1 五折跨独立组结果

| 方法 | P@1 | Recall@5 | MAP | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 函数体直接效果 | 0.281 | 0.457 | 0.376 | 0.432 |
| 跨过程图启发式 | 0.285 | 0.465 | 0.382 | 0.441 |
| PU 偏好排序 | 0.313 | 0.515 | 0.417 | 0.493 |
| PU + 图残差 | **0.335** | **0.528** | **0.432** | **0.506** |
| 现有 q4 | 0.310 | 0.448 | 0.396 | 0.447 |

相对 q4，完整独立方案的绝对变化为 P@1 `+0.025`、Recall@5 `+0.080`、MAP `+0.036`、nDCG@10 `+0.058`。Recall@5 的配对 bootstrap 95% 区间为 `[0.015, 0.146]`，nDCG@10 为 `[0.004, 0.112]`，两项不跨 0；P@1 和 MAP 的区间仍跨 0，因此不能声称所有指标均显著优越。

### 7.2 消融解释

- 直接函数体到跨过程图：Recall@5 增加 0.008，说明调用传播能找回部分公共包装，但单独依靠图规则仍弱。
- 图启发式到 PU 排序：Recall@5 增加 0.050，MAP 增加 0.036，说明 H02 查询内相对偏好能够学习 API 层级与角色组合。
- PU 到图残差：P@1 再增加 0.021，MAP 增加 0.014，说明轻量模型不能完全保留查询内的硬件证据强度，固定残差有补偿作用。

### 7.3 外部板卡诊断

独立方案在 50 个板卡查询上的 P@1/Recall@5/MAP/nDCG@10 为 0.160/0.415/0.290/0.386，显著低于历史 q4 的诊断结果。该现象说明目前的寄存器目录、调用解析和 H02 偏好尚不能替代现有字段语义，尤其对宏、内联、厂商封装和 RTOS 已知板级模式支持不足。不得选择性只报告五折正向结果而隐去此项失败。

### 7.4 完整错误分析

完整错误报告见 `docs/hardware-effect-graph-pu-error-report-v0.1.md`，机器可读结果见 `experiments/operation-ranking/results-hardware-effect-pu-h02-v0.1-errors.json`。281 个 out-of-fold 查询中 94 个 Top1 正确、187 个错误，主归因如下：

| 主归因 | 数量 | 占错误比例 | 含义 |
| --- | ---: | ---: | --- |
| 同 API 家族动作混淆 | 61 | 32.6% | 找到了正确外设家族，但选中 register/unregister、read/status、configure/write 等错误子操作 |
| 排序模型无法区分 | 59 | 31.6% | 图特征接近，728 参数模型缺少代码语义先验 |
| 真值效果路径缺失 | 33 | 17.6% | 真值函数体、宏展开、函数指针或寄存器目录没有形成目标效果路径 |
| 抽象层级不匹配 | 16 | 8.6% | 直接效果层与 H02 指定的公共 HAL/driver 层不一致 |
| 复合入口压过目标 API | 10 | 5.3% | 初始化、平台或中间件入口同时触发多个能力 |
| 效果强度混淆 | 6 | 3.2% | 错误子外设的寄存器效果强于正确接口契约 |
| 示例/内部角色 | 2 | 1.0% | 示例入口或内部回调未被充分降权 |

四个主要类别占全部错误的 90.4%。这表明下一阶段优先级应是补全调用/宏/寄存器图、引入操作级代码编码器和改进 API 层级建模，而不是单纯增加训练轮数。

具体例子：

- `ti-mspm0-driverlib::interrupt.register` 将 `DL_Interrupt_unregisterInterrupt` 排在真值 `DL_Interrupt_registerInterrupt` 前。系统找对了 API 家族，但没有可靠理解相反动作。
- `ti-mspm0-driverlib::clock.enable` 将查询函数 `DL_MCAN_isModuleClockEnabled` 排到首位，三个 H02 真值的寄存器效果路径很弱或缺失。这是寄存器目录与读/写动作联合恢复不足。
- `arduino-renesas-core::uart.read` 的真值 `UART::read` 排名为 46，系统选择 `UART::cfg_pins`。类方法已进入图，但方法调用和对象状态传播不足。
- `espressif-esp-idf-6.0.1::interrupt.register` 选择 `touch_pad_isr_register`，真值 `esp_intr_alloc_intrstatus` 和 `esp_intr_alloc` 位于第 2、3 名。当前角色特征没有充分区分外设专用 ISR 注册与通用中断分配 API。
- `ti-simplelink-f2::timer.initialize` 选择示例/平台入口 `platformAlarmMicroInit`，真值 `GPTimerCC26XX_open` 排名第 6，说明复合上层调用不能仅凭“能到达定时器”就视为迁移接口。

### 7.5 非函数和无单一公共 API 的比例

H02 训练真值共有 22 套 SDK × 19 个操作，即 418 个查询组：

| H02 状态 | 查询数 | 比例 | 是否进入当前函数排序指标 |
| --- | ---: | ---: | --- |
| `complete`，存在可独立满足契约的公共函数/内联入口 | 281 | 67.2% | 是 |
| `no_public_api`，没有单一稳定公共 API | 137 | 32.8% | 否 |

137 个 `no_public_api` 组中，122 组至少有一个相关 callable，27 组有两个及以上相关 callable，15 组没有可用 callable 近邻。相关条目共 193 个，其中 public driver 79、public macro/inline 57、internal helper 47、public HAL 7、public framework 3；183 个只达到 grade 1，表示它们单独不能完成操作。

因此需要同时给出两个结论：

1. 当前 P@1 0.335 的分母只包含 281 个存在正函数的查询，低指标主要是系统性能问题，不能归因于那 137 个非单函数组。
2. 对端到端迁移而言，32.8% 的 `no_public_api` 比例不可忽略。即使函数排序达到很高准确率，系统仍需要定位宏、寄存器、配置对象或多函数调用序列。

## 8. 从单函数扩展到多类型语义目标

下一版 IR 不应强制所有操作输出一个函数，而应定义统一的 `SemanticTarget`：

```text
SemanticTarget = CallableTarget
               | MacroTarget
               | RegisterEffectTarget
               | ConfigTarget
               | CallbackSlotTarget
               | SequenceTarget
               | BackendProvidedTarget
```

- `CallableTarget`：普通函数、类方法、静态内联函数；类方法保留 receiver 类型，后端需要 C ABI 时生成薄包装。
- `MacroTarget`：函数式宏、寄存器访问宏和常量组合，IR 保存宏参数、展开体和定义条件。
- `RegisterEffectTarget`：没有稳定 SDK API 时定位寄存器字段、位掩码和访问顺序；默认只生成候选 recipe，不绕过厂商约束直接写寄存器。
- `ConfigTarget`：设备实例、配置结构体、devicetree/Kconfig/SCons/CMake 选项等声明式实体。
- `CallbackSlotTarget`：操作通过函数指针表、weak symbol 或回调字段提供时，输出槽位、签名和注册位置。
- `SequenceTarget`：一个操作需要多个 grade-1 callable 时，输出带顺序、参数绑定、前置条件和回滚动作的 API DAG。
- `BackendProvidedTarget`：该操作由 RTOS 既有 BSP、体系结构端口或内核设施提供，不应错误地要求 SDK 再实现。

定位流程先恢复底层寄存器效果，再在反向图上寻找能够覆盖目标效果的最小公共子图。若一个节点不能独立覆盖契约，则求解最小 API 集合：效果覆盖完整、前置条件可满足、调用顺序无冲突、接口层级稳定且不经过示例/应用入口。最终输出从 `selected_symbol` 升级为：

```json
{
  "operation": "gpio.attach_irq",
  "target_kind": "sequence",
  "steps": [
    {"call": "exti_select_source", "bind": ["line", "port"]},
    {"call": "exti_set_trigger", "bind": ["line", "edge"]},
    {"call": "exti_enable_request", "bind": ["line"]}
  ],
  "covered_effects": ["source-route", "edge-config", "irq-enable"],
  "evidence_paths": ["API -> register"],
  "verification": ["type-check", "compile", "effect-coverage", "board-test"]
}
```

对应评测也要拆成实体定位 Recall、recipe 完整率、参数绑定准确率、编译成功率和上板行为通过率，不能继续只用函数 P@1 描述全部能力。

## 9. OS 后端与 19 个操作的支撑边界

### 9.1 不同 RTOS 的需求确实不同

19 个操作是目标无关的 SDK 硬件原语集合，不是 RT-Thread 或 Zephyr 的完整驱动接口。RT-Thread 串口设备模型需要 `configure/control/putc/getc` 和设备注册；Zephyr 需要设备初始化、driver API、devicetree/Kconfig 实例化及其中断/同步约定。GPIO、定时器和中断生命周期也存在类似差异。

正确架构应由 OS 后端声明需求矩阵：

```text
backend requirement -> canonical operation/recipe -> SDK semantic target
```

每个操作针对某个后端标注 `required`、`optional`、`derived` 或 `backend-provided`。当前 `BindingPlanner` 仍遍历全部 19 个操作，尚未把该后端需求矩阵做成显式一等数据结构，这是后续需要补齐的工程边界。

### 9.2 找到 19 个操作并不等于 OS 一定运行

若 19 个操作都找对并生成可编译工程，可以有力证明五类硬件适配层已形成，但不能单独证明 OS 可以启动和稳定运行。完整 OS 还依赖：

- 启动代码、链接脚本、内存布局、栈和堆；
- 体系结构端口、上下文切换和异常入口；
- 系统 tick、时钟频率和中断控制器初始化；
- 设备实例、引脚复用、时钟门控和板级参数；
- 中断并发、缓存/内存屏障、DMA 一致性和错误恢复；
- OS 原生设备注册、初始化顺序和配置系统。

这些内容分别由 Closure Solver、OS Backend、既有 RTOS BSP/arch port 和板级配置提供。项目没有要求 19 个操作独自承担全部 OS 移植工作。

### 9.3 论文应采用分层证据链

1. 语义层：操作或 recipe 与人工真值一致；
2. 工程层：生成代码类型正确并进入目标构建；
3. 产物层：ELF/BIN/HEX 架构、段和关键符号正确；
4. 启动层：开发板重复启动并出现 OS banner/console；
5. 内核层：调度、tick、线程切换和中断可持续运行；
6. 外设层：UART、GPIO、IRQ、timer 的统一回归通过；
7. 稳定性层：长时间、重复启动和错误注入测试通过。

当前六套组合已完成工程和静态产物层，Zephyr native_sim 完成部分运行回归；真实开发板仍需要完成第 4 至第 7 层。只有“19 个操作 + 构建闭包 + OS 后端 + 上板行为”联合起来，才能有力支撑 OS 运行主张。

## 10. 创新性与结论边界

新方向更适合形成论文核心创新，但理由应落在方法本身，而不是当前分数：

- 从名称相似性推进到寄存器效果锚定的跨过程语义；
- 同时恢复硬件效果和公共 API 抽象边界，而不是把最底层寄存器函数直接当答案；
- 在不完整真值下使用 PU 查询内偏好，避免把所有未标注函数声明为负例；
- 将单函数选择扩展为宏、配置和可验证 API recipe；
- 用证据路径连接语义选择、代码生成、编译闭环和上板行为。

该组合比“调整静态权重”更容易形成清晰贡献，也具有更高的表示能力上限。但是，当前 P@1 0.335 和板卡诊断失败意味着它还不能作为性能领先的最终方法。论文达到较高层次至少需要：补全多类型目标、引入适合 C/C++ 的预训练代码编码器、在未见 SDK 上显著超过 q4/字段基线，并通过三块板卡和模拟平台验证 recipe 的运行行为。

## 11. 当前结论与后续融合边界

本轮证明函数实际内容和寄存器效果路径提供了函数暴露信息之外的互补证据，主要收益体现在 Top5 召回；它尚未达到论文目标，也不应立即替换 q4。下一阶段可冻结本方案 v0.1，再做以下独立实验：

1. 使用 AST/SSA 改善宏展开、函数指针、类方法和跨文件调用解析；
2. 从 SVD 和芯片头文件建立更精确的寄存器-操作本体；
3. 对 H02 补标同族等价 API，并采用 bagging PU 或非负 PU 风险降低漏标冲突；
4. 在完全未参与调试的新 SDK 上一次性评估；
5. 最后才把 `s_hardware` 作为 q4 的独立通道，通过开发集预注册权重，比较 q4、硬件图和二者融合。

在完成第 5 步之前，论文中应将本方案称为“独立候选方法/消融方案”，不能把其结果与 q4 融合结果混写为同一算法。

## 12. 文件职责与复现

- `bspforge/hardware_effect_graph.py`：源码恢复、寄存器目录、直接效果、跨过程传播、API 角色特征和硬件图启发式。
- `bspforge/hardware_effect_ranker.py`：728 参数操作门控 PU 排序器、特征标准化、模型保存与加载。
- `scripts/add_hardware_effect_graph_features.py`：按 SDK 读取 IR/源码并生成标签无关图特征。
- `scripts/evaluate_hardware_effect_pu_ranker.py`：H02 PU 训练、独立组五折评测、消融、外部诊断和配对 bootstrap。
- `scripts/generate_hardware_effect_error_report.py`：连接 out-of-fold 预测、图证据和 H02 真值，生成逐查询错误清单与机器 JSON。
- `tests/test_pipeline_modules.py`：公共 UART 包装到 TX 寄存器叶子的效果路径回归测试。

```bash
conda run -n AIoT-v1.0 python scripts/add_hardware_effect_graph_features.py \
  --dataset experiments/generated/deterministic-no-training-v1.1-h02-structured.json \
  --output experiments/generated/hardware-effect-h02-v0.1.json

conda run -n AIoT-v1.0 python scripts/evaluate_hardware_effect_pu_ranker.py \
  --dataset experiments/generated/hardware-effect-h02-v0.1.json \
  --output experiments/operation-ranking/results-hardware-effect-pu-h02-v0.1.json \
  --output-model models/hardware-effect-pu-h02-v0.1.pt
```
