# STM32F103 冻结 LambdaMART 双 RTOS 实板验证 v2.5

## 1. 验证目标

本轮以 正点原子战舰 V3（STM32F103ZET6）为目标板，冻结语义模型与部署规则后，分别生成 RT-Thread 和 Zephyr 工程。实验验证以下链路是否闭合：

```text
STM32CubeF1 SDK -> Migration IR -> LambdaMART 排序
-> 签名/家族约束解码 -> 闭包与编译诊断
-> RTOS 原生设备接口 -> 固件 -> 实板功能回归
```

目标能力为时钟、中断、UART、GPIO 和硬件定时器，共 19 项规范操作。实板每轮执行设备信息、时钟、基础中断、UART 回环、GPIO 电平、GPIO 中断、定时器单次、定时器周期和稳定性九条命令。

## 2. 冻结输入与语义结果

| 项目 | 数值或位置 |
| --- | --- |
| SDK | `sdk/stm32f103/source` |
| IR 摘要 | 3,921 文件、15,250 函数、50,411 条边 |
| IR 标识 | `0870692ef7f56a48` |
| 运行时模型包 | `models/runtime/stm32f103-operation-lambdamart-h03-eq-r1-v2.3.json` |
| 候选预算 | 每项操作最多 256 个，不读取目标真值 |
| 后验真值 | 仅在运行时包生成后用于评估 |
| P@1 / Recall@5 | 0.611 / 0.643 |
| MAP / nDCG@10 / Hit@5 | 0.586 / 0.674 / 0.944 |

18 个具有稳定单函数真值的操作进入严格指标，`gpio.attach_irq` 因需要组合多个接口而单独记录。P@1 表明原始首位仍有错误，不能用实板通过率把它改写为 1；Hit@5 较高说明正确或等价实现通常已进入短名单。部署解码只使用函数签名、动作契约和 API 家族一致性，从短名单中形成可执行组合，不读取 H03 或板卡符号白名单。

## 3. 接线与主机环境

| 用途 | 连接 |
| --- | --- |
| 调试与烧录 | J-Link 20 针接口，SWD，目标参考电压约 3.3 V |
| 协议控制台 | 板载 `USB_UART`，Windows `COM5`，115200 8N1，无流控 |
| UART3 外部回环 | PB10（TX）连接 PB11（RX） |
| GPIO 电平与中断 | PB0（输出）连接 PB1（输入） |

板卡由自身 USB/电源接口供电；J-Link 的 VTref 用于识别目标逻辑电平。测试前关闭串口助手，避免占用 COM5。

## 4. 工程生成与构建

在 WSL 中执行：

```bash
cd /home/whk/RTT-porting/bspforge
/home/whk/miniconda3/bin/conda run --no-capture-output -n AIoT-v1.0 \
  bspforge pipeline --config examples/stm32f103-rtthread/project.json

/home/whk/miniconda3/bin/conda run --no-capture-output -n AIoT-v1.0 \
  bspforge pipeline --config examples/stm32f103-zephyr/project.json
```

RT-Thread 第一次链接根据未定义符号加入 `stm32f1xx_hal_tim.c`，第二次加入 `stm32f1xx_hal_tim_ex.c`，第三次成功。Zephyr 第一次构建成功。两套工程均生成 19/19 项绑定，编译反馈均观察到 19/19 项处置。

STM32 RT-Thread 后端还执行三项通用兼容处理：把使用 CMSIS 默认启动文件时的应用入口从 `main` 修正到 RT-Thread 的 `entry`；按配置中的 UART 实例与引脚生成缺失的 HAL MSP 分支；将机器协议控制台缓冲区设为 512 字节，防止 JSON 被 FinSH 默认缓冲区截断。这些规则由芯片族、函数签名和工程配置触发，不包含本次真值函数或板卡专用回退。

## 5. 固件与烧录

