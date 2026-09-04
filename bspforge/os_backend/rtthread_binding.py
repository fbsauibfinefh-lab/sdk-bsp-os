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


CAPABILITY_AUXILIARY_SYMBOLS: dict[str, list[str]] = {
    "clock": [],
    "interrupt": ["plic_irq_unregister", "plic_irq_claim"],
    "uart": ["uart_init"],
    "gpio": ["gpiohs_set_pin_edge", "gpiohs_irq_unregister"],
    "timer": [
        "timer_irq_register",
        "timer_irq_unregister",
        "timer_set_mode",
        "timer_enable_interrupt",
    ],
}


CAPABILITY_BINDINGS: dict[str, dict[str, Any]] = {
    "clock": {
        "headers": ["sysctl.h"],
        "declarations": [
            "rt_err_t bspforge_clock_initialize(rt_uint32_t selector, rt_uint32_t source);",
            "rt_err_t bspforge_clock_enable(rt_uint32_t clock);",
            "rt_err_t bspforge_clock_disable(rt_uint32_t clock);",
            "rt_uint32_t bspforge_clock_frequency(rt_uint32_t clock);",
        ],
        "definitions": r"""
rt_err_t bspforge_clock_initialize(rt_uint32_t selector, rt_uint32_t source)
{
    return @OP:clock.initialize@((sysctl_clock_select_t)selector, (int)source) == 0
               ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_clock_enable(rt_uint32_t clock)
{
    return @OP:clock.enable@((sysctl_clock_t)clock) == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_clock_disable(rt_uint32_t clock)
{
    return @OP:clock.disable@((sysctl_clock_t)clock) == 0 ? RT_EOK : -RT_ERROR;
}

rt_uint32_t bspforge_clock_frequency(rt_uint32_t clock)
{
    return (rt_uint32_t)@OP:clock.get_frequency@((sysctl_clock_t)clock);
}
""",
    },
    "interrupt": {
        "headers": ["plic.h"],
        "declarations": [
            "typedef int (*bspforge_irq_handler_t)(void *context);",
            "void bspforge_irq_initialize(void);",
            "rt_err_t bspforge_irq_enable(rt_uint32_t irq);",
            "rt_err_t bspforge_irq_disable(rt_uint32_t irq);",
            "void bspforge_irq_register(rt_uint32_t irq, bspforge_irq_handler_t handler, void *context);",
            "void bspforge_irq_unregister(rt_uint32_t irq);",
            "rt_uint32_t bspforge_irq_claim(void);",
        ],
        "definitions": r"""
void bspforge_irq_initialize(void)
{
    @OP:interrupt.initialize@();
}

rt_err_t bspforge_irq_enable(rt_uint32_t irq)
{
    return @OP:interrupt.enable@((plic_irq_t)irq) == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_irq_disable(rt_uint32_t irq)
{
    return @OP:interrupt.disable@((plic_irq_t)irq) == 0 ? RT_EOK : -RT_ERROR;
}

void bspforge_irq_register(rt_uint32_t irq, bspforge_irq_handler_t handler, void *context)
{
    @OP:interrupt.register@((plic_irq_t)irq,
                            (plic_irq_callback_t)handler, context);
}

void bspforge_irq_unregister(rt_uint32_t irq)
{
    plic_irq_unregister((plic_irq_t)irq);
}

rt_uint32_t bspforge_irq_claim(void)
{
    return (rt_uint32_t)plic_irq_claim();
}
""",
    },
    "uart": {
        "headers": ["uart.h"],
        "declarations": [
            "rt_err_t bspforge_uart_configure(rt_uint32_t channel, rt_uint32_t baud_rate, rt_uint8_t data_bits, rt_uint8_t stop_bits, rt_uint8_t parity);",
            "rt_ssize_t bspforge_uart_write(rt_uint32_t channel, const void *buffer, rt_size_t size);",
            "rt_ssize_t bspforge_uart_read(rt_uint32_t channel, void *buffer, rt_size_t size);",
        ],
        "definitions": r"""
rt_err_t bspforge_uart_configure(rt_uint32_t channel, rt_uint32_t baud_rate,
                                 rt_uint8_t data_bits, rt_uint8_t stop_bits,
                                 rt_uint8_t parity)
{
    uart_stopbit_t sdk_stop_bits;
    uart_parity_t sdk_parity;

    if (channel >= (rt_uint32_t)UART_DEVICE_MAX || baud_rate == 0 ||
        data_bits < 5 || data_bits > 8)
        return -RT_EINVAL;

    if (stop_bits == 1)
        sdk_stop_bits = UART_STOP_1;
    else if (stop_bits == 2)
        sdk_stop_bits = UART_STOP_2;
    else
        return -RT_EINVAL;

    switch (parity)
    {
    case 0:
        sdk_parity = UART_PARITY_NONE;
        break;
    case 1:
        sdk_parity = UART_PARITY_ODD;
        break;
    case 2:
        sdk_parity = UART_PARITY_EVEN;
        break;
    default:
        return -RT_EINVAL;
    }

    uart_init((uart_device_number_t)channel);
    @OP:uart.configure@((uart_device_number_t)channel, baud_rate,
                        (uart_bitwidth_t)data_bits, sdk_stop_bits, sdk_parity);
    return RT_EOK;
}

rt_ssize_t bspforge_uart_write(rt_uint32_t channel, const void *buffer, rt_size_t size)
{
    if (buffer == RT_NULL || channel >= (rt_uint32_t)UART_DEVICE_MAX)
        return -RT_EINVAL;
    return (rt_ssize_t)@OP:uart.write@((uart_device_number_t)channel,
                                       (const char *)buffer, (size_t)size);
}

rt_ssize_t bspforge_uart_read(rt_uint32_t channel, void *buffer, rt_size_t size)
{
    if (buffer == RT_NULL || channel >= (rt_uint32_t)UART_DEVICE_MAX)
        return -RT_EINVAL;
    return (rt_ssize_t)@OP:uart.read@((uart_device_number_t)channel,
                                      (char *)buffer, (size_t)size);
}
""",
    },
    "gpio": {
        "headers": ["gpiohs.h"],
        "declarations": [
            "typedef int (*bspforge_gpio_irq_handler_t)(void *context);",
            "#define BSPFORGE_GPIO_PIN_COUNT 32U",
            "enum bspforge_gpio_mode { BSPFORGE_GPIO_INPUT, BSPFORGE_GPIO_INPUT_PULL_DOWN, BSPFORGE_GPIO_INPUT_PULL_UP, BSPFORGE_GPIO_OUTPUT };",
            "enum bspforge_gpio_edge { BSPFORGE_GPIO_RISING, BSPFORGE_GPIO_FALLING, BSPFORGE_GPIO_BOTH, BSPFORGE_GPIO_LOW_LEVEL, BSPFORGE_GPIO_HIGH_LEVEL };",
            "rt_err_t bspforge_gpio_mode(rt_uint8_t pin, rt_uint8_t mode);",
            "rt_err_t bspforge_gpio_write(rt_uint8_t pin, rt_uint8_t value);",
            "rt_int32_t bspforge_gpio_read(rt_uint8_t pin);",
            "rt_err_t bspforge_gpio_irq_register(rt_uint8_t pin, rt_uint8_t edge, bspforge_gpio_irq_handler_t handler, void *context);",
            "void bspforge_gpio_irq_unregister(rt_uint8_t pin);",
        ],
        "definitions": r"""
rt_err_t bspforge_gpio_mode(rt_uint8_t pin, rt_uint8_t mode)
{
    gpio_drive_mode_t sdk_mode;
    if (pin >= BSPFORGE_GPIO_PIN_COUNT)
        return -RT_EINVAL;
    switch (mode)
    {
    case BSPFORGE_GPIO_INPUT:
        sdk_mode = GPIO_DM_INPUT;
        break;
    case BSPFORGE_GPIO_INPUT_PULL_DOWN:
        sdk_mode = GPIO_DM_INPUT_PULL_DOWN;
        break;
    case BSPFORGE_GPIO_INPUT_PULL_UP:
        sdk_mode = GPIO_DM_INPUT_PULL_UP;
        break;
    case BSPFORGE_GPIO_OUTPUT:
        sdk_mode = GPIO_DM_OUTPUT;
        break;
    default:
        return -RT_EINVAL;
    }
    @OP:gpio.configure@(pin, sdk_mode);
    return RT_EOK;
}

rt_err_t bspforge_gpio_write(rt_uint8_t pin, rt_uint8_t value)
{
    if (pin >= BSPFORGE_GPIO_PIN_COUNT)
        return -RT_EINVAL;
    @OP:gpio.write@(pin, value ? GPIO_PV_HIGH : GPIO_PV_LOW);
    return RT_EOK;
}

rt_int32_t bspforge_gpio_read(rt_uint8_t pin)
{
    if (pin >= BSPFORGE_GPIO_PIN_COUNT)
        return -RT_EINVAL;
    return @OP:gpio.read@(pin) == GPIO_PV_HIGH ? 1 : 0;
}

rt_err_t bspforge_gpio_irq_register(rt_uint8_t pin, rt_uint8_t edge,
                                    bspforge_gpio_irq_handler_t handler,
                                    void *context)
{
    gpio_pin_edge_t sdk_edge;
    if (pin >= BSPFORGE_GPIO_PIN_COUNT || handler == RT_NULL)
        return -RT_EINVAL;
    switch (edge)
    {
    case BSPFORGE_GPIO_RISING:
        sdk_edge = GPIO_PE_RISING;
        break;
    case BSPFORGE_GPIO_FALLING:
        sdk_edge = GPIO_PE_FALLING;
        break;
    case BSPFORGE_GPIO_BOTH:
        sdk_edge = GPIO_PE_BOTH;
        break;
    case BSPFORGE_GPIO_LOW_LEVEL:
        sdk_edge = GPIO_PE_LOW;
        break;
    case BSPFORGE_GPIO_HIGH_LEVEL:
        sdk_edge = GPIO_PE_HIGH;
        break;
    default:
        return -RT_EINVAL;
    }
    gpiohs_set_pin_edge(pin, sdk_edge);
    @OP:gpio.attach_irq@(pin, 1, (plic_irq_callback_t)handler, context);
    return RT_EOK;
}

void bspforge_gpio_irq_unregister(rt_uint8_t pin)
{
    if (pin < BSPFORGE_GPIO_PIN_COUNT)
        gpiohs_irq_unregister(pin);
}
""",
    },
    "timer": {
        "headers": ["timer.h"],
        "data_contracts": [
            {"symbol": "timer", "header": "timer.h", "usage": "read current_value register"},
        ],
        "declarations": [
            "typedef int (*bspforge_timer_handler_t)(void *context);",
            "rt_err_t bspforge_timer_initialize(rt_uint32_t device);",
            "rt_err_t bspforge_timer_start(rt_uint32_t device, rt_uint32_t channel, rt_uint64_t interval_ns, rt_bool_t single_shot, bspforge_timer_handler_t handler, void *context);",
            "rt_err_t bspforge_timer_stop(rt_uint32_t device, rt_uint32_t channel);",
            "rt_uint32_t bspforge_timer_count(rt_uint32_t device, rt_uint32_t channel);",
        ],
        "definitions": r"""
rt_err_t bspforge_timer_initialize(rt_uint32_t device)
{
    if (device >= (rt_uint32_t)TIMER_DEVICE_MAX)
        return -RT_EINVAL;
    @OP:timer.initialize@((timer_device_number_t)device);
    return RT_EOK;
}

rt_err_t bspforge_timer_start(rt_uint32_t device, rt_uint32_t channel,
                              rt_uint64_t interval_ns, rt_bool_t single_shot,
                              bspforge_timer_handler_t handler, void *context)
{
    size_t applied;
    if (device >= (rt_uint32_t)TIMER_DEVICE_MAX ||
        channel >= (rt_uint32_t)TIMER_CHANNEL_MAX || interval_ns == 0 ||
        handler == RT_NULL)
        return -RT_EINVAL;
    applied = @OP:timer.set_interval@((timer_device_number_t)device,
                                      (timer_channel_number_t)channel,
                                      (size_t)interval_ns);
    if (applied == 0)
        return -RT_ERROR;
    if (timer_irq_register((timer_device_number_t)device,
                           (timer_channel_number_t)channel,
                           single_shot ? 1 : 0, 1,
                           (timer_callback_t)handler, context) != 0)
        return -RT_ERROR;
    timer_set_mode((timer_device_number_t)device,
                   (timer_channel_number_t)channel, TIMER_CR_USER_MODE);
    timer_enable_interrupt((timer_device_number_t)device,
                           (timer_channel_number_t)channel);
    @OP:timer.start@((timer_device_number_t)device,
                     (timer_channel_number_t)channel);
    return RT_EOK;
}

rt_err_t bspforge_timer_stop(rt_uint32_t device, rt_uint32_t channel)
{
    if (device >= (rt_uint32_t)TIMER_DEVICE_MAX ||
        channel >= (rt_uint32_t)TIMER_CHANNEL_MAX)
        return -RT_EINVAL;
    @OP:timer.stop@((timer_device_number_t)device,
                    (timer_channel_number_t)channel);
    return timer_irq_unregister((timer_device_number_t)device,
                                (timer_channel_number_t)channel) == 0
               ? RT_EOK : -RT_ERROR;
}

rt_uint32_t bspforge_timer_count(rt_uint32_t device, rt_uint32_t channel)
{
    if (device >= (rt_uint32_t)TIMER_DEVICE_MAX ||
        channel >= (rt_uint32_t)TIMER_CHANNEL_MAX)
        return 0;
    return timer[device]->channel[channel].current_value;
}
""",
    },
}


