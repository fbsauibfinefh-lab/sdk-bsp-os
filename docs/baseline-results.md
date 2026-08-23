# K210/RT-Thread v0.3 基线实验结果

本文档记录 2026-08-23 在 WSL Ubuntu 22.04 和 `AIoT-v1.0` 环境完成的端到端基线。结果尚未包含开发板运行验证。

## 输入版本

| 输入 | 标识 |
| --- | --- |
| SDK | `kendryte-k210-standalone-sdk-0.5.6` |
| SDK Git 提交 | `02576ba67e8797444f3ee3f34c625b5ed048e707` |
| SDK IR 摘要 | `2dbe5aaaea39d6dc` |
| RT-Thread Git 提交 | `c3da935369e110accd64686abde6bb7d9c825ee4` |
| 工具链 | xPack GNU RISC-V Embedded GCC 10.2.0-1.2 |

## SDK 分析与闭包

| 指标 | 结果 |
| --- | ---: |
| SDK 文件 | 199 |
| 函数实体 | 645 |
| 全局变量实体 | 8 |
| 构建规则实体 | 22 |
| 类型化 IR 边 | 2,062 |
| 请求/成功解析能力 | 5 / 5 |
| 操作去重后的接受函数 | 23 |
| 初始闭包文件 | 59 |
| 初始闭包构建规则 | 9 |
| 启动/链接资产 | 1 / 1 |

## 功能绑定与设备模型

| 指标 | 结果 |
| --- | ---: |
| 成功生成能力 | 5 |
| 缺失必要 SDK 符号 | 0 |
| 注册 UART/PIN/HWTIMER 设备 | 2 / 1 / 1 |
| 生成 RT-Thread 操作表 | 3 |
| 设备注册入口 | 2 |
| 绑定符号宏平均召回率 | 1.0000 |
| 设备操作宏平均召回率 | 1.0000 |

生成对象不是仅供展示的代码。产物验证在最终 ELF 中找到了 `bspforge_uart_ops`、`bspforge_pin_ops`、`bspforge_hwtimer_ops`、`bspforge_rtthread_devices_init` 和 `bspforge_hwtimer_devices_init`。

## 语义恢复基线

K210 人工真值集当前得到：Accepted 集合宏 Precision 0.6000、Recall 0.5967、F1 0.5894，候选排序 MRR 0.9000。该结果说明能力级检索能够找到相关区域，但仅靠通用加权规则还不能稳定完成精确操作角色选择；最终绑定由目标后端契约继续筛选并达到完整覆盖。论文中应分别报告“通用候选恢复”和“契约约束后的绑定完成”，不能把二者合并成一个准确率。

`10-evidence-ablations.json` 保存七类证据逐项去除后的指标，可直接用于消融表。扩大 SDK 样本后沿用同一评估程序。

## 自动诊断迭代

1. 第 1 轮链接报告 `sys_register_getchar`、`sys_register_putchar`、`sys_getchar` 和 `sys_putchar` 未定义。
2. Build Diagnoser 通过函数和全局变量 IR 将提供者统一定位到 `lib/bsp/syscalls.c`。
3. Closure Solver 生成一项 `add-source` 增量约束并重新物化工程。
4. 第 2 轮编译和链接成功。

| 指标 | 结果 |
| --- | ---: |
| 编译尝试次数 | 2 |
| 第 1 轮诊断数 | 4 |
| 应用修复数 | 1 |
| 未归因诊断 | 0 |
| 停止原因 | `build-succeeded` |

## 最终构建结果

| 产物/指标 | 结果 |
| --- | --- |
| ELF 类型 | ELF64, RISC-V, little-endian |
| ELF 入口 | `0x80000000` |
| `rtthread.elf` | 666,264 B |
| `rtthread.bin` | 470,912 B |
| ELF `text/data/bss` | `466971 / 3864 / 45827` B |
| ELF SHA-256 | `5c28811f7b4b5ce7e4a7927d1c416e9f3b631ce171a0cfdb18a5a65e8efeffc3` |
| BIN SHA-256 | `9d17d3cfd1d8a21605c9a7792b1f182aef982fa5436f5e254ba357ade5887a55` |
| 构建警告 | 9 |
| 第 1/2 轮构建耗时 | `44.558 / 44.448` s |
| 流水线总耗时 | `111.789` s |

警告来自既有 K210 BSP、RT-Thread 组件和 SDK 文件，生成的三个设备操作表未引入新的编译警告。警告类别和样例保存在 `report.json`，后续实验可按来源单独统计。

## 结论边界

当前结果证明 SDK 分析、证据化映射、功能绑定、RT-Thread 原生设备生成、构建闭包、自动诊断修复以及固件验证能够闭环运行。它不证明固件已经在开发板启动，也不证明外设语义在硬件上完全正确；这些结论留给上板回归实验。
