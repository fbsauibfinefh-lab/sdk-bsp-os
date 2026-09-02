# 六套上板组合的能力操作语义选择对照

> 本文档由 `scripts/generate_board_truth_comparison.py` 自动生成。系统对每个存在候选的能力操作始终输出最终分数最高的 Top1；低分标记只提示复核，不会取消选择。

## 口径说明

- 六套组合由三款开发板 SDK 与 RT-Thread、Zephyr 两个后端交叉形成。
- 语义排序发生在 SDK 侧，因此同一开发板的两个 RTOS 后端共享同一个 SDK API 选择结果；二者后续生成的设备对象、注册代码和构建资产不同。表格保留六套组合，是为了直接服务后续逐组合编译和上板记录。
- `H01` 与 `H02` 列列出对应平行真值中标签大于 0 的全部可接受符号。系统 Top1 落入该集合即记为一致。
- 当前三块板卡的 H01/H02 条目继承同一套 `source-audited` 板卡标注，不代表两位工程师分别对板卡样本完成了独立复核。
- `低分/弱证据` 不属于正确性判定指标，也不影响 Top1 输出。其用途是指出应优先人工检查的操作。

## 汇总

| 组合 | 操作数 | H01 一致 | H02 一致 | 双真值一致 | 低分/弱证据 |
|---|---:|---:|---:|---:|---:|
| Kendryte K210 + RT-Thread | 19 | 19 | 19 | 19 | 0 |
| Kendryte K210 + Zephyr | 19 | 19 | 19 | 19 | 0 |
| STM32F103 + RT-Thread | 14 | 14 | 14 | 14 | 1 |
| STM32F103 + Zephyr | 14 | 14 | 14 | 14 | 1 |
| PSoC E84 EDGI-Talk + RT-Thread | 17 | 17 | 17 | 17 | 0 |
| PSoC E84 EDGI-Talk + Zephyr | 17 | 17 | 17 | 17 | 0 |

## Kendryte K210 + RT-Thread

