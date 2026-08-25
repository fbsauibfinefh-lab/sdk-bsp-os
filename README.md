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

v0.7 已把开发语料扩展到 22 套 SDK、20 个独立来源组，并把 K210、STM32F103、PSoC E84 保留为严格外部测试。语义恢复细化为 19 个操作，支持参数化开关、适配方向、HAL 层次、轻量语义嵌入和置信拒答。当前外部测试的静态与语义等权融合 P@1 为 0.600、MAP 为 0.628，仍不能替代实物外设验证。3 块开发板 × 2 个 RTOS 的六组工程均已完成固件静态验证；Zephyr native_sim 已完成 20 轮可执行回归。

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

运行跨 SDK 排序实验和 native_sim 回归：

```bash
./scripts/bootstrap_evaluation_sdks.sh
conda run -n AIoT-v1.0 python -m pip install -e '.[learning]'
./scripts/run_semantic_experiment.sh
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
- [实验规模与仿真方案](docs/experiment-scale-and-simulation-plan.md)
- [扩展新 SDK/后端](docs/extending.md)

## 仓库约定

SDK、RT-Thread 源码、工具链、生成工程和固件是可复现的本地依赖，不提交到 Git。仓库只保存实现代码、配置、下载信息、真值集、实验说明和测试，避免重新分发大体积第三方文件。
