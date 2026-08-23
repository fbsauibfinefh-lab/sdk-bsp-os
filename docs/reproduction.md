# K210 到 RT-Thread 复现实验

## 本地条件

- WSL：`UbuntuD-22.04`
- Conda 环境：`AIoT-v1.0`
- K210 SDK：`/mnt/d/Wuhk/AIOT/k210sdk/kendryte-standalone-sdk`
- RT-Thread：`/mnt/d/Wuhk/RTT/rt-thread`
- 主机工具：`scons`、`wget`、`tar`

K210 BSP 使用 `riscv-none-embed-` 工具前缀以及 `rv64imafc/lp64f` 参数，因此当前配置采用 xPack GNU RISC-V Embedded GCC 10.2.0-1.2。

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

## 主要输出

```text
workspace/
  ir/<sdk-id>/<digest>/sdk-ir.json
  runs/k210-rtthread-baseline/
    01-sdk-ir.json
    02-semantic-resolution.json
    03-build-closure.json
    04-generation.json
    05-build-iteration-01.log
    06-diagnosis-iteration-01.json
    07-build-iterations.json
    report.json
  generated/k210-rtthread/bsp/k210/
    board/bspforge_bindings.c
    board/bspforge_bindings.h
    bspforge/functional-bindings.json
    rtthread.elf
    rtthread.bin
```

若第 1 次编译失败且存在可自动修复约束，还会出现下一轮闭包、生成清单、日志和诊断文件。`07-build-iterations.json` 记录尝试次数、停止原因和修复数量。

## 论文实验指标

- 语义映射 Top-1/Top-K 准确率、召回率；
- 功能操作覆盖率和绑定生成成功率；
- 闭包准确率、召回率和冗余文件比例；
- 首次编译成功率、自动修复成功率和平均迭代次数；
- 各阶段耗时、固件尺寸和内存区域占用；
- UART、GPIO、定时器、中断和时钟的上板回归通过率；
- 去除构建证据、调用证据、功能绑定和诊断反馈后的消融实验；
- 与人工迁移、仅名称匹配和仅路径匹配基线进行比较。

