# STM32F103 双 RTOS 实板证据

本目录保存冻结 LambdaMART v2.5 部署链在 正点原子战舰 V3（STM32F103ZET6）上的可提交机器证据。公开复现说明见 `docs/stm32f103-lambdamart-board-validation-v2.5.md`。

| 文件 | 内容 |
| --- | --- |
| `rtthread-final-10rounds.json` | RT-Thread 10 次启动、90 条命令的最终报告 |
| `zephyr-final-10rounds-retry-aware.json` | Zephyr 10 次启动、90 条功能命令及两次传输重试 |
| `zephyr-no-retry-run-1.json` | Zephyr 不重试原始运行，89/90 |
| `zephyr-no-retry-run-2.json` | Zephyr 不重试原始运行，88/90 |
| `*-canonical-binding-plan.json` | 19 项规范操作的冻结绑定计划 |
| `*-functional-bindings.json` | OS 后端生成或接管每项操作的证据 |
| `*-compile-feedback.json` | 绑定在最终构建中的可观察性 |
| `*-artifact-verification.json` | ELF/BIN 类型、符号、大小和哈希 |

Zephyr 最终报告的 90/90 表示所有功能命令最终得到通过响应；其中两条命令的首次响应因 CH340 串口帧丢字节而超时，随后各重试一次通过。原始无重试报告被同时保留，避免把传输异常隐藏为无条件成功。
