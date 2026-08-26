# 系统架构

## 问题定义

BSPForge 将 BSP 迁移建模为两个相互约束的问题：一是从厂商 SDK 中恢复外设能力与 API 语义，二是恢复这些能力在目标 RTOS 原生工程中可编译所需的完整代码和构建资产。编译不是最后的打包步骤，而是验证和反馈机制。

```text
芯片 SDK
   |
   v
SDK Ingestor ---- 代码、构建、链接、启动证据
   |
   v
IR Store -------- 版本化 SDK Migration IR
   |
   v
Semantic Resolver ---- 带评分的能力映射
   |
   v
Closure Solver ------- 类型化构建闭包
   |
   v
OS Backend ----------- RT-Thread BSP / Zephyr 应用 + 功能绑定
   |
   v
编译器/链接器 ---------- 固件或错误日志
   |                         |
   +---- Build Diagnoser <---+
             |
             +---- 增量约束、重新生成和编译
```

## 模块职责

### SDK Ingestor

递归识别 C/C++/汇编源码、头文件、静态库、CMake/Make/SCons 规则、链接脚本和启动文件；记录 SHA-256、源码与头文件内联函数定义、调用、包含关系、宏上下文、构建引用和源码行号。`hybrid` 前端优先使用编译数据库驱动的 Clang AST，其次使用 tree-sitter，最后以正则兜底；`regex` 模式保留为论文基线。实体证据同时记录解析前端和置信度，AST 使用显式栈遍历以支持大型生成代码中的深层语法树。

### IR Store

以 SDK 标识和内容摘要保存不可变 JSON 快照。语义映射和闭包只引用稳定实体 ID，因此生成结果可以回溯到具体 SDK 文件、函数和行号。

### Semantic Resolver

基于名称、操作词、路径、函数签名、包含文件、调用和宏等独立证据恢复候选。固定权重排序是可审计基线，学习排序从独立 SDK 标注训练 LightGBM LambdaRank；`hybrid` 将固定证据作为先验并使用模型重排序。候选随后映射为 OS 无关的规范化操作计划，缺失和多解不会由人工 profile 静默填充。训练和评测以 SDK 为分组边界，禁止同一 SDK 的实体随机泄漏到两侧。

### Closure Solver

从已接受函数出发，沿定义、调用、包含和构建规则边求解闭包。启动与链接资产依据构建引用、架构、芯片、CPU 核、入口符号和后端策略选择；当目标 RTOS 已提供这些契约时，SDK 资产被明确记录为 `replaced-by-os-backend`。闭包记录每个实体的加入或拒绝原因。

### Build Diagnoser

识别缺失头文件、未定义符号、重复定义、ABI 不匹配、链接库缺失、内存区域溢出、构建工具错误和一般编译错误。修复按风险分级：低风险动作默认自动应用，唯一静态库属于中风险，ABI、内存布局与重复定义保持人工处理。每次修复以闭包快照为事务边界；若下一轮诊断代价上升，后端从基快照重新生成。

流水线采用有界迭代，默认最多 3 次：

1. 生成工程并编译。
2. 将日志结构化，反查 SDK IR。
3. 将新源码或包含目录加入闭包。
4. 保存新闭包和生成清单，重新生成并编译。
5. 在编译成功、无新约束或达到上限时停止。

### OS Backend

OS Backend 管理设备模型、工程结构、构建系统和产物验证。RT-Thread 后端生成隔离 BSP 或厂商原生工程，调用 SCons；Zephyr 后端生成独立应用、devicetree overlay 与 Kconfig 配置，调用 west/CMake/Ninja。两者消费相同的 IR、语义解析和闭包，不在通用阶段写入 OS 专属类型。

当前绑定统一了五类能力：

- 时钟：使能、关闭和频率查询；
- 中断：初始化、使能、关闭、注册、注销和 claim；
- UART：配置、发送和接收；
- GPIO：模式、读、写和边沿配置；
- 定时器：初始化、启动、停止和周期设置。

每个包装函数均在 `functional-bindings.json` 中记录所依赖的 SDK 符号、函数签名、实体 ID 和源码证据。绑定所需 SDK 源码会自动补入 SCons 构建规则。

K210 路径从 SDK 适配层生成 RT-Thread 的 serial、pin 和 hwtimer 操作表、设备实例及注册代码。STM32F103 与 PSoC E84 已有成熟的 RTOS 原生 HAL 驱动，后端不重复生成整套底层驱动，而是分别记录原生驱动对 SDK 实体的调用和 HAL provider 中的定义证据，并生成统一的 RTOS 设备 API 验证入口。两类策略都输出 `functional-bindings.json`，可在实验中分别统计生成式绑定、直接驱动引用和 provider 覆盖。

## 核心不变量

1. 不原地修改或编译输入 SDK、RT-Thread 或 Zephyr 源码。
2. 每个语义映射包含评分和源码证据。
3. 每个闭包实体包含类型化加入原因。
4. 每个功能绑定可追溯到 SDK 函数定义。
5. 每轮编译、诊断、修复和闭包均独立留档。
6. 编译成功必须同时满足返回码为 0、预期固件存在、ELF 架构正确且关键符号已链接。
7. 编译成功不等同于硬件功能正确，上板结果单独统计。

