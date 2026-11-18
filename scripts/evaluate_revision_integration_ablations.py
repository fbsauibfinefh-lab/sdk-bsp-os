#!/usr/bin/env python3
"""在独立目录以真实交叉编译器运行六配置、四条件集成对照。"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from bspforge.binding_planner import BindingPlanner
from bspforge.common import file_sha256, read_json, write_json
from bspforge.pipeline import Pipeline


TARGETS = ('k210-rtthread', 'k210-zephyr', 'psoc-e84-rtthread', 'psoc-e84-zephyr', 'stm32f103-rtthread', 'stm32f103-zephyr')
CONDITIONS = ('full', 'without-compatibility', 'target-components', 'without-feedback')


def component_config(config: dict, root: Path) -> dict:
    board = config['backend']['sdk_profile']
    sdk = root / config['sdk']['path']
    if board == 'k210':
        roots = ['lib/drivers', 'lib/utils']
        exclusions = []
        if config['backend']['type'] == 'rtthread':
            roots += ['lib/bsp']
            exclusions = [p.relative_to(sdk).as_posix() for p in (sdk / 'lib/bsp').glob('*.c') if p.name in {'entry.c'}]
    elif board == 'stm32f103':
        roots = ['Drivers/STM32F1xx_HAL_Driver/Src']
        exclusions = [p.relative_to(sdk).as_posix() for p in (sdk / roots[0]).rglob('*.c') if 'template' in p.name or 'timebase' in p.name]
    else:
        roots = ['Common', 'M33_Config', 'HAL_Drivers']
        exclusions = []
    return {**config['closure'], 'strategy': 'target-components', 'component_roots': roots, 'excluded_sources': exclusions}


def plan_quality(path: Path) -> dict:
    if not path.exists():
        return {'available': False}
    plan = read_json(path)
    checks = []
    for capability in plan['capabilities']:
        families = set()
        for op in capability['operations']:
            valid, reason = BindingPlanner._signature_compatible(capability['capability'], op['operation'], op.get('selected_symbol') or '', op.get('signature') or '')
            family = BindingPlanner._compatible_family(capability['capability'], op.get('selected_symbol') or '')
            if family:
                families.add(family)
            checks.append({'operation_id': capability['capability'] + '.' + op['operation'], 'symbol': op['selected_symbol'], 'signature_compatible': valid, 'reason': reason, 'composite_symbols': op.get('composite_symbols', []), 'selection_changed': op.get('decoder', {}).get('selection_changed', False)})
    return {'available': True, 'operations': len(checks), 'signature_compatible': sum(x['signature_compatible'] for x in checks), 'checks': checks}


def run_one(root: Path, work: Path, target: str, condition: str) -> dict:
    base = root / 'examples' / target / 'project.json'
    config = copy.deepcopy(read_json(base))
    run_id = f'{target}-{condition}'
    config.update(run_id=run_id, workspace=str(work), ir_store=str(work / 'ir'))
    config['backend']['output'] = str(work / 'generated' / run_id)
    config['build']['jobs'] = 8
    config.pop('evaluation', None)
    if condition == 'without-compatibility':
        config['resolver']['binding_decoder'] = 'top1'
    if condition == 'target-components':
        config['closure'] = component_config(config, root)
    if condition == 'without-feedback':
        config['build']['max_iterations'] = 1
    path = work / 'configs' / (run_id + '.json')
    write_json(path, config)
    result = {'target': target, 'condition': condition, 'config': str(path), 'base_config_sha256': file_sha256(base), 'bundle_sha256': file_sha256(root / config['resolver']['model_path']), 'manual_edits_during_run': 0, 'hardware_retested': False}
    started = time.perf_counter()
    try:
        report = Pipeline(root).run(path)
        result.update(build_success=report['build']['success'], attempts=report['build']['attempts'], repairs=report['build']['repairs_applied'], stop_reason=report['build']['stop_reason'], timings=report['timings'], selected_files=report['closure']['files'], report=str(work / 'runs' / run_id / 'report.json'))
        result['first_build_success'] = report['build']['iterations'][0]['success']
        result['diagnostic_categories'] = sorted({d['category'] for it in report['build']['iterations'] for d in it['diagnosis']['diagnostics']})
        result['artifact_sizes'] = [{k: a[k] for k in ('kind', 'size', 'sha256')} for a in report['build'].get('artifact_verification', {}).get('artifacts', [])]
    except Exception as error:
        result.update(build_success=False, attempts=0, repairs=0, stop_reason='generation-or-tool-exception', error=repr(error), traceback=traceback.format_exc())
        (work / 'logs').mkdir(parents=True, exist_ok=True)
        (work / 'logs' / (run_id + '.log')).write_text(traceback.format_exc(), encoding='utf-8')
    result['wall_seconds'] = time.perf_counter() - started
    result['plan_quality'] = plan_quality(work / 'runs' / run_id / '02b-canonical-binding-plan.json')
    generated = Path(config['backend']['output'])
    objects = list(generated.rglob('*.o')) if generated.exists() else []
    result['object_files_on_disk'] = len(objects)
    result['object_size_bytes'] = sum(p.stat().st_size for p in objects)
    # Native HAL providers remain selected by their official RTOS configuration.
    result['component_scope'] = 'native OS target component configuration retained' if config['backend'].get('binding_strategy') != 'generated-sdk-adapter' and 'k210' not in target else 'generated SDK adapter component sources'
    write_json(work / 'records' / (run_id + '.json'), result)
    print(json.dumps({k: result.get(k) for k in ('target', 'condition', 'build_success', 'attempts', 'stop_reason', 'wall_seconds')}, ensure_ascii=False), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')
    args.work.mkdir(parents=True, exist_ok=True)
    records = []
    for condition in CONDITIONS:
        for target in TARGETS:
            saved = args.work / 'records' / f'{target}-{condition}.json'
            if saved.exists():
                records.append(read_json(saved))
                continue
            records.append(run_one(root, args.work, target, condition))
    write_json(args.output, {'protocol': {'conditions': CONDITIONS, 'targets': TARGETS, 'threads': 8, 'repetitions': 1, 'ranking_frozen': True, 'independent_generated_directories': True, 'no_physical_test_claim': True, 'timing_note': 'One controlled build per configuration; not a performance significance study.'}, 'records': records})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
