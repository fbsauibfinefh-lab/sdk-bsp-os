# 三芯片双 RTOS 构建矩阵

本文档记录 2026-08-23 至 2026-08-25 在 WSL Ubuntu 22.04、`AIoT-v1.0` 环境完成的构建实验。下表已更新为 v0.6 头文件 API 摄取、多证据语义恢复、目标感知闭包和统一自测协议接入后的结果。六个组合均从 SDK 摄取开始运行完整流水线并通过固件静态验证；结果不包含开发板运行验证。

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
| K210 | 201 | 2,164 | 5,759 | 23 | 73 | 10 | 1 / 1 |
| STM32CubeF1 | 3,921 | 15,250 | 50,411 | 23 | 609 | 0 | 0 / 0（后端提供） |
| PSoC E84 | 3,254 | 17,423 | 66,698 | 21 | 650 | 24 | 0 / 0（后端提供） |

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

## v0.6 自动绑定覆盖

规范化绑定计划包含 19 个常见操作。K210 自动推断 19/19，STM32CubeF1 为 15/19，PSoC E84 为 13/19。后两项仍能编译是因为成熟 RTOS BSP 提供了已审计驱动，这不能反推自动绑定已经完整；正式论文应把自动计划覆盖与人工/成熟后端上限分开报告。PSoC 的数值低于 v0.5 是因为 v0.6 真值和候选审计收紧了动作级适配条件，不再把仅在名称上相关的函数当作完整操作绑定。

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