## v0.3 原生设备生成链

RT-Thread 后端现在包含两级生成：

1. 功能绑定层把 SDK 类型、枚举和返回值归一化，并记录每个 SDK 符号的 IR 证据。
2. 设备模型层消费归一化接口和项目设备配置，生成 `rt_uart_ops`、`rt_pin_ops`、`rt_hwtimer_ops`、设备实例及注册函数。

两级清单分别保存在 `functional-bindings.json` 和 `device-model.json`。前者回答“调用了哪些 SDK 实现”，后者回答“生成了哪些 RT-Thread 对象、操作和设备”。设备模型层不直接包含 K210 SDK 头文件，因此后续替换 SDK profile 时不需要改写 RT-Thread 设备契约。

## v0.4 双后端与多平台生成链

### RT-Thread 后端

- K210：复制原生 BSP，重新物化被分析的 SDK 包，生成 SDK 适配层和 serial/pin/hwtimer 对象。
- STM32F103：复制 `stm32f103-atk-warshipv3` BSP，同时链接 STM32 共享驱动目录；从输入 STM32CubeF1 物化 CMSIS Core、Device 和 HAL 软件包。
- PSoC E84：复制 Edgi-Talk M33 工程模板，链接其 RT-Thread、HAL 和组件目录，保留厂商工程的链接布局。

STM32/PSoC 生成的 `bspforge_validation.c` 仅调用 `rt_device_find/open/write`、PIN 和定时器等原生 API。底层初始化仍由目标 BSP 完成，因此工程框架与设备模型保持 RT-Thread 原生形式。

### Zephyr 后端

Zephyr 后端生成 `app/CMakeLists.txt`、`prj.conf`、可选 `app.overlay` 和 `src/main.c`，再由 west 选择目标板并完成 Kconfig、devicetree、CMake 和 Ninja 闭包。STM32F103 与 PSoC E84 使用 Zephyr 上游板级目标和 HAL 模块；K210 使用 `ports/zephyr-k210` 中的仓库内板级端口。

功能绑定清单在生成阶段先记录 SDK 实体和 HAL provider 证据。构建成功后，后端解析 `build.ninja`，只从本次实际参与编译且位于允许驱动根目录中的源文件提取 `driver_references`，随后回写 `functional-bindings.json`。因此 provider 存在、源码树中出现调用和当前固件实际选中驱动是三个不同证据层级。

K210 端口定义 RV64 CPU、6 MiB SRAM、PLIC、机器定时器和 UARTHS，并在 `PRE_KERNEL_1` 阶段设置标准串口 FPIOA。PSoC E84 的 GNU objcopy 原地 LMA 调整由生成工程中的受控包装器转换为“保留 ELF、在 HEX 转换时应用偏移”，上游 Zephyr 与工具链目录均保持只读。

### 统一产物契约

两个后端都生成 `sdk-ir.json`、`semantic-resolution.json`、`canonical-binding-plan.json`、`build-closure.json`、`functional-bindings.json`、`device-model.json` 和 `generation-manifest.json`。最终验证统一检查 ELF、BIN/HEX、架构、段大小、SHA-256 和注册入口，从而让不同 RTOS 的工程结构可用同一实验脚本比较。

## v0.5 规范化绑定与实板数据流

`02b-canonical-binding-plan.json` 位于语义解析和 OS Backend 之间。它按 clock、interrupt、uart、gpio、timer 的规范化操作保存所选 SDK 实体、签名、参数来源、备选项、置信度及 `inferred/missing` 状态。OS 后端消费这份计划；`SDK_PROFILES` 只提供已知平台架构提示和人工 oracle，不替代自动选择。

固件自测采用统一命令集合：`info`、`uart.loopback`、`gpio.toggle`、`gpio.irq`、`timer.oneshot`、`timer.periodic`、`stability`。RT-Thread 通过 FinSH 命令接收，Zephyr 通过 console 轮询接收，均输出协议 1.0 的逐行 JSON。主机端保存原始串口日志，并把 `unsupported` 从适用命令分母中剔除。详细操作见 `docs/hardware-validation.md`。

## 构建后验证与评估

编译返回码为 0 后，Artifact Verifier 继续检查 ELF 与 BIN/HEX、ARM/RISC-V 架构、段大小、哈希以及生成操作表和注册入口是否真实进入 ELF。Experiment Evaluator 使用人工真值集分别评估候选恢复、后端契约绑定和设备操作覆盖，并自动执行证据消融。构建验证和方法评估是两个独立结果，避免用“能编译”替代语义准确性。

## v0.6 语料与仿真数据流

