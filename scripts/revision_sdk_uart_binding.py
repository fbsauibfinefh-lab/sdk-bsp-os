"""新增SDK的串口类型契约与薄绑定；候选顺序来自同一个冻结排序包。"""
from pathlib import Path
import re
import subprocess
import sys
from bspforge.common import read_json,write_json
from run_sifive_zephyr_simulation import typed_parameters

CONTRACTS={
 'sifive-fe310':{'uart.configure':['struct metal_uart*','int'],'uart.write':['struct metal_uart*','int'],'uart.read':['struct metal_uart*','int*']},
 'litex':{'uart.configure':[],'uart.write':['char'],'uart.read':[]},
 'opentitan':{'uart.configure':['const dif_uart_t*','dif_uart_config_t'],'uart.write':['const dif_uart_t*','const uint8_t*','size_t','size_t*'],'uart.read':['const dif_uart_t*','size_t','uint8_t*','size_t*']},
 'asf4-samd21':{'uart.write':['struct _usart_async_device*const','uint8_t'],'uart.read':['const struct _usart_sync_device*const']},
 'ambiq-apollo4':{'uart.configure':['void*','const am_hal_uart_config_t*'],'uart.write':['void*','uint8_t*','uint32_t','uint32_t*'],'uart.read':['void*','uint8_t*','uint32_t','uint32_t*']},
}

