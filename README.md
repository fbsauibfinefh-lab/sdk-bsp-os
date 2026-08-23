# BSPForge

BSPForge 是一个面向芯片 SDK 语义恢复与 RTOS BSP 自动生成的研究原型。当前端到端样例以 Kendryte K210 SDK 为输入、以 RT-Thread 为操作系统后端；通用分析、闭包、诊断和评估模块不依赖特定芯片。

## 核心能力

工程按论文方法划分为六个模块：

1. **SDK Ingestor**：提取源码、头文件、构建规则、链接脚本、启动文件、函数、调用关系和证据位置。
2. **IR Store**：保存版本化 SDK Migration IR，支持按稳定实体 ID 回溯证据。
3. **Semantic Resolver**：融合名称、路径、签名、头文件、调用和宏证据，恢复 SDK 能力与目标 OS 契约的映射。
4. **Closure Solver**：求解源码、头文件、构建规则、启动文件和链接脚本闭包。
5. **Build Diagnoser**：把编译/链接错误转换为约束，定位 SDK 提供者并执行安全的增量修复。
6. **OS Backend**：生成原生 RT-Thread BSP、设备模型和注册代码，调用 SCons，并验证 ELF/BIN。

v0.3 会生成真实参与链接的 `rt_uart_ops`、`rt_pin_ops`、`rt_hwtimer_ops`、设备实例和初始化注册函数。流水线在编译失败后根据 IR 增补源码或包含目录，直到成功、无新约束或达到迭代上限；链接成功后还会检查固件架构、段信息、哈希和关键生成符号。

## 快速开始

```bash
cd /home/whk/RTT-porting/bspforge
./scripts/bootstrap_local_inputs.sh
./scripts/install_toolchain.sh
./scripts/run_k210.sh
```

只分析和生成，不执行编译：

```bash
./scripts/run_k210.sh --no-build
```

运行测试：

```bash
conda run -n AIoT-v1.0 python -m unittest discover -s tests -v
```

所有阶段产物保存在 `workspace/runs/<run-id>/`，包括 SDK IR、语义映射、闭包、绑定与设备清单、逐轮编译日志、诊断约束、产物验证、方法指标、证据消融和最终报告。

## 文档

- [系统架构](docs/architecture.md)
- [IR 数据结构](docs/ir-schema.md)
- [K210 复现实验](docs/reproduction.md)
- [基线实验结果](docs/baseline-results.md)
- [研究状态与版本演进](docs/research-status.md)
- [扩展新 SDK/后端](docs/extending.md)

## 仓库约定

SDK、RT-Thread 源码、工具链、生成工程和固件是可复现的本地依赖，不提交到 Git。仓库只保存实现代码、配置、下载信息、真值集、实验说明和测试，避免重新分发大体积第三方文件。
