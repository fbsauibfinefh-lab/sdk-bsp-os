"""对受共享Zephyr后端修改影响的四配置执行真实构建与十轮回归。"""
from pathlib import Path
import argparse
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--asf3-only',action='store_true');p.add_argument('--wait-pid',type=int)
    args=p.parse_args()
    if args.wait_pid:
        print('WAITING_FOR_PRIOR_ASF3_RUN',args.wait_pid,flush=True)
        while Path('/proc',str(args.wait_pid),'cmdline').exists():time.sleep(2)
    if args.asf3_only:
        for os in ['rtthread','zephyr']:
            result=subprocess.run([sys.executable,'-u','scripts/run_replacement_sdk_matrix.py','--experiment-root',
                                   'experiments/revision-r1-expanded','--only','asf3-sam4s','--os',os,'--rounds','10','--contract-guards'],cwd=ROOT)
            print('FINAL_ASF3_CONFIGURATION_FINISHED',os,result.returncode,flush=True)
        return
    configurations=[('revision-r1-replacements','max32650-msdk'),('revision-r1-replacements','stm32f4-stdperiph'),
                    ('revision-r1-expanded','stellaris-driverlib'),('revision-r1-expanded','asf3-sam4s')]
    for cohort,sdk in configurations:
        result=subprocess.run([sys.executable,'-u','scripts/run_replacement_sdk_matrix.py','--experiment-root',
                               'experiments/'+cohort,'--only',sdk,'--os','zephyr','--rounds','10','--contract-guards'],cwd=ROOT)
        print('CONFIGURATION_FINISHED',sdk,result.returncode,flush=True)


if __name__=='__main__':main()
