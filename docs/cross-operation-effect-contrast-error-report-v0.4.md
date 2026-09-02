# 跨操作效果对比排序完整错误报告 v0.4

## 1. 报告口径

本报告使用 H02 和 `multiview-lambdamart-nested` 的跨独立组五折 out-of-fold 预测。每个查询只由未见过该 independence group 的模型预测。板卡外部诊断不并入本报告。

- 有效查询：281
- Top1 正确：180
- Top1 错误：101
- P@1：0.640569
- 完整机器可读记录：`experiments/operation-ranking/results-cross-operation-effect-contrast-h02-v0.4-errors.json`

## 2. 主错误归因

归因是基于当前图证据的可复现诊断规则，不等同于人工确认的唯一根因。

| 主归因 | 错误数 | 占全部错误 |
| --- | ---: | ---: |
| `ranking-model-confusion` | 40 | 39.6% |
| `same-family-operation-confusion` | 27 | 26.7% |
| `truth-path-missing` | 16 | 15.8% |
| `abstraction-level-mismatch` | 6 | 5.9% |
| `effect-strength-confusion` | 6 | 5.9% |
| `composite-entry-overranked` | 5 | 5.0% |
| `internal-role-overranked` | 1 | 1.0% |

## 3. 按操作统计

| 操作 | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `clock.disable` | 7/12 | 58.3% |
| `timer.set_interval` | 11/20 | 55.0% |
| `clock.initialize` | 7/13 | 53.8% |
| `gpio.write` | 9/19 | 47.4% |
| `timer.initialize` | 8/17 | 47.1% |
| `interrupt.initialize` | 2/5 | 40.0% |
| `timer.stop` | 8/20 | 40.0% |
| `interrupt.enable` | 5/13 | 38.5% |
| `gpio.attach_irq` | 3/8 | 37.5% |
| `gpio.configure` | 6/16 | 37.5% |
| `uart.read` | 7/19 | 36.8% |
| `clock.enable` | 4/12 | 33.3% |
| `gpio.read` | 6/19 | 31.6% |
| `interrupt.register` | 2/7 | 28.6% |
| `uart.write` | 5/19 | 26.3% |
| `clock.get_frequency` | 3/12 | 25.0% |
| `interrupt.disable` | 3/13 | 23.1% |
| `timer.start` | 4/20 | 20.0% |
| `uart.configure` | 1/17 | 5.9% |

## 4. 按 SDK 统计

| SDK | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `sifli-hal` | 11/16 | 68.8% |
| `renesas-fsp` | 11/18 | 61.1% |
| `ti-simplelink-f2` | 9/15 | 60.0% |
| `libopencm3-hal` | 8/14 | 57.1% |
| `silabs-emlib` | 7/14 | 50.0% |
| `ti-mspm0-driverlib` | 7/14 | 50.0% |
| `arduino-renesas-core` | 4/9 | 44.4% |
| `alif-ensemble-dfp` | 4/10 | 40.0% |
| `nuclei-soc-sdk` | 6/16 | 37.5% |
| `nordic-nrfx-4.2.1` | 5/14 | 35.7% |
| `wch-ch32v307-stdperiph` | 5/16 | 31.2% |
| `hpmicro-hpm-sdk` | 3/10 | 30.0% |
| `nuvoton-std-driver` | 4/14 | 28.6% |
| `raspberry-pi-pico-sdk-2.2.0` | 5/18 | 27.8% |
| `telink-tlsr9-hal` | 3/11 | 27.3% |
| `bouffalo-lhal` | 3/16 | 18.8% |
| `nxp-mcuxpresso-sdk-2.16.100` | 3/19 | 15.8% |
| `arm-mbed-hal` | 2/15 | 13.3% |
| `espressif-esp-idf-6.0.1` | 1/16 | 6.2% |
| `sony-spresense-sdk` | 0/6 | 0.0% |

## 5. 代表性错误详解

### 5.1 `ti-mspm0-driverlib::clock.enable`

- 系统 Top1：`DL_SYSCTL_enableExternalClock`，分数 0.177643。
- 系统效果路径：`无`。
- H02 真值：`DL_SYSCTL_enableMFCLK`(grade=3, rank=6), `DL_SYSCTL_enableMFPCLK`(grade=3, rank=5), `DL_SYSCTL_enableSYSPLL`(grade=3, rank=3)。
- 主归因：`truth-path-missing`，真值函数没有恢复出足够的目标操作效果路径。
- Top5：`DL_SYSCTL_enableExternalClock`(label=0, score=0.177643), `DL_SYSCTL_enableInterrupt`(label=0, score=-0.254503), `DL_SYSCTL_enableSYSPLL`(label=3, score=-0.391072), `DL_SYSCTL_enableSYSOSCFCL`(label=0, score=-0.502084), `DL_SYSCTL_enableMFPCLK`(label=3, score=-0.649443)。

