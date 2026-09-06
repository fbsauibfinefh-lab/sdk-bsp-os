# BSPForge

BSPForge 是一个面向芯片 SDK 语义恢复与 RTOS BSP 自动生成的研究原型。当前支持 Kendryte K210、STM32F103 和 PSoC E84 Edgi-Talk 三类 SDK，以及 RT-Thread、Zephyr 两个具有不同设备模型和构建系统的后端。

## 核心能力

工程按论文方法划分为六个模块：

1. **SDK Ingestor**：提取源码、头文件、构建规则、链接脚本、启动文件、函数、调用关系和证据位置。
2. **IR Store**：保存版本化 SDK Migration IR，支持按稳定实体 ID 回溯证据。
3. **Semantic Resolver**：支持固定权重与学习排序，恢复 SDK 能力并生成规范化操作绑定计划。
4. **Closure Solver**：按目标架构、芯片、CPU 核、入口和后端策略求解构建闭包。
5. **Build Diagnoser**：把编译/链接错误转换为约束，定位 SDK 提供者并执行安全的增量修复。
6. **OS Backend**：生成原生 RT-Thread BSP 或 Zephyr 应用，调用 SCons 或 west/CMake/Ninja，并验证 ELF 与 BIN/HEX。

K210/RT-Thread 路径会生成真实参与链接的 `rt_uart_ops`、`rt_pin_ops`、`rt_hwtimer_ops`、设备实例和初始化注册函数。成熟 BSP 路径追踪 RTOS 原生驱动到 SDK 实体的调用证据，并生成设备 API 验证入口。流水线在编译失败后根据 IR 增补源码或包含目录，直到成功、无新约束或达到迭代上限；链接成功后还会检查固件架构、段信息、哈希和关键生成符号。

当前论文部署方法为结构先验与目标可行性保护增强的 LambdaMART。K210 部署候选由 IR 独立生成，不读取目标板真值；系统对 14,814 个候选行计算字段语义、代码双视图、寄存器效果图和结构特征，并保留每项操作的完整候选排名。事后独立真值评测覆盖 48/48 个真值符号，原始模型 P@1 为 0.895、nDCG@10 为 0.816。部署解码器再用参数签名可封装性和同能力 API 家族完整性构造 19 项规范计划，避免把高分但签名不满足操作契约的函数直接写入后端。RT-Thread 有 18 项直接调用计划所选 SDK 实体，PLIC 初始化由 RT-Thread 启动阶段等价接管；Zephyr 有 15 项直接调用，4 项 PLIC 操作由 Zephyr 二级 IRQ 框架等价实现。两套处置均在逐操作清单中明确记录，编译反馈均覆盖 19/19 项操作。计划驱动固件已完成 K210 实板复测：RT-Thread 和 Zephyr 各 10/10 次启动、90/90 条协议命令通过，失败与 `unsupported` 均为 0。Zephyr 路径把恢复所得 SDK 绑定生成为 `clock_control`、UART、GPIO 和 Counter 四类原生 `struct device` 驱动，PLIC 则按 Zephyr 中断控制器子系统接入；验证程序只通过两种 RTOS 的公共设备 API 访问生成实现。完整证据见 `experiments/hardware-results/k210-operation-lambdamart-v2.2/`。

PSoC E84 和 STM32F103 也已完成双 RTOS 实板验证。PSoC 在更换故障 UART 跳线后，两套固件的五类能力均获得通过证据；STM32F103 两套固件均完成 10/10 次启动和 90/90 条功能命令，其中 Zephyr 明确记录两次 USB-UART 传输重试。各板原始语义指标、编译闭包和实板结果分开报告，不用硬件通过率覆盖模型错误。

## 快速开始

```bash
cd /home/whk/RTT-porting/bspforge
./scripts/bootstrap_local_inputs.sh
./scripts/install_python_dependencies.sh
./scripts/install_toolchain.sh
./scripts/run_matrix.sh
```

只分析和生成，不执行编译：

```bash
./scripts/run_matrix.sh --no-build
```

运行测试：

```bash
conda run -n AIoT-v1.0 python -m unittest discover -s tests -v
```

准备评测 SDK 并运行 native_sim 回归：

```bash
./scripts/bootstrap_evaluation_sdks.sh
conda run -n AIoT-v1.0 python -m pip install -e '.[retrieval]'
./scripts/run_zephyr_native_simulation.sh
```

运行 20 个独立 SDK 的操作级实验：

```bash
conda run -n AIoT-v1.0 python scripts/ingest_operation_corpus.py \
  --manifest experiments/operation-ranking/manifest.json --ir-root workspace/operation-ir
conda run -n AIoT-v1.0 python scripts/build_operation_dataset.py \
  --manifest experiments/operation-ranking/manifest.json --ir-root workspace/operation-ir \
  --output experiments/generated/operation-ranking-dataset.json
conda run -n AIoT-v1.0 python scripts/evaluate_operation_ranker.py \
  --dataset experiments/generated/operation-ranking-dataset.json \
  --output experiments/generated/operation-ranking-results.json
```

