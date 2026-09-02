# 三开发板双 RTOS 实板验证操作手册

## 1. 文档目的与当前边界

本文固定 K210、STM32F103 正点原子战舰 V3 和 PSoC E84 Edgi-Talk 三块开发板，在 RT-Thread、Zephyr 两个后端上的六套实板验证流程。文档中的“构建通过”表示 ELF 与可烧录镜像已生成并通过静态产物检查；“上板通过”只能由烧录后的串口 JSON 报告证明。截至 2026-09-02，K210 + RT-Thread 已完成基础协议回归以及时钟、GPIO、硬件定时器和中断绑定的 30 轮实板回归，其余五个组合以及 K210 的外部 UART/GPIO IRQ 接线实验仍待执行，不能把 6/6 构建成功写成 6/6 实板成功。

工程根目录固定为：

```text
/home/whk/RTT-porting/bspforge
```

Windows 可通过以下 UNC 路径访问同一目录：

```text
\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge
```

当前板端程序提供统一的逐行 JSON 协议，命令集合为 `info`、`clock.basic`、`interrupt.basic`、`uart.loopback`、`gpio.toggle`、`gpio.irq`、`timer.oneshot`、`timer.periodic` 和 `stability`。RT-Thread 通过 FinSH 接收 `bspforge_selftest <request-id> <command>`，Zephyr 在 console 主循环中接收同样格式。主机程序保存全部原始串口行、启动事件、逐命令结果和汇总统计。

当前实现的能力边界必须如实理解：

- `info` 和 `stability` 是协议可达性与基本存活检查。
- K210 + RT-Thread 的 `clock.basic` 调用生成时钟绑定，对 CPU 与安全外设时钟做非零频率检查，并覆盖外设时钟 enable/disable；其他组合尚需分别实现等价判据。
- K210 + RT-Thread 的 `gpio.toggle` 将 IO35 映射为 GPIOHS31，检查输出低/高锁存位，并将 IO16 映射为 GPIOHS30 后检查上拉输入；其他组合只在测试引脚或 Zephyr `led0` 已配置时执行。
- K210 + RT-Thread 的 `interrupt.basic`、`timer.oneshot` 和 `timer.periodic` 已打开生成的 `bsptim0`，由真实硬件定时器和 PLIC 回调计数判定；其他组合仍需按后端实现等价测试。
- `uart.loopback` 和 `gpio.irq` 当前在未配置测试接线时返回 `unsupported`。
- 因此，现有程序足以先完成六套启动、命令链路和基础 GPIO/时间路径验证，但论文中的“外设功能完整性”还需要在上板阶段补齐 UART 回环、GPIO 中断和真实定时器统计。`unsupported` 不能改写为 `pass`。

## 2. 六套固件、测试源码与构建报告

下表中的“烧录文件”是本轮实际核验的文件。烧录前应再次执行 `sha256sum`，确保使用的不是旧缓存。

