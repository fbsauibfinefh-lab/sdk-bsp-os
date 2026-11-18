"""按目标芯片的官方源文件清单准备替换SDK，保留全部外设模块，不按预测裁剪。"""
from pathlib import Path
import re
import shutil
import subprocess
from bspforge.common import read_json,write_json,file_sha256,utc_now
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.ir_store import IRStore


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)


def main():
    root=Path.cwd();out=root/'experiments/revision-r1-replacements';out.mkdir(parents=True,exist_ok=True)
    records=[]
    for name in ['max32650-msdk','stm32f4-stdperiph']:
        repo=root.parent/'evaluation-sdks'/('revision-maxim-msdk' if name.startswith('max') else 'revision-stm32f4-stdperiph')
        target=root/'sdk'/name/'source';target.mkdir(parents=True,exist_ok=True)
        if name.startswith('max'):
            periph=repo/'Libraries/PeriphDrivers';mk=periph/'max32650_files.mk'
            copy(mk,target/'Libraries/PeriphDrivers/max32650_files.mk')
            # 官方Makefile给出的目标源集，包括与五类测试能力无关的外设。
            sources=set(re.findall(r'\$\(SOURCE_DIR\)/([A-Za-z0-9_/.-]+\.c)',mk.read_text()))
            sources.update(['SYS/pins_me10.c','SYS/nvic_table.c'])
            for source in sources:copy(periph/'Source'/source,target/'Libraries/PeriphDrivers/Source'/source)
            for folder in {str(Path(s).parent) for s in sources}:
                for header in (periph/'Source'/folder).glob('*.h'):
                    copy(header,target/'Libraries/PeriphDrivers/Source'/folder/header.name)
            shutil.copytree(periph/'Include/MAX32650',target/'Libraries/PeriphDrivers/Include/MAX32650',dirs_exist_ok=True)
            for header in (periph/'Include').glob('*.h'):copy(header,target/'Libraries/PeriphDrivers/Include'/header.name)
            shutil.copytree(repo/'Libraries/CMSIS/Device/Maxim/MAX32650',target/'Libraries/CMSIS/Device/Maxim/MAX32650',dirs_exist_ok=True)
            shutil.copytree(repo/'Libraries/CMSIS/Include',target/'Libraries/CMSIS/Include',dirs_exist_ok=True)
            url='https://github.com/analogdevicesinc/msdk';board='max32650evkit';model='max32652.repl'
            selection='MAX32650官方max32650_files.mk完整外设源集、目标CMSIS和头文件'
            vendor='Analog Devices/Maxim'
        else:
            libraries=repo/'Libraries'
            shutil.copytree(libraries/'STM32F4xx_StdPeriph_Driver',target/'Libraries/STM32F4xx_StdPeriph_Driver',dirs_exist_ok=True)
            shutil.copytree(libraries/'CMSIS/Device/ST/STM32F4xx',target/'Libraries/CMSIS/Device/ST/STM32F4xx',dirs_exist_ok=True)
            shutil.copytree(libraries/'CMSIS/Include',target/'Libraries/CMSIS/Include',dirs_exist_ok=True)
            url='https://github.com/whimsicalraps/STM32F4xx_DSP_StdPeriph_Lib';board='stm32f4_disco';model='stm32f4.repl'
            selection='完整StdPeriph外设驱动和目标CMSIS；DSP算法库不属于芯片外设SDK输入'
            vendor='STMicroelectronics'
        for license in repo.glob('*'):
            if license.is_file() and any(s in license.name.lower() for s in ['license','licence','notice','release_notes']):copy(license,target/license.name)
        revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        record={'name':name,'sdk_id':'revision-'+name,'vendor':vendor,'architecture':'arm-cortex-m4',
                'source_path':str(target),'source_url':url,'revision':revision,'original_repository':str(repo),
                'role':'external-test','training_included':False,'independence_group':'revision-'+name,
                'board':board,'renode_platform':model,'input_scope':selection,'operations':19,
                'rtos_backends':['rtthread','zephyr'],'source_sha256':{str(p.relative_to(target)):file_sha256(p) for p in target.rglob('*') if p.is_file()}}
        previous=read_json(out/name/'source-manifest.json') if (out/name/'source-manifest.json').exists() else {}
        write_json(out/name/'source-manifest.json',record);records.append(record)
        irpath=out/name/'ir'/(record['sdk_id']+'.json')
        if not irpath.exists() or previous.get('source_sha256')!=record['source_sha256']:
            ir=SDKIngestor(frontend_mode='hybrid').ingest(target,record['sdk_id'])
            write_json(irpath,ir)
            print(name,{'files':len(ir['files']),'functions':len(ir['functions']),'edges':len(ir['edges'])},flush=True)
        IRStore(irpath.parent).put(read_json(irpath))
    write_json(out/'manifest.json',{'schema_version':'1.0','created_at':utc_now(),'sdks':records,
        'selection_policy':'公开接口与模型覆盖预审先于语义预测；不按预测分数选择或删去SDK',
        'model_sha256':file_sha256(root/'models/structural-prior-feasible-lambdamart-h03-eq-r1-v2.1.txt')})


if __name__=='__main__':main()
