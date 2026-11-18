"""替换SDK的公开ABI配置及绑定生成；不读取参考、分数阈值或运行结果。"""
from pathlib import Path
import re
import subprocess
from bspforge.common import read_json,write_json
try:
    from scripts.run_sifive_zephyr_simulation import typed_parameters
except ModuleNotFoundError as error:
    if error.name!='scripts':raise
    from run_sifive_zephyr_simulation import typed_parameters

ABI={
 'max32650-msdk':{
  'clock.initialize':([], 'void'),'clock.enable':(['mxc_sys_periph_clock_t'],'int'),
  'clock.disable':(['mxc_sys_periph_clock_t'],'int'),'clock.get_frequency':([],'uint32_t'),
  'interrupt.initialize':(['uint32_t'],'void'),'interrupt.enable':(['IRQn_Type'],'void'),
  'interrupt.disable':(['IRQn_Type'],'void'),'interrupt.register':(['IRQn_Type','void(*)(void)'],'void'),
  'uart.configure':(['mxc_uart_regs_t*','unsigned int'],'int'),
  'uart.write':(['mxc_uart_regs_t*','uint8_t'],'int'),'uart.read':(['mxc_uart_regs_t*'],'int'),
  'gpio.configure':(['const mxc_gpio_cfg_t*'],'int'),
  'gpio.write':(['mxc_gpio_regs_t*','uint32_t','uint32_t'],'void'),
  'gpio.read':(['mxc_gpio_regs_t*','uint32_t'],'uint32_t'),
  'gpio.attach_irq':(['const mxc_gpio_cfg_t*','mxc_gpio_callback_fn','void*'],'void'),
  'timer.initialize':(['mxc_tmr_regs_t*','mxc_tmr_cfg_t*'],'void'),
  'timer.start':(['mxc_tmr_regs_t*'],'void'),'timer.stop':(['mxc_tmr_regs_t*'],'void'),
  'timer.set_interval':(['mxc_tmr_regs_t*','uint32_t'],'void')},
 'stm32f4-stdperiph':{
  'clock.initialize':([],'void'),'clock.enable':(['uint32_t','FunctionalState'],'void'),
  'clock.disable':(['uint32_t','FunctionalState'],'void'),
  'clock.get_frequency':(['RCC_ClocksTypeDef*'],'void'),
  'interrupt.initialize':(['uint32_t'],'void'),'interrupt.enable':(['IRQn_Type'],'void'),
  'interrupt.disable':(['IRQn_Type'],'void'),
  'uart.configure':(['USART_TypeDef*','USART_InitTypeDef*'],'void'),
  'uart.write':(['USART_TypeDef*','uint16_t'],'void'),'uart.read':(['USART_TypeDef*'],'uint16_t'),
  'gpio.configure':(['GPIO_TypeDef*','GPIO_InitTypeDef*'],'void'),
  'gpio.write':(['GPIO_TypeDef*','uint16_t','BitAction'],'void'),
  'gpio.read':(['GPIO_TypeDef*','uint16_t'],'uint8_t'),
  'timer.initialize':(['TIM_TypeDef*','TIM_TimeBaseInitTypeDef*'],'void'),
  'timer.start':(['TIM_TypeDef*','FunctionalState'],'void'),
  'timer.stop':(['TIM_TypeDef*','FunctionalState'],'void'),
  'timer.set_interval':(['TIM_TypeDef*','uint32_t'],'void')},
}

def canonical(value):
    return re.sub(r'\s+','',re.sub(r'\(\s*\*\s*\w+\s*\)','(*)',value))

