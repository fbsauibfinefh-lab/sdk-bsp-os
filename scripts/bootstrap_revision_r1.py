#!/usr/bin/env python3
"""准备正式五SDK的固定源码和适用范围；不读取真值或模型预测。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'reproduction/mdpi-r1'
SPARSE = {
    'max32650-msdk': ['Libraries/PeriphDrivers', 'Libraries/CMSIS'],
    'stm32f4-stdperiph': ['Libraries/STM32F4xx_StdPeriph_Driver', 'Libraries/CMSIS'],
    'stellaris-driverlib': ['driverlib', 'inc'],
    'asf3-sam4s': ['sam', 'common', 'thirdparty/CMSIS/Include'],
    'nrf5-nrf52840': ['modules/nrfx', 'integration/nrfx', 'components/drivers_nrf', 'components/toolchain/cmsis/include'],
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def run(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def verify_inputs(selected):
    checked = 0
    for sdk in selected:
        source = ROOT / sdk['source_path']
        for relative, expected in load(PUBLIC / sdk['source_hash_manifest']).items():
            path = source / relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('SDK输入与论文快照不一致: ' + str(path))
            checked += 1
    print(json.dumps({'source_files_verified': checked, 'reference_labels_read': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=list(SPARSE))
    parser.add_argument('--download', action='store_true', help='下载缺失的固定源码；已有不同提交的目录停止处理')
    parser.add_argument('--prepare', action='store_true', help='准备两个完整批次的SDK输入与IR')
    parser.add_argument('--verify-inputs', action='store_true', help='验证所选SDK全部文件哈希')
    args = parser.parse_args()
    records = load(PUBLIC / 'simulation-sdks.json')['sdks']
    selected = [r for r in records if args.only is None or r['name'] == args.only]
    if args.download:
        for sdk in selected:
            repo = ROOT.parent / 'evaluation-sdks' / sdk['original_repository']
            if not repo.exists():
                repo.parent.mkdir(parents=True, exist_ok=True)
                run(['git', 'clone', '--filter=blob:none', '--no-checkout', sdk['source_url'], repo])
                run(['git', '-C', repo, 'sparse-checkout', 'init', '--cone'])
                run(['git', '-C', repo, 'sparse-checkout', 'set', *SPARSE[sdk['name']]])
                run(['git', '-C', repo, 'fetch', '--depth', '1', 'origin', sdk['revision']])
                run(['git', '-C', repo, 'checkout', '--detach', sdk['revision']])
            actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            if actual != sdk['revision']:
                raise ValueError('已有目录提交不同，请使用独立输入目录: ' + str(repo))
    for cohort in ['revision-r1-replacements', 'revision-r1-expanded']:
        destination = ROOT / 'experiments' / cohort / 'operation-scope.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        original = PUBLIC / 'config' / cohort / 'operation-scope.json'
        if destination.exists() and destination.read_bytes() != original.read_bytes():
            if load(destination) != load(original):
                raise ValueError('已有适用范围不同，保留原文件并停止: ' + str(destination))
        elif not destination.exists():
            shutil.copy2(original, destination)
    if args.prepare:
        if args.only:
            parser.error('--prepare按完整批次准备，不与--only同时使用')
        for name in ['prepare_revision_replacement_sdks.py', 'prepare_revision_expanded_sdks.py']:
            run([sys.executable, ROOT / 'scripts' / name])
    if args.verify_inputs:
        verify_inputs(selected)
    if not any([args.download, args.prepare, args.verify_inputs]):
        print(json.dumps({'sdks': [{k: r[k] for k in ['name', 'source_url', 'revision']} for r in selected]}, indent=2))


if __name__ == '__main__':
    main()
