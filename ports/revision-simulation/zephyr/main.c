#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/drivers/gpio.h>
#include <stdint.h>
#include "target.h"
#ifdef BSP_USE_SDK
#include <zephyr/sys/printk.h>
extern void sdk_gpio_mode(int);
extern void sdk_gpio_write(int);
extern int sdk_gpio_read(void);
extern uint32_t sdk_gpio_write_calls(void),sdk_gpio_read_calls(void);
static int sdk_configure(const struct device*d,gpio_pin_t p,gpio_flags_t f){ARG_UNUSED(d);ARG_UNUSED(p);ARG_UNUSED(f);sdk_gpio_mode(1);return 0;}
static int sdk_get(const struct device*d,gpio_port_value_t*v){ARG_UNUSED(d);*v=sdk_gpio_read()?1:0;return 0;}
static int sdk_set(const struct device*d,gpio_port_pins_t m,gpio_port_value_t v){ARG_UNUSED(d);if(m!=1)return -1;sdk_gpio_write(v&1);return 0;}
static int sdk_set_bits(const struct device*d,gpio_port_pins_t m){return sdk_set(d,m,m);}
static int sdk_clear_bits(const struct device*d,gpio_port_pins_t m){return sdk_set(d,m,0);}
static struct gpio_driver_data sdk_data;
static const struct gpio_driver_config sdk_config={.port_pin_mask=1};
static DEVICE_API(gpio,sdk_gpio_api)={.pin_configure=sdk_configure,.port_get_raw=sdk_get,.port_set_masked_raw=sdk_set,.port_set_bits_raw=sdk_set_bits,.port_clear_bits_raw=sdk_clear_bits};
DEVICE_DEFINE(revision_sdk_gpio,"revision_sdk_gpio",NULL,NULL,&sdk_data,&sdk_config,POST_KERNEL,90,&sdk_gpio_api);
#undef PROBE_NATIVE_GPIO
#define PROBE_NATIVE_GPIO 1
#undef PROBE_OUTPUT
#undef PROBE_INPUT
#define PROBE_OUTPUT 0
#define PROBE_INPUT 0
#endif

#ifdef BSP_USE_SDK_UART
extern int sdk_uart_setup(void),sdk_uart_getc(void);
extern void sdk_uart_putc(int);
extern uint32_t sdk_uart_tx_calls(void),sdk_uart_rx_calls(void);
static int sdk_poll_in(const struct device*d,unsigned char*c){ARG_UNUSED(d);int v=sdk_uart_getc();if(v<0)return -1;*c=v;return 0;}
static void sdk_poll_out(const struct device*d,unsigned char c){ARG_UNUSED(d);sdk_uart_putc(c);}
static DEVICE_API(uart,sdk_uart_api)={.poll_in=sdk_poll_in,.poll_out=sdk_poll_out};
DEVICE_DEFINE(revision_sdk_uart,"revision_sdk_uart",NULL,NULL,NULL,NULL,POST_KERNEL,90,&sdk_uart_api);
static const struct device *uart=DEVICE_GET(revision_sdk_uart);
#else
static const struct device *uart = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
#endif
#if PROBE_NATIVE_GPIO
#ifdef BSP_USE_SDK
static const struct device *gpio_out=DEVICE_GET(revision_sdk_gpio),*gpio_in=DEVICE_GET(revision_sdk_gpio);
#else
static const struct device *gpio_out = DEVICE_DT_GET(DT_NODELABEL(PROBE_GPIO_OUT));
static const struct device *gpio_in = DEVICE_DT_GET(DT_NODELABEL(PROBE_GPIO_IN));
#endif
#endif
static volatile uint32_t ticks;
static void tick(struct k_timer *timer) { ARG_UNUSED(timer); ticks++; }
K_TIMER_DEFINE(probe_timer, tick, NULL);
static void text(const char *s) { while (*s) uart_poll_out(uart, *s++); }
static int byte(void) {
    unsigned char c;
    int64_t end = k_uptime_get() + 3000;
    do { if (uart_poll_in(uart, &c) == 0) return c; k_sleep(K_MSEC(1)); } while (k_uptime_get() < end);
    return -1;
}
static int gpio_probe(void) {
#if PROBE_NATIVE_GPIO
    if (!device_is_ready(gpio_out) || !device_is_ready(gpio_in)) return 0;
    if (gpio_pin_configure(gpio_out, PROBE_OUTPUT, GPIO_OUTPUT_INACTIVE)) return 0;
    if (gpio_in != gpio_out || PROBE_INPUT != PROBE_OUTPUT)
        if (gpio_pin_configure(gpio_in, PROBE_INPUT, GPIO_INPUT)) return 0;
    for (int i=0; i<32; i++) {
        if (gpio_pin_set(gpio_out, PROBE_OUTPUT, i&1)) return 0;
        k_sleep(K_MSEC(1));
        if (gpio_pin_get(gpio_in, PROBE_INPUT) != (i&1)) return 0;
    }
    return 1;
#else
    return 0;
#endif
}
static int timer_probe(void) {
    ticks=0; k_timer_start(&probe_timer,K_MSEC(2),K_MSEC(2)); k_sleep(K_MSEC(12));
    k_timer_stop(&probe_timer); uint32_t before=ticks; k_sleep(K_MSEC(8));
    uint32_t stopped=ticks; k_timer_start(&probe_timer,K_MSEC(1),K_MSEC(1)); k_sleep(K_MSEC(6));
    k_timer_stop(&probe_timer); return before>1 && stopped==before && ticks>stopped;
}
int main(void) {
#ifdef BSP_USE_SDK_UART
    if(sdk_uart_setup()!=0){const char*s="SDK_UART_SETUP_FAILED\n";while(*s)uart_poll_out(DEVICE_DT_GET(DT_CHOSEN(zephyr_console)),*s++);return -1;}
#endif
#ifdef BSP_USE_SDK_UART
    text("READY zephyr sdk-uart-gpio\n");
#elif defined(BSP_USE_SDK)
    text("READY zephyr sdk-gpio\n");
#else
    text("READY zephyr native-control\n");
#endif
    for (;;) {
        int c=byte(); if(c<0) continue;
        if(c=='G') text(gpio_probe()?"PASS G\n":"FAIL G\n");
        else if(c=='T') text(timer_probe()?"PASS T\n":"FAIL T\n");
#ifdef BSP_USE_SDK
        else if(c=='S') {char line[100];int ok=sdk_gpio_write_calls()>0&&sdk_gpio_read_calls()>0;
#ifdef BSP_USE_SDK_UART
            snprintk(line,sizeof line,"CALLS tx=%u rx=%u write=%u read=%u\n",sdk_uart_tx_calls(),sdk_uart_rx_calls(),sdk_gpio_write_calls(),sdk_gpio_read_calls());
            ok=ok&&sdk_uart_tx_calls()>0&&sdk_uart_rx_calls()>0;
#else
            snprintk(line,sizeof line,"CALLS write=%u read=%u\n",sdk_gpio_write_calls(),sdk_gpio_read_calls());
#endif
            text(line);text(ok?"PASS S\n":"FAIL S\n");}
#endif
        else if(c=='U') {
            int n=byte(); uint8_t buf[255]; int ok=n>=0;
            for(int i=0;i<n;i++) { int v=byte(); if(v<0) ok=0; buf[i]=(uint8_t)v; }
            if(ok) { text("PAYLOAD "); for(int i=0;i<n;i++) uart_poll_out(uart,buf[i]); text("\nPASS U\n"); }
            else text("FAIL U\n");
        }
    }
}
