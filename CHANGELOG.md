# 变更记录

## 0.4.0

- 增加 Zephyr 4.4 后端，生成 devicetree/Kconfig/CMake 原生应用并调用 west/Ninja 构建。
- 增加 STM32CubeF1 与 PSoC E84 Edgi-Talk SDK profile，完成三个 SDK、两个 RTOS 的六组合构建矩阵。
- 增加 K210 Zephyr 板级端口，覆盖 RV64、SRAM、PLIC、机器定时器、UARTHS 和 FPIOA 初始化。
- 增加成熟 RTOS 驱动到 SDK IR 实体的证据追踪，以及 RT-Thread/Zephyr 原生设备 API 验证入口。
- STM32F103 从输入 SDK 重新物化 CMSIS Core、Device 和 HAL 软件包；PSoC E84 复用厂商 M33 工程模板。
- 统一验证 ARM/RISC-V ELF、BIN/HEX、段信息、SHA-256 和关键注册符号。
- 增加双架构工具链安装、六配置运行脚本、构建矩阵结果文档和 4 项单元测试。

## 0.3.0

- 生成 RT-Thread 原生 `rt_uart_ops`、`rt_pin_ops` 和 `rt_hwtimer_ops`，以及设备实例和初始化注册代码。
- 设备名称、UART 通道、PIN 数量、硬件定时器通道与频率改为项目配置驱动。
- 修正 UART 停止位和 GPIO 模式的跨框架枚举转换，硬件定时器改用独立 TIMER 外设，避免占用系统节拍 CLINT。
- 增加 ELF/BIN 哈希、架构、段大小和关键生成符号验证；链接成功但产物验证失败时，流水线仍判为失败。
- 增加警告分类、阶段耗时、K210 人工真值集、语义检索指标、绑定/设备操作覆盖率和七类证据消融。
- 单元测试扩展到 11 项，覆盖全部诊断类别、设备配置校验、设备源码生成、评估和产物解析。
- 简化 Conda 运行脚本，复现实验不再依赖重复执行可编辑安装。

## 0.2.0

- 生成时钟、中断、UART、GPIO 和定时器的实际 RT-Thread/SDK 功能绑定。
- 输出功能绑定到 SDK 符号、签名和源码位置的证据清单。
- 增加缺失头文件、未定义函数和未定义全局变量的 IR 反查。
- 增加闭包增量修复、工程重新生成和有界自动编译迭代。
- 保存每轮日志、诊断、修复提案、闭包和停止原因。
- 将仓库自有 Markdown 文档统一改为中文。

## 0.1.0

- 建立六模块原型、K210 SDK 摄取、RT-Thread 后端和首次固件编译基线。
