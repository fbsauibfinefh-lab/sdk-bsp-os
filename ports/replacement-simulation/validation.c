#include "sdk_api.h"
#include "validation.h"
#include "target.h"
#include <stdio.h>
#ifndef GPIO_TEST_DELAY_MS
#define GPIO_TEST_DELAY_MS 1
#endif
#ifndef HAS_TIMER_PERIOD_BINDING
#define HAS_TIMER_PERIOD_BINDING 1
#endif
volatile uint32_t probe_irq_count,gpio_irq_count,timer_irq_count;
static int timer_running_matches(int expected){
#if HAS_TIMER_ENABLE_PROBE
    return sdk_timer_running()==expected;
#else
    (void)expected;return 1;
#endif
}
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
static void result(int operation,int passed,uint32_t before,uint32_t after){
    if(!(ELIGIBLE_MASK&(1u<<operation)))return;
    uint32_t calls=operation==7?os_irq_registration_calls():sdk_calls(operation);
    char line[128];snprintf(line,sizeof line,"OP %d %s before=%lu after=%lu calls=%lu\n",operation,passed?"PASS":"FAIL",(unsigned long)before,(unsigned long)after,(unsigned long)calls);os_text(line);
}
static void validation_run_mask(uint32_t mask){
    if(mask&0x0fu){
    uint32_t frequency=0;int ok=os_clock(0,&frequency);
    result(0,ok&&sdk_calls(0)>0&&frequency==CPU_HZ,CPU_HZ,frequency);
    int before=sdk_clock_enabled();os_clock(1,&frequency);int enabled=sdk_clock_enabled();result(1,enabled,before,enabled);
    os_clock(2,&frequency);result(2,enabled&&!sdk_clock_enabled(),enabled,sdk_clock_enabled());os_clock(1,&frequency);
    os_clock(3,&frequency);result(3,frequency>0,0,frequency);
    }
    if(mask&0xf0u){
    sdk_interrupt_initialize();uint32_t group=(REG(0xe000ed0c)>>8)&7;
    result(4,group==EXPECTED_PRIORITY_GROUP,EXPECTED_PRIORITY_GROUP,group);
    os_irq_prepare();sdk_interrupt_disable(PROBE_IRQ);os_irq_clear();probe_irq_count=0;
    sdk_interrupt_enable(PROBE_IRQ);os_irq_trigger();os_delay(3);
    uint32_t first=probe_irq_count;result(5,first==1,0,first);
    result(7,first==1&&os_irq_registration_calls()>0,0,first);
    sdk_interrupt_disable(PROBE_IRQ);os_irq_trigger();os_delay(3);
    result(6,first==1&&probe_irq_count==first,first,probe_irq_count);os_irq_clear();
    }
    if(mask&0x7800u){
    int configured=os_gpio_setup()==0;int levels=configured;
    for(int i=0;i<32;i++){if(os_gpio_set(i&1))levels=0;os_delay(GPIO_TEST_DELAY_MS);if(os_gpio_get()!=(i&1))levels=0;}
    result(11,configured&&levels,0,sdk_calls(11));
    result(12,levels,0,sdk_calls(12));result(13,levels,0,sdk_calls(13));
    if(ELIGIBLE_MASK&(1u<<14)){
        os_gpio_set(0);os_delay(2);gpio_irq_count=0;int attached=os_gpio_attach()==0;os_gpio_irq(1);
        for(int i=0;i<4;i++){os_gpio_set(0);os_delay(2);os_gpio_set(1);os_delay(2);}
        os_gpio_irq(0);result(14,attached&&gpio_irq_count==4,4,gpio_irq_count);
    }
    }
    if(mask&0x78000u){
    int initialized=os_timer_setup()==0;
    result(15,initialized&&sdk_calls(15)>0,0,sdk_timer_compare());
#if HAS_TIMER_PERIOD_BINDING
    timer_irq_count=0;int started=os_timer_start(TIMER_FREQUENCY/1000)==0;os_delay(9);
    uint32_t events=timer_irq_count;result(16,started&&events>0&&timer_running_matches(1),0,events);
    os_timer_stop();uint32_t count=os_timer_count(),stopped_events=timer_irq_count;os_delay(6);
    result(17,events>0&&timer_running_matches(0)&&os_timer_count()==count&&timer_irq_count==stopped_events,count,os_timer_count());
    uint32_t old=sdk_timer_compare();os_timer_start(TIMER_FREQUENCY/500);uint32_t updated=sdk_timer_compare();
    os_delay(9);result(18,updated!=old&&timer_irq_count>stopped_events,old,updated);os_timer_stop();
#else
    /* No safe start without a resolved compare period; report dependent failures. */
    result(16,0,0,0);result(17,0,0,0);result(18,0,0,0);
#endif
    }
    os_text("DONE B\n");
}
void validation_run(void){validation_run_mask(0x7ffffu);}
void validation_loop(void){
    os_text("READY replacement-native-devices\n");
    for(;;){
        int c=os_byte();if(c<0)continue;
        if(c=='B')validation_run();
        else if(c=='C')validation_run_mask(0x0fu);
        else if(c=='I')validation_run_mask(0xf0u);
        else if(c=='G')validation_run_mask(0x7800u);
        else if(c=='T')validation_run_mask(0x78000u);
        else if(c=='U'){
            int n=os_byte();uint8_t payload[255];int ok=n>=0;
            for(int i=0;i<n;i++){int v=os_byte();if(v<0)ok=0;payload[i]=(uint8_t)v;}
            if(ok){os_text("PAYLOAD ");for(int i=0;i<n;i++){char s[2]={(char)payload[i],0};
                /* 二进制字节不能使用字符串API。 */
                extern void os_put_byte(uint8_t value);os_put_byte((uint8_t)s[0]);}
                os_text("\nPASS U\n");}else os_text("FAIL U\n");
        }else if(c=='S'){
            result(8,sdk_calls(8)>0,0,sdk_calls(8));result(9,sdk_calls(9)>0,0,sdk_calls(9));result(10,sdk_calls(10)>0,0,sdk_calls(10));os_text("DONE S\n");
        }
    }
}