def public_scope(name,operation,e):
    path=e['file'];symbol=e['name'];signature=e.get('signature','')
    if name=='max32650-msdk':
        if operation=='clock.initialize':return '/Source/system_' in path
        if operation.startswith('clock.'):return '/Source/SYS/' in path
        if operation.startswith('interrupt.'):
            return path.endswith('core_cm4.h') if operation!='interrupt.register' else '/Source/SYS/nvic_table.c' in path
        kind={'uart':'UART','gpio':'GPIO','timer':'TMR'}[operation.split('.')[0]]
        return '/Source/'+kind+'/' in path and symbol.startswith('MXC_') and not symbol.startswith('MXC_'+kind+'_Rev') and 'static ' not in signature
    if operation=='clock.initialize':return '/Source/Templates/system_stm32f4xx.c' in path
    if operation in ['clock.enable','clock.disable']:
        # 目标GPIO端口属于AHB1时钟域，硬件域是实例契约，不是参考函数回退。
        return path.endswith('stm32f4xx_rcc.c') and 'AHB1' in symbol
    if operation=='clock.get_frequency':return path.endswith('stm32f4xx_rcc.c')
    if operation=='interrupt.initialize':return path.endswith('misc.c')
    if operation.startswith('interrupt.'):return path.endswith('core_cm4.h')
    suffix={'uart':'usart','gpio':'gpio','timer':'tim'}[operation.split('.')[0]]
    return path.endswith('stm32f4xx_'+suffix+'.c')

