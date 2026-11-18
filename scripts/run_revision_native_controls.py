#!/usr/bin/env python3
"""交叉编译并启动原生Zephyr对照；这些结果与SDK迁移结果严格分列。"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time
import base64
import socket
from bspforge.common import write_json,file_sha256
from run_sifive_zephyr_simulation import free_port,receive

def connect(port, process):
    end=time.monotonic()+120
    while time.monotonic()<end:
        if process.poll() is not None: raise RuntimeError(f'Renode exited {process.returncode}')
        try:return socket.create_connection(('127.0.0.1',port),timeout=1)
        except OSError:time.sleep(.2)
    raise TimeoutError(f'port {port}')

PROFILES={
 'sifive-fe310': {'board':'hifive1','platform':'sifive-fe310.repl','uart':'uart0','cpu':'cpu','gpio':'gpio0','out':0,'input':0,'connection':None},
 'opentitan': {'board':'opentitan_earlgrey','platform':'opentitan-earlgrey.repl','uart':'uart0','cpu':'cpu0','gpio':'gpio0','out':0,'input':1,'connection':'gpio: { 0 -> gpio@1 }','native_gpio':False},
 'litex': {'board':'litex_vexriscv','platform':'litex_vexriscv_zephyr.repl','uart':'uart','cpu':'cpu','gpio':'gpio_out','gpio_in':'gpio_in','out':0,'input':0,'connection':'gpio_out: { 0 -> gpio_in@0 }'},
 'asf4-samd21': {'board':'samd21_xpro','platform':'atsamd21j17d-aft.repl','uart':'usart2','cpu':'cpu0','gpio':'porta','out':2,'input':3,'connection':'gpio_a: { 2 -> gpio_a@3 }'},
 'ambiq-apollo4': {'board':'apollo4p_evb','platform':'ambiq-apollo4.repl','uart':'uart0','cpu':'cpu','gpio':'gpio0_31','out':12,'input':13,'connection':'gpio: { 12 -> gpio@13 }'},
}

def platform_lines(name, profile, platform, run):
    lines=[]
    if name=='sifive-fe310':
        adjusted=run/'platform.repl'
        adjusted.write_text(platform.read_text().replace('frequency: 62000000','frequency: 16000000'))
        platform=adjusted
    if name=='asf4-samd21':
        adjusted=run/'platform-iobus.repl';definition=platform.read_text()
        for port,address,alias in [('a','0x4100_4400','0x60000000'),('b','0x4100_4480','0x60000080')]:
            old=f'gpio_{port}: GPIOPort.SAMD21_GPIO @ sysbus {address}'
            assert definition.count(old)==1
            definition=definition.replace(old,f'gpio_{port}: GPIOPort.SAMD21_GPIO @ {{ sysbus {address}; sysbus {alias} }}')
        adjusted.write_text(definition);platform=adjusted
    if name=='litex':
        # Zephyr当前板描述与本SDK生成配置均使用CSR32，选择Renode自带的同宽度模型。
        adjusted=run/'platform-csr32.repl';definition=platform.read_text()
        assert definition.count('Timers.LiteX_Timer @')==1
        adjusted.write_text(definition.replace('Timers.LiteX_Timer @','Timers.LiteX_Timer_CSR32 @'))
        platform=adjusted
    lines.append(f'machine LoadPlatformDescription @{platform}')
    if profile['connection']:
        lines.append('machine LoadPlatformDescriptionFromString "'+profile['connection']+'"')
    if name=='sifive-fe310':
        lines+=['sysbus Tag <0x10008000 4> "PRCI_HFROSCCFG" 0xFFFFFFFF',
                'sysbus Tag <0x10008008 4> "PRCI_PLLCFG" 0xFFFFFFFF']
    if name=='opentitan':
        # 原生板描述假设boot ROM已使能计数器；24MHz/24得到设备树约定的1MHz。
        lines+=['sysbus WriteDoubleWord 0x4010010c 0x00010017',
                'sysbus WriteDoubleWord 0x40100100 1','sysbus WriteDoubleWord 0x40100004 1']
    return lines

def simulate(name, profile, elf, output, rounds):
    root=Path.cwd(); renode=root.parent/'tools/renode-1.17.0'; records=[]
    for i in range(rounds):
        run=output/'runs'/time.strftime('%Y%m%d-%H%M%S')/f'round-{i+1:02d}'; run.mkdir(parents=True)
        uart,monitor=free_port(),free_port()
        lines=['mach create "revision"',*platform_lines(name,profile,renode/'platforms/cpus'/profile['platform'],run),
          f'emulation CreateServerSocketTerminal {uart} "terminal" false',
          f'connector Connect sysbus.{profile["uart"]} terminal',
          f'sysbus.{profile["uart"]} CreateFileBackend @{run/"uart.log"} true',f'sysbus LoadELF @{elf}']
        if name in ['sifive-fe310','opentitan','litex']:
            symbol='__start' if profile.get('os')!='rtthread' or name!='opentitan' else '__start'
            lines.append(f'{profile["cpu"]} PC `sysbus GetSymbolAddress "{symbol}"`')
        script=run/'run.resc';script.write_text('\n'.join(lines)+'\n')
        cmd=[str(renode/'renode'),'--disable-gui','--plain','--port',str(monitor),'--execute',f'include @{script}']
        record={'round':i+1,'directory':str(run),'boot':False,'cases':[],'command':cmd}
        with (run/'renode.log').open('w') as log:
            proc=subprocess.Popen(cmd,cwd=renode,stdout=log,stderr=subprocess.STDOUT)
            try:
                with connect(uart,proc) as serial,connect(monitor,proc) as control:
                    receive(control,b'(revision)',2);control.sendall(b'start\r\n')
                    ready=receive(serial,b'READY ',20)+receive(serial,b'\n',3)
                    record['ready_base64']=base64.b64encode(ready).decode();record['boot']=b'READY ' in ready
                    if not record['boot']: raise RuntimeError('boot timeout '+repr(ready))
                    for case in (['G','T','U16','U255','S'] if profile.get('sdk') else ['G','T','U16','U255']):
                        payload=bytes((j*37+i)%256 for j in range(int(case[1:]))) if case.startswith('U') else b''
                        tx=b'U'+bytes([len(payload)])+payload if payload else case.encode()
                        if len(payload)>32:
                            serial.sendall(tx[:2])
                            for offset in range(2,len(tx),8):
                                serial.sendall(tx[offset:offset+8]);time.sleep(.005)
                        else:serial.sendall(tx)
                        marker=b'\nPASS U\n' if payload else b' '+case.encode()+b'\n'
                        rx=receive(serial,marker,10)
                        passed=b'PASS '+case[:1].encode()+b'\n' in rx
                        if payload: passed &= b'PAYLOAD '+payload+b'\nPASS U\n' in rx
                        record['cases'].append({'case':case,'passed':passed,'retries':0,'host_pacing':'8 bytes per 5 ms for payloads >32 bytes','tx_base64':base64.b64encode(tx).decode(),'rx_base64':base64.b64encode(rx).decode()})
                    if not all(c['passed'] for c in record['cases']):
                        control.sendall(b'pause\r\n');receive(control,b'(revision)',1)
                        snapshots=[]
                        for q in [f'{profile["cpu"]} PC','sysbus ReadDoubleWord 0xe0002808','sysbus ReadDoubleWord 0xe0002814','sysbus ReadDoubleWord 0xe0002818','sysbus ReadDoubleWord 0xe000281c'] if name=='litex' else []:
                            control.sendall(q.encode()+b'\r\n');snapshots.append({'command':q,'output':receive(control,b'(revision)',1).decode(errors='replace')})
                        record['debug_snapshots']=snapshots
            except Exception as e:record['error']=repr(e)
            finally:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        write_json(run/'result.json',record);records.append(record);print(name,record,flush=True)
        if not record['boot']:break
    result={'experiment_role':'SDK UART/GPIO bindings in native RTOS device frameworks' if profile.get('sdk_uart') else 'SDK GPIO binding with native OS services' if profile.get('sdk') else 'native-os-control-not-sdk-migration','firmware':str(elf),'firmware_sha256':file_sha256(elf),
            'boots':sum(r['boot'] for r in records),'rounds':len(records),'passed':sum(c['passed'] for r in records for c in r['cases']),
            'cases':sum(len(r['cases']) for r in records),'records':records}
    write_json(output/'results.json',result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--only',choices=list(PROFILES));p.add_argument('--rounds',type=int,default=1);p.add_argument('--skip-build',action='store_true');p.add_argument('--sdk',action='store_true');p.add_argument('--sdk-uart',action='store_true');p.add_argument('--negative-write',action='store_true');a=p.parse_args()
    if a.sdk_uart:a.sdk=True
    if a.negative_write and not a.sdk:p.error('--negative-write requires --sdk')
    root=Path.cwd()
    for name,profile in PROFILES.items():
        if a.only and name!=a.only:continue
        mode='zephyr-sdk-gpio' if a.sdk else 'zephyr-native-control'
        if a.sdk_uart:mode='zephyr-sdk-uart-gpio'
        if a.negative_write:mode+='-negative-write'
        out=root/'experiments/revision-r1-five-sdk'/name/mode;out.mkdir(parents=True,exist_ok=True)
        work=root/'workspace/revision-r1-five-sdk'/name/mode;app=work/'app'
        shutil.copytree(root/'ports/revision-simulation/zephyr',app,dirs_exist_ok=True)
        (app/'target.h').write_text(f'#define PROBE_NATIVE_GPIO {int(profile.get("native_gpio",True))}\n#define PROBE_GPIO_OUT {profile["gpio"]}\n#define PROBE_GPIO_IN {profile.get("gpio_in",profile["gpio"])}\n#define PROBE_OUTPUT {profile["out"]}\n#define PROBE_INPUT {profile["input"]}\n')
        if name=='litex':
            with (app/'prj.conf').open('a') as f:f.write('\nCONFIG_CLOCK_CONTROL=n\n')
        if a.sdk:
            from revision_sdk_binding import prepare
            try:assets=prepare(root,name,app,a.negative_write)
            except Exception as error:
                write_json(out/'preparation-error.json',{'error':repr(error)});print(name,repr(error),flush=True);continue
            if a.sdk_uart:
                from revision_sdk_uart_binding import augment
                try:assets=augment(root,name,app,assets)
                except Exception as error:
                    write_json(out/'preparation-error.json',{'error':repr(error)});print(name,repr(error),flush=True);continue
                from revision_profile_feedback import apply_assets
                assets=apply_assets(assets,work/'feedback-assets.json')
            with (app/'target.h').open('a') as f:f.write('\n#define BSP_USE_SDK 1\n')
            if a.sdk_uart:
                with (app/'target.h').open('a') as f:f.write('#define BSP_USE_SDK_UART 1\n')
            cmake=app/'sdk_build.cmake'
            cmake.write_text('target_sources(app PRIVATE\n'+''.join(' "'+s+'"\n' for s in assets['providers'])+')\n'
               +'target_include_directories(app PRIVATE\n'+''.join(' "'+s+'"\n' for s in assets['includes'])+')\n'
               +'target_compile_definitions(app PRIVATE '+ ' '.join(assets['defines'])+')\n'
               +(''.join(f'set_source_files_properties("{provider}" PROPERTIES COMPILE_OPTIONS "-include;{assets["namespace_header"]}")\n' for provider in assets['providers'][1:]) if assets['namespace_header'] else ''))
            with cmake.open('a') as f:f.write('target_compile_definitions(app PRIVATE asm=__asm__)\n')
            with (app/'CMakeLists.txt').open('a') as f:f.write('\ninclude(sdk_build.cmake)\n')
        env=dict(os.environ);env['PATH']=str(Path(sys.executable).parent)+':'+env['PATH']
        tool='arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-' if name in ['asf4-samd21','ambiq-apollo4'] else 'xpack-riscv-none-elf-gcc-14.2.0-3/bin/riscv-none-elf-'
        env.update(ZEPHYR_BASE=str(root.parent/'zephyr'),ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',CROSS_COMPILE=str(root/'toolchains'/tool),CMAKE_BUILD_PARALLEL_LEVEL='4')
        cmd=['west','build','-b',profile['board'],'-d',str(work/'build'),str(app),'--',f'-DUSER_CACHE_DIR={work/"cache"}']
        if not a.skip_build:
            for filename in ['build.log','build-result.json']:
                if (out/filename).exists():shutil.copy2(out/filename,out/(f'previous-{time.time_ns()}-'+filename))
            start=time.monotonic();proc=subprocess.run(cmd,cwd=root.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            (out/'build.log').write_text(proc.stdout);write_json(out/'build-result.json',{'command':cmd,'returncode':proc.returncode,'seconds':time.monotonic()-start})
            print(name,proc.returncode,proc.stdout[-2200:],flush=True)
            if proc.returncode:continue
        simulate(name,{**profile,'sdk':a.sdk,'sdk_uart':a.sdk_uart},work/'build/zephyr/zephyr.elf',out,a.rounds)

if __name__=='__main__':main()
