# 预训练代码效果排序完整错误报告 v0.2

## 1. 报告口径

本报告使用 H02 和 `pretrained-code-calibrated-fusion` 的跨独立组五折 out-of-fold 预测。每个查询只由未见过该 independence group 的模型预测。板卡外部诊断不并入本报告。

- 有效查询：281
- Top1 正确：139
- Top1 错误：142
- P@1：0.494662
- 完整机器可读记录：`experiments/operation-ranking/results-pretrained-effect-h02-v0.2-errors.json`

## 2. 主错误归因

归因是基于当前图证据的可复现诊断规则，不等同于人工确认的唯一根因。

| 主归因 | 错误数 | 占全部错误 |
| --- | ---: | ---: |
| `ranking-model-confusion` | 57 | 40.1% |
| `same-family-operation-confusion` | 37 | 26.1% |
| `truth-path-missing` | 21 | 14.8% |
| `abstraction-level-mismatch` | 15 | 10.6% |
| `composite-entry-overranked` | 8 | 5.6% |
| `effect-strength-confusion` | 4 | 2.8% |

## 3. 按操作统计

| 操作 | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `timer.set_interval` | 16/20 | 80.0% |
| `clock.initialize` | 10/13 | 76.9% |
| `clock.enable` | 8/12 | 66.7% |
| `gpio.attach_irq` | 5/8 | 62.5% |
| `interrupt.initialize` | 3/5 | 60.0% |
| `timer.start` | 12/20 | 60.0% |
| `clock.disable` | 7/12 | 58.3% |
| `gpio.write` | 11/19 | 57.9% |
| `gpio.configure` | 9/16 | 56.2% |
| `timer.stop` | 11/20 | 55.0% |
| `interrupt.disable` | 7/13 | 53.8% |
| `timer.initialize` | 9/17 | 52.9% |
| `interrupt.register` | 3/7 | 42.9% |
| `gpio.read` | 8/19 | 42.1% |
| `clock.get_frequency` | 5/12 | 41.7% |
| `uart.write` | 6/19 | 31.6% |
| `interrupt.enable` | 4/13 | 30.8% |
| `uart.configure` | 4/17 | 23.5% |
| `uart.read` | 4/19 | 21.1% |

## 4. 按 SDK 统计

| SDK | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `bouffalo-lhal` | 15/16 | 93.8% |
| `arduino-renesas-core` | 7/9 | 77.8% |
| `sifli-hal` | 12/16 | 75.0% |
| `nordic-nrfx-4.2.1` | 9/14 | 64.3% |
| `renesas-fsp` | 11/18 | 61.1% |
| `hpmicro-hpm-sdk` | 6/10 | 60.0% |
| `ti-simplelink-f2` | 9/15 | 60.0% |
| `nuclei-soc-sdk` | 9/16 | 56.2% |
| `raspberry-pi-pico-sdk-2.2.0` | 9/18 | 50.0% |
| `silabs-emlib` | 7/14 | 50.0% |
| `sony-spresense-sdk` | 3/6 | 50.0% |
| `telink-tlsr9-hal` | 5/11 | 45.5% |
| `wch-ch32v307-stdperiph` | 7/16 | 43.8% |
| `libopencm3-hal` | 6/14 | 42.9% |
| `ti-mspm0-driverlib` | 6/14 | 42.9% |
| `nxp-mcuxpresso-sdk-2.16.100` | 7/19 | 36.8% |
| `nuvoton-std-driver` | 4/14 | 28.6% |
| `arm-mbed-hal` | 4/15 | 26.7% |
| `espressif-esp-idf-6.0.1` | 4/16 | 25.0% |
| `alif-ensemble-dfp` | 2/10 | 20.0% |

## 5. 代表性错误详解

### 5.1 `ti-mspm0-driverlib::clock.initialize`

- 系统 Top1：`DL_SYSCTL_setLFCLKSourceLFXT`，分数 0.698252。
- 系统效果路径：`DL_SYSCTL_setLFCLKSourceLFXT`。
- H02 真值：`DL_SYSCTL_configSYSPLL`(grade=3, rank=6), `DL_SYSCTL_setSYSOSCFreq`(grade=3, rank=30), `DL_SYSCTL_setHFCLKSourceHFCLKIN`(grade=2, rank=14), `DL_SYSCTL_setHFCLKSourceHFXT`(grade=2, rank=3), `DL_SYSCTL_setHFCLKSourceHFXTParams`(grade=2, rank=2), `DL_SYSCTL_setMCLKDivider`(grade=2, rank=13)。
- 主归因：`same-family-operation-confusion`，预测项与真值属于同一 API 家族，但动作或子操作不一致。
- Top5：`DL_SYSCTL_setLFCLKSourceLFXT`(label=0, score=0.698252), `DL_SYSCTL_setHFCLKSourceHFXTParams`(label=2, score=0.666289), `DL_SYSCTL_setHFCLKSourceHFXT`(label=2, score=0.658721), `DL_Timer_setClockConfig`(label=0, score=0.624162), `DL_RTC_Common_setCalendarAlarm2`(label=0, score=0.563203)。

### 5.2 `ti-mspm0-driverlib::clock.enable`

- 系统 Top1：`DL_MCAN_isModuleClockEnabled`，分数 0.845861。
- 系统效果路径：`DL_MCAN_isModuleClockEnabled`。
- H02 真值：`DL_SYSCTL_enableMFCLK`(grade=3, rank=9), `DL_SYSCTL_enableMFPCLK`(grade=3, rank=15), `DL_SYSCTL_enableSYSPLL`(grade=3, rank=4)。
- 主归因：`truth-path-missing`，真值函数没有恢复出足够的目标操作效果路径。
- Top5：`DL_MCAN_isModuleClockEnabled`(label=0, score=0.845861), `DL_SYSCTL_enableExternalClock`(label=0, score=0.83245), `HAL_delayMilliSeconds`(label=0, score=0.458251), `DL_SYSCTL_enableSYSPLL`(label=3, score=0.44403), `DL_Timer_isClockFaultDetectionEnabled`(label=0, score=0.406059)。

### 5.3 `ti-simplelink-f2::clock.disable`

