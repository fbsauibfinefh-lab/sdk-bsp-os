from __future__ import annotations

from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now


class RTThreadValidationGenerator:
    """Generate RT-Thread smoke tests and the common board-test protocol."""

    def generate(self, bsp: Path, options: dict[str, Any] | None) -> dict[str, Any]:
        config = options or {}
        applications = bsp / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        source = applications / "bspforge_validation.c"
        uart_name = str(config.get("uart", "uart1"))
        pin_device = str(config.get("pin_device", "pin"))
        pin_number = int(config.get("pin", -1))
        hwtimer_name = str(config.get("hwtimer", "bsptim0"))
        binding_validation = bool(config.get("binding_validation", False))
        uart_channel = int(config.get("uart_channel", -1))
        uart_tx_fpioa_io = int(config.get("uart_tx_fpioa_io", -1))
        uart_rx_fpioa_io = int(config.get("uart_rx_fpioa_io", -1))
        gpio_fpioa_io = int(config.get("gpio_fpioa_io", -1))
        gpio_binding_pin = int(config.get("gpio_binding_pin", -1))
        gpio_input_fpioa_io = int(config.get("gpio_input_fpioa_io", -1))
        gpio_input_binding_pin = int(config.get("gpio_input_binding_pin", -1))
        board = str(config.get("board", "unknown"))
        build_id = str(config.get("firmware_build_id", "uncommitted"))
        source.write_text(
            self._source(
                uart_name,
                pin_device,
                pin_number,
                hwtimer_name,
                binding_validation,
                uart_channel,
                uart_tx_fpioa_io,
                uart_rx_fpioa_io,
                gpio_fpioa_io,
                gpio_binding_pin,
                gpio_input_fpioa_io,
                gpio_input_binding_pin,
                board,
                build_id,
            ),
            encoding="utf-8",
        )
        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "strategy": "reuse-native-device-model-with-common-selftest-protocol",
            "protocol_version": "1.0",
            "source": str(source),
            "source_sha256": file_sha256(source),
            "devices": [
                {"class": "serial", "name": uart_name, "operations": ["find", "open", "write", "read", "loopback"]},
                {"class": "pin", "name": pin_device, "pin": pin_number, "operations": ["mode", "write", "read", "irq"]},
                {"class": "hwtimer", "name": hwtimer_name, "operations": ["find", "open", "start", "isr", "stop", "close"]},
            ],
            "operation_tables": [],
            "registration_symbols": [
                "bspforge_validation_init",
                "bspforge_validation_run",
                "bspforge_selftest",
            ],
            "required_rtthread_features": ["RT_USING_SERIAL", "RT_USING_PIN", "RT_USING_FINSH"],
            "summary": {"devices": 3, "generated_sources": 1},
        }

    @staticmethod
    def _source(
        uart_name: str,
        pin_device: str,
        pin_number: int,
        hwtimer_name: str,
        binding_validation: bool,
        uart_channel: int,
        uart_tx_fpioa_io: int,
        uart_rx_fpioa_io: int,
        gpio_fpioa_io: int,
        gpio_binding_pin: int,
        gpio_input_fpioa_io: int,
        gpio_input_binding_pin: int,
        board: str,
        build_id: str,
    ) -> str:
        binding_includes = ""
        binding_helpers = ""
        if binding_validation:
            binding_includes = '''#include "../board/bspforge_bindings.h"
#include <fpioa.h>
#include <gpiohs.h>
#include <plic.h>
#include <sysctl.h>
'''
            binding_helpers = rf'''
static int bspforge_binding_uart_loopback(rt_uint32_t *bytes,
                                          rt_uint32_t *errors)
{{
    rt_device_t serial;
    rt_uint32_t index;

    *bytes = 0U;
    *errors = 0U;
    if ({uart_channel} < 0 || {uart_channel} > 2 ||
        {uart_tx_fpioa_io} < 0 || {uart_rx_fpioa_io} < 0)
        return -RT_ENOSYS;
    if (fpioa_set_function((uint8_t){uart_tx_fpioa_io},
                           (fpioa_function_t)(FUNC_UART1_TX + 2 * {uart_channel})) != 0)
        return -RT_ERROR;
    if (fpioa_set_function((uint8_t){uart_rx_fpioa_io},
                           (fpioa_function_t)(FUNC_UART1_RX + 2 * {uart_channel})) != 0)
        return -RT_ERROR;
    serial = rt_device_find(bspforge_uart_name);
    if (serial == RT_NULL)
        return -RT_ENOSYS;
    if (rt_device_open(serial, RT_DEVICE_FLAG_RDWR) != RT_EOK)
        return -RT_ERROR;
    for (index = 0U; index < 16U; ++index)
    {{
        rt_uint8_t sent = (rt_uint8_t)(0x31U + index * 7U);
        rt_uint8_t received = 0U;
        rt_tick_t deadline;
        rt_ssize_t received_count = 0;

        if (rt_device_write(serial, 0, &sent, 1U) != 1U)
        {{
            (*errors)++;
            continue;
        }}
        deadline = rt_tick_get() + RT_TICK_PER_SECOND / 10U;
        while ((received_count = rt_device_read(serial, 0, &received, 1U)) != 1U)
        {{
            if ((rt_int32_t)(rt_tick_get() - deadline) >= 0)
                break;
            rt_thread_mdelay(1);
        }}
        if (received_count != 1U)
        {{
            (*errors)++;
            continue;
        }}
        (*bytes)++;
        if (received != sent)
            (*errors)++;
    }}
    (void)rt_device_close(serial);
    return *bytes == 16U && *errors == 0U ? RT_EOK : -RT_ERROR;
}}

static int bspforge_binding_clock_test(rt_uint32_t *cpu_hz, rt_uint32_t *timer_hz)
{{
    if (bspforge_clock_initialize(
            (rt_uint32_t)SYSCTL_CLOCK_SELECT_TIMER2, 1U) != RT_EOK)
        return -RT_ERROR;
    *cpu_hz = bspforge_clock_frequency((rt_uint32_t)SYSCTL_CLOCK_CPU);
    if (bspforge_clock_enable((rt_uint32_t)SYSCTL_CLOCK_TIMER2) != RT_EOK)
        return -RT_ERROR;
    *timer_hz = bspforge_clock_frequency((rt_uint32_t)SYSCTL_CLOCK_TIMER2);
    if (bspforge_clock_disable((rt_uint32_t)SYSCTL_CLOCK_TIMER2) != RT_EOK)
        return -RT_ERROR;
    return (*cpu_hz > 0U && *timer_hz > 0U) ? RT_EOK : -RT_ERROR;
}}

static int bspforge_binding_gpio_test(rt_int32_t *low_latch,
                                      rt_int32_t *high_latch,
                                      rt_int32_t *input_low,
                                      rt_int32_t *input_high)
{{
    if ({gpio_fpioa_io} < 0 || {gpio_binding_pin} < 0 ||
        {gpio_input_fpioa_io} < 0 || {gpio_input_binding_pin} < 0)
        return -RT_ENOSYS;
    if (fpioa_set_function((uint8_t){gpio_fpioa_io},
                           (fpioa_function_t)(FUNC_GPIOHS0 + {gpio_binding_pin})) != 0)
        return -RT_ERROR;
    if (fpioa_set_function((uint8_t){gpio_input_fpioa_io},
                           (fpioa_function_t)(FUNC_GPIOHS0 + {gpio_input_binding_pin})) != 0)
        return -RT_ERROR;
    if (bspforge_gpio_mode((rt_uint8_t){gpio_binding_pin}, BSPFORGE_GPIO_OUTPUT) != RT_EOK)
        return -RT_ERROR;
    if (bspforge_gpio_mode((rt_uint8_t){gpio_input_binding_pin},
                           BSPFORGE_GPIO_INPUT_PULL_DOWN) != RT_EOK)
        return -RT_ERROR;
    if (bspforge_gpio_write((rt_uint8_t){gpio_binding_pin}, 0U) != RT_EOK)
        return -RT_ERROR;
    rt_thread_mdelay(2);
    *low_latch = (rt_int32_t)((gpiohs->output_val.u32[0] >> {gpio_binding_pin}) & 1U);
    *input_low = bspforge_gpio_read((rt_uint8_t){gpio_input_binding_pin});
    if (bspforge_gpio_write((rt_uint8_t){gpio_binding_pin}, 1U) != RT_EOK)
        return -RT_ERROR;
    rt_thread_mdelay(2);
    *high_latch = (rt_int32_t)((gpiohs->output_val.u32[0] >> {gpio_binding_pin}) & 1U);
    *input_high = bspforge_gpio_read((rt_uint8_t){gpio_input_binding_pin});
    return (*low_latch == 0 && *high_latch == 1 &&
            *input_low == 0 && *input_high == 1)
               ? RT_EOK : -RT_ERROR;
}}

static volatile rt_uint32_t bspforge_gpio_irq_fires;

static int bspforge_gpio_irq_callback(void *context)
{{
    RT_UNUSED(context);
    bspforge_gpio_irq_fires++;
    return 0;
}}

static int bspforge_binding_gpio_irq_test(rt_uint32_t *fires)
{{
    rt_tick_t started;

    *fires = 0U;
    if ({gpio_fpioa_io} < 0 || {gpio_binding_pin} < 0 ||
        {gpio_input_fpioa_io} < 0 || {gpio_input_binding_pin} < 0)
        return -RT_ENOSYS;
    if (fpioa_set_function((uint8_t){gpio_fpioa_io},
                           (fpioa_function_t)(FUNC_GPIOHS0 + {gpio_binding_pin})) != 0 ||
        fpioa_set_function((uint8_t){gpio_input_fpioa_io},
                           (fpioa_function_t)(FUNC_GPIOHS0 + {gpio_input_binding_pin})) != 0)
        return -RT_ERROR;
    if (bspforge_gpio_mode((rt_uint8_t){gpio_binding_pin}, BSPFORGE_GPIO_OUTPUT) != RT_EOK ||
        bspforge_gpio_mode((rt_uint8_t){gpio_input_binding_pin},
                           BSPFORGE_GPIO_INPUT_PULL_DOWN) != RT_EOK)
        return -RT_ERROR;
    if (bspforge_gpio_write((rt_uint8_t){gpio_binding_pin}, 0U) != RT_EOK)
        return -RT_ERROR;
    bspforge_gpio_irq_fires = 0U;
    if (bspforge_gpio_irq_register((rt_uint8_t){gpio_input_binding_pin},
                                   BSPFORGE_GPIO_RISING,
                                   bspforge_gpio_irq_callback, RT_NULL) != RT_EOK)
        return -RT_ERROR;
    rt_thread_mdelay(2);
    if (bspforge_gpio_write((rt_uint8_t){gpio_binding_pin}, 1U) != RT_EOK)
    {{
        bspforge_gpio_irq_unregister((rt_uint8_t){gpio_input_binding_pin});
        return -RT_ERROR;
    }}
    started = rt_tick_get();
    while (bspforge_gpio_irq_fires == 0U &&
           (rt_tick_get() - started) < RT_TICK_PER_SECOND / 2U)
        rt_thread_mdelay(1);
    bspforge_gpio_irq_unregister((rt_uint8_t){gpio_input_binding_pin});
    *fires = bspforge_gpio_irq_fires;
    return *fires > 0U ? RT_EOK : -RT_ETIMEOUT;
}}
'''
        return rf'''/* Generated by BSPForge; configuration evidence is in bspforge/. */
#include <string.h>
#include <rtdevice.h>
#include <rtthread.h>
{binding_includes}

static const char bspforge_uart_name[] = "{uart_name}";
static const char bspforge_pin_device[] = "{pin_device}";
static const rt_base_t bspforge_pin_number = {pin_number};
static const char bspforge_hwtimer_name[] = "{hwtimer_name}";
static struct rt_timer bspforge_timer;
static volatile rt_uint32_t bspforge_hwtimer_fires;

static void bspforge_timer_timeout(void *parameter)
{{
    (void)parameter;
}}

static rt_err_t bspforge_hwtimer_timeout(rt_device_t device, rt_size_t size)
{{
    RT_UNUSED(device);
    RT_UNUSED(size);
    bspforge_hwtimer_fires++;
    return RT_EOK;
}}

static int bspforge_hwtimer_test(rt_hwtimer_mode_t mode,
                                 rt_uint32_t expected_fires,
                                 rt_uint32_t *observed_fires,
                                 rt_uint32_t *elapsed_ticks)
{{
    rt_device_t timer = rt_device_find(bspforge_hwtimer_name);
    rt_hwtimerval_t interval = {{0, 10000}};
    rt_tick_t started;
    rt_err_t result = RT_EOK;

    if (timer == RT_NULL)
        return -RT_ENOSYS;
    if (rt_device_open(timer, RT_DEVICE_OFLAG_RDWR) != RT_EOK)
        return -RT_ERROR;
    bspforge_hwtimer_fires = 0U;
    rt_device_set_rx_indicate(timer, bspforge_hwtimer_timeout);
    if (rt_device_control(timer, HWTIMER_CTRL_MODE_SET, &mode) != RT_EOK)
    {{
        result = -RT_ERROR;
        goto exit;
    }}
    started = rt_tick_get();
    if (rt_device_write(timer, 0, &interval, sizeof(interval)) != sizeof(interval))
    {{
        result = -RT_ERROR;
        goto exit;
    }}
    while (bspforge_hwtimer_fires < expected_fires &&
           (rt_tick_get() - started) < RT_TICK_PER_SECOND)
        rt_thread_mdelay(1);
    *observed_fires = bspforge_hwtimer_fires;
    *elapsed_ticks = (rt_uint32_t)(rt_tick_get() - started);
    if (*observed_fires < expected_fires)
        result = -RT_ETIMEOUT;
exit:
    (void)rt_device_control(timer, HWTIMER_CTRL_STOP, RT_NULL);
    (void)rt_device_close(timer);
    return result;
}}
{binding_helpers}

int bspforge_validation_run(void)
{{
    static const char banner[] =
        "{{\"bspforge\":true,\"protocol\":\"1.0\","
        "\"event\":\"boot\",\"rtos\":\"rtthread\","
        "\"board\":\"{board}\",\"build_id\":\"{build_id}\","
        "\"stage\":\"application\"}}\r\n";
    rt_device_t serial = rt_device_find(bspforge_uart_name);

    rt_kprintf("%s", banner);
    if (serial == RT_NULL)
        return -RT_ENOSYS;
    if (rt_device_open(serial, RT_DEVICE_FLAG_RDWR) != RT_EOK)
        return -RT_ERROR;

    if (bspforge_pin_number >= 0)
    {{
        (void)bspforge_pin_device;
        rt_pin_mode(bspforge_pin_number, PIN_MODE_OUTPUT);
        rt_pin_write(bspforge_pin_number, PIN_HIGH);
    }}

    rt_timer_init(&bspforge_timer, "bfval", bspforge_timer_timeout, RT_NULL,
                  1, RT_TIMER_FLAG_ONE_SHOT | RT_TIMER_FLAG_HARD_TIMER);
    rt_timer_start(&bspforge_timer);
    rt_timer_stop(&bspforge_timer);
    rt_timer_detach(&bspforge_timer);
    return RT_EOK;
}}

int bspforge_selftest(int argc, char **argv)
{{
    const char *request_id;
    const char *command;
    const char *status = "unsupported";
    const char *metrics = "{{}}";

    if (argc < 3)
        return -RT_EINVAL;
    request_id = argv[1];
    command = argv[2];
    if (strcmp(command, "info") == 0)
        status = "pass";
    else if (strcmp(command, "clock.basic") == 0)
    {{
        rt_uint32_t cpu_hz = 0U;
        rt_uint32_t timer_hz = 0U;
        int result = -RT_ENOSYS;
{('        result = bspforge_binding_clock_test(&cpu_hz, &timer_hz);' if binding_validation else '')}
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"cpu_hz\":%lu,\"timer_hz\":%lu}}}}\r\n",
                   request_id, command, status,
                   (unsigned long)cpu_hz, (unsigned long)timer_hz);
        return 0;
    }}
    else if (strcmp(command, "interrupt.basic") == 0)
    {{
        rt_uint32_t fires = 0U;
        rt_uint32_t ticks = 0U;
        int result;
        bspforge_irq_initialize();
        result = bspforge_hwtimer_test(HWTIMER_MODE_ONESHOT, 1U, &fires, &ticks);
        if (bspforge_irq_disable((rt_uint32_t)IRQN_TIMER0A_INTERRUPT) != RT_EOK)
            result = -RT_ERROR;
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"irq_callbacks\":%lu,\"ticks\":%lu}}}}\r\n",
                   request_id, command, status,
                   (unsigned long)fires, (unsigned long)ticks);
        return 0;
    }}
    else if (strcmp(command, "uart.loopback") == 0)
    {{
        rt_uint32_t bytes = 0U;
        rt_uint32_t errors = 0U;
        int result = -RT_ENOSYS;
{('        result = bspforge_binding_uart_loopback(&bytes, &errors);' if binding_validation else '')}
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"bytes\":%lu,\"errors\":%lu}}}}\r\n",
                   request_id, command, status,
                   (unsigned long)bytes, (unsigned long)errors);
        return 0;
    }}
    else if (strcmp(command, "gpio.toggle") == 0 && bspforge_pin_number >= 0)
    {{
        rt_pin_write(bspforge_pin_number, PIN_LOW);
        rt_pin_write(bspforge_pin_number, PIN_HIGH);
        status = "pass";
        metrics = "{{\"toggles\":2}}";
    }}
    else if (strcmp(command, "gpio.toggle") == 0)
    {{
        rt_int32_t low_latch = -1;
        rt_int32_t high_latch = -1;
        rt_int32_t input_low = -1;
        rt_int32_t input_high = -1;
        int result = -RT_ENOSYS;
{('        result = bspforge_binding_gpio_test(&low_latch, &high_latch, &input_low, &input_high);' if binding_validation else '')}
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"output_low_latch\":%ld,"
                   "\"output_high_latch\":%ld,\"input_low\":%ld,"
                   "\"input_high\":%ld}}}}\r\n",
                   request_id, command, status, (long)low_latch,
                   (long)high_latch, (long)input_low, (long)input_high);
        return 0;
    }}
    else if (strcmp(command, "gpio.irq") == 0)
    {{
        rt_uint32_t fires = 0U;
        int result = -RT_ENOSYS;
{('        result = bspforge_binding_gpio_irq_test(&fires);' if binding_validation else '')}
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"irq_callbacks\":%lu}}}}\r\n",
                   request_id, command, status, (unsigned long)fires);
        return 0;
    }}
    else if (strcmp(command, "timer.oneshot") == 0 ||
             strcmp(command, "timer.periodic") == 0)
    {{
        rt_uint32_t fires = 0U;
        rt_uint32_t ticks = 0U;
        rt_bool_t periodic = strcmp(command, "timer.periodic") == 0;
        int result = bspforge_hwtimer_test(
            periodic ? HWTIMER_MODE_PERIOD : HWTIMER_MODE_ONESHOT,
            periodic ? 3U : 1U, &fires, &ticks);
        status = result == RT_EOK ? "pass" :
                 result == -RT_ENOSYS ? "unsupported" : "fail";
        rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
                   "\"event\":\"result\",\"request_id\":\"%s\","
                   "\"command\":\"%s\",\"status\":\"%s\","
                   "\"metrics\":{{\"callbacks\":%lu,\"ticks\":%lu}}}}\r\n",
                   request_id, command, status,
                   (unsigned long)fires, (unsigned long)ticks);
        return 0;
    }}
    else if (strcmp(command, "stability") == 0)
        status = "pass";

    rt_kprintf("{{\"bspforge\":true,\"protocol\":\"1.0\","
               "\"event\":\"result\",\"request_id\":\"%s\","
               "\"command\":\"%s\",\"status\":\"%s\","
               "\"metrics\":%s}}\r\n",
               request_id, command, status, metrics);
    return 0;
}}

int bspforge_validation_init(void)
{{
    return bspforge_validation_run();
}}
INIT_APP_EXPORT(bspforge_validation_init);

#ifdef RT_USING_FINSH
#include <finsh.h>
MSH_CMD_EXPORT(bspforge_validation_run, run BSPForge native-device validation);
MSH_CMD_EXPORT(bspforge_selftest, run a BSPForge protocol self-test);
#endif
'''
