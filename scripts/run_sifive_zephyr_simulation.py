#!/usr/bin/env python3
"""在真实FE310外设模型中交叉编译并运行Zephyr，保存串口原始流和逐项断言。"""
from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from bspforge.common import file_sha256, read_json, write_json
from bspforge.binding_planner import BindingPlanner


def typed_parameters(signature: str) -> list[str]:
    return [re.sub(r'\s+', ' ', re.sub(r'\b[A-Za-z_]\w*\s*$', '', p).strip())
            .replace(' *', '*').replace('* ', '*')
            for p in BindingPlanner._signature_parameters(signature)]


def select_typed_call(candidates: list[dict], entities: dict, parameters: list[str]) -> tuple[dict, list[dict]]:
    rejected = []
    for candidate in candidates:
        entity = entities[candidate['entity_id']]
        path = entity['file']
        public = path.startswith('metal/') and '/drivers/' not in path
        actual = typed_parameters(entity.get('signature', ''))
        if public and actual == parameters:
            return {**candidate, 'signature': entity['signature'], 'file': path, 'line': entity.get('line')}, rejected
        rejected.append({'symbol': candidate['symbol'], 'rank': candidate['rank'],
                         'reason': 'non-public-header' if not public else 'parameter-types',
                         'actual': actual})
    raise ValueError(f'No typed call matching {parameters}')


def prepare_selected_calls(output: Path) -> dict:
    bundle = read_json(output / 'frozen-runtime-bundle.json')
    ir = read_json(output / 'ir/sifive-freedom-metal-fe310.json')
    entities = {entity['id']: entity for entity in ir['functions']}
    contracts = {'uart.configure': ['struct metal_uart*', 'int'],
                 'uart.write': ['struct metal_uart*', 'int'],
                 'uart.read': ['struct metal_uart*', 'int*'],
                 'gpio.write': ['struct metal_gpio*', 'int', 'int'],
                 'gpio.read': ['struct metal_gpio*', 'int']}
    selections = {}
    lines = ['/* Experimental typed SDK adapter; production ranker is unchanged. */']
    for operation, contract in contracts.items():
        selected, rejected = select_typed_call(bundle['operations'][operation]['candidates'], entities, contract)
        selections[operation] = {'selected': selected, 'rejected_before_selection': rejected, 'parameter_contract': contract}
        lines.append('#define SDK_' + operation.upper().replace('.', '_') + ' ' + selected['symbol'])
    (output / 'simulation-selected-calls.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = {'strategy': 'new SDK profile with public-header parameter-type adapter',
              'ranker_retrained': False, 'production_planner_changed': False, 'selections': selections,
              'os_owned': ['PLIC initialization and GPIO IRQ registration/masking', 'CLINT system timer and kernel timer lifecycle'],
              'sdk_profile_setup': ['metal_gpio_get_device(0)', 'metal_uart_get_device(0)',
                  'metal_gpio_disable_pinmux(gpio,0)', 'metal_gpio_enable_output(gpio,0)', 'metal_gpio_enable_input(gpio,0)'],
              'scope': 'Five ranking-selected SDK operations in a new integration profile; not a 19-operation unchanged-backend confirmation.'}
    write_json(output / 'simulation-selection-manifest.json', result)
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def connect(port: int, process: subprocess.Popen) -> socket.socket:
    end = time.monotonic() + 40
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f'Renode exited {process.returncode}')
        try:
            return socket.create_connection(('127.0.0.1', port), timeout=1)
        except OSError:
            time.sleep(.1)
    raise TimeoutError(f'port {port}')


def receive(sock: socket.socket, marker: bytes, timeout: float = 20) -> bytes:
    sock.settimeout(.2)
    output = bytearray()
    end = time.monotonic() + timeout
    while marker not in output and time.monotonic() < end:
        try:
            part = sock.recv(4096)
            if not part: break
            output.extend(part)
        except socket.timeout:
            pass
    return bytes(output)


