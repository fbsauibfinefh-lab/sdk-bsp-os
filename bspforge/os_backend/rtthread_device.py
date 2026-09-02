from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now


DEFAULT_DEVICE_CONFIG: dict[str, Any] = {
    "uart": [
        {"name": "bspuart1", "channel": 0, "baud_rate": 115200},
    ],
    "pin": {"name": "bsppin", "max_pins": 32, "skip_if_device_exists": "pin"},
    "hwtimer": [
        {"name": "bsptim0", "device": 0, "channel": 0, "frequency": 1_000_000},
    ],
}


class RTThreadDeviceModelGenerator:
    """Generate native RT-Thread device objects backed by callable SDK bindings."""

    def generate(
        self,
        generated_bsp: Path,
        binding_manifest: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capabilities = {item["capability"] for item in binding_manifest["bindings"]}
        normalized = self._normalize_config(config or {})
        board_source = generated_bsp / "board" / "bspforge_devices.c"
        timer_source = generated_bsp / "drivers" / "drv_hw_timer.c"
        devices: list[dict[str, Any]] = []
        operation_tables: list[str] = []
        registration_symbols: list[str] = []
        sources: list[Path] = []
        required_features: list[str] = []

        uart_devices = normalized["uart"] if "uart" in capabilities else []
        pin_device = normalized["pin"] if "gpio" in capabilities else None
        if uart_devices or pin_device:
            board_source.write_text(
                self._board_source(uart_devices, pin_device), encoding="utf-8"
            )
            sources.append(board_source)
            registration_symbols.append("bspforge_rtthread_devices_init")
        if uart_devices:
            required_features.append("RT_USING_SERIAL")
            operation_tables.append("bspforge_uart_ops")
            devices.extend(
                {
                    "class": "serial",
                    "name": item["name"],
                    "channel": item["channel"],
                    "baud_rate": item["baud_rate"],
                    "operations": ["configure", "control", "putc", "getc"],
                    "registration": "rt_hw_serial_register",
                }
                for item in uart_devices
            )
        if pin_device:
            required_features.append("RT_USING_PIN")
            operation_tables.append("bspforge_pin_ops")
            devices.append({
                "class": "pin",
                "name": pin_device["name"],
                "max_pins": pin_device["max_pins"],
                "operations": [
                    "pin_mode",
                    "pin_write",
                    "pin_read",
                    "pin_attach_irq",
                    "pin_detach_irq",
                    "pin_irq_enable",
                ],
                "registration": "rt_device_pin_register",
                "skip_if_device_exists": pin_device["skip_if_device_exists"],
            })

        timer_devices = normalized["hwtimer"] if "timer" in capabilities else []
        if timer_devices:
            timer_source.parent.mkdir(parents=True, exist_ok=True)
            timer_source.write_text(self._timer_source(timer_devices), encoding="utf-8")
            sources.append(timer_source)
            required_features.append("RT_USING_HWTIMER")
            operation_tables.append("bspforge_hwtimer_ops")
            registration_symbols.append("bspforge_hwtimer_devices_init")
            devices.extend(
                {
                    "class": "hwtimer",
                    "name": item["name"],
                    "device": item["device"],
                    "channel": item["channel"],
                    "frequency": item["frequency"],
                    "operations": ["init", "start", "stop", "count_get", "control"],
                    "registration": "rt_device_hwtimer_register",
                }
                for item in timer_devices
            )

        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "backend": "rtthread",
            "configuration": normalized,
            "devices": devices,
            "sources": [str(path) for path in sources],
            "source_sha256": {str(path): file_sha256(path) for path in sources},
            "operation_tables": operation_tables,
            "registration_symbols": registration_symbols,
            "required_rtthread_features": sorted(set(required_features)),
            "summary": {
                "devices": len(devices),
                "serial": sum(item["class"] == "serial" for item in devices),
                "pin": sum(item["class"] == "pin" for item in devices),
                "hwtimer": sum(item["class"] == "hwtimer" for item in devices),
                "operation_tables": len(operation_tables),
                "registration_functions": len(registration_symbols),
            },
        }

    @classmethod
    def _normalize_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "uart": config.get("uart", DEFAULT_DEVICE_CONFIG["uart"]),
            "pin": config.get("pin", DEFAULT_DEVICE_CONFIG["pin"]),
            "hwtimer": config.get("hwtimer", DEFAULT_DEVICE_CONFIG["hwtimer"]),
        }
        names: set[str] = set()
        for group in (merged["uart"], merged["hwtimer"]):
            if not isinstance(group, list):
                raise ValueError("UART and hwtimer device configuration must be lists")
            for item in group:
                cls._validate_name(item["name"], names)
        if merged["pin"] is not None:
            if not isinstance(merged["pin"], dict):
                raise ValueError("Pin device configuration must be an object or null")
            cls._validate_name(merged["pin"]["name"], names)

        uart = []
        for item in merged["uart"]:
            channel = int(item["channel"])
            baud_rate = int(item.get("baud_rate", 115200))
            if channel < 0 or channel > 2 or baud_rate <= 0:
                raise ValueError(f"Invalid UART device configuration: {item}")
            uart.append({"name": item["name"], "channel": channel, "baud_rate": baud_rate})

        pin = None
        if merged["pin"] is not None:
            max_pins = int(merged["pin"].get("max_pins", 32))
            if max_pins < 1 or max_pins > 32:
                raise ValueError("K210 GPIOHS max_pins must be between 1 and 32")
            skip_if_device_exists = merged["pin"].get("skip_if_device_exists", "pin")
            if skip_if_device_exists is not None:
                cls._validate_device_name(skip_if_device_exists)
            pin = {
                "name": merged["pin"]["name"],
                "max_pins": max_pins,
                "skip_if_device_exists": skip_if_device_exists,
            }

        hwtimer = []
        occupied: set[tuple[int, int]] = set()
        for item in merged["hwtimer"]:
            device = int(item["device"])
            channel = int(item["channel"])
            frequency = int(item.get("frequency", 1_000_000))
            key = (device, channel)
            if device < 0 or device > 2 or channel < 0 or channel > 3:
                raise ValueError(f"Invalid K210 timer device/channel: {item}")
            if frequency < 1 or frequency > 10_000_000:
                raise ValueError(f"Invalid hwtimer frequency: {frequency}")
            if key in occupied:
                raise ValueError(f"Duplicate K210 timer device/channel: {key}")
            occupied.add(key)
            hwtimer.append({
                "name": item["name"],
                "device": device,
                "channel": channel,
                "frequency": frequency,
            })
        return {"uart": uart, "pin": pin, "hwtimer": hwtimer}

    @staticmethod
    def _validate_name(name: str, existing: set[str]) -> None:
        RTThreadDeviceModelGenerator._validate_device_name(name)
        if name in existing:
            raise ValueError(f"Duplicate RT-Thread device name: {name}")
        existing.add(name)

    @staticmethod
    def _validate_device_name(name: str) -> None:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name):
            raise ValueError(f"Invalid RT-Thread device name: {name!r}")

    @staticmethod
    def _board_source(uarts: list[dict[str, Any]], pin: dict[str, Any] | None) -> str:
        sections: list[str] = []
        registrations: list[str] = []
        if uarts:
            contexts = ",\n".join(
                f"    {{{item['channel']}U, {item['baud_rate']}U}}" for item in uarts
            )
            serials = "\n".join(
                f'''    bspforge_uart_devices[{index}].ops = &bspforge_uart_ops;
    bspforge_uart_devices[{index}].config = (struct serial_configure)RT_SERIAL_CONFIG_DEFAULT;
    bspforge_uart_devices[{index}].config.baud_rate = bspforge_uart_contexts[{index}].baud_rate;
    result = rt_hw_serial_register(&bspforge_uart_devices[{index}], "{item['name']}",
                                   RT_DEVICE_FLAG_RDWR,
                                   &bspforge_uart_contexts[{index}]);
    if (result != RT_EOK)
        return result;'''
                for index, item in enumerate(uarts)
            )
            sections.append(f"""
#ifdef RT_USING_SERIAL
struct bspforge_uart_context
{{
    rt_uint32_t channel;
    rt_uint32_t baud_rate;
}};

static struct bspforge_uart_context bspforge_uart_contexts[] =
{{
{contexts}
}};
static struct rt_serial_device bspforge_uart_devices[{len(uarts)}];

static rt_err_t bspforge_serial_configure(struct rt_serial_device *serial,
                                          struct serial_configure *configuration)
{{
    struct bspforge_uart_context *context = serial->parent.user_data;
    rt_uint8_t stop_bits = configuration->stop_bits == STOP_BITS_2 ? 2U : 1U;
    rt_err_t result = bspforge_uart_configure(context->channel,
                                              configuration->baud_rate,
                                              configuration->data_bits,
                                              stop_bits,
                                              configuration->parity);
    if (result == RT_EOK)
        serial->config = *configuration;
    return result;
}}

static rt_err_t bspforge_serial_control(struct rt_serial_device *serial,
                                        int command, void *argument)
{{
    RT_UNUSED(serial);
    RT_UNUSED(command);
    RT_UNUSED(argument);
    return -RT_ENOSYS;
}}

static int bspforge_serial_putc(struct rt_serial_device *serial, char value)
{{
    struct bspforge_uart_context *context = serial->parent.user_data;
    return bspforge_uart_write(context->channel, &value, 1U) == 1 ? 1 : -1;
}}

static int bspforge_serial_getc(struct rt_serial_device *serial)
{{
    struct bspforge_uart_context *context = serial->parent.user_data;
    rt_uint8_t value = 0;
    return bspforge_uart_read(context->channel, &value, 1U) == 1
               ? (int)value : -1;
}}

static const struct rt_uart_ops bspforge_uart_ops =
{{
    bspforge_serial_configure,
    bspforge_serial_control,
    bspforge_serial_putc,
    bspforge_serial_getc,
    RT_NULL
}};
#endif
""".strip())
            registrations.append(f"""
#ifdef RT_USING_SERIAL
{serials}
#endif
""".strip())

        if pin:
            max_pins = pin["max_pins"]
            guard_begin = ""
            guard_end = ""
            if pin["skip_if_device_exists"] is not None:
                guard_begin = (
                    f'    if (rt_device_find("{pin["skip_if_device_exists"]}") == RT_NULL)\n'
                    "    {\n"
                )
                guard_end = "    }\n"
            sections.append(f"""
#ifdef RT_USING_PIN
#define BSPFORGE_PIN_COUNT {max_pins}U

struct bspforge_pin_irq
{{
    void (*handler)(void *argument);
    void *argument;
    rt_uint8_t mode;
}};

static struct bspforge_pin_irq bspforge_pin_irqs[BSPFORGE_PIN_COUNT];

static int bspforge_pin_irq_bridge(void *argument)
{{
    struct bspforge_pin_irq *entry = argument;
    if (entry != RT_NULL && entry->handler != RT_NULL)
        entry->handler(entry->argument);
    return 0;
}}

static void bspforge_pin_mode(struct rt_device *device, rt_base_t pin,
                              rt_uint8_t mode)
{{
    rt_uint8_t normalized;
    RT_UNUSED(device);
    switch (mode)
    {{
    case PIN_MODE_OUTPUT:
        normalized = BSPFORGE_GPIO_OUTPUT;
        break;
    case PIN_MODE_INPUT:
        normalized = BSPFORGE_GPIO_INPUT;
        break;
    case PIN_MODE_INPUT_PULLUP:
        normalized = BSPFORGE_GPIO_INPUT_PULL_UP;
        break;
    case PIN_MODE_INPUT_PULLDOWN:
        normalized = BSPFORGE_GPIO_INPUT_PULL_DOWN;
        break;
    default:
        return;
    }}
    if (pin >= 0 && pin < (rt_base_t)BSPFORGE_PIN_COUNT)
        (void)bspforge_gpio_mode((rt_uint8_t)pin, normalized);
}}

static void bspforge_pin_write(struct rt_device *device, rt_base_t pin,
                               rt_uint8_t value)
{{
    RT_UNUSED(device);
    if (pin >= 0 && pin < (rt_base_t)BSPFORGE_PIN_COUNT)
        (void)bspforge_gpio_write((rt_uint8_t)pin, value == PIN_HIGH ? 1U : 0U);
}}

static rt_ssize_t bspforge_pin_read(struct rt_device *device, rt_base_t pin)
{{
    RT_UNUSED(device);
    if (pin < 0 || pin >= (rt_base_t)BSPFORGE_PIN_COUNT)
        return -RT_EINVAL;
    return (rt_ssize_t)bspforge_gpio_read((rt_uint8_t)pin);
}}

static rt_err_t bspforge_pin_attach_irq(struct rt_device *device, rt_base_t pin,
                                        rt_uint8_t mode,
                                        void (*handler)(void *argument),
                                        void *argument)
{{
    RT_UNUSED(device);
    if (pin < 0 || pin >= (rt_base_t)BSPFORGE_PIN_COUNT || handler == RT_NULL)
        return -RT_EINVAL;
    bspforge_pin_irqs[pin].handler = handler;
    bspforge_pin_irqs[pin].argument = argument;
    bspforge_pin_irqs[pin].mode = mode;
    return RT_EOK;
}}

static rt_err_t bspforge_pin_detach_irq(struct rt_device *device, rt_base_t pin)
{{
    RT_UNUSED(device);
    if (pin < 0 || pin >= (rt_base_t)BSPFORGE_PIN_COUNT)
        return -RT_EINVAL;
    bspforge_gpio_irq_unregister((rt_uint8_t)pin);
    rt_memset(&bspforge_pin_irqs[pin], 0, sizeof(bspforge_pin_irqs[pin]));
    return RT_EOK;
}}

static rt_err_t bspforge_pin_irq_enable(struct rt_device *device, rt_base_t pin,
                                        rt_uint8_t enabled)
{{
    struct bspforge_pin_irq *entry;
    rt_uint8_t edge;
    RT_UNUSED(device);
    if (pin < 0 || pin >= (rt_base_t)BSPFORGE_PIN_COUNT)
        return -RT_EINVAL;
    entry = &bspforge_pin_irqs[pin];
    if (enabled == PIN_IRQ_DISABLE)
    {{
        bspforge_gpio_irq_unregister((rt_uint8_t)pin);
        return RT_EOK;
    }}
    if (entry->handler == RT_NULL)
        return -RT_EINVAL;
    switch (entry->mode)
    {{
    case PIN_IRQ_MODE_RISING:
        edge = BSPFORGE_GPIO_RISING;
        break;
    case PIN_IRQ_MODE_FALLING:
        edge = BSPFORGE_GPIO_FALLING;
        break;
    case PIN_IRQ_MODE_RISING_FALLING:
        edge = BSPFORGE_GPIO_BOTH;
        break;
    case PIN_IRQ_MODE_HIGH_LEVEL:
        edge = BSPFORGE_GPIO_HIGH_LEVEL;
        break;
    case PIN_IRQ_MODE_LOW_LEVEL:
        edge = BSPFORGE_GPIO_LOW_LEVEL;
        break;
    default:
        return -RT_EINVAL;
    }}
    return bspforge_gpio_irq_register((rt_uint8_t)pin, edge,
                                      bspforge_pin_irq_bridge, entry);
}}

static const struct rt_pin_ops bspforge_pin_ops =
{{
    bspforge_pin_mode,
    bspforge_pin_write,
    bspforge_pin_read,
    bspforge_pin_attach_irq,
    bspforge_pin_detach_irq,
    bspforge_pin_irq_enable
}};
#endif
""".strip())
            registrations.append(f"""
#ifdef RT_USING_PIN
{guard_begin.rstrip()}
    result = rt_device_pin_register("{pin['name']}", &bspforge_pin_ops, RT_NULL);
    if (result != RT_EOK)
        return result;
{guard_end.rstrip()}
#endif
""".strip())

        return f"""/* Generated by BSPForge from RT-Thread device contracts. */
#include <rtthread.h>
#include <rtdevice.h>
#include \"bspforge_bindings.h\"

{chr(10).join(sections)}

static int bspforge_rtthread_devices_init(void)
{{
    rt_err_t result = RT_EOK;
{chr(10).join(registrations)}
    return result;
}}
INIT_DEVICE_EXPORT(bspforge_rtthread_devices_init);
"""

    @staticmethod
    def _timer_source(timers: list[dict[str, Any]]) -> str:
        contexts = ",\n".join(
            f"    {{{item['device']}U, {item['channel']}U, RT_NULL}}" for item in timers
        )
        registrations = "\n".join(
            f'''    bspforge_hwtimers[{index}].ops = &bspforge_hwtimer_ops;
    bspforge_hwtimers[{index}].info = &bspforge_hwtimer_info;
    bspforge_hwtimers[{index}].freq = {item['frequency']};
    bspforge_hwtimer_contexts[{index}].timer = &bspforge_hwtimers[{index}];
    result = rt_device_hwtimer_register(&bspforge_hwtimers[{index}], "{item['name']}",
                                        &bspforge_hwtimer_contexts[{index}]);
    if (result != RT_EOK)
        return result;'''
            for index, item in enumerate(timers)
        )
        return f"""/* Generated by BSPForge from the RT-Thread hwtimer contract. */
#include <rtthread.h>
#include <rtdevice.h>
#include \"../board/bspforge_bindings.h\"

#ifdef RT_USING_HWTIMER
struct bspforge_hwtimer_context
{{
    rt_uint32_t device;
    rt_uint32_t channel;
    rt_hwtimer_t *timer;
}};

static rt_hwtimer_t bspforge_hwtimers[{len(timers)}];
static struct bspforge_hwtimer_context bspforge_hwtimer_contexts[] =
{{
{contexts}
}};

static int bspforge_hwtimer_callback(void *argument)
{{
    struct bspforge_hwtimer_context *context = argument;
    if (context != RT_NULL && context->timer != RT_NULL)
        rt_device_hwtimer_isr(context->timer);
    return 0;
}}

static void bspforge_hwtimer_init(struct rt_hwtimer_device *timer,
                                  rt_uint32_t state)
{{
    struct bspforge_hwtimer_context *context = timer->parent.user_data;
    if (state)
        (void)bspforge_timer_initialize(context->device);
    else
        (void)bspforge_timer_stop(context->device, context->channel);
}}

static rt_err_t bspforge_hwtimer_start(struct rt_hwtimer_device *timer,
                                       rt_uint32_t count,
                                       rt_hwtimer_mode_t mode)
{{
    struct bspforge_hwtimer_context *context = timer->parent.user_data;
    rt_uint64_t interval_ns;
    if (timer->freq <= 0 || count == 0)
        return -RT_EINVAL;
    interval_ns = ((rt_uint64_t)count * 1000000000ULL) /
                  (rt_uint64_t)timer->freq;
    return bspforge_timer_start(context->device, context->channel,
                                interval_ns,
                                mode == HWTIMER_MODE_ONESHOT,
                                bspforge_hwtimer_callback, context);
}}

static void bspforge_hwtimer_stop(struct rt_hwtimer_device *timer)
{{
    struct bspforge_hwtimer_context *context = timer->parent.user_data;
    (void)bspforge_timer_stop(context->device, context->channel);
}}

static rt_uint32_t bspforge_hwtimer_count_get(struct rt_hwtimer_device *timer)
{{
    struct bspforge_hwtimer_context *context = timer->parent.user_data;
    return bspforge_timer_count(context->device, context->channel);
}}

static rt_err_t bspforge_hwtimer_control(struct rt_hwtimer_device *timer,
                                         rt_uint32_t command, void *argument)
{{
    RT_UNUSED(timer);
    if (command == HWTIMER_CTRL_FREQ_SET && argument != RT_NULL)
    {{
        rt_uint32_t frequency = *(rt_uint32_t *)argument;
        return frequency >= 1U && frequency <= 10000000U
                   ? RT_EOK : -RT_EINVAL;
    }}
    return -RT_ENOSYS;
}}

static const struct rt_hwtimer_ops bspforge_hwtimer_ops =
{{
    bspforge_hwtimer_init,
    bspforge_hwtimer_start,
    bspforge_hwtimer_stop,
    bspforge_hwtimer_count_get,
    bspforge_hwtimer_control
}};

static const struct rt_hwtimer_info bspforge_hwtimer_info =
{{
    10000000,
    1,
    0xffffffffU,
    HWTIMER_CNTMODE_DW
}};

static int bspforge_hwtimer_devices_init(void)
{{
    rt_err_t result = RT_EOK;
{registrations}
    return result;
}}
INIT_DEVICE_EXPORT(bspforge_hwtimer_devices_init);
#endif
"""