| 组合 | 烧录文件 | 当前 SHA-256 | 板端测试程序 | 构建报告 |
| --- | --- | --- | --- | --- |
| K210 + RT-Thread | `workspace/generated/k210-rtthread/bsp/k210/rtthread.bin` | `41d39de17b7939f5b8166b89591e3c6e6f7eeac65bc96c555a6d725e64391042` | `workspace/generated/k210-rtthread/bsp/k210/applications/bspforge_validation.c` | `workspace/runs/k210-rtthread-baseline/report.json` |
| K210 + Zephyr | `workspace/generated/k210-zephyr/build/zephyr/zephyr.bin` | `baac92ecb6f1c694f585e6d04cf17420753d084ef957e18373dc9ed0546a5a67` | `workspace/generated/k210-zephyr/app/src/main.c` | `workspace/runs/k210-zephyr-v0.4/report.json` |
| STM32F103 + RT-Thread | `workspace/generated/stm32f103-rtthread/bsp/stm32/stm32f103-atk-warshipv3/rtthread.bin` | `1d92067fe926f24441e275453581d4f05dc107709db548ca2dcaebe049c9f843` | `workspace/generated/stm32f103-rtthread/bsp/stm32/stm32f103-atk-warshipv3/applications/bspforge_validation.c` | `workspace/runs/stm32f103-rtthread-v0.4/report.json` |
| STM32F103 + Zephyr | `workspace/generated/stm32f103-zephyr/build/zephyr/zephyr.hex` | `5d90002b183e7078af2f4459b3efa04e10b5487bf175f6ae2ec837813a3b81e2` | `workspace/generated/stm32f103-zephyr/app/src/main.c` | `workspace/runs/stm32f103-zephyr-v0.4/report.json` |
| PSoC E84 + RT-Thread | `workspace/generated/psoc-e84-rtthread/build/rtthread-combined.hex` | `d15979217d9cef32a2d16ac06e0d4147b14a02c7f2b6b502e4f0a3ad0b441906` | `workspace/generated/psoc-e84-rtthread/applications/bspforge_validation.c` | `workspace/runs/psoc-e84-rtthread-v0.4/report.json` |
| PSoC E84 + Zephyr | `workspace/generated/psoc-e84-zephyr/build/zephyr/zephyr.signed.hex` | `4b48ad96a5eb268caf291b0245cda8e2f3ef07c35c16b798951babf16e5a5774` | `workspace/generated/psoc-e84-zephyr/app/src/main.c` | `workspace/runs/psoc-e84-zephyr-v0.4/report.json` |

公共实现位于：

| 内容 | 文件 |
| --- | --- |
| RT-Thread 自测源码生成器 | `bspforge/os_backend/rtthread_validation.py` |
| Zephyr 自测源码生成器 | `bspforge/os_backend/zephyr.py` 中的 `_validation_source` |
| 主机执行器 | `bspforge/hardware_test/host.py` |
| 请求和 JSON 协议 | `bspforge/hardware_test/protocol.py` |
| 命令行入口 | `pyproject.toml` 中的 `bspforge-hwtest` |

PSoC E84 的 RT-Thread `rtthread.hex` 只是非安全 M33 应用，不能代替完整启动镜像。`rtthread-combined.hex` 已经过地址重定位，并与厂商 `proj_cm33_s_signed.hex` 合并。PSoC Zephyr 必须使用 `zephyr.signed.hex`，不能优先烧录未签名的 `zephyr.hex`。

### 2.1 K210 + RT-Thread 已完成的实板结果

2026-09-01 使用 CH9102 串口桥接器、`/dev/ttyACM0`、115200 baud 和同一固件完成 30 轮自动 DTR 复位回归。机器可读报告位于：

```text
workspace/hardware/k210-board-v1-20260901/k210-rtthread-30round-final.json
```

结果为启动 30/30，平均/最小/最大启动时间分别为 179.652/177.560/180.507 ms；`info`、`timer.oneshot`、`timer.periodic` 和 `stability` 共 120/120 次通过，失败为 0。未接 UART 回环线且未配置 GPIO 测试引脚，因此 `uart.loopback`、`gpio.toggle`、`gpio.irq` 共 90 次明确记录为 `unsupported`。该结果证明固件稳定启动、FinSH 命令链路和当前适用自测路径可重复执行，不证明三项跳过功能已经通过。

为适配 K210 原生 BSP，生成配置禁用了非必需的 `RT_USING_SMP`，避免该板当前双核调度初始化断言；生成 PIN 设备在系统已有全局 `pin` 设备时跳过重复注册，但仍保留生成的 `rt_pin_ops` 和链接证据。主机协议解析器同时支持 RTOS 彩色日志控制码或 shell 提示符与 JSON 位于同一行。

### 2.2 K210 + RT-Thread 绑定级回归结果

2026-09-02 使用重新生成和构建的固件完成 30 轮自动复位。BIN 大小为 467,176 bytes，SHA-256 见上表；ELF SHA-256 为 `7f2a997b79c8fec08f2b4e163123425ddf981d37082911e2ceb653966f0ba5ad`。机器报告位于：

