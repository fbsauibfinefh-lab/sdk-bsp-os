# 三芯片双 RTOS 构建矩阵

本文档记录 2026-08-23 至 2026-08-25 在 WSL Ubuntu 22.04、`AIoT-v1.0` 环境完成的构建实验。下表已更新为 v0.7 操作级语义恢复、目标感知闭包和统一自测协议接入后的结果。六个组合均从 SDK 摄取开始运行完整流水线并通过固件静态验证；结果不包含开发板运行验证。

## 固定输入

| 输入 | 版本或提交 |
| --- | --- |
| RT-Thread | `c3da935369e110accd64686abde6bb7d9c825ee4` |
| Zephyr | v4.4.0，`684c9e8f32e4373a21098559f748f06915f950c9` |
| K210 standalone SDK | `02576ba67e8797444f3ee3f34c625b5ed048e707` |
| STM32CubeF1 | `bb2016eaa0004f74b5bd2369709415cae1fc88b2` |
| PSoC E84 Edgi-Talk SDK | `1c6964a67ffb3925e9731c2e29e14b99a3534ee2` |
| K210/RT-Thread 工具链 | xPack RISC-V GCC 10.2.0-1.2 |
| K210/Zephyr 工具链 | xPack RISC-V GCC 14.2.0-3 |
| ARM 工具链 | Arm GNU Toolchain 14.2.Rel1 |

## SDK 与闭包规模

| SDK | 文件 | 函数 | IR 边 | 接受函数 | 闭包文件 | 构建规则 | 启动/链接资产 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| K210 | 201 | 2,164 | 5,759 | 19 | 65-66 | 10 | 1 / 1 |
| STM32CubeF1 | 3,921 | 15,250 | 50,411 | 19 | 605 | 0 | 0 / 0（后端提供） |
| PSoC E84 | 3,254 | 17,423 | 66,698 | 19 | 385 | 20 | 0 / 0（后端提供） |

## 构建结果

| 芯片/开发板 | RTOS | 架构 | 尝试 | ELF | 可刷写镜像 | text/data/bss（B） | 结果 |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| K210 | RT-Thread | ELF64 RISC-V | 2 | 667,976 B | BIN 471,960 B | 468019 / 3864 / 45939 | 通过 |
| K210 | Zephyr 4.4 | ELF64 RISC-V | 1 | 433,512 B | BIN 20,088 B | 20038 / 40 / 7728 | 通过 |
| STM32F103 | RT-Thread | ELF32 ARM | 1 | 445,552 B | BIN 56,324 B | 55224 / 1100 / 2968 | 通过 |
| STM32F103 | Zephyr 4.4 | ELF32 ARM | 1 | 546,072 B | BIN 25,468 B | 25364 / 104 / 4046 | 通过 |
| PSoC E84 Edgi-Talk | RT-Thread | ELF32 ARM | 1 | 1,455,572 B | HEX 180,331 B | 62720 / 1368 / 258285 | 通过 |
| PSoC E84 兼容基线 | Zephyr 4.4 | ELF32 ARM | 1 | 923,652 B | BIN 44,688 B | 42572 / 2096 / 4573 | 通过 |

矩阵成功率为 6/6。每项验证同时要求：构建返回码为 0、ELF 与镜像非空、ELF 机器类型正确、段信息可读、BSPForge 验证或设备注册符号存在于最终 ELF。RT-Thread 三个目标还静态确认 `bspforge_selftest` 进入 ELF；Zephyr 三个目标确认统一协议分发循环随 `main.c` 链接。完整 SHA-256、耗时、警告和逐轮日志保存在 `workspace/runs/<run-id>/report.json`；`workspace` 不提交到 Git。

## v0.7 操作级计划覆盖

六个示例现统一使用 `operation-weighted`，规范化绑定计划均产生 19/19 个候选操作。构建矩阵将 `operation_min_margin` 设为 0，用于检验操作级输出契约、闭包和后端能否端到端工作；因此“19/19 有候选”不是“19/19 语义正确”。严格外部真值上的首选准确率和拒答覆盖见 `docs/operation-ranking-v0.7.md`。STM32F103 和 PSoC E84 即使候选错误也可能依靠成熟 RTOS BSP 编译成功，正式论文必须把自动计划、成熟驱动上限、编译和实板功能分开报告。

