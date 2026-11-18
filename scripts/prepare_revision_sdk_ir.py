#!/usr/bin/env python3
"""解析五个新SDK，并导出源码接口清单供独立参考答案审阅。"""
from __future__ import annotations

import gc
import argparse
import shutil
import time
from pathlib import Path

from bspforge.common import file_sha256, read_json, write_json
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.ir_store import IRStore


def main() -> int:
    root = Path.cwd()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', choices=['litex'])
    args = parser.parse_args()
    output = root / 'experiments/revision-r1-five-sdk'
    manifest = read_json(output / 'manifest.json')
    for sdk in manifest['sdks']:
        target = output / sdk['name']
        target.mkdir(parents=True, exist_ok=True)
        irpath = target / 'ir' / (sdk['sdk_id'] + '.json')
        if irpath.exists() and args.refresh != sdk['name']:
            continue
        start = time.perf_counter()
        if sdk['name'] == 'sifive-fe310':
            old = root / 'experiments/revision-r1-20261112/sifive-fe310/ir' / irpath.name
            ir = read_json(old)
        else:
            ir = SDKIngestor(frontend_mode='hybrid').ingest(Path(sdk['source_path']), sdk['sdk_id'])
        IRStore(irpath.parent).put(ir)
        write_json(irpath, ir)
        functions = [{'entity_id': e['id'], 'symbol': e['name'], 'signature': e.get('signature'),
                      'file': e['file'], 'line': e.get('line'), 'end_line': e.get('end_line')}
                     for e in ir['functions']]
        write_json(target / 'source-interface-inventory.json', functions)
        result = {'seconds': time.perf_counter() - start, 'files': len(ir['files']),
                  'functions': len(functions), 'edges': len(ir['edges']), 'sdk_digest': ir['sdk']['digest'],
                  'ir_sha256': file_sha256(irpath), 'ranking_performed': False}
        write_json(target / 'ingest-summary.json', result)
        print(sdk['name'], result, flush=True)
        del ir, functions
        gc.collect()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
