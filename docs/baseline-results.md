# K210/RT-Thread 基线实验结果

本文件记录 2026-08-23 在 WSL Ubuntu 22.04 和 `AIoT-v1.0` Conda 环境中完成的 v0.2 端到端基线。

## 输入版本

| 输入 | 标识 |
| --- | --- |
| SDK | `kendryte-k210-standalone-sdk-0.5.6` |
| SDK Git 提交 | `02576ba67e8797444f3ee3f34c625b5ed048e707` |
| SDK IR 摘要 | `2dbe5aaaea39d6dc` |
| RT-Thread Git 提交 | `c3da935369e110accd64686abde6bb7d9c825ee4` |
| 工具链 | xPack GNU RISC-V Embedded GCC 10.2.0-1.2 |
| 目标参数 | `rv64imafc`、`lp64f`、`medany` |

上述提交号标识仓库基础版本。当前 RT-Thread 工作区包含项目内 BSP 修改，在这些修改提交前，精确复现还需保留本次生成目录和运行产物。

## SDK 分析与闭包

| 指标 | 结果 |
| --- | ---: |
| SDK 文件 | 199 |
| 函数实体 | 645 |
| 全局变量实体 | 8 |
| 构建规则实体 | 22 |
| 类型化 IR 边 | 2,062 |
| 请求/成功解析能力 | 5 / 5 |
| 操作去重后的接受函数 | 21 |
| 初始闭包文件 | 63 |
| 初始闭包构建规则 | 9 |
| 启动/链接资产 | 1 / 1 |

生成 SDK 包来自本次分析输入。抽查 `lib/drivers/sysctl.c` 时，输入和生成文件 SHA-256 均为 `cc18314b87fa31f11c10871a80ce2f5157560516acb05a2dfe5ce62f2fba976e`。

## 功能绑定生成

| 指标 | 结果 |
| --- | ---: |
| 成功生成能力 | 5 |
| 生成包装函数 | 20 |
| 引用 SDK 源文件 | 5 |
| 缺失必要符号 | 0 |

生成内容覆盖时钟、中断、UART、GPIO 和定时器。每个包装函数依赖的 SDK 符号、签名、实体 ID、路径和行号均记录在 `functional-bindings.json`。`bspforge_bindings.c` 实际参与编译并生成 `build/board/bspforge_bindings.o`，不是仅供展示的代码。

## 自动诊断迭代

本次运行在未注入人工故障的情况下形成了真实闭环：

1. 第 1 轮编译功能绑定及 `uart.c`，链接器报告 `sys_register_getchar`、`sys_register_putchar`、`sys_getchar` 和 `sys_putchar` 未定义。
2. Build Diagnoser 将 4 个错误归类为 `undefined-symbol`，并通过函数与全局变量 IR 将提供者统一定位到 `lib/bsp/syscalls.c`，未留下无法归因的符号。
3. Closure Solver 将该源码作为 1 条增量修复约束加入新闭包。
4. 后端重新生成 SDK SConscript 和工程，第 2 轮编译成功。

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
| `rtthread.elf` 文件大小 | 657,352 B |
| `rtthread.bin` 文件大小 | 465,528 B |
| ELF `text/data/bss` | `461610 / 3848 / 43963` B |
| 链接器 SRAM 使用 | 509,491 B / 6 MiB（8.10%） |
| ELF SHA-256 | `eb90d0b3d74947431fb8b5a54993faefb1252101055427c0d00940feda150f44` |
| BIN SHA-256 | `7edae707cd304eae9bc35ab17d71a8b10ae1607146513fb8d09322fdc5ba0ed0` |

编译日志仍包含继承 K210 BSP/SDK 的接口兼容和多字符常量警告。它们不阻止链接，但后续实验应单独统计警告数量和类型。

## 验证边界

当前结果证明了 SDK 分析、证据化映射、功能绑定生成、构建闭包、自动诊断修复、RT-Thread 工程生成以及固件编译链能够闭环运行。它尚不能证明生成固件已在开发板上启动，也不能证明各外设包装函数在硬件上的语义完全正确。上板启动和外设回归仍是后续独立实验阶段。