SDK 标识：`kendryte-k210-standalone-sdk-0.5.6`；OS 后端：`RT-Thread`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.disable | `sysctl_clock_disable` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_disable` | 是 | `sysctl_clock_disable` | 是 |
| clock.enable | `sysctl_clock_enable` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_enable` | 是 | `sysctl_clock_enable` | 是 |
| clock.get_frequency | `sysctl_clock_source_get_freq` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_get_freq`<br>`sysctl_clock_source_get_freq` | 是 | `sysctl_clock_get_freq`<br>`sysctl_clock_source_get_freq` | 是 |
| clock.initialize | `sysctl_clock_set_clock_select` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_set_clock_select`<br>`sysctl_pll_set_freq` | 是 | `sysctl_clock_set_clock_select`<br>`sysctl_pll_set_freq` | 是 |
| interrupt.disable | `plic_irq_disable` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_disable` | 是 | `plic_irq_disable` | 是 |
| interrupt.enable | `plic_irq_enable` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_enable` | 是 | `plic_irq_enable` | 是 |
| interrupt.initialize | `plic_init` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_init` | 是 | `plic_init` | 是 |
| interrupt.register | `plic_irq_register` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_register`<br>`plic_irq_unregister` | 是 | `plic_irq_register`<br>`plic_irq_unregister` | 是 |
| uart.configure | `uart_configure` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_configure`<br>`uart_init` | 是 | `uart_configure`<br>`uart_init` | 是 |
| uart.read | `uart_receive_data_dma` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_receive_data`<br>`uart_receive_data_dma`<br>`uart_receive_data_dma_irq` | 是 | `uart_receive_data`<br>`uart_receive_data_dma`<br>`uart_receive_data_dma_irq` | 是 |
| uart.write | `uart_send_data` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_send_data` | 是 | `uart_send_data` | 是 |
| gpio.attach_irq | `gpiohs_irq_register` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpiohs_irq_register`<br>`gpiohs_irq_unregister` | 是 | `gpiohs_irq_register`<br>`gpiohs_irq_unregister` | 是 |
| gpio.configure | `gpiohs_set_drive_mode` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpiohs_set_drive_mode`<br>`gpiohs_set_pin_edge`<br>`gpio_set_drive_mode` | 是 | `gpiohs_set_drive_mode`<br>`gpiohs_set_pin_edge`<br>`gpio_set_drive_mode` | 是 |
| gpio.read | `gpiohs_get_pin` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpio_get_pin`<br>`gpiohs_get_pin` | 是 | `gpio_get_pin`<br>`gpiohs_get_pin` | 是 |
| gpio.write | `gpiohs_set_pin` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpio_set_pin`<br>`gpiohs_set_pin` | 是 | `gpio_set_pin`<br>`gpiohs_set_pin` | 是 |
| timer.initialize | `timer_init` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_init` | 是 | `timer_init` | 是 |
| timer.set_interval | `timer_set_interval` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_interval` | 是 | `timer_set_interval` | 是 |
| timer.start | `timer_set_enable` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_enable`<br>`timer_enable` | 是 | `timer_set_enable`<br>`timer_enable` | 是 |
| timer.stop | `timer_disable` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_enable`<br>`timer_disable` | 是 | `timer_set_enable`<br>`timer_disable` | 是 |


## Kendryte K210 + Zephyr

SDK 标识：`kendryte-k210-standalone-sdk-0.5.6`；OS 后端：`Zephyr`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.disable | `sysctl_clock_disable` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_disable` | 是 | `sysctl_clock_disable` | 是 |
| clock.enable | `sysctl_clock_enable` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_enable` | 是 | `sysctl_clock_enable` | 是 |
| clock.get_frequency | `sysctl_clock_source_get_freq` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_get_freq`<br>`sysctl_clock_source_get_freq` | 是 | `sysctl_clock_get_freq`<br>`sysctl_clock_source_get_freq` | 是 |
| clock.initialize | `sysctl_clock_set_clock_select` | `lib/drivers/sysctl.c` | 1.000000 | 否 | `sysctl_clock_set_clock_select`<br>`sysctl_pll_set_freq` | 是 | `sysctl_clock_set_clock_select`<br>`sysctl_pll_set_freq` | 是 |
| interrupt.disable | `plic_irq_disable` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_disable` | 是 | `plic_irq_disable` | 是 |
| interrupt.enable | `plic_irq_enable` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_enable` | 是 | `plic_irq_enable` | 是 |
| interrupt.initialize | `plic_init` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_init` | 是 | `plic_init` | 是 |
| interrupt.register | `plic_irq_register` | `lib/drivers/plic.c` | 1.000000 | 否 | `plic_irq_register`<br>`plic_irq_unregister` | 是 | `plic_irq_register`<br>`plic_irq_unregister` | 是 |
| uart.configure | `uart_configure` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_configure`<br>`uart_init` | 是 | `uart_configure`<br>`uart_init` | 是 |
| uart.read | `uart_receive_data_dma` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_receive_data`<br>`uart_receive_data_dma`<br>`uart_receive_data_dma_irq` | 是 | `uart_receive_data`<br>`uart_receive_data_dma`<br>`uart_receive_data_dma_irq` | 是 |
| uart.write | `uart_send_data` | `lib/drivers/uart.c` | 1.000000 | 否 | `uart_send_data` | 是 | `uart_send_data` | 是 |
| gpio.attach_irq | `gpiohs_irq_register` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpiohs_irq_register`<br>`gpiohs_irq_unregister` | 是 | `gpiohs_irq_register`<br>`gpiohs_irq_unregister` | 是 |
| gpio.configure | `gpiohs_set_drive_mode` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpiohs_set_drive_mode`<br>`gpiohs_set_pin_edge`<br>`gpio_set_drive_mode` | 是 | `gpiohs_set_drive_mode`<br>`gpiohs_set_pin_edge`<br>`gpio_set_drive_mode` | 是 |
| gpio.read | `gpiohs_get_pin` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpio_get_pin`<br>`gpiohs_get_pin` | 是 | `gpio_get_pin`<br>`gpiohs_get_pin` | 是 |
| gpio.write | `gpiohs_set_pin` | `lib/drivers/gpiohs.c` | 1.000000 | 否 | `gpio_set_pin`<br>`gpiohs_set_pin` | 是 | `gpio_set_pin`<br>`gpiohs_set_pin` | 是 |
| timer.initialize | `timer_init` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_init` | 是 | `timer_init` | 是 |
| timer.set_interval | `timer_set_interval` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_interval` | 是 | `timer_set_interval` | 是 |
| timer.start | `timer_set_enable` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_enable`<br>`timer_enable` | 是 | `timer_set_enable`<br>`timer_enable` | 是 |
| timer.stop | `timer_disable` | `lib/drivers/timer.c` | 1.000000 | 否 | `timer_set_enable`<br>`timer_disable` | 是 | `timer_set_enable`<br>`timer_disable` | 是 |


## STM32F103 + RT-Thread

SDK 标识：`stm32cube-f1`；OS 后端：`RT-Thread`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.get_frequency | `RCC_PLL2_GetFreqClockFreq` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_ll_rcc.c` | 1.000000 | 否 | `HAL_RCC_GetHCLKFreq`<br>`HAL_RCC_GetPCLK1Freq`<br>`HAL_RCC_GetPCLK2Freq`<br>`HAL_RCC_GetSysClockFreq`<br>`RCC_PLL2_GetFreqClockFreq` | 是 | `HAL_RCC_GetHCLKFreq`<br>`HAL_RCC_GetPCLK1Freq`<br>`HAL_RCC_GetPCLK2Freq`<br>`HAL_RCC_GetSysClockFreq`<br>`RCC_PLL2_GetFreqClockFreq` | 是 |
| clock.initialize | `HAL_RCC_ClockConfig` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_rcc.c` | 1.000000 | 否 | `HAL_RCC_ClockConfig`<br>`HAL_RCC_OscConfig` | 是 | `HAL_RCC_ClockConfig`<br>`HAL_RCC_OscConfig` | 是 |
| interrupt.disable | `HAL_NVIC_DisableIRQ` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | 否 | `HAL_NVIC_DisableIRQ` | 是 | `HAL_NVIC_DisableIRQ` | 是 |
| interrupt.enable | `HAL_NVIC_EnableIRQ` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | 否 | `HAL_NVIC_EnableIRQ` | 是 | `HAL_NVIC_EnableIRQ` | 是 |
| interrupt.initialize | `HAL_NVIC_SetPriority` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | `weak-operation-contract` | `HAL_NVIC_SetPriority` | 是 | `HAL_NVIC_SetPriority` | 是 |
| uart.configure | `HAL_UART_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_DeInit`<br>`HAL_UART_Init` | 是 | `HAL_UART_DeInit`<br>`HAL_UART_Init` | 是 |
| uart.read | `HAL_UART_Receive_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_Receive`<br>`HAL_UART_Receive_IT` | 是 | `HAL_UART_Receive`<br>`HAL_UART_Receive_IT` | 是 |
| uart.write | `HAL_UART_Transmit_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_Transmit`<br>`HAL_UART_Transmit_IT` | 是 | `HAL_UART_Transmit`<br>`HAL_UART_Transmit_IT` | 是 |
| gpio.configure | `HAL_GPIO_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_DeInit`<br>`HAL_GPIO_Init` | 是 | `HAL_GPIO_DeInit`<br>`HAL_GPIO_Init` | 是 |
| gpio.read | `HAL_GPIO_ReadPin` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_ReadPin` | 是 | `HAL_GPIO_ReadPin` | 是 |
| gpio.write | `HAL_GPIO_WritePin` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_TogglePin`<br>`HAL_GPIO_WritePin` | 是 | `HAL_GPIO_TogglePin`<br>`HAL_GPIO_WritePin` | 是 |
| timer.initialize | `HAL_TIM_Base_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Init` | 是 | `HAL_TIM_Base_Init` | 是 |
| timer.start | `HAL_TIM_Base_Start` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Start`<br>`HAL_TIM_Base_Start_IT` | 是 | `HAL_TIM_Base_Start`<br>`HAL_TIM_Base_Start_IT` | 是 |
| timer.stop | `HAL_TIM_Base_Stop_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Stop`<br>`HAL_TIM_Base_Stop_IT` | 是 | `HAL_TIM_Base_Stop`<br>`HAL_TIM_Base_Stop_IT` | 是 |


