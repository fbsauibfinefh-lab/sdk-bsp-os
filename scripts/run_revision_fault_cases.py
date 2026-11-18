#!/usr/bin/env python3
"""用真实ARM交叉编译器检验安全修复与歧义停止，全部属于人工故障用例。"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.common import file_sha256, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    gcc = (root/'toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc').resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture = {'entry.c': 'extern int provider(void); void _start(void) { volatile int n=provider(); (void)n; for (;;) {} }\n', 'include-entry.c': '#include "revision_fixture.h"\nvoid _start(void) { volatile int n=VALUE; (void)n; for (;;) {} }\n', 'inc/revision_fixture.h': '#define VALUE 7\n', 'provider.c': 'int provider(void) { return 7; }\n', 'other/provider.c': 'int provider(void) { return 9; }\n', 'overflow.c': 'char too_large[1024]; void _start(void) { too_large[0]=1; for (;;) {} }\n', 'tiny.ld': 'MEMORY { RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 128 }\nSECTIONS { .text : { *(.text*) } > RAM .bss : { *(.bss*) *(COMMON) } > RAM /DISCARD/ : { *(.comment*) *(.ARM*) } }\n'}
    for name,text in fixture.items():
        p=out/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='ascii')
    files=[{'id': name,'path':name,'kind':'header' if name.endswith('.h') else 'source'} for name in fixture]
    functions=[{'id':name,'name':'provider','file':name,'signature':'int provider(void)'} for name in ['provider.c','other/provider.c']]
    records=[]
    for name, entry, providers in [('missing-header','include-entry.c',[]),('unique-provider','entry.c',['provider.c']),('ambiguous-provider','entry.c',['provider.c','other/provider.c']),('memory-overflow','overflow.c',[])]:
        command=[str(gcc),'-mcpu=cortex-m3','-mthumb','-nostdlib','-Wl,-e,_start',str(out/entry),'-o',str(out/(name+'.elf'))]
        if name=='memory-overflow':
            command+=['-T',str(out/'tiny.ld')]
        attempts=[]
        current=list(command)
        for iteration in range(2):
            run=subprocess.run(current, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log=out/f'{name}-{iteration+1}.log'
            log.write_text(run.stdout, encoding='utf-8')
            diagnosis=BuildDiagnoser().diagnose(run.stdout,run.returncode)
            ir={'files':files,'functions':[f for f in functions if f['file'] in providers]}
            proposal=BuildDiagnoser().propose_repairs(ir,diagnosis,{'selected_files':[], 'target_context':{'architecture':'arm'}}) if run.returncode else {'repairs':[],'unresolved':[]}
            attempts.append({'command':list(current),'returncode':run.returncode,'log':str(log),'diagnosis':diagnosis,'proposal':proposal})
            if run.returncode==0 or not proposal['repairs']:
                break
            for repair in proposal['repairs']:
                if repair['action']=='add-include-dir':
                    current+=['-I',str(out/repair['path'])]
                elif repair['action']=='add-source':
                    current+=[str(out/repair['path'])]
        expected_success=name in {'missing-header','unique-provider'}
        success=attempts[-1]['returncode']==0
        assert success==expected_success, name
        records.append({'case':name,'artificial_injection':True,'first_success':attempts[0]['returncode']==0,'feedback_success':success,'safe_stop':not success and not attempts[-1]['proposal']['repairs'],'attempts':attempts})
    result={'compiler':str(gcc),'compiler_sha256':file_sha256(gcc),'version':subprocess.check_output([str(gcc),'--version'],text=True).splitlines()[0],'not_board_or_natural_failure_evidence':True,'records':records}
    write_json(out/'results.json',result)
    print([(r['case'],r['feedback_success'],r['safe_stop']) for r in records])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
