# PSoC E84 Edgi-Talk SDK 输入

`source` 由 `scripts/bootstrap_local_inputs.sh` 链接到 Edgi-Talk SDK 的 `libraries` 目录，避免把示例工程和 RTOS 源码重复计入 SDK IR。RT-Thread 后端复用该 SDK 自带的 M33 工程模板和设备驱动，Zephyr 后端复用其上游 PSoC Edge E84 HAL 模块。

Zephyr 4.4 尚无名为 Edgi-Talk 的板级条目，因此使用 SoC、串口和 LED 引脚兼容的 `kit_pse84_eval/pse846gps2dbzc4a/m33` 作为基线。最终硬件结论必须以上板回归结果为准。