## STM32F103 + Zephyr

SDK 标识：`stm32cube-f1`；OS 后端：`Zephyr`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.get_frequency | `RCC_PLL2_GetFreqClockFreq` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_ll_rcc.c` | 1.000000 | 否 | `HAL_RCC_GetHCLKFreq`<br>`HAL_RCC_GetPCLK1Freq`<br>`HAL_RCC_GetPCLK2Freq`<br>`HAL_RCC_GetSysClockFreq`<br>`RCC_PLL2_GetFreqClockFreq` | 是 | `HAL_RCC_GetHCLKFreq`<br>`HAL_RCC_GetPCLK1Freq`<br>`HAL_RCC_GetPCLK2Freq`<br>`HAL_RCC_GetSysClockFreq`<br>`RCC_PLL2_GetFreqClockFreq` | 是 |
| clock.initialize | `HAL_RCC_ClockConfig` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_rcc.c` | 1.000000 | 否 | `HAL_RCC_ClockConfig`<br>`HAL_RCC_OscConfig` | 是 | `HAL_RCC_ClockConfig`<br>`HAL_RCC_OscConfig` | 是 |
| interrupt.disable | `HAL_NVIC_DisableIRQ` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | 否 | `HAL_NVIC_DisableIRQ` | 是 | `HAL_NVIC_DisableIRQ` | 是 |
| interrupt.enable | `HAL_NVIC_EnableIRQ` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | 否 | `HAL_NVIC_EnableIRQ` | 是 | `HAL_NVIC_EnableIRQ` | 是 |
| interrupt.initialize | `HAL_NVIC_SetPriority` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c` | 1.000000 | `weak-operation-contract` | `HAL_NVIC_SetPriority` | 是 | `HAL_NVIC_SetPriority` | 是 |
| uart.configure | `HAL_UART_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_DeInit`<br>`HAL_UART_Init` | 是 | `HAL_UART_DeInit`<br>`HAL_UART_Init` | 是 |
| uart.read | `HAL_UART_Receive_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_Receive`<br>`HAL_UART_Receive_IT` | 是 | `HAL_UART_Receive`<br>`HAL_UART_Receive_IT` | 是 |
| uart.write | `HAL_UART_Transmit_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c` | 1.000000 | 否 | `HAL_UART_Transmit`<br>`HAL_UART_Transmit_IT` | 是 | `HAL_UART_Transmit`<br>`HAL_UART_Transmit_IT` | 是 |
| gpio.configure | `HAL_GPIO_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_DeInit`<br>`HAL_GPIO_Init` | 是 | `HAL_GPIO_DeInit`<br>`HAL_GPIO_Init` | 是 |
| gpio.read | `HAL_GPIO_ReadPin` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_ReadPin` | 是 | `HAL_GPIO_ReadPin` | 是 |
| gpio.write | `HAL_GPIO_WritePin` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c` | 1.000000 | 否 | `HAL_GPIO_TogglePin`<br>`HAL_GPIO_WritePin` | 是 | `HAL_GPIO_TogglePin`<br>`HAL_GPIO_WritePin` | 是 |
| timer.initialize | `HAL_TIM_Base_Init` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Init` | 是 | `HAL_TIM_Base_Init` | 是 |
| timer.start | `HAL_TIM_Base_Start` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Start`<br>`HAL_TIM_Base_Start_IT` | 是 | `HAL_TIM_Base_Start`<br>`HAL_TIM_Base_Start_IT` | 是 |
| timer.stop | `HAL_TIM_Base_Stop_IT` | `Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_tim.c` | 1.000000 | 否 | `HAL_TIM_Base_Stop`<br>`HAL_TIM_Base_Stop_IT` | 是 | `HAL_TIM_Base_Stop`<br>`HAL_TIM_Base_Stop_IT` | 是 |


## PSoC E84 EDGI-Talk + RT-Thread

SDK 标识：`psoc-e84-edgi-talk-sdk`；OS 后端：`RT-Thread`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.disable | `mtb_hal_clock_set_peri_clock_enabled` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 |
| clock.enable | `mtb_hal_clock_set_peri_clock_enabled` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 |
| clock.get_frequency | `mtb_hal_clock_get_peri_src_clock_freq` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_get_hf_clock_freq`<br>`mtb_hal_clock_get_peri_clock_freq`<br>`mtb_hal_clock_get_peri_src_clock_freq` | 是 | `mtb_hal_clock_get_hf_clock_freq`<br>`mtb_hal_clock_get_peri_clock_freq`<br>`mtb_hal_clock_get_peri_src_clock_freq` | 是 |
| clock.initialize | `mtb_hal_clock_set_peri_clock_freq` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_freq`<br>`mtb_hal_clock_set_peri_clock_freq` | 是 | `mtb_hal_clock_set_hf_clock_freq`<br>`mtb_hal_clock_set_peri_clock_freq` | 是 |
| interrupt.initialize | `Cy_SysInt_Init` | `components/mtb-device-support-pse8xxgp/pdl/drivers/source/cy_sysint_v2.c` | 1.000000 | 否 | `Cy_SysInt_Init` | 是 | `Cy_SysInt_Init` | 是 |
| interrupt.register | `Cy_SysInt_SetVector` | `components/mtb-device-support-pse8xxgp/pdl/drivers/source/cy_sysint_v2.c` | 1.000000 | 否 | `Cy_SysInt_SetVector` | 是 | `Cy_SysInt_SetVector` | 是 |
| uart.configure | `mtb_hal_uart_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_set_baud`<br>`mtb_hal_uart_setup` | 是 | `mtb_hal_uart_set_baud`<br>`mtb_hal_uart_setup` | 是 |
| uart.read | `mtb_hal_uart_read` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_read` | 是 | `mtb_hal_uart_read` | 是 |
| uart.write | `mtb_hal_uart_write` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_write` | 是 | `mtb_hal_uart_write` | 是 |
| gpio.attach_irq | `mtb_hal_gpio_register_callback` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_gpio.c` | 1.000000 | 否 | `mtb_hal_gpio_enable_event`<br>`mtb_hal_gpio_register_callback` | 是 | `mtb_hal_gpio_enable_event`<br>`mtb_hal_gpio_register_callback` | 是 |
| gpio.configure | `mtb_hal_gpio_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_gpio.c` | 1.000000 | 否 | `mtb_hal_gpio_configure`<br>`mtb_hal_gpio_setup` | 是 | `mtb_hal_gpio_configure`<br>`mtb_hal_gpio_setup` | 是 |
| gpio.read | `mtb_hal_gpio_port_read_internal` | `components/mtb-device-support-pse8xxgp/hal/include/mtb_hal_gpio_impl.h` | 1.000000 | 否 | `mtb_hal_gpio_read_internal`<br>`Cy_GPIO_Read`<br>`mtb_hal_gpio_port_read_internal` | 是 | `mtb_hal_gpio_read_internal`<br>`Cy_GPIO_Read`<br>`mtb_hal_gpio_port_read_internal` | 是 |
| gpio.write | `mtb_hal_gpio_port_write_internal` | `components/mtb-device-support-pse8xxgp/hal/include/mtb_hal_gpio_impl.h` | 1.000000 | 否 | `mtb_hal_gpio_toggle_internal`<br>`mtb_hal_gpio_write_internal`<br>`Cy_GPIO_Write`<br>`mtb_hal_gpio_port_write_internal` | 是 | `mtb_hal_gpio_toggle_internal`<br>`mtb_hal_gpio_write_internal`<br>`Cy_GPIO_Write`<br>`mtb_hal_gpio_port_write_internal` | 是 |
| timer.initialize | `mtb_hal_timer_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_Init` | 是 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_Init` | 是 |
| timer.set_interval | `Cy_TCPWM_Counter_SetPeriod` | `components/mtb-device-support-pse8xxgp/pdl/drivers/include/cy_tcpwm_counter.h` | 1.000000 | 否 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_SetPeriod` | 是 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_SetPeriod` | 是 |
| timer.start | `mtb_hal_timer_start` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_start` | 是 | `mtb_hal_timer_start` | 是 |
| timer.stop | `mtb_hal_timer_stop` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_stop` | 是 | `mtb_hal_timer_stop` | 是 |


## PSoC E84 EDGI-Talk + Zephyr

SDK 标识：`psoc-e84-edgi-talk-sdk`；OS 后端：`Zephyr`。

| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |
|---|---|---|---:|---|---|:---:|---|:---:|
| clock.disable | `mtb_hal_clock_set_peri_clock_enabled` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 |
| clock.enable | `mtb_hal_clock_set_peri_clock_enabled` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 | `mtb_hal_clock_set_hf_clock_enabled`<br>`mtb_hal_clock_set_peri_clock_enabled` | 是 |
| clock.get_frequency | `mtb_hal_clock_get_peri_src_clock_freq` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_get_hf_clock_freq`<br>`mtb_hal_clock_get_peri_clock_freq`<br>`mtb_hal_clock_get_peri_src_clock_freq` | 是 | `mtb_hal_clock_get_hf_clock_freq`<br>`mtb_hal_clock_get_peri_clock_freq`<br>`mtb_hal_clock_get_peri_src_clock_freq` | 是 |
| clock.initialize | `mtb_hal_clock_set_peri_clock_freq` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_clock.c` | 1.000000 | 否 | `mtb_hal_clock_set_hf_clock_freq`<br>`mtb_hal_clock_set_peri_clock_freq` | 是 | `mtb_hal_clock_set_hf_clock_freq`<br>`mtb_hal_clock_set_peri_clock_freq` | 是 |
| interrupt.initialize | `Cy_SysInt_Init` | `components/mtb-device-support-pse8xxgp/pdl/drivers/source/cy_sysint_v2.c` | 1.000000 | 否 | `Cy_SysInt_Init` | 是 | `Cy_SysInt_Init` | 是 |
| interrupt.register | `Cy_SysInt_SetVector` | `components/mtb-device-support-pse8xxgp/pdl/drivers/source/cy_sysint_v2.c` | 1.000000 | 否 | `Cy_SysInt_SetVector` | 是 | `Cy_SysInt_SetVector` | 是 |
| uart.configure | `mtb_hal_uart_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_set_baud`<br>`mtb_hal_uart_setup` | 是 | `mtb_hal_uart_set_baud`<br>`mtb_hal_uart_setup` | 是 |
| uart.read | `mtb_hal_uart_read` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_read` | 是 | `mtb_hal_uart_read` | 是 |
| uart.write | `mtb_hal_uart_write` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_uart.c` | 1.000000 | 否 | `mtb_hal_uart_write` | 是 | `mtb_hal_uart_write` | 是 |
| gpio.attach_irq | `mtb_hal_gpio_register_callback` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_gpio.c` | 1.000000 | 否 | `mtb_hal_gpio_enable_event`<br>`mtb_hal_gpio_register_callback` | 是 | `mtb_hal_gpio_enable_event`<br>`mtb_hal_gpio_register_callback` | 是 |
| gpio.configure | `mtb_hal_gpio_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_gpio.c` | 1.000000 | 否 | `mtb_hal_gpio_configure`<br>`mtb_hal_gpio_setup` | 是 | `mtb_hal_gpio_configure`<br>`mtb_hal_gpio_setup` | 是 |
| gpio.read | `mtb_hal_gpio_port_read_internal` | `components/mtb-device-support-pse8xxgp/hal/include/mtb_hal_gpio_impl.h` | 1.000000 | 否 | `mtb_hal_gpio_read_internal`<br>`Cy_GPIO_Read`<br>`mtb_hal_gpio_port_read_internal` | 是 | `mtb_hal_gpio_read_internal`<br>`Cy_GPIO_Read`<br>`mtb_hal_gpio_port_read_internal` | 是 |
| gpio.write | `mtb_hal_gpio_port_write_internal` | `components/mtb-device-support-pse8xxgp/hal/include/mtb_hal_gpio_impl.h` | 1.000000 | 否 | `mtb_hal_gpio_toggle_internal`<br>`mtb_hal_gpio_write_internal`<br>`Cy_GPIO_Write`<br>`mtb_hal_gpio_port_write_internal` | 是 | `mtb_hal_gpio_toggle_internal`<br>`mtb_hal_gpio_write_internal`<br>`Cy_GPIO_Write`<br>`mtb_hal_gpio_port_write_internal` | 是 |
| timer.initialize | `mtb_hal_timer_setup` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_Init` | 是 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_Init` | 是 |
| timer.set_interval | `Cy_TCPWM_Counter_SetPeriod` | `components/mtb-device-support-pse8xxgp/pdl/drivers/include/cy_tcpwm_counter.h` | 1.000000 | 否 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_SetPeriod` | 是 | `mtb_hal_timer_setup`<br>`Cy_TCPWM_Counter_SetPeriod` | 是 |
| timer.start | `mtb_hal_timer_start` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_start` | 是 | `mtb_hal_timer_start` | 是 |
| timer.stop | `mtb_hal_timer_stop` | `components/mtb-device-support-pse8xxgp/hal/source/mtb_hal_timer.c` | 1.000000 | 否 | `mtb_hal_timer_stop` | 是 | `mtb_hal_timer_stop` | 是 |
