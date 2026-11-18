#include <rtthread.h>
#include <rthw.h>
#include <drivers/dev_pin.h>
#include <stdint.h>
#include "target.h"

extern void platform_init(void);
extern void platform_putc(int c);
extern int platform_getc(void);
extern void platform_gpio_mode(int output);
extern void platform_gpio_write(int value);
extern int platform_gpio_read(void);
#ifdef BSP_USE_SDK
extern void sdk_gpio_mode(int),sdk_gpio_write(int);
extern int sdk_gpio_read(void);
extern uint32_t sdk_gpio_write_calls(void),sdk_gpio_read_calls(void);
#define platform_gpio_mode sdk_gpio_mode
#define platform_gpio_write sdk_gpio_write
#define platform_gpio_read sdk_gpio_read
#endif
#ifdef BSP_USE_SDK_UART
#include <rtdevice.h>
extern int sdk_uart_setup(void),sdk_uart_getc(void);
extern void sdk_uart_putc(int);
extern uint32_t sdk_uart_tx_calls(void),sdk_uart_rx_calls(void);
static struct rt_serial_device sdk_serial;
static int serial_ready;
static rt_err_t serial_config(struct rt_serial_device*s,struct serial_configure*c){(void)s;(void)c;return sdk_uart_setup()==0?RT_EOK:-RT_ERROR;}
static rt_err_t serial_control(struct rt_serial_device*s,int cmd,void*arg){(void)s;(void)cmd;(void)arg;return RT_EOK;}
static int serial_putc(struct rt_serial_device*s,char c){(void)s;sdk_uart_putc((uint8_t)c);return 1;}
static int serial_getc(struct rt_serial_device*s){(void)s;return sdk_uart_getc();}
static const struct rt_uart_ops serial_ops={.configure=serial_config,.control=serial_control,.putc=serial_putc,.getc=serial_getc};
static rt_align(8) uint8_t heap[4096];
#endif
static struct rt_thread worker;
static rt_align(8) unsigned char worker_stack[2048];
static struct rt_timer probe_timer;
static volatile uint32_t ticks;
static void pin_mode(struct rt_device *dev,rt_base_t pin,rt_uint8_t mode) { (void)dev;(void)pin;platform_gpio_mode(mode==PIN_MODE_OUTPUT); }
static void pin_write(struct rt_device *dev,rt_base_t pin,rt_uint8_t v) { (void)dev;(void)pin;platform_gpio_write(v); }
static rt_ssize_t pin_read(struct rt_device *dev,rt_base_t pin) { (void)dev;(void)pin;return platform_gpio_read(); }
static const struct rt_pin_ops pin_ops={.pin_mode=pin_mode,.pin_write=pin_write,.pin_read=pin_read};
void rt_hw_console_output(const char *s) {
#ifdef BSP_USE_SDK_UART
    if(serial_ready){rt_device_write(&sdk_serial.parent,0,s,rt_strlen(s));return;}
#endif
    while(*s) platform_putc(*s++);
}
void rt_hw_cpu_shutdown(void) { while(1) {} }
static void text(const char*s) {rt_hw_console_output(s);}
static int byte(void) {
    rt_tick_t start=rt_tick_get();int c;
    do {
#ifdef BSP_USE_SDK_UART
        uint8_t ch;c=rt_device_read(&sdk_serial.parent,0,&ch,1)==1?ch:-1;
#else
        c=platform_getc();
#endif
        if(c>=0)return c;rt_thread_mdelay(1);
    } while(rt_tick_get()-start<3000);
    return -1;
}
static void tick(void *arg) { (void)arg;ticks++; }
static int gpio_probe(void) {
    rt_pin_mode(0,PIN_MODE_OUTPUT);
    for(int i=0;i<32;i++) {rt_pin_write(0,i&1);rt_thread_mdelay(1);if(rt_pin_read(0)!=(i&1))return 0;}
    return 1;
}
static int timer_probe(void) {
    ticks=0;rt_tick_t interval=2;rt_timer_control(&probe_timer,RT_TIMER_CTRL_SET_TIME,&interval);rt_timer_start(&probe_timer);
    rt_thread_mdelay(12);rt_timer_stop(&probe_timer);uint32_t before=ticks;rt_thread_mdelay(8);
    uint32_t stopped=ticks;interval=1;rt_timer_control(&probe_timer,RT_TIMER_CTRL_SET_TIME,&interval);rt_timer_start(&probe_timer);
    rt_thread_mdelay(6);rt_timer_stop(&probe_timer);return before>1&&stopped==before&&ticks>stopped;
}
static void run(void *arg) {
#ifdef BSP_USE_SDK_UART
    sdk_serial.ops=&serial_ops;struct serial_configure config=RT_SERIAL_CONFIG_DEFAULT;sdk_serial.config=config;
    if(rt_hw_serial_register(&sdk_serial,"sdk_uart",RT_DEVICE_FLAG_RDWR,RT_NULL)!=RT_EOK||rt_device_open(&sdk_serial.parent,RT_DEVICE_FLAG_RDWR)!=RT_EOK){text("SDK_UART_SETUP_FAILED\n");return;}
    serial_ready=1;
#endif
    (void)arg;rt_device_pin_register("pin",&pin_ops,RT_NULL);
    rt_timer_init(&probe_timer,"probe",tick,RT_NULL,2,RT_TIMER_FLAG_PERIODIC);
#ifdef BSP_USE_SDK_UART
    text("READY rtthread sdk-uart-gpio\n");
#elif defined(BSP_USE_SDK)
    text("READY rtthread sdk-gpio\n");
#else
    text("READY rtthread native-control\n");
#endif
    for(;;) {
        int c=byte();if(c<0)continue;
        if(c=='G')text(gpio_probe()?"PASS G\n":"FAIL G\n");
        else if(c=='T')text(timer_probe()?"PASS T\n":"FAIL T\n");
#ifdef BSP_USE_SDK
        else if(c=='S'){char s[100];int ok=sdk_gpio_write_calls()>0&&sdk_gpio_read_calls()>0;
#ifdef BSP_USE_SDK_UART
            rt_snprintf(s,sizeof s,"CALLS tx=%u rx=%u write=%u read=%u\n",sdk_uart_tx_calls(),sdk_uart_rx_calls(),sdk_gpio_write_calls(),sdk_gpio_read_calls());
            ok=ok&&sdk_uart_tx_calls()>0&&sdk_uart_rx_calls()>0;
#else
            rt_snprintf(s,sizeof s,"CALLS write=%u read=%u\n",sdk_gpio_write_calls(),sdk_gpio_read_calls());
#endif
            text(s);text(ok?"PASS S\n":"FAIL S\n");}
#endif
        else if(c=='U') {int n=byte(),ok=n>=0;uint8_t buf[255];
            for(int i=0;i<n;i++){int v=byte();if(v<0)ok=0;buf[i]=(uint8_t)v;}
            if(ok){text("PAYLOAD ");
#ifdef BSP_USE_SDK_UART
                rt_device_write(&sdk_serial.parent,0,buf,n);
#else
                for(int i=0;i<n;i++)platform_putc(buf[i]);
#endif
                text("\nPASS U\n");}else text("FAIL U\n");
        }
    }
}
void simulation_start(void) {
    rt_hw_interrupt_disable();
    rt_system_timer_init();rt_system_scheduler_init();
#ifdef BSP_USE_SDK_UART
    rt_system_heap_init(heap,heap+sizeof heap);
#endif
    platform_init();rt_system_timer_thread_init();rt_thread_idle_init();
    rt_thread_init(&worker,"probe",run,RT_NULL,worker_stack,sizeof worker_stack,8,10);rt_thread_startup(&worker);
    rt_system_scheduler_start();
    while(1){}
}
