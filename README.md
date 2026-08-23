# BSPForge

BSPForge 是一个面向芯片 SDK 语义恢复与 RTOS BSP 自动生成的研究原型。当前端到端样例以 Kendryte K210 SDK 为输入，以 RT-Thread 为操作系统后端；分析、闭包和诊断模块本身不依赖特定芯片或操作系统。

## 核心能力

工程按论文方法划分为六个模块：

1. **SDK Ingestor**：提取源代码、头文件、构建规则、链接脚本、启动文件、函数定义、调用关系和证据位置。
2. **IR Store**：保存版本化 SDK Migration IR，并支持按实体和证据查询。
3. **Semantic Resolver**：融合名称、路径、签名、头文件、调用和宏等证据，恢复 SDK 能力与目标 OS 契约之间的映射。
4. **Closure Solver**：从已接受映射出发，求解源码、头文件、构建规则、启动文件和链接脚本闭包。
5. **Build Diagnoser**：将编译/链接错误转换为结构化约束，自动定位缺失头文件或未定义符号的 SDK 提供者。
6. **OS Backend**：生成 RT-Thread 原生 BSP、功能性绑定代码，调用 SCons，并检查 ELF/BIN 固件。

当前 RT-Thread 后端不再只生成符号表，而会生成可调用的时钟、中断、UART、GPIO 和定时器包装函数。流水线支持有界自动诊断迭代：编译失败后，根据 IR 增补源码或包含目录，重新生成并编译，直到成功、没有新约束或达到最大迭代次数。

## 快速开始

```bash
cd /home/whk/RTT-porting/bspforge
./scripts/bootstrap_local_inputs.sh
./scripts/install_toolchain.sh
./scripts/run_k210.sh
```

只运行分析与工程生成，不执行编译：

```bash
./scripts/run_k210.sh --no-build
```

运行测试：

```bash
conda run -n AIoT-v1.0 python -m unittest discover -s tests -v
```

所有阶段产物保存在 `workspace/runs/<run-id>/`，包括 SDK IR、语义映射、闭包、功能绑定清单、每轮编译日志、诊断约束和最终报告。

## 文档

- [系统架构](docs/architecture.md)
- [IR 数据结构](docs/ir-schema.md)
- [K210 复现实验](docs/reproduction.md)
- [基线实验结果](docs/baseline-results.md)
- [当前实现状态](docs/research-status.md)
- [扩展新 SDK/后端](docs/extending.md)

## 仓库约定

SDK、RT-Thread 源码、工具链、生成工程和固件均为可复现的本地依赖，不提交到 Git。仓库只保留实现代码、配置、下载信息、实验说明和测试，避免重新分发大体积第三方文件。