## 两类绑定策略

K210/RT-Thread 使用生成式 SDK 适配和原生设备对象，适合验证从 SDK IR 生成缺失 BSP 绑定的能力。STM32F103、PSoC E84 和 Zephyr 路径优先复用成熟的 RTOS/HAL 驱动，并把证据分为两类：`driver_references` 表示 RTOS 驱动对 SDK 函数的直接引用，`provider_references` 表示对应函数存在于后端声明的 HAL provider。后者不计入直接绑定成功率。Zephyr 在链接成功后从 `build.ninja` 提取本次实际编译的驱动源文件并刷新直接引用，避免扫描未选中的板级驱动。两类策略共享 IR、闭包、诊断、清单和产物验证接口，但不把成熟驱动重新生成一遍。

## 自动诊断样本

K210/RT-Thread 第 1 轮出现 4 个未定义符号。Build Diagnoser 将其提供者定位到 `lib/bsp/syscalls.c`，Closure Solver 增加一项 `add-source` 约束并重新生成；第 2 轮成功。其余五个组合在首轮完成构建。这一结果可用于报告诊断覆盖、修复正确性和收敛轮数，但还需要设计故障注入实验扩大诊断样本量。

## 上板边界

STM32F103 的两个目标与手头最小系统板芯片一致。PSoC Zephyr 4.4 没有名为 Edgi-Talk 的上游板级条目，本轮使用 SoC 和基础引脚兼容的 `kit_pse84_eval/pse846gps2dbzc4a/m33`；是否完全兼容必须通过 Edgi-Talk 实物验证。K210 Zephyr 使用 SDK 证据恢复的仓库内端口，也必须验证启动时钟、串口、GPIO 和定时器行为。因此本表只支持“可生成、可编译、可链接、可静态验证”的结论。

## 复现

```bash
cd /home/whk/RTT-porting/bspforge
./scripts/bootstrap_local_inputs.sh
./scripts/install_python_dependencies.sh
./scripts/install_toolchain.sh
./scripts/run_matrix.sh
```

## 冻结方法增量结果（2026-09-06）

PSoC E84 Edgi-Talk 已用冻结 LambdaMART v2.4 重新运行双 RTOS 流水线。两套均从 3,254 个 SDK 文件、17,423 个函数和 66,698 条 IR 边出发，形成 19/19 项绑定、270 个闭包文件和 18 条构建规则，并在第一次构建成功。RT-Thread ELF 为 1,503,296 bytes，Zephyr ELF 为 976,188 bytes；19/19 绑定均被编译反馈观察。

初次完整回归中，两套均 10/10 次启动、80/90 条命令通过，唯一失败为 UART5 外部回环。更换 Pin8/Pin10 跳线后，在不修改绑定、后端和固件的条件下独立复测 UART5，两套均 10/10 次启动、10/10 条回环命令通过，每轮 16 bytes、0 errors。结合原完整回归的其余 80/80 条通过记录，五类能力的适用测试均已获得通过证据；该结果不是换线后重新执行的一次完整 90/90 回归。详见 `docs/psoc-e84-lambdamart-board-validation-v2.4.md`。

## STM32F103 冻结方法增量结果（2026-09-06）

STM32CubeF1 的冻结 Top-256 运行时包包含 19 项操作；后验严格评估在 18 个单函数组上得到 P@1 0.611、Recall@5 0.643、MAP 0.586、nDCG@10 0.674 和 Hit@5 0.944。RT-Thread 形成 334 文件闭包，Build Diagnoser 两次补齐 TIM/TIM_EX 源后第三次构建成功；Zephyr 首次构建成功。两套均生成并编译观察到 19/19 项操作。

RT-Thread ELF/BIN 分别为 617,664/87,184 bytes，实板 10/10 次启动、90/90 条命令通过。Zephyr ELF/BIN 分别为 601,304/28,600 bytes，实板 10/10 次启动、90/90 条功能命令通过；两条命令发生一次可见的传输重试。关闭重试的原始运行也已保存，分别为 89/90 和 88/90。详见 `docs/stm32f103-lambdamart-board-validation-v2.5.md`。