### 5.2 `ti-mspm0-driverlib::uart.write`

- 系统 Top1：`UART_write`，分数 2.825074。
- 系统效果路径：`UART_write`。
- H02 真值：`DL_UART_transmitDataBlocking`(grade=3, rank=13), `DL_UART_fillTXFIFO`(grade=2, rank=10), `DL_UART_transmitData`(grade=2, rank=11)。
- 主归因：`abstraction-level-mismatch`，直接效果层与 H02 指定的可迁移 API 层级不一致。
- Top5：`UART_write`(label=0, score=2.825074), `UART_writeCallback`(label=0, score=2.187154), `UART_writeBuffered`(label=0, score=1.575168), `UART_writeTimeout`(label=0, score=1.394368), `UART_sendCommand`(label=0, score=1.16965)。

### 5.3 `ti-mspm0-driverlib::uart.read`

- 系统 Top1：`UART_read`，分数 2.400273。
- 系统效果路径：`UART_read`。
- H02 真值：`DL_UART_receiveDataBlocking`(grade=3, rank=14), `DL_UART_drainRXFIFO`(grade=2, rank=9), `DL_UART_receiveData`(grade=2, rank=6)。
- 主归因：`ranking-model-confusion`，现有图特征和 PU 权重不能区分两个相近候选。
- Top5：`UART_read`(label=0, score=2.400273), `UART_readTimeout`(label=0, score=1.732107), `UART_readCancel`(label=0, score=1.366235), `UART_readCallback`(label=0, score=1.200479), `UART_readBuffered`(label=0, score=1.158074)。

### 5.4 `ti-mspm0-driverlib::gpio.write`

- 系统 Top1：`GPIO_write`，分数 2.496775。
- 系统效果路径：`GPIO_write`。
- H02 真值：`DL_GPIO_clearPins`(grade=3, rank=10), `DL_GPIO_setPins`(grade=3, rank=5), `DL_GPIO_togglePins`(grade=2, rank=4)。
- 主归因：`effect-strength-confusion`，错误候选的寄存器效果强度压过了接口契约。
- Top5：`GPIO_write`(label=0, score=2.496775), `GPIO_setConfig`(label=0, score=1.345738), `HAL_writeGPIOPin`(label=0, score=0.58944), `DL_GPIO_togglePins`(label=2, score=0.566705), `DL_GPIO_setPins`(label=3, score=0.340206)。

### 5.5 `ti-simplelink-f2::gpio.configure`

- 系统 Top1：`GPIO_init`，分数 3.050405。
- 系统效果路径：`GPIO_init`。
- H02 真值：`GPIO_setConfig`(grade=3, rank=5), `GPIO_setConfigAndMux`(grade=3, rank=19)。
- 主归因：`same-family-operation-confusion`，预测项与真值属于同一 API 家族，但动作或子操作不一致。
- Top5：`GPIO_init`(label=0, score=3.050405), `sid_pal_gpio_pull_mode`(label=0, score=-0.451619), `sid_pal_gpio_output_mode`(label=0, score=-0.583153), `sid_pal_gpio_input_mode`(label=0, score=-0.583153), `GPIO_setConfig`(label=3, score=-1.205719)。

### 5.6 `arm-mbed-hal::clock.initialize`

- 系统 Top1：`CLOCK_InitSysPll`，分数 1.485899。
- 系统效果路径：`CLOCK_InitSysPll -> while -> scard_fifo_write`。
- H02 真值：`SystemInit`(grade=2, rank=13), `mbed_sdk_init`(grade=2, rank=14)。
- 主归因：`composite-entry-overranked`，复合初始化或多能力入口的硬件效果过强。
- Top5：`CLOCK_InitSysPll`(label=0, score=1.485899), `CLOCK_InitArmPll`(label=0, score=1.195802), `CLOCK_InitAudioPll`(label=0, score=1.149681), `CLOCK_InitVideoPll`(label=0, score=1.115072), `CLOCK_InitOsc0`(label=0, score=0.680044)。

### 5.7 `arm-mbed-hal::interrupt.register`

- 系统 Top1：`InterruptHandlerRegister`，分数 2.567475。
- 系统效果路径：`InterruptHandlerRegister -> IRQ_SetHandler`。
- H02 真值：`NVIC_SetVector`(grade=3, rank=2)。
- 主归因：`internal-role-overranked`，内部 handler/callback/dispatch 角色被排到公共接口之前。
- Top5：`InterruptHandlerRegister`(label=0, score=2.567475), `NVIC_SetVector`(label=3, score=1.629116), `whd_bus_irq_register`(label=0, score=-0.183351), `cyhal_usb_dev_register_irq_callback`(label=0, score=-0.321986), `whd_bus_spi_irq_register`(label=0, score=-0.362845)。

## 6. 全部 Top1 错误清单

真值排名来自该折完整唯一符号排序；每一行同时保留系统 Top1、效果路径以及全部 H02 正例。

