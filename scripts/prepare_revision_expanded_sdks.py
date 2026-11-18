"""准备扩展SDK诊断池，记录完整输入范围、版本和与训练库族的关系。"""
from pathlib import Path
import gc
import shutil
import subprocess
from bspforge.common import read_json,write_json,file_sha256,utc_now
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.ir_store import IRStore


SPECS=[
 ('stellaris-driverlib','revision-stellaris','https://github.com/yuvadm/stellaris','TI Stellaris','qemu_cortex_m3','qemu-lm3s6965','new-sdk-source'),
 ('asf3-sam4s','revision-asf3','https://github.com/avrxml/asf','Microchip ASF3','sam4s_xplained','sam4s.repl','new-library-same-vendor-as-asf4'),
 ('nrf5-nrf52840','revision-nrf5-sdk','https://github.com/bestie-org/nRF5_SDK','Nordic nRF5 SDK 17.1.0','nrf52840dk/nrf52840','nrf52840.repl','shared-nrfx-family-with-training'),
]


def copytree(source,target):
    if not source.exists():raise FileNotFoundError(source)
    shutil.copytree(source,target,dirs_exist_ok=True)


def main():
    root=Path.cwd();base=root/'experiments/revision-r1-expanded';base.mkdir(parents=True,exist_ok=True);records=[]
    for name,repo_name,url,vendor,board,platform,relation in SPECS:
        repo=root.parent/'evaluation-sdks'/repo_name;target=root/'sdk'/name/'source';target.mkdir(parents=True,exist_ok=True)
        if name.startswith('stellaris'):
            for folder in ['driverlib','inc']:copytree(repo/folder,target/folder)
            scope='完整DriverLib与器件寄存器头文件；不包含示例、USB协议栈及预编译库'
        elif name.startswith('asf3'):
            device=repo/'sam/utils/cmsis/sam4s'
            copytree(device,target/'sam/utils/cmsis/sam4s')
            components={p.stem.removeprefix('component_') for p in (device/'include/component').glob('*.h')}
            modules=sorted(components|{'cpu','pio','pmc','tc','uart','usart','pdc','efc','wdt'})
            for module in modules:
                if (repo/'sam/drivers'/module).is_dir():copytree(repo/'sam/drivers'/module,target/'sam/drivers'/module)
            for folder in ['common/utils','common/services/clock/sam4s','sam/utils/header_files','sam/utils/preprocessor','thirdparty/CMSIS/Include']:
                copytree(repo/folder,target/folder)
            for file in [repo/'sam/utils/compiler.h',*(repo/'common/services/clock').glob('*.h')]:
                destination=target/file.relative_to(repo);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
            scope='SAM4S器件组件对应的全部ASF驱动、公共工具、目标时钟服务与CMSIS；按器件组件选源，非按预测结果裁剪'
        else:
            for folder in ['modules/nrfx/hal','modules/nrfx/drivers','modules/nrfx/helpers','modules/nrfx/soc','integration/nrfx','components/drivers_nrf','components/toolchain/cmsis/include']:
                copytree(repo/folder,target/folder)
            for file in (repo/'modules/nrfx').glob('*.h'):
                destination=target/'modules/nrfx'/file.name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
            for file in (repo/'modules/nrfx/mdk').glob('*'):
                if file.is_file() and (file.name in {'nrf.h','compiler_abstraction.h','nrf_peripherals.h','system_nrf52.c','system_nrf52.h','nrf_erratas.h','nrf52_erratas.h'} or '52840' in file.name or file.name.startswith('nrf52_name_change')):
                    destination=target/'modules/nrfx/mdk'/file.name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
            scope='nRF52840器件支持、全部nrfx外设HAL/驱动及旧版驱动兼容层；不包含无线协议栈或示例'
        for file in repo.iterdir():
            if file.is_file() and any(k in file.name.lower() for k in ['license','licence','readme']):shutil.copy2(file,target/file.name)
        revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        record={'name':name,'sdk_id':'revision-'+name,'vendor':vendor,'architecture':'arm-cortex-m3' if name.startswith('stellaris') else 'arm-cortex-m4',
            'source_path':str(target),'source_url':url,'revision':revision,'original_repository':str(repo),'input_scope':scope,
            'role':'external-diagnostic','training_included':False,'training_relation':relation,'independence_group':name,
            'board':board,'simulation_platform':platform,'operations':19,
            'source_sha256':{str(p.relative_to(target)):file_sha256(p) for p in target.rglob('*') if p.is_file() and p.suffix not in {'.a','.o','.lib'}}}
        dest=base/name;dest.mkdir(parents=True,exist_ok=True)
        previous=read_json(dest/'source-manifest.json') if (dest/'source-manifest.json').exists() else {}
        write_json(dest/'source-manifest.json',record);records.append(record)
        irfile=dest/'ir'/(record['sdk_id']+'.json')
        if not irfile.exists() or previous.get('source_sha256')!=record['source_sha256']:
            ir=SDKIngestor(frontend_mode='hybrid').ingest(target,record['sdk_id']);IRStore(irfile.parent).put(ir);write_json(irfile,ir)
            write_json(dest/'source-interface-inventory.json',[{k:e.get(k) for k in ['id','name','file','line','signature']} for e in ir['functions']])
            print(name,{'files':len(ir['files']),'functions':len(ir['functions']),'edges':len(ir['edges'])},flush=True)
            del ir;gc.collect()
    write_json(base/'manifest.json',{'created_at':utc_now(),'sdks':records,'model_retrained':False,
        'selection_policy':'预测前固定三来源；全部结果保留；最终纳入由作者决定并说明选择依据'})


if __name__=='__main__':main()
