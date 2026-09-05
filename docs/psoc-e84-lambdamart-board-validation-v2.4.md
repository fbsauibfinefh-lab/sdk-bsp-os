# PSoC E84 Edgi-Talk 冻结 LambdaMART 双 RTOS 验证 v2.4

本文档记录 PSoC E84 Edgi-Talk 在冻结 LambdaMART 方法、RT-Thread 和 Zephyr 原生设备后端上的正式生成、编译与实板结果。目标 SDK 真值只在冻结包导出后的独立评测中读取，不参与候选生成、特征计算、模型训练或运行时选择。

## 1. 冻结语义输入

运行时数据由 SDK Migration IR 独立生成。每个操作先按能力级静态证据稳定排序并保留 96 个候选，再计算字段迟交互、结构检索、寄存器效果图、完整代码和操作聚焦代码向量。该候选预算在 96、128 和 1024 三档无标签消融中固定；三档分别得到 P@1 0.833、0.778、0.611，因此选择 96。选择过程不使用 PSoC 符号白名单，但属于目标 SDK 上的部署参数诊断，论文中应与模型训练和独立泛化指标分开报告。

冻结包：

```text
models/runtime/psoc-e84-operation-lambdamart-h03-eq-r1-full-v2.4.json
```

包中含 19 个操作、1,824 个候选，声明 `contains_labels=false`。H03 独立评测只统计 18 个具有完整单函数真值的操作；`gpio.attach_irq` 被 H03 标为 `no_public_api`，仍参与部署，但不进入单函数排序指标分母。

| 指标 | 结果 |
| --- | ---: |
| P@1 | 0.833 |
| Recall@5 | 0.742 |
| MAP | 0.641 |
| nDCG@10 | 0.731 |
| Hit@5 | 1.000 |
| 四项核心指标均值 | 0.737 |

候选池包含 53 个严格真值符号中的 42 个，缺失的 11 个主要是同操作的次级等价实现。18 个可评测操作的 Top5 均至少包含一个正例。完整逐操作结果位于 `experiments/operation-ranking/runtime-evaluation/psoc-e84-lambdamart-v2.4.json`。

## 2. 部署解码修正

签名族解码没有回退到人工真值。它只做两项通用修正：

1. 将 `SysInt`、`NVIC` 和 `PLIC` 归一为系统中断控制器语义族，允许初始化、向量登记和使能/禁用由同一控制器栈的不同公共层完成，同时继续拒绝 CAN、SD、GPIO 等外设局部中断族。
2. 将 `base`、`obj`、`counter`、`cnt` 和 `tcpwm` 识别为通用定时器实例参数，使 `Init/Enable/Disable/SetPeriod` 这类完整控制器族能够通过签名可执行性检查。

两项规则不包含 SDK ID、文件路径、实体 ID 或 PSoC 真值符号。其作用是阻止语义相关但无法由后端传参的函数进入最终绑定，而不是修改 LambdaMART 原始指标。

## 3. 构建结果

两套项目都从 SDK 摄取开始执行完整流水线：IR、Resolver、绑定计划、闭包、后端生成、编译、诊断和产物验证。

| 项目 | RT-Thread | Zephyr |
| --- | ---: | ---: |
| SDK 文件/函数/IR 边 | 3,254 / 17,423 / 66,698 | 3,254 / 17,423 / 66,698 |
| 规范操作 | 19/19 | 19/19 |
| 解析能力 | 5/5 | 5/5 |
| 闭包文件/构建规则 | 270 / 18 | 270 / 18 |
| 构建尝试 | 1 | 1 |
| 编译反馈观察绑定 | 19/19 | 19/19 |
| 结果 | 成功 | 成功 |

RT-Thread ELF 为 1,503,296 bytes，Zephyr ELF 为 976,188 bytes。两者均为 ELF32 ARM，验证入口存在于最终 ELF。RT-Thread 烧录镜像必须包含安全启动段和重定位后的应用段；只烧录应用 HEX 可能继续启动外部闪存中残留的 Zephyr 镜像。

