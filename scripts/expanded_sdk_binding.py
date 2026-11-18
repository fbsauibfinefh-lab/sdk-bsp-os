"""扩展池显式ABI适配，不读取参考；未绑定操作保留零调用及失败记录。"""
from pathlib import Path
import re
import subprocess
from bspforge.common import read_json,write_json
try:
    from scripts.replacement_sdk_binding import canonical,exported_data_symbols
    from scripts.run_sifive_zephyr_simulation import typed_parameters
except ModuleNotFoundError as error:
    if error.name!='scripts':raise
    from replacement_sdk_binding import canonical,exported_data_symbols
    from run_sifive_zephyr_simulation import typed_parameters

U='unsigned long';B='unsigned char'
C_KEYWORDS=set('auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while _Alignas _Alignof _Atomic _Bool _Complex _Generic _Imaginary _Noreturn _Static_assert _Thread_local'.split())
CONTRACTS={
 'stellaris-driverlib':{
 'clock.initialize':[[U]],'clock.enable':[[U]],'clock.disable':[[U]],'clock.get_frequency':[[]],
 'interrupt.initialize':[[U]],'interrupt.enable':[[U]],'interrupt.disable':[[U]],'interrupt.register':[[U,'void(*)(void)']],
 'uart.configure':[[U,U,U,U]],'uart.write':[[U,B]],'uart.read':[[U]],
 'gpio.configure':[[U,B,U]],'gpio.write':[[U,B,B]],'gpio.read':[[U,B]],'gpio.attach_irq':[[U,'void(*)(void)']],
 'timer.initialize':[[U,U]],'timer.start':[[U,U]],'timer.stop':[[U,U]],'timer.set_interval':[[U,U,U]]},
 'asf3-sam4s':{
 'clock.initialize':[[]],'clock.enable':[['uint32_t']],'clock.disable':[['uint32_t']],'clock.get_frequency':[[]],
 'interrupt.initialize':[['uint32_t']],'interrupt.enable':[['IRQn_Type']],'interrupt.disable':[['IRQn_Type']],
 'uart.configure':[['Uart*','const sam_uart_opt_t*']],'uart.write':[['Uart*','const uint8_t']],'uart.read':[['Uart*','uint8_t*']],
 'gpio.configure':[['Pio*','const pio_type_t','const uint32_t','const uint32_t']],
 'gpio.write':[['Pio*','const uint32_t']],'gpio.read':[['Pio*','const pio_type_t','const uint32_t']],
 'gpio.attach_irq':[['Pio*','uint32_t','uint32_t','uint32_t','void(*)(uint32_t,uint32_t)']],
 'timer.initialize':[['Tc*','uint32_t','uint32_t']],'timer.start':[['Tc*','uint32_t']],'timer.stop':[['Tc*','uint32_t']],
 'timer.set_interval':[['Tc*','uint32_t','uint32_t']]},
 'nrf5-nrf52840':{
 'clock.initialize':[['nrfx_clock_event_handler_t'],[]],'clock.enable':[[]],'clock.disable':[[]],
 'interrupt.initialize':[['uint32_t']],'interrupt.enable':[['IRQn_Type']],'interrupt.disable':[['IRQn_Type']],
 'interrupt.register':[['IRQn_Type','uint32_t']],
 'uart.configure':[['nrfx_uart_t const*','nrfx_uart_config_t const*','nrfx_uart_event_handler_t']],
 'uart.write':[['nrfx_uart_t const*','uint8_t const*','size_t']],'uart.read':[['nrfx_uart_t const*','uint8_t*','size_t']],
 'gpio.configure':[['uint32_t']],'gpio.write':[['uint32_t','uint32_t']],'gpio.read':[['uint32_t']],
 'gpio.attach_irq':[['nrfx_gpiote_pin_t','nrfx_gpiote_in_config_t const*','nrfx_gpiote_evt_handler_t']],
 'timer.initialize':[['nrfx_timer_t const*','nrfx_timer_config_t const*','nrfx_timer_event_handler_t']],
 'timer.start':[['nrfx_timer_t const*']],'timer.stop':[['nrfx_timer_t const*']],
 'timer.set_interval':[['nrfx_timer_t const*','nrf_timer_cc_channel_t','uint32_t','bool']]},
}
RETURNS={
 'stellaris-driverlib':{'clock.get_frequency':['unsigned long'],'uart.write':['void','tBoolean'],'uart.read':['long'],'gpio.read':['long']},
 'asf3-sam4s':{'clock.enable':['uint32_t','void'],'clock.disable':['uint32_t','void'],'clock.get_frequency':['uint32_t'],
     'uart.configure':['uint32_t'],'uart.write':['uint32_t'],'uart.read':['uint32_t'],'gpio.configure':['uint32_t'],'gpio.read':['uint32_t'],'gpio.attach_irq':['uint32_t']},
 'nrf5-nrf52840':{'clock.initialize':['nrfx_err_t'],'uart.configure':['nrfx_err_t'],'uart.write':['nrfx_err_t'],'uart.read':['nrfx_err_t'],
     'gpio.read':['uint32_t'],'gpio.attach_irq':['nrfx_err_t'],'timer.initialize':['nrfx_err_t']},
}