class RTThreadBindingGenerator:
    """Generate callable RT-Thread-to-SDK bindings with symbol-level evidence."""

    def generate(
        self,
        board_dir: Path,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        binding_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selections = validate_operation_plan(ir, binding_plan)
        function_index: dict[str, list[dict[str, Any]]] = {}
        for function in ir["functions"]:
            function_index.setdefault(function["name"], []).append(function)
        files_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in ir["files"]:
            files_by_name.setdefault(Path(item["path"]).name, []).append(item)

        headers: list[str] = []
        declarations: list[str] = []
        definitions: list[str] = []
        bindings: list[dict[str, Any]] = []
        required_sources: set[str] = set()
        missing: list[dict[str, str]] = []
        callable_symbols: list[str] = []

        for capability in selections:
            specification = CAPABILITY_BINDINGS[capability]
            operation_selections = selections[capability]
            selected_symbols = [
                item["selected_symbol"] for item in operation_selections.values()
            ]
            required_symbols = list(dict.fromkeys(
                selected_symbols + CAPABILITY_AUXILIARY_SYMBOLS.get(capability, [])
            ))
            callable_symbols.extend(required_symbols)
            symbol_evidence: list[dict[str, Any]] = []
            data_evidence: list[dict[str, Any]] = []
            capability_missing: list[str] = []
            for symbol in required_symbols:
                matches = function_index.get(symbol, [])
                if not matches:
                    capability_missing.append(symbol)
                    missing.append({"capability": capability, "symbol": symbol})
                    continue
                entity = matches[0]
                required_sources.add(entity["file"])
                symbol_evidence.append({
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
            if capability_missing:
                continue
            for contract in specification.get("data_contracts", []):
                headers_with_contract = files_by_name.get(contract["header"], [])
                if headers_with_contract:
                    header = min(headers_with_contract, key=lambda item: len(Path(item["path"]).parts))
                    data_evidence.append({
                        **contract,
                        "entity_id": header["id"],
                        "source": {"path": header["path"], "line": 1, "kind": "header-contract"},
                        "selection_method": "backend-contract-exported-data",
                    })
            headers.extend(specification["headers"])
            declarations.extend(specification["declarations"])
            definitions.append(
                render_operation_symbols(
                    specification["definitions"].strip(), selections
                )
            )
            bindings.append({
                "capability": capability,
                "status": "generated",
                "sdk_symbols": symbol_evidence,
                "sdk_data_contracts": data_evidence,
                "selected_operations": [
                    {
                        "operation": operation,
                        "symbol": item["selected_symbol"],
                        "entity_id": item["entity_id"],
                    }
                    for operation, item in operation_selections.items()
                ],
                "auxiliary_symbols": CAPABILITY_AUXILIARY_SYMBOLS.get(capability, []),
                "wrapper_count": sum(
                    1 for item in specification["declarations"]
                    if item.endswith(";") and not item.startswith(("typedef", "enum"))
                ),
            })

        header_path = board_dir / "bspforge_bindings.h"
        source_path = board_dir / "bspforge_bindings.c"
        header_path.write_text(self._header(declarations), encoding="utf-8")
        call_source = self._source(headers, definitions)
        operation_bindings = operation_manifest(selections, call_source)
        ir_declarations = function_declarations(function_index, callable_symbols)
        generated_source = self._source(headers, definitions, ir_declarations)
        source_path.write_text(generated_source, encoding="utf-8")
        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "backend": "rtthread",
            "binding_plan_id": binding_plan.get("id") if binding_plan else None,
            "source": str(source_path),
            "header": str(header_path),
            "source_sha256": file_sha256(source_path),
            "header_sha256": file_sha256(header_path),
            "bindings": bindings,
            "operation_bindings": operation_bindings,
            "ir_function_declarations": ir_declarations,
            "required_sources": sorted(required_sources),
            "missing_symbols": missing,
            "summary": {
                "capabilities": len(bindings),
                "wrappers": sum(item["wrapper_count"] for item in bindings),
                "required_sources": len(required_sources),
                "missing_symbols": len(missing),
                "data_contracts": sum(
                    len(item["sdk_data_contracts"]) for item in bindings
                ),
                "plan_operations": len(operation_bindings),
                "direct_plan_operations": sum(
                    item["direct_call_in_generated_source"]
                    for item in operation_bindings
                ),
            },
        }

    @staticmethod
    def _header(declarations: list[str]) -> str:
        body = "\n".join(declarations)
        return f"""/* Generated by BSPForge. Do not edit manually. */
#ifndef BSPFORGE_BINDINGS_H
#define BSPFORGE_BINDINGS_H

#include <rtthread.h>

#ifdef __cplusplus
extern \"C\" {{
#endif

{body}

#ifdef __cplusplus
}}
#endif

#endif
"""

    @staticmethod
    def _source(
        headers: list[str],
        definitions: list[str],
        ir_declarations: list[str] | None = None,
    ) -> str:
        includes = "\n".join(f'#include <{header}>' for header in sorted(set(headers)))
        prototypes = "\n".join(ir_declarations or [])
        body = "\n\n".join(definitions)
        return f"""/* Generated from SDK IR and the RT-Thread backend contract. */
#include \"bspforge_bindings.h\"
{includes}

/* Prototypes recovered from SDK implementation entities in the IR. */
{prototypes}

{body}
"""
