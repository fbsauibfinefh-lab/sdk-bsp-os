from __future__ import annotations

from typing import Any


SDK_PROFILES: dict[str, dict[str, Any]] = {
    "k210": {
        "architecture": "riscv64",
        "machine": "RISC-V",
        "capabilities": {
            "clock": ["sysctl_clock_enable", "sysctl_clock_disable", "sysctl_clock_get_freq"],
            "interrupt": ["plic_init", "plic_irq_enable", "plic_irq_disable", "plic_irq_register"],
            "uart": ["uart_init", "uart_configure", "uart_send_data", "uart_receive_data"],
            "gpio": ["gpiohs_set_drive_mode", "gpiohs_get_pin", "gpiohs_set_pin"],
            "timer": ["timer_init", "timer_set_interval", "timer_set_enable"],
        },
    },
    "stm32f103": {
        "architecture": "arm",
        "machine": "ARM",
        "capabilities": {
            "clock": ["HAL_RCC_OscConfig", "HAL_RCC_ClockConfig", "HAL_RCC_GetHCLKFreq"],
            "interrupt": ["HAL_NVIC_SetPriority", "HAL_NVIC_EnableIRQ", "HAL_NVIC_DisableIRQ"],
            "uart": ["HAL_UART_Init", "HAL_UART_Transmit", "HAL_UART_Receive"],
            "gpio": ["HAL_GPIO_Init", "HAL_GPIO_ReadPin", "HAL_GPIO_WritePin"],
            "timer": ["HAL_TIM_Base_Init", "HAL_TIM_Base_Start", "HAL_TIM_Base_Stop"],
        },
    },
    "psoc_e84_edgi_talk": {
        "architecture": "arm",
        "machine": "ARM",
        "capabilities": {
            "clock": [
                "Cy_SysClk_ClkHfSetSource",
                "Cy_SysClk_ClkHfSetDivider",
                "Cy_SysClk_PeriPclkDisableDivider",
                "Cy_SysClk_PeriPclkSetDivider",
                "Cy_SysClk_PeriPclkEnableDivider",
            ],
            "interrupt": ["Cy_SysInt_Init", "Cy_SysInt_SetVector"],
            "uart": ["Cy_SCB_UART_Init", "Cy_SCB_UART_Put", "Cy_SCB_UART_Get"],
            "gpio": [
                "Cy_GPIO_Pin_Init",
                "Cy_GPIO_Pin_FastInit",
                "Cy_GPIO_Read",
                "Cy_GPIO_Write",
                "mtb_hal_gpio_setup",
                "mtb_hal_gpio_read",
                "mtb_hal_gpio_write",
            ],
            "timer": ["Cy_TCPWM_Counter_Init", "Cy_TCPWM_TriggerStart", "Cy_TCPWM_TriggerStop"],
        },
    },
}


def sdk_profile(name: str) -> dict[str, Any]:
    try:
        return SDK_PROFILES[name]
    except KeyError as error:
        raise ValueError(f"Unsupported SDK profile: {name}") from error
