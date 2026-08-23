# K210 到 RT-Thread 复现实验

## 本地条件

- WSL：`UbuntuD-22.04`
- Conda 环境：`AIoT-v1.0`
- K210 SDK：`/mnt/d/Wuhk/AIOT/k210sdk/kendryte-standalone-sdk`
- RT-Thread：`/mnt/d/Wuhk/RTT/rt-thread`
- 工具链：xPack GNU RISC-V Embedded GCC 10.2.0-1.2
- 目标参数：`rv64imafc`、`lp64f`、`medany`

## 一键运行

```bash
cd /home/whk/RTT-porting/bspforge
./scripts/bootstrap_local_inputs.sh
./scripts/install_toolchain.sh
./scripts/run_k210.sh
```

仅分析和生成：

```bash
./scripts/run_k210.sh --no-build
```

脚本直接在 `AIoT-v1.0` 中运行仓库模块，不会在每次实验前重复安装项目。

## 设备配置

`examples/k210-rtthread/project.json` 的 `backend.devices` 指定生成设备。当前基线生成 `bspuart1`、`bspuart2`、`bsppin` 和 `bsptim0`。设备名称与原 K210 BSP 驱动不同，避免注册冲突，并支持后续上板并行比较。

## 主要输出

```text
workspace/
  ir/<sdk-id>/<digest>/sdk-ir.json
  runs/k210-rtthread-baseline/
    01-sdk-ir.json
    02-semantic-resolution.json
    03-build-closure.json
    04-generation.json
    05-build-iteration-<n>.log
    06-diagnosis-iteration-<n>.json
    07-build-iterations.json
    08-artifact-verification.json
    09-method-evaluation.json
    10-evidence-ablations.json
    report.json
  generated/k210-rtthread/bsp/k210/
    board/bspforge_bindings.c
    board/bspforge_devices.c
    drivers/drv_hw_timer.c
    bspforge/functional-bindings.json
    bspforge/device-model.json
    rtthread.elf
    rtthread.bin
```

## 成功判定

一次运行只有同时满足下列条件才记为成功：

1. SCons 返回码为 0。
2. `rtthread.elf` 和 `rtthread.bin` 存在且非空。
3. ELF 机器类型为 RISC-V，段大小可由工具链读取。
4. 生成的 UART/PIN/HWTIMER 操作表和注册入口均存在于 ELF 符号表。

`report.json` 同时记录环境、Git 修订号、各阶段耗时、构建迭代、警告分类、固件哈希和评估摘要。

## 论文实验指标

- 语义映射 Precision、Recall、F1、Recall@K 和 MRR；
- 绑定符号覆盖率和设备操作覆盖率；
- 闭包文件数、构建规则数、诊断修复数和收敛轮次；
- SDK 摄取、语义解析、闭包、生成、编译、重生成和评估耗时；
- ELF/BIN 大小、text/data/bss 与构建警告类别；
- 七类静态证据的逐项消融结果；
- 后续上板后的启动和 UART/GPIO/定时器回归通过率。
