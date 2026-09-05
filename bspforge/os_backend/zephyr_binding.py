from __future__ import annotations

from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now
from bspforge.os_backend.plan_binding import (
    function_declarations,
    operation_manifest,
    render_operation_symbols,
    validate_operation_plan,
)


K210_AUXILIARY_SYMBOLS = {
    "clock": ["sysctl_clock_set_threshold"],
    "interrupt": ["plic_irq_unregister"],
    "uart": ["uart_init"],
    "gpio": ["gpiohs_set_pin_edge", "gpiohs_irq_unregister"],
    "timer": [
        "timer_irq_register",
        "timer_irq_unregister",
        "timer_set_mode",
        "timer_enable_interrupt",
    ],
}

K210_REQUIRED_SOURCES = [
    "lib/drivers/fpioa.c",
    "lib/drivers/gpiohs.c",
    "lib/drivers/sysctl.c",
    "lib/drivers/timer.c",
    "lib/drivers/uart.c",
    "lib/drivers/utils.c",
]


class ZephyrBindingGenerator:
    """Generate a Zephyr-callable adapter backed by the analyzed K210 SDK."""

    def generate(
        self,
        source_dir: Path,
        ir: dict[str, Any],
        binding_plan: dict[str, Any] | None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = options or {}
        if config.get("sdk_profile") != "k210":
            raise ValueError("generated Zephyr SDK bindings currently support k210")
        selections = validate_operation_plan(ir, binding_plan)

        function_index: dict[str, list[dict[str, Any]]] = {}
        for function in ir["functions"]:
            function_index.setdefault(function["name"], []).append(function)

        bindings: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        for capability, operations in selections.items():
            selected_symbols = [
                item["selected_symbol"] for item in operations.values()
            ]
            symbols = list(dict.fromkeys(
                selected_symbols + K210_AUXILIARY_SYMBOLS.get(capability, [])
            ))
            evidence = []
            capability_missing = []
            for symbol in symbols:
                matches = function_index.get(symbol, [])
                if not matches:
                    capability_missing.append(symbol)
                    missing.append({"capability": capability, "symbol": symbol})
                    continue
                entity = matches[0]
                evidence.append({
                    "symbol": symbol,
                    "entity_id": entity["id"],
                    "source": entity["evidence"],
                    "signature": entity["signature"],
                    "selection_method": (
                        "canonical-plan-selected-operation"
                        if symbol in selected_symbols
                        else "backend-adaptation-dependency"
                    ),
                })
            if not capability_missing:
                bindings.append({
                    "capability": capability,
                    "status": "generated",
                    "sdk_symbols": evidence,
                    "selected_operations": [
                        {
                            "operation": operation,
                            "symbol": item["selected_symbol"],
                            "entity_id": item["entity_id"],
                        }
                        for operation, item in operations.items()
                    ],
                    "auxiliary_symbols": K210_AUXILIARY_SYMBOLS.get(capability, []),
                })

        if missing:
            names = ", ".join(item["symbol"] for item in missing)
            raise ValueError(f"K210 Zephyr binding requires missing SDK symbols: {names}")

        header = source_dir / "bspforge_bindings.h"
        source = source_dir / "bspforge_bindings.c"
        machine_include = source_dir / "machine"
        machine_include.mkdir(parents=True, exist_ok=True)
        (machine_include / "syscall.h").write_text(
            "/* Zephyr compatibility shim for unused K210 bare-metal syscall IDs. */\n",
            encoding="utf-8",
        )
        (source_dir / "math.h").write_text(
            "/* Builtin math declarations needed while compiling the K210 SDK. */\n"
            "#define fabs(value) __builtin_fabs(value)\n"
            "#define floor(value) __builtin_floor(value)\n"
            "#define ceil(value) __builtin_ceil(value)\n"
            "#define rint(value) __builtin_rint(value)\n",
            encoding="utf-8",
        )
        header.write_text(self._header(), encoding="utf-8")
        call_source = self._source(config.get("validation", {}), selections)
        operation_bindings = operation_manifest(
            selections,
            call_source,
            replaced_operations={
                ("interrupt", operation) for operation in selections["interrupt"]
            },
        )
        callable_symbols = [
            item["symbol"]
            for binding in bindings
            for item in binding["sdk_symbols"]
        ]
        ir_declarations = function_declarations(function_index, callable_symbols)
        generated_source = self._source(
            config.get("validation", {}), selections, ir_declarations
        )
        source.write_text(generated_source, encoding="utf-8")
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "backend": "zephyr",
            "strategy": "generated-sdk-adapter",
            "binding_plan_id": binding_plan.get("id") if binding_plan else None,
            "source": str(source),
            "header": str(header),
            "source_sha256": file_sha256(source),
            "header_sha256": file_sha256(header),
            "compatibility_headers": [
                str(machine_include / "syscall.h"),
                str(source_dir / "math.h"),
            ],
            "bindings": bindings,
            "operation_bindings": operation_bindings,
            "ir_function_declarations": ir_declarations,
            "required_sources": K210_REQUIRED_SOURCES,
            "missing_symbols": missing,
            "summary": {
                "capabilities": len(bindings),
                "wrappers": 19,
                "plan_operations": len(operation_bindings),
                "direct_plan_operations": sum(
                    item["disposition"] == "direct-generated-call"
                    for item in operation_bindings
                ),
                "os_replaced_operations": sum(
                    item["disposition"] == "replaced-by-os-backend"
                    for item in operation_bindings
                ),
                "required_sources": len(K210_REQUIRED_SOURCES),
                "missing_symbols": len(missing),
            },
        }

    @staticmethod
    def _header() -> str:
        return r'''/* Generated by BSPForge. Do not edit manually. */
#ifndef BSPFORGE_ZEPHYR_BINDINGS_H
#define BSPFORGE_ZEPHYR_BINDINGS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef int (*bspforge_callback_t)(void *context);

int bspforge_clock_on(uint32_t clock_id);
int bspforge_clock_off(uint32_t clock_id);
int bspforge_clock_get_rate(uint32_t clock_id, uint32_t *rate);
int bspforge_clock_test(uint32_t *cpu_hz, uint32_t *timer_hz);
int bspforge_uart_initialize(void);
int bspforge_uart_configure(uint32_t baud_rate);
int bspforge_uart_write(const void *buffer, size_t size);
int bspforge_uart_read(void *buffer, size_t size);
int bspforge_gpio_initialize(void);
int bspforge_gpio_write(uint8_t value);
int bspforge_gpio_read(void);
int bspforge_gpio_output_latch(void);
int bspforge_gpio_irq_register(bspforge_callback_t handler, void *context);
void bspforge_gpio_irq_unregister(void);
int bspforge_timer_initialize(void);
int bspforge_timer_start(uint64_t interval_ns, bool single_shot,
                         bspforge_callback_t handler, void *context);
void bspforge_timer_quiesce(void);
int bspforge_timer_stop(void);
uint32_t bspforge_timer_count(void);

#endif
'''

    @staticmethod
    def _source(
        validation: dict[str, Any],
        selections: dict[str, dict[str, dict[str, Any]]],
        ir_declarations: list[str] | None = None,
    ) -> str:
        uart_channel = int(validation.get("uart_channel", 0))
        uart_tx = int(validation.get("uart_tx_fpioa_io", 7))
        uart_rx = int(validation.get("uart_rx_fpioa_io", 6))
        gpio_io = int(validation.get("gpio_fpioa_io", 8))
        gpio_pin = int(validation.get("gpio_binding_pin", 29))
        gpio_input_io = int(validation.get("gpio_input_fpioa_io", 9))
        gpio_input_pin = int(validation.get("gpio_input_binding_pin", 28))
        timer_device = int(validation.get("timer_device", 0))
        timer_channel = int(validation.get("timer_channel", 0))
        if not 0 <= uart_channel <= 2:
            raise ValueError("K210 UART channel must be in [0, 2]")
        if not all(
            0 <= item <= 47
            for item in (uart_tx, uart_rx, gpio_io, gpio_input_io)
        ):
            raise ValueError("K210 FPIOA IO must be in [0, 47]")
        if not all(0 <= item <= 31 for item in (gpio_pin, gpio_input_pin)):
            raise ValueError("K210 GPIOHS pin must be in [0, 31]")
        if not 0 <= timer_device <= 2 or not 0 <= timer_channel <= 3:
            raise ValueError("K210 timer device/channel must be in [0, 2]/[0, 3]")
        prototypes = "\n".join(ir_declarations or [])
        template = rf'''/* Generated from K210 SDK IR and the Zephyr backend contract. */
#include "bspforge_bindings.h"

#include <zephyr/irq.h>
#include <zephyr/irq_multilevel.h>
#include <zephyr/arch/riscv/irq.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <errno.h>

#include <fpioa.h>
#include <gpiohs.h>
#include <plic.h>
#include <sysctl.h>
#include <timer.h>
#include <uart.h>

/* Prototypes recovered from SDK implementation entities in the IR. */
{prototypes}

#define BSPFORGE_UART_CHANNEL {uart_channel}U
#define BSPFORGE_UART_TX_IO {uart_tx}U
#define BSPFORGE_UART_RX_IO {uart_rx}U
#define BSPFORGE_GPIO_OUTPUT_IO {gpio_io}U
#define BSPFORGE_GPIO_OUTPUT_PIN {gpio_pin}U
#define BSPFORGE_GPIO_INPUT_IO {gpio_input_io}U
#define BSPFORGE_GPIO_INPUT_PIN {gpio_input_pin}U
#define BSPFORGE_TIMER_DEVICE {timer_device}U
#define BSPFORGE_TIMER_CHANNEL {timer_channel}U
#define BSPFORGE_TIMER_LOCAL_IRQ \
    (IRQN_TIMER0A_INTERRUPT + BSPFORGE_TIMER_DEVICE * 2U + \
     BSPFORGE_TIMER_CHANNEL / 2U)
#define BSPFORGE_ZEPHYR_IRQ(local_irq) \
    (IRQ_TO_L2(local_irq) | RISCV_IRQ_MEXT)

static plic_irq_callback_t bspforge_plic_callbacks[IRQN_MAX];
static void *bspforge_plic_contexts[IRQN_MAX];

static void bspforge_dispatch_irq(unsigned int irq)
{{
    if (irq < IRQN_MAX && bspforge_plic_callbacks[irq] != NULL)
        (void)bspforge_plic_callbacks[irq](bspforge_plic_contexts[irq]);
}}

static void bspforge_timer0a_isr(const void *unused)
{{
    ARG_UNUSED(unused);
    bspforge_dispatch_irq(BSPFORGE_TIMER_LOCAL_IRQ);
}}

static void bspforge_gpiohs28_isr(const void *unused)
{{
    ARG_UNUSED(unused);
    bspforge_dispatch_irq(IRQN_GPIOHS0_INTERRUPT + BSPFORGE_GPIO_INPUT_PIN);
}}

static int bspforge_plic_bridge_init(void)
{{
    IRQ_CONNECT(BSPFORGE_ZEPHYR_IRQ(BSPFORGE_TIMER_LOCAL_IRQ), 1,
                bspforge_timer0a_isr, NULL, 0);
    IRQ_CONNECT(BSPFORGE_ZEPHYR_IRQ(IRQN_GPIOHS0_INTERRUPT +
                                    BSPFORGE_GPIO_INPUT_PIN), 1,
                bspforge_gpiohs28_isr, NULL, 0);
    return 0;
}}
SYS_INIT(bspforge_plic_bridge_init, PRE_KERNEL_1, 60);

void plic_init(void)
{{
}}

int plic_irq_enable(plic_irq_t irq)
{{
    if (irq <= IRQN_NO_INTERRUPT || irq >= IRQN_MAX)
        return -1;
    irq_enable(BSPFORGE_ZEPHYR_IRQ((unsigned int)irq));
    return 0;
}}

int plic_irq_disable(plic_irq_t irq)
{{
    if (irq <= IRQN_NO_INTERRUPT || irq >= IRQN_MAX)
        return -1;
    irq_disable(BSPFORGE_ZEPHYR_IRQ((unsigned int)irq));
    return 0;
}}

int plic_set_priority(plic_irq_t irq, uint32_t priority)
{{
    ARG_UNUSED(priority);
    return irq > IRQN_NO_INTERRUPT && irq < IRQN_MAX ? 0 : -1;
}}

uint32_t plic_get_priority(plic_irq_t irq)
{{
    return irq > IRQN_NO_INTERRUPT && irq < IRQN_MAX ? 1U : 0U;
}}

void plic_irq_register(plic_irq_t irq, plic_irq_callback_t callback, void *context)
{{
    if (irq > IRQN_NO_INTERRUPT && irq < IRQN_MAX) {{
        bspforge_plic_callbacks[irq] = callback;
        bspforge_plic_contexts[irq] = context;
    }}
}}

void plic_irq_unregister(plic_irq_t irq)
{{
    if (irq > IRQN_NO_INTERRUPT && irq < IRQN_MAX) {{
        irq_disable(BSPFORGE_ZEPHYR_IRQ((unsigned int)irq));
        bspforge_plic_callbacks[irq] = NULL;
        bspforge_plic_contexts[irq] = NULL;
    }}
}}

uint32_t plic_irq_claim(void)
{{
    return 0U;
}}

int plic_irq_complete(uint32_t source)
{{
    ARG_UNUSED(source);
    return 0;
}}

int usleep(uint64_t usec)
{{
    while (usec > UINT32_MAX) {{
        k_busy_wait(UINT32_MAX);
        usec -= UINT32_MAX;
    }}
    k_busy_wait((uint32_t)usec);
    return 0;
}}

static int bspforge_clock_id(uint32_t clock_id, sysctl_clock_t *clock)
{{
    if (clock == NULL)
        return -EINVAL;
    if (clock_id == 0U)
        *clock = SYSCTL_CLOCK_CPU;
    else if (clock_id == 1U)
        *clock = SYSCTL_CLOCK_TIMER2;
    else
        return -EINVAL;
    return 0;
}}

int bspforge_clock_on(uint32_t clock_id)
{{
    sysctl_clock_t clock;
    int result = bspforge_clock_id(clock_id, &clock);

    if (result != 0)
        return result;
    return @OP:clock.enable@(clock) == 0 ? 0 : -EIO;
}}

int bspforge_clock_off(uint32_t clock_id)
{{
    sysctl_clock_t clock;
    int result;

    if (clock_id == 0U)
        return -ENOTSUP;
    result = bspforge_clock_id(clock_id, &clock);
    if (result != 0)
        return result;
    return @OP:clock.disable@(clock) == 0 ? 0 : -EIO;
}}

int bspforge_clock_get_rate(uint32_t clock_id, uint32_t *rate)
{{
    sysctl_clock_t clock;

    if (rate == NULL)
        return -EINVAL;
    if (bspforge_clock_id(clock_id, &clock) != 0)
        return -EINVAL;
    *rate = @OP:clock.get_frequency@(clock);
    return *rate > 0U ? 0 : -EIO;
}}

int bspforge_clock_test(uint32_t *cpu_hz, uint32_t *timer_hz)
{{
    if (cpu_hz == NULL || timer_hz == NULL)
        return -EINVAL;
    if (bspforge_clock_get_rate(0U, cpu_hz) != 0)
        return -EIO;
    if (bspforge_clock_on(1U) != 0)
        return -EIO;
    if (bspforge_clock_get_rate(1U, timer_hz) != 0)
        return -EIO;
    return bspforge_clock_off(1U);
}}

int bspforge_uart_initialize(void)
{{
    if (fpioa_set_function(BSPFORGE_UART_TX_IO,
                           FUNC_UART1_TX + 2 * BSPFORGE_UART_CHANNEL) != 0 ||
        fpioa_set_function(BSPFORGE_UART_RX_IO,
                           FUNC_UART1_RX + 2 * BSPFORGE_UART_CHANNEL) != 0)
        return -EIO;
    uart_init((uart_device_number_t)BSPFORGE_UART_CHANNEL);
    return bspforge_uart_configure(115200U);
}}

int bspforge_uart_configure(uint32_t baud_rate)
{{
    if (baud_rate == 0U)
        return -EINVAL;
    @OP:uart.configure@((uart_device_number_t)BSPFORGE_UART_CHANNEL, baud_rate,
                        UART_BITWIDTH_8BIT, UART_STOP_1, UART_PARITY_NONE);
    return 0;
}}

int bspforge_uart_write(const void *buffer, size_t size)
{{
    if (buffer == NULL)
        return -EINVAL;
    return @OP:uart.write@((uart_device_number_t)BSPFORGE_UART_CHANNEL,
                           (const char *)buffer, size);
}}

int bspforge_uart_read(void *buffer, size_t size)
{{
    if (buffer == NULL)
        return -EINVAL;
    return @OP:uart.read@((uart_device_number_t)BSPFORGE_UART_CHANNEL,
                          (char *)buffer, size);
}}

int bspforge_gpio_initialize(void)
{{
    int output_mapping;
    int input_mapping;
    uint32_t mapping_attempt;

    /* GPIOHS drive-mode setup requires the SDK FPIOA clock/init contract. */
    if (fpioa_init() != 0)
        return -EIO;
    if (fpioa_set_function(BSPFORGE_GPIO_OUTPUT_IO,
                           FUNC_GPIOHS0 + BSPFORGE_GPIO_OUTPUT_PIN) != 0 ||
        fpioa_set_function(BSPFORGE_GPIO_INPUT_IO,
                           FUNC_GPIOHS0 + BSPFORGE_GPIO_INPUT_PIN) != 0)
        return -EIO;
    if (fpioa_set_io_pull(BSPFORGE_GPIO_OUTPUT_IO, FPIOA_PULL_DOWN) != 0 ||
        fpioa_set_io_pull(BSPFORGE_GPIO_INPUT_IO, FPIOA_PULL_DOWN) != 0)
        return -EIO;
    output_mapping = -1;
    input_mapping = -1;
    for (mapping_attempt = 0U; mapping_attempt < 16U; ++mapping_attempt) {{
        output_mapping = fpioa_get_io_by_function(
            FUNC_GPIOHS0 + BSPFORGE_GPIO_OUTPUT_PIN);
        input_mapping = fpioa_get_io_by_function(
            FUNC_GPIOHS0 + BSPFORGE_GPIO_INPUT_PIN);
        if (output_mapping == (int)BSPFORGE_GPIO_OUTPUT_IO &&
            input_mapping == (int)BSPFORGE_GPIO_INPUT_IO)
            break;
        k_busy_wait(1U);
    }}
    if (output_mapping != (int)BSPFORGE_GPIO_OUTPUT_IO ||
        input_mapping != (int)BSPFORGE_GPIO_INPUT_IO) {{
        printk("bspforge: FPIOA mapping timeout output=%d input=%d\n",
               output_mapping, input_mapping);
        return -EIO;
    }}
    @OP:gpio.configure@(BSPFORGE_GPIO_OUTPUT_PIN, GPIO_DM_OUTPUT);
    @OP:gpio.configure@(BSPFORGE_GPIO_INPUT_PIN, GPIO_DM_INPUT_PULL_DOWN);
    return 0;
}}

int bspforge_gpio_write(uint8_t value)
{{
    @OP:gpio.write@(BSPFORGE_GPIO_OUTPUT_PIN,
                    value ? GPIO_PV_HIGH : GPIO_PV_LOW);
    return 0;
}}

int bspforge_gpio_read(void)
{{
    return @OP:gpio.read@(BSPFORGE_GPIO_INPUT_PIN) == GPIO_PV_HIGH ? 1 : 0;
}}

int bspforge_gpio_output_latch(void)
{{
    return (int)((gpiohs->output_val.u32[0] >> BSPFORGE_GPIO_OUTPUT_PIN) & 1U);
}}

int bspforge_gpio_irq_register(bspforge_callback_t handler, void *context)
{{
    if (handler == NULL)
        return -EINVAL;
    gpiohs_set_pin_edge(BSPFORGE_GPIO_INPUT_PIN, GPIO_PE_RISING);
    @OP:gpio.attach_irq@(BSPFORGE_GPIO_INPUT_PIN, 1,
                         (plic_irq_callback_t)handler, context);
    return 0;
}}

void bspforge_gpio_irq_unregister(void)
{{
    gpiohs_irq_unregister(BSPFORGE_GPIO_INPUT_PIN);
}}

int bspforge_timer_initialize(void)
{{
    @OP:timer.initialize@((timer_device_number_t)BSPFORGE_TIMER_DEVICE);
    if (@OP:clock.initialize@(
            (sysctl_clock_select_t)(SYSCTL_CLOCK_SELECT_TIMER0 +
                                    BSPFORGE_TIMER_DEVICE), 1) != 0)
        return -EIO;
    if (sysctl_clock_set_threshold(
            (sysctl_threshold_t)(SYSCTL_THRESHOLD_TIMER0 +
                                 BSPFORGE_TIMER_DEVICE), 0) != 0)
        return -EIO;
    @OP:timer.stop@((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                    (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL);
    (void)timer[BSPFORGE_TIMER_DEVICE]
        ->channel[BSPFORGE_TIMER_CHANNEL].eoi;
    return 0;
}}

int bspforge_timer_start(uint64_t interval_ns, bool single_shot,
                         bspforge_callback_t handler, void *context)
{{
    if (interval_ns == 0U || handler == NULL)
        return -EINVAL;
    if (@OP:timer.set_interval@(
            (timer_device_number_t)BSPFORGE_TIMER_DEVICE,
            (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL,
            (size_t)interval_ns) == 0U)
        return -EIO;
    if (timer_irq_register((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                           (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL,
                           single_shot ? 1 : 0, 1,
                           (timer_callback_t)handler, context) != 0)
        return -EIO;
    timer_set_mode((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                   (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL,
                   TIMER_CR_USER_MODE);
    timer_enable_interrupt((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                           (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL);
    @OP:timer.start@((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                     (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL);
    return 0;
}}

void bspforge_timer_quiesce(void)
{{
    @OP:timer.stop@((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                    (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL);
}}

int bspforge_timer_stop(void)
{{
    bspforge_timer_quiesce();
    return timer_irq_unregister((timer_device_number_t)BSPFORGE_TIMER_DEVICE,
                                (timer_channel_number_t)BSPFORGE_TIMER_CHANNEL);
}}

uint32_t bspforge_timer_count(void)
{{
    return timer[BSPFORGE_TIMER_DEVICE]
        ->channel[BSPFORGE_TIMER_CHANNEL].current_value;
}}
'''
        return render_operation_symbols(template, selections)
