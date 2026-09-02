# 寄存器效果图 PU 排序完整错误报告 v0.1

## 1. 报告口径

本报告使用 H02 和 `hardware-effect-pu-residual` 的跨独立组五折 out-of-fold 预测。每个查询只由未见过该 independence group 的模型预测。板卡外部诊断不并入本报告。

- 有效查询：281
- Top1 正确：94
- Top1 错误：187
- P@1：0.334520
- 完整机器可读记录：`experiments/operation-ranking/results-hardware-effect-pu-h02-v0.1-errors.json`

## 2. 主错误归因

归因是基于当前图证据的可复现诊断规则，不等同于人工确认的唯一根因。

| 主归因 | 错误数 | 占全部错误 |
| --- | ---: | ---: |
| `same-family-operation-confusion` | 61 | 32.6% |
| `ranking-model-confusion` | 59 | 31.6% |
| `truth-path-missing` | 33 | 17.6% |
| `abstraction-level-mismatch` | 16 | 8.6% |
| `composite-entry-overranked` | 10 | 5.3% |
| `effect-strength-confusion` | 6 | 3.2% |
| `example-overranked` | 1 | 0.5% |
| `internal-role-overranked` | 1 | 0.5% |

## 3. 按操作统计

| 操作 | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `timer.set_interval` | 18/20 | 90.0% |
| `clock.initialize` | 11/13 | 84.6% |
| `interrupt.enable` | 11/13 | 84.6% |
| `timer.start` | 16/20 | 80.0% |
| `timer.initialize` | 13/17 | 76.5% |
| `clock.disable` | 9/12 | 75.0% |
| `timer.stop` | 14/20 | 70.0% |
| `interrupt.disable` | 9/13 | 69.2% |
| `gpio.write` | 13/19 | 68.4% |
| `uart.read` | 13/19 | 68.4% |
| `gpio.read` | 12/19 | 63.2% |
| `clock.enable` | 7/12 | 58.3% |
| `uart.write` | 11/19 | 57.9% |
| `interrupt.register` | 4/7 | 57.1% |
| `clock.get_frequency` | 6/12 | 50.0% |
| `gpio.attach_irq` | 4/8 | 50.0% |
| `gpio.configure` | 7/16 | 43.8% |
| `uart.configure` | 7/17 | 41.2% |
| `interrupt.initialize` | 2/5 | 40.0% |

## 4. 按 SDK 统计

| SDK | 错误/总数 | 错误率 |
| --- | ---: | ---: |
| `telink-tlsr9-hal` | 10/11 | 90.9% |
| `libopencm3-hal` | 12/14 | 85.7% |
| `ti-mspm0-driverlib` | 12/14 | 85.7% |
| `nuclei-soc-sdk` | 13/16 | 81.2% |
| `nuvoton-std-driver` | 11/14 | 78.6% |
| `arduino-renesas-core` | 7/9 | 77.8% |
| `wch-ch32v307-stdperiph` | 12/16 | 75.0% |
| `nordic-nrfx-4.2.1` | 10/14 | 71.4% |
| `silabs-emlib` | 10/14 | 71.4% |
| `alif-ensemble-dfp` | 7/10 | 70.0% |
| `hpmicro-hpm-sdk` | 7/10 | 70.0% |
| `bouffalo-lhal` | 11/16 | 68.8% |
| `sifli-hal` | 11/16 | 68.8% |
| `renesas-fsp` | 12/18 | 66.7% |
| `ti-simplelink-f2` | 10/15 | 66.7% |
| `raspberry-pi-pico-sdk-2.2.0` | 11/18 | 61.1% |
| `espressif-esp-idf-6.0.1` | 9/16 | 56.2% |
| `nxp-mcuxpresso-sdk-2.16.100` | 7/19 | 36.8% |
| `sony-spresense-sdk` | 2/6 | 33.3% |
| `arm-mbed-hal` | 3/15 | 20.0% |

## 5. 代表性错误详解

### 5.1 `ti-mspm0-driverlib::clock.initialize`

- 系统 Top1：`DL_Timer_setClockConfig`，分数 7.664951。
- 系统效果路径：`DL_Timer_setClockConfig`。
- H02 真值：`DL_SYSCTL_configSYSPLL`(grade=3, rank=2), `DL_SYSCTL_setSYSOSCFreq`(grade=3, rank=5), `DL_SYSCTL_setHFCLKSourceHFCLKIN`(grade=2, rank=21), `DL_SYSCTL_setHFCLKSourceHFXT`(grade=2, rank=8), `DL_SYSCTL_setHFCLKSourceHFXTParams`(grade=2, rank=9), `DL_SYSCTL_setMCLKDivider`(grade=2, rank=19)。
- 主归因：`ranking-model-confusion`，现有图特征和 PU 权重不能区分两个相近候选。
- Top5：`DL_Timer_setClockConfig`(label=0, score=7.664951), `DL_SYSCTL_configSYSPLL`(label=3, score=6.755339), `DL_SYSCTL_setLFCLKSourceLFXT`(label=0, score=3.612847), `DL_Timer_initFourCCPWMMode`(label=0, score=3.184205), `DL_SYSCTL_setSYSOSCFreq`(label=3, score=2.510536)。

### 5.2 `ti-mspm0-driverlib::clock.enable`

- 系统 Top1：`DL_MCAN_isModuleClockEnabled`，分数 6.961464。
- 系统效果路径：`DL_MCAN_isModuleClockEnabled`。
- H02 真值：`DL_SYSCTL_enableMFCLK`(grade=3, rank=27), `DL_SYSCTL_enableMFPCLK`(grade=3, rank=25), `DL_SYSCTL_enableSYSPLL`(grade=3, rank=5)。
- 主归因：`truth-path-missing`，真值函数没有恢复出足够的目标操作效果路径。
- Top5：`DL_MCAN_isModuleClockEnabled`(label=0, score=6.961464), `DL_SYSCTL_enableExternalClock`(label=0, score=5.44888), `DRV8889Q1_setSPIRegisterLock`(label=0, score=3.067191), `HAL_processADCIRQ`(label=0, score=1.292182), `DL_SYSCTL_enableSYSPLL`(label=3, score=1.019102)。

### 5.3 `ti-mspm0-driverlib::interrupt.register`

- 系统 Top1：`DL_Interrupt_unregisterInterrupt`，分数 6.865724。
- 系统效果路径：`DL_Interrupt_unregisterInterrupt`。
- H02 真值：`DL_Interrupt_registerInterrupt`(grade=3, rank=2)。
- 主归因：`same-family-operation-confusion`，预测项与真值属于同一 API 家族，但动作或子操作不一致。
- Top5：`DL_Interrupt_unregisterInterrupt`(label=0, score=6.865724), `DL_Interrupt_registerInterrupt`(label=3, score=6.235536), `DRV8889Q1_spiUpdateRegister`(label=0, score=5.73288), `UARTMSP_interruptHandler`(label=0, score=5.199396), `DRV8706Q1_spiUpdateRegister`(label=0, score=4.66192)。

### 5.4 `ti-mspm0-driverlib::uart.configure`

- 系统 Top1：`UART_checkForCommand`，分数 6.660316。
- 系统效果路径：`UART_checkForCommand`。
- H02 真值：`DL_UART_init`(grade=3, rank=6)。
- 主归因：`composite-entry-overranked`，复合初始化或多能力入口的硬件效果过强。
- Top5：`UART_checkForCommand`(label=0, score=6.660316), `UART_init`(label=0, score=5.719585), `DL_UART_enablePower`(label=0, score=4.1267), `DL_UART_setExternalDriverSetup`(label=0, score=3.82077), `DL_UART_getExternalDriverSetup`(label=0, score=3.766978)。

### 5.5 `ti-mspm0-driverlib::uart.write`

- 系统 Top1：`UART_write`，分数 6.52279。
- 系统效果路径：`UART_write`。
- H02 真值：`DL_UART_transmitDataBlocking`(grade=3, rank=16), `DL_UART_fillTXFIFO`(grade=2, rank=30), `DL_UART_transmitData`(grade=2, rank=2)。
- 主归因：`abstraction-level-mismatch`，直接效果层与 H02 指定的可迁移 API 层级不一致。
- Top5：`UART_write`(label=0, score=6.52279), `DL_UART_transmitData`(label=2, score=6.262268), `UART_writeBufferedMode`(label=0, score=6.211197), `UART_sendBuffer`(label=0, score=6.045399), `DL_UART_setBaudRateDivisor`(label=0, score=5.822969)。