def abi_parameter(value):
    # C形参最外层指针const不改变调用ABI，保留其指向类型的限定。
    return canonical(re.sub(r'(\*)\s*(?:const|volatile)\s*$',r'\1',value.strip()))


def scope(name,op,e):
    path=e['file'];symbol=e['name']
    if name.startswith('stellaris'):
        file={'clock':'sysctl','interrupt':'interrupt','uart':'uart','gpio':'gpio','timer':'timer'}[op.split('.')[0]]
        return path==f'driverlib/{file}.c'
    if op.startswith('interrupt.'):return path.endswith('core_cm4.h')
    if name.startswith('asf3'):
        kind=op.split('.')[0]
        if kind=='clock':return '/clock/sam4s/' in path or '/pmc/' in path or 'system_sam4s' in path
        return '/'+{'uart':'uart','gpio':'pio','timer':'tc'}[kind]+'/' in path
    kind=op.split('.')[0]
    if kind=='clock':return 'nrfx_clock' in path
    if kind=='gpio':return ('nrfx_gpiote' in path if op=='gpio.attach_irq' else 'hal/nrf_gpio.h' in path)
    return f'nrfx_{kind}' in path and '/drivers/' in path and symbol.startswith('nrfx_')


def select(root,name,app,headers,includes,defines,contract_guard=False):
    base=root/'experiments/revision-r1-expanded';sdk=next(s for s in read_json(base/'manifest.json')['sdks'] if s['name']==name)
    ir=read_json(base/name/'ir'/(sdk['sdk_id']+'.json'));entities={e['id']:e for e in ir['functions']}
    bundle=read_json(base/name/'frozen-runtime-bundle.json');selected={}
    from bspforge.binding_contract_guard import BindingContractGuard
    guard=BindingContractGuard(Path(sdk['source_path']),ir) if contract_guard else None
    compiler=root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc'
    probe=app/'public-api-probes';probe.mkdir(exist_ok=True)
    for op,shapes in CONTRACTS[name].items():
        rejected=[]
        for c in bundle['operations'][op]['candidates']:
            e=entities[c['entity_id']];actual=[abi_parameter(p) for p in typed_parameters(e.get('signature',''))]
            prefix=e.get('signature','').split(e['name'],1)[0]
            returns=RETURNS[name].get(op,['void'])
            normalized_return=canonical(re.sub(r'\b(?:extern|static|inline|__STATIC_INLINE|__INLINE|__inline|__inline__)\b','',prefix))
            if not scope(name,op,e) or not any(actual==[abi_parameter(p) for p in shape] for shape in shapes) or normalized_return not in [canonical(t) for t in returns]:continue
            path=probe/(c['symbol']+'.c');path.write_text(''.join('#include <'+h+'>\n' for h in headers)+'void probe(void){(void)&'+c['symbol']+';}\n')
            command=[str(compiler),'-mcpu=cortex-m4','-mthumb','-mfloat-abi=soft','-fsyntax-only',*['-D'+d for d in defines],
                *[v for inc in includes for v in ['-I',str(inc)]],str(path)]
            p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            write_json(path.with_suffix('.json'),{'command':command,'returncode':p.returncode,'diagnostic':p.stdout})
            if p.returncode:rejected.append({'symbol':c['symbol'],'reason':'目标声明编译不通过'});continue
            validation=guard.check(op,e,required_gpio_direction='output' if op=='gpio.configure' and len(actual)==1 else None) if guard else None
            if validation and not validation['accepted']:
                rejected.append({'symbol':c['symbol'],'rank':c['rank'],'reason':'operation-contract-conflict','evidence':validation});continue
            selected[op]={'candidate':c,'entity':e,'rejected':rejected,'owner':'frozen-ranking-with-explicit-abi-profile','contract_validation':validation};break
        else:selected[op]={'candidate':None,'entity':None,'rejected':rejected,'owner':'unresolved-no-public-abi-compatible-candidate'}
    write_json(base/name/'typed-selection.json',{'selections':selected,'reads_reference_labels':False,'ranker_changed':False,
        'policy':'冻结候选序列按公开ABI与模块过滤；未绑定操作保留零调用与未验证状态；不回退参考'})
    return sdk,ir,selected


