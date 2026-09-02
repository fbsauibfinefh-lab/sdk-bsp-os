# 操作条件效果切片与多视图排序完整错误报告 v0.3

## 1. 报告口径

本报告使用 H02 和 `multiview-lambdamart-nested` 的跨独立组五折 out-of-fold 预测。每个查询只由未见过该 independence group 的模型预测。板卡外部诊断不并入本报告。

- 有效查询：281
- Top1 正确：183
- Top1 错误：98
- P@1：0.651246
- 完整机器可读记录：`experiments/operation-ranking/results-multiview-lambdamart-h02-v0.3-errors.json`

## 2. 主错误归因

归因是基于当前图证据的可复现诊断规则，不等同于人工确认的唯一根因。

| 主归因 | 错误数 | 占全部错误 |
| --- | ---: | ---: |
| `ranking-model-confusion` | 40 | 40.8% |
| `same-family-operation-confusion` | 26 | 26.5% |
| `truth-path-missing` | 15 | 15.3% |
| `abstraction-level-mismatch` | 6 | 6.1% |
| `effect-strength-confusion` | 6 | 6.1% |
| `composite-entry-overranked` | 3 | 3.1% |
| `internal-role-overranked` | 2 | 2.0% |

## 3. 按操作统计

| 操作 | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `timer.set_interval` | 11/20 | 55.0% |
| `clock.initialize` | 7/13 | 53.8% |
| `clock.disable` | 6/12 | 50.0% |
| `gpio.attach_irq` | 4/8 | 50.0% |
| `gpio.write` | 9/19 | 47.4% |
| `timer.initialize` | 8/17 | 47.1% |
| `clock.enable` | 5/12 | 41.7% |
| `interrupt.initialize` | 2/5 | 40.0% |
| `interrupt.enable` | 5/13 | 38.5% |
| `gpio.configure` | 6/16 | 37.5% |
| `uart.read` | 7/19 | 36.8% |
| `timer.stop` | 7/20 | 35.0% |
| `interrupt.register` | 2/7 | 28.6% |
| `gpio.read` | 5/19 | 26.3% |
| `uart.write` | 5/19 | 26.3% |
| `interrupt.disable` | 3/13 | 23.1% |
| `timer.start` | 4/20 | 20.0% |
| `clock.get_frequency` | 2/12 | 16.7% |
| `uart.configure` | 0/17 | 0.0% |

## 4. 按 SDK 统计

| SDK | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `renesas-fsp` | 11/18 | 61.1% |
| `ti-simplelink-f2` | 9/15 | 60.0% |
| `sifli-hal` | 9/16 | 56.2% |
| `libopencm3-hal` | 7/14 | 50.0% |
| `silabs-emlib` | 7/14 | 50.0% |
| `ti-mspm0-driverlib` | 7/14 | 50.0% |
| `arduino-renesas-core` | 4/9 | 44.4% |
| `nordic-nrfx-4.2.1` | 6/14 | 42.9% |
| `alif-ensemble-dfp` | 4/10 | 40.0% |
| `nuclei-soc-sdk` | 6/16 | 37.5% |
| `wch-ch32v307-stdperiph` | 6/16 | 37.5% |
| `hpmicro-hpm-sdk` | 3/10 | 30.0% |
| `raspberry-pi-pico-sdk-2.2.0` | 5/18 | 27.8% |
| `nuvoton-std-driver` | 3/14 | 21.4% |
| `bouffalo-lhal` | 3/16 | 18.8% |
| `telink-tlsr9-hal` | 2/11 | 18.2% |
| `arm-mbed-hal` | 2/15 | 13.3% |
| `espressif-esp-idf-6.0.1` | 2/16 | 12.5% |
| `nxp-mcuxpresso-sdk-2.16.100` | 2/19 | 10.5% |
| `sony-spresense-sdk` | 0/6 | 0.0% |

## 5. 代表性错误详解

### 5.1 `ti-mspm0-driverlib::clock.enable`

- 系统 Top1：`DL_SYSCTL_enableExternalClock`，分数 0.104741。
- 系统效果路径：`无`。
- H02 真值：`DL_SYSCTL_enableMFCLK`(grade=3, rank=5), `DL_SYSCTL_enableMFPCLK`(grade=3, rank=4), `DL_SYSCTL_enableSYSPLL`(grade=3, rank=2)。
- 主归因：`truth-path-missing`，真值函数没有恢复出足够的目标操作效果路径。
- Top5：`DL_SYSCTL_enableExternalClock`(label=0, score=0.104741), `DL_SYSCTL_enableSYSPLL`(label=3, score=-0.212583), `DL_SYSCTL_enableInterrupt`(label=0, score=-0.235669), `DL_SYSCTL_enableMFPCLK`(label=3, score=-0.5464), `DL_SYSCTL_enableMFCLK`(label=3, score=-0.5464)。