```text
workspace/hardware/k210-board-v2-20260902/k210-rtthread-binding-30round.json
```

结果为启动 30/30，平均/最小/最大启动时间为 186.330/184.612/203.829 ms；适用命令 210/210 通过，失败 0。每轮时钟测试均返回 CPU/TIMER2 频率 403,000,000 Hz；GPIO 均得到输出低锁存 0、输出高锁存 1、IO16 上拉输入 1；中断测试得到 1 次回调，单次定时器得到 1 次回调，周期定时器得到 3 次回调。未接线的 `uart.loopback` 与 `gpio.irq` 共 60 次为 `unsupported`。

该固件由当前 `project.json` 的 `operation-weighted` Resolver 生成，不是 v0.5 LambdaMART 模型的最终部署固件。本节结果验证当前生成绑定、构建闭环与实板执行路径；正式论文若以 LambdaMART 为主方法，必须先接入并冻结最终模型，再重生成六套固件并重复相同实验，不能把本节行为结果直接归因于 LambdaMART。

GPIO 输出锁存检查证明预测的 `gpiohs_set_pin` 写入路径和目标寄存器状态成立；IO35 板载 LED 的亮灭仍建议人工记录。GPIO 输入使用独立的 IO16 上拉场景，因为 K210 SDK 的 `gpiohs_get_pin` 读取输入寄存器，而输出模式会关闭输入使能，不能把输出后直接调用输入读取函数作为合法的高电平判据。

## 3. 主机环境准备

### 3.1 安装并核验测试程序

```bash
cd /home/whk/RTT-porting/bspforge
conda run -n AIoT-v1.0 python -m pip install -e '.[hardware]'
conda run -n AIoT-v1.0 bspforge-hwtest --help
```

当前 `AIoT-v1.0` 环境已安装 pyserial 3.5。每次开始实验前创建一个不可覆盖的实验目录，例如：

```bash
export EXPERIMENT_ID=board-v1-20260831
mkdir -p workspace/hardware/$EXPERIMENT_ID
```

### 3.2 把 USB 设备连接到 WSL

若 WSL 中已经出现 `/dev/ttyUSB*` 或 `/dev/ttyACM*`，可直接继续：

```bash
lsusb
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

若设备只出现在 Windows 设备管理器中，应在管理员 PowerShell 执行：

```powershell
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

然后回到 WSL 执行 `lsusb` 和串口枚举。一次只接一块板最容易避免端口混淆。WSL USB/IP 的官方步骤见 Microsoft Learn：<https://learn.microsoft.com/windows/wsl/connect-usb>。

### 3.3 固定串口参数和设备身份

三套控制台均按 `115200, 8 data bits, no parity, 1 stop bit` 采集。正式实验前记录以下信息：

```bash
udevadm info -q property -n /dev/ttyUSB0 | sort
sha256sum <本次烧录文件>
git rev-parse HEAD
```

建议把开发板名称、芯片丝印、下载器序列号、串口设备、固件哈希、接线和日期写入同一实验目录的 `manifest.txt`。不要仅凭 `/dev/ttyUSB0` 判断板卡，因为重新插拔后编号可能变化。

## 4. 各开发板烧录

### 4.1 K210 的两套固件

K210 两个后端都使用同一种 UART ISP 流程，只需替换 BIN。官方 `kflash` 支持显式串口、下载波特率和板型参数：<https://github.com/kendryte/kflash.py>。

安装：

```bash
conda run -n AIoT-v1.0 python -m pip install kflash
```

烧录 RT-Thread：

```bash
conda run -n AIoT-v1.0 kflash \
  -p /dev/ttyUSB0 -b 2000000 \
  workspace/generated/k210-rtthread/bsp/k210/rtthread.bin
```

烧录 Zephyr：

```bash
conda run -n AIoT-v1.0 kflash \
  -p /dev/ttyUSB0 -b 2000000 \
  workspace/generated/k210-zephyr/build/zephyr/zephyr.bin
```