def augment(root,name,app,assets):
    dest=root/'experiments/revision-r1-five-sdk'/name
    sdk=next(s for s in read_json(dest.parent/'manifest.json')['sdks'] if s['name']==name)
    source=Path(sdk['source_path']);ir=read_json(dest/'ir'/(sdk['sdk_id']+'.json'));entities={e['id']:e for e in ir['functions']}
    bundle=read_json(dest/'frozen-runtime-bundle.json');selections={}
    for op,params in CONTRACTS[name].items():
        rejected=[]
        for candidate in bundle['operations'][op]['candidates']:
            e=entities[candidate['entity_id']];actual=typed_parameters(e.get('signature',''))
            public=not re.search(r'\bstatic\b',e.get('signature',''))
            if name=='sifive-fe310':public=e['file']=='metal/uart.h'
            if name=='litex':public=e['file']=='libbase/uart.c'
            if name=='asf4-samd21':public=e['file']=='hpl/sercom/hpl_sercom.c' and public
            if name=='opentitan':public=e['file']=='dif/dif_uart.c' and public
            if name=='ambiq-apollo4':public=e['file']=='hal/mcu/am_hal_uart.c' and public
            if public and actual==params:
                selections[op]={'candidate':candidate,'entity':e,'abi':params,'rejected':rejected};break
            rejected.append({'symbol':candidate['symbol'],'rank':candidate['rank'],'abi':actual,'reason':'abi-or-public-scope'})
        else:raise ValueError(f'{name} {op}: no compatible UART candidate')
    write_json(dest/'typed-uart-selection.json',{'reads_reference_labels':False,'selections':selections,
             'profile_contracts':'SDK公开ABI或HPL ABI；框架初始化前提在配置中另列。'})
    write=selections['uart.write']['candidate']['symbol'];read=selections['uart.read']['candidate']['symbol']
    configure=selections.get('uart.configure',{}).get('candidate',{}).get('symbol')
    prefix='''#include <stdint.h>\n#include <stdbool.h>\nstatic uint32_t tx_calls,rx_calls;\nuint32_t sdk_uart_tx_calls(void){return tx_calls;}\nuint32_t sdk_uart_rx_calls(void){return rx_calls;}\n'''
    if name=='sifive-fe310':
        signature=selections['uart.configure']['entity'].get('signature','')
        init_call=f'{configure}(uart,115200);return 0;' if re.search(r'\bvoid\s+'+re.escape(configure)+r'\s*\(',signature) else f'return {configure}(uart,115200);'
        body=f'''#include <metal/uart.h>
static struct metal_uart *uart;
int sdk_uart_setup(void){{uart=metal_uart_get_device(0);{init_call}}}
void sdk_uart_putc(int c){{(void){write}(uart,c);tx_calls++;}}
int sdk_uart_getc(void){{int c=-1;(void){read}(uart,&c);if(c<0)return -1;rx_calls++;return c&255;}}
'''
    elif name=='litex':
        assets['providers'].append(str(source/'libbase/uart.c'))
        assets['defines'].append('UART_POLLING')
        body=f'''#include <uart.h>
int sdk_uart_setup(void){{{configure}();return 0;}}
void sdk_uart_putc(int c){{{write}((char)c);tx_calls++;}}
int sdk_uart_getc(void){{if(!uart_read_nonblock())return -1;rx_calls++;return (uint8_t){read}();}}
'''
        assets['includes'].append(str(source/'libbase'))
    elif name=='asf4-samd21':
        assets['providers'].append(str(source/'hpl/sercom/hpl_sercom.c'))
        assets['includes'].append(str(source/'hpl/sercom'))
        body=f'''#include <hpl_usart_async.h>
#include <hpl_usart_sync.h>
static struct _usart_async_device tx;
static struct _usart_sync_device rx;
int sdk_uart_setup(void){{tx.hw=SERCOM3;rx.hw=SERCOM3;return 0;}}
void sdk_uart_putc(int c){{while(!hri_sercomusart_get_INTFLAG_DRE_bit(SERCOM3)){{}}{write}(&tx,(uint8_t)c);tx_calls++;}}
int sdk_uart_getc(void){{if(!hri_sercomusart_get_INTFLAG_RXC_bit(SERCOM3))return -1;rx_calls++;return (uint8_t){read}(&rx);}}
'''
    elif name=='opentitan':
        repo=root.parent/'evaluation-sdks/revision-opentitan';regpython=root.parent/'tools/opentitan-reggen-venv/bin/python'
        proc=subprocess.run([str(regpython),str(repo/'util/regtool.py'),'-D','-o',str(app/'generated/uart_regs.h'),str(repo/'hw/ip/uart/data/uart.hjson')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (app/'uart-register-generation.log').write_text(proc.stdout)
        if proc.returncode:raise RuntimeError(proc.stdout[-1500:])
        assets['providers'].append(str(source/'dif/dif_uart.c'))
        body=f'''#include "sw/device/lib/dif/dif_uart.h"
static const dif_uart_t uart={{.base_addr={{.base=(volatile void*)0x40000000}}}};
int sdk_uart_setup(void){{dif_uart_config_t c={{.baudrate=115200,.clk_freq_hz=24000000,.parity_enable=kDifToggleDisabled,.tx_enable=kDifToggleEnabled,.rx_enable=kDifToggleEnabled}};return {configure}(&uart,c)==kDifOk?0:-1;}}
void sdk_uart_putc(int c){{uint8_t v=c;size_t written=0;do{{dif_result_t rc={write}(&uart,&v,1,&written);if(rc!=kDifOk)return;}}while(written==0);tx_calls++;}}
int sdk_uart_getc(void){{uint8_t c=0;size_t count=0;dif_result_t rc={read}(&uart,1,&c,&count);if(rc!=kDifOk||count!=1)return -1;rx_calls++;return c;}}
'''
    else:
        assets['providers'].append(str(source/'hal/mcu/am_hal_uart.c'))
        header=app/'sdk_namespace.h'
        reserved={'if','else','while','for','switch','return','sizeof','do','case','default','goto','break','continue','typeof','__attribute__','__asm__'}
        names={e['name'] for e in ir['functions'] if e['file']=='hal/mcu/am_hal_uart.c'
               and e['name'] not in reserved and not re.search(r'\bstatic\b',e.get('signature',''))
               and (e['name'].startswith('am_hal_uart_') or e['evidence'].get('parser')=='tree-sitter')}
        names.update(re.findall(r'\bg_am_hal_uart_\w+\b',(source/'hal/mcu/am_hal_uart.c').read_text()))
        with header.open('a') as f:f.write('\n'.join('#define '+n+' bsp_input_'+n for n in sorted(names))+'\n')
        body=f'''#include "sdk_namespace.h"
#include <am_mcu_apollo.h>
static void *uart;
int sdk_uart_setup(void){{am_hal_uart_config_t c={{.ui32BaudRate=115200,.eDataBits=AM_HAL_UART_DATA_BITS_8,.eParity=AM_HAL_UART_PARITY_NONE,.eStopBits=AM_HAL_UART_ONE_STOP_BIT,.eFlowControl=AM_HAL_UART_FLOW_CTRL_NONE}};if(am_hal_uart_initialize(0,&uart)!=AM_HAL_STATUS_SUCCESS)return -1;return {configure}(uart,&c)==AM_HAL_STATUS_SUCCESS?0:-1;}}
void sdk_uart_putc(int c){{uint8_t v=c;uint32_t n=0;do{{uint32_t rc={write}(uart,&v,1,&n);if(rc)return;}}while(n==0);tx_calls++;}}
int sdk_uart_getc(void){{uint8_t c=0;uint32_t n=0;if({read}(uart,&c,1,&n)||n!=1)return -1;rx_calls++;return c;}}
'''
    (app/'sdk_uart.c').write_text(prefix+body);assets['providers'].insert(1,str(app/'sdk_uart.c'))
    assets['selected_operations']+=list(selections)
    assets['uart_role']='ranked SDK calls behind RTOS UART device callbacks'
    write_json(app/'sdk-build-assets.json',assets)
    return assets