| # | SDK / 操作 | 系统 Top1 | H02 真值（等级；排名） | 主归因 |
| ---: | --- | --- | --- | --- |
| 1 | `ti-mspm0-driverlib`<br>`clock.enable` | `DL_SYSCTL_enableExternalClock`<br>无路径 | `DL_SYSCTL_enableMFCLK` (3; 6)<br>`DL_SYSCTL_enableMFPCLK` (3; 5)<br>`DL_SYSCTL_enableSYSPLL` (3; 3) | `truth-path-missing` |
| 2 | `ti-mspm0-driverlib`<br>`uart.write` | `UART_write`<br>UART_write | `DL_UART_transmitDataBlocking` (3; 13)<br>`DL_UART_fillTXFIFO` (2; 10)<br>`DL_UART_transmitData` (2; 11) | `abstraction-level-mismatch` |
| 3 | `ti-mspm0-driverlib`<br>`uart.read` | `UART_read`<br>UART_read | `DL_UART_receiveDataBlocking` (3; 14)<br>`DL_UART_drainRXFIFO` (2; 9)<br>`DL_UART_receiveData` (2; 6) | `ranking-model-confusion` |
| 4 | `ti-mspm0-driverlib`<br>`gpio.configure` | `GPIO_init`<br>GPIO_init -> GPIO_setConfig -> GPIO_setConfigAndMux | `DL_GPIO_initDigitalInput` (3; 7)<br>`DL_GPIO_initDigitalOutput` (3; 5) | `truth-path-missing` |
| 5 | `ti-mspm0-driverlib`<br>`gpio.write` | `GPIO_write`<br>GPIO_write | `DL_GPIO_clearPins` (3; 10)<br>`DL_GPIO_setPins` (3; 5)<br>`DL_GPIO_togglePins` (2; 4) | `effect-strength-confusion` |
| 6 | `ti-mspm0-driverlib`<br>`gpio.read` | `GPIO_read`<br>GPIO_read | `DL_GPIO_readPins` (3; 2) | `truth-path-missing` |
| 7 | `ti-mspm0-driverlib`<br>`timer.set_interval` | `DL_Timer_initCompareMode`<br>DL_Timer_initCompareMode | `DL_TimerB_setLoadValue` (3; 10)<br>`DL_Timer_setLoadValue` (3; 8) | `truth-path-missing` |
| 8 | `ti-simplelink-f2`<br>`clock.enable` | `enableExternalClock`<br>enableExternalClock | `Power_setDependency` (2; 2) | `truth-path-missing` |
| 9 | `ti-simplelink-f2`<br>`clock.disable` | `disableLFClockQualifiers`<br>disableLFClockQualifiers | `Power_releaseDependency` (2; 13) | `ranking-model-confusion` |
| 10 | `ti-simplelink-f2`<br>`interrupt.enable` | `__NVIC_EnableIRQ`<br>__NVIC_EnableIRQ | `TZ_NVIC_EnableIRQ_NS` (3; 4) | `ranking-model-confusion` |
| 11 | `ti-simplelink-f2`<br>`interrupt.disable` | `IntDisable`<br>IntDisable | `TZ_NVIC_DisableIRQ_NS` (3; 4) | `effect-strength-confusion` |
| 12 | `ti-simplelink-f2`<br>`gpio.configure` | `GPIO_init`<br>GPIO_init | `GPIO_setConfig` (3; 5)<br>`GPIO_setConfigAndMux` (3; 19) | `same-family-operation-confusion` |
| 13 | `ti-simplelink-f2`<br>`timer.initialize` | `TimerConfigure`<br>TimerConfigure | `GPTimerCC26XX_open` (3; 10) | `effect-strength-confusion` |
| 14 | `ti-simplelink-f2`<br>`timer.start` | `UtilTimer_start`<br>无路径 | `GPTimerCC26XX_start` (3; 13) | `ranking-model-confusion` |
| 15 | `ti-simplelink-f2`<br>`timer.stop` | `UtilTimer_stop`<br>无路径 | `GPTimerCC26XX_stop` (3; 11) | `ranking-model-confusion` |
| 16 | `ti-simplelink-f2`<br>`timer.set_interval` | `Timer_setPeriod`<br>Timer_setPeriod | `GPTimerCC26XX_setLoadValue` (3; 6)<br>`GPTimerCC26XX_setMatchValue` (3; 8) | `abstraction-level-mismatch` |
| 17 | `arm-mbed-hal`<br>`clock.initialize` | `CLOCK_InitSysPll`<br>CLOCK_InitSysPll -> while -> scard_fifo_write | `SystemInit` (2; 13)<br>`mbed_sdk_init` (2; 14) | `composite-entry-overranked` |
| 18 | `arm-mbed-hal`<br>`interrupt.register` | `InterruptHandlerRegister`<br>InterruptHandlerRegister -> IRQ_SetHandler | `NVIC_SetVector` (3; 2) | `internal-role-overranked` |
| 19 | `telink-tlsr9-hal`<br>`gpio.write` | `gpio_set_output`<br>gpio_set_output -> gpio_output_dis | `gpio_set_level` (3; 4)<br>`gpio_set_high_level` (2; 5)<br>`gpio_set_low_level` (2; 6)<br>`gpio_toggle` (2; 3) | `same-family-operation-confusion` |
| 20 | `telink-tlsr9-hal`<br>`gpio.read` | `gpio_read_all`<br>无路径 | `gpio_get_level` (3; 2)<br>`gpio_get_level_all` (2; 4) | `same-family-operation-confusion` |
| 21 | `telink-tlsr9-hal`<br>`timer.set_interval` | `timer_set_cap_tick`<br>无路径 | `stimer_set_irq_capture` (3; 9) | `truth-path-missing` |
| 22 | `renesas-fsp`<br>`clock.initialize` | `bsp_prv_clock_set`<br>bsp_prv_clock_set | `R_CGC_ClocksCfg` (3; 7)<br>`R_CGC_Open` (3; 31) | `ranking-model-confusion` |
| 23 | `renesas-fsp`<br>`clock.enable` | `R_I3C_Enable`<br>R_I3C_Enable | `R_CGC_ClockStart` (3; 3) | `composite-entry-overranked` |
| 24 | `renesas-fsp`<br>`clock.disable` | `R_DTC_Disable`<br>无路径 | `R_CGC_ClockStop` (3; 2) | `ranking-model-confusion` |
| 25 | `renesas-fsp`<br>`interrupt.initialize` | `d1_initirq_intern`<br>d1_initirq_intern | `R_BSP_IrqCfg` (2; 4) | `truth-path-missing` |
| 26 | `renesas-fsp`<br>`interrupt.enable` | `nvic_interrupt_enable`<br>nvic_interrupt_enable | `R_BSP_IrqCfgEnable` (3; 3)<br>`R_BSP_IrqEnable` (3; 2) | `ranking-model-confusion` |
| 27 | `renesas-fsp`<br>`gpio.read` | `ptxPLAT_GPIO_ReadLevel`<br>ptxPLAT_GPIO_ReadLevel | `R_IOPORT_PinRead` (3; 3) | `ranking-model-confusion` |
| 28 | `renesas-fsp`<br>`gpio.attach_irq` | `ptxPLAT_GPIO_EnableInterrupt`<br>ptxPLAT_GPIO_EnableInterrupt | `R_ICU_ExternalIrqCallbackSet` (3; 15)<br>`R_ICU_ExternalIrqOpen` (3; 7)<br>`R_ICU_ExternalIrqEnable` (1; 8) | `abstraction-level-mismatch` |
| 29 | `renesas-fsp`<br>`timer.initialize` | `rm_gptp_sys_baremetal_timer_setup`<br>rm_gptp_sys_baremetal_timer_setup | `R_AGT_Open` (3; 13)<br>`R_GPT_Open` (3; 4) | `abstraction-level-mismatch` |
| 30 | `renesas-fsp`<br>`timer.start` | `ptxPLAT_TIMER_Start`<br>ptxPLAT_TIMER_Start | `R_AGT_Start` (3; 11)<br>`R_GPT_Start` (3; 5) | `composite-entry-overranked` |
| 31 | `renesas-fsp`<br>`timer.stop` | `gptp_timer_stop`<br>gptp_timer_stop | `R_AGT_Stop` (3; 9)<br>`R_GPT_Stop` (3; 10) | `ranking-model-confusion` |
| 32 | `renesas-fsp`<br>`timer.set_interval` | `gptp_timer_change_period`<br>gptp_timer_change_period | `R_AGT_PeriodSet` (3; 14)<br>`R_GPT_PeriodSet` (3; 20) | `effect-strength-confusion` |
| 33 | `wch-ch32v307-stdperiph`<br>`clock.initialize` | `RCC_APB2PeriphResetCmd`<br>RCC_APB2PeriphResetCmd | `RCC_PLLConfig` (3; 7)<br>`RCC_SYSCLKConfig` (3; 5)<br>`RCC_HSEConfig` (2; 2) | `same-family-operation-confusion` |
| 34 | `wch-ch32v307-stdperiph`<br>`clock.enable` | `RCC_ClockSecuritySystemCmd`<br>RCC_ClockSecuritySystemCmd | `RCC_AHBPeriphClockCmd` (3; 2)<br>`RCC_APB1PeriphClockCmd` (3; 22)<br>`RCC_APB2PeriphClockCmd` (3; 16) | `same-family-operation-confusion` |
| 35 | `wch-ch32v307-stdperiph`<br>`clock.disable` | `RCC_DeInit`<br>RCC_DeInit | `RCC_AHBPeriphClockCmd` (3; 9)<br>`RCC_APB1PeriphClockCmd` (3; 21)<br>`RCC_APB2PeriphClockCmd` (3; 20) | `same-family-operation-confusion` |
| 36 | `wch-ch32v307-stdperiph`<br>`timer.stop` | `TIM_TimeBaseInit`<br>TIM_TimeBaseInit | `TIM_Cmd` (3; 3) | `same-family-operation-confusion` |
| 37 | `wch-ch32v307-stdperiph`<br>`timer.set_interval` | `TIM_TimeBaseInit`<br>TIM_TimeBaseInit | `TIM_SetAutoreload` (3; 49)<br>`TIM_SetCompare1` (2; 59)<br>`TIM_SetCompare2` (2; 61)<br>`TIM_SetCompare3` (2; 60)<br>`TIM_SetCompare4` (2; 63) | `truth-path-missing` |
| 38 | `arduino-renesas-core`<br>`interrupt.enable` | `IRQManager`<br>IRQManager -> IRQManager::addPeripheral | `interrupts` (2; 8) | `truth-path-missing` |
| 39 | `arduino-renesas-core`<br>`interrupt.disable` | `detachIrq2Link`<br>detachIrq2Link | `noInterrupts` (2; 9) | `truth-path-missing` |
| 40 | `arduino-renesas-core`<br>`timer.initialize` | `FspTimer`<br>FspTimer -> FspTimer::begin_pwm -> FspTimer::begin | `FspTimer::begin` (3; 2) | `same-family-operation-confusion` |
| 41 | `arduino-renesas-core`<br>`timer.set_interval` | `FspTimer`<br>FspTimer -> FspTimer::begin_pwm -> FspTimer::begin | `FspTimer::set_period` (3; 2) | `same-family-operation-confusion` |
| 42 | `silabs-emlib`<br>`clock.initialize` | `TIMER_Init`<br>TIMER_Init | `CMU_ClockSelectSet` (3; 2) | `ranking-model-confusion` |
| 43 | `silabs-emlib`<br>`clock.disable` | `CMU_ClockSelectSet`<br>CMU_ClockSelectSet | `CMU_ClockEnable` (3; 70) | `same-family-operation-confusion` |
| 44 | `silabs-emlib`<br>`uart.write` | `USART_Enable`<br>USART_Enable | `USART_Tx` (3; 2)<br>`USART_TxDouble` (2; 9)<br>`USART_TxExt` (2; 5) | `same-family-operation-confusion` |
| 45 | `silabs-emlib`<br>`uart.read` | `USART_BaudrateCalc`<br>USART_BaudrateCalc | `USART_Rx` (3; 3)<br>`USART_RxDataGet` (2; 11)<br>`USART_RxDouble` (2; 7) | `same-family-operation-confusion` |
| 46 | `silabs-emlib`<br>`gpio.configure` | `ACMP_GPIOSetup`<br>ACMP_GPIOSetup | `GPIO_PinModeSet` (3; 5) | `ranking-model-confusion` |
| 47 | `silabs-emlib`<br>`timer.stop` | `TIMER_IntDisable`<br>TIMER_IntDisable | `TIMER_Enable` (3; 6) | `same-family-operation-confusion` |
| 48 | `silabs-emlib`<br>`timer.set_interval` | `TIMER_Init`<br>TIMER_Init | `TIMER_TopSet` (3; 20) | `same-family-operation-confusion` |
| 49 | `nxp-mcuxpresso-sdk-2.16.100`<br>`interrupt.enable` | `EnableGlobalIRQ`<br>EnableGlobalIRQ | `EnableIRQ` (3; 4)<br>`EnableIRQWithPriority` (3; 8)<br>`IRQ_Enable` (3; 3)<br>`IRQ_EnableInterrupt` (3; 2) | `ranking-model-confusion` |
| 50 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.attach_irq` | `SEC_GPIO_INT0_IRQ0_DriverIRQHandler`<br>SEC_GPIO_INT0_IRQ0_DriverIRQHandler -> PINT_PinInterruptClrStatus | `PINT_PinInterruptConfig` (3; 13)<br>`GPIO_PinSetInterruptConfig` (1; 4) | `ranking-model-confusion` |
| 51 | `nxp-mcuxpresso-sdk-2.16.100`<br>`timer.stop` | `NETC_TimerStopAlarm`<br>NETC_TimerStopAlarm | `CTIMER_StopTimer` (3; 2)<br>`FTM_StopTimer` (2; 18)<br>`LPTMR_StopTimer` (2; 4)<br>`QTMR_StopTimer` (2; 6)<br>`TPM_StopTimer` (2; 11) | `ranking-model-confusion` |
| 52 | `sifli-hal`<br>`clock.initialize` | `HAL_RCC_Reset_and_Halt_LCPU`<br>HAL_RCC_Reset_and_Halt_LCPU | `HAL_RCC_Init` (3; 2) | `same-family-operation-confusion` |
| 53 | `sifli-hal`<br>`interrupt.enable` | `HAL_MATH_EnableInterrupt`<br>无路径 | `HAL_NVIC_EnableIRQ` (3; 6) | `ranking-model-confusion` |
| 54 | `sifli-hal`<br>`interrupt.disable` | `HAL_MATH_DisableInterrupt`<br>无路径 | `HAL_NVIC_DisableIRQ` (3; 7) | `ranking-model-confusion` |
| 55 | `sifli-hal`<br>`uart.configure` | `HAL_UART_MspInit`<br>无路径 | `HAL_UART_Init` (3; 2) | `same-family-operation-confusion` |
| 56 | `sifli-hal`<br>`uart.write` | `ll_usart_clear_flag_cts`<br>ll_usart_clear_flag_cts | `HAL_UART_Transmit` (3; 2)<br>`HAL_UART_Transmit_DMA` (2; 4)<br>`HAL_UART_Transmit_IT` (2; 3) | `ranking-model-confusion` |
| 57 | `sifli-hal`<br>`uart.read` | `ll_usart_receive_data9`<br>无路径 | `HAL_UART_Receive` (3; 3)<br>`HAL_UART_Receive_DMA` (2; 6)<br>`HAL_UART_Receive_IT` (2; 5) | `ranking-model-confusion` |
| 58 | `sifli-hal`<br>`gpio.configure` | `ll_gpio_bank_clear_output_mode`<br>ll_gpio_bank_clear_output_mode | `HAL_GPIO_Init` (3; 4) | `ranking-model-confusion` |
| 59 | `sifli-hal`<br>`gpio.write` | `ll_gpio_bank_set_high_pin`<br>ll_gpio_bank_set_high_pin -> ll_gpio_bank_set_high | `HAL_GPIO_WritePin` (3; 10)<br>`HAL_GPIO_TogglePin` (2; 11) | `ranking-model-confusion` |
| 60 | `sifli-hal`<br>`gpio.read` | `ll_gpio_bank_read_output_port`<br>ll_gpio_bank_read_output_port | `HAL_GPIO_ReadPin` (3; 3) | `ranking-model-confusion` |
| 61 | `sifli-hal`<br>`timer.initialize` | `HAL_InitTick`<br>HAL_InitTick | `HAL_LPTIM_Init` (3; 3) | `ranking-model-confusion` |
| 62 | `sifli-hal`<br>`timer.set_interval` | `HAL_RTC_SetWakeUpTimer`<br>HAL_RTC_SetWakeUpTimer | `HAL_LPTIM_PWM_Set_Period` (3; 4) | `composite-entry-overranked` |
| 63 | `nuvoton-std-driver`<br>`clock.get_frequency` | `CLK_GetHCLK0Freq`<br>CLK_GetHCLK0Freq -> CLK_SystemClockUpdate | `CLK_GetCPUFreq` (3; 18)<br>`CLK_GetHCLKFreq` (3; 7)<br>`CLK_GetPCLK0Freq` (3; 4)<br>`CLK_GetPCLK1Freq` (3; 3)<br>`CLK_GetPCLK2Freq` (3; 11)<br>`CLK_GetPCLK3Freq` (3; 10)<br>`CLK_GetPCLK4Freq` (3; 8)<br>`CLK_GetPCLK5Freq` (3; 13) | `same-family-operation-confusion` |
| 64 | `nuvoton-std-driver`<br>`uart.write` | `UART_WRITE`<br>无路径 | `LPUART_Write` (3; 4)<br>`UART_Write` (3; 2)<br>`UUART_Write` (3; 3) | `same-family-operation-confusion` |
| 65 | `nuvoton-std-driver`<br>`uart.read` | `UART_READ`<br>无路径 | `LPUART_Read` (3; 4)<br>`UART_Read` (3; 2)<br>`UUART_Read` (3; 6) | `same-family-operation-confusion` |
| 66 | `nuvoton-std-driver`<br>`gpio.configure` | `LPGPIO_MODE_INPUT`<br>LPGPIO_MODE_INPUT | `GPIO_SetMode` (3; 5) | `effect-strength-confusion` |
| 67 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.read` | `uart_get_hw`<br>uart_get_hw | `uart_read_blocking` (3; 2)<br>`uart_getc` (2; 4) | `same-family-operation-confusion` |
| 68 | `raspberry-pi-pico-sdk-2.2.0`<br>`gpio.write` | `gpio_set_function`<br>gpio_set_function | `gpio_put` (3; 3)<br>`gpio_clr_mask` (2; 13)<br>`gpio_put_masked` (2; 11)<br>`gpio_set_mask` (2; 9)<br>`gpio_xor_mask` (2; 18) | `same-family-operation-confusion` |
| 69 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.initialize` | `timer_hardware_alarm_set_target`<br>timer_hardware_alarm_set_target | `alarm_pool_create` (2; 8)<br>`alarm_pool_create_with_unused_hardware_alarm` (2; 13)<br>`hardware_alarm_claim` (1; 6)<br>`hardware_alarm_claim_unused` (1; 4) | `abstraction-level-mismatch` |
| 70 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.start` | `aon_timer_start`<br>aon_timer_start -> powman_timer_start | `add_alarm_at` (3; 21)<br>`add_alarm_in_ms` (3; 22)<br>`add_alarm_in_us` (3; 23)<br>`add_repeating_timer_ms` (3; 16)<br>`add_repeating_timer_us` (3; 15)<br>`hardware_alarm_set_target` (3; 3) | `composite-entry-overranked` |
| 71 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.stop` | `aon_timer_stop`<br>aon_timer_stop | `cancel_alarm` (3; 12)<br>`cancel_repeating_timer` (3; 2)<br>`hardware_alarm_cancel` (3; 5) | `abstraction-level-mismatch` |
| 72 | `nordic-nrfx-4.2.1`<br>`clock.disable` | `nrf_clock_int_disable`<br>无路径 | `nrfx_clock_disable` (3; 2)<br>`nrfx_clock_hfclk_stop` (2; 5)<br>`nrfx_clock_lfclk_stop` (2; 3) | `ranking-model-confusion` |
| 73 | `nordic-nrfx-4.2.1`<br>`gpio.write` | `nrf_gpio_pin_write`<br>nrf_gpio_pin_write -> nrf_gpio_pin_clear -> nrf_gpio_pin_port_decode -> nrf_gpio_pin_present_check | `nrfx_gpiote_out_clear` (3; 24)<br>`nrfx_gpiote_out_set` (3; 19)<br>`nrfx_gpiote_out_toggle` (2; 16) | `ranking-model-confusion` |
| 74 | `nordic-nrfx-4.2.1`<br>`gpio.read` | `nrf_gpio_pin_read`<br>nrf_gpio_pin_read | `nrfx_gpiote_in_is_set` (3; 74) | `ranking-model-confusion` |
| 75 | `nordic-nrfx-4.2.1`<br>`gpio.attach_irq` | `nrfx_gpiote_irq_handler`<br>nrfx_gpiote_irq_handler -> irq_handler | `nrfx_gpiote_input_configure` (3; 19)<br>`nrfx_gpiote_trigger_enable` (1; 2) | `same-family-operation-confusion` |
| 76 | `nordic-nrfx-4.2.1`<br>`timer.set_interval` | `nrfx_timer_init`<br>nrfx_timer_init -> timer_configure -> nrfy_timer_int_init | `nrfx_timer_compare` (3; 4)<br>`nrfx_timer_extended_compare` (3; 8) | `same-family-operation-confusion` |
| 77 | `nuclei-soc-sdk`<br>`clock.initialize` | `rcu_rtc_clock_config`<br>rcu_rtc_clock_config | `SystemInit` (3; 2) | `ranking-model-confusion` |
| 78 | `nuclei-soc-sdk`<br>`clock.get_frequency` | `rcu_clock_freq_get`<br>rcu_clock_freq_get | `get_cpu_freq` (3; 2)<br>`SystemCoreClockUpdate` (1; 4) | `ranking-model-confusion` |
| 79 | `nuclei-soc-sdk`<br>`interrupt.initialize` | `PLIC_Interrupt_Init`<br>PLIC_Interrupt_Init | `ECLIC_Init` (3; 4) | `truth-path-missing` |
| 80 | `nuclei-soc-sdk`<br>`interrupt.register` | `PLIC_Register_IRQ`<br>PLIC_Register_IRQ | `Core_Register_IRQ` (3; 11)<br>`Core_Register_IRQ_S` (3; 12)<br>`ECLIC_Register_IRQ` (3; 9)<br>`ECLIC_Register_IRQ_S` (3; 13) | `effect-strength-confusion` |
| 81 | `nuclei-soc-sdk`<br>`uart.read` | `usart_read`<br>usart_read -> usart_data_receive | `uart_read` (3; 2)<br>`usart_data_receive` (3; 3) | `same-family-operation-confusion` |
| 82 | `nuclei-soc-sdk`<br>`timer.set_interval` | `timer_init`<br>timer_init | `timer_autoreload_value_config` (3; 8) | `same-family-operation-confusion` |
| 83 | `hpmicro-hpm-sdk`<br>`gpio.configure` | `qeo_pwm_config_mode`<br>无路径 | `gpio_set_pin_input` (3; 43)<br>`gpio_set_pin_output` (3; 42)<br>`gpio_set_pin_output_with_initial` (3; 27) | `ranking-model-confusion` |
| 84 | `hpmicro-hpm-sdk`<br>`timer.initialize` | `mchtmr_init_counter`<br>无路径 | `gptmr_channel_config` (3; 6) | `ranking-model-confusion` |
| 85 | `hpmicro-hpm-sdk`<br>`timer.set_interval` | `mchtmr_delay`<br>mchtmr_delay | `gptmr_channel_update_count` (3; 11)<br>`gptmr_update_cmp` (3; 12) | `truth-path-missing` |
| 86 | `espressif-esp-idf-6.0.1`<br>`gpio.write` | `gpio_set_direction`<br>gpio_set_direction | `gpio_set_level` (3; 2) | `same-family-operation-confusion` |
| 87 | `bouffalo-lhal`<br>`clock.get_frequency` | `Clock_System_Clock_Get`<br>Clock_System_Clock_Get -> Clock_MCU_Root_Clk_Mux_Output | `bflb_clk_get_peripheral_clock` (3; 9)<br>`bflb_clk_get_system_clock` (3; 8) | `ranking-model-confusion` |
| 88 | `bouffalo-lhal`<br>`gpio.write` | `GLB_GPIO_Write`<br>GLB_GPIO_Write | `bflb_gpio_reset` (3; 8)<br>`bflb_gpio_set` (3; 2)<br>`bflb_gpio_pin0_31_output` (2; 6)<br>`bflb_gpio_pin0_31_reset` (2; 19)<br>`bflb_gpio_pin0_31_set` (2; 10)<br>`bflb_gpio_pin32_63_output` (2; 7)<br>`bflb_gpio_pin32_63_reset` (2; 20)<br>`bflb_gpio_pin32_63_set` (2; 11) | `ranking-model-confusion` |
| 89 | `bouffalo-lhal`<br>`timer.initialize` | `TIMER_Init`<br>TIMER_Init | `bflb_timer_init` (3; 2) | `ranking-model-confusion` |
| 90 | `libopencm3-hal`<br>`clock.initialize` | `ccs_configure_clocks`<br>ccs_configure_clocks | `rcc_clock_setup_hse` (3; 3)<br>`rcc_clock_setup_hse_3v3` (3; 5)<br>`rcc_clock_setup_hsi` (3; 4)<br>`rcc_clock_setup_hsi48` (3; 19)<br>`rcc_clock_setup_cfgr` (1; 8)<br>`rcc_clock_setup_domain1` (1; 10)<br>`rcc_clock_setup_domain2` (1; 13)<br>`rcc_clock_setup_domain3` (1; 14) | `ranking-model-confusion` |
| 91 | `libopencm3-hal`<br>`clock.disable` | `rcc_disable_rtc_clock`<br>无路径 | `rcc_periph_clock_disable` (3; 2) | `truth-path-missing` |
| 92 | `libopencm3-hal`<br>`uart.write` | `uart_send`<br>uart_send | `usart_send_blocking` (3; 6)<br>`usart_send` (2; 5) | `ranking-model-confusion` |
| 93 | `libopencm3-hal`<br>`uart.read` | `uart_read`<br>无路径 | `usart_recv_blocking` (3; 11)<br>`usart_recv` (2; 6) | `ranking-model-confusion` |
| 94 | `libopencm3-hal`<br>`gpio.write` | `gpio_write`<br>gpio_write | `gpio_clear` (3; 5)<br>`gpio_set` (3; 3)<br>`gpio_toggle` (2; 4) | `truth-path-missing` |
| 95 | `libopencm3-hal`<br>`gpio.read` | `gpio_read`<br>gpio_read | `gpio_get` (3; 2) | `same-family-operation-confusion` |
| 96 | `libopencm3-hal`<br>`timer.start` | `timer_enable`<br>无路径 | `timer_enable_counter` (3; 3) | `truth-path-missing` |
| 97 | `libopencm3-hal`<br>`timer.stop` | `timer_stop`<br>timer_stop | `timer_disable_counter` (3; 2) | `truth-path-missing` |
| 98 | `alif-ensemble-dfp`<br>`clock.disable` | `canfd_clock_disable`<br>canfd_clock_disable | `SERVICES_clocks_enable_clock` (3; 69) | `ranking-model-confusion` |
| 99 | `alif-ensemble-dfp`<br>`gpio.write` | `pinconf_set`<br>pinconf_set | `gpio_bit_man_set_value_high` (2; 11)<br>`gpio_bit_man_set_value_low` (2; 10)<br>`gpio_set_value_high` (2; 4)<br>`gpio_set_value_low` (2; 6)<br>`GPIO_SetValue` (1; 2) | `ranking-model-confusion` |
| 100 | `alif-ensemble-dfp`<br>`timer.initialize` | `chbsp_periodic_timer_init`<br>无路径 | `utimer_config_mode` (2; 2) | `ranking-model-confusion` |
| 101 | `alif-ensemble-dfp`<br>`timer.stop` | `lptimer_disable_counter`<br>lptimer_disable_counter | `utimer_counter_stop` (3; 2) | `ranking-model-confusion` |
