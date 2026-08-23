from __future__ import annotations

from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now


CAPABILITY_BINDINGS: dict[str, dict[str, Any]] = {
    "clock": {
        "headers": ["sysctl.h"],
        "symbols": ["sysctl_clock_enable", "sysctl_clock_disable", "sysctl_clock_get_freq"],
        "declarations": [
            "rt_err_t bspforge_clock_enable(rt_uint32_t clock);",
            "rt_err_t bspforge_clock_disable(rt_uint32_t clock);",
            "rt_uint32_t bspforge_clock_frequency(rt_uint32_t clock);",
        ],
        "definitions": r"""
rt_err_t bspforge_clock_enable(rt_uint32_t clock)
{
    return sysctl_clock_enable((sysctl_clock_t)clock) == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_clock_disable(rt_uint32_t clock)
{
    return sysctl_clock_disable((sysctl_clock_t)clock) == 0 ? RT_EOK : -RT_ERROR;
}

rt_uint32_t bspforge_clock_frequency(rt_uint32_t clock)
{
    return (rt_uint32_t)sysctl_clock_get_freq((sysctl_clock_t)clock);
}
""",
    },
    "interrupt": {
        "headers": ["plic.h"],
        "symbols": ["plic_init", "plic_irq_enable", "plic_irq_disable", "plic_irq_register", "plic_irq_unregister", "plic_irq_claim"],
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
    plic_init();
}

rt_err_t bspforge_irq_enable(rt_uint32_t irq)
{
    return plic_irq_enable((plic_irq_t)irq) == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_irq_disable(rt_uint32_t irq)
{
    return plic_irq_disable((plic_irq_t)irq) == 0 ? RT_EOK : -RT_ERROR;
}

void bspforge_irq_register(rt_uint32_t irq, bspforge_irq_handler_t handler, void *context)
{
    plic_irq_register((plic_irq_t)irq, (plic_irq_callback_t)handler, context);
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
        "symbols": ["uart_init", "uart_configure", "uart_send_data", "uart_receive_data"],
        "declarations": [
            "rt_err_t bspforge_uart_configure(rt_uint32_t channel, rt_uint32_t baud_rate);",
            "rt_ssize_t bspforge_uart_write(rt_uint32_t channel, const void *buffer, rt_size_t size);",
            "rt_ssize_t bspforge_uart_read(rt_uint32_t channel, void *buffer, rt_size_t size);",
        ],
        "definitions": r"""
rt_err_t bspforge_uart_configure(rt_uint32_t channel, rt_uint32_t baud_rate)
{
    if (channel >= (rt_uint32_t)UART_DEVICE_MAX || baud_rate == 0)
        return -RT_EINVAL;
    uart_init((uart_device_number_t)channel);
    uart_configure((uart_device_number_t)channel, baud_rate,
                   UART_BITWIDTH_8BIT, UART_STOP_1, UART_PARITY_NONE);
    return RT_EOK;
}

rt_ssize_t bspforge_uart_write(rt_uint32_t channel, const void *buffer, rt_size_t size)
{
    if (buffer == RT_NULL || channel >= (rt_uint32_t)UART_DEVICE_MAX)
        return -RT_EINVAL;
    return (rt_ssize_t)uart_send_data((uart_device_number_t)channel,
                                     (const char *)buffer, (size_t)size);
}

rt_ssize_t bspforge_uart_read(rt_uint32_t channel, void *buffer, rt_size_t size)
{
    if (buffer == RT_NULL || channel >= (rt_uint32_t)UART_DEVICE_MAX)
        return -RT_EINVAL;
    return (rt_ssize_t)uart_receive_data((uart_device_number_t)channel,
                                        (char *)buffer, (size_t)size);
}
""",
    },
    "gpio": {
        "headers": ["gpiohs.h"],
        "symbols": ["gpiohs_set_drive_mode", "gpiohs_get_pin", "gpiohs_set_pin", "gpiohs_set_pin_edge"],
        "declarations": [
            "void bspforge_gpio_mode(rt_uint8_t pin, rt_uint32_t mode);",
            "void bspforge_gpio_write(rt_uint8_t pin, rt_uint8_t value);",
            "rt_int32_t bspforge_gpio_read(rt_uint8_t pin);",
            "void bspforge_gpio_edge(rt_uint8_t pin, rt_uint32_t edge);",
        ],
        "definitions": r"""
void bspforge_gpio_mode(rt_uint8_t pin, rt_uint32_t mode)
{
    gpiohs_set_drive_mode(pin, (gpio_drive_mode_t)mode);
}

void bspforge_gpio_write(rt_uint8_t pin, rt_uint8_t value)
{
    gpiohs_set_pin(pin, value ? GPIO_PV_HIGH : GPIO_PV_LOW);
}

rt_int32_t bspforge_gpio_read(rt_uint8_t pin)
{
    return gpiohs_get_pin(pin) == GPIO_PV_HIGH ? 1 : 0;
}

void bspforge_gpio_edge(rt_uint8_t pin, rt_uint32_t edge)
{
    gpiohs_set_pin_edge(pin, (gpio_pin_edge_t)edge);
}
""",
    },
    "timer": {
        "headers": ["clint.h"],
        "symbols": ["clint_timer_init", "clint_timer_start", "clint_timer_stop", "clint_timer_set_interval"],
        "declarations": [
            "rt_err_t bspforge_timer_initialize(void);",
            "rt_err_t bspforge_timer_start(rt_uint64_t interval, rt_bool_t single_shot);",
            "rt_err_t bspforge_timer_stop(void);",
            "rt_err_t bspforge_timer_set_interval(rt_uint64_t interval);",
        ],
        "definitions": r"""
rt_err_t bspforge_timer_initialize(void)
{
    return clint_timer_init() == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_timer_start(rt_uint64_t interval, rt_bool_t single_shot)
{
    return clint_timer_start((uint64_t)interval, single_shot ? 1 : 0) == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_timer_stop(void)
{
    return clint_timer_stop() == 0 ? RT_EOK : -RT_ERROR;
}

rt_err_t bspforge_timer_set_interval(rt_uint64_t interval)
{
    return clint_timer_set_interval((uint64_t)interval) == 0 ? RT_EOK : -RT_ERROR;
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
    ) -> dict[str, Any]:
        function_index: dict[str, list[dict[str, Any]]] = {}
        for function in ir["functions"]:
            function_index.setdefault(function["name"], []).append(function)

        resolved = {
            item["capability"]
            for item in resolution["mappings"]
            if item["status"] == "resolved"
        }
        headers: list[str] = []
        declarations: list[str] = []
        definitions: list[str] = []
        bindings: list[dict[str, Any]] = []
        required_sources: set[str] = set()
        missing: list[dict[str, str]] = []

        for capability, specification in CAPABILITY_BINDINGS.items():
            if capability not in resolved:
                continue
            symbol_evidence: list[dict[str, Any]] = []
            capability_missing: list[str] = []
            for symbol in specification["symbols"]:
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
                })
            if capability_missing:
                continue
            headers.extend(specification["headers"])
            declarations.extend(specification["declarations"])
            definitions.append(specification["definitions"].strip())
            bindings.append({
                "capability": capability,
                "status": "generated",
                "sdk_symbols": symbol_evidence,
                "wrapper_count": sum(
                    1 for item in specification["declarations"]
                    if item.endswith(";") and not item.startswith("typedef")
                ),
            })

        header_path = board_dir / "bspforge_bindings.h"
        source_path = board_dir / "bspforge_bindings.c"
        header_path.write_text(self._header(declarations), encoding="utf-8")
        source_path.write_text(self._source(headers, definitions), encoding="utf-8")
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "backend": "rtthread",
            "source": str(source_path),
            "header": str(header_path),
            "source_sha256": file_sha256(source_path),
            "header_sha256": file_sha256(header_path),
            "bindings": bindings,
            "required_sources": sorted(required_sources),
            "missing_symbols": missing,
            "summary": {
                "capabilities": len(bindings),
                "wrappers": sum(item["wrapper_count"] for item in bindings),
                "required_sources": len(required_sources),
                "missing_symbols": len(missing),
            },
        }

    @staticmethod
    def _header(declarations: list[str]) -> str:
        body = "\n".join(declarations)
        return f"""/* 由 BSPForge 自动生成；请勿手工修改。 */
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
    def _source(headers: list[str], definitions: list[str]) -> str:
        includes = "\n".join(f'#include <{header}>' for header in sorted(set(headers)))
        body = "\n\n".join(definitions)
        return f"""/* 由 BSPForge 根据 SDK IR 和 RT-Thread 契约自动生成。 */
#include \"bspforge_bindings.h\"
{includes}

{body}
"""
