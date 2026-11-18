"""补充平台的类型化GPIO绑定，所有入口均从冻结候选顺序选择。

平台配置给出外设实例、ABI和初始化资产，不读取AI参考集，也不回退参考符号。
这是一层显式新增的实验适配配置，不改动已冻结的排序器/原三板后端。
"""
from pathlib import Path
import re
import subprocess
import sys
from bspforge.common import read_json,write_json,file_sha256
from run_sifive_zephyr_simulation import typed_parameters

CONTRACTS={
 'sifive-fe310': {'gpio.write':['struct metal_gpio*','int','int'], 'gpio.read':['struct metal_gpio*','int']},
 'opentitan': {'gpio.write':['const dif_gpio_t*','dif_gpio_pin_t','bool'], 'gpio.read':['const dif_gpio_t*','dif_gpio_pin_t','bool*']},
 'litex': {'gpio.write':['uint32_t'], 'gpio.read':[]},
 'asf4-samd21': {'gpio.write':['const uint8_t','const bool'], 'gpio.read':['const uint8_t']},
 'ambiq-apollo4': {'gpio.write':['uint32_t','am_hal_gpio_write_type_e'], 'gpio.read':['uint32_t','am_hal_gpio_read_type_e','uint32_t*']},
}
def select(root,name):
    dest=root/'experiments/revision-r1-five-sdk'/name
    sdk=next(s for s in read_json(dest.parent/'manifest.json')['sdks'] if s['name']==name)
    ir=read_json(dest/'ir'/(sdk['sdk_id']+'.json'));entities={e['id']:e for e in ir['functions']}
    bundle=read_json(dest/'frozen-runtime-bundle.json');result={}
    for op,params in CONTRACTS[name].items():
        rejected=[]
        for c in bundle['operations'][op]['candidates']:
            e=entities[c['entity_id']];actual=typed_parameters(e.get('signature',''))
            public=not('/dsp/' in e['file'] or e['file'].startswith(('testing/','runtime/')))
            if name=='sifive-fe310':public=e['file'].startswith('metal/') and '/drivers/' not in e['file']
            if name=='asf4-samd21':public=e['file']=='hal/include/hal_gpio.h'
            if name=='litex':
                # 不同GPIO实例的同型CSR入口不能互换；实例来自平台内存映射。
                public=e['file']=='include/generated/csr.h' and e['name'].startswith('gpio_out_' if op.endswith('write') else 'gpio_in_')
            if actual==params and public:
                result[op]={'candidate':c,'entity':e,'abi':params,'rejected':rejected};break
            rejected.append({'symbol':c['symbol'],'rank':c['rank'],'actual_abi':actual,'reason':'instance-or-public-scope' if not public else 'abi'})
        else:raise ValueError(f'{name} {op}: no compatible candidate; no reference fallback')
    write_json(dest/'typed-gpio-selection.json',{'policy':'first ranked candidate satisfying ABI, public scope and target instance',
       'reads_reference_labels':False,'ranker_changed':False,'new_sdk_profile':True,
       'selections':result,'bundle_sha256':file_sha256(dest/'frozen-runtime-bundle.json')})
    return sdk,result