如果板载自动下载电路不能被自动识别，按实际 K210 板型增加 `-B dan`、`-B goE`、`-B kd233` 等参数。板型必须按手中开发板确认，不能为了让命令运行而随意选择。烧录结束后关闭 `kflash` 的串口终端，再启动 `bspforge-hwtest`，避免串口被占用。

### 4.2 STM32F103 的两套固件

该工程对应 `stm32f103-atk-warshipv3`，板载 ST-Link 负责 SWD 烧录，UART1 负责测试日志。两条 USB 链路可能分别枚举为调试器和串口。

RT-Thread BIN 的起始地址是 `0x08000000`。可使用 RT-Thread Studio/STM32CubeProgrammer，也可在 PowerShell 中使用本机 OpenOCD：

```powershell
$ocd = 'D:\RT-ThreadStudio\RT-ThreadStudio\repo\Extract\Debugger_Support_Packages\Infineon\OpenOCD-Infineon\2.0.0\bin\openocd.exe'
$scripts = 'D:\RT-ThreadStudio\RT-ThreadStudio\repo\Extract\Debugger_Support_Packages\Infineon\OpenOCD-Infineon\2.0.0\scripts'
$image = '//wsl.localhost/UbuntuD-22.04/home/whk/RTT-porting/bspforge/workspace/generated/stm32f103-rtthread/bsp/stm32/stm32f103-atk-warshipv3/rtthread.bin'
& $ocd -s $scripts -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program $image 0x08000000 verify reset exit"
```

Zephyr 已生成 OpenOCD runner，可在 WSL 中使用：

```bash
cd /home/whk/RTT-porting
conda run -n AIoT-v1.0 west flash \
  -d bspforge/workspace/generated/stm32f103-zephyr/build \
  --runner openocd
```

若 WSL 未配置 OpenOCD，也可在 Windows 编程工具中直接选择：

```text
\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\generated\stm32f103-zephyr\build\zephyr\zephyr.hex
```

Zephyr 官方说明确认 `west flash -d <build-dir>` 会使用构建目录中的 runner 配置：<https://docs.zephyrproject.org/latest/develop/west/build-flash-debug.html>。

### 4.3 PSoC E84 的两套固件

使用板载 KitProg3/DAP。RT-Thread 应烧录合并后的：

```text
workspace/generated/psoc-e84-rtthread/build/rtthread-combined.hex
```

Zephyr 应烧录签名后的：

```text
workspace/generated/psoc-e84-zephyr/build/zephyr/zephyr.signed.hex
```

本机已经安装 Infineon ModusToolbox Programming Tools 1.8，OpenOCD 位于：

```text
C:\Infineon\Tools\ModusToolboxProgtools-1.8\openocd\bin\openocd.exe
```

推荐先使用 ModusToolbox Programmer 或 RT-Thread Studio 2.2.9 及以上版本选择对应 HEX 烧录。命令行方式应使用同一安装目录下的 `interface/kitprog3.cfg` 和 `target/infineon/pse84xgxs2.cfg`；执行前先运行 `openocd.exe --version` 并确认 KitProg3 被识别。PSoC E84 涉及安全核与非安全核启动顺序，若工具报告保护状态、签名或生命周期错误，应停止并保存完整日志，不要改用未签名 HEX 绕过。

Zephyr 构建目录已经把默认 runner 固定为 OpenOCD：

```bash
cd /home/whk/RTT-porting
conda run -n AIoT-v1.0 west flash \
  -d bspforge/workspace/generated/psoc-e84-zephyr/build \
  --runner openocd
```

PSoC RT-Thread 工程的控制台是 `uart2`；烧录探针与日志串口并非必须是同一设备节点。必须从 UART2 对应的 USB-to-UART 端口采集 JSON。

## 5. 六套组合的运行命令

### 5.1 先做单轮冒烟

每次烧录后先运行一轮，确认能收到如下启动行：

```json
{"bspforge":true,"protocol":"1.0","event":"boot","rtos":"rtthread","board":"...","build_id":"...","stage":"application"}
```