### 5.2 `ti-mspm0-driverlib::uart.write`

- 系统 Top1：`UART_write`，分数 2.809539。
- 系统效果路径：`UART_write`。
- H02 真值：`DL_UART_transmitDataBlocking`(grade=3, rank=15), `DL_UART_fillTXFIFO`(grade=2, rank=10), `DL_UART_transmitData`(grade=2, rank=12)。
- 主归因：`abstraction-level-mismatch`，直接效果层与 H02 指定的可迁移 API 层级不一致。
- Top5：`UART_write`(label=0, score=2.809539), `UART_writeCallback`(label=0, score=1.978157), `UART_writeBuffered`(label=0, score=1.316068), `UART_writeTimeout`(label=0, score=1.261255), `UART_sendBuffer`(label=0, score=1.236467)。

### 5.3 `ti-mspm0-driverlib::uart.read`

- 系统 Top1：`UART_read`，分数 2.198198。
- 系统效果路径：`UART_read`。
- H02 真值：`DL_UART_receiveDataBlocking`(grade=3, rank=14), `DL_UART_drainRXFIFO`(grade=2, rank=11), `DL_UART_receiveData`(grade=2, rank=5)。
- 主归因：`ranking-model-confusion`，现有图特征和 PU 权重不能区分两个相近候选。
- Top5：`UART_read`(label=0, score=2.198198), `UART_readTimeout`(label=0, score=1.643667), `UART_readCancel`(label=0, score=1.414253), `UART_readCallback`(label=0, score=1.063342), `DL_UART_receiveData`(label=2, score=0.976636)。

### 5.4 `ti-mspm0-driverlib::gpio.write`

- 系统 Top1：`GPIO_write`，分数 2.391439。
- 系统效果路径：`GPIO_write`。
- H02 真值：`DL_GPIO_clearPins`(grade=3, rank=12), `DL_GPIO_setPins`(grade=3, rank=6), `DL_GPIO_togglePins`(grade=2, rank=3)。
- 主归因：`effect-strength-confusion`，错误候选的寄存器效果强度压过了接口契约。
- Top5：`GPIO_write`(label=0, score=2.391439), `GPIO_setConfig`(label=0, score=1.442473), `DL_GPIO_togglePins`(label=2, score=0.667354), `HAL_writeGPIOPin`(label=0, score=0.393007), `DL_GPIO_writePins`(label=0, score=0.339918)。

### 5.5 `ti-simplelink-f2::gpio.configure`

- 系统 Top1：`GPIO_init`，分数 3.018774。
- 系统效果路径：`GPIO_init`。
- H02 真值：`GPIO_setConfig`(grade=3, rank=5), `GPIO_setConfigAndMux`(grade=3, rank=18)。
- 主归因：`same-family-operation-confusion`，预测项与真值属于同一 API 家族，但动作或子操作不一致。
- Top5：`GPIO_init`(label=0, score=3.018774), `sid_pal_gpio_pull_mode`(label=0, score=-0.684023), `sid_pal_gpio_output_mode`(label=0, score=-0.779007), `sid_pal_gpio_input_mode`(label=0, score=-0.779007), `GPIO_setConfig`(label=3, score=-1.403185)。

### 5.6 `arm-mbed-hal::clock.initialize`

- 系统 Top1：`CLOCK_InitSysPll`，分数 1.489316。
- 系统效果路径：`CLOCK_InitSysPll -> while -> scard_fifo_write`。
- H02 真值：`SystemInit`(grade=2, rank=13), `mbed_sdk_init`(grade=2, rank=19)。
- 主归因：`composite-entry-overranked`，复合初始化或多能力入口的硬件效果过强。
- Top5：`CLOCK_InitSysPll`(label=0, score=1.489316), `CLOCK_InitArmPll`(label=0, score=1.384931), `CLOCK_InitAudioPll`(label=0, score=1.22871), `CLOCK_InitVideoPll`(label=0, score=1.110457), `CLOCK_InitOsc0`(label=0, score=0.946575)。

### 5.7 `arm-mbed-hal::interrupt.register`

- 系统 Top1：`InterruptHandlerRegister`，分数 2.284429。
- 系统效果路径：`InterruptHandlerRegister -> IRQ_SetHandler`。
- H02 真值：`NVIC_SetVector`(grade=3, rank=2)。
- 主归因：`internal-role-overranked`，内部 handler/callback/dispatch 角色被排到公共接口之前。
- Top5：`InterruptHandlerRegister`(label=0, score=2.284429), `NVIC_SetVector`(label=3, score=1.657978), `whd_bus_irq_register`(label=0, score=-0.142931), `whd_bus_spi_irq_register`(label=0, score=-0.359711), `cyhal_usb_dev_register_irq_callback`(label=0, score=-0.419901)。