### 5.6 `ti-simplelink-f2::interrupt.disable`

- 系统 Top1：`IntDisable`，分数 9.455186。
- 系统效果路径：`IntDisable`。
- H02 真值：`TZ_NVIC_DisableIRQ_NS`(grade=3, rank=4)。
- 主归因：`effect-strength-confusion`，错误候选的寄存器效果强度压过了接口契约。
- Top5：`IntDisable`(label=0, score=9.455186), `GPTimerCC26XX_disableInterrupt`(label=0, score=5.874388), `__NVIC_DisableIRQ`(label=0, score=5.745231), `TZ_NVIC_DisableIRQ_NS`(label=3, score=5.745231), `OPT3001_disableInterrupt`(label=0, score=4.664481)。

### 5.7 `ti-simplelink-f2::timer.initialize`

- 系统 Top1：`platformAlarmMicroInit`，分数 7.145172。
- 系统效果路径：`platformAlarmMicroInit -> timer_create`。
- H02 真值：`GPTimerCC26XX_open`(grade=3, rank=6)。
- 主归因：`example-overranked`，示例或测试入口被排到 SDK 公共接口之前。
- Top5：`platformAlarmMicroInit`(label=0, score=7.145172), `platformAlarmInit`(label=0, score=7.145172), `osal_CbTimerInit`(label=0, score=6.556157), `sid_pal_timer_init`(label=0, score=6.26275), `zclTel_InfoSendConfigurePushInformationTimer`(label=0, score=6.182092)。

### 5.8 `espressif-esp-idf-6.0.1::interrupt.register`

- 系统 Top1：`touch_pad_isr_register`，分数 8.517358。
- 系统效果路径：`touch_pad_isr_register -> rtc_isr_register`。
- H02 真值：`esp_intr_alloc`(grade=3, rank=3), `esp_intr_alloc_intrstatus`(grade=3, rank=2)。
- 主归因：`internal-role-overranked`，内部 handler/callback/dispatch 角色被排到公共接口之前。
- Top5：`touch_pad_isr_register`(label=0, score=8.517358), `esp_intr_alloc_intrstatus`(label=3, score=8.227099), `esp_intr_alloc`(label=3, score=8.095065), `dma2d_register_rx_event_callbacks`(label=0, score=7.791611), `gptimer_register_event_callbacks`(label=0, score=7.765242)。

## 6. 全部 Top1 错误清单

真值排名来自该折完整唯一符号排序；每一行同时保留系统 Top1、效果路径以及全部 H02 正例。