- 系统 Top1：`PRCMAudioClockDisable`，分数 0.772535。
- 系统效果路径：`PRCMAudioClockDisable`。
- H02 真值：`Power_releaseDependency`(grade=2, rank=3)。
- 主归因：`ranking-model-confusion`，现有图特征和 PU 权重不能区分两个相近候选。
- Top5：`PRCMAudioClockDisable`(label=0, score=0.772535), `SysCtrlClockLossResetDisable`(label=0, score=0.542933), `Power_releaseDependency`(label=2, score=0.515681), `DAC_disable`(label=0, score=0.476514), `RFCClockDisable`(label=0, score=0.394455)。

### 5.4 `ti-simplelink-f2::uart.configure`

- 系统 Top1：`platformDebugUartInit`，分数 0.882168。
- 系统效果路径：`platformDebugUartInit`。
- H02 真值：`UART2_open`(grade=3, rank=2)。
- 主归因：`composite-entry-overranked`，复合初始化或多能力入口的硬件效果过强。
- Top5：`platformDebugUartInit`(label=0, score=0.882168), `UART2_open`(label=3, score=0.861974), `LogSinkUART_init`(label=0, score=0.623105), `LEDProfile_init`(label=0, score=0.577083), `UartLog_doInit`(label=0, score=0.526021)。

### 5.5 `ti-simplelink-f2::gpio.configure`

- 系统 Top1：`sid_pal_gpio_input_mode`，分数 1.124559。
- 系统效果路径：`sid_pal_gpio_input_mode`。
- H02 真值：`GPIO_setConfig`(grade=3, rank=43), `GPIO_setConfigAndMux`(grade=3, rank=44)。
- 主归因：`abstraction-level-mismatch`，直接效果层与 H02 指定的可迁移 API 层级不一致。
- Top5：`sid_pal_gpio_input_mode`(label=0, score=1.124559), `GPIO_init`(label=0, score=1.091513), `sid_pal_gpio_pull_mode`(label=0, score=1.067252), `sid_pal_gpio_output_mode`(label=0, score=1.032057), `Radio_Init`(label=0, score=0.644448)。

### 5.6 `ti-simplelink-f2::timer.start`

- 系统 Top1：`OsalPortTimers_startTimer`，分数 0.980162。
- 系统效果路径：`OsalPortTimers_startTimer -> createTimerEntry`。
- H02 真值：`GPTimerCC26XX_start`(grade=3, rank=7)。
- 主归因：`effect-strength-confusion`，错误候选的寄存器效果强度压过了接口契约。
- Top5：`OsalPortTimers_startTimer`(label=0, score=0.980162), `OsalPortTimers_startReloadTimer`(label=0, score=0.740103), `osal_start_timerEx`(label=0, score=0.70752), `osal_CbTimerStart`(label=0, score=0.688139), `port_timerStart`(label=0, score=0.675605)。

## 6. 全部 Top1 错误清单

真值排名来自该折完整唯一符号排序；每一行同时保留系统 Top1、效果路径以及全部 H02 正例。