运行冻结 MiniLM 字段语义与 K210 确定性流水线：

```bash
conda run -n AIoT-v1.0 python -m pip install -e '.[retrieval]'
conda run -n AIoT-v1.0 python -m bspforge.cli pipeline \
  --config examples/k210-rtthread/project-semantic.json
```

运行冻结 LambdaMART 的 K210 部署流水线：

```bash
conda run --no-capture-output -n AIoT-v1.0 python -m bspforge.cli pipeline \
  --config examples/k210-rtthread/project.json
conda run --no-capture-output -n AIoT-v1.0 python -m bspforge.cli pipeline \
  --config examples/k210-zephyr/project.json
```

预训练代码效果排序的模型下载、全量缓存和五折评测命令见 `docs/pretrained-code-effect-ranking-v0.2.md`。模型权重放在 `/home/whk/RTT-porting/models/`，不纳入本仓库；本次首次 CPU 缓存耗时 6,351.642 秒，缓存后完整嵌套五折评测耗时 137.650 秒，后续只训练 12,636 参数的小型排序头。

所有阶段产物保存在 `workspace/runs/<run-id>/`，包括 SDK IR、语义映射、闭包、绑定与设备清单、逐轮编译日志、诊断约束、产物验证、方法指标、证据消融和最终报告。

## 文档

- [系统架构](docs/architecture.md)
- [IR 数据结构](docs/ir-schema.md)
- [K210 复现实验](docs/reproduction.md)
- [基线实验结果](docs/baseline-results.md)
- [三芯片双 RTOS 构建矩阵](docs/matrix-results.md)
- [研究状态与版本演进](docs/research-status.md)
- [实板自动回归](docs/hardware-validation.md)
- [语义排序实验](docs/semantic-ranking.md)
- [操作级排序与模型优化](docs/operation-ranking-v0.7.md)
- [IR 感知轻量语义排序 v0.8](docs/ir-semantic-reranking-v0.8.md)
- [字段迟交互、组合约束与编译校准 v0.9](docs/field-aware-structured-ranking-v0.9.md)
- [无 SDK 训练的确定性排序与低分诊断 v1.2](docs/deterministic-ranking-low-score-diagnostics-v1.2.md)
- [六套上板组合的能力操作真值对照](docs/board-six-combination-operation-comparison.md)
- [寄存器效果图与正例-未标注偏好排序 v0.1](docs/hardware-effect-graph-pu-ranking-v0.1.md)
- [寄存器效果图 PU 排序完整错误报告](docs/hardware-effect-graph-pu-error-report-v0.1.md)
- [冻结预训练代码模型增强的硬件效果排序 v0.2](docs/pretrained-code-effect-ranking-v0.2.md)
- [预训练代码效果排序完整错误报告](docs/pretrained-code-effect-error-report-v0.2.md)
- [操作条件效果切片与多视图排序 v0.3](docs/effect-slice-multiview-ranking-v0.3.md)
- [操作条件多视图排序完整错误报告](docs/effect-slice-multiview-error-report-v0.3.md)
- [跨操作效果对比与结构一致性探索 v0.4](docs/cross-operation-effect-contrast-v0.4.md)
- [跨操作效果对比完整错误报告](docs/cross-operation-effect-contrast-error-report-v0.4.md)
- [相近任务指标与论文实验目标参考](docs/related-task-metric-reference-v0.4.md)
- [论文核心方法与整体工作梳理 v1.0](docs/core-method-v1.0.md)
- [LambdaMART 主方法与三板外部评估 v0.6](docs/lambdamart-method-and-external-board-evaluation-v0.6.md)
- [冻结 LambdaMART Resolver 与 K210 实板验证 v2.1](docs/frozen-lambdamart-resolver-k210-v2.1.md)
- [PSoC E84 冻结 LambdaMART 双 RTOS 实板验证 v2.4](docs/psoc-e84-lambdamart-board-validation-v2.4.md)
- [STM32F103 冻结 LambdaMART 双 RTOS 实板验证 v2.5](docs/stm32f103-lambdamart-board-validation-v2.5.md)
- [方法引用与知识产权风险检查](docs/related-work-citation-and-ip-risk-v0.9.md)
- [第三方组件与许可证说明](THIRD_PARTY_NOTICES.md)
- [实验规模与仿真方案](docs/experiment-scale-and-simulation-plan.md)
- [扩展新 SDK/后端](docs/extending.md)

## 仓库约定

SDK、RT-Thread 源码、工具链、生成工程和固件是可复现的本地依赖，不提交到 Git。仓库只保存实现代码、配置、下载信息、真值集、实验说明和测试，避免重新分发大体积第三方文件。