def compiler_visible(root,name,source,symbol):
    """用真实目标宏验证公共声明，过滤私有函数与其他芯片分支的同型接口。"""
    folder=root/'workspace/revision-r1-replacements'/name/'public-api-probes';folder.mkdir(parents=True,exist_ok=True)
    result_path=folder/(symbol+'.json')
    if result_path.exists():return read_json(result_path)['visible']
    if name.startswith('max'):
        inc=[source/'Libraries/PeriphDrivers/Include/MAX32650',source/'Libraries/CMSIS/Include',source/'Libraries/CMSIS/Device/Maxim/MAX32650/Include']
        headers=['mxc_device.h','mxc_sys.h','nvic_table.h','gpio.h','uart.h','tmr.h'];defines=['TARGET=MAX32650','TARGET_REV=0x4131']
    else:
        inc=[source/'Libraries/STM32F4xx_StdPeriph_Driver/inc',source/'Libraries/CMSIS/Include',source/'Libraries/CMSIS/Device/ST/STM32F4xx/Include']
        headers=['stm32f4xx.h','stm32f4xx_rcc.h','stm32f4xx_gpio.h','stm32f4xx_usart.h','stm32f4xx_tim.h','misc.h'];defines=['STM32F40_41xxx']
    code=''.join('#include <'+h+'>\n' for h in headers)+'void declaration_probe(void){(void)&'+symbol+';}\n'
    path=folder/(symbol+'.c');path.write_text(code)
    command=[str(root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc'),'-mthumb','-mcpu=cortex-m4','-mfloat-abi=soft','-fsyntax-only',*['-D'+v for v in defines],*[v for p in inc for v in ['-I',str(p)]],str(path)]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    write_json(result_path,{'command':command,'visible':result.returncode==0,'returncode':result.returncode,'diagnostic':result.stdout})
    return result.returncode==0

def select(root,name,contract_guard=False):
    out=root/'experiments/revision-r1-replacements';dest=out/name
    sdk=next(s for s in read_json(out/'manifest.json')['sdks'] if s['name']==name)
    ir=read_json(dest/'ir'/(sdk['sdk_id']+'.json'));entities={e['id']:e for e in ir['functions']}
    bundle=read_json(dest/'frozen-runtime-bundle.json');selected={}
    from bspforge.binding_contract_guard import BindingContractGuard
    guard=BindingContractGuard(Path(sdk['source_path']),ir) if contract_guard else None
    for operation,(parameters,return_type) in ABI[name].items():
        if operation=='clock.initialize':
            # CMSIS启动约定属于OS端口元数据，单列归属，不伪装成排序命中。
            startup=[e for e in ir['functions'] if e['name']=='SystemInit' and '/Source/' in e['file'] and e['file'].endswith('.c')]
            if len(startup)!=1 or not compiler_visible(root,name,Path(sdk['source_path']),'SystemInit'):
                raise ValueError((name,'无法恢复唯一CMSIS启动资产'))
            selected[operation]={'candidate':None,'entity':startup[0],'abi':[],'return_type':'void','rejected':[],
                'owner':'cmsis-standard-startup-asset','raw_top1':bundle['operations'][operation]['candidates'][0]['symbol']}
            continue
        rejected=[]
        for candidate in bundle['operations'][operation]['candidates']:
            e=entities[candidate['entity_id']];sig=e.get('signature','')
            actual=[canonical(v) for v in typed_parameters(sig)]
            prefix=sig.split(e['name']+'(',1)[0] if e['name']+'(' in sig else sig.split(e['name']+' (',1)[0]
            shapes=[parameters]
            if name=='max32650-msdk' and operation=='gpio.write':shapes.append(['mxc_gpio_regs_t*','uint32_t'])
            matches=any(actual==[canonical(v) for v in shape] for shape in shapes) and re.search(r'\b'+re.escape(return_type)+r'\s*$',prefix)
            visible=bool(matches and public_scope(name,operation,e) and compiler_visible(root,name,Path(sdk['source_path']),e['name']))
            validation=guard.check(operation,e) if visible and guard else None
            if visible and (validation is None or validation['accepted']):
                selected[operation]={'candidate':candidate,'entity':e,'abi':typed_parameters(sig),'return_type':return_type,'rejected':rejected,'contract_validation':validation};break
            if visible and validation and not validation['accepted']:
                rejected.append({'symbol':e['name'],'rank':candidate['rank'],'signature':sig,'reason':'operation-contract-conflict','evidence':validation});continue
            rejected.append({'symbol':e['name'],'rank':candidate['rank'],'signature':sig,'reason':'ABI/public-module/target-clock-domain/active-declaration'})
        else:raise ValueError((name,operation,'无满足公开ABI的候选'))
    write_json(dest/'typed-selection.json',{'reads_reference_labels':False,'ranker_changed':False,'selections':selected,
        'policy':'冻结排名中首个满足SDK公开ABI、目标实例域和模块边界的候选；无真值回退'})
    return sdk,selected

def exported_data_symbols(root,providers,includes,defines,folder):
    """从编译对象恢复外部数据符号，隔离输入SDK与OS自带HAL。"""
    folder.mkdir(parents=True,exist_ok=True)
    binary=root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-'
    names=set();evidence=[]
    for index,path in enumerate(providers):
        obj=folder/f'{index:02d}-{path.stem}.o'
        command=[str(binary)+'gcc','-mthumb','-mcpu=cortex-m4','-mfloat-abi=soft',
            '-ffunction-sections','-fdata-sections','-Dassert_param(x)=((void)0)',*['-D'+d for d in defines],
            *[v for inc in includes for v in ['-I',str(inc)]],'-c',str(path),'-o',str(obj)]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if result.returncode:raise ValueError(('数据符号编译探针失败',str(path),result.stdout))
        output=subprocess.check_output([str(binary)+'nm','-g','--defined-only',str(obj)],text=True)
        data=[line.split()[-1] for line in output.splitlines() if len(line.split())==3 and line.split()[1].upper() in {'B','C','D','G','R','S','V','T','W'}]
        names.update(data);evidence.append({'source':str(path),'command':command,'data_symbols':data})
    write_json(folder/'symbols.json',{'symbols':sorted(names),'evidence':evidence})
    return names


def prepare(root,name,app,contract_guard=False):
    sdk,chosen=select(root,name,contract_guard);source=Path(sdk['source_path'])
    fn={op:r['candidate']['symbol'] if r['candidate'] else r['entity']['name'] for op,r in chosen.items()}
    header='''#include "sdk_api.h"
static uint32_t calls[19];
uint32_t sdk_calls(int op){return calls[op];}
#define COUNT(op) (calls[op]++)
'''
    if name=='max32650-msdk':
        inc=source/'Libraries/PeriphDrivers/Include/MAX32650';src=source/'Libraries/PeriphDrivers/Source'
        includes=[inc,source/'Libraries/CMSIS/Include',source/'Libraries/CMSIS/Device/Maxim/MAX32650/Include']
        providers=[src/s for s in ['SYS/sys_me10.c','SYS/pins_me10.c','SYS/nvic_table.c','GPIO/gpio_me10.c','GPIO/gpio_reva.c','GPIO/gpio_common.c','UART/uart_me10.c','UART/uart_reva.c','UART/uart_common.c','TMR/tmr_me10.c','TMR/tmr_reva.c','TMR/tmr_common.c']]
        providers.append(source/'Libraries/CMSIS/Device/Maxim/MAX32650/Source/system_max32650.c')
        providers += [src/'FLC'/s for s in ['flc_me10.c','flc_reva.c','flc_common.c']]
        support=root.parent/'evaluation-sdks/revision-maxim-msdk/Libraries/PeriphDrivers/Source/SYS'
        providers += [support/'mxc_delay.c',support/'mxc_lock.c']
        includes+=[src/p for p in ['GPIO','UART','TMR','DMA','SYS']]
        write_call=f"{fn['gpio.write']}(MXC_GPIO0,1,value?1:0);"
        if len(chosen['gpio.write']['abi'])==2:
            symbol=fn['gpio.write'];lower=symbol.lower()
            if 'toggle' in lower:write_call=f"if(!!MXC_GPIO_OutGet(MXC_GPIO0,1)!=!!value){symbol}(MXC_GPIO0,1);"
            elif 'set' in lower:write_call=f"if(value){symbol}(MXC_GPIO0,1);else MXC_GPIO_OutClr(MXC_GPIO0,1);"
            elif 'clr' in lower or 'clear' in lower:write_call=f"if(value)MXC_GPIO_OutSet(MXC_GPIO0,1);else {symbol}(MXC_GPIO0,1);"
            else:raise ValueError('两参数写接口缺少可辨识的置位/清零/翻转契约')
            chosen['gpio.write']['parameter_adapter']='布尔电平对应置位/清零配对，或读取现态后按需翻转；辅助函数作为SDK平台资产明列'
        body=f'''#include <mxc_device.h>
#include <mxc_sys.h>
#include <gpio.h>
#include <uart.h>
#include <tmr.h>
#include <nvic_table.h>
static mxc_gpio_cfg_t output={{.port=MXC_GPIO0,.mask=1,.pad=MXC_GPIO_PAD_NONE,.func=MXC_GPIO_FUNC_OUT,.vssel=MXC_GPIO_VSSEL_VDDIO}};
static mxc_gpio_cfg_t input={{.port=MXC_GPIO1,.mask=2,.pad=MXC_GPIO_PAD_NONE,.func=MXC_GPIO_FUNC_IN,.vssel=MXC_GPIO_VSSEL_VDDIO}};
int sdk_clock_initialize(void){{COUNT(0);{fn['clock.initialize']}();return SystemCoreClock>0;}}
void sdk_clock_enable(void){{COUNT(1);(void){fn['clock.enable']}(MXC_SYS_PERIPH_CLOCK_SPI0);}}
void sdk_clock_disable(void){{COUNT(2);(void){fn['clock.disable']}(MXC_SYS_PERIPH_CLOCK_SPI0);}}
int sdk_clock_enabled(void){{return MXC_SYS_IsClockEnabled(MXC_SYS_PERIPH_CLOCK_SPI0);}}
uint32_t sdk_clock_frequency(void){{COUNT(3);return {fn['clock.get_frequency']}();}}
void sdk_interrupt_initialize(void){{COUNT(4);{fn['interrupt.initialize']}(0);}}
void sdk_interrupt_enable(int irq){{COUNT(5);{fn['interrupt.enable']}((IRQn_Type)irq);}}
void sdk_interrupt_disable(int irq){{COUNT(6);{fn['interrupt.disable']}((IRQn_Type)irq);}}
void sdk_interrupt_register(int irq,void(*handler)(void)){{COUNT(7);{fn['interrupt.register']}((IRQn_Type)irq,handler);}}
int sdk_uart_setup(void){{COUNT(8);return {fn['uart.configure']}(MXC_UART0,115200);}}
void sdk_uart_putc(int c){{COUNT(9);(void){fn['uart.write']}(MXC_UART0,(uint8_t)c);}}
int sdk_uart_getc(void){{if(MXC_UART_GetRXFIFOAvailable(MXC_UART0)==0)return -1;COUNT(10);return {fn['uart.read']}(MXC_UART0);}}
void sdk_gpio_mode(int out){{(void)out;MXC_SYS_ClockEnable(MXC_SYS_PERIPH_CLOCK_GPIO0);MXC_SYS_ClockEnable(MXC_SYS_PERIPH_CLOCK_GPIO1);COUNT(11);(void){fn['gpio.configure']}(&input);(void){fn['gpio.configure']}(&output);}}
void sdk_gpio_write(int value){{COUNT(12);{write_call}}}
int sdk_gpio_read(void){{COUNT(13);return !!{fn['gpio.read']}(MXC_GPIO1,2);}}
void sdk_gpio_attach(void(*callback)(void*),void*arg){{COUNT(14);{fn['gpio.attach_irq']}(&input,callback,arg);MXC_GPIO_IntConfig(&input,MXC_GPIO_INT_RISING);}}
void sdk_gpio_irq_enable(int enable){{if(enable){{MXC_GPIO_ClearFlags(MXC_GPIO1,2);NVIC_ClearPendingIRQ(GPIO1_IRQn);MXC_GPIO_EnableInt(MXC_GPIO1,2);}}else MXC_GPIO_DisableInt(MXC_GPIO1,2);}}
void sdk_gpio_irq_handler(void){{MXC_GPIO_Handler(1);}}
void sdk_timer_initialize(void){{mxc_tmr_cfg_t cfg={{.mode=MXC_TMR_MODE_CONTINUOUS,.pres=MXC_TMR_PRES_128,.cmp_cnt=60000,.pol=0}};COUNT(15);{fn['timer.initialize']}(MXC_TMR0,&cfg);}}
void sdk_timer_start(void){{COUNT(16);{fn['timer.start']}(MXC_TMR0);}}
void sdk_timer_stop(void){{COUNT(17);{fn['timer.stop']}(MXC_TMR0);}}
void sdk_timer_interval(uint32_t ticks){{COUNT(18);{fn['timer.set_interval']}(MXC_TMR0,ticks);}}
uint32_t sdk_timer_count(void){{return MXC_TMR_GetCount(MXC_TMR0);}}
uint32_t sdk_timer_compare(void){{return MXC_TMR_GetCompare(MXC_TMR0);}}
void sdk_timer_clear(void){{MXC_TMR_ClearFlags(MXC_TMR0);}}
void sdk_timer_reset(void){{MXC_TMR_SetCount(MXC_TMR0,1);}}
'''
        defines=['TARGET=MAX32650','TARGET_REV=0x4131','MXC_ASSERT_DISABLE']
        gpio_irq=24;timer_irq=5;probe_irq=16;cpu_hz=120000000;uart_address=0x40042000
        platform='max32652.repl';board='max32650evkit';clock_hz=375000
    else:
        driver=source/'Libraries/STM32F4xx_StdPeriph_Driver'
        includes=[driver/'inc',source/'Libraries/CMSIS/Include',source/'Libraries/CMSIS/Device/ST/STM32F4xx/Include']
        providers=[driver/'src'/s for s in ['stm32f4xx_rcc.c','stm32f4xx_gpio.c','stm32f4xx_usart.c','stm32f4xx_tim.c','misc.c']]
        providers.append(source/'Libraries/CMSIS/Device/ST/STM32F4xx/Source/Templates/system_stm32f4xx.c')
        body=f'''#include <stm32f4xx.h>
#include <stm32f4xx_rcc.h>
#include <stm32f4xx_gpio.h>
#include <stm32f4xx_usart.h>
#include <stm32f4xx_tim.h>
#include <misc.h>
int sdk_clock_initialize(void){{COUNT(0);{fn['clock.initialize']}();return SystemCoreClock>0;}}
void sdk_clock_enable(void){{COUNT(1);{fn['clock.enable']}(RCC_AHB1Periph_GPIOB,ENABLE);}}
void sdk_clock_disable(void){{COUNT(2);{fn['clock.disable']}(RCC_AHB1Periph_GPIOB,DISABLE);}}
int sdk_clock_enabled(void){{return !!(RCC->AHB1ENR&RCC_AHB1Periph_GPIOB);}}
uint32_t sdk_clock_frequency(void){{RCC_ClocksTypeDef clocks;COUNT(3);{fn['clock.get_frequency']}(&clocks);return clocks.SYSCLK_Frequency;}}
void sdk_interrupt_initialize(void){{COUNT(4);{fn['interrupt.initialize']}(NVIC_PriorityGroup_4);}}
void sdk_interrupt_enable(int irq){{COUNT(5);{fn['interrupt.enable']}((IRQn_Type)irq);}}
void sdk_interrupt_disable(int irq){{COUNT(6);{fn['interrupt.disable']}((IRQn_Type)irq);}}
void sdk_interrupt_register(int irq,void(*handler)(void)){{(void)irq;(void)handler;}}
int sdk_uart_setup(void){{USART_InitTypeDef cfg;GPIO_InitTypeDef pin;COUNT(8);RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA,ENABLE);RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART2,ENABLE);GPIO_StructInit(&pin);pin.GPIO_Pin=GPIO_Pin_2|GPIO_Pin_3;pin.GPIO_Mode=GPIO_Mode_AF;pin.GPIO_Speed=GPIO_Speed_50MHz;GPIO_Init(GPIOA,&pin);GPIO_PinAFConfig(GPIOA,GPIO_PinSource2,GPIO_AF_USART2);GPIO_PinAFConfig(GPIOA,GPIO_PinSource3,GPIO_AF_USART2);USART_StructInit(&cfg);cfg.USART_BaudRate=115200;{fn['uart.configure']}(USART2,&cfg);USART_Cmd(USART2,ENABLE);return 0;}}
void sdk_uart_putc(int c){{COUNT(9);while(!(USART2->SR&USART_SR_TXE)){{}}{fn['uart.write']}(USART2,(uint16_t)(uint8_t)c);}}
int sdk_uart_getc(void){{if(!(USART2->SR&USART_SR_RXNE))return -1;COUNT(10);return {fn['uart.read']}(USART2)&255;}}
void sdk_gpio_mode(int out){{(void)out;GPIO_InitTypeDef pin;COUNT(11);RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOD|RCC_AHB1Periph_GPIOE,ENABLE);GPIO_StructInit(&pin);pin.GPIO_Pin=GPIO_Pin_13;pin.GPIO_Mode=GPIO_Mode_IN;{fn['gpio.configure']}(GPIOE,&pin);pin.GPIO_Pin=GPIO_Pin_12;pin.GPIO_Mode=GPIO_Mode_OUT;{fn['gpio.configure']}(GPIOD,&pin);}}
void sdk_gpio_write(int value){{COUNT(12);{fn['gpio.write']}(GPIOD,GPIO_Pin_12,value?Bit_SET:Bit_RESET);}}
int sdk_gpio_read(void){{COUNT(13);return !!{fn['gpio.read']}(GPIOE,GPIO_Pin_13);}}
void sdk_gpio_attach(void(*callback)(void*),void*arg){{(void)callback;(void)arg;}}
void sdk_gpio_irq_enable(int enable){{(void)enable;}}
void sdk_gpio_irq_handler(void){{}}
void sdk_timer_initialize(void){{TIM_TimeBaseInitTypeDef cfg;COUNT(15);RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM2,ENABLE);TIM_TimeBaseStructInit(&cfg);cfg.TIM_Prescaler=83;cfg.TIM_Period=60000;{fn['timer.initialize']}(TIM2,&cfg);TIM_ITConfig(TIM2,TIM_IT_Update,ENABLE);}}
void sdk_timer_start(void){{COUNT(16);{fn['timer.start']}(TIM2,ENABLE);}}
void sdk_timer_stop(void){{COUNT(17);{fn['timer.stop']}(TIM2,DISABLE);}}
void sdk_timer_interval(uint32_t ticks){{COUNT(18);{fn['timer.set_interval']}(TIM2,ticks);TIM_GenerateEvent(TIM2,TIM_EventSource_Update);TIM_ClearITPendingBit(TIM2,TIM_IT_Update);}}
uint32_t sdk_timer_count(void){{return TIM_GetCounter(TIM2);}}
uint32_t sdk_timer_compare(void){{return TIM2->ARR;}}
void sdk_timer_clear(void){{TIM_ClearITPendingBit(TIM2,TIM_IT_Update);}}
void sdk_timer_reset(void){{TIM_SetCounter(TIM2,1);}}
'''
        defines=['STM32F40_41xxx','HSE_VALUE=25000000'];gpio_irq=40;timer_irq=28;probe_irq=30;cpu_hz=168000000;uart_address=0x40004400
        platform='stm32f4.repl';board='stm32f4_disco';clock_hz=1000000
    namespace=app/'sdk_namespace.h'
    ir=read_json(root/'experiments/revision-r1-replacements'/name/'ir'/(sdk['sdk_id']+'.json'))
    reserved={'if','else','while','for','switch','return','sizeof','do','case','default','goto','break','continue','typeof','__attribute__','__asm__','assert_param'}
    exported={e['name'] for e in ir['functions'] if e['name'] not in reserved and not re.search(r'\bstatic\b',e.get('signature',''))}
    exported.update(['SystemCoreClock','SystemInit','SystemCoreClockUpdate','ChipRevision',
        'AHBPrescTable','APBPrescTable','MXC_Delay','MXC_DelayAsync','MXC_DelayCheck','MXC_DelayAbort','MXC_GetLock','MXC_FreeLock'])
    exported.update(exported_data_symbols(root,providers,includes,defines,app/'data-symbol-probes'))
    namespace.write_text(''.join('#define '+s+' bsp_input_'+s+'\n' for s in sorted(exported))+'\n#ifndef assert_param\n#define assert_param(value) ((void)0)\n#endif\n')
    (app/'sdk_binding.c').write_text('#include "sdk_namespace.h"\n'+header+body)
    providers.insert(0,app/'sdk_binding.c')
    assets={'providers':list(map(str,providers)),'includes':list(map(str,includes)),'defines':defines,
            'namespace_header':str(namespace),'selected_operations':list(chosen),'board':board,'platform':platform,
            'gpio_irq':gpio_irq,'timer_irq':timer_irq,'probe_irq':probe_irq,'cpu_hz':cpu_hz,'uart_address':uart_address,
            'timer_frequency':clock_hz,'eligible_operations':len(chosen),'source_root':str(source)}
    assets['gpio_connection']='gpio0: { 0 -> gpio1@1 }' if name.startswith('max') else 'gpioPortD: { 12 -> gpioPortE@13 }'
    if name.startswith('max'):assets['gpio_irq']=25
    assets['fixture_note']='跨GPIO端口连接，隔离同一端口自回环的模型状态更新次序；SDK所选函数及行为断言不变'
    write_json(app/'sdk-build-assets.json',assets)
    write_json(root/'experiments/revision-r1-replacements'/name/'typed-selection.json',{
        'reads_reference_labels':False,'ranker_changed':False,'selections':chosen,
        'policy':'冻结排名中首个满足公开ABI和实例域的候选；标准CMSIS启动资产单列，不计为排序命中'})
    return assets
