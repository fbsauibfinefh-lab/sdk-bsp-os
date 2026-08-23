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

递归识别 C/C++/汇编源码、头文件、CMake/Make/SCons 规则、链接脚本和启动文件；记录 SHA-256、函数定义、调用、包含关系、宏上下文、构建引用和源码行号。当前解析器强调确定性和低依赖，后续可接入 Clang 或 tree-sitter 而不改变下游接口。

### IR Store

以 SDK 标识和内容摘要保存不可变 JSON 快照。语义映射和闭包只引用稳定实体 ID，因此生成结果可以回溯到具体 SDK 文件、函数和行号。

### Semantic Resolver

基于名称、操作词、路径、函数签名、包含文件、调用和宏等独立证据进行加权评分。同一能力只保留能够覆盖不同操作角色的高分候选，减少简单 Top-K 带来的重复结果。

### Closure Solver

从已接受函数出发，沿定义、调用、包含和构建规则边求解闭包，并强制加入启动与链接资产。闭包记录每个实体的加入原因。诊断阶段可在原闭包上增量加入提供未定义符号的源码或缺失头文件的包含目录，并形成新版本。

### Build Diagnoser

识别缺失头文件、未定义符号、重复定义、ABI 不匹配、链接库缺失、内存区域溢出和一般编译错误。缺失头文件和未定义符号可安全反查 SDK IR 并形成自动修复；其余问题保留为不可自动处理约束，避免危险修改。

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

两个后端都生成 `sdk-ir.json`、`semantic-resolution.json`、`build-closure.json`、`functional-bindings.json`、`device-model.json` 和 `generation-manifest.json`。最终验证统一检查 ELF、BIN/HEX、架构、段大小、SHA-256 和注册入口，从而让不同 RTOS 的工程结构可用同一实验脚本比较。

## 构建后验证与评估

编译返回码为 0 后，Artifact Verifier 继续检查 ELF 与 BIN/HEX、ARM/RISC-V 架构、段大小、哈希以及生成操作表和注册入口是否真实进入 ELF。Experiment Evaluator 使用人工真值集分别评估候选恢复、后端契约绑定和设备操作覆盖，并自动执行证据消融。构建验证和方法评估是两个独立结果，避免用“能编译”替代语义准确性。