def simulate(root: Path, elf: Path, output: Path, rounds: int, sdk_counters_required: bool = False) -> list[dict]:
    renode = root.parent / 'tools/renode-1.17.0'
    platform = renode / 'platforms/cpus/sifive-fe310.repl'
    records = []
    output = output / 'runs' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    for round_id in range(1, rounds + 1):
        run = output / f'round-{round_id:02d}'
        run.mkdir(parents=True, exist_ok=True)
        monitor, uart = free_port(), free_port()
        configured_platform = run / 'sifive-fe310-16mhz.repl'
        definition, changes = re.subn(r'frequency:\s*62000000', 'frequency: 16000000', platform.read_text(encoding='utf-8'))
        if changes != 1:
            raise ValueError('Expected exactly one CLINT clock setting in the pinned platform')
        configured_platform.write_text(definition, encoding='utf-8')
        script = run / 'run.resc'
        script.write_text(
            f'mach create "bspforge-fe310"\n'
            f'machine LoadPlatformDescription @{configured_platform}\n'
            f'emulation CreateServerSocketTerminal {uart} "terminal" false\n'
            'connector Connect sysbus.uart0 terminal\n'
            f'sysbus.uart0 CreateFileBackend @{run / "uart.log"} true\n'
            'sysbus Tag <0x10008000 4> "PRCI_HFROSCCFG" 0xFFFFFFFF\n'
            'sysbus Tag <0x10008008 4> "PRCI_PLLCFG" 0xFFFFFFFF\n'
            f'sysbus LoadELF @{elf}\n'
            'cpu PC `sysbus GetSymbolAddress "__start"`\n'
            'cpu PerformanceInMips 100\n', encoding='utf-8')
        command = [str(renode / 'renode'), '--disable-gui', '--plain',
                   '--port', str(monitor), '--execute', f'include @{script}']
        record = {'round': round_id, 'directory': str(run), 'command': command, 'boot': False, 'cases': [], 'raw': []}
        with (run / 'renode.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=renode, stdout=log, stderr=subprocess.STDOUT)
            try:
                with connect(uart, process) as serial, connect(monitor, process) as control:
                    greeting = receive(control, b'(bspforge-fe310)', 2)
                    control.sendall(b'start\r\n')
                    ready = receive(serial, b'\n', 20)
                    record['raw'].append({'direction': 'rx', 'base64': base64.b64encode(ready).decode()})
                    record['boot'] = b'READY ' in ready
                    if not record['boot']:
                        raise RuntimeError('firmware READY timeout: ' + repr(ready))
                    for key in ['G', 'I', 'T', 'U16', 'U255', 'S']:
                        payload = bytes((i * 37 + round_id) % 256 for i in range(int(key[1:]))) if key.startswith('U') else b''
                        tx = b'U' + bytes([len(payload)]) + payload if payload else key.encode()
                        serial.sendall(tx)
                        rx = receive(serial, b'PASS ' + key[0].encode() + b'\n', 10)
                        success = (b'PASS ' + key[0].encode() + b'\n') in rx
                        if payload:
                            success = success and b'PAYLOAD ' + payload + b'\nPASS U\n' in rx
                        if key == 'S' and sdk_counters_required:
                            counters = re.search(rb'COUNTS tx=(\d+) rx=(\d+) write=(\d+) read=(\d+)', rx)
                            success = success and counters is not None and all(int(v) > 0 for v in counters.groups())
                        record['cases'].append({'case': key, 'passed': success, 'tx_base64': base64.b64encode(tx).decode(), 'rx_base64': base64.b64encode(rx).decode(), 'bytes': len(payload), 'retries': 0})
                    record['monitor_greeting'] = greeting.decode(errors='replace')
            except Exception as error:
                record['error'] = repr(error)
            finally:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        write_json(run / 'result.json', record)
        records.append(record)
        print({'round': round_id, 'boot': record['boot'], 'passed': sum(c['passed'] for c in record['cases']), 'error': record.get('error')}, flush=True)
        if not record['boot']: break
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['native', 'metal'], default='native')
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    root = Path.cwd()
    output = root / 'experiments/revision-r1-20261112/sifive-fe310' / args.mode
    output.mkdir(parents=True, exist_ok=True)
    work = root / 'workspace/revision-r1-20261112/sifive-fe310' / args.mode
    app = work / 'app'
    shutil.copytree(root / 'ports/zephyr-fe310-simulation', app, dirs_exist_ok=True)
    env = dict(os.environ)
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env['PATH']
    env.update(ZEPHYR_BASE=str(root.parent / 'zephyr'), ZEPHYR_TOOLCHAIN_VARIANT='cross-compile',
               CROSS_COMPILE=str(root / 'toolchains/xpack-riscv-none-elf-gcc-14.2.0-3/bin/riscv-none-elf-'),
               CMAKE_BUILD_PARALLEL_LEVEL='4')
    command = ['west', 'build', '-b', 'hifive1', '-d', str(work / 'build'), str(app), '--', f'-DUSER_CACHE_DIR={work / "cache"}']
    if args.mode == 'metal':
        sdk = root / 'sdk/sifive-fe310/source'
        machine = app / 'include/metal/machine'
        machine.mkdir(parents=True, exist_ok=True)
        for source, dest in [('metal.h', machine.parent / 'machine.h'), ('metal-inline.h', machine / 'inline.h'), ('metal-platform.h', machine / 'platform.h')]:
            shutil.copy2(sdk / 'board/sifive-hifive1' / source, dest)
        selected = output.parent / 'simulation-selected-calls.h'
        prepare_selected_calls(output.parent)
        shutil.copy2(selected, app / 'include/selected_calls.h')
        command += [f'-DMETAL_ROOT={sdk}']
    if not args.skip_build:
        previous = output / 'build.log'
        if previous.exists():
            shutil.copy2(previous, output / f'build-before-{time.time_ns()}.log')
        started = time.monotonic()
        proc = subprocess.run(command, cwd=root.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (output / 'build.log').write_text(proc.stdout, encoding='utf-8')
        write_json(output / 'build-result.json', {'command': command, 'returncode': proc.returncode, 'seconds': time.monotonic() - started})
        print(proc.stdout[-5500:], flush=True)
        if proc.returncode: return proc.returncode
    elf = work / 'build/zephyr/zephyr.elf'
    records = simulate(root, elf, output, args.rounds, args.mode == 'metal')
    summary = {'mode': args.mode, 'firmware': str(elf), 'firmware_sha256': file_sha256(elf), 'boot_passed': sum(r['boot'] for r in records),
               'boots_attempted': len(records), 'cases_passed': sum(c['passed'] for r in records for c in r['cases']),
               'cases_attempted': sum(len(r['cases']) for r in records), 'planned_cases': args.rounds * 6,
               'records': records, 'platform_sha256': file_sha256(root.parent / 'tools/renode-1.17.0/platforms/cpus/sifive-fe310.repl')}
    write_json(output / 'results.json', summary)
    return 0 if summary['cases_passed'] == summary['planned_cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
