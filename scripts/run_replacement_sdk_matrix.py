"""生成双OS原生设备绑定并交叉编译，在Renode逐项记录事前确定的能力范围。"""
from pathlib import Path
import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import time
from bspforge.common import read_json,write_json,file_sha256
from bspforge.build_diagnoser import BuildDiagnoser
from replacement_sdk_binding import prepare
from run_revision_native_controls import connect
from run_sifive_zephyr_simulation import free_port,receive


def build(root,name,os_name,out,work,app,assets):
    previous=[p for p in out.iterdir() if p.is_file() and (p.name.startswith('build-attempt-') or p.name in {'build-result.json','compiler-feedback.json'})]
    if previous:
        archive=out/'build-history'/str(time.time_ns());archive.mkdir(parents=True)
        for p in previous:shutil.copy2(p,archive/p.name)
    source=Path(assets['source_root']);builddir=work/'build';builddir.mkdir(parents=True,exist_ok=True)
    ir=read_json(out.parent/'ir'/('revision-'+name+'.json'))
    providers=list(assets['providers']);includes=list(assets['includes']);feedback=[]
    for attempt in range(1,4):
        logpath=out/f'build-attempt-{attempt:02d}.log';start=time.monotonic()
        if os_name=='zephyr':
            binary=root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-'
            commands=[];objects=[]
            for index,provider in enumerate(providers):
                obj=builddir/f'sdk-{index:02d}.o';objects.append(str(obj))
                commands.append([str(binary)+'gcc','-mthumb','-mcpu='+assets.get('cpu','cortex-m4'),'-mfloat-abi=soft',
                    '-Os','-g','-std=gnu11','-ffunction-sections','-fdata-sections',
                    '-include',assets['namespace_header'],*['-D'+d for d in assets['defines']],
                    *[v for inc in [str(app),*includes] for v in ['-I',inc]],'-c',provider,'-o',str(obj)])
            archive=builddir/'libsdk_input.a'
            commands.append([str(binary)+'ar','rcs',str(archive),*objects])
            cmake=['cmake_minimum_required(VERSION 3.20.0)','find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})','project(replacement_sdk)',
                'target_sources(app PRIVATE zephyr.c validation.c)',
                'target_include_directories(app PRIVATE .)',
                'target_link_libraries(app PRIVATE "'+str(archive)+'")',
                'zephyr_link_libraries(-Wl,--defsym,__isr_vector=_vector_start)']
            if assets.get('writable_vector_section'):
                (app/'sdk_vectors.ld').write_text('SECTION_DATA_PROLOGUE(sdk_input_vectors,(NOLOAD),)\n{ . = ALIGN(1024); KEEP(*(vtable)) } GROUP_DATA_LINK_IN(RAMABLE_REGION, ROMABLE_REGION)\n')
                cmake.append('zephyr_linker_sources(RAM_SECTIONS sdk_vectors.ld)')
            (app/'CMakeLists.txt').write_text('\n'.join(cmake)+'\n')
            (app/'prj.conf').write_text('CONFIG_CONSOLE=n\nCONFIG_UART_CONSOLE=n\nCONFIG_PRINTK=n\nCONFIG_SERIAL=y\nCONFIG_GPIO=y\nCONFIG_COUNTER=y\nCONFIG_CLOCK_CONTROL=y\nCONFIG_MAIN_STACK_SIZE=6144\nCONFIG_ISR_STACK_SIZE=3072\nCONFIG_DYNAMIC_INTERRUPTS=y\nCONFIG_SRAM_VECTOR_TABLE=y\nCONFIG_ZERO_LATENCY_IRQS=y\nCONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC='+str(assets.get('os_tick_hz',assets['cpu_hz']))+'\n')
            # A generated device must not share its peripheral with a board's default driver.
            exclusive=assets.get('zephyr_exclusive_nodes',[])
            if exclusive:
                if any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',node) for node in exclusive):
                    raise ValueError('Invalid exclusive devicetree node label')
                (app/'app.overlay').write_text(''.join('&'+node+' { status = "disabled"; };\n' for node in exclusive))
            env=dict(os.environ,PATH=str(Path(sys.executable).parent)+':'+os.environ['PATH'],
                 ZEPHYR_BASE=str(root.parent/'zephyr'),ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',
                 CROSS_COMPILE=str(root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-'),CMAKE_BUILD_PARALLEL_LEVEL='4')
            commands.append(['west','build','-b',assets['board'],'-d',str(builddir),str(app),'--',f'-DUSER_CACHE_DIR={work/"cache"}',
                             '-DDTC_OVERLAY_FILE='+str(app/'app.overlay') if exclusive else '-DDTC_OVERLAY_FILE='])
            elf=builddir/'zephyr/zephyr.elf'
        else:
            rtt=(root/'third_party/rt-thread').resolve();port=rtt/'libcpu/arm'/assets.get('cpu','cortex-m4')
            includes_all=[app,rtt/'include',port,rtt/'components/drivers/include',*map(Path,includes)]
            sourcefiles=[rtt/'src'/f for f in ['clock.c','cpu_up.c','defunct.c','idle.c','ipc.c','irq.c','kservice.c','object.c','scheduler_comm.c','scheduler_up.c','thread.c','timer.c','mem.c']]
            sourcefiles += [rtt/'src/klibc'/f for f in ['kerrno.c','kstdio.c','kstring.c','rt_vsnprintf_tiny.c']]
            sourcefiles += [rtt/'components/drivers'/f for f in ['core/device.c','pin/dev_pin.c','serial/dev_serial.c','ipc/completion_up.c','ipc/completion_comm.c','hwtimer/hwtimer.c']]
            sourcefiles += [port/'cpuport.c',port/'context_gcc.S',app/'rtthread.c',app/'validation.c',app/'startup-arm.S',*map(Path,providers)]
            gcc=root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc'
            flags=['-mthumb','-mcpu='+assets.get('cpu','cortex-m4'),'-mfloat-abi=soft','-Os','-g','-std=gnu11','-ffunction-sections','-fdata-sections','-D__RTTHREAD__','-D__RT_KERNEL_SOURCE__']
            commands=[];objects=[]
            for index,path in enumerate(sourcefiles):
                obj=builddir/f'{index:03d}-{path.stem}.o';objects.append(obj)
                cmd=[str(gcc),*flags,*['-D'+d for d in assets['defines']],*[v for inc in includes_all for v in ['-I',str(inc)]],'-c',str(path),'-o',str(obj)]
                if str(path) in providers:cmd[1:1]=['-include',assets['namespace_header'],'-iquote',str(source/'Libraries/CMSIS/Include')]
                commands.append(cmd)
            elf=builddir/'firmware.elf'
            commands.append([str(gcc),*flags,'-nostartfiles','--specs=nosys.specs','-Wl,--gc-sections','-Wl,--defsym,__isr_vector=vectors','-Wl,-Map='+str(builddir/'firmware.map'),'-T',str(app/'link.ld'),*map(str,objects),'-lm','-o',str(elf)])
            env=dict(os.environ)
        returncode=0
        with logpath.open('w') as log:
            for command in commands:
                log.write('$ '+' '.join(command)+'\n');log.flush()
                process=subprocess.run(command,cwd=root.parent,env=env,stdout=log,stderr=subprocess.STDOUT)
                if process.returncode:returncode=process.returncode;break
        text=logpath.read_text();diagnoser=BuildDiagnoser();diagnosis=diagnoser.diagnose(text.replace('bsp_input_',''),returncode)
        closure={'selected_files':[{'path':str(Path(f).relative_to(source))} for f in providers if Path(f).is_relative_to(source)],'target_context':{'architecture':'arm'}}
        proposal=diagnoser.propose_repairs(ir,diagnosis,closure);applied=[]
        if returncode:
            for repair in proposal['repairs']:
                path=(source/repair['path']).resolve()
                if not path.is_relative_to(source):continue
                target=providers if repair['action']=='add-source' else includes if repair['action']=='add-include-dir' else None
                if target is not None and str(path) not in target:target.append(str(path));applied.append(repair)
        row={'attempt':attempt,'returncode':returncode,'seconds':time.monotonic()-start,'diagnosis':diagnosis,'applied':applied,'proposal':proposal,'log':str(logpath)}
        feedback.append(row);write_json(out/'compiler-feedback.json',{'attempts':feedback,'semantic_predictions_changed':False,'reference_read':False})
        write_json(out/'build-result.json',{'returncode':returncode,'commands':commands,'attempts':attempt,'elf':str(elf),'providers':providers,'includes':includes})
        print(name,os_name,'build',attempt,returncode,text[-1600:],flush=True)
        if not returncode:return elf
        if not applied:return None
    return None


def simulate(root,name,os_name,elf,out,assets,rounds):
    original_elf=Path(elf).resolve();digest=file_sha256(original_elf)
    pin=out/'firmware-pinned'/(digest+'.elf');pin.parent.mkdir(parents=True,exist_ok=True)
    if not pin.exists():shutil.copy2(original_elf,pin)
    assert file_sha256(pin)==digest
    elf=pin
    renode=root.parent/'tools/renode-1.17.0';records=[]
    scope=read_json(out.parent.parent/'operation-scope.json')['rows']
    from bspforge.operation_ranking import OPERATION_DESCRIPTIONS
    operations=list(OPERATION_DESCRIPTIONS);eligible={operations.index(r['operation']) for r in scope if r['sdk']==name and r['eligible']}
    for i in range(rounds):
        folder=out/'runs'/str(time.time_ns())/f'round-{i+1:02d}';folder.mkdir(parents=True)
        terminal,monitor=free_port(),free_port()
        qemu=assets.get('simulation_kind')=='qemu';gpio_wire=None
        if qemu:
            qtest=free_port()
            command=['qemu-system-arm','-M','lm3s6965evb','-display','none','-S','-kernel',str(elf),
                '-serial',f'tcp:127.0.0.1:{terminal},server=on,wait=off',
                '-monitor',f'tcp:127.0.0.1:{monitor},server=on,wait=off',
                '-qtest',f'tcp:127.0.0.1:{qtest},server=on,wait=off,nodelay=on','-qtest-log',str(folder/'qtest.log')]
        else:
            definition=(renode/'platforms/cpus'/assets['platform']).read_text()
            if assets.get('omit_remote_svd_metadata'):
                definition=re.sub(r'^\s*ApplySVD @https?://[^\n]+\n','\n',definition,flags=re.M)
            if 'uart_easy_dma' in assets:
                uart=assets['uart_name'];value=str(assets['uart_easy_dma']).lower()
                definition,count=re.subn(r'(?m)^('+re.escape(uart)+r':[^\n]+\n\s+easyDMA:)\s*(?:true|false)',r'\g<1> '+value,definition)
                if count!=1:raise ValueError('目标UART模型模式配置不唯一')
            definition=re.sub(r'systickFrequency:\s*\d+','systickFrequency: '+str(assets['cpu_hz']),definition)
            platform=folder/'platform.repl';platform.write_text(definition)
            gpio=assets.get('gpio_connection','gpio0: { 0 -> gpio0@1 }' if name.startswith('max') else 'gpioPortD: { 12 -> gpioPortD@13 }')
            uart_name=assets.get('uart_name','uart0' if name.startswith('max') else 'usart2')
            flash=assets.get('flash_address',0x10000000 if name.startswith('max') else 0x08000000)
            lines=['mach create "replacement"',f'machine LoadPlatformDescription @{platform}',
                'machine LoadPlatformDescriptionFromString "'+gpio+'"',f'cpu VectorTableOffset {flash:#x}',
                f'emulation CreateServerSocketTerminal {terminal} "terminal" false',f'connector Connect sysbus.{uart_name} terminal',
                f'sysbus.{uart_name} CreateFileBackend @{folder/"uart.log"} true',f'sysbus LoadELF @{elf}']
            script=folder/'run.resc';script.write_text('\n'.join(lines)+'\n')
            command=[str(renode/'renode'),'--disable-gui','--plain','--port',str(monitor),'--execute',f'include @{script}']
        row={'round':i+1,'boot':False,'records':[],'directory':str(folder),'command':command}
        with (folder/'renode.log').open('w') as log:
            process=subprocess.Popen(command,cwd=renode,stdout=log,stderr=subprocess.STDOUT)
            try:
                with connect(terminal,process) as serial,connect(monitor,process) as control:
                    if qemu:
                        from qemu_gpio_wire import GPIOWire
                        gpio_wire=GPIOWire(connect(qtest,process)).start()
                    receive(control,b'(qemu)' if qemu else b'(replacement)',2);control.sendall(b'cont\r\n' if qemu else b'start\r\n')
                    ready=receive(serial,b'READY ',25)+receive(serial,b'\n',2);row['ready_base64']=base64.b64encode(ready).decode();row['boot']=b'READY ' in ready
                    if not row['boot']:
                        snapshots=[]
                        if not qemu:
                            for command in ['pause','cpu PC','cpu SP','cpu LR','sysbus ReadDoubleWord 0x40002500','sysbus ReadDoubleWord 0x4000211C','sysbus ReadDoubleWord 0x40002108']:
                                control.sendall((command+'\r\n').encode())
                                snapshots.append({'command':command,'response':receive(control,b'(replacement)',2).decode(errors='replace')})
                        row['boot_diagnostics']=snapshots
                        row['boot_diagnostics_tail']=receive(control,b'__END_OF_DIAGNOSTICS__',3).decode(errors='replace') if not qemu else ''
                        raise RuntimeError('启动未收到READY')
                    wire=[];body=b'';tail=b''
                    if not assets.get('uart_first'):
                        serial.sendall(b'B');body=receive(serial,b'DONE B\n',15);wire.append({'tx':'Qg==','rx':base64.b64encode(body).decode()})
                        serial.sendall(b'S');tail=receive(serial,b'DONE S\n',5);wire.append({'tx':'Uw==','rx':base64.b64encode(tail).decode()})
                    payloads=[]
                    for n in [16,255]:
                        payload=bytes((j*37+i)%256 for j in range(n));tx=b'U'+bytes([n])+payload
                        for offset in range(len(tx)):serial.sendall(tx[offset:offset+1]);time.sleep(.004)
                        rx=receive(serial,b'\nPASS U\n',8);passed=b'PAYLOAD '+payload+b'\nPASS U\n' in rx
                        payloads.append({'length':n,'passed':passed,'tx_base64':base64.b64encode(tx).decode(),'rx_base64':base64.b64encode(rx).decode(),'retries':0})
                    if assets.get('uart_first'):
                        serial.sendall(b'S');tail=receive(serial,b'DONE S\n',5);wire.append({'tx':'Uw==','rx':base64.b64encode(tail).decode()})
                        for group in [g.encode() for g in assets.get('validation_groups',['I','G','T','C'])]:
                            serial.sendall(group);data=receive(serial,b'DONE B\n',15);body+=data
                            wire.append({'tx':base64.b64encode(group).decode(),'rx':base64.b64encode(data).decode()})
                    parsed={int(m[0]):m for m in re.findall(rb'OP (\d+) (PASS|FAIL) before=(\d+) after=(\d+) calls=(\d+)',body+tail)}
                    for index in sorted(eligible):
                        m=parsed.get(index);passed=bool(m and m[1]==b'PASS' and int(m[4])>0)
                        if index in [9,10]:passed=passed and all(p['passed'] for p in payloads)
                        row['records'].append({'operation':operations[index],'passed':passed,'status':'pass' if passed else 'fail' if m else 'unverified',
                            'operation_owner':assets.get('operation_owners',{}).get(operations[index],'selected-sdk-binding'),
                            'before':int(m[2]) if m else None,'after':int(m[3]) if m else None,'binding_calls':int(m[4]) if m else 0,'retries':0})
                    row['wire']=wire;row['uart_payloads']=payloads
                    if len(parsed)<len(eligible) and not qemu:
                        diagnostics=[]
                        for command in ['pause','cpu PC','cpu LR','cpu GetRegister 0','cpu GetRegister 1',
                                        'sysbus ReadDoubleWord `sysbus GetSymbolAddress "bsp_fatal_reason"`',
                                        'sysbus ReadDoubleWord `sysbus GetSymbolAddress "bsp_fatal_ipsr"`',
                                        'sysbus ReadDoubleWord 0xE000ED08','sysbus ReadDoubleWord 0xE000ED28','sysbus ReadDoubleWord 0xE000ED2C','sysbus ReadDoubleWord 0x20000094','sysbus ReadDoubleWord 0xE000E100','sysbus ReadDoubleWord 0xE000E200']:
                            control.sendall((command+'\r\n').encode())
                            diagnostics.append({'command':command,'response':receive(control,b'(replacement)',2).decode(errors='replace')})
                        row['incomplete_diagnostics']=diagnostics
                        row['incomplete_diagnostics_tail']=receive(control,b'__END_OF_DIAGNOSTICS__',3).decode(errors='replace')
            except Exception as error:row['error']=repr(error)
            finally:
                if gpio_wire:
                    gpio_wire.close();write_json(folder/'gpio-wire.json',{'error':gpio_wire.error,'events':gpio_wire.records})
                process.terminate()
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        write_json(folder/'result.json',row);records.append(row)
        print(name,os_name,'round',i+1,'boot',row['boot'],'passed',sum(x['passed'] for x in row['records']),'of',len(eligible),row.get('error',''),flush=True)
        if not row['boot']:break
    result={'sdk':name,'os':os_name,'firmware':str(elf),'firmware_sha256':file_sha256(elf),'build_firmware_source':str(original_elf),'eligible_operations':len(eligible),
        'rounds':len(records),'requested_rounds':rounds,'boots':sum(r['boot'] for r in records),
        'operation_checks':sum(len(r['records']) for r in records),'scheduled_operation_checks':len(eligible)*rounds,
        'passed':sum(x['passed'] for r in records for x in r['records']),'records':records,'command_retries':0,
        'scope_file':str(out.parent.parent/'operation-scope.json'),
        'operation_owners':assets.get('operation_owners',{}),
        'uart_transmission_policy':{'bytes_per_chunk':1,'host_pause_seconds':0.004,'retries':0},
        'protocol_order':'U16,U255,S,I,G,T,C' if assets.get('uart_first') else 'B,S,U16,U255'}
    write_json(out/'results.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--only');p.add_argument('--os',choices=['rtthread','zephyr'],required=True);p.add_argument('--rounds',type=int,default=1);p.add_argument('--skip-build',action='store_true');p.add_argument('--experiment-root',type=Path,default=Path('experiments/revision-r1-replacements'));p.add_argument('--contract-guards',action='store_true');a=p.parse_args()
    root=Path.cwd();base=a.experiment_root.resolve();templates=root/'ports/replacement-simulation'
    prepare_sdk=prepare
    if base.name=='revision-r1-expanded':
        from expanded_sdk_binding import prepare as prepare_sdk
    failed=False
    for sdk in read_json(base/'manifest.json')['sdks']:
        name=sdk['name']
        if a.only and name!=a.only:continue
        out=base/name/a.os;out.mkdir(parents=True,exist_ok=True);work=root/'workspace'/base.name/name/a.os;app=work/'app';app.mkdir(parents=True,exist_ok=True)
        for source in templates.iterdir():
            if source.is_file():shutil.copy2(source,app/source.name)
        try:assets=prepare_sdk(root,name,app,contract_guard=a.contract_guards)
        except Exception as error:write_json(out/'binding-diagnostic.json',{'error':repr(error)});print(name,repr(error),flush=True);failed=True;continue
        scope=read_json(base/'operation-scope.json')['rows'];operations=list(__import__('bspforge.operation_ranking',fromlist=['OPERATION_DESCRIPTIONS']).OPERATION_DESCRIPTIONS)
        mask=sum(1<<operations.index(r['operation']) for r in scope if r['sdk']==name and r['eligible'])
        selections=read_json(out.parent/'typed-selection.json')['selections']
        has_period=bool(selections.get('timer.set_interval',{}).get('candidate'))
        (app/'target.h').write_text(f'#define ELIGIBLE_MASK {mask}u\n#define HAS_TIMER_PERIOD_BINDING {int(has_period)}\n#define HAS_TIMER_ENABLE_PROBE {int(assets.get("has_timer_enable_probe",False))}\n#define HAS_SDK_VECTOR {int(assets.get("has_sdk_vector",name.startswith("max")))}\n#define EXPECTED_PRIORITY_GROUP {assets.get("priority_group",0 if name.startswith("max") else 3)}\n#define GPIO_TEST_DELAY_MS {10 if assets.get("simulation_kind")=="qemu" else 1}\n'+''.join(f'#define {macro} {assets[key]}\n' for macro,key in [('GPIO_IRQ','gpio_irq'),('TIMER_IRQ','timer_irq'),('PROBE_IRQ','probe_irq'),('CPU_HZ','cpu_hz'),('TIMER_FREQUENCY','timer_frequency')]))
        if a.os=='rtthread':
            shutil.copy2(root/'ports/revision-simulation/rtthread/startup-arm.S',app/'startup-arm.S')
            config=(root/'ports/revision-simulation/rtthread/rtconfig.h').read_text()+'\n#define RT_USING_HEAP\n#define RT_USING_SMALL_MEM\n#define RT_USING_SMALL_MEM_AS_HEAP\n#define RT_USING_SERIAL\n#define RT_USING_HWTIMER\n'
            (app/'rtconfig.h').write_text(config)
            flash=assets.get('flash_address',0x10000000 if name.startswith('max') else 0x08000000);ram=0x20000000
            (app/'link.ld').write_text(f'''ENTRY(Reset_Handler)
MEMORY {{ ROM (rx) : ORIGIN = {flash:#x}, LENGTH = 512K
RAM (rwx) : ORIGIN = {ram:#x}, LENGTH = {assets.get('ram_size',131072)} }}
SECTIONS {{ .text : {{ KEEP(*(.isr_vector)) *(.text*) *(.rodata*) . = ALIGN(8); }} > ROM
_sidata = LOADADDR(.data); .data : {{ _sdata = .; *(.data*) . = ALIGN(8); _edata = .; }} > RAM AT>ROM
.bss (NOLOAD) : {{ _sbss = .; *(.bss*) *(COMMON) . = ALIGN(8); _ebss = .; end = .; _end = .; }} > RAM
_estack = ORIGIN(RAM)+LENGTH(RAM); }}
''')
        elf=work/'build'/('zephyr/zephyr.elf' if a.os=='zephyr' else 'firmware.elf')
        if not a.skip_build:elf=build(root,name,a.os,out,work,app,assets)
        if elf:
            if a.os=='zephyr':
                config=(work/'build/zephyr/.config').read_text()
                if 'CONFIG_ARM_MPU=y' in config or not assets.get('has_sdk_vector',name.startswith('max')):
                    assets['operation_owners']={'interrupt.register':'zephyr-native-vector-framework'}
            write_json(app/'sdk-build-assets.json',assets)
            result=simulate(root,name,a.os,elf,out,assets,a.rounds)
            failed=failed or result['boots']!=a.rounds or result['passed']!=result['operation_checks']
        else:failed=True
    return int(failed)

if __name__=='__main__':raise SystemExit(main())
