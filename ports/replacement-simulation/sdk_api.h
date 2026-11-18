#ifndef BSPFORGE_REPLACEMENT_SDK_API_H
#define BSPFORGE_REPLACEMENT_SDK_API_H
#include <stdint.h>
int sdk_clock_initialize(void);
void sdk_clock_enable(void),sdk_clock_disable(void);
int sdk_clock_enabled(void);
uint32_t sdk_clock_frequency(void),sdk_calls(int operation);
void sdk_interrupt_initialize(void),sdk_interrupt_enable(int irq),sdk_interrupt_disable(int irq);
void sdk_interrupt_register(int irq,void(*handler)(void));
int sdk_uart_setup(void),sdk_uart_getc(void);
void sdk_uart_putc(int value);
void sdk_gpio_mode(int output),sdk_gpio_write(int value);
int sdk_gpio_read(void);
void sdk_gpio_attach(void(*callback)(void*),void*argument);
void sdk_gpio_irq_enable(int enable),sdk_gpio_irq_handler(void);
void sdk_timer_initialize(void),sdk_timer_start(void),sdk_timer_stop(void);
void sdk_timer_interval(uint32_t ticks),sdk_timer_clear(void),sdk_timer_reset(void);
uint32_t sdk_timer_count(void),sdk_timer_compare(void);
int sdk_timer_running(void);
#endif
