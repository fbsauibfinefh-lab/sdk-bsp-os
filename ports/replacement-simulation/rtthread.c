#include <rtthread.h>
#include <rthw.h>
#include <rtdevice.h>
#include "sdk_api.h"
#include "validation.h"
#include "target.h"
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
extern uint32_t vectors[];
static uint32_t ram_vectors[256] __attribute__((aligned(1024)));
static struct rt_thread thread;
static rt_uint8_t stack[6144],heap[16384];
static int clock_initialized;
static struct rt_serial_device serial;
static rt_device_t uart;
static struct rt_device clock_device;
static rt_err_t clock_control(rt_device_t device,int command,void*argument){(void)device;if(command==0){*(uint32_t*)argument=sdk_clock_frequency();return clock_initialized?RT_EOK:-RT_ERROR;}if(command==1)sdk_clock_enable();if(command==2)sdk_clock_disable();if(command==3)*(uint32_t*)argument=sdk_clock_frequency();return RT_EOK;}
int os_clock(int operation,uint32_t*value){int rc=rt_device_control(&clock_device,operation,value);return operation==0?rc==RT_EOK:rc;}
static rt_err_t configure(struct rt_serial_device*s,struct serial_configure*c){(void)s;(void)c;return sdk_uart_setup()==0?RT_EOK:-RT_ERROR;}
static rt_err_t serial_control(struct rt_serial_device*s,int command,void*arg){(void)s;(void)command;(void)arg;return RT_EOK;}
static int serial_putc(struct rt_serial_device*s,char c){(void)s;sdk_uart_putc((uint8_t)c);return 1;}
static int getc(struct rt_serial_device*s){(void)s;return sdk_uart_getc();}
static const struct rt_uart_ops uart_ops={.configure=configure,.control=serial_control,.putc=serial_putc,.getc=getc};
void os_put_byte(uint8_t c){rt_device_write(uart,0,&c,1);}
void os_text(const char*s){while(*s)os_put_byte((uint8_t)*s++);}
void os_delay(unsigned ms){rt_thread_mdelay(ms);}
int os_byte(void){uint8_t c;rt_tick_t start=rt_tick_get();do{if(rt_device_read(uart,0,&c,1)==1)return c;os_delay(1);}while(rt_tick_get()-start<3000);return -1;}
static void pin_mode(struct rt_device*d,rt_base_t pin,rt_uint8_t mode){(void)d;(void)pin;(void)mode;sdk_gpio_mode(1);}
static void pin_write(struct rt_device*d,rt_base_t pin,rt_uint8_t value){(void)d;(void)pin;sdk_gpio_write(value);}
static rt_ssize_t pin_read(struct rt_device*d,rt_base_t pin){(void)d;(void)pin;return sdk_gpio_read();}
static void(*pin_handler)(void*);static void*pin_argument;
static void callback(void*argument){(void)argument;if(pin_handler)pin_handler(pin_argument);}
static rt_err_t pin_attach(struct rt_device*d,rt_base_t p,rt_uint8_t m,void(*handler)(void*),void*arg){(void)d;(void)p;(void)m;pin_handler=handler;pin_argument=arg;sdk_gpio_attach(callback,RT_NULL);return RT_EOK;}
static rt_err_t pin_detach(struct rt_device*d,rt_base_t p){(void)d;(void)p;pin_handler=RT_NULL;return RT_EOK;}
static rt_err_t pin_irq(struct rt_device*d,rt_base_t p,rt_uint8_t enabled){(void)d;(void)p;sdk_gpio_irq_enable(enabled);return RT_EOK;}
static const struct rt_pin_ops pin_ops={.pin_mode=pin_mode,.pin_write=pin_write,.pin_read=pin_read,.pin_attach_irq=pin_attach,.pin_detach_irq=pin_detach,.pin_irq_enable=pin_irq};
static void probe_handler(void){rt_interrupt_enter();probe_irq_count++;rt_interrupt_leave();}
static void gpio_handler(void){rt_interrupt_enter();sdk_gpio_irq_handler();rt_interrupt_leave();}
static struct rt_hwtimer_device timer;
static void timer_handler(void){rt_interrupt_enter();sdk_timer_clear();timer_irq_count++;rt_device_hwtimer_isr(&timer);rt_interrupt_leave();}
static void install(int irq,void(*handler)(void)){
#if HAS_SDK_VECTOR
sdk_interrupt_register(irq,handler);
#else
uint32_t*original=(uint32_t*)(uintptr_t)REG(0xe000ed08);for(unsigned i=0;i<256;i++)ram_vectors[i]=original[i];
ram_vectors[irq+16]=(uint32_t)(uintptr_t)handler;REG(0xe000ed08)=(uint32_t)(uintptr_t)ram_vectors;
#endif
}
void os_irq_prepare(void){install(PROBE_IRQ,probe_handler);}
uint32_t os_irq_registration_calls(void){return sdk_calls(7);}
void os_irq_trigger(void){REG(0xe000e200+(PROBE_IRQ/32)*4)=1u<<(PROBE_IRQ%32);}
void os_irq_clear(void){REG(0xe000e280+(PROBE_IRQ/32)*4)=1u<<(PROBE_IRQ%32);}
static void pin_callback(void*argument){(void)argument;gpio_irq_count++;}
int os_gpio_setup(void){rt_pin_mode(0,PIN_MODE_OUTPUT);rt_pin_mode(1,PIN_MODE_INPUT);return 0;}
int os_gpio_set(int value){rt_pin_write(0,value);return 0;}
int os_gpio_get(void){return rt_pin_read(1);}
int os_gpio_attach(void){install(GPIO_IRQ,gpio_handler);sdk_interrupt_enable(GPIO_IRQ);return rt_pin_attach_irq(1,PIN_IRQ_MODE_RISING,pin_callback,RT_NULL);}
void os_gpio_irq(int enabled){rt_pin_irq_enable(1,enabled?PIN_IRQ_ENABLE:PIN_IRQ_DISABLE);}
static void timer_init_device(struct rt_hwtimer_device*d,rt_uint32_t enabled){(void)d;if(enabled)sdk_timer_initialize();else sdk_timer_stop();}
static rt_err_t timer_start_device(struct rt_hwtimer_device*d,rt_uint32_t count,rt_hwtimer_mode_t mode){(void)d;(void)mode;sdk_timer_interval(count);sdk_timer_reset();sdk_timer_start();return RT_EOK;}
static void timer_stop_device(struct rt_hwtimer_device*d){(void)d;sdk_timer_stop();}
static rt_uint32_t timer_count_device(struct rt_hwtimer_device*d){(void)d;return sdk_timer_count();}
static rt_err_t timer_control_device(struct rt_hwtimer_device*d,rt_uint32_t command,void*argument){(void)d;(void)command;*(uint32_t*)argument=TIMER_FREQUENCY;return RT_EOK;}
static const struct rt_hwtimer_ops timer_ops={.init=timer_init_device,.start=timer_start_device,.stop=timer_stop_device,.count_get=timer_count_device,.control=timer_control_device};
static const struct rt_hwtimer_info timer_info={.maxfreq=TIMER_FREQUENCY,.minfreq=TIMER_FREQUENCY,.maxcnt=0xffffffff,.cntmode=HWTIMER_CNTMODE_UP};
int os_timer_setup(void){install(TIMER_IRQ,timer_handler);sdk_interrupt_enable(TIMER_IRQ);return rt_device_open(&timer.parent,RT_DEVICE_OFLAG_RDWR);}
int os_timer_start(uint32_t count){rt_hwtimer_mode_t mode=HWTIMER_MODE_PERIOD;rt_hwtimerval_t value={.sec=0,.usec=(rt_int32_t)((uint64_t)count*1000000/TIMER_FREQUENCY)};rt_device_control(&timer.parent,HWTIMER_CTRL_MODE_SET,&mode);return rt_device_write(&timer.parent,0,&value,sizeof(value))==sizeof(value)?0:-1;}
int os_timer_stop(void){return rt_device_control(&timer.parent,HWTIMER_CTRL_STOP,RT_NULL);}
uint32_t os_timer_count(void){rt_hwtimerval_t value;rt_device_read(&timer.parent,0,&value,sizeof(value));return (uint32_t)((uint64_t)value.sec*TIMER_FREQUENCY+(uint64_t)value.usec*TIMER_FREQUENCY/1000000);}
static void validation_entry(void*argument){(void)argument;serial.ops=&uart_ops;struct serial_configure cfg=RT_SERIAL_CONFIG_DEFAULT;serial.config=cfg;rt_hw_serial_register(&serial,"sdk-uart",RT_DEVICE_FLAG_RDWR,RT_NULL);uart=rt_device_find("sdk-uart");rt_device_open(uart,RT_DEVICE_OFLAG_RDWR);rt_device_pin_register("pin",&pin_ops,RT_NULL);timer.ops=&timer_ops;timer.info=&timer_info;rt_device_hwtimer_register(&timer,"sdk-timer",RT_NULL);clock_device.type=RT_Device_Class_Unknown;clock_device.control=clock_control;rt_device_register(&clock_device,"sdk-clock",RT_DEVICE_FLAG_RDWR);validation_loop();}
void SysTick_Handler(void){rt_interrupt_enter();rt_tick_increase();rt_interrupt_leave();}
void rt_hw_console_output(const char*s){while(*s)sdk_uart_putc((uint8_t)*s++);}
void simulation_start(void){
REG(0xe000ed08)=(uint32_t)(uintptr_t)vectors;clock_initialized=sdk_clock_initialize();
rt_hw_interrupt_disable();rt_system_timer_init();rt_system_scheduler_init();rt_system_heap_init(heap,heap+sizeof(heap));
rt_thread_init(&thread,"validate",validation_entry,RT_NULL,stack,sizeof(stack),10,10);rt_thread_startup(&thread);rt_system_timer_thread_init();rt_thread_idle_init();
REG(0xe000e014)=CPU_HZ/1000-1;REG(0xe000e018)=0;REG(0xe000e010)=7;rt_system_scheduler_start();for(;;){}
}