## 6. 全部 Top1 错误清单

真值排名来自该折完整唯一符号排序；每一行同时保留系统 Top1、效果路径以及全部 H02 正例。

| # | SDK / 操作 | 系统 Top1 | H02 真值（等级；排名） | 主归因 |
| ---: | --- | --- | --- | --- |
| 1 | `ti-mspm0-driverlib`<br>`clock.enable` | `DL_SYSCTL_enableExternalClock`<br>无路径 | `DL_SYSCTL_enableMFCLK` (3; 5)<br>`DL_SYSCTL_enableMFPCLK` (3; 4)<br>`DL_SYSCTL_enableSYSPLL` (3; 2) | `truth-path-missing` |
| 2 | `ti-mspm0-driverlib`<br>`uart.write` | `UART_write`<br>UART_write | `DL_UART_transmitDataBlocking` (3; 15)<br>`DL_UART_fillTXFIFO` (2; 10)<br>`DL_UART_transmitData` (2; 12) | `abstraction-level-mismatch` |
| 3 | `ti-mspm0-driverlib`<br>`uart.read` | `UART_read`<br>UART_read | `DL_UART_receiveDataBlocking` (3; 14)<br>`DL_UART_drainRXFIFO` (2; 11)<br>`DL_UART_receiveData` (2; 5) | `ranking-model-confusion` |
| 4 | `ti-mspm0-driverlib`<br>`gpio.configure` | `GPIO_init`<br>GPIO_init -> GPIO_setConfig -> GPIO_setConfigAndMux | `DL_GPIO_initDigitalInput` (3; 7)<br>`DL_GPIO_initDigitalOutput` (3; 5) | `truth-path-missing` |
| 5 | `ti-mspm0-driverlib`<br>`gpio.write` | `GPIO_write`<br>GPIO_write | `DL_GPIO_clearPins` (3; 12)<br>`DL_GPIO_setPins` (3; 6)<br>`DL_GPIO_togglePins` (2; 3) | `effect-strength-confusion` |
| 6 | `ti-mspm0-driverlib`<br>`gpio.read` | `GPIO_read`<br>GPIO_read | `DL_GPIO_readPins` (3; 2) | `truth-path-missing` |
| 7 | `ti-mspm0-driverlib`<br>`timer.set_interval` | `DL_Timer_initCompareMode`<br>DL_Timer_initCompareMode | `DL_TimerB_setLoadValue` (3; 11)<br>`DL_Timer_setLoadValue` (3; 7) | `truth-path-missing` |
| 8 | `ti-simplelink-f2`<br>`clock.enable` | `enableExternalClock`<br>enableExternalClock | `Power_setDependency` (2; 3) | `truth-path-missing` |
| 9 | `ti-simplelink-f2`<br>`clock.disable` | `disableLFClockQualifiers`<br>disableLFClockQualifiers | `Power_releaseDependency` (2; 14) | `ranking-model-confusion` |
| 10 | `ti-simplelink-f2`<br>`interrupt.enable` | `__NVIC_EnableIRQ`<br>__NVIC_EnableIRQ | `TZ_NVIC_EnableIRQ_NS` (3; 4) | `ranking-model-confusion` |
| 11 | `ti-simplelink-f2`<br>`interrupt.disable` | `IntDisable`<br>IntDisable | `TZ_NVIC_DisableIRQ_NS` (3; 4) | `effect-strength-confusion` |
| 12 | `ti-simplelink-f2`<br>`gpio.configure` | `GPIO_init`<br>GPIO_init | `GPIO_setConfig` (3; 5)<br>`GPIO_setConfigAndMux` (3; 18) | `same-family-operation-confusion` |
| 13 | `ti-simplelink-f2`<br>`timer.initialize` | `TimerConfigure`<br>TimerConfigure | `GPTimerCC26XX_open` (3; 10) | `effect-strength-confusion` |
| 14 | `ti-simplelink-f2`<br>`timer.start` | `UtilTimer_start`<br>无路径 | `GPTimerCC26XX_start` (3; 13) | `ranking-model-confusion` |
| 15 | `ti-simplelink-f2`<br>`timer.stop` | `UtilTimer_stop`<br>无路径 | `GPTimerCC26XX_stop` (3; 11) | `ranking-model-confusion` |
| 16 | `ti-simplelink-f2`<br>`timer.set_interval` | `Timer_setPeriod`<br>Timer_setPeriod | `GPTimerCC26XX_setLoadValue` (3; 7)<br>`GPTimerCC26XX_setMatchValue` (3; 8) | `abstraction-level-mismatch` |
| 17 | `arm-mbed-hal`<br>`clock.initialize` | `CLOCK_InitSysPll`<br>CLOCK_InitSysPll -> while -> scard_fifo_write | `SystemInit` (2; 13)<br>`mbed_sdk_init` (2; 19) | `composite-entry-overranked` |
| 18 | `arm-mbed-hal`<br>`interrupt.register` | `InterruptHandlerRegister`<br>InterruptHandlerRegister -> IRQ_SetHandler | `NVIC_SetVector` (3; 2) | `internal-role-overranked` |
| 19 | `telink-tlsr9-hal`<br>`gpio.write` | `gpio_set_output`<br>gpio_set_output -> gpio_output_dis | `gpio_set_level` (3; 4)<br>`gpio_set_high_level` (2; 5)<br>`gpio_set_low_level` (2; 6)<br>`gpio_toggle` (2; 3) | `same-family-operation-confusion` |
| 20 | `telink-tlsr9-hal`<br>`timer.set_interval` | `timer_set_cap_tick`<br>无路径 | `stimer_set_irq_capture` (3; 9) | `truth-path-missing` |
| 21 | `renesas-fsp`<br>`clock.initialize` | `bsp_prv_clock_set`<br>bsp_prv_clock_set | `R_CGC_ClocksCfg` (3; 9)<br>`R_CGC_Open` (3; 34) | `ranking-model-confusion` |
| 22 | `renesas-fsp`<br>`clock.enable` | `R_DTC_Enable`<br>无路径 | `R_CGC_ClockStart` (3; 3) | `ranking-model-confusion` |
| 23 | `renesas-fsp`<br>`clock.disable` | `R_DTC_Disable`<br>无路径 | `R_CGC_ClockStop` (3; 2) | `ranking-model-confusion` |
| 24 | `renesas-fsp`<br>`interrupt.initialize` | `d1_initirq_intern`<br>d1_initirq_intern | `R_BSP_IrqCfg` (2; 3) | `truth-path-missing` |
| 25 | `renesas-fsp`<br>`interrupt.enable` | `nvic_interrupt_enable`<br>nvic_interrupt_enable | `R_BSP_IrqCfgEnable` (3; 3)<br>`R_BSP_IrqEnable` (3; 2) | `ranking-model-confusion` |
| 26 | `renesas-fsp`<br>`gpio.read` | `ptxPLAT_GPIO_ReadLevel`<br>ptxPLAT_GPIO_ReadLevel | `R_IOPORT_PinRead` (3; 2) | `ranking-model-confusion` |
| 27 | `renesas-fsp`<br>`gpio.attach_irq` | `ptxPLAT_GPIO_EnableInterrupt`<br>ptxPLAT_GPIO_EnableInterrupt | `R_ICU_ExternalIrqCallbackSet` (3; 16)<br>`R_ICU_ExternalIrqOpen` (3; 9)<br>`R_ICU_ExternalIrqEnable` (1; 10) | `abstraction-level-mismatch` |
| 28 | `renesas-fsp`<br>`timer.initialize` | `rm_gptp_sys_baremetal_timer_setup`<br>rm_gptp_sys_baremetal_timer_setup | `R_AGT_Open` (3; 13)<br>`R_GPT_Open` (3; 4) | `abstraction-level-mismatch` |
| 29 | `renesas-fsp`<br>`timer.start` | `ptxPLAT_TIMER_Start`<br>ptxPLAT_TIMER_Start | `R_AGT_Start` (3; 9)<br>`R_GPT_Start` (3; 8) | `composite-entry-overranked` |
| 30 | `renesas-fsp`<br>`timer.stop` | `gptp_timer_stop`<br>gptp_timer_stop | `R_AGT_Stop` (3; 9)<br>`R_GPT_Stop` (3; 11) | `ranking-model-confusion` |
| 31 | `renesas-fsp`<br>`timer.set_interval` | `gptp_timer_change_period`<br>gptp_timer_change_period | `R_AGT_PeriodSet` (3; 15)<br>`R_GPT_PeriodSet` (3; 21) | `effect-strength-confusion` |
| 32 | `wch-ch32v307-stdperiph`<br>`clock.initialize` | `RCC_APB2PeriphResetCmd`<br>RCC_APB2PeriphResetCmd | `RCC_PLLConfig` (3; 8)<br>`RCC_SYSCLKConfig` (3; 5)<br>`RCC_HSEConfig` (2; 2) | `same-family-operation-confusion` |
| 33 | `wch-ch32v307-stdperiph`<br>`clock.enable` | `RCC_ClockSecuritySystemCmd`<br>RCC_ClockSecuritySystemCmd | `RCC_AHBPeriphClockCmd` (3; 4)<br>`RCC_APB1PeriphClockCmd` (3; 26)<br>`RCC_APB2PeriphClockCmd` (3; 18) | `same-family-operation-confusion` |
| 34 | `wch-ch32v307-stdperiph`<br>`clock.disable` | `RCC_DeInit`<br>RCC_DeInit | `RCC_AHBPeriphClockCmd` (3; 8)<br>`RCC_APB1PeriphClockCmd` (3; 32)<br>`RCC_APB2PeriphClockCmd` (3; 21) | `same-family-operation-confusion` |
| 35 | `wch-ch32v307-stdperiph`<br>`timer.initialize` | `TIM_TimeBaseStructInit`<br>TIM_TimeBaseStructInit | `TIM_TimeBaseInit` (3; 3) | `same-family-operation-confusion` |
| 36 | `wch-ch32v307-stdperiph`<br>`timer.stop` | `TIM_TimeBaseInit`<br>TIM_TimeBaseInit | `TIM_Cmd` (3; 8) | `same-family-operation-confusion` |
| 37 | `wch-ch32v307-stdperiph`<br>`timer.set_interval` | `TIM_TimeBaseInit`<br>TIM_TimeBaseInit | `TIM_SetAutoreload` (3; 43)<br>`TIM_SetCompare1` (2; 58)<br>`TIM_SetCompare2` (2; 60)<br>`TIM_SetCompare3` (2; 59)<br>`TIM_SetCompare4` (2; 61) | `truth-path-missing` |
| 38 | `arduino-renesas-core`<br>`interrupt.enable` | `IRQManager`<br>IRQManager -> IRQManager::addPeripheral | `interrupts` (2; 10) | `truth-path-missing` |
| 39 | `arduino-renesas-core`<br>`interrupt.disable` | `detachIrq2Link`<br>detachIrq2Link | `noInterrupts` (2; 9) | `truth-path-missing` |
| 40 | `arduino-renesas-core`<br>`timer.initialize` | `FspTimer`<br>FspTimer -> FspTimer::begin_pwm -> FspTimer::begin | `FspTimer::begin` (3; 3) | `same-family-operation-confusion` |
| 41 | `arduino-renesas-core`<br>`timer.set_interval` | `FspTimer`<br>FspTimer -> FspTimer::begin_pwm -> FspTimer::begin | `FspTimer::set_period` (3; 2) | `same-family-operation-confusion` |
| 42 | `silabs-emlib`<br>`clock.initialize` | `TIMER_Init`<br>TIMER_Init | `CMU_ClockSelectSet` (3; 2) | `ranking-model-confusion` |
| 43 | `silabs-emlib`<br>`clock.disable` | `CMU_ClockSelectSet`<br>CMU_ClockSelectSet | `CMU_ClockEnable` (3; 68) | `same-family-operation-confusion` |
| 44 | `silabs-emlib`<br>`uart.write` | `USART_Enable`<br>USART_Enable | `USART_Tx` (3; 2)<br>`USART_TxDouble` (2; 10)<br>`USART_TxExt` (2; 6) | `same-family-operation-confusion` |
| 45 | `silabs-emlib`<br>`uart.read` | `USART_BaudrateCalc`<br>USART_BaudrateCalc | `USART_Rx` (3; 3)<br>`USART_RxDataGet` (2; 11)<br>`USART_RxDouble` (2; 6) | `same-family-operation-confusion` |
| 46 | `silabs-emlib`<br>`gpio.configure` | `ACMP_GPIOSetup`<br>ACMP_GPIOSetup | `GPIO_PinModeSet` (3; 6) | `ranking-model-confusion` |
| 47 | `silabs-emlib`<br>`timer.stop` | `TIMER_IntDisable`<br>TIMER_IntDisable | `TIMER_Enable` (3; 7) | `same-family-operation-confusion` |
| 48 | `silabs-emlib`<br>`timer.set_interval` | `TIMER_Init`<br>TIMER_Init | `TIMER_TopSet` (3; 23) | `same-family-operation-confusion` |
| 49 | `nxp-mcuxpresso-sdk-2.16.100`<br>`interrupt.enable` | `EnableGlobalIRQ`<br>EnableGlobalIRQ | `EnableIRQ` (3; 2)<br>`EnableIRQWithPriority` (3; 8)<br>`IRQ_Enable` (3; 3)<br>`IRQ_EnableInterrupt` (3; 4) | `ranking-model-confusion` |
| 50 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.attach_irq` | `SEC_GPIO_INT0_IRQ0_DriverIRQHandler`<br>SEC_GPIO_INT0_IRQ0_DriverIRQHandler -> PINT_PinInterruptClrStatus | `PINT_PinInterruptConfig` (3; 10)<br>`GPIO_PinSetInterruptConfig` (1; 4) | `ranking-model-confusion` |
| 51 | `sifli-hal`<br>`clock.initialize` | `HAL_RCC_Reset_and_Halt_LCPU`<br>HAL_RCC_Reset_and_Halt_LCPU | `HAL_RCC_Init` (3; 2) | `same-family-operation-confusion` |
| 52 | `sifli-hal`<br>`interrupt.enable` | `HAL_MATH_EnableInterrupt`<br>无路径 | `HAL_NVIC_EnableIRQ` (3; 8) | `ranking-model-confusion` |
| 53 | `sifli-hal`<br>`interrupt.disable` | `HAL_MATH_DisableInterrupt`<br>无路径 | `HAL_NVIC_DisableIRQ` (3; 7) | `ranking-model-confusion` |
| 54 | `sifli-hal`<br>`uart.write` | `ll_usart_transmit_data9`<br>无路径 | `HAL_UART_Transmit` (3; 3)<br>`HAL_UART_Transmit_DMA` (2; 7)<br>`HAL_UART_Transmit_IT` (2; 5) | `ranking-model-confusion` |
| 55 | `sifli-hal`<br>`uart.read` | `ll_usart_receive_data9`<br>无路径 | `HAL_UART_Receive` (3; 3)<br>`HAL_UART_Receive_DMA` (2; 7)<br>`HAL_UART_Receive_IT` (2; 6) | `ranking-model-confusion` |
| 56 | `sifli-hal`<br>`gpio.configure` | `ll_gpio_bank_clear_output_mode`<br>ll_gpio_bank_clear_output_mode | `HAL_GPIO_Init` (3; 4) | `ranking-model-confusion` |
| 57 | `sifli-hal`<br>`gpio.write` | `ll_gpio_bank_set_high_pin`<br>ll_gpio_bank_set_high_pin -> ll_gpio_bank_set_high | `HAL_GPIO_WritePin` (3; 6)<br>`HAL_GPIO_TogglePin` (2; 11) | `ranking-model-confusion` |
| 58 | `sifli-hal`<br>`gpio.read` | `ll_gpio_bank_read_output_port`<br>ll_gpio_bank_read_output_port | `HAL_GPIO_ReadPin` (3; 3) | `ranking-model-confusion` |
| 59 | `sifli-hal`<br>`timer.initialize` | `HAL_InitTick`<br>HAL_InitTick | `HAL_LPTIM_Init` (3; 2) | `ranking-model-confusion` |
| 60 | `nuvoton-std-driver`<br>`uart.write` | `UART_WRITE`<br>无路径 | `LPUART_Write` (3; 4)<br>`UART_Write` (3; 2)<br>`UUART_Write` (3; 3) | `same-family-operation-confusion` |
| 61 | `nuvoton-std-driver`<br>`uart.read` | `UART_READ`<br>无路径 | `LPUART_Read` (3; 4)<br>`UART_Read` (3; 2)<br>`UUART_Read` (3; 5) | `same-family-operation-confusion` |
| 62 | `nuvoton-std-driver`<br>`gpio.configure` | `LPGPIO_MODE_INPUT`<br>LPGPIO_MODE_INPUT | `GPIO_SetMode` (3; 8) | `effect-strength-confusion` |
| 63 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.read` | `uart_get_hw`<br>uart_get_hw | `uart_read_blocking` (3; 2)<br>`uart_getc` (2; 3) | `same-family-operation-confusion` |
| 64 | `raspberry-pi-pico-sdk-2.2.0`<br>`gpio.write` | `gpio_set_function`<br>gpio_set_function | `gpio_put` (3; 3)<br>`gpio_clr_mask` (2; 15)<br>`gpio_put_masked` (2; 10)<br>`gpio_set_mask` (2; 12)<br>`gpio_xor_mask` (2; 20) | `same-family-operation-confusion` |
| 65 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.initialize` | `timer_hardware_alarm_set_target`<br>timer_hardware_alarm_set_target | `alarm_pool_create` (2; 8)<br>`alarm_pool_create_with_unused_hardware_alarm` (2; 13)<br>`hardware_alarm_claim` (1; 7)<br>`hardware_alarm_claim_unused` (1; 6) | `abstraction-level-mismatch` |
| 66 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.start` | `aon_timer_start`<br>aon_timer_start -> powman_timer_start | `add_alarm_at` (3; 21)<br>`add_alarm_in_ms` (3; 22)<br>`add_alarm_in_us` (3; 23)<br>`add_repeating_timer_ms` (3; 15)<br>`add_repeating_timer_us` (3; 14)<br>`hardware_alarm_set_target` (3; 3) | `composite-entry-overranked` |
| 67 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.stop` | `aon_timer_stop`<br>aon_timer_stop | `cancel_alarm` (3; 15)<br>`cancel_repeating_timer` (3; 2)<br>`hardware_alarm_cancel` (3; 5) | `abstraction-level-mismatch` |
| 68 | `nordic-nrfx-4.2.1`<br>`clock.enable` | `nrf_clock_int_enable`<br>无路径 | `nrfx_clock_enable` (3; 2)<br>`nrfx_clock_hfclk_start` (2; 4)<br>`nrfx_clock_lfclk_start` (2; 5) | `ranking-model-confusion` |
| 69 | `nordic-nrfx-4.2.1`<br>`clock.disable` | `nrf_clock_int_disable`<br>无路径 | `nrfx_clock_disable` (3; 2)<br>`nrfx_clock_hfclk_stop` (2; 4)<br>`nrfx_clock_lfclk_stop` (2; 3) | `ranking-model-confusion` |
| 70 | `nordic-nrfx-4.2.1`<br>`gpio.write` | `nrf_gpio_pin_write`<br>nrf_gpio_pin_write -> nrf_gpio_pin_clear -> nrf_gpio_pin_port_decode -> nrf_gpio_pin_present_check | `nrfx_gpiote_out_clear` (3; 29)<br>`nrfx_gpiote_out_set` (3; 22)<br>`nrfx_gpiote_out_toggle` (2; 18) | `ranking-model-confusion` |
| 71 | `nordic-nrfx-4.2.1`<br>`gpio.read` | `nrf_gpio_pin_read`<br>nrf_gpio_pin_read | `nrfx_gpiote_in_is_set` (3; 76) | `ranking-model-confusion` |
| 72 | `nordic-nrfx-4.2.1`<br>`gpio.attach_irq` | `nrfx_gpiote_irq_handler`<br>nrfx_gpiote_irq_handler -> irq_handler | `nrfx_gpiote_input_configure` (3; 22)<br>`nrfx_gpiote_trigger_enable` (1; 2) | `same-family-operation-confusion` |
| 73 | `nordic-nrfx-4.2.1`<br>`timer.set_interval` | `nrfx_timer_init`<br>nrfx_timer_init -> timer_configure -> nrfy_timer_int_init | `nrfx_timer_compare` (3; 4)<br>`nrfx_timer_extended_compare` (3; 8) | `same-family-operation-confusion` |
| 74 | `nuclei-soc-sdk`<br>`clock.initialize` | `rcu_rtc_clock_config`<br>rcu_rtc_clock_config | `SystemInit` (3; 2) | `ranking-model-confusion` |
| 75 | `nuclei-soc-sdk`<br>`clock.get_frequency` | `rcu_clock_freq_get`<br>rcu_clock_freq_get | `get_cpu_freq` (3; 2)<br>`SystemCoreClockUpdate` (1; 3) | `ranking-model-confusion` |
| 76 | `nuclei-soc-sdk`<br>`interrupt.initialize` | `PLIC_Interrupt_Init`<br>PLIC_Interrupt_Init | `ECLIC_Init` (3; 5) | `truth-path-missing` |
| 77 | `nuclei-soc-sdk`<br>`interrupt.register` | `PLIC_Register_IRQ`<br>PLIC_Register_IRQ | `Core_Register_IRQ` (3; 11)<br>`Core_Register_IRQ_S` (3; 12)<br>`ECLIC_Register_IRQ` (3; 9)<br>`ECLIC_Register_IRQ_S` (3; 13) | `effect-strength-confusion` |
| 78 | `nuclei-soc-sdk`<br>`uart.read` | `usart_read`<br>usart_read -> usart_data_receive | `uart_read` (3; 2)<br>`usart_data_receive` (3; 3) | `same-family-operation-confusion` |
| 79 | `nuclei-soc-sdk`<br>`timer.set_interval` | `timer_init`<br>timer_init | `timer_autoreload_value_config` (3; 12) | `same-family-operation-confusion` |
| 80 | `hpmicro-hpm-sdk`<br>`gpio.configure` | `qeo_pwm_config_mode`<br>无路径 | `gpio_set_pin_input` (3; 41)<br>`gpio_set_pin_output` (3; 37)<br>`gpio_set_pin_output_with_initial` (3; 19) | `ranking-model-confusion` |
| 81 | `hpmicro-hpm-sdk`<br>`timer.initialize` | `mchtmr_init_counter`<br>无路径 | `gptmr_channel_config` (3; 5) | `ranking-model-confusion` |
| 82 | `hpmicro-hpm-sdk`<br>`timer.set_interval` | `mchtmr_delay`<br>mchtmr_delay | `gptmr_channel_update_count` (3; 8)<br>`gptmr_update_cmp` (3; 9) | `truth-path-missing` |
| 83 | `espressif-esp-idf-6.0.1`<br>`gpio.write` | `gpio_set_direction`<br>gpio_set_direction | `gpio_set_level` (3; 2) | `same-family-operation-confusion` |
| 84 | `espressif-esp-idf-6.0.1`<br>`gpio.attach_irq` | `dedic_gpio_bundle_set_interrupt_and_callback`<br>dedic_gpio_bundle_set_interrupt_and_callback -> dedic_gpio_install_interrupt | `gpio_isr_handler_add` (3; 2)<br>`gpio_intr_enable` (1; 3)<br>`gpio_set_intr_type` (1; 4) | `internal-role-overranked` |
| 85 | `bouffalo-lhal`<br>`clock.get_frequency` | `Clock_System_Clock_Get`<br>Clock_System_Clock_Get -> Clock_MCU_Root_Clk_Mux_Output | `bflb_clk_get_peripheral_clock` (3; 9)<br>`bflb_clk_get_system_clock` (3; 7) | `ranking-model-confusion` |
| 86 | `bouffalo-lhal`<br>`gpio.write` | `GLB_GPIO_Write`<br>GLB_GPIO_Write | `bflb_gpio_reset` (3; 6)<br>`bflb_gpio_set` (3; 2)<br>`bflb_gpio_pin0_31_output` (2; 9)<br>`bflb_gpio_pin0_31_reset` (2; 19)<br>`bflb_gpio_pin0_31_set` (2; 7)<br>`bflb_gpio_pin32_63_output` (2; 10)<br>`bflb_gpio_pin32_63_reset` (2; 21)<br>`bflb_gpio_pin32_63_set` (2; 11) | `ranking-model-confusion` |
| 87 | `bouffalo-lhal`<br>`timer.set_interval` | `bflb_mtimer_config`<br>bflb_mtimer_config -> csi_coret_config_use | `bflb_timer_set_compvalue` (3; 2)<br>`bflb_timer_set_preloadvalue` (3; 3) | `ranking-model-confusion` |
| 88 | `libopencm3-hal`<br>`clock.initialize` | `rcc_configure_pll`<br>rcc_configure_pll | `rcc_clock_setup_hse` (3; 4)<br>`rcc_clock_setup_hse_3v3` (3; 5)<br>`rcc_clock_setup_hsi` (3; 3)<br>`rcc_clock_setup_hsi48` (3; 13)<br>`rcc_clock_setup_cfgr` (1; 10)<br>`rcc_clock_setup_domain1` (1; 14)<br>`rcc_clock_setup_domain2` (1; 15)<br>`rcc_clock_setup_domain3` (1; 12) | `same-family-operation-confusion` |
| 89 | `libopencm3-hal`<br>`uart.write` | `uart_send`<br>uart_send | `usart_send_blocking` (3; 6)<br>`usart_send` (2; 4) | `ranking-model-confusion` |
| 90 | `libopencm3-hal`<br>`uart.read` | `uart_read`<br>无路径 | `usart_recv_blocking` (3; 14)<br>`usart_recv` (2; 4) | `ranking-model-confusion` |
| 91 | `libopencm3-hal`<br>`gpio.write` | `gpio_write`<br>gpio_write | `gpio_clear` (3; 5)<br>`gpio_set` (3; 3)<br>`gpio_toggle` (2; 4) | `truth-path-missing` |
| 92 | `libopencm3-hal`<br>`gpio.read` | `gpio_read`<br>gpio_read | `gpio_get` (3; 2) | `same-family-operation-confusion` |
| 93 | `libopencm3-hal`<br>`timer.start` | `timer_enable`<br>无路径 | `timer_enable_counter` (3; 3) | `truth-path-missing` |
| 94 | `libopencm3-hal`<br>`timer.stop` | `timer_stop`<br>timer_stop | `timer_disable_counter` (3; 2) | `truth-path-missing` |
| 95 | `alif-ensemble-dfp`<br>`clock.disable` | `canfd_clock_disable`<br>canfd_clock_disable | `SERVICES_clocks_enable_clock` (3; 64) | `ranking-model-confusion` |
| 96 | `alif-ensemble-dfp`<br>`gpio.write` | `pinconf_set`<br>pinconf_set | `gpio_bit_man_set_value_high` (2; 10)<br>`gpio_bit_man_set_value_low` (2; 8)<br>`gpio_set_value_high` (2; 4)<br>`gpio_set_value_low` (2; 5)<br>`GPIO_SetValue` (1; 2) | `ranking-model-confusion` |
| 97 | `alif-ensemble-dfp`<br>`timer.initialize` | `chbsp_periodic_timer_init`<br>无路径 | `utimer_config_mode` (2; 2) | `ranking-model-confusion` |
| 98 | `alif-ensemble-dfp`<br>`timer.stop` | `lptimer_disable_counter`<br>lptimer_disable_counter | `utimer_counter_stop` (3; 2) | `ranking-model-confusion` |