主机程序在每轮开始时切换串口 DTR 尝试复位。如果某块板的 DTR 没有连接到复位电路，应使用 `--rounds 1 --timeout 15` 启动程序后立即按板上 RESET；这种人工操作可验证启动，但人工反应时间不能作为论文中的精确启动耗时。

K210 + RT-Thread：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyUSB0 --board k210 --rtos rtthread \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/k210-rtthread-smoke.json
```

K210 + Zephyr：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyUSB0 --board k210 --rtos zephyr \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/k210-zephyr-smoke.json
```

STM32F103 + RT-Thread：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyUSB0 --board stm32f103-atk-warshipv3 --rtos rtthread \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/stm32f103-rtthread-smoke.json
```

STM32F103 + Zephyr：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyUSB0 --board stm32_min_dev --rtos zephyr \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/stm32f103-zephyr-smoke.json
```

PSoC E84 + RT-Thread：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyACM0 --board psoc_e84-edgi-talk --rtos rtthread \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/psoc-e84-rtthread-smoke.json
```

PSoC E84 + Zephyr：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --port /dev/ttyACM0 --board kit_pse84_eval --rtos zephyr \
  --baudrate 115200 --timeout 15 --rounds 1 \
  --output workspace/hardware/$EXPERIMENT_ID/psoc-e84-zephyr-smoke.json
```

上述 `/dev/ttyUSB0` 和 `/dev/ttyACM0` 只是示例，必须替换为本次 `udevadm` 核验后的设备。

### 5.2 正式重复实验

确认 DTR 能自动复位后，将同一组合改为 `--rounds 30 --timeout 5`，输出文件去掉 `-smoke`。若 DTR 不能自动复位，应先完成自动复位接线或调试器复位脚本；不要把 30 次人工按键得到的反应时间当作启动时间分布。

建议正式文件固定为：

```text
workspace/hardware/<EXPERIMENT_ID>/k210-rtthread.json
workspace/hardware/<EXPERIMENT_ID>/k210-zephyr.json
workspace/hardware/<EXPERIMENT_ID>/stm32f103-rtthread.json
workspace/hardware/<EXPERIMENT_ID>/stm32f103-zephyr.json
workspace/hardware/<EXPERIMENT_ID>/psoc-e84-rtthread.json
workspace/hardware/<EXPERIMENT_ID>/psoc-e84-zephyr.json
```

## 6. 测试执行时的数据流

每轮按以下顺序执行：

1. 主机复位或等待开发板复位，并清空串口输入缓存。
2. 固件在应用初始化阶段输出 `boot` JSON，包含协议、RTOS、板卡、SDK 摘要构建 ID 和启动阶段。
3. 主机依次发送七个带随机 `request_id` 的命令。
4. 固件输出同一 `request_id` 的 `result` JSON，状态只能是 `pass`、`fail` 或 `unsupported`。
5. 主机记录命令往返时间、板端 `metrics` 和没有被协议解析的原始 RTOS 日志。
6. 全部轮次结束后写入一个 JSON 文件，控制台只打印汇总。

报告结构为：

```text
schema_version
created_at
board
rtos
rounds[]
  round
  boot_success
  boot_time_ms
  boot_event
  commands[]
    request_id
    command
    status
    metrics
    host_round_trip_ms
raw_log[]
summary
```

`raw_log` 是后续排查最重要的证据，既包含 JSON，也可能包含 RT-Thread banner、Zephyr printk、断言、HardFault 和重启信息。不要只保留终端打印的 `summary`。

## 7. 结果判定和后续分析输入

### 7.1 主机汇总字段

- `boot_successes/boot_attempts`：超时内收到启动事件的次数。
- `boot_success_rate`：启动成功率。
- `boot_time_mean_ms/min/max`：从复位动作结束到主机读到启动事件的时间。
- `commands_passed/commands_applicable`：通过命令数与排除 `unsupported` 后的适用命令数。
- `commands_total`：所有已发送命令数。
- `failed`：明确失败或主机等待超时的命令数。
- `unsupported`：固件没有实现或当前接线不满足的命令数。

