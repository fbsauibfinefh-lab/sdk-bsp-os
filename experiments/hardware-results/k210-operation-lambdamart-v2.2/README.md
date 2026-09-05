# K210 计划驱动双 RTOS 实板证据

本目录记录冻结 LambdaMART 运行时包、签名与 API 家族约束解码后的 K210 端到端验证。部署过程不读取 H01/H02/H03 真值；真值只用于独立离线评测。

## 最终结果

| 后端 | 计划操作 | 直接 SDK 调用 | OS 等价接管 | 构建 | 启动 | 命令 |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| RT-Thread | 19 | 18 | 1 个 PLIC 初始化 | 成功 | 10/10 | 90/90 |
| Zephyr | 19 | 15 | 4 个 PLIC 操作 | 成功 | 10/10 | 90/90 |

RT-Thread BIN 为 468776 bytes，SHA-256 为 `174b0c613700da6c8fef487fef96e869c1ff87fac03cef59f831bebda1abe90b`。Zephyr BIN 为 35584 bytes，SHA-256 为 `94146dffa0559993f759f96f792f35056bb689dd9c86ae862befe4f3de0e078b`。

## 文件说明

- `*-canonical-binding-plan.json`：模型原始 Top1、最终选择、签名约束、API 家族和拒绝理由。
- `*-functional-bindings.json`：每项操作的实体 ID、源码位置、生成处置和辅助依赖。
- `*-compile-feedback.json`：19 项计划操作在目标构建中的逐项可观察性。
- `*-artifact-verification.json`：ELF 架构、段、生成符号、文件大小和哈希。
- `*-final-10rounds.json`：实板启动、逐命令结果、硬件观测量和固件哈希。
- `diagnostics/`：开发过程中保留的失败报告，用于说明 OS 所有权、串口残留和 MMIO 访问宽度问题的发现过程；这些报告不得替代最终结果，也不应被删除来制造全通过结论。

九条协议命令为 `info`、`clock.basic`、`interrupt.basic`、`uart.loopback`、`gpio.toggle`、`gpio.irq`、`timer.oneshot`、`timer.periodic` 和 `stability`。UART 使用 IO7/IO6 回环，GPIO 使用 IO8 输出到 IO9 输入；验证程序只通过 RT-Thread 或 Zephyr 的公共设备 API 进入生成绑定。
