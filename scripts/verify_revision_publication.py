#!/usr/bin/env python3
"""验证公开文件和模型版本；可核对作者交付记录重算的指标。"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'reproduction/mdpi-r1'
MANIFEST = PUBLIC / 'files.sha256.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def inventory():
    raw = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'])
    files = sorted({x.decode() for x in raw.split(b'\0') if x})
    return {name: {'size': (ROOT / name).stat().st_size,
        'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in files if (ROOT / name).is_file() and (ROOT / name) != MANIFEST}


def equal(actual, expected, path='metrics'):
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError('字段不一致: ' + path)
        for key in expected:
            equal(actual[key], expected[key], path + '.' + key)
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError('长度不一致: ' + path)
        for i, (a, b) in enumerate(zip(actual, expected)):
            equal(a, b, path + '.' + str(i))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isclose(actual, expected, abs_tol=1e-9, rel_tol=1e-9):
            raise ValueError('数值不一致: ' + path)
    elif actual != expected:
        raise ValueError('内容不一致: ' + path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest', action='store_true')
    parser.add_argument('--metrics', type=Path)
    args = parser.parse_args()
    contract = read(PUBLIC / 'model-contract.json')
    actual = hashlib.sha256((ROOT / contract['deployment_model']).read_bytes()).hexdigest()
    if actual != contract['deployment_sha256']:
        raise ValueError('冻结部署模型SHA-256不一致')
    assert len(contract['deployment_feature_names']) == 91
    if args.metrics:
        equal(read(args.metrics), read(PUBLIC / 'expected-metrics.json'))
    if args.write_manifest:
        MANIFEST.write_text(json.dumps({'schema_version': '1.0', 'release_tag': 'mdpi-r1-20261118',
            'hash_algorithm': 'sha256', 'files': inventory()}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    recorded = read(MANIFEST)['files']
    mismatches = []
    for name, record in recorded.items():
        path = ROOT / name
        if not path.is_file() or path.stat().st_size != record['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            mismatches.append(name)
    if mismatches:
        raise ValueError('公开文件校验失败: ' + ', '.join(mismatches))
    print(json.dumps({'public_files_verified': len(recorded), 'model_sha256': actual,
        'metrics_compared': args.metrics is not None, 'training_or_firmware_execution': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