| # | SDK / 操作 | 系统 Top1 | H02 真值（等级；排名） | 主归因 |
| ---: | --- | --- | --- | --- |
| 1 | `ti-mspm0-driverlib`<br>`clock.initialize` | `DL_Timer_setClockConfig`<br>DL_Timer_setClockConfig | `DL_SYSCTL_configSYSPLL` (3; 2)<br>`DL_SYSCTL_setSYSOSCFreq` (3; 5)<br>`DL_SYSCTL_setHFCLKSourceHFCLKIN` (2; 21)<br>`DL_SYSCTL_setHFCLKSourceHFXT` (2; 8)<br>`DL_SYSCTL_setHFCLKSourceHFXTParams` (2; 9)<br>`DL_SYSCTL_setMCLKDivider` (2; 19) | `ranking-model-confusion` |
| 2 | `ti-mspm0-driverlib`<br>`clock.enable` | `DL_MCAN_isModuleClockEnabled`<br>DL_MCAN_isModuleClockEnabled | `DL_SYSCTL_enableMFCLK` (3; 27)<br>`DL_SYSCTL_enableMFPCLK` (3; 25)<br>`DL_SYSCTL_enableSYSPLL` (3; 5) | `truth-path-missing` |
| 3 | `ti-mspm0-driverlib`<br>`clock.disable` | `DL_SYSCTL_disableExternalClock`<br>无路径 | `DL_SYSCTL_disableHFXT` (3; 3)<br>`DL_SYSCTL_disableMFCLK` (3; 10)<br>`DL_SYSCTL_disableMFPCLK` (3; 13)<br>`DL_SYSCTL_disableSYSPLL` (3; 5) | `truth-path-missing` |
| 4 | `ti-mspm0-driverlib`<br>`interrupt.register` | `DL_Interrupt_unregisterInterrupt`<br>DL_Interrupt_unregisterInterrupt | `DL_Interrupt_registerInterrupt` (3; 2) | `same-family-operation-confusion` |
| 5 | `ti-mspm0-driverlib`<br>`uart.configure` | `UART_checkForCommand`<br>UART_checkForCommand | `DL_UART_init` (3; 6) | `composite-entry-overranked` |
| 6 | `ti-mspm0-driverlib`<br>`uart.write` | `UART_write`<br>UART_write | `DL_UART_transmitDataBlocking` (3; 16)<br>`DL_UART_fillTXFIFO` (2; 30)<br>`DL_UART_transmitData` (2; 2) | `abstraction-level-mismatch` |
| 7 | `ti-mspm0-driverlib`<br>`uart.read` | `DL_UART_getClockConfig`<br>DL_UART_getClockConfig | `DL_UART_receiveDataBlocking` (3; 11)<br>`DL_UART_drainRXFIFO` (2; 37)<br>`DL_UART_receiveData` (2; 12) | `same-family-operation-confusion` |
| 8 | `ti-mspm0-driverlib`<br>`gpio.configure` | `DL_GPIO_initDigitalInputFeatures`<br>DL_GPIO_initDigitalInputFeatures | `DL_GPIO_initDigitalInput` (3; 16)<br>`DL_GPIO_initDigitalOutput` (3; 5) | `truth-path-missing` |
| 9 | `ti-mspm0-driverlib`<br>`gpio.write` | `GPIO_setConfigAndMux`<br>GPIO_setConfigAndMux | `DL_GPIO_clearPins` (3; 19)<br>`DL_GPIO_setPins` (3; 3)<br>`DL_GPIO_togglePins` (2; 24) | `composite-entry-overranked` |
| 10 | `ti-mspm0-driverlib`<br>`gpio.read` | `HAL_readGPIOVal`<br>HAL_readGPIOVal | `DL_GPIO_readPins` (3; 15) | `truth-path-missing` |
| 11 | `ti-mspm0-driverlib`<br>`timer.initialize` | `DL_Timer_initCompareMode`<br>DL_Timer_initCompareMode | `DL_TimerB_initTimer` (3; 4)<br>`DL_Timer_initTimerMode` (3; 11) | `same-family-operation-confusion` |
| 12 | `ti-mspm0-driverlib`<br>`timer.set_interval` | `DL_I2C_setTimerPeriod`<br>DL_I2C_setTimerPeriod | `DL_TimerB_setLoadValue` (3; 10)<br>`DL_Timer_setLoadValue` (3; 16) | `truth-path-missing` |
| 13 | `ti-simplelink-f2`<br>`clock.enable` | `PowerCC26X2_oscIsHPOSCEnabledWithHfDerivedLfClock`<br>PowerCC26X2_oscIsHPOSCEnabledWithHfDerivedLfClock -> OSC_IsHPOSCEnabledWithHfDerivedLfClock | `Power_setDependency` (2; 9) | `truth-path-missing` |
| 14 | `ti-simplelink-f2`<br>`clock.disable` | `PRCMAudioClockDisable`<br>PRCMAudioClockDisable | `Power_releaseDependency` (2; 29) | `ranking-model-confusion` |
| 15 | `ti-simplelink-f2`<br>`interrupt.enable` | `ARM_PMU_Set_CNTR_IRQ_Enable`<br>无路径 | `TZ_NVIC_EnableIRQ_NS` (3; 4) | `ranking-model-confusion` |
| 16 | `ti-simplelink-f2`<br>`interrupt.disable` | `IntDisable`<br>IntDisable | `TZ_NVIC_DisableIRQ_NS` (3; 4) | `effect-strength-confusion` |
| 17 | `ti-simplelink-f2`<br>`uart.configure` | `platformDebugUartInit`<br>platformDebugUartInit | `UART2_open` (3; 2) | `composite-entry-overranked` |
| 18 | `ti-simplelink-f2`<br>`gpio.read` | `GPIO_getConfig`<br>GPIO_getConfig | `GPIO_read` (3; 2) | `same-family-operation-confusion` |
| 19 | `ti-simplelink-f2`<br>`timer.initialize` | `platformAlarmMicroInit`<br>platformAlarmMicroInit -> timer_create | `GPTimerCC26XX_open` (3; 6) | `example-overranked` |
| 20 | `ti-simplelink-f2`<br>`timer.start` | `OsalPortTimers_startTimer`<br>OsalPortTimers_startTimer -> createTimerEntry | `GPTimerCC26XX_start` (3; 8) | `effect-strength-confusion` |
| 21 | `ti-simplelink-f2`<br>`timer.stop` | `port_timerStop`<br>port_timerStop -> timer_settime | `GPTimerCC26XX_stop` (3; 5) | `ranking-model-confusion` |
| 22 | `ti-simplelink-f2`<br>`timer.set_interval` | `ICall_getTickPeriod`<br>ICall_getTickPeriod | `GPTimerCC26XX_setLoadValue` (3; 4)<br>`GPTimerCC26XX_setMatchValue` (3; 6) | `abstraction-level-mismatch` |
| 23 | `arm-mbed-hal`<br>`clock.initialize` | `CLOCK_SetSimConfig`<br>CLOCK_SetSimConfig | `SystemInit` (2; 3)<br>`mbed_sdk_init` (2; 2) | `abstraction-level-mismatch` |
| 24 | `arm-mbed-hal`<br>`interrupt.register` | `whd_bus_irq_register`<br>whd_bus_irq_register | `NVIC_SetVector` (3; 2) | `ranking-model-confusion` |
| 25 | `arm-mbed-hal`<br>`timer.start` | `HAL_HRTIM_SimpleOnePulseStart`<br>HAL_HRTIM_SimpleOnePulseStart | `lp_ticker_set_interrupt` (3; 27)<br>`us_ticker_set_interrupt` (3; 2) | `abstraction-level-mismatch` |
| 26 | `telink-tlsr9-hal`<br>`clock.initialize` | `s7816_init`<br>s7816_init | `clock_init` (3; 2) | `ranking-model-confusion` |
| 27 | `telink-tlsr9-hal`<br>`interrupt.enable` | `plic_enter_critical_sec`<br>plic_enter_critical_sec | `core_interrupt_enable` (3; 47)<br>`plic_interrupt_enable` (3; 3) | `truth-path-missing` |
| 28 | `telink-tlsr9-hal`<br>`interrupt.disable` | `plic_enter_critical_sec`<br>plic_enter_critical_sec | `core_interrupt_disable` (3; 3)<br>`plic_interrupt_disable` (3; 2) | `truth-path-missing` |
| 29 | `telink-tlsr9-hal`<br>`uart.configure` | `uart_cts_config`<br>无路径 | `uart_init` (3; 32) | `same-family-operation-confusion` |
| 30 | `telink-tlsr9-hal`<br>`uart.read` | `uart_get_txfifo_num`<br>无路径 | `uart_read_byte` (3; 2) | `truth-path-missing` |
| 31 | `telink-tlsr9-hal`<br>`gpio.write` | `uart_set_rtx_pin`<br>uart_set_rtx_pin | `gpio_set_level` (3; 17)<br>`gpio_set_high_level` (2; 28)<br>`gpio_set_low_level` (2; 4)<br>`gpio_toggle` (2; 30) | `abstraction-level-mismatch` |
| 32 | `telink-tlsr9-hal`<br>`gpio.read` | `gpio_read_cache`<br>无路径 | `gpio_get_level` (3; 3)<br>`gpio_get_level_all` (2; 2) | `same-family-operation-confusion` |
| 33 | `telink-tlsr9-hal`<br>`timer.start` | `clock_get_32k_tick`<br>clock_get_32k_tick | `stimer_set_irq_capture` (3; 32)<br>`timer_start` (3; 8) | `truth-path-missing` |
| 34 | `telink-tlsr9-hal`<br>`timer.stop` | `pm_sleep_wakeup`<br>pm_sleep_wakeup | `timer_stop` (3; 6) | `truth-path-missing` |
| 35 | `telink-tlsr9-hal`<br>`timer.set_interval` | `clock_set_32k_tick`<br>clock_set_32k_tick | `stimer_set_irq_capture` (3; 20) | `truth-path-missing` |
| 36 | `renesas-fsp`<br>`clock.enable` | `R_GPT_OutputEnable`<br>无路径 | `R_CGC_ClockStart` (3; 2) | `ranking-model-confusion` |
| 37 | `renesas-fsp`<br>`interrupt.initialize` | `usb_hdriver_init`<br>usb_hdriver_init | `R_BSP_IrqCfg` (2; 2) | `truth-path-missing` |
| 38 | `renesas-fsp`<br>`interrupt.enable` | `R_BSP_IrqEnableNoClear`<br>R_BSP_IrqEnableNoClear | `R_BSP_IrqCfgEnable` (3; 4)<br>`R_BSP_IrqEnable` (3; 2) | `same-family-operation-confusion` |
| 39 | `renesas-fsp`<br>`uart.write` | `usb_hstd_write_data`<br>usb_hstd_write_data | `R_SCI_B_UART_Write` (3; 9)<br>`R_SCI_UART_Write` (3; 13) | `composite-entry-overranked` |
| 40 | `renesas-fsp`<br>`uart.read` | `r_sci_b_lin_clock_freq_get`<br>r_sci_b_lin_clock_freq_get | `R_SCI_B_UART_Read` (3; 14)<br>`R_SCI_UART_Read` (3; 10) | `same-family-operation-confusion` |
| 41 | `renesas-fsp`<br>`gpio.write` | `R_BSP_PinWrite`<br>R_BSP_PinWrite | `R_IOPORT_PinWrite` (3; 5) | `effect-strength-confusion` |
| 42 | `renesas-fsp`<br>`gpio.read` | `R_IOPORT_PinEventInputRead`<br>R_IOPORT_PinEventInputRead | `R_IOPORT_PinRead` (3; 12) | `same-family-operation-confusion` |
| 43 | `renesas-fsp`<br>`gpio.attach_irq` | `ptxPLAT_GPIO_DisableInterrupt`<br>ptxPLAT_GPIO_DisableInterrupt | `R_ICU_ExternalIrqCallbackSet` (3; 20)<br>`R_ICU_ExternalIrqOpen` (3; 12)<br>`R_ICU_ExternalIrqEnable` (1; 17) | `abstraction-level-mismatch` |
| 44 | `renesas-fsp`<br>`timer.initialize` | `ptxPLAT_TIMER_GetInitializedTimer`<br>ptxPLAT_TIMER_GetInitializedTimer | `R_AGT_Open` (3; 8)<br>`R_GPT_Open` (3; 6) | `abstraction-level-mismatch` |
| 45 | `renesas-fsp`<br>`timer.start` | `R_GPT_OutputEnable`<br>无路径 | `R_AGT_Start` (3; 12)<br>`R_GPT_Start` (3; 25) | `same-family-operation-confusion` |
| 46 | `renesas-fsp`<br>`timer.stop` | `R_GPT_OutputDisable`<br>无路径 | `R_AGT_Stop` (3; 13)<br>`R_GPT_Stop` (3; 2) | `same-family-operation-confusion` |
| 47 | `renesas-fsp`<br>`timer.set_interval` | `ptxPLAT_TIMER_GetInitializedTimer`<br>ptxPLAT_TIMER_GetInitializedTimer | `R_AGT_PeriodSet` (3; 11)<br>`R_GPT_PeriodSet` (3; 16) | `ranking-model-confusion` |
| 48 | `wch-ch32v307-stdperiph`<br>`clock.initialize` | `RCC_BackupResetCmd`<br>RCC_BackupResetCmd | `RCC_PLLConfig` (3; 14)<br>`RCC_SYSCLKConfig` (3; 6)<br>`RCC_HSEConfig` (2; 4) | `same-family-operation-confusion` |
| 49 | `wch-ch32v307-stdperiph`<br>`clock.enable` | `RCC_APB1PeriphResetCmd`<br>RCC_APB1PeriphResetCmd | `RCC_AHBPeriphClockCmd` (3; 18)<br>`RCC_APB1PeriphClockCmd` (3; 21)<br>`RCC_APB2PeriphClockCmd` (3; 3) | `same-family-operation-confusion` |
| 50 | `wch-ch32v307-stdperiph`<br>`clock.disable` | `RCC_APB1PeriphResetCmd`<br>RCC_APB1PeriphResetCmd | `RCC_AHBPeriphClockCmd` (3; 29)<br>`RCC_APB1PeriphClockCmd` (3; 32)<br>`RCC_APB2PeriphClockCmd` (3; 15) | `same-family-operation-confusion` |
| 51 | `wch-ch32v307-stdperiph`<br>`uart.configure` | `USART_StructInit`<br>USART_StructInit | `USART_Init` (3; 3) | `same-family-operation-confusion` |
| 52 | `wch-ch32v307-stdperiph`<br>`uart.write` | `USART_SetAddress`<br>USART_SetAddress | `USART_SendData` (3; 14) | `same-family-operation-confusion` |
| 53 | `wch-ch32v307-stdperiph`<br>`uart.read` | `USART_GetITStatus`<br>USART_GetITStatus | `USART_ReceiveData` (3; 12) | `truth-path-missing` |
| 54 | `wch-ch32v307-stdperiph`<br>`gpio.write` | `GPIO_EXTILineConfig`<br>GPIO_EXTILineConfig | `GPIO_WriteBit` (3; 2)<br>`GPIO_ResetBits` (2; 3)<br>`GPIO_SetBits` (2; 4)<br>`GPIO_Write` (2; 7) | `same-family-operation-confusion` |
| 55 | `wch-ch32v307-stdperiph`<br>`gpio.read` | `GPIO_ReadOutputDataBit`<br>无路径 | `GPIO_ReadInputDataBit` (3; 2)<br>`GPIO_ReadInputData` (2; 5) | `truth-path-missing` |
| 56 | `wch-ch32v307-stdperiph`<br>`timer.initialize` | `TIM_OCStructInit`<br>TIM_OCStructInit | `TIM_TimeBaseInit` (3; 31) | `same-family-operation-confusion` |
| 57 | `wch-ch32v307-stdperiph`<br>`timer.start` | `TIM_ITRxExternalClockConfig`<br>TIM_ITRxExternalClockConfig | `TIM_Cmd` (3; 15) | `same-family-operation-confusion` |
| 58 | `wch-ch32v307-stdperiph`<br>`timer.stop` | `CAN_GetLSBTransmitErrorCounter`<br>CAN_GetLSBTransmitErrorCounter | `TIM_Cmd` (3; 26) | `ranking-model-confusion` |
| 59 | `wch-ch32v307-stdperiph`<br>`timer.set_interval` | `TIM_SetIC1Prescaler`<br>TIM_SetIC1Prescaler | `TIM_SetAutoreload` (3; 9)<br>`TIM_SetCompare1` (2; 10)<br>`TIM_SetCompare2` (2; 12)<br>`TIM_SetCompare3` (2; 11)<br>`TIM_SetCompare4` (2; 13) | `truth-path-missing` |
| 60 | `arduino-renesas-core`<br>`interrupt.enable` | `linkGPTimerIrq`<br>linkGPTimerIrq | `interrupts` (2; 58) | `truth-path-missing` |
| 61 | `arduino-renesas-core`<br>`interrupt.disable` | `linkGPTimerIrq`<br>linkGPTimerIrq | `noInterrupts` (2; 60) | `truth-path-missing` |
| 62 | `arduino-renesas-core`<br>`uart.read` | `UART::cfg_pins`<br>UART::cfg_pins | `UART::read` (3; 46) | `truth-path-missing` |
| 63 | `arduino-renesas-core`<br>`timer.initialize` | `FspTimer::get_cfg_for_irq`<br>FspTimer::get_cfg_for_irq | `FspTimer::begin` (3; 8) | `same-family-operation-confusion` |
| 64 | `arduino-renesas-core`<br>`timer.start` | `FspTimer::setup_overflow_irq`<br>FspTimer::setup_overflow_irq -> FspTimer::start | `FspTimer::start` (3; 4) | `same-family-operation-confusion` |
| 65 | `arduino-renesas-core`<br>`timer.stop` | `FspTimer::get_cfg_for_irq`<br>FspTimer::get_cfg_for_irq | `FspTimer::stop` (3; 25) | `same-family-operation-confusion` |
| 66 | `arduino-renesas-core`<br>`timer.set_interval` | `PwmOut::begin`<br>PwmOut::begin | `FspTimer::set_period` (3; 27) | `abstraction-level-mismatch` |
| 67 | `silabs-emlib`<br>`clock.initialize` | `CMU_USBPLLInit`<br>CMU_USBPLLInit | `CMU_ClockSelectSet` (3; 4) | `effect-strength-confusion` |
| 68 | `silabs-emlib`<br>`clock.disable` | `sli_em_cmu_SYSCLKInitPreClockSelect`<br>sli_em_cmu_SYSCLKInitPreClockSelect -> EMU_VScaleEM01 | `CMU_ClockEnable` (3; 32) | `ranking-model-confusion` |
| 69 | `silabs-emlib`<br>`clock.get_frequency` | `CMU_ClockSelectGet`<br>CMU_ClockSelectGet | `CMU_ClockFreqGet` (3; 3) | `same-family-operation-confusion` |
| 70 | `silabs-emlib`<br>`uart.write` | `USART_BaudrateGet`<br>USART_BaudrateGet | `USART_Tx` (3; 10)<br>`USART_TxDouble` (2; 12)<br>`USART_TxExt` (2; 11) | `same-family-operation-confusion` |
| 71 | `silabs-emlib`<br>`uart.read` | `USART_BaudrateGet`<br>USART_BaudrateGet | `USART_Rx` (3; 5)<br>`USART_RxDataGet` (2; 15)<br>`USART_RxDouble` (2; 3) | `same-family-operation-confusion` |
| 72 | `silabs-emlib`<br>`gpio.read` | `GPIO_PortInGet`<br>GPIO_PortInGet | `GPIO_PinInGet` (3; 9) | `same-family-operation-confusion` |
| 73 | `silabs-emlib`<br>`timer.initialize` | `MSC_Init`<br>MSC_Init | `TIMER_Init` (3; 2) | `ranking-model-confusion` |
| 74 | `silabs-emlib`<br>`timer.start` | `CMU_OscillatorEnable`<br>无路径 | `TIMER_Enable` (3; 4) | `ranking-model-confusion` |
| 75 | `silabs-emlib`<br>`timer.stop` | `TIMER_EnableDTI`<br>TIMER_EnableDTI | `TIMER_Enable` (3; 3) | `same-family-operation-confusion` |
| 76 | `silabs-emlib`<br>`timer.set_interval` | `TIMER_SyncWait`<br>TIMER_SyncWait | `TIMER_TopSet` (3; 27) | `same-family-operation-confusion` |
| 77 | `nxp-mcuxpresso-sdk-2.16.100`<br>`clock.disable` | `CLOCK_SetPbeMode`<br>CLOCK_SetPbeMode -> CLOCK_EnablePll0 | `CLOCK_DisableClock` (3; 2)<br>`CLOCK_DisableAnalogClock` (2; 13)<br>`CLOCK_DisableUsbDevicefs0Clock` (2; 8)<br>`CLOCK_DisableUsbHs0DeviceClock` (2; 4)<br>`CLOCK_DisableUsbHs0HostClock` (2; 3)<br>`CLOCK_DisableUsbHs0PhyPllClock` (2; 19) | `same-family-operation-confusion` |
| 78 | `nxp-mcuxpresso-sdk-2.16.100`<br>`interrupt.enable` | `EnableGlobalIRQ`<br>EnableGlobalIRQ | `EnableIRQ` (3; 7)<br>`EnableIRQWithPriority` (3; 16)<br>`IRQ_Enable` (3; 9)<br>`IRQ_EnableInterrupt` (3; 8) | `ranking-model-confusion` |
| 79 | `nxp-mcuxpresso-sdk-2.16.100`<br>`interrupt.disable` | `INTMUX_DisableInterrupt`<br>INTMUX_DisableInterrupt | `DisableIRQ` (3; 6) | `truth-path-missing` |
| 80 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.configure` | `HAL_GpioInit`<br>HAL_GpioInit -> GPIO_PinInit | `GPIO_PinInit` (3; 2)<br>`GPIO_PortInit` (1; 5) | `ranking-model-confusion` |
| 81 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.write` | `HAL_GpioSetOutput`<br>HAL_GpioSetOutput -> GPIO_PinWrite | `GPIO_PinWrite` (3; 2)<br>`GPIO_PortClear` (2; 16)<br>`GPIO_PortSet` (2; 19)<br>`GPIO_PortToggle` (2; 15) | `ranking-model-confusion` |
| 82 | `nxp-mcuxpresso-sdk-2.16.100`<br>`gpio.attach_irq` | `PINT_PinInterruptClrStatus`<br>PINT_PinInterruptClrStatus | `PINT_PinInterruptConfig` (3; 6)<br>`GPIO_PinSetInterruptConfig` (1; 29) | `same-family-operation-confusion` |
| 83 | `nxp-mcuxpresso-sdk-2.16.100`<br>`timer.initialize` | `CTIMER_SetupMatch`<br>CTIMER_SetupMatch | `CTIMER_Init` (3; 8)<br>`FTM_Init` (2; 5)<br>`LPTMR_Init` (2; 17)<br>`QTMR_Init` (2; 6)<br>`SCTIMER_Init` (2; 3) | `same-family-operation-confusion` |
| 84 | `sony-spresense-sdk`<br>`clock.get_frequency` | `cxd56_get_clock`<br>cxd56_get_clock | `clock_getcpubaseclock` (3; 6) | `ranking-model-confusion` |
| 85 | `sony-spresense-sdk`<br>`timer.set_interval` | `StepCounterClass`<br>StepCounterClass | `timer_settimeout` (2; 4) | `truth-path-missing` |
| 86 | `sifli-hal`<br>`clock.initialize` | `HAL_RCC_ResetModule`<br>HAL_RCC_ResetModule | `HAL_RCC_Init` (3; 10) | `same-family-operation-confusion` |
| 87 | `sifli-hal`<br>`clock.disable` | `HAL_RCC_LCPU_ClockSelect`<br>HAL_RCC_LCPU_ClockSelect | `HAL_RCC_DisableModule` (3; 2)<br>`HAL_RCC_HCPU_DisableDLL1` (3; 15)<br>`HAL_RCC_HCPU_DisableDLL2` (3; 17) | `same-family-operation-confusion` |
| 88 | `sifli-hal`<br>`interrupt.enable` | `HAL_FLASH_ENABLE_QSPI`<br>无路径 | `HAL_NVIC_EnableIRQ` (3; 12) | `ranking-model-confusion` |
| 89 | `sifli-hal`<br>`interrupt.disable` | `HAL_MATH_DisableInterrupt`<br>无路径 | `HAL_NVIC_DisableIRQ` (3; 3) | `ranking-model-confusion` |
| 90 | `sifli-hal`<br>`uart.write` | `ll_usart_clear_flag_cts`<br>ll_usart_clear_flag_cts | `HAL_UART_Transmit` (3; 6)<br>`HAL_UART_Transmit_DMA` (2; 9)<br>`HAL_UART_Transmit_IT` (2; 21) | `ranking-model-confusion` |
| 91 | `sifli-hal`<br>`uart.read` | `HAL_UART_GetState`<br>HAL_UART_GetState | `HAL_UART_Receive` (3; 2)<br>`HAL_UART_Receive_DMA` (2; 9)<br>`HAL_UART_Receive_IT` (2; 21) | `same-family-operation-confusion` |
| 92 | `sifli-hal`<br>`gpio.configure` | `ll_pinmux_config_drive`<br>ll_pinmux_config_drive | `HAL_GPIO_Init` (3; 11) | `ranking-model-confusion` |
| 93 | `sifli-hal`<br>`gpio.write` | `HAL_HPAON_QueryWakeupPin`<br>HAL_HPAON_QueryWakeupPin | `HAL_GPIO_WritePin` (3; 9)<br>`HAL_GPIO_TogglePin` (2; 34) | `ranking-model-confusion` |
| 94 | `sifli-hal`<br>`timer.initialize` | `HAL_SD_InitCard`<br>HAL_SD_InitCard | `HAL_LPTIM_Init` (3; 6) | `composite-entry-overranked` |
| 95 | `sifli-hal`<br>`timer.stop` | `HAL_GPT_Encoder_Stop_IT`<br>HAL_GPT_Encoder_Stop_IT | `HAL_LPTIM_Counter_Stop` (3; 9)<br>`HAL_LPTIM_Counter_Stop_IT` (2; 5) | `composite-entry-overranked` |
| 96 | `sifli-hal`<br>`timer.set_interval` | `HAL_LPTIM_ReadCompare`<br>无路径 | `HAL_LPTIM_PWM_Set_Period` (3; 11) | `same-family-operation-confusion` |
| 97 | `nuvoton-std-driver`<br>`clock.initialize` | `CLK_SetModuleClock`<br>CLK_SetModuleClock | `CLK_SetBusClock` (3; 8)<br>`CLK_SetCoreClock` (3; 2) | `same-family-operation-confusion` |
| 98 | `nuvoton-std-driver`<br>`clock.get_frequency` | `CLK_GetPLLClockFreq`<br>CLK_GetPLLClockFreq | `CLK_GetCPUFreq` (3; 15)<br>`CLK_GetHCLKFreq` (3; 13)<br>`CLK_GetPCLK0Freq` (3; 7)<br>`CLK_GetPCLK1Freq` (3; 2)<br>`CLK_GetPCLK2Freq` (3; 8)<br>`CLK_GetPCLK3Freq` (3; 9)<br>`CLK_GetPCLK4Freq` (3; 3)<br>`CLK_GetPCLK5Freq` (3; 25) | `same-family-operation-confusion` |
| 99 | `nuvoton-std-driver`<br>`uart.write` | `SendChar_ToUART`<br>SendChar_ToUART | `LPUART_Write` (3; 6)<br>`UART_Write` (3; 5)<br>`UUART_Write` (3; 9) | `ranking-model-confusion` |
| 100 | `nuvoton-std-driver`<br>`uart.read` | `LPUART_RS485_GET_ADDR_FLAG`<br>无路径 | `LPUART_Read` (3; 14)<br>`UART_Read` (3; 13)<br>`UUART_Read` (3; 26) | `ranking-model-confusion` |
| 101 | `nuvoton-std-driver`<br>`gpio.configure` | `PSIO_SWITCH_MODE`<br>PSIO_SWITCH_MODE | `GPIO_SetMode` (3; 4) | `ranking-model-confusion` |
| 102 | `nuvoton-std-driver`<br>`gpio.write` | `GPIO_SetSlewCtl`<br>GPIO_SetSlewCtl | `GPIO_SET_OUT_DATA` (2; 3) | `truth-path-missing` |
| 103 | `nuvoton-std-driver`<br>`gpio.read` | `TPWM_CNTR_SYNC_START_BY_TIMER0`<br>TPWM_CNTR_SYNC_START_BY_TIMER0 | `GPIO_GET_IN_DATA` (2; 4) | `truth-path-missing` |
| 104 | `nuvoton-std-driver`<br>`timer.initialize` | `TIMER_Delay`<br>TIMER_Delay | `TIMER_Open` (3; 4) | `same-family-operation-confusion` |
| 105 | `nuvoton-std-driver`<br>`timer.start` | `TIMER_EnableCaptureInputNoiseFilter`<br>TIMER_EnableCaptureInputNoiseFilter | `TIMER_Start` (3; 4) | `same-family-operation-confusion` |
| 106 | `nuvoton-std-driver`<br>`timer.stop` | `TIMER_DisableInt`<br>TIMER_DisableInt | `TIMER_Stop` (3; 5) | `same-family-operation-confusion` |
| 107 | `nuvoton-std-driver`<br>`timer.set_interval` | `RTC_SetTickPeriod`<br>RTC_SetTickPeriod | `TIMER_SET_CMP_VALUE` (3; 3) | `ranking-model-confusion` |
| 108 | `raspberry-pi-pico-sdk-2.2.0`<br>`clock.initialize` | `pll_init`<br>pll_init | `clock_configure` (3; 5)<br>`clocks_init` (3; 21)<br>`set_sys_clock_48mhz` (2; 9)<br>`set_sys_clock_hz` (2; 17)<br>`set_sys_clock_pll` (2; 2) | `abstraction-level-mismatch` |
| 109 | `raspberry-pi-pico-sdk-2.2.0`<br>`clock.enable` | `pll_init`<br>pll_init | `clock_configure` (2; 2) | `abstraction-level-mismatch` |
| 110 | `raspberry-pi-pico-sdk-2.2.0`<br>`interrupt.enable` | `irq_is_enabled`<br>irq_is_enabled | `irq_set_enabled` (3; 2)<br>`irq_set_mask_enabled` (3; 17)<br>`TZ_NVIC_EnableIRQ_NS` (1; 7) | `same-family-operation-confusion` |
| 111 | `raspberry-pi-pico-sdk-2.2.0`<br>`interrupt.register` | `__NVIC_SetVector`<br>__NVIC_SetVector | `irq_add_shared_handler` (3; 8)<br>`irq_set_exclusive_handler` (3; 16) | `abstraction-level-mismatch` |
| 112 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.configure` | `setup_default_uart`<br>setup_default_uart -> uart_init | `uart_init` (3; 4)<br>`uart_set_baudrate` (1; 8)<br>`uart_set_format` (1; 3) | `composite-entry-overranked` |
| 113 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.write` | `uart_set_irqs_enabled`<br>uart_set_irqs_enabled | `uart_write_blocking` (3; 4)<br>`uart_putc` (2; 10)<br>`uart_putc_raw` (2; 13)<br>`uart_puts` (2; 21) | `same-family-operation-confusion` |
| 114 | `raspberry-pi-pico-sdk-2.2.0`<br>`uart.read` | `uart_get_hw`<br>uart_get_hw | `uart_read_blocking` (3; 3)<br>`uart_getc` (2; 20) | `same-family-operation-confusion` |
| 115 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.initialize` | `timer_hardware_alarm_set_target`<br>timer_hardware_alarm_set_target | `alarm_pool_create` (2; 11)<br>`alarm_pool_create_with_unused_hardware_alarm` (2; 19)<br>`hardware_alarm_claim` (1; 23)<br>`hardware_alarm_claim_unused` (1; 15) | `abstraction-level-mismatch` |
| 116 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.start` | `powman_timer_enable_alarm_at_ms`<br>powman_timer_enable_alarm_at_ms | `add_alarm_at` (3; 12)<br>`add_alarm_in_ms` (3; 14)<br>`add_alarm_in_us` (3; 13)<br>`add_repeating_timer_ms` (3; 24)<br>`add_repeating_timer_us` (3; 4)<br>`hardware_alarm_set_target` (3; 6) | `abstraction-level-mismatch` |
| 117 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.stop` | `aon_timer_get_irq_num`<br>无路径 | `cancel_alarm` (3; 6)<br>`cancel_repeating_timer` (3; 18)<br>`hardware_alarm_cancel` (3; 31) | `ranking-model-confusion` |
| 118 | `raspberry-pi-pico-sdk-2.2.0`<br>`timer.set_interval` | `cancel_alarm`<br>cancel_alarm -> alarm_pool_cancel_alarm | `add_repeating_timer_ms` (3; 42)<br>`add_repeating_timer_us` (3; 8)<br>`add_alarm_at` (2; 21)<br>`add_alarm_in_ms` (2; 31)<br>`add_alarm_in_us` (2; 30)<br>`hardware_alarm_set_target` (2; 5) | `ranking-model-confusion` |
| 119 | `nordic-nrfx-4.2.1`<br>`clock.initialize` | `nrf_clock_hfclkaudio_config_set`<br>nrf_clock_hfclkaudio_config_set | `nrfx_clock_hfclk_init` (3; 18)<br>`nrfx_clock_init` (3; 19)<br>`nrfx_clock_lfclk_init` (3; 32) | `ranking-model-confusion` |
| 120 | `nordic-nrfx-4.2.1`<br>`clock.enable` | `nrf_clock_config_reset_enable_set`<br>nrf_clock_config_reset_enable_set | `nrfx_clock_enable` (3; 8)<br>`nrfx_clock_hfclk_start` (2; 5)<br>`nrfx_clock_lfclk_start` (2; 11) | `abstraction-level-mismatch` |
| 121 | `nordic-nrfx-4.2.1`<br>`clock.disable` | `nrf_clock_int_disable`<br>无路径 | `nrfx_clock_disable` (3; 5)<br>`nrfx_clock_hfclk_stop` (2; 2)<br>`nrfx_clock_lfclk_stop` (2; 3) | `ranking-model-confusion` |
| 122 | `nordic-nrfx-4.2.1`<br>`uart.write` | `nrfx_uart_rx`<br>nrfx_uart_rx | `nrfx_uart_tx` (3; 2)<br>`nrfx_uarte_tx` (3; 50)<br>`nrfx_uarte_tx_abort` (1; 60) | `same-family-operation-confusion` |
| 123 | `nordic-nrfx-4.2.1`<br>`uart.read` | `nrf_uart_errorsrc_get_and_clear`<br>无路径 | `nrfx_uart_rx` (3; 7)<br>`nrfx_uarte_rx_enable` (1; 62) | `ranking-model-confusion` |
| 124 | `nordic-nrfx-4.2.1`<br>`gpio.configure` | `nrfx_nfct_init`<br>nrfx_nfct_init | `nrfx_gpiote_input_configure` (3; 12)<br>`nrfx_gpiote_output_configure` (3; 14)<br>`nrfx_gpiote_init` (1; 30) | `abstraction-level-mismatch` |
| 125 | `nordic-nrfx-4.2.1`<br>`gpio.write` | `nrf_spim_pins_set`<br>nrf_spim_pins_set | `nrfx_gpiote_out_clear` (3; 45)<br>`nrfx_gpiote_out_set` (3; 17)<br>`nrfx_gpiote_out_toggle` (2; 44) | `ranking-model-confusion` |
| 126 | `nordic-nrfx-4.2.1`<br>`gpio.read` | `nrf_gpio_pin_read`<br>nrf_gpio_pin_read | `nrfx_gpiote_in_is_set` (3; 56) | `ranking-model-confusion` |
| 127 | `nordic-nrfx-4.2.1`<br>`timer.start` | `nrf_grtc_sys_counter_cc_enable_check`<br>无路径 | `nrfx_timer_enable` (3; 6) | `ranking-model-confusion` |
| 128 | `nordic-nrfx-4.2.1`<br>`timer.set_interval` | `nrf_rtc_compare_event_get`<br>nrf_rtc_compare_event_get | `nrfx_timer_compare` (3; 23)<br>`nrfx_timer_extended_compare` (3; 21) | `ranking-model-confusion` |
| 129 | `nuclei-soc-sdk`<br>`clock.initialize` | `usb_host_init`<br>usb_host_init | `SystemInit` (3; 37) | `composite-entry-overranked` |
| 130 | `nuclei-soc-sdk`<br>`clock.get_frequency` | `rcu_clock_freq_get`<br>rcu_clock_freq_get | `get_cpu_freq` (3; 3)<br>`SystemCoreClockUpdate` (1; 4) | `ranking-model-confusion` |
| 131 | `nuclei-soc-sdk`<br>`interrupt.initialize` | `CLINT_Interrupt_Init`<br>无路径 | `ECLIC_Init` (3; 61) | `truth-path-missing` |
| 132 | `nuclei-soc-sdk`<br>`interrupt.enable` | `adc_interrupt_enable`<br>adc_interrupt_enable | `eclic_global_interrupt_enable` (3; 9)<br>`eclic_irq_enable` (3; 4) | `effect-strength-confusion` |
| 133 | `nuclei-soc-sdk`<br>`interrupt.disable` | `adc_interrupt_disable`<br>adc_interrupt_disable | `eclic_global_interrupt_disable` (3; 11)<br>`eclic_irq_disable` (3; 10) | `effect-strength-confusion` |
| 134 | `nuclei-soc-sdk`<br>`uart.configure` | `usart_parity_config`<br>usart_parity_config | `uart_init` (3; 4) | `ranking-model-confusion` |
| 135 | `nuclei-soc-sdk`<br>`uart.write` | `usart_transmit_config`<br>usart_transmit_config | `uart_write` (3; 4)<br>`usart_data_transmit` (3; 7) | `same-family-operation-confusion` |
| 136 | `nuclei-soc-sdk`<br>`uart.read` | `usart_receive_config`<br>usart_receive_config | `uart_read` (3; 6)<br>`usart_data_receive` (3; 2) | `same-family-operation-confusion` |
| 137 | `nuclei-soc-sdk`<br>`gpio.write` | `gpio_output_options_set`<br>gpio_output_options_set | `gpio_bit_write` (3; 6)<br>`gpio_bit_reset` (2; 4)<br>`gpio_bit_set` (2; 2)<br>`gpio_bit_toggle` (2; 5)<br>`gpio_port_write` (2; 7) | `same-family-operation-confusion` |
| 138 | `nuclei-soc-sdk`<br>`timer.initialize` | `timer_channel_output_config`<br>timer_channel_output_config | `timer_init` (3; 2) | `same-family-operation-confusion` |
| 139 | `nuclei-soc-sdk`<br>`timer.start` | `timer_break_enable`<br>timer_break_enable | `timer_enable` (3; 4) | `same-family-operation-confusion` |
| 140 | `nuclei-soc-sdk`<br>`timer.stop` | `timer_interrupt_disable`<br>timer_interrupt_disable | `timer_disable` (3; 7) | `same-family-operation-confusion` |
| 141 | `nuclei-soc-sdk`<br>`timer.set_interval` | `timer_input_pwm_capture_config`<br>timer_input_pwm_capture_config | `timer_autoreload_value_config` (3; 31) | `same-family-operation-confusion` |
| 142 | `hpmicro-hpm-sdk`<br>`uart.configure` | `uart_init_txline_idle_detection`<br>uart_init_txline_idle_detection | `uart_init` (3; 4)<br>`uart_set_baudrate` (1; 24) | `same-family-operation-confusion` |
| 143 | `hpmicro-hpm-sdk`<br>`gpio.configure` | `uart_init`<br>uart_init | `gpio_set_pin_input` (3; 18)<br>`gpio_set_pin_output` (3; 39)<br>`gpio_set_pin_output_with_initial` (3; 36) | `composite-entry-overranked` |
| 144 | `hpmicro-hpm-sdk`<br>`gpio.write` | `gpiom_set_pin_controller`<br>gpiom_set_pin_controller | `gpio_write_pin` (3; 15) | `ranking-model-confusion` |
| 145 | `hpmicro-hpm-sdk`<br>`gpio.read` | `spi_directio_read`<br>spi_directio_read | `gpio_read_pin` (3; 7) | `truth-path-missing` |
| 146 | `hpmicro-hpm-sdk`<br>`timer.initialize` | `ewdg_init_ctrl_func`<br>ewdg_init_ctrl_func | `gptmr_channel_config` (3; 4) | `composite-entry-overranked` |
| 147 | `hpmicro-hpm-sdk`<br>`timer.start` | `ptpc_enable_timer`<br>ptpc_enable_timer | `gptmr_start_counter` (3; 3) | `truth-path-missing` |
| 148 | `hpmicro-hpm-sdk`<br>`timer.set_interval` | `pwmv2_is_cmp_cross_period_event_invalid`<br>pwmv2_is_cmp_cross_period_event_invalid | `gptmr_channel_update_count` (3; 44)<br>`gptmr_update_cmp` (3; 43) | `truth-path-missing` |
| 149 | `espressif-esp-idf-6.0.1`<br>`interrupt.enable` | `interrupt_controller_hal_enable_interrupts`<br>interrupt_controller_hal_enable_interrupts -> esp_cpu_intr_enable -> rv_utils_intr_enable | `esp_intr_enable` (3; 5) | `ranking-model-confusion` |
| 150 | `espressif-esp-idf-6.0.1`<br>`interrupt.disable` | `esp_cpu_intr_disable`<br>esp_cpu_intr_disable -> rv_utils_intr_disable | `esp_intr_disable` (3; 6) | `ranking-model-confusion` |
| 151 | `espressif-esp-idf-6.0.1`<br>`interrupt.register` | `touch_pad_isr_register`<br>touch_pad_isr_register -> rtc_isr_register | `esp_intr_alloc` (3; 3)<br>`esp_intr_alloc_intrstatus` (3; 2) | `internal-role-overranked` |
| 152 | `espressif-esp-idf-6.0.1`<br>`uart.read` | `uart_get_word_length`<br>uart_get_word_length | `uart_read_bytes` (3; 10) | `same-family-operation-confusion` |
| 153 | `espressif-esp-idf-6.0.1`<br>`gpio.write` | `gpio_set_direction`<br>gpio_set_direction | `gpio_set_level` (3; 12) | `same-family-operation-confusion` |
| 154 | `espressif-esp-idf-6.0.1`<br>`gpio.attach_irq` | `dma2d_register_rx_event_callbacks`<br>dma2d_register_rx_event_callbacks | `gpio_isr_handler_add` (3; 4)<br>`gpio_intr_enable` (1; 9)<br>`gpio_set_intr_type` (1; 2) | `abstraction-level-mismatch` |
| 155 | `espressif-esp-idf-6.0.1`<br>`timer.start` | `systimer_hal_enable_counter`<br>systimer_hal_enable_counter | `esp_timer_start_once` (3; 2)<br>`esp_timer_start_periodic` (3; 3)<br>`gptimer_start` (3; 7) | `ranking-model-confusion` |
| 156 | `espressif-esp-idf-6.0.1`<br>`timer.stop` | `i3c_master_ll_set_stop_setup_time`<br>i3c_master_ll_set_stop_setup_time | `esp_timer_stop` (3; 10)<br>`gptimer_stop` (3; 9) | `ranking-model-confusion` |
| 157 | `espressif-esp-idf-6.0.1`<br>`timer.set_interval` | `systimer_ll_set_alarm_period`<br>systimer_ll_set_alarm_period | `esp_timer_start_periodic` (3; 4)<br>`gptimer_set_alarm_action` (3; 2)<br>`esp_timer_start_once` (2; 3) | `ranking-model-confusion` |
| 158 | `bouffalo-lhal`<br>`clock.get_frequency` | `Clock_Get_PSRAMB_Clk`<br>Clock_Get_PSRAMB_Clk | `bflb_clk_get_peripheral_clock` (3; 7)<br>`bflb_clk_get_system_clock` (3; 3) | `ranking-model-confusion` |
| 159 | `bouffalo-lhal`<br>`interrupt.enable` | `HBN_Enable_AComp_IRQ`<br>HBN_Enable_AComp_IRQ -> if -> bflb_irq_enable -> csi_vic_set_prio | `bflb_irq_enable` (3; 13) | `ranking-model-confusion` |
| 160 | `bouffalo-lhal`<br>`interrupt.disable` | `HBN_Disable_BOD_IRQ`<br>HBN_Disable_BOD_IRQ | `bflb_irq_disable` (3; 7) | `ranking-model-confusion` |
| 161 | `bouffalo-lhal`<br>`gpio.configure` | `bflb_sf_cfg_init_ext_flash_gpio`<br>bflb_sf_cfg_init_ext_flash_gpio -> bflb_gpio_init | `bflb_gpio_init` (3; 6) | `ranking-model-confusion` |
| 162 | `bouffalo-lhal`<br>`gpio.write` | `PDS_Set_PDS_GPIO_INT_DET_CLK_Sel`<br>PDS_Set_PDS_GPIO_INT_DET_CLK_Sel | `bflb_gpio_reset` (3; 21)<br>`bflb_gpio_set` (3; 6)<br>`bflb_gpio_pin0_31_output` (2; 20)<br>`bflb_gpio_pin0_31_reset` (2; 26)<br>`bflb_gpio_pin0_31_set` (2; 9)<br>`bflb_gpio_pin32_63_output` (2; 25)<br>`bflb_gpio_pin32_63_reset` (2; 29)<br>`bflb_gpio_pin32_63_set` (2; 24) | `ranking-model-confusion` |
| 163 | `bouffalo-lhal`<br>`gpio.read` | `PDS_Get_GPIO_Pad_IntStatus`<br>PDS_Get_GPIO_Pad_IntStatus | `bflb_gpio_read` (3; 4)<br>`bflb_gpio_pin0_31_read` (2; 20)<br>`bflb_gpio_pin32_63_read` (2; 19) | `ranking-model-confusion` |
| 164 | `bouffalo-lhal`<br>`gpio.attach_irq` | `GPIO_INT0_IRQHandler`<br>GPIO_INT0_IRQHandler -> GLB_Clr_GPIO_IntStatus | `bflb_gpio_irq_attach` (3; 6)<br>`bflb_gpio_int_init` (1; 7)<br>`bflb_gpio_int_mask` (1; 5) | `ranking-model-confusion` |
| 165 | `bouffalo-lhal`<br>`timer.initialize` | `SysTimer_SetSWIRQ`<br>SysTimer_SetSWIRQ -> SysTimer_SetHartSWIRQ | `bflb_timer_init` (3; 4) | `ranking-model-confusion` |
| 166 | `bouffalo-lhal`<br>`timer.start` | `HBN_Enable_RTC_Counter`<br>HBN_Enable_RTC_Counter | `bflb_timer_start` (3; 3) | `ranking-model-confusion` |
| 167 | `bouffalo-lhal`<br>`timer.stop` | `__disable_mhpm_counter`<br>无路径 | `bflb_timer_stop` (3; 10) | `ranking-model-confusion` |
| 168 | `bouffalo-lhal`<br>`timer.set_interval` | `SysTimer_SetCompareValue`<br>SysTimer_SetCompareValue -> SysTimer_SetHartCompareValue | `bflb_timer_set_compvalue` (3; 35)<br>`bflb_timer_set_preloadvalue` (3; 28) | `ranking-model-confusion` |
| 169 | `libopencm3-hal`<br>`clock.initialize` | `rcc_set_and_enable_plls`<br>rcc_set_and_enable_plls | `rcc_clock_setup_hse` (3; 6)<br>`rcc_clock_setup_hse_3v3` (3; 3)<br>`rcc_clock_setup_hsi` (3; 5)<br>`rcc_clock_setup_hsi48` (3; 20)<br>`rcc_clock_setup_cfgr` (1; 16)<br>`rcc_clock_setup_domain1` (1; 7)<br>`rcc_clock_setup_domain2` (1; 10)<br>`rcc_clock_setup_domain3` (1; 11) | `same-family-operation-confusion` |
| 170 | `libopencm3-hal`<br>`clock.enable` | `rcc_set_and_enable_plls`<br>rcc_set_and_enable_plls -> rcc_configure_pll | `rcc_periph_clock_enable` (3; 3) | `truth-path-missing` |
| 171 | `libopencm3-hal`<br>`clock.disable` | `ccs_pll_disable`<br>无路径 | `rcc_periph_clock_disable` (3; 9) | `truth-path-missing` |
| 172 | `libopencm3-hal`<br>`clock.get_frequency` | `ccs_get_peripheral_clk_freq`<br>ccs_get_peripheral_clk_freq | `rcc_get_bus_clk_freq` (3; 26)<br>`rcc_get_fdcan_clk_freq` (3; 29)<br>`rcc_get_i2c_clk_freq` (3; 14)<br>`rcc_get_spi_clk_freq` (3; 13)<br>`rcc_get_system_clock_frequency` (3; 7)<br>`rcc_get_timer_clk_freq` (3; 15)<br>`rcc_get_clksel_freq` (1; 3)<br>`rcc_get_i2c_clksel_freq` (1; 19)<br>`rcc_get_spi_clksel_freq` (1; 20)<br>`rcc_msi_frequency` (1; 18)<br>`rcc_pll_input_frequency` (1; 16) | `ranking-model-confusion` |
| 173 | `libopencm3-hal`<br>`interrupt.enable` | `NVIC_EnableIRQ`<br>NVIC_EnableIRQ | `nvic_enable_irq` (3; 2) | `same-family-operation-confusion` |
| 174 | `libopencm3-hal`<br>`interrupt.disable` | `NVIC_DisableIRQ`<br>NVIC_DisableIRQ | `nvic_disable_irq` (3; 2) | `same-family-operation-confusion` |
| 175 | `libopencm3-hal`<br>`uart.write` | `uart_wait_send_ready`<br>uart_wait_send_ready | `usart_send_blocking` (3; 6)<br>`usart_send` (2; 4) | `ranking-model-confusion` |
| 176 | `libopencm3-hal`<br>`uart.read` | `uart_wait_recv_ready`<br>uart_wait_recv_ready | `usart_recv_blocking` (3; 7)<br>`usart_recv` (2; 6) | `ranking-model-confusion` |
| 177 | `libopencm3-hal`<br>`gpio.read` | `gpio_port_read`<br>gpio_port_read | `gpio_get` (3; 2) | `same-family-operation-confusion` |
| 178 | `libopencm3-hal`<br>`timer.start` | `systick_counter_enable`<br>systick_counter_enable | `timer_enable_counter` (3; 12) | `truth-path-missing` |
| 179 | `libopencm3-hal`<br>`timer.stop` | `cm_disable_interrupts`<br>无路径 | `timer_disable_counter` (3; 9) | `truth-path-missing` |
| 180 | `libopencm3-hal`<br>`timer.set_interval` | `SysTick_Config`<br>SysTick_Config -> systick_set_reload | `timer_set_period` (3; 2) | `truth-path-missing` |
| 181 | `alif-ensemble-dfp`<br>`clock.disable` | `disable_txdphy_configure_clock`<br>disable_txdphy_configure_clock | `SERVICES_clocks_enable_clock` (3; 36) | `ranking-model-confusion` |
| 182 | `alif-ensemble-dfp`<br>`uart.write` | `uart_send_a_char_to_thr`<br>uart_send_a_char_to_thr | `uart_send_blocking` (3; 12) | `same-family-operation-confusion` |
| 183 | `alif-ensemble-dfp`<br>`gpio.write` | `gpio_set_direction_input`<br>gpio_set_direction_input | `gpio_bit_man_set_value_high` (2; 6)<br>`gpio_bit_man_set_value_low` (2; 5)<br>`gpio_set_value_high` (2; 4)<br>`gpio_set_value_low` (2; 3)<br>`GPIO_SetValue` (1; 25) | `same-family-operation-confusion` |
| 184 | `alif-ensemble-dfp`<br>`gpio.read` | `gpio_read_config2`<br>gpio_read_config2 | `gpio_get_value` (3; 43)<br>`GPIO_GetValue` (1; 42) | `same-family-operation-confusion` |
| 185 | `alif-ensemble-dfp`<br>`timer.start` | `lprtc_counter_wrap_enable`<br>lprtc_counter_wrap_enable | `utimer_counter_start` (3; 3) | `truth-path-missing` |
| 186 | `alif-ensemble-dfp`<br>`timer.stop` | `lptimer_disable_counter`<br>lptimer_disable_counter | `utimer_counter_stop` (3; 7) | `ranking-model-confusion` |
| 187 | `alif-ensemble-dfp`<br>`timer.set_interval` | `ch_set_freerun_interval`<br>ch_set_freerun_interval -> ch_common_set_freerun_interval -> set_interval_ticks | `utimer_set_count` (2; 20) | `ranking-model-confusion` |