当前 CLI 的退出码只根据 `failed` 判断，不能单靠退出码判定整套实验成功。还必须检查 `boot_success_rate`、`commands_applicable` 和 `unsupported`。如果全部外设命令都为 `unsupported`，即使退出码为 0，也只能说明协议没有报告显式失败。

### 7.2 论文级最低记录要求

每个组合至少保存：

- 30 次冷/硬复位启动结果和固定复位方式；
- 固件 SHA-256、Git 提交、工具链版本和下载器版本；
- UART TX-RX 实际回环的字节数、错误数和超时；
- GPIO 输出翻转的逻辑分析仪或示波器证据；
- GPIO 输入边沿与中断计数；
- 单次和周期定时器的回调次数、平均误差、最大误差、抖动和丢失次数；
- 至少 1 小时稳定运行或等价的高轮次压力结果；
- 所有失败、重启、HardFault 和 `unsupported`，不删除异常轮次。

六套组合验证的是 3 个硬件平台与 2 个 OS 集成路径，不等于 6 个彼此独立的 SDK 样本。论文中应把 20 余 SDK 的离线语义评测、6/6 构建闭环、native_sim 重复实验和六套实板行为验证分开报告。

### 7.3 建议增加的对照组

仅证明“生成固件能运行”还不足以解释工具价值。每块板至少选择一个人工维护的原生 BSP/示例作为对照，记录：

- 从 SDK 输入到首次构建成功的总时间；
- 自动诊断迭代次数和人工修改次数；
- 生成/修改代码行数；
- 构建成功率和上板命令通过率；
- Flash/RAM 占用；
- UART 吞吐、GPIO 中断延迟、定时器误差等功能指标与人工 BSP 的差值。

这样可以区分“RTOS 原生驱动本身可用”和“BSPForge 恢复语义、组织依赖并生成后端工程所带来的增量价值”。

## 8. 常见故障

| 现象 | 优先检查 |
| --- | --- |
| 找不到串口 | `usbipd list`、`lsusb`、设备是否仍被 Windows 占用、USB 线是否只有供电 |
| 串口被占用 | 关闭 kflash terminal、串口助手、RT-Thread Studio console 和其他 pyserial 进程 |
| 能看到 RTOS banner，但没有 boot JSON | 确认烧录哈希；确认使用本轮重新生成的固件；检查 `raw_log` 是否有初始化错误 |
| 第一轮通过，后续轮次 boot timeout | DTR 没有连接到硬件复位，改做单轮人工复位或配置调试器自动复位 |
| 命令全部 host-timeout | RT-Thread 检查 FinSH 是否启动；Zephyr 检查 console RX；确认换行与波特率 |
| PSoC RT-Thread 无法启动 | 确认烧录 `rtthread-combined.hex`，而不是根目录的未合并 `rtthread.hex` |
| PSoC Zephyr 无法启动 | 确认烧录 `zephyr.signed.hex`，并记录具体板卡安全配置与 Zephyr 兼容板目标差异 |
| `unsupported` 很多 | 这是当前测试实现或接线边界，不是通过；补齐回环线、测试引脚与板端实现后重新生成固件 |
| CLI 返回 0 但启动率为 0 | 当前退出码未包含启动失败，必须以 JSON 汇总和原始日志为准 |

## 9. 仿真回归位置

实板之前可先复查统一协议的 native_sim 结果：

```text
experiments/generated/zephyr-native-simulation.json
```

复现命令：

```bash
conda run -n AIoT-v1.0 bspforge-hwtest \
  --command workspace/generated/simulation-zephyr-native/build/zephyr/zephyr.exe \
  --board native_sim --rtos zephyr --rounds 20 \
  --output experiments/generated/zephyr-native-simulation.json
```

仿真用于验证协议、OS API 行为和重复性，不能替代真实时钟、中断、电气连接和芯片启动链验证。