## 4. 实板配置

| 项目 | 设置 |
| --- | --- |
| 板卡 | PSoC E84 Edgi-Talk，PSE846GPS2DBZC4A B0 |
| 调试器 | KitProg3 2.81.1663，SWD 4 MHz |
| 主机协议串口 | COM8，115200 bit/s |
| UART5 回环 | CN5 Pin8 TXD 与 Pin10 RXD |
| GPIO 回环 | CN5 Pin11 GPIO0 与 Pin12 GPIO1 |
| RT-Thread 固件 SHA-256 | `33985f092b64302baa0e08fd2fbf419e67661841ccd3ce13b45344cd6ac754aa` |
| Zephyr 固件 SHA-256 | `56a72d3da9f82a3b9b508058d124f645cc064e554cf16e27ab492b8a10845b51` |

测试程序不直接调用 SDK。RT-Thread 经 serial、pin 和 hwtimer 设备 API，Zephyr 经 UART、GPIO、Counter、时钟和 IRQ 原生 API进入后端，再到 SDK/PDL 与硬件。每套固件执行 10 次 OpenOCD 自动复位和每轮 9 条协议命令。

## 5. 实板结果

| 命令 | RT-Thread | Zephyr | 判据摘要 |
| --- | ---: | ---: | --- |
| 启动 | 10/10 | 10/10 | 收到含正确 RTOS 与 build ID 的 boot 事件 |
| `info` | 10/10 | 10/10 | 验证服务和原生设备可用 |
| `clock.basic` | 10/10 | 10/10 | 时钟源非零，OS 时间持续前进 |
| `interrupt.basic` | 10/10 | 10/10 | 回调计数为 1 |
| `uart.loopback` | 0/10 | 0/10 | UART5 收到 0/16 bytes |
| `gpio.toggle` | 10/10 | 10/10 | 输出锁存及跨线输入低/高一致 |
| `gpio.irq` | 10/10 | 10/10 | 边沿回调计数为 1 |
| `timer.oneshot` | 10/10 | 10/10 | 单次回调计数为 1 |
| `timer.periodic` | 10/10 | 10/10 | 周期回调计数为 3 |
| `stability` | 10/10 | 10/10 | 命令末尾服务仍可用 |

两套固件均为 10/10 次启动、80/90 条命令通过、10 条失败、0 条 `unsupported`。失败不是十种不同故障，而是同一 UART5 外部回环在十轮中的重复失败。

CN5 原理图确认 Pin8/Pin10 经常使能的 TXS0108E 连接 P17.1/P17.0。调试阶段把两端改为普通 GPIO并交换方向后，输出锁存能变化，但另一端始终读高；同一现象跨 RT-Thread 和 Zephyr 重现。因此当前证据支持 UART 后端已实现且协议控制台 UART 可双向工作，但不能声称 CN5 UART5 外部通道通过。应检查跳线接触、排针方向、电平转换器两侧电压和实际波形后重测。

最终机器报告：

```text
experiments/hardware-results/psoc-e84-operation-lambdamart-v2.4/rtthread-10-rounds.json
experiments/hardware-results/psoc-e84-operation-lambdamart-v2.4/zephyr-10-rounds.json
```

## 6. 可支持的结论

本轮可以支持：同一冻结语义包能生成两种 RTOS 的 19 项绑定，完成闭包并一次编译；两套固件均可稳定启动，并通过时钟、中断、GPIO、GPIO 中断、单次和周期定时器的 OS 原生 API 路径。

本轮不能支持“PSoC E84 五类能力全部正常”或“90/90 命令通过”。UART5 仍是公开待解决项。当前 0.833 的 P@1 是独立语义评测结果，80/90 是端到端行为结果，19/19 是生成和编译观察结果，三者分母和含义不同，不得合并成一个成功率。