def prepare(root,name,app,suppress_write=False):
    sdk,selected=select(root,name);source=Path(sdk['source_path']);includes=[app];providers=[];defines=[]
    write=selected['gpio.write']['candidate']['symbol'];read=selected['gpio.read']['candidate']['symbol']
    common='''#include <stdint.h>\n#include <stdbool.h>\nstatic uint32_t writes, reads;\nuint32_t sdk_gpio_write_calls(void){return writes;}\nuint32_t sdk_gpio_read_calls(void){return reads;}\n'''
    if name=='sifive-fe310':
        machine=app/'metal/machine';machine.mkdir(parents=True,exist_ok=True)
        import shutil
        for src,dest in [('metal.h',machine.parent/'machine.h'),('metal-inline.h',machine/'inline.h'),('metal-platform.h',machine/'platform.h')]:shutil.copy2(source/'board/sifive-hifive1'/src,dest)
        includes += [source]
        names=['inline','fixed-clock','fixed-factor-clock','sifive_gpio0','sifive_uart0','sifive_fe310-g000_hfrosc','sifive_fe310-g000_hfxosc','sifive_fe310-g000_lfrosc','sifive_fe310-g000_pll','sifive_fe310-g000_prci','riscv_plic0','riscv_clint0','riscv_cpu']
        providers += [source/'src/drivers'/(n+'.c') for n in names]
        providers += [source/'src'/n for n in ['gpio.c','uart.c','clock.c','interrupt.c','cpu.c','shutdown.c','trap.S','vector.S']]
        body=f'''#include <metal/gpio.h>
static struct metal_gpio *gpio;
void sdk_gpio_mode(int out){{(void)out;gpio=metal_gpio_get_device(0);metal_gpio_disable_pinmux(gpio,0);metal_gpio_enable_output(gpio,0);metal_gpio_enable_input(gpio,0);}}
void sdk_gpio_write(int v){{writes++;{write}(gpio,0,v);}}
int sdk_gpio_read(void){{reads++;return {read}(gpio,0)!=0;}}
'''
    elif name=='litex':
        includes += [source/'include',source/'cpu/vexriscv']
        defines += ['CONFIG_CPU_NOP="nop"']
        body=f'''#include <generated/csr.h>
void sdk_gpio_mode(int out){{(void)out;}}
void sdk_gpio_write(int v){{writes++;{write}(v?1:0);}}
int sdk_gpio_read(void){{reads++;return {read}()&1;}}
'''
    elif name=='asf4-samd21':
        includes += [source/'include',source/'CMSIS/Include',source/'hal/include',source/'hal/utils/include',source/'hri',source/'hpl/port',source/'config']
        defines+=['__SAMD21J18A__']
        providers += [source/'hal/src/hal_atomic.c']
        body=f'''#include <hal_gpio.h>
void sdk_gpio_mode(int out){{(void)out;gpio_set_pin_direction(2,GPIO_DIRECTION_OUT);gpio_set_pin_direction(3,GPIO_DIRECTION_IN);}}
void sdk_gpio_write(int v){{writes++;{write}(2,v!=0);}}
int sdk_gpio_read(void){{reads++;return {read}(3)!=0;}}
'''
    elif name=='ambiq-apollo4':
        import shutil
        overlay=app/'input-sdk/mcu/apollo4p'
        shutil.copytree(source,overlay,dirs_exist_ok=True)
        version=subprocess.check_output(['git','-C',str(root.parent/'evaluation-sdks/revision-ambiq-apollo4'),'show','HEAD:mcu/am_sdk_version.h'])
        (overlay.parent/'am_sdk_version.h').write_bytes(version)
        includes += [overlay]
        includes += [source,root.parent/'evaluation-sdks/revision-ambiq-apollo4/CMSIS/AmbiqMicro/Include',root.parent/'modules/hal/cmsis/CMSIS/Core/Include']
        providers += [source/'hal/am_hal_gpio.c',source/'hal/mcu/am_hal_interrupt.c']
        # 原生Zephyr HAL与输入SDK同名时，给输入翻译单元独立命名空间，确保调用证据不被原HAL替代。
        text=(source/'hal/am_hal_gpio.c').read_text()
        names=set(re.findall(r'\bam_hal_gpio_\w+\b',text))
        macro_names=set(re.findall(r'^\s*#define\s+(am_hal_gpio_\w+)',(source/'hal/am_hal_gpio.h').read_text(),re.MULTILINE))
        names-=macro_names
        names.update(re.findall(r'\bam_hal_interrupt_master_\w+\b',(source/'hal/mcu/am_hal_interrupt.c').read_text()))
        namespace=app/'sdk_namespace.h';namespace.write_text('\n'.join('#define '+n+' bsp_input_'+n for n in sorted(names))+'\n')
        body=f'''#include "sdk_namespace.h"
#include <am_mcu_apollo.h>
void sdk_gpio_mode(int out){{(void)out;am_hal_gpio_pinconfig(12,am_hal_gpio_pincfg_output);am_hal_gpio_pinconfig(13,am_hal_gpio_pincfg_input);}}
void sdk_gpio_write(int v){{writes++;{write}(12,v?AM_HAL_GPIO_OUTPUT_SET:AM_HAL_GPIO_OUTPUT_CLEAR);}}
int sdk_gpio_read(void){{reads++;uint32_t v=0;{read}(13,AM_HAL_GPIO_INPUT_READ,&v);return v!=0;}}
'''
    else:
        repo=root.parent/'evaluation-sdks/revision-opentitan'
        generated=app/'generated';generated.mkdir(parents=True,exist_ok=True)
        regpython=root.parent/'tools/opentitan-reggen-venv/bin/python'
        cmd=[str(regpython) if regpython.exists() else sys.executable,str(repo/'util/regtool.py'),'-D','-o',str(generated/'gpio_regs.h'),str(repo/'hw/ip/gpio/data/gpio.hjson')]
        proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (app/'register-generation.log').write_text(proc.stdout)
        if proc.returncode:raise RuntimeError('OpenTitan official register generation: '+proc.stdout[-2000:])
        layout=app/'sdk-layout/sw/device';layout.mkdir(parents=True,exist_ok=True)
        if not (layout/'lib').exists():(layout/'lib').symlink_to(source,target_is_directory=True)
        includes += [app/'sdk-layout',generated]
        providers += [source/'dif/dif_gpio.c',source/'base/mmio.c']
        body=f'''#include "sw/device/lib/dif/dif_gpio.h"
static const dif_gpio_t gpio={{.base_addr={{.base=(volatile void*)0x40040000}}}};
void sdk_gpio_mode(int out){{(void)out;dif_gpio_output_set_enabled(&gpio,0,kDifToggleEnabled);dif_gpio_output_set_enabled(&gpio,1,kDifToggleDisabled);}}
void sdk_gpio_write(int v){{writes++;(void){write}(&gpio,0,v!=0);}}
int sdk_gpio_read(void){{reads++;bool v=false;(void){read}(&gpio,1,&v);return v;}}
'''
    if suppress_write:body=body.replace('writes++;','return;writes++;')
    (app/'sdk_gpio.c').write_text(common+body)
    providers.insert(0,app/'sdk_gpio.c')
    result={'source':str(source),'providers':list(map(str,providers)),'includes':list(map(str,includes)),'defines':defines,
       'namespace_header':str(app/'sdk_namespace.h') if name=='ambiq-apollo4' else None,
       'selected_operations':['gpio.write','gpio.read'],'profile_setup_is_ranked':False,
       'os_owned':['clock/startup','interrupt controller/dispatch','system timer'],
       'uart_role':'native OS/platform console control; not ranking-selected SDK UART validation',
       'negative_write_control':suppress_write}
    write_json(app/'sdk-build-assets.json',result)
    return result