def target_assets(root,name,app):
    source=root/'sdk'/name/'source';extra='';providers=[]
    if name.startswith('stellaris'):
        includes=[app,source,source/'inc',source/'driverlib'];defines=['PART_LM3S6965','TARGET_IS_TEMPEST_RB1','gcc']
        headers=['inc/hw_types.h','inc/hw_memmap.h','inc/hw_ints.h',*[f'driverlib/{x}.h' for x in ['sysctl','interrupt','gpio','uart','timer']]]
        providers=[source/'driverlib'/(x+'.c') for x in ['sysctl','interrupt','gpio','uart','timer','cpu']]
        meta={'board':'qemu_cortex_m3','platform':'qemu-lm3s6965','simulation_kind':'qemu','cpu':'cortex-m3','flash_address':0,'ram_size':65536,
              'cpu_hz':12000000,'gpio_irq':1,'timer_irq':19,'probe_irq':7,'timer_frequency':12000000,'priority_group':4,'has_sdk_vector':True,'writable_vector_section':True,'has_timer_enable_probe':True}
    elif name.startswith('asf3'):
        inc=['sam/utils','sam/utils/header_files','sam/utils/preprocessor','sam/utils/cmsis/sam4s/include','thirdparty/CMSIS/Include',
             'common/utils','common/utils/interrupt','common/services/clock','common/services/clock/sam4s',
             *['sam/drivers/'+x for x in ['pmc','pio','tc','uart','usart','pdc','efc','wdt']]]
        includes=[app,*[source/x for x in inc]];defines=['__SAM4S16C__','BOARD=0']
        (app/'conf_clock.h').write_text('#define CONFIG_SYSCLK_SOURCE SYSCLK_SRC_MAINCK_12M_RC\n#define CONFIG_SYSCLK_PRES SYSCLK_PRES_1\n')
        (app/'board.h').write_text('#define BOARD_FREQ_SLCK_XTAL 32768u\n#define BOARD_FREQ_MAINCK_XTAL 12000000u\n#define BOARD_FREQ_MAINCK_BYPASS 12000000u\n#define BOARD_OSC_STARTUP_US 15625u\n')
        headers=['compiler.h','pmc.h','sysclk.h','pio.h','pio_handler.h','uart.h','tc.h']
        providers=[source/'sam/drivers'/x/(x+'.c') for x in ['pmc','pio','tc','uart','usart','efc','wdt']]
        providers += [source/'sam/drivers/pio/pio_handler.c',source/'common/services/clock/sam4s/sysclk.c',source/'sam/utils/cmsis/sam4s/source/templates/system_sam4s.c']
        meta={'board':'sam4s_xplained','platform':'sam4s.repl','simulation_kind':'renode','flash_address':0x400000,'ram_size':131072,
              'cpu_hz':12000000,'gpio_irq':11,'timer_irq':23,'probe_irq':21,'timer_frequency':93750,'priority_group':3,'has_sdk_vector':False,
              'uart_name':'uart0','gpio_connection':'pioA: { 0 -> pioA@1 }','has_timer_enable_probe':True,'model_caveat':'PMC仅部分状态占位，时钟门控独立验证受模型限制'}
    else:
        configdir=app/'sdk-private';configdir.mkdir(exist_ok=True)
        for filename in ['sdk_config.h','nrfx_config.h','nrfx_glue.h','nrfx_log.h']:
            (app/filename).unlink(missing_ok=True)
        (configdir/'sdk_config.h').write_text('#define NRF_LOG_ENABLED 0\n')
        (configdir/'nrfx_config.h').write_text('''#define NRFX_UART_ENABLED 1
#define NRFX_UART0_ENABLED 1
#define NRFX_TIMER_ENABLED 1
#define NRFX_TIMER1_ENABLED 1
#define NRFX_GPIOTE_ENABLED 1
#define NRFX_GPIOTE_CONFIG_NUM_OF_LOW_POWER_EVENTS 4
#define NRFX_CLOCK_ENABLED 1
#define NRFX_CLOCK_CONFIG_LF_SRC 1
#define NRFX_CLOCK_CONFIG_IRQ_PRIORITY 3
#define NRFX_GPIOTE_CONFIG_IRQ_PRIORITY 3
#define NRFX_UART_DEFAULT_CONFIG_HWFC 0
#define NRFX_UART_DEFAULT_CONFIG_PARITY 0
#define NRFX_UART_DEFAULT_CONFIG_BAUDRATE 30801920
#define NRFX_UART_DEFAULT_CONFIG_IRQ_PRIORITY 3
#define NRFX_TIMER_DEFAULT_CONFIG_FREQUENCY 0
#define NRFX_TIMER_DEFAULT_CONFIG_MODE 0
#define NRFX_TIMER_DEFAULT_CONFIG_BIT_WIDTH 0
#define NRFX_TIMER_DEFAULT_CONFIG_IRQ_PRIORITY 3
''')
        (configdir/'nrfx_glue.h').write_text('''#include <nrf.h>
#define NRFX_ASSERT(x) ((void)0)
#define NRFX_STATIC_ASSERT(x) _Static_assert(x,"nrfx")
#define NRFX_IRQ_PRIORITY_SET(i,p) NVIC_SetPriority(i,p)
#define NRFX_IRQ_ENABLE(i) NVIC_EnableIRQ(i)
#define NRFX_IRQ_IS_ENABLED(i) NVIC_GetEnableIRQ(i)
#define NRFX_IRQ_DISABLE(i) NVIC_DisableIRQ(i)
#define NRFX_IRQ_PENDING_SET(i) NVIC_SetPendingIRQ(i)
#define NRFX_IRQ_PENDING_CLEAR(i) NVIC_ClearPendingIRQ(i)
#define NRFX_IRQ_IS_PENDING(i) NVIC_GetPendingIRQ(i)
#define NRFX_CRITICAL_SECTION_ENTER() uint32_t nrfx_mask=__get_PRIMASK();__disable_irq()
#define NRFX_CRITICAL_SECTION_EXIT() __set_PRIMASK(nrfx_mask)
#define NRFX_DELAY_US(x) do{for(volatile unsigned i=0;i<(unsigned)(x)*16u;i++)__NOP();}while(0)
#define NRFX_CLZ(x) __CLZ(x)
#define NRFX_CTZ(x) __builtin_ctz(x)
#define NRFX_EVENT_READBACK_ENABLED 1
#define NRFX_HW_HAS_DPPI 0
''')
        (configdir/'nrfx_log.h').write_text(''.join('#define NRFX_LOG_'+x+'(...) ((void)0)\n' for x in ['INFO','DEBUG','WARNING','ERROR','HEXDUMP_DEBUG'])+'#define NRFX_LOG_ERROR_STRING_GET(x) ""\n')
        inc=['modules/nrfx','modules/nrfx/mdk','modules/nrfx/hal','modules/nrfx/drivers/include','modules/nrfx/helpers','components/toolchain/cmsis/include']
        includes=[configdir,*[source/x for x in inc],root.parent/'evaluation-sdks/revision-nrf5-sdk/modules/nrfx/mdk'];defines=['NRF52840_XXAA']
        headers=['nrfx_clock.h','nrfx_uart.h','nrfx_timer.h','nrfx_gpiote.h','nrf_gpio.h','nrf_uart.h','nrf_timer.h']
        providers=[source/'modules/nrfx/drivers/src'/('nrfx_'+x+'.c') for x in ['clock','uart','timer','gpiote']]
        providers += [source/'modules/nrfx/mdk/system_nrf52840.c']
        meta={'board':'nrf52840dk/nrf52840','platform':'nrf52840.repl','simulation_kind':'renode','flash_address':0,'ram_size':262144,
              'cpu_hz':64000000,'os_tick_hz':32768,'gpio_irq':6,'timer_irq':9,'probe_irq':21,'timer_frequency':1000000,'priority_group':3,'has_sdk_vector':True,
              'uart_name':'uart0','gpio_connection':'gpio0: { 12 -> gpio0@13 }','omit_remote_svd_metadata':True,'uart_easy_dma':False,
              'zephyr_exclusive_nodes':['uart0']}
    return source,headers,includes,defines,providers,meta