| # | SDK / 操作 | 系统 Top1 | H02 真值（等级；排名） | 主归因 |
| ---: | --- | --- | --- | --- |
| 1 | `ti-mspm0-driverlib`<br>`clock.initialize` | `DL_SYSCTL_setLFCLKSourceLFXT`<br>DL_SYSCTL_setLFCLKSourceLFXT | `DL_SYSCTL_configSYSPLL` (3; 6)<br>`DL_SYSCTL_setSYSOSCFreq` (3; 30)<br>`DL_SYSCTL_setHFCLKSourceHFCLKIN` (2; 14)<br>`DL_SYSCTL_setHFCLKSourceHFXT` (2; 3)<br>`DL_SYSCTL_setHFCLKSourceHFXTParams` (2; 2)<br>`DL_SYSCTL_setMCLKDivider` (2; 13) | `same-family-operation-confusion` |
| 2 | `ti-mspm0-driverlib`<br>`clock.enable` | `DL_MCAN_isModuleClockEnabled`<br>DL_MCAN_isModuleClockEnabled | `DL_SYSCTL_enableMFCLK` (3; 9)<br>`DL_SYSCTL_enableMFPCLK` (3; 15)<br>`DL_SYSCTL_enableSYSPLL` (3; 4) | `truth-path-missing` |
| 3 | `ti-mspm0-driverlib`<br>`clock.disable` | `DL_SYSCTL_disableExternalClock`<br>无路径 | `DL_SYSCTL_disableHFXT` (3; 3)<br>`DL_SYSCTL_disableMFCLK` (3; 5)<br>`DL_SYSCTL_disableMFPCLK` (3; 6)<br>`DL_SYSCTL_disableSYSPLL` (3; 4) | `truth-path-missing` |
| 4 | `ti-mspm0-driverlib`<br>`gpio.configure` | `HAL_configurePin`<br>HAL_configurePin | `DL_GPIO_initDigitalInput` (3; 16)<br>`DL_GPIO_initDigitalOutput` (3; 14) | `truth-path-missing` |
| 5 | `ti-mspm0-driverlib`<br>`gpio.read` | `HAL_readGPIOPin`<br>HAL_readGPIOPin | `DL_GPIO_readPins` (3; 2) | `truth-path-missing` |
| 6 | `ti-mspm0-driverlib`<br>`timer.set_interval` | `DL_Timer_initCompareMode`<br>DL_Timer_initCompareMode | `DL_TimerB_setLoadValue` (3; 3)<br>`DL_Timer_setLoadValue` (3; 5) | `truth-path-missing` |
| 7 | `ti-simplelink-f2`<br>`clock.enable` | `PRCMAudioClockEnable`<br>PRCMAudioClockEnable | `Power_setDependency` (2; 9) | `truth-path-missing` |
| 8 | `ti-simplelink-f2`<br>`clock.disable` | `PRCMAudioClockDisable`<br>PRCMAudioClockDisable | `Power_releaseDependency` (2; 3) | `ranking-model-confusion` |
| 9 | `ti-simplelink-f2`<br>`uart.configure` | `platformDebugUartInit`<br>platformDebugUartInit | `UART2_open` (3; 2) | `composite-entry-overranked` |
| 10 | `ti-simplelink-f2`<br>`uart.write` | `otPlatUartSend`<br>otPlatUartSend -> UART2_write -> UART2_writeTimeout -> UART2_writeTimeoutBlocking | `UART2_write` (3; 3)<br>`UART2_writeTimeout` (2; 6)<br>`UART2_writePolling` (1; 18) | `ranking-model-confusion` |
| 11 | `ti-simplelink-f2`<br>`gpio.configure` | `sid_pal_gpio_input_mode`<br>sid_pal_gpio_input_mode | `GPIO_setConfig` (3; 43)<br>`GPIO_setConfigAndMux` (3; 44) | `abstraction-level-mismatch` |
| 12 | `ti-simplelink-f2`<br>`gpio.attach_irq` | `sid_pal_gpio_set_irq`<br>sid_pal_gpio_set_irq | `GPIO_setCallback` (3; 6)<br>`GPIO_enableInt` (1; 2)<br>`GPIO_setInterruptConfig` (1; 7) | `composite-entry-overranked` |
| 13 | `ti-simplelink-f2`<br>`timer.start` | `OsalPortTimers_startTimer`<br>OsalPortTimers_startTimer -> createTimerEntry | `GPTimerCC26XX_start` (3; 7) | `effect-strength-confusion` |
| 14 | `ti-simplelink-f2`<br>`timer.stop` | `port_timerStop`<br>port_timerStop -> timer_settime | `GPTimerCC26XX_stop` (3; 5) | `ranking-model-confusion` |
| 15 | `ti-simplelink-f2`<br>`timer.set_interval` | `Timer_setPeriod`<br>Timer_setPeriod | `GPTimerCC26XX_setLoadValue` (3; 8)<br>`GPTimerCC26XX_setMatchValue` (3; 2) | `abstraction-level-mismatch` |
| 16 | `arm-mbed-hal`<br>`clock.initialize` | `CLOCK_InitOsc0`<br>CLOCK_InitOsc0 | `SystemInit` (2; 9)<br>`mbed_sdk_init` (2; 10) | `abstraction-level-mismatch` |
| 17 | `arm-mbed-hal`<br>`timer.start` | `HAL_LPTIM_Counter_Start`<br>HAL_LPTIM_Counter_Start | `lp_ticker_set_interrupt` (3; 6)<br>`us_ticker_set_interrupt` (3; 4) | `abstraction-level-mismatch` |
| 18 | `arm-mbed-hal`<br>`timer.stop` | `HAL_HRTIM_SimpleBaseStop`<br>HAL_HRTIM_SimpleBaseStop | `lp_ticker_disable_interrupt` (3; 5)<br>`us_ticker_disable_interrupt` (3; 2) | `ranking-model-confusion` |
| 19 | `arm-mbed-hal`<br>`timer.set_interval` | `am_hal_ctimer_compare_set`<br>am_hal_ctimer_compare_set | `lp_ticker_set_interrupt` (2; 7)<br>`us_ticker_set_interrupt` (2; 4) | `composite-entry-overranked` |
| 20 | `telink-tlsr9-hal`<br>`clock.initialize` | `clock_32k_init`<br>无路径 | `clock_init` (3; 2) | `same-family-operation-confusion` |
| 21 | `telink-tlsr9-hal`<br>`interrupt.disable` | `aes_set_irq_mask`<br>aes_set_irq_mask | `core_interrupt_disable` (3; 22)<br>`plic_interrupt_disable` (3; 2) | `truth-path-missing` |
| 22 | `telink-tlsr9-hal`<br>`gpio.write` | `gpio_set_up_down_res`<br>gpio_set_up_down_res | `gpio_set_level` (3; 12)<br>`gpio_set_high_level` (2; 11)<br>`gpio_set_low_level` (2; 19)<br>`gpio_toggle` (2; 2) | `same-family-operation-confusion` |
| 23 | `telink-tlsr9-hal`<br>`gpio.read` | `gpio_read_cache`<br>无路径 | `gpio_get_level` (3; 2)<br>`gpio_get_level_all` (2; 5) | `same-family-operation-confusion` |
| 24 | `telink-tlsr9-hal`<br>`timer.set_interval` | `timer1_set_tick`<br>无路径 | `stimer_set_irq_capture` (3; 23) | `truth-path-missing` |
| 25 | `renesas-fsp`<br>`clock.initialize` | `bsp_clock_set_prechange`<br>bsp_clock_set_prechange | `R_CGC_ClocksCfg` (3; 14)<br>`R_CGC_Open` (3; 42) | `ranking-model-confusion` |
| 26 | `renesas-fsp`<br>`interrupt.enable` | `R_BSP_IrqEnableNoClear`<br>R_BSP_IrqEnableNoClear | `R_BSP_IrqCfgEnable` (3; 2)<br>`R_BSP_IrqEnable` (3; 3) | `same-family-operation-confusion` |
| 27 | `renesas-fsp`<br>`uart.write` | `rm_at_transport_da16xxx_uart_atCommandSend`<br>rm_at_transport_da16xxx_uart_atCommandSend | `R_SCI_B_UART_Write` (3; 8)<br>`R_SCI_UART_Write` (3; 6) | `composite-entry-overranked` |
| 28 | `renesas-fsp`<br>`uart.read` | `R_SAU_UART_Read`<br>R_SAU_UART_Read | `R_SCI_B_UART_Read` (3; 8)<br>`R_SCI_UART_Read` (3; 9) | `ranking-model-confusion` |
| 29 | `renesas-fsp`<br>`gpio.write` | `R_BSP_PinWrite`<br>R_BSP_PinWrite | `R_IOPORT_PinWrite` (3; 5) | `effect-strength-confusion` |
| 30 | `renesas-fsp`<br>`gpio.read` | `ptxPLAT_GPIO_ReadLevel`<br>ptxPLAT_GPIO_ReadLevel | `R_IOPORT_PinRead` (3; 7) | `ranking-model-confusion` |
| 31 | `renesas-fsp`<br>`gpio.attach_irq` | `ptxPLAT_GPIO_EnableInterrupt`<br>ptxPLAT_GPIO_EnableInterrupt | `R_ICU_ExternalIrqCallbackSet` (3; 4)<br>`R_ICU_ExternalIrqOpen` (3; 3)<br>`R_ICU_ExternalIrqEnable` (1; 5) | `abstraction-level-mismatch` |
| 32 | `renesas-fsp`<br>`timer.initialize` | `ptxPLAT_TIMER_GetInitializedTimer`<br>ptxPLAT_TIMER_GetInitializedTimer | `R_AGT_Open` (3; 8)<br>`R_GPT_Open` (3; 4) | `abstraction-level-mismatch` |
| 33 | `renesas-fsp`<br>`timer.start` | `ptxPLAT_TIMER_Start`<br>ptxPLAT_TIMER_Start | `R_AGT_Start` (3; 3)<br>`R_GPT_Start` (3; 7) | `composite-entry-overranked` |
| 34 | `renesas-fsp`<br>`timer.stop` | `ptxPERIPH_APPTIMER_Stop`<br>ptxPERIPH_APPTIMER_Stop | `R_AGT_Stop` (3; 3)<br>`R_GPT_Stop` (3; 7) | `effect-strength-confusion` |
| 35 | `renesas-fsp`<br>`timer.set_interval` | `R_ULPT_CompareMatchSet`<br>R_ULPT_CompareMatchSet | `R_AGT_PeriodSet` (3; 13)<br>`R_GPT_PeriodSet` (3; 11) | `ranking-model-confusion` |
| 36 | `wch-ch32v307-stdperiph`<br>`clock.enable` | `RCC_APB1PeriphResetCmd`<br>RCC_APB1PeriphResetCmd | `RCC_AHBPeriphClockCmd` (3; 12)<br>`RCC_APB1PeriphClockCmd` (3; 19)<br>`RCC_APB2PeriphClockCmd` (3; 9) | `same-family-operation-confusion` |
| 37 | `wch-ch32v307-stdperiph`<br>`clock.disable` | `RCC_APB1PeriphResetCmd`<br>RCC_APB1PeriphResetCmd | `RCC_AHBPeriphClockCmd` (3; 8)<br>`RCC_APB1PeriphClockCmd` (3; 13)<br>`RCC_APB2PeriphClockCmd` (3; 6) | `same-family-operation-confusion` |
| 38 | `wch-ch32v307-stdperiph`<br>`uart.configure` | `USART_StructInit`<br>USART_StructInit | `USART_Init` (3; 4) | `same-family-operation-confusion` |
| 39 | `wch-ch32v307-stdperiph`<br>`timer.initialize` | `TIM_BDTRStructInit`<br>TIM_BDTRStructInit | `TIM_TimeBaseInit` (3; 3) | `same-family-operation-confusion` |
| 40 | `wch-ch32v307-stdperiph`<br>`timer.start` | `TIM_SetCounter`<br>TIM_SetCounter | `TIM_Cmd` (3; 24) | `same-family-operation-confusion` |
| 41 | `wch-ch32v307-stdperiph`<br>`timer.stop` | `TIM_SetCounter`<br>TIM_SetCounter | `TIM_Cmd` (3; 10) | `same-family-operation-confusion` |
| 42 | `wch-ch32v307-stdperiph`<br>`timer.set_interval` | `TIM_SetCounter`<br>TIM_SetCounter | `TIM_SetAutoreload` (3; 6)<br>`TIM_SetCompare1` (2; 4)<br>`TIM_SetCompare2` (2; 5)<br>`TIM_SetCompare3` (2; 2)<br>`TIM_SetCompare4` (2; 3) | `truth-path-missing` |
| 43 | `arduino-renesas-core`<br>`interrupt.enable` | `getIrqIndexFromPin`<br>getIrqIndexFromPin | `interrupts` (2; 38) | `truth-path-missing` |
| 44 | `arduino-renesas-core`<br>`interrupt.disable` | `detachIrq2Link`<br>detachIrq2Link | `noInterrupts` (2; 48) | `truth-path-missing` |
| 45 | `arduino-renesas-core`<br>`uart.configure` | `UART::UART`<br>UART::UART | `UART::begin` (3; 3) | `truth-path-missing` |
| 46 | `arduino-renesas-core`<br>`uart.write` | `UART::write_raw`<br>UART::write_raw | `UART::write` (3; 9) | `same-family-operation-confusion` |
| 47 | `arduino-renesas-core`<br>`timer.initialize` | `FspTimer::get_counter`<br>FspTimer::get_counter | `FspTimer::begin` (3; 2) | `same-family-operation-confusion` |
| 48 | `arduino-renesas-core`<br>`timer.start` | `FspTimer::get_counter`<br>FspTimer::get_counter | `FspTimer::start` (3; 2) | `same-family-operation-confusion` |
| 49 | `arduino-renesas-core`<br>`timer.set_interval` | `FspTimer::get_counter`<br>FspTimer::get_counter | `FspTimer::set_period` (3; 12) | `same-family-operation-confusion` |
| 50 | `silabs-emlib`<br>`clock.initialize` | `CMU_ClockDivSet`<br>CMU_ClockDivSet | `CMU_ClockSelectSet` (3; 8) | `same-family-operation-confusion` |
| 51 | `silabs-emlib`<br>`clock.disable` | `DAC_IntDisable`<br>无路径 | `CMU_ClockEnable` (3; 70) | `ranking-model-confusion` |
| 52 | `silabs-emlib`<br>`gpio.configure` | `GPIO_PinOutToggle`<br>GPIO_PinOutToggle | `GPIO_PinModeSet` (3; 56) | `same-family-operation-confusion` |
| 53 | `silabs-emlib`<br>`timer.initialize` | `MSC_Init`<br>MSC_Init | `TIMER_Init` (3; 6) | `ranking-model-confusion` |
| 54 | `silabs-emlib`<br>`timer.start` | `cycle_counter_start`<br>无路径 | `TIMER_Enable` (3; 2) | `ranking-model-confusion` |
| 55 | `silabs-emlib`<br>`timer.stop` | `cycle_counter_stop`<br>无路径 | `TIMER_Enable` (3; 70) | `ranking-model-confusion` |
| 56 | `silabs-emlib`<br>`timer.set_interval` | `TIMER_CounterSet`<br>TIMER_CounterSet | `TIMER_TopSet` (3; 13) | `same-family-operation-confusion` |
| 57 | `nxp-mcuxpresso-sdk-2.16.100`<br>`clock.initialize` | `CLOCK_SetLpFllAsyncClkDiv`<br>CLOCK_SetLpFllAsyncClkDiv | `CLOCK_Init` (3; 2)<br>`CLOCK_InitArmPll` (3; 14)<br>`CLOCK_InitArmPllWithFreq` (3; 30)<br>`CLOCK_InitAudioPfd` (3; 8)<br>`CLOCK_InitAudioPll` (3; 13)<br>`CLOCK_InitAudioPll1` (3; 3)<br>`CLOCK_InitAudioPll2` (3; 4)<br>`CLOCK_InitAudioPllWithFreq` (3; 29)<br>`CLOCK_InitEnetPll` (3; 12) | `same-family-operation-confusion` |
| 58 | `nxp-mcuxpresso-sdk-2.16.100`<br>`clock.get_frequency` | `CLOCK_GetOutClkFreq`<br>CLOCK_GetOutClkFreq | `CLOCK_GetFreq` (3; 2)<br>`CLOCK_GetAcmpClkFreq` (2; 22)<br>`CLOCK_GetAdAudClkFreq` (2; 29)<br>`CLOCK_GetAdFroAsyncFreq` (2; 18)<br>`CLOCK_GetAdSysOscAsyncFreq` (2; 35)<br>`CLOCK_GetAdcClkFreq` (2; 19)<br>`CLOCK_GetAdSaiClkFreq` (1; 44) | `same-family-operation-confusion` |
| 59 | `nxp-mcuxpresso-sdk-2.16.100`<br>`interrupt.initialize` | `MSGINTR_Init`<br>无路径 | `IRQ_Init` (3; 2)<br>`IRQ_SetPriority` (1; 3) | `ranking-model-confusion` |
| 60 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.configure` | `CMSIS_GPIO_InitPinAsInput`<br>CMSIS_GPIO_InitPinAsInput | `GPIO_PinInit` (3; 5)<br>`GPIO_PortInit` (1; 19) | `ranking-model-confusion` |
| 61 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.attach_irq` | `RGPIO_SetPinInterruptConfig`<br>RGPIO_SetPinInterruptConfig | `PINT_PinInterruptConfig` (3; 19)<br>`GPIO_PinSetInterruptConfig` (1; 11) | `ranking-model-confusion` |
| 62 | `nxp-mcuxpresso-sdk-2.16.100`<br>`timer.initialize` | `CTIMER_SetupMatch`<br>CTIMER_SetupMatch | `CTIMER_Init` (3; 6)<br>`FTM_Init` (2; 15)<br>`LPTMR_Init` (2; 25)<br>`QTMR_Init` (2; 20)<br>`SCTIMER_Init` (2; 7) | `same-family-operation-confusion` |
| 63 | `nxp-mcuxpresso-sdk-2.16.100`<br>`timer.set_interval` | `RIT_SetTimerCompare`<br>无路径 | `CTIMER_SetupMatch` (3; 14)<br>`FTM_SetTimerPeriod` (2; 4)<br>`LPTMR_SetTimerPeriod` (2; 8)<br>`QTMR_SetTimerPeriod` (2; 7)<br>`TPM_SetTimerPeriod` (2; 10) | `ranking-model-confusion` |
| 64 | `sony-spresense-sdk`<br>`clock.get_frequency` | `cxd56_get_clock`<br>cxd56_get_clock | `clock_getcpubaseclock` (3; 2) | `ranking-model-confusion` |
| 65 | `sony-spresense-sdk`<br>`gpio.read` | `cxd56_gpio_read`<br>cxd56_gpio_read | `board_gpio_read` (2; 3) | `ranking-model-confusion` |
| 66 | `sony-spresense-sdk`<br>`timer.set_interval` | `StepCounterClass`<br>StepCounterClass | `timer_settimeout` (2; 10) | `truth-path-missing` |
| 67 | `sifli-hal`<br>`clock.initialize` | `HAL_SDMMC_CLK_SET`<br>HAL_SDMMC_CLK_SET | `HAL_RCC_Init` (3; 7) | `ranking-model-confusion` |
| 68 | `sifli-hal`<br>`clock.enable` | `HAL_RCC_IsModuleEnabled`<br>HAL_RCC_IsModuleEnabled | `HAL_RCC_EnableModule` (3; 2)<br>`HAL_RCC_HCPU_EnableDLL` (3; 3)<br>`HAL_RCC_HCPU_EnableDLL1` (3; 8)<br>`HAL_RCC_HCPU_EnableDLL2` (3; 14)<br>`HAL_RCC_HCPU_EnableDLL3` (3; 16) | `same-family-operation-confusion` |
| 69 | `sifli-hal`<br>`clock.disable` | `HAL_RCC_LCPU_ClockSelect`<br>HAL_RCC_LCPU_ClockSelect | `HAL_RCC_DisableModule` (3; 2)<br>`HAL_RCC_HCPU_DisableDLL1` (3; 8)<br>`HAL_RCC_HCPU_DisableDLL2` (3; 7) | `same-family-operation-confusion` |
| 70 | `sifli-hal`<br>`clock.get_frequency` | `HAL_RCC_LCPU_GetClockSrc`<br>HAL_RCC_LCPU_GetClockSrc | `HAL_RCC_GetHCLKFreq` (3; 3)<br>`HAL_RCC_GetModuleFreq` (3; 5)<br>`HAL_RCC_GetPCLKFreq` (3; 4)<br>`HAL_RCC_GetSysCLKFreq` (3; 6) | `same-family-operation-confusion` |
| 71 | `sifli-hal`<br>`interrupt.disable` | `ll_gpio_bank_disable_irq`<br>ll_gpio_bank_disable_irq | `HAL_NVIC_DisableIRQ` (3; 2) | `ranking-model-confusion` |
| 72 | `sifli-hal`<br>`uart.write` | `UART_EndTransmit_IT`<br>UART_EndTransmit_IT | `HAL_UART_Transmit` (3; 2)<br>`HAL_UART_Transmit_DMA` (2; 10)<br>`HAL_UART_Transmit_IT` (2; 7) | `ranking-model-confusion` |
| 73 | `sifli-hal`<br>`uart.read` | `ll_usart_receive_data8`<br>无路径 | `HAL_UART_Receive` (3; 3)<br>`HAL_UART_Receive_DMA` (2; 8)<br>`HAL_UART_Receive_IT` (2; 4) | `ranking-model-confusion` |
| 74 | `sifli-hal`<br>`gpio.configure` | `ll_pinmux_is_input_enabled`<br>无路径 | `HAL_GPIO_Init` (3; 4) | `ranking-model-confusion` |
| 75 | `sifli-hal`<br>`gpio.write` | `ll_gpio_bank_set_high_pin`<br>ll_gpio_bank_set_high_pin -> ll_gpio_bank_set_high | `HAL_GPIO_WritePin` (3; 14)<br>`HAL_GPIO_TogglePin` (2; 9) | `ranking-model-confusion` |
| 76 | `sifli-hal`<br>`timer.initialize` | `HAL_SDADC_SetTimer`<br>HAL_SDADC_SetTimer | `HAL_LPTIM_Init` (3; 7) | `ranking-model-confusion` |
| 77 | `sifli-hal`<br>`timer.stop` | `HAL_GPT_OC_Stop`<br>HAL_GPT_OC_Stop | `HAL_LPTIM_Counter_Stop` (3; 5)<br>`HAL_LPTIM_Counter_Stop_IT` (2; 4) | `ranking-model-confusion` |
| 78 | `sifli-hal`<br>`timer.set_interval` | `HAL_LPTIM_CompareMatchCallback`<br>HAL_LPTIM_CompareMatchCallback | `HAL_LPTIM_PWM_Set_Period` (3; 10) | `same-family-operation-confusion` |
| 79 | `nuvoton-std-driver`<br>`clock.initialize` | `SDH_Set_clock`<br>SDH_Set_clock | `CLK_SetBusClock` (3; 10)<br>`CLK_SetCoreClock` (3; 2) | `abstraction-level-mismatch` |
| 80 | `nuvoton-std-driver`<br>`clock.enable` | `CLK_ENABLE_RTCWK`<br>CLK_ENABLE_RTCWK | `CLK_EnableModuleClock` (3; 5)<br>`CLK_EnablePLL` (3; 8)<br>`CLK_EnableXtalRC` (3; 13) | `same-family-operation-confusion` |
| 81 | `nuvoton-std-driver`<br>`gpio.configure` | `LPGPIO_MODE_INPUT`<br>LPGPIO_MODE_INPUT | `GPIO_SetMode` (3; 31) | `effect-strength-confusion` |
| 82 | `nuvoton-std-driver`<br>`gpio.write` | `PWM_SetBrakePinSource`<br>PWM_SetBrakePinSource | `GPIO_SET_OUT_DATA` (2; 8) | `truth-path-missing` |
| 83 | `raspberry-pi-pico-sdk-2.2.0`<br>`clock.enable` | `dma_irqn_set_channel_enabled`<br>dma_irqn_set_channel_enabled | `clock_configure` (2; 8) | `abstraction-level-mismatch` |
| 84 | `raspberry-pi-pico-sdk-2.2.0`<br>`interrupt.register` | `check_irq_param`<br>check_irq_param | `irq_add_shared_handler` (3; 5)<br>`irq_set_exclusive_handler` (3; 13) | `ranking-model-confusion` |
| 85 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.read` | `uart_get_hw`<br>uart_get_hw | `uart_read_blocking` (3; 4)<br>`uart_getc` (2; 2) | `same-family-operation-confusion` |
| 86 | `raspberry-pi-pico-sdk-2.2.0`<br>`gpio.write` | `gpio_set_pulls`<br>gpio_set_pulls | `gpio_put` (3; 2)<br>`gpio_clr_mask` (2; 15)<br>`gpio_put_masked` (2; 19)<br>`gpio_set_mask` (2; 28)<br>`gpio_xor_mask` (2; 6) | `same-family-operation-confusion` |
| 87 | `raspberry-pi-pico-sdk-2.2.0`<br>`gpio.attach_irq` | `gpio_acknowledge_irq`<br>gpio_acknowledge_irq | `gpio_set_irq_enabled_with_callback` (3; 15)<br>`gpio_add_raw_irq_handler` (1; 27)<br>`gpio_add_raw_irq_handler_with_order_priority` (1; 16)<br>`gpio_set_irq_callback` (1; 33)<br>`gpio_set_irq_enabled` (1; 5) | `same-family-operation-confusion` |
| 88 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.initialize` | `timer_hardware_alarm_set_target`<br>timer_hardware_alarm_set_target | `alarm_pool_create` (2; 12)<br>`alarm_pool_create_with_unused_hardware_alarm` (2; 14)<br>`hardware_alarm_claim` (1; 10)<br>`hardware_alarm_claim_unused` (1; 9) | `abstraction-level-mismatch` |
| 89 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.start` | `tick_start`<br>tick_start | `add_alarm_at` (3; 28)<br>`add_alarm_in_ms` (3; 25)<br>`add_alarm_in_us` (3; 23)<br>`add_repeating_timer_ms` (3; 16)<br>`add_repeating_timer_us` (3; 17)<br>`hardware_alarm_set_target` (3; 5) | `abstraction-level-mismatch` |
| 90 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.stop` | `timer_get_index`<br>timer_get_index | `cancel_alarm` (3; 18)<br>`cancel_repeating_timer` (3; 3)<br>`hardware_alarm_cancel` (3; 9) | `abstraction-level-mismatch` |
| 91 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.set_interval` | `pwm_set_counter`<br>无路径 | `add_repeating_timer_ms` (3; 15)<br>`add_repeating_timer_us` (3; 30)<br>`add_alarm_at` (2; 36)<br>`add_alarm_in_ms` (2; 39)<br>`add_alarm_in_us` (2; 33)<br>`hardware_alarm_set_target` (2; 8) | `ranking-model-confusion` |
| 92 | `nordic-nrfx-4.2.1`<br>`clock.initialize` | `nrf_clock_hfclkaudio_config_set`<br>nrf_clock_hfclkaudio_config_set | `nrfx_clock_hfclk_init` (3; 3)<br>`nrfx_clock_init` (3; 8)<br>`nrfx_clock_lfclk_init` (3; 4) | `ranking-model-confusion` |
| 93 | `nordic-nrfx-4.2.1`<br>`clock.enable` | `nrf_clock_int_enable`<br>无路径 | `nrfx_clock_enable` (3; 2)<br>`nrfx_clock_hfclk_start` (2; 4)<br>`nrfx_clock_lfclk_start` (2; 5) | `ranking-model-confusion` |
| 94 | `nordic-nrfx-4.2.1`<br>`clock.disable` | `nrf_clock_int_disable`<br>无路径 | `nrfx_clock_disable` (3; 4)<br>`nrfx_clock_hfclk_stop` (2; 2)<br>`nrfx_clock_lfclk_stop` (2; 3) | `ranking-model-confusion` |
| 95 | `nordic-nrfx-4.2.1`<br>`uart.write` | `nrfx_uart_rx`<br>nrfx_uart_rx | `nrfx_uart_tx` (3; 2)<br>`nrfx_uarte_tx` (3; 27)<br>`nrfx_uarte_tx_abort` (1; 13) | `same-family-operation-confusion` |
| 96 | `nordic-nrfx-4.2.1`<br>`gpio.write` | `nrfy_gpio_pin_clock_set`<br>nrfy_gpio_pin_clock_set -> nrf_gpio_pin_clock_set -> nrf_gpio_pin_port_decode -> nrf_gpio_pin_present_check | `nrfx_gpiote_out_clear` (3; 16)<br>`nrfx_gpiote_out_set` (3; 25)<br>`nrfx_gpiote_out_toggle` (2; 21) | `ranking-model-confusion` |
| 97 | `nordic-nrfx-4.2.1`<br>`gpio.read` | `nrf_gpio_pin_read`<br>nrf_gpio_pin_read | `nrfx_gpiote_in_is_set` (3; 76) | `ranking-model-confusion` |
| 98 | `nordic-nrfx-4.2.1`<br>`timer.start` | `nrf_timer_int_enable`<br>无路径 | `nrfx_timer_enable` (3; 5) | `ranking-model-confusion` |
| 99 | `nordic-nrfx-4.2.1`<br>`timer.stop` | `nrf_timer_int_disable`<br>无路径 | `nrfx_timer_disable` (3; 4) | `ranking-model-confusion` |
| 100 | `nordic-nrfx-4.2.1`<br>`timer.set_interval` | `nrf_grtc_sys_counter_compare_event_get`<br>nrf_grtc_sys_counter_compare_event_get | `nrfx_timer_compare` (3; 44)<br>`nrfx_timer_extended_compare` (3; 32) | `ranking-model-confusion` |
| 101 | `nuclei-soc-sdk`<br>`clock.initialize` | `usb_host_init`<br>usb_host_init | `SystemInit` (3; 44) | `composite-entry-overranked` |
| 102 | `nuclei-soc-sdk`<br>`clock.get_frequency` | `rcu_clock_freq_get`<br>rcu_clock_freq_get | `get_cpu_freq` (3; 3)<br>`SystemCoreClockUpdate` (1; 5) | `ranking-model-confusion` |
| 103 | `nuclei-soc-sdk`<br>`interrupt.initialize` | `cau_iv_init`<br>cau_iv_init | `ECLIC_Init` (3; 61) | `truth-path-missing` |
| 104 | `nuclei-soc-sdk`<br>`interrupt.disable` | `hau_interrupt_disable`<br>hau_interrupt_disable | `eclic_global_interrupt_disable` (3; 14)<br>`eclic_irq_disable` (3; 10) | `ranking-model-confusion` |
| 105 | `nuclei-soc-sdk`<br>`interrupt.register` | `Interrupt_Register_CoreIRQ`<br>Interrupt_Register_CoreIRQ | `Core_Register_IRQ` (3; 3)<br>`Core_Register_IRQ_S` (3; 4)<br>`ECLIC_Register_IRQ` (3; 6)<br>`ECLIC_Register_IRQ_S` (3; 5) | `ranking-model-confusion` |
| 106 | `nuclei-soc-sdk`<br>`gpio.write` | `gd_com_init`<br>gd_com_init | `gpio_bit_write` (3; 4)<br>`gpio_bit_reset` (2; 2)<br>`gpio_bit_set` (2; 5)<br>`gpio_bit_toggle` (2; 3)<br>`gpio_port_write` (2; 7) | `composite-entry-overranked` |
| 107 | `nuclei-soc-sdk`<br>`timer.start` | `timer_interrupt_enable`<br>timer_interrupt_enable | `timer_enable` (3; 5) | `same-family-operation-confusion` |
| 108 | `nuclei-soc-sdk`<br>`timer.stop` | `timer_interrupt_disable`<br>timer_interrupt_disable | `timer_disable` (3; 3) | `same-family-operation-confusion` |
| 109 | `nuclei-soc-sdk`<br>`timer.set_interval` | `timer_init`<br>timer_init | `timer_autoreload_value_config` (3; 6) | `same-family-operation-confusion` |
| 110 | `hpmicro-hpm-sdk`<br>`gpio.configure` | `uart_init`<br>uart_init | `gpio_set_pin_input` (3; 57)<br>`gpio_set_pin_output` (3; 55)<br>`gpio_set_pin_output_with_initial` (3; 58) | `composite-entry-overranked` |
| 111 | `hpmicro-hpm-sdk`<br>`gpio.write` | `ppi_set_clk_pin_disable`<br>无路径 | `gpio_write_pin` (3; 2) | `ranking-model-confusion` |
| 112 | `hpmicro-hpm-sdk`<br>`gpio.read` | `tsw_ep_mdio_read`<br>tsw_ep_mdio_read | `gpio_read_pin` (3; 2) | `truth-path-missing` |
| 113 | `hpmicro-hpm-sdk`<br>`timer.initialize` | `ptpc_init`<br>ptpc_init | `gptmr_channel_config` (3; 2) | `ranking-model-confusion` |
| 114 | `hpmicro-hpm-sdk`<br>`timer.start` | `pwmv2_counter_start_select_trigger_index`<br>pwmv2_counter_start_select_trigger_index | `gptmr_start_counter` (3; 7) | `truth-path-missing` |
| 115 | `hpmicro-hpm-sdk`<br>`timer.set_interval` | `pwmv2_calculate_set_period_parameter`<br>无路径 | `gptmr_channel_update_count` (3; 47)<br>`gptmr_update_cmp` (3; 44) | `truth-path-missing` |
| 116 | `espressif-esp-idf-6.0.1`<br>`interrupt.disable` | `esp_cpu_intr_disable`<br>esp_cpu_intr_disable -> rv_utils_intr_disable | `esp_intr_disable` (3; 2) | `ranking-model-confusion` |
| 117 | `espressif-esp-idf-6.0.1`<br>`gpio.configure` | `rtc_gpio_init`<br>rtc_gpio_init -> io_mux_enable_lp_io_clock | `gpio_config` (3; 3)<br>`gpio_set_direction` (2; 51)<br>`gpio_set_pull_mode` (2; 52) | `ranking-model-confusion` |
| 118 | `espressif-esp-idf-6.0.1`<br>`gpio.write` | `rtc_gpio_set_direction`<br>rtc_gpio_set_direction -> rtcio_hal_set_direction -> rtcio_ll_output_mode_set | `gpio_set_level` (3; 10) | `ranking-model-confusion` |
| 119 | `espressif-esp-idf-6.0.1`<br>`gpio.attach_irq` | `parlio_tx_unit_register_event_callbacks`<br>parlio_tx_unit_register_event_callbacks | `gpio_isr_handler_add` (3; 2)<br>`gpio_intr_enable` (1; 6)<br>`gpio_set_intr_type` (1; 3) | `abstraction-level-mismatch` |
| 120 | `bouffalo-lhal`<br>`clock.get_frequency` | `Clock_System_Clock_Get`<br>Clock_System_Clock_Get -> Clock_MCU_Root_Clk_Mux_Output | `bflb_clk_get_peripheral_clock` (3; 4)<br>`bflb_clk_get_system_clock` (3; 6) | `ranking-model-confusion` |
| 121 | `bouffalo-lhal`<br>`interrupt.initialize` | `__ECLIC_SetPriorityIRQ_S`<br>__ECLIC_SetPriorityIRQ_S -> if -> bflb_irq_attach | `bflb_irq_initialize` (3; 6) | `ranking-model-confusion` |
| 122 | `bouffalo-lhal`<br>`interrupt.enable` | `__ECLIC_EnableIRQ_S`<br>__ECLIC_EnableIRQ_S | `bflb_irq_enable` (3; 26) | `abstraction-level-mismatch` |
| 123 | `bouffalo-lhal`<br>`interrupt.disable` | `__ECLIC_DisableIRQ`<br>__ECLIC_DisableIRQ | `bflb_irq_disable` (3; 16) | `ranking-model-confusion` |
| 124 | `bouffalo-lhal`<br>`interrupt.register` | `interrupt_entry`<br>interrupt_entry -> if -> bflb_irq_attach | `bflb_irq_attach` (3; 2) | `ranking-model-confusion` |
| 125 | `bouffalo-lhal`<br>`uart.configure` | `UART_SetBaudRate`<br>UART_SetBaudRate | `bflb_uart_init` (3; 3) | `ranking-model-confusion` |
| 126 | `bouffalo-lhal`<br>`uart.write` | `UART_SendData`<br>UART_SendData | `bflb_uart_put` (3; 5)<br>`bflb_uart_put_block` (3; 4)<br>`bflb_uart_putchar` (2; 6) | `abstraction-level-mismatch` |
| 127 | `bouffalo-lhal`<br>`uart.read` | `UART_ReceiveData`<br>UART_ReceiveData | `bflb_uart_get` (3; 4)<br>`bflb_uart_getchar` (2; 5) | `abstraction-level-mismatch` |
| 128 | `bouffalo-lhal`<br>`gpio.configure` | `GLB_GPIO_Int_Init`<br>GLB_GPIO_Int_Init | `bflb_gpio_init` (3; 9) | `ranking-model-confusion` |
| 129 | `bouffalo-lhal`<br>`gpio.write` | `MD_GPIO_Write`<br>MD_GPIO_Write | `bflb_gpio_reset` (3; 6)<br>`bflb_gpio_set` (3; 2)<br>`bflb_gpio_pin0_31_output` (2; 13)<br>`bflb_gpio_pin0_31_reset` (2; 5)<br>`bflb_gpio_pin0_31_set` (2; 8)<br>`bflb_gpio_pin32_63_output` (2; 17)<br>`bflb_gpio_pin32_63_reset` (2; 32)<br>`bflb_gpio_pin32_63_set` (2; 30) | `ranking-model-confusion` |
| 130 | `bouffalo-lhal`<br>`gpio.read` | `MD_GPIO_Read`<br>MD_GPIO_Read | `bflb_gpio_read` (3; 2)<br>`bflb_gpio_pin0_31_read` (2; 12)<br>`bflb_gpio_pin32_63_read` (2; 8) | `ranking-model-confusion` |
| 131 | `bouffalo-lhal`<br>`timer.initialize` | `TIMER_Init`<br>TIMER_Init | `bflb_timer_init` (3; 2) | `ranking-model-confusion` |
| 132 | `bouffalo-lhal`<br>`timer.start` | `SysTimer_Start`<br>SysTimer_Start | `bflb_timer_start` (3; 3) | `ranking-model-confusion` |
| 133 | `bouffalo-lhal`<br>`timer.stop` | `SysTimer_Stop`<br>SysTimer_Stop | `bflb_timer_stop` (3; 2) | `ranking-model-confusion` |
| 134 | `bouffalo-lhal`<br>`timer.set_interval` | `SysTimer_SetCompareValue`<br>SysTimer_SetCompareValue -> SysTimer_SetHartCompareValue | `bflb_timer_set_compvalue` (3; 7)<br>`bflb_timer_set_preloadvalue` (3; 6) | `ranking-model-confusion` |
| 135 | `libopencm3-hal`<br>`clock.enable` | `rcc_rtc_clock_enable`<br>rcc_rtc_clock_enable | `rcc_periph_clock_enable` (3; 7) | `truth-path-missing` |
| 136 | `libopencm3-hal`<br>`interrupt.enable` | `NVIC_EnableIRQ`<br>NVIC_EnableIRQ | `nvic_enable_irq` (3; 2) | `same-family-operation-confusion` |
| 137 | `libopencm3-hal`<br>`interrupt.disable` | `NVIC_DisableIRQ`<br>NVIC_DisableIRQ | `nvic_disable_irq` (3; 2) | `same-family-operation-confusion` |
| 138 | `libopencm3-hal`<br>`gpio.read` | `gpio_read`<br>gpio_read | `gpio_get` (3; 2) | `same-family-operation-confusion` |
| 139 | `libopencm3-hal`<br>`timer.start` | `timer_start`<br>timer_start | `timer_enable_counter` (3; 4) | `truth-path-missing` |
| 140 | `libopencm3-hal`<br>`timer.stop` | `timer_stop`<br>timer_stop | `timer_disable_counter` (3; 3) | `truth-path-missing` |
| 141 | `alif-ensemble-dfp`<br>`clock.disable` | `disable_dphy_pll_reference_clock`<br>disable_dphy_pll_reference_clock | `SERVICES_clocks_enable_clock` (3; 76) | `ranking-model-confusion` |
| 142 | `alif-ensemble-dfp`<br>`gpio.write` | `gpio_set_direction_input`<br>gpio_set_direction_input | `gpio_bit_man_set_value_high` (2; 4)<br>`gpio_bit_man_set_value_low` (2; 5)<br>`gpio_set_value_high` (2; 6)<br>`gpio_set_value_low` (2; 2)<br>`GPIO_SetValue` (1; 25) | `same-family-operation-confusion` |
