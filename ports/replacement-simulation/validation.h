#ifndef BSPFORGE_REPLACEMENT_VALIDATION_H
#define BSPFORGE_REPLACEMENT_VALIDATION_H
#include <stdint.h>
extern volatile uint32_t probe_irq_count,gpio_irq_count,timer_irq_count;
void os_delay(unsigned ms),os_text(const char *s);
int os_byte(void),os_clock(int operation,uint32_t *value);
void os_irq_prepare(void),os_irq_trigger(void),os_irq_clear(void);
uint32_t os_irq_registration_calls(void);
int os_gpio_setup(void),os_gpio_set(int value),os_gpio_get(void),os_gpio_attach(void);
void os_gpio_irq(int enabled);
int os_timer_setup(void),os_timer_start(uint32_t ticks),os_timer_stop(void);
uint32_t os_timer_count(void);
void validation_run(void),validation_loop(void);
#endif