def prepare(root,name,app,contract_guard=False):
    source,headers,includes,defines,providers,meta=target_assets(root,name,app)
    sdk,ir,chosen=select(root,name,app,headers,includes,defines,contract_guard)
    fn={op:r['candidate']['symbol'] if r['candidate'] else 'BSP_UNBOUND' for op,r in chosen.items()}
    def F(op):return fn.get(op,'BSP_UNBOUND')
    operations=list(__import__('bspforge.operation_ranking',fromlist=['OPERATION_DESCRIPTIONS']).OPERATION_DESCRIPTIONS)
    mask=sum(1<<operations.index(op) for op,row in chosen.items() if row['candidate'])
    text='#include "sdk_api.h"\n'+''.join('#include <'+h+'>\n' for h in headers)
    text+=f'\nstatic uint32_t calls[19];\n#define BOUND_MASK {mask}u\n#define COUNT(op) (calls[op]+=!!(BOUND_MASK&(1u<<(op))))\n#define BSP_UNBOUND(...) 0\nuint32_t sdk_calls(int op){{return calls[op];}}\n'
    if name.startswith('stellaris'):
        text+=f'''
int sdk_clock_initialize(void){{COUNT(0);{F('clock.initialize')}(SYSCTL_SYSDIV_1|SYSCTL_USE_OSC|SYSCTL_OSC_MAIN|SYSCTL_XTAL_12MHZ);return 1;}}
void sdk_clock_enable(void){{COUNT(1);{F('clock.enable')}(SYSCTL_PERIPH_TIMER1);}}
void sdk_clock_disable(void){{COUNT(2);{F('clock.disable')}(SYSCTL_PERIPH_TIMER1);}}
int sdk_clock_enabled(void){{return !!(*(volatile uint32_t*)0x400fe104u&(1u<<17));}}
uint32_t sdk_clock_frequency(void){{COUNT(3);return {F('clock.get_frequency')}();}}
void sdk_interrupt_initialize(void){{COUNT(4);{F('interrupt.initialize')}(3);}}
void sdk_interrupt_enable(int i){{COUNT(5);{F('interrupt.enable')}(i+16);}}
void sdk_interrupt_disable(int i){{COUNT(6);{F('interrupt.disable')}(i+16);}}
void sdk_interrupt_register(int i,void(*h)(void)){{COUNT(7);{F('interrupt.register')}(i+16,h);}}
int sdk_uart_setup(void){{COUNT(8);SysCtlPeripheralEnable(SYSCTL_PERIPH_UART0);SysCtlPeripheralEnable(SYSCTL_PERIPH_GPIOA);GPIOPinTypeUART(GPIO_PORTA_BASE,3);{F('uart.configure')}(UART0_BASE,12000000,115200,UART_CONFIG_WLEN_8|UART_CONFIG_STOP_ONE|UART_CONFIG_PAR_NONE);UARTEnable(UART0_BASE);return 0;}}
void sdk_uart_putc(int c){{COUNT(9);while(!UARTSpaceAvail(UART0_BASE)){{}}{F('uart.write')}(UART0_BASE,(uint8_t)c);}}
int sdk_uart_getc(void){{if(!UARTCharsAvail(UART0_BASE))return -1;COUNT(10);return {F('uart.read')}(UART0_BASE);}}
void sdk_gpio_mode(int x){{(void)x;COUNT(11);SysCtlPeripheralEnable(SYSCTL_PERIPH_GPIOB);{F('gpio.configure')}(GPIO_PORTB_BASE,1,GPIO_DIR_MODE_OUT);{F('gpio.configure')}(GPIO_PORTB_BASE,2,GPIO_DIR_MODE_IN);}}
void sdk_gpio_write(int v){{COUNT(12);{F('gpio.write')}(GPIO_PORTB_BASE,1,v?1:0);}}
int sdk_gpio_read(void){{COUNT(13);return !!{F('gpio.read')}(GPIO_PORTB_BASE,2);}}
static void(*gpio_cb)(void*);static void*gpio_arg;
static void port_callback(void){{GPIOPinIntClear(GPIO_PORTB_BASE,2);if(gpio_cb)gpio_cb(gpio_arg);}}
void sdk_gpio_attach(void(*cb)(void*),void*arg){{COUNT(14);gpio_cb=cb;gpio_arg=arg;GPIOIntTypeSet(GPIO_PORTB_BASE,2,GPIO_RISING_EDGE);{F('gpio.attach_irq')}(GPIO_PORTB_BASE,port_callback);}}
void sdk_gpio_irq_enable(int e){{if(e){{GPIOPinIntClear(GPIO_PORTB_BASE,2);IntPendClear(INT_GPIOB);GPIOPinIntEnable(GPIO_PORTB_BASE,2);}}else GPIOPinIntDisable(GPIO_PORTB_BASE,2);}}
void sdk_gpio_irq_handler(void){{port_callback();}}
void sdk_timer_initialize(void){{COUNT(15);SysCtlPeripheralEnable(SYSCTL_PERIPH_TIMER0);{F('timer.initialize')}(TIMER0_BASE,TIMER_CFG_PERIODIC);TimerIntEnable(TIMER0_BASE,TIMER_TIMA_TIMEOUT);}}
void sdk_timer_start(void){{COUNT(16);{F('timer.start')}(TIMER0_BASE,TIMER_A);}}
void sdk_timer_stop(void){{COUNT(17);{F('timer.stop')}(TIMER0_BASE,TIMER_A);}}
void sdk_timer_interval(uint32_t t){{COUNT(18);{F('timer.set_interval')}(TIMER0_BASE,TIMER_A,t);}}
uint32_t sdk_timer_count(void){{return TimerValueGet(TIMER0_BASE,TIMER_A);}}
uint32_t sdk_timer_compare(void){{return TimerLoadGet(TIMER0_BASE,TIMER_A);}}
int sdk_timer_running(void){{return !!(*(volatile uint32_t*)0x4003000cu&1u);}}
void sdk_timer_clear(void){{TimerIntClear(TIMER0_BASE,TIMER_TIMA_TIMEOUT);}}
void sdk_timer_reset(void){{}}
'''
    elif name.startswith('asf3'):
        symbol=F('gpio.write');toggle='clear' in symbol.lower()
        write=f"if(v)pio_set(PIOA,1);else {symbol}(PIOA,1);" if toggle else f"if(v){symbol}(PIOA,1);else pio_clear(PIOA,1);"
        text+=f'''
int sdk_clock_initialize(void){{COUNT(0);{F('clock.initialize')}();return 1;}}
void sdk_clock_enable(void){{COUNT(1);{F('clock.enable')}(ID_TC1);}}
void sdk_clock_disable(void){{COUNT(2);{F('clock.disable')}(ID_TC1);}}
int sdk_clock_enabled(void){{return !!(PMC->PMC_PCSR0&(1u<<ID_TC1));}}
uint32_t sdk_clock_frequency(void){{COUNT(3);return {F('clock.get_frequency')}();}}
void sdk_interrupt_initialize(void){{COUNT(4);{F('interrupt.initialize')}(3);}}
void sdk_interrupt_enable(int i){{COUNT(5);{F('interrupt.enable')}((IRQn_Type)i);}}
void sdk_interrupt_disable(int i){{COUNT(6);{F('interrupt.disable')}((IRQn_Type)i);}}
void sdk_interrupt_register(int i,void(*h)(void)){{(void)i;(void)h;}}
int sdk_uart_setup(void){{sam_uart_opt_t c={{.ul_mck=12000000,.ul_baudrate=115200,.ul_mode=UART_MR_PAR_NO}};COUNT(8);pmc_enable_periph_clk(ID_UART0);{F('uart.configure')}(UART0,&c);uart_enable(UART0);return 0;}}
void sdk_uart_putc(int c){{COUNT(9);while(!uart_is_tx_ready(UART0)){{}}{F('uart.write')}(UART0,(uint8_t)c);}}
int sdk_uart_getc(void){{uint8_t c;if(!uart_is_rx_ready(UART0))return -1;COUNT(10);{F('uart.read')}(UART0,&c);return c;}}
void sdk_gpio_mode(int x){{(void)x;COUNT(11);pmc_enable_periph_clk(ID_PIOA);{F('gpio.configure')}(PIOA,PIO_OUTPUT_0,1,PIO_DEFAULT);{F('gpio.configure')}(PIOA,PIO_INPUT,2,PIO_DEFAULT);}}
void sdk_gpio_write(int v){{COUNT(12);{write}}}
int sdk_gpio_read(void){{COUNT(13);return !!{F('gpio.read')}(PIOA,PIO_INPUT,2);}}
static void(*gpio_cb)(void*);static void*gpio_arg;
static void pio_callback(uint32_t id,uint32_t mask){{(void)id;(void)mask;if(gpio_cb)gpio_cb(gpio_arg);}}
void sdk_gpio_attach(void(*cb)(void*),void*arg){{COUNT(14);gpio_cb=cb;gpio_arg=arg;{F('gpio.attach_irq')}(PIOA,ID_PIOA,2,PIO_IT_RISE_EDGE,pio_callback);}}
void sdk_gpio_irq_enable(int e){{if(e)pio_enable_interrupt(PIOA,2);else pio_disable_interrupt(PIOA,2);}}
void sdk_gpio_irq_handler(void){{pio_handler_process(PIOA,ID_PIOA);}}
void sdk_timer_initialize(void){{COUNT(15);pmc_enable_periph_clk(ID_TC0);{F('timer.initialize')}(TC0,0,TC_CMR_TCCLKS_TIMER_CLOCK4|TC_CMR_WAVE|TC_CMR_WAVSEL_UP_RC);tc_enable_interrupt(TC0,0,TC_IER_CPCS);}}
void sdk_timer_start(void){{COUNT(16);{F('timer.start')}(TC0,0);}}
void sdk_timer_stop(void){{COUNT(17);{F('timer.stop')}(TC0,0);}}
void sdk_timer_interval(uint32_t t){{COUNT(18);{F('timer.set_interval')}(TC0,0,t);}}
uint32_t sdk_timer_count(void){{return tc_read_cv(TC0,0);}}
uint32_t sdk_timer_compare(void){{return tc_read_rc(TC0,0);}}
int sdk_timer_running(void){{return !!(TC0->TC_CHANNEL[0].TC_SR&TC_SR_CLKSTA);}}
void sdk_timer_clear(void){{(void)tc_get_status(TC0,0);}}
void sdk_timer_reset(void){{}}
'''
    else:
        clock_parameters=typed_parameters(chosen['clock.initialize']['entity']['signature']) if chosen['clock.initialize']['entity'] else []
        clock_argument='clock_callback' if clock_parameters else ''
        text+=f'''
static const nrfx_uart_t uart=NRFX_UART_INSTANCE(0);static const nrfx_timer_t timer=NRFX_TIMER_INSTANCE(1);
static void clock_callback(nrfx_clock_evt_type_t event){{(void)event;}}
int sdk_clock_initialize(void){{COUNT(0);return {F('clock.initialize')}({clock_argument})==NRFX_SUCCESS;}}
void sdk_clock_enable(void){{COUNT(1);{F('clock.enable')}();}}
void sdk_clock_disable(void){{COUNT(2);{F('clock.disable')}();}}
int sdk_clock_enabled(void){{return !!(NRF_CLOCK->HFCLKSTAT&1u);}}
uint32_t sdk_clock_frequency(void){{return SystemCoreClock;}}
void sdk_interrupt_initialize(void){{COUNT(4);{F('interrupt.initialize')}(3);}}
void sdk_interrupt_enable(int i){{COUNT(5);{F('interrupt.enable')}((IRQn_Type)i);}}
void sdk_interrupt_disable(int i){{COUNT(6);{F('interrupt.disable')}((IRQn_Type)i);}}
void sdk_interrupt_register(int i,void(*h)(void)){{COUNT(7);{F('interrupt.register')}((IRQn_Type)i,(uint32_t)(uintptr_t)h);}}
int sdk_uart_setup(void){{nrfx_uart_config_t c=NRFX_UART_DEFAULT_CONFIG;c.pseltxd=6;c.pselrxd=8;c.baudrate=NRF_UART_BAUDRATE_115200;c.interrupt_priority=3;COUNT(8);nrfx_err_t r={F('uart.configure')}(&uart,&c,0);if(r==NRFX_SUCCESS)nrfx_uart_rx_enable(&uart);return r==NRFX_SUCCESS?0:-1;}}
void sdk_uart_putc(int c){{uint8_t v=c;COUNT(9);(void){F('uart.write')}(&uart,&v,1);}}
int sdk_uart_getc(void){{uint8_t v;if(!nrf_uart_event_check(NRF_UART0,NRF_UART_EVENT_RXDRDY))return -1;COUNT(10);(void){F('uart.read')}(&uart,&v,1);return v;}}
void sdk_gpio_mode(int x){{(void)x;COUNT(11);{F('gpio.configure')}(12);nrf_gpio_cfg_input(13,NRF_GPIO_PIN_NOPULL);}}
void sdk_gpio_write(int v){{COUNT(12);{F('gpio.write')}(12,v?1:0);}}
int sdk_gpio_read(void){{COUNT(13);return !!{F('gpio.read')}(13);}}
static void(*gpio_cb)(void*);static void*gpio_arg;
static void gpio_callback(nrfx_gpiote_pin_t p,nrf_gpiote_polarity_t a){{(void)p;(void)a;if(gpio_cb)gpio_cb(gpio_arg);}}
void sdk_gpio_attach(void(*cb)(void*),void*arg){{nrfx_gpiote_in_config_t c=NRFX_GPIOTE_CONFIG_IN_SENSE_LOTOHI(true);COUNT(14);gpio_cb=cb;gpio_arg=arg;if(!nrfx_gpiote_is_init())nrfx_gpiote_init();(void){F('gpio.attach_irq')}(13,&c,gpio_callback);}}
void sdk_gpio_irq_enable(int e){{if(e)nrfx_gpiote_in_event_enable(13,true);else nrfx_gpiote_in_event_disable(13);}}
void sdk_gpio_irq_handler(void){{nrfx_gpiote_irq_handler();}}
static void timer_callback(nrf_timer_event_t e,void*a){{(void)e;(void)a;}}
void sdk_timer_initialize(void){{nrfx_timer_config_t c=NRFX_TIMER_DEFAULT_CONFIG;c.frequency=NRF_TIMER_FREQ_1MHz;c.bit_width=NRF_TIMER_BIT_WIDTH_32;c.interrupt_priority=3;COUNT(15);(void){F('timer.initialize')}(&timer,&c,timer_callback);nrf_timer_shorts_enable(NRF_TIMER1,NRF_TIMER_SHORT_COMPARE0_CLEAR_MASK);}}
void sdk_timer_start(void){{COUNT(16);{F('timer.start')}(&timer);}}
void sdk_timer_stop(void){{COUNT(17);{F('timer.stop')}(&timer);}}
void sdk_timer_interval(uint32_t t){{COUNT(18);{F('timer.set_interval')}(&timer,NRF_TIMER_CC_CHANNEL0,t,true);}}
uint32_t sdk_timer_count(void){{nrf_timer_task_trigger(NRF_TIMER1,NRF_TIMER_TASK_CAPTURE1);return nrf_timer_cc_read(NRF_TIMER1,NRF_TIMER_CC_CHANNEL1);}}
uint32_t sdk_timer_compare(void){{return nrf_timer_cc_read(NRF_TIMER1,NRF_TIMER_CC_CHANNEL0);}}
void sdk_timer_clear(void){{nrf_timer_event_clear(NRF_TIMER1,NRF_TIMER_EVENT_COMPARE0);}}
void sdk_timer_reset(void){{nrf_timer_task_trigger(NRF_TIMER1,NRF_TIMER_TASK_CLEAR);}}
'''
    namespace=app/'sdk_namespace.h';exported={e['name'] for e in ir['functions'] if not re.search(r'\bstatic\b',e.get('signature','')) and re.fullmatch(r'[A-Za-z_]\w*',e['name'])}
    exported-= C_KEYWORDS|{'__attribute__','__asm__','assert_param'}
    exported.update(exported_data_symbols(root,providers,includes,defines,app/'data-symbol-probes'))
    exported.update(['SystemCoreClock','SystemInit','SystemCoreClockUpdate'])
    assembly_exceptions=['SysCtlDelay'] if name.startswith('stellaris') else []
    exported.difference_update(assembly_exceptions)
    namespace.write_text(''.join('#define '+x+' bsp_input_'+x+'\n' for x in sorted(exported)))
    (app/'sdk_binding.c').write_text('#include "sdk_namespace.h"\n'+text)
    assets={**meta,'source_root':str(source),'providers':[str(app/'sdk_binding.c'),*map(str,providers)],'includes':list(map(str,includes)),
        'defines':defines,'namespace_header':str(namespace),'public_bound_mask':mask,'explicit_profile':True,'reference_read':False,
        'assembly_namespace_exceptions':assembly_exceptions,'uart_first':True}
    write_json(app/'sdk-build-assets.json',assets)
    return assets