| RTOS | 固件 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| RT-Thread | `workspace/generated/stm32f103-rtthread-lambdamart/bsp/stm32/stm32f103-atk-warshipv3/rtthread.bin` | 87,184 B | `f108a92c4411d14dd617646a3ee482e470a88bf5da3cc574ca604d53fe56c4bd` |
| Zephyr | `workspace/generated/stm32f103-zephyr-lambdamart/build/zephyr/zephyr.bin` | 28,600 B | `0a4f5521299f674ed3bb07faa4c64cc30d8b63d2018508b6e0d4af7019d0f675` |

在 Windows PowerShell 中烧录 RT-Thread：

```powershell
py -3 "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\scripts\stm32_jlink.py" program `
  --firmware "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\generated\stm32f103-rtthread-lambdamart\bsp\stm32\stm32f103-atk-warshipv3\rtthread.bin"
```

烧录 Zephyr 时只替换 `--firmware`：

```powershell
py -3 "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\scripts\stm32_jlink.py" program `
  --firmware "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\generated\stm32f103-zephyr-lambdamart\build\zephyr\zephyr.bin"
```

脚本固定使用 `STM32F103ZE`、SWD、4 MHz，依次复位、暂停、写入 `0x08000000`、逐字节验证、再次复位并运行。出现 `Verify successful` 后才返回成功。

## 6. 十轮回归

主机测试直接访问 Windows COM5。RT-Thread 命令为：

```powershell
$env:PYTHONPATH='\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge'
py -3 -m bspforge.hardware_test.host --port COM5 `
  --board stm32f103-atk-warshipv3 --rtos rtthread --baudrate 115200 `
  --timeout 5 --rounds 10 `
  --firmware "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\generated\stm32f103-rtthread-lambdamart\bsp\stm32\stm32f103-atk-warshipv3\rtthread.bin" `
  --output "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\hardware\stm32f103-lambdamart-20260906\stm32f103-rtthread-full-10rounds.json"
```

Zephyr 使用同一协议，但允许幂等测试命令在串口帧不完整时重试两次：

```powershell
$env:PYTHONPATH='\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge'
py -3 -m bspforge.hardware_test.host --port COM5 `
  --board stm32f103-atk-warshipv3 --rtos zephyr --baudrate 115200 `
  --timeout 5 --rounds 10 --command-retries 2 `
  --firmware "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\generated\stm32f103-zephyr-lambdamart\build\zephyr\zephyr.bin" `
  --output "\\wsl.localhost\UbuntuD-22.04\home\whk\RTT-porting\bspforge\workspace\hardware\stm32f103-lambdamart-20260906\stm32f103-zephyr-full-10rounds-retry-aware.json"
```

## 7. 实验结果

| RTOS | 启动 | 功能命令 | 失败 | unsupported | 启动均值 | 传输重试 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RT-Thread | 10/10 | 90/90 | 0 | 0 | 2.891 ms | 0 |
| Zephyr | 10/10 | 90/90 | 0 | 0 | 2.233 ms | 2 |

RT-Thread 每轮 UART 收发 16 字节且错误为 0，PB0/PB1 电平低/高均正确，GPIO 中断、TIM2 单次和周期回调均达到预期。Zephyr 通过 `uart`、`gpio`、`counter` 等公共设备 API 完成同一组验证。

Zephyr 两份不重试原始报告分别为 89/90 和 88/90。原始日志显示缺失的是请求 ID 或整行响应的部分串口字节，紧邻命令和重试后的同一硬件功能均通过。最终报告因此把两次首次超时记为 `transport_retries=2`，不能表述成没有异常的 90 次首次响应，也不能记为硬件功能失败。

## 8. 结论边界

本轮支持以下结论：在冻结输入和通用部署规则下，系统为 STM32F103ZET6 生成了可构建固件，并通过 RT-Thread 与 Zephyr 的原生设备接口完成五类目标能力的实板回归。它不代表 SDK 中全部外设已经迁移，也不代表原始语义排序达到完美准确率。排序、编译反馈、OS 接入和实板功能是四类互补证据，应在论文中分别报告。

提交用机器证据位于 `experiments/hardware-results/stm32f103-operation-lambdamart-v2.5/`；工作区内的完整日志位于 `workspace/runs/` 和 `workspace/hardware/stm32f103-lambdamart-20260906/`。
