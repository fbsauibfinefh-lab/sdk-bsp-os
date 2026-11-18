"""在新增验证配置中复用既有BuildDiagnoser，仅添加IR可唯一确定的构建资产。"""
from pathlib import Path
import argparse
import subprocess
import sys
import shutil
import time
from bspforge.common import read_json,write_json,file_sha256
from bspforge.build_diagnoser import BuildDiagnoser

def apply_assets(assets,path):
    if path.exists():
        extra=read_json(path)
        for key in ['providers','includes']:
            assets[key]=list(dict.fromkeys(assets[key]+extra.get(key,[])))
    write_json(path.parent/'app/sdk-build-assets.json',assets)
    return assets

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--os',required=True,choices=['rtthread','zephyr']);p.add_argument('--only');p.add_argument('--rounds',type=int,default=1);p.add_argument('--fresh',action='store_true');a=p.parse_args()
    root=Path.cwd();base=root/'experiments/revision-r1-five-sdk';manifest=read_json(base/'manifest.json')
    for sdk in manifest['sdks']:
        name=sdk['name']
        if a.only and name!=a.only:continue
        mode=a.os+'-sdk-uart-gpio';out=base/name/mode;work=root/'workspace/revision-r1-five-sdk'/name/mode
        out.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
        series=out/'feedback-series'/str(time.time_ns());series.mkdir(parents=True)
        if a.fresh:
            if (work/'feedback-assets.json').exists():shutil.copy2(work/'feedback-assets.json',series/'previous-feedback-assets.json')
            write_json(work/'feedback-assets.json',{'providers':[],'includes':[]})
        script='build_revision_rtthread_controls.py' if a.os=='rtthread' else 'run_revision_native_controls.py'
        ir=read_json(base/name/'ir'/(sdk['sdk_id']+'.json'));source=Path(sdk['source_path'])
        # 模块归属是SDK配置的CPU证据，不允许将DSP提供者加入MCU工程。
        ir={**ir,'functions':[e for e in ir['functions'] if '/dsp/' not in e['file']]}
        attempts=[]
        for attempt in range(1,4):
            cmd=[sys.executable,str(root/'scripts'/script),'--sdk-uart','--only',name,'--rounds',str(a.rounds)]
            folder=series/f'feedback-attempt-{attempt:02d}';folder.mkdir(parents=True,exist_ok=True)
            with (folder/'runner.log').open('w') as log:subprocess.run(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT)
            result=read_json(out/'build-result.json') if (out/'build-result.json').exists() else {'returncode':-1}
            text=(out/'build.log').read_text() if (out/'build.log').exists() else ''
            for filename in ['build-result.json','build.log']:
                if (out/filename).exists():shutil.copy2(out/filename,folder/filename)
            assets=read_json(work/'app/sdk-build-assets.json') if (work/'app/sdk-build-assets.json').exists() else {}
            diagnosis=BuildDiagnoser().diagnose(text.replace('bsp_input_',''),result['returncode'])
            closure={'selected_files':[{'path':str(Path(f).relative_to(source))} for f in assets.get('providers',[]) if Path(f).is_relative_to(source)],
                     'target_context':{'architecture':'arm' if sdk['architecture'].startswith('arm') else 'riscv'}}
            proposal=BuildDiagnoser().propose_repairs(ir,diagnosis,closure)
            extra=read_json(work/'feedback-assets.json') if (work/'feedback-assets.json').exists() else {'providers':[],'includes':[]}
            changes=[]
            if result['returncode']:
                for repair in proposal['repairs']:
                    path=(source/repair['path']).resolve()
                    if not path.is_relative_to(source.resolve()):continue
                    key='providers' if repair['action']=='add-source' and path.suffix in ['.c','.cpp','.S'] else 'includes' if repair['action']=='add-include-dir' else None
                    if key and str(path) not in assets.get(key,[]):
                        extra[key].append(str(path));changes.append(repair)
            write_json(work/'feedback-assets.json',{k:sorted(set(v)) for k,v in extra.items()})
            record={'attempt':attempt,'returncode':result['returncode'],'diagnosis':diagnosis,'proposal':proposal,'applied':changes,
                    'assets_sha256':file_sha256(work/'app/sdk-build-assets.json') if assets else None}
            write_json(folder/'diagnosis-and-repairs.json',record);attempts.append(record)
            print(name,a.os,attempt,result['returncode'],[r['path'] for r in changes],flush=True)
            if result['returncode']==0 or not changes:break
        write_json(out/'compiler-feedback.json',{'max_attempts':3,'attempts':attempts,
          'fresh_asset_feedback_state':a.fresh,'series':str(series),
          'automatic_repair_applied':any(r['applied'] for r in attempts),'semantics_or_reference_changed':False,
          'scope':'既有诊断器的唯一提供者与头文件路径修复；签名、参数、命名空间和平台初始化由显式适配配置提供。'})

if __name__=='__main__':main()
