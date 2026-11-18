#include <rtthread.h>
#include <rthw.h>
#include <stdint.h>
#include "target.h"
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))

#if TARGET_FE310
static void tick_next(void) {
    uint64_t now=((uint64_t)REG(0x0200bffc)<<32)|REG(0x0200bff8);
    uint64_t next=now+16000;REG(0x02004004)=0xffffffff;REG(0x02004000)=(uint32_t)next;REG(0x02004004)=next>>32;
}
void platform_putc(int c){while(REG(0x10013000)&0x80000000){}REG(0x10013000)=c;}
int platform_getc(void){uint32_t v=REG(0x10013004);return v&0x80000000?-1:(v&255);}
void platform_gpio_mode(int output){REG(0x10012008)|=1;REG(0x10012004)|=1;(void)output;}
void platform_gpio_write(int value){if(value)REG(0x1001200c)|=1;else REG(0x1001200c)&=~1u;}
int platform_gpio_read(void){return REG(0x10012000)&1;}
void platform_init(void){REG(0x10013008)=1;REG(0x1001300c)=1;REG(0x10013018)=138;tick_next();__asm__ volatile("csrs mie,%0"::"r"(128));}
void rt_hw_do_after_save_above(void){uint32_t cause;__asm__ volatile("csrr %0,mcause":"=r"(cause));if(cause==0x80000007){tick_next();rt_tick_increase();}else while(1){}}
void rt_trigger_software_interrupt(void){}
#elif TARGET_LITEX
void platform_putc(int c){while(REG(0xe0001804)){}REG(0xe0001800)=c;}
int platform_getc(void){if(REG(0xe0001808))return -1;int c=REG(0xe0001800)&255;REG(0xe0001810)=2;return c;}
void platform_gpio_mode(int output){(void)output;}
void platform_gpio_write(int v){REG(0xe0005800)=v&1;}
int platform_gpio_read(void){return REG(0xe0006000)&1;}
void platform_init(void){REG(0xe0002808)=0;REG(0xe0002800)=100000;REG(0xe0002804)=100000;REG(0xe0002818)=1;REG(0xe000281c)=1;REG(0xe0002808)=1;__asm__ volatile("csrw 0xbc0,%0"::"r"(2));__asm__ volatile("csrs mie,%0"::"r"(2048));}
void rt_hw_do_after_save_above(void){REG(0xe0002818)=1;rt_tick_increase();}
void rt_trigger_software_interrupt(void){}
#elif TARGET_OPENTITAN
static void tick_next(void){REG(0x4010011c)=0xffffffff;REG(0x40100118)=REG(0x40100110)+1000;REG(0x4010011c)=0;REG(0x40100104)=1;}
void platform_putc(int c){while(REG(0x40000014)&1){}REG(0x4000001c)=c;}
int platform_getc(void){return REG(0x40000014)&0x20?-1:REG(0x40000018)&255;}
void platform_gpio_mode(int output){REG(0x40040020)|=1;(void)output;}
void platform_gpio_write(int v){REG(0x40040014)=v&1;}
int platform_gpio_read(void){return (REG(0x40040010)>>1)&1;}
void platform_init(void){REG(0x40000010)=3|(0x34eu<<16);REG(0x4010010c)=0x10017;REG(0x40100100)=1;tick_next();REG(0x40100004)=1;__asm__ volatile("csrs mie,%0"::"r"(128));}
void rt_hw_do_after_save_above(void){tick_next();rt_tick_increase();}
void rt_trigger_software_interrupt(void){}
#else
void SysTick_Handler(void){rt_interrupt_enter();rt_tick_increase();rt_interrupt_leave();}
void platform_init(void){
#if TARGET_APOLLO4
REG(0x4001c030)=0x301;
#endif
REG(0xe000e014)=CPU_HZ/1000-1;REG(0xe000e018)=0;REG(0xe000e010)=7;}
#if TARGET_SAMD21
void platform_putc(int c){while(!(REG(0x42001418)&1)){}REG(0x42001428)=c;}
int platform_getc(void){if(!(REG(0x42001418)&4))return -1;return REG(0x42001428)&255;}
void platform_gpio_mode(int output){REG(0x41004408)=1<<2;REG(0x41004400)&=~(1u<<3);*(volatile uint8_t*)0x41004443=2;(void)output;}
void platform_gpio_write(int v){REG(v?0x41004418:0x41004414)=1<<2;}
int platform_gpio_read(void){return (REG(0x41004420)>>3)&1;}
#else
void platform_putc(int c){while(REG(0x4001c018)&32){}REG(0x4001c000)=c;}
int platform_getc(void){return REG(0x4001c018)&16?-1:REG(0x4001c000)&255;}
void platform_gpio_mode(int output){(void)output;REG(0x40010030)=0x00000001;}
void platform_gpio_write(int v){REG(v?0x40010208:0x40010218)=1<<12;}
int platform_gpio_read(void){return (REG(0x40010080)>>13)&1;}
#endif
#endif