`scripts/ingest_semantic_corpus.py` 从固定版本的 7 个 SDK 生成 IR，`build_semantic_dataset.py` 先逐符号审计真值，再抽取全部正例、高分困难负例和固定种子随机负例。`evaluate_ranker_cv.py` 执行外层 SDK 留一、内层融合权重选择、特征消融、Bootstrap 和配对置换检验。最终模型及特征模式保存在 `models/semantic-ranker.txt` 和相邻元数据中。

主机验证层实现 `SerialTransport` 与 `ProcessTransport`。前者连接三块实板，后者启动 Zephyr native_sim、QEMU 或 Renode 并连接标准输入输出；二者均交给同一个 `HardwareTestRunner`，因而请求、超时、原始日志和统计口径完全一致。仿真验证可重复性和 OS API 行为，实板验证真实时钟、中断和外设电气语义。

## v0.7 操作级排序与拒答数据流

`experiments/operation-ranking/manifest.json` 把 22 套开发 SDK 和 3 套板卡外部测试 SDK 固定为不同角色。`ingest_operation_corpus.py` 生成独立操作 IR，`build_operation_dataset.py` 将五类能力展开为 19 个操作查询，并分别产生弱监督训练标签和源码审计外部标签。板卡真值不进入训练。

操作排序在能力候选池内部增加动作、签名、HAL 层次、中断控制器、参数化开关、冲突操作和适配方向证据。可选嵌入脚本只增加 `code-embedding` 特征，不改变 IR 或解析输出模式。`evaluate_operation_ranker.py` 统一计算 BM25、静态规则、弱监督 LambdaRank、语义嵌入和融合结果，并保存 bootstrap 区间、前五候选和置信拒答曲线。

Resolver 的 `operation_min_margin` 对每个操作比较前两名不同符号的分差。低于门槛时保留候选和证据，但不写入已接受绑定；Binding Planner 将其转成 missing，后端不得用低分函数静默填充。该变更只扩展语义输出契约，Closure Solver、Build Diagnoser 和两个 OS Backend 的职责不变。

## v0.8 轻量 IR 语义适配数据流

`operation-semantic` 在 `operation-weighted` 的候选和证据之上增加两个冻结 MiniLM 分支。基础分支把 IR 中的操作契约作为简洁查询；适配分支把 capability、operation 和 contract 序列化为 `ir-operation-v1`，再经过秩 16 的查询残差适配器。SDK 函数实体统一序列化为文件、符号、签名、包含和调用文本，候选向量只计算一次。

基础模型为固定提交的 22.7M 参数 all-MiniLM-L6-v2。主体参数不进入训练，适配器只有 12,288 个参数，并以近似恒等映射初始化。运行时输出静态、基础语义和适配语义三项证据；均衡模式在全候选中融合，精度模式先用静态证据建立 Top-10 池，再在池内重排。

语义模型只扩展 Semantic Resolver。其输出仍是稳定实体 ID、操作、分数和证据，Binding Planner、Closure Solver、Build Diagnoser 与两个 OS Backend 的输入契约不变。K210 完整回归已经验证该输出能够形成 19 操作绑定、触发一次链接诊断修复并生成 RISC-V ELF/BIN。详细算法、负向消融、指标与复现命令见 `docs/ir-semantic-reranking-v0.8.md`。

## v0.9 字段迟交互、组合约束与编译校准数据流

v0.9 将候选函数 IR 拆为 `symbol`、`signature`、`calls`、`file` 和 `includes` 五个字段。每个字段使用不同的操作查询，经冻结 MiniLM 生成 token 表示后，以 MaxSim 计算迟交互分数。系统同时保留五个字段分数和聚合分数，使 LambdaMART、手工权重及字段消融共享同一份输入证据。

训练真值改为 0 至 3 的分级标签。每条标签包含规则证据和置信度；外部板卡真值区分首选 HAL 绑定与功能等价的次级驱动层实现。数据审计器检查 20 个训练独立组、外部组隔离、标签来源和强正例覆盖。自动分级标签仍不是人工金标准，正式投稿前需要第二标注者复核。

独立操作分数进入能力级组合解码。解码器先施加操作冲突、API 可见性和适配方向等一元契约，再用共享 API 族、目录、签名类型、HAL 层级和参数化互补函数计算成对兼容。离线实验使用 beam search；Resolver 运行时采用有界贪心，并在 `constraint_scores` 中保存调整证据。

构建结束后，`compile_feedback.py` 将结果写入 `08b-semantic-compile-feedback.json`。直接被诊断提及、完整编译并通过产物检查、构建失败但不可归因和未观测绑定采用不同校准值。历史反馈可在同一 SDK 的后续解析中按稳定实体 ID 融合。该反馈只说明可编译、可链接和产物结构，不声明硬件语义正确。

选择性自动接受使用分差、静态/语义一致性、契约准入和候选分数建立置信度。阈值按开发 SDK 分组校准并取保守值；外部集不允许重新选阈值。详细公式、约束表、保证边界和复现命令见 `docs/field-aware-structured-ranking-v0.9.md`，文献与许可边界见 `docs/related-work-citation-and-ip-risk-v0.9.md`。
