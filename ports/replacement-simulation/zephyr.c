#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/irq.h>
#include <zephyr/fatal.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_utils.h>
#include <zephyr/drivers/counter.h>
#include <zephyr/drivers/clock_control.h>
#include "sdk_api.h"
#include "validation.h"
#include "target.h"
#if HAS_SDK_VECTOR && !defined(CONFIG_ARM_MPU)
#define BSP_SDK_VECTOR_WRITABLE 1
#else
#define BSP_SDK_VECTOR_WRITABLE 0
#endif
static uint32_t native_vector_registrations;
volatile uint32_t bsp_fatal_reason,bsp_fatal_ipsr;
void k_sys_fatal_error_handler(unsigned int reason,const struct arch_esf *esf){
    ARG_UNUSED(esf);bsp_fatal_reason=reason;
    __asm__ volatile("mrs %0, ipsr":"=r"(bsp_fatal_ipsr));
    (void)irq_lock();for(;;){__asm__ volatile("nop");}
}
static int clock_initialized;
static int core_prepare(void){clock_initialized=sdk_clock_initialize();return 0;}
SYS_INIT(core_prepare,PRE_KERNEL_1,10);
static int clk_on(const struct device*d,clock_control_subsys_t s){ARG_UNUSED(d);ARG_UNUSED(s);sdk_clock_enable();return 0;}
static int clk_off(const struct device*d,clock_control_subsys_t s){ARG_UNUSED(d);ARG_UNUSED(s);sdk_clock_disable();return 0;}
static int clk_rate(const struct device*d,clock_control_subsys_t s,uint32_t*r){ARG_UNUSED(d);ARG_UNUSED(s);*r=sdk_clock_frequency();return 0;}
static DEVICE_API(clock_control,clock_api)={.on=clk_on,.off=clk_off,.get_rate=clk_rate};
DEVICE_DEFINE(replacement_clock,"replacement_clock",NULL,NULL,NULL,NULL,POST_KERNEL,70,&clock_api);
int os_clock(int operation,uint32_t*value){const struct device*d=DEVICE_GET(replacement_clock);if(operation==0){*value=sdk_clock_frequency();return clock_initialized;}if(operation==1)return clock_control_on(d,NULL);if(operation==2)return clock_control_off(d,NULL);return clock_control_get_rate(d,NULL,value);}
static int uart_init_device(const struct device*d){ARG_UNUSED(d);return sdk_uart_setup();}
static int poll_in(const struct device*d,unsigned char*c){ARG_UNUSED(d);int v=sdk_uart_getc();if(v<0)return -1;*c=v;return 0;}
static void poll_out(const struct device*d,unsigned char c){ARG_UNUSED(d);sdk_uart_putc(c);}
static DEVICE_API(uart,uart_api)={.poll_in=poll_in,.poll_out=poll_out};
DEVICE_DEFINE(replacement_uart,"replacement_uart",uart_init_device,NULL,NULL,NULL,POST_KERNEL,71,&uart_api);
static const struct device*uart=DEVICE_GET(replacement_uart);
void os_put_byte(uint8_t c){uart_poll_out(uart,c);}
void os_text(const char*s){while(*s)os_put_byte((uint8_t)*s++);}
void os_delay(unsigned ms){k_sleep(K_MSEC(ms));}
int os_byte(void){int64_t end=k_uptime_get()+3000;unsigned char c;do{if(!uart_poll_in(uart,&c))return c;os_delay(1);}while(k_uptime_get()<end);return -1;}
static struct gpio_driver_data gpio_data;
static sys_slist_t callbacks;
static struct gpio_callback callback;
static const struct gpio_driver_config gpio_config={.port_pin_mask=3};
static int pin_configure(const struct device*d,gpio_pin_t p,gpio_flags_t f){ARG_UNUSED(d);ARG_UNUSED(p);ARG_UNUSED(f);sdk_gpio_mode(1);return 0;}
static int port_get(const struct device*d,gpio_port_value_t*v){ARG_UNUSED(d);*v=sdk_gpio_read()?2:0;return 0;}
static int port_set(const struct device*d,gpio_port_pins_t m,gpio_port_value_t v){ARG_UNUSED(d);if(m!=1)return -EINVAL;sdk_gpio_write(v&1);return 0;}
static int port_bits_set(const struct device*d,gpio_port_pins_t m){return port_set(d,m,m);}
static int port_bits_clear(const struct device*d,gpio_port_pins_t m){return port_set(d,m,0);}
static int manage_callback(const struct device*d,struct gpio_callback*cb,bool set){ARG_UNUSED(d);return gpio_manage_callback(&callbacks,cb,set);}
static void sdk_callback(void*arg){const struct device*d=arg;gpio_fire_callbacks(&callbacks,d,2);}
static int pin_interrupt(const struct device*d,gpio_pin_t pin,enum gpio_int_mode mode,enum gpio_int_trig trig){ARG_UNUSED(pin);ARG_UNUSED(trig);if(mode==GPIO_INT_MODE_DISABLED){sdk_gpio_irq_enable(0);return 0;}sdk_gpio_attach(sdk_callback,(void*)d);sdk_gpio_irq_enable(1);return 0;}
static DEVICE_API(gpio,gpio_api)={.pin_configure=pin_configure,.port_get_raw=port_get,.port_set_masked_raw=port_set,.port_set_bits_raw=port_bits_set,.port_clear_bits_raw=port_bits_clear,.pin_interrupt_configure=pin_interrupt,.manage_callback=manage_callback};
DEVICE_DEFINE(replacement_gpio,"replacement_gpio",NULL,NULL,&gpio_data,&gpio_config,POST_KERNEL,72,&gpio_api);
static const struct device*gpio=DEVICE_GET(replacement_gpio);
static void pin_callback(const struct device*d,struct gpio_callback*cb,gpio_port_pins_t pins){ARG_UNUSED(d);ARG_UNUSED(cb);ARG_UNUSED(pins);gpio_irq_count++;}
ISR_DIRECT_DECLARE(gpio_direct){sdk_gpio_irq_handler();return 0;}
ISR_DIRECT_DECLARE(probe_direct){probe_irq_count++;return 0;}
ISR_DIRECT_DECLARE(timer_direct){sdk_timer_clear();timer_irq_count++;return 0;}
static void install(int irq,void(*handler)(void)){
#if BSP_SDK_VECTOR_WRITABLE
sdk_interrupt_register(irq,handler);
#else
ARG_UNUSED(irq);ARG_UNUSED(handler);native_vector_registrations++;
#endif
}
void os_irq_prepare(void){
#if !BSP_SDK_VECTOR_WRITABLE
IRQ_DIRECT_CONNECT(PROBE_IRQ,2,probe_direct,0);
#endif
install(PROBE_IRQ,probe_direct);}
uint32_t os_irq_registration_calls(void){
#if BSP_SDK_VECTOR_WRITABLE
return sdk_calls(7);
#else
return native_vector_registrations;
#endif
}
void os_irq_trigger(void){*(volatile uint32_t*)(0xe000e200+(PROBE_IRQ/32)*4)=1u<<(PROBE_IRQ%32);}
void os_irq_clear(void){*(volatile uint32_t*)(0xe000e280+(PROBE_IRQ/32)*4)=1u<<(PROBE_IRQ%32);}
int os_gpio_setup(void){return gpio_pin_configure(gpio,0,GPIO_OUTPUT_INACTIVE)||gpio_pin_configure(gpio,1,GPIO_INPUT);}
int os_gpio_set(int value){return gpio_pin_set(gpio,0,value);}
int os_gpio_get(void){return gpio_pin_get(gpio,1);}
int os_gpio_attach(void){
#if !BSP_SDK_VECTOR_WRITABLE
IRQ_DIRECT_CONNECT(GPIO_IRQ,2,gpio_direct,0);
#endif
gpio_init_callback(&callback,pin_callback,2);int rc=gpio_add_callback(gpio,&callback);install(GPIO_IRQ,gpio_direct);sdk_interrupt_enable(GPIO_IRQ);return rc;}
void os_gpio_irq(int enabled){gpio_pin_interrupt_configure(gpio,1,enabled?GPIO_INT_EDGE_RISING:GPIO_INT_DISABLE);}
static uint32_t top_value;
static int counter_init_device(const struct device*d){ARG_UNUSED(d);sdk_timer_initialize();top_value=sdk_timer_compare();return 0;}
static int counter_start_device(const struct device*d){ARG_UNUSED(d);sdk_timer_start();return 0;}
static int counter_stop_device(const struct device*d){ARG_UNUSED(d);sdk_timer_stop();return 0;}
static int counter_get(const struct device*d,uint32_t*v){ARG_UNUSED(d);*v=sdk_timer_count();return 0;}
static int counter_top(const struct device*d,const struct counter_top_cfg*cfg){ARG_UNUSED(d);sdk_timer_interval(cfg->ticks);sdk_timer_reset();top_value=cfg->ticks;return 0;}
static uint32_t counter_get_top(const struct device*d){ARG_UNUSED(d);return top_value;}
static const struct counter_config_info counter_config={.max_top_value=0xffffffff,.freq=TIMER_FREQUENCY,.flags=COUNTER_CONFIG_INFO_COUNT_UP,.channels=0};
static DEVICE_API(counter,counter_api)={.start=counter_start_device,.stop=counter_stop_device,.get_value=counter_get,.set_top_value=counter_top,.get_top_value=counter_get_top};
DEVICE_DEFINE(replacement_counter,"replacement_counter",counter_init_device,NULL,NULL,&counter_config,POST_KERNEL,73,&counter_api);
static const struct device*counter=DEVICE_GET(replacement_counter);
int os_timer_setup(void){
#if !BSP_SDK_VECTOR_WRITABLE
IRQ_DIRECT_CONNECT(TIMER_IRQ,2,timer_direct,0);
#endif
install(TIMER_IRQ,timer_direct);sdk_interrupt_enable(TIMER_IRQ);return device_is_ready(counter)?0:-1;}
int os_timer_start(uint32_t ticks){struct counter_top_cfg cfg={.ticks=ticks};int rc=counter_set_top_value(counter,&cfg);return rc?rc:counter_start(counter);}
int os_timer_stop(void){return counter_stop(counter);}
uint32_t os_timer_count(void){uint32_t v=0;counter_get_value(counter,&v);return v;}
int main(void){validation_loop();return 0;}
