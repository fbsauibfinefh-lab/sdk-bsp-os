# 跨 RTOS 实板自动回归

## 协议与边界

RT-Thread 与 Zephyr 固件实现相同的自测命令，并输出一行一个 JSON 对象。启动事件和结果事件都包含 `protocol: "1.0"`；每条结果通过 `request_id` 与主机请求关联。未接回环线、未配置测试引脚或 SDK 不提供能力时返回 `unsupported`，不计为成功，也不进入适用命令分母。

| 命令 | 目标 | 典型外部条件 |
| --- | --- | --- |
| `info` | 协议和固件可达性 | 无 |
| `uart.loopback` | UART 发送/接收及错误数 | TX/RX 回环 |
| `gpio.toggle` | 输出翻转 | LED 或示波器/逻辑分析仪 |
| `gpio.irq` | 输入边沿与中断计数 | 两引脚连线或信号源 |
| `timer.oneshot` | 单次定时与误差 | 无 |
| `timer.periodic` | 周期、抖动和丢失次数 | 无 |
| `stability` | 连续运行与错误累计 | 建议多轮 |

当前板端基础实现已覆盖协议、启动事件、GPIO 翻转和定时器命令；需要特定接线的 UART loopback 与 GPIO IRQ 在未配置时返回 `unsupported`。后续上板时应按开发板配置扩展这两项测量，不能把 unsupported 改成固定 pass。

## 运行

烧录对应固件并确认串口设备后执行：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyUSB0 \
  --board k210 \
  --rtos rtthread \
  --baudrate 115200 \
  --rounds 10 \
  --output workspace/hardware/k210-rtthread.json
```

RT-Thread 接收形式为 `bspforge_selftest <request-id> <command>` 的 FinSH 命令；Zephyr 使用同一行格式，由 console 轮询分发。主机报告包含原始日志、每轮启动事件、每项命令往返时间和板端指标。

## 报告口径

- `boot_successes/boot_attempts` 与 `boot_success_rate`：主机复位后在超时内收到启动事件的次数。
- `boot_time_mean_ms/min/max`：从主机执行复位到收到应用阶段启动事件的时间。
- `commands_passed/commands_applicable`：通过命令数与排除 unsupported 后的适用命令数。
- `commands_total`：所有已发送命令数，用于同时展示 unsupported 覆盖。
- `failed` 与 `unsupported`：分别表示适用能力失败和当前目标不具备测试条件。

正式论文实验应固定固件提交、工具链、串口参数、接线、轮数和超时，并保存每块板的原始 JSON，避免只摘录汇总比例。
