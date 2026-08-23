# STM32F103 SDK 输入

`source` 由 `scripts/bootstrap_local_inputs.sh` 链接到官方 STM32CubeF1 源码树。流水线从其中解析 CMSIS、STM32F1 HAL、启动文件和构建资产；仓库只保存输入说明，不提交第三方 SDK 本体。

当前实物目标为 STM32F103 最小系统板。RT-Thread 使用同芯片的成熟 STM32F103 BSP 作为原生工程基线，Zephyr 使用 `stm32_min_dev@black/stm32f103xb` 板级目标。
