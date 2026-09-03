from __future__ import annotations

import argparse
import json
import selectors
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Protocol

from bspforge.common import file_sha256, utc_now, write_json
from bspforge.hardware_test.protocol import DEFAULT_COMMANDS, parse_event, request_line


class Transport(Protocol):
    def write(self, value: bytes) -> int: ...
    def readline(self) -> bytes: ...
    def close(self) -> None: ...


class SerialTransport:
    def __init__(self, port: str, baudrate: int, timeout: float) -> None:
        try:
            import serial
        except ImportError as error:
            raise RuntimeError("hardware test requires the 'hardware' optional dependency") from error
        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)

    def write(self, value: bytes) -> int:
        return self.serial.write(value)

    def readline(self) -> bytes:
        return self.serial.readline()

    def close(self) -> None:
        self.serial.close()

    def reset(self) -> None:
        self.serial.dtr = False
        time.sleep(0.05)
        self.serial.reset_input_buffer()
        self.serial.dtr = True


class ProcessTransport:
    """Run a simulator/native executable through the same line protocol as a board."""

    def __init__(self, command: list[str], timeout: float) -> None:
        if not command:
            raise ValueError("simulator command cannot be empty")
        self.command = command
        self.timeout = timeout
        self.process: subprocess.Popen[bytes] | None = None
        self.selector = selectors.DefaultSelector()
        self._start()

    def _start(self) -> None:
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        assert self.process.stdout is not None
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def write(self, value: bytes) -> int:
        if self.process is None or self.process.stdin is None:
            return 0
        self.process.stdin.write(value)
        self.process.stdin.flush()
        return len(value)

    def readline(self) -> bytes:
        if self.process is None or self.process.stdout is None:
            return b""
        if not self.selector.select(self.timeout):
            return b""
        return self.process.stdout.readline()

    def reset(self) -> None:
        self.close()
        self.selector = selectors.DefaultSelector()
        self._start()

    def close(self) -> None:
        if self.process is None:
            return
        process = self.process
        if process.stdout is not None:
            try:
                self.selector.unregister(process.stdout)
            except KeyError:
                pass
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        self.process = None
        self.selector.close()


@dataclass
class HardwareTestRunner:
    transport: Transport
    board: str
    rtos: str
    timeout: float = 5.0
    firmware_artifact: Path | None = None

    def run(self, rounds: int = 1, commands: list[str] | None = None) -> dict[str, Any]:
        commands = commands or DEFAULT_COMMANDS
        raw_lines: list[str] = []
        round_reports: list[dict[str, Any]] = []
        for round_number in range(1, rounds + 1):
            if hasattr(self.transport, "reset"):
                self.transport.reset()
            boot_started = time.monotonic()
            boot_event = self._wait_for(
                lambda event: event.get("event") == "boot",
                raw_lines,
                timeout=self.timeout,
            )
            boot_ms = round((time.monotonic() - boot_started) * 1000, 3)
            results: list[dict[str, Any]] = []
            for command in commands:
                request_id = uuid.uuid4().hex[:12]
                started = time.monotonic()
                self.transport.write(request_line(request_id, command))
                event = self._wait_for(
                    lambda item, request_id=request_id: item.get("request_id") == request_id,
                    raw_lines,
                    timeout=self.timeout,
                )
                results.append({
                    **(event or {
                        "request_id": request_id,
                        "command": command,
                        "status": "fail",
                        "reason": "host-timeout",
                    }),
                    "host_round_trip_ms": round((time.monotonic() - started) * 1000, 3),
                })
            round_reports.append({
                "round": round_number,
                "boot_success": boot_event is not None,
                "boot_time_ms": boot_ms if boot_event else None,
                "boot_event": boot_event,
                "commands": results,
            })
        return self._report(round_reports, raw_lines)

    def _wait_for(self, predicate: Any, raw_lines: list[str], timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.transport.readline()
            if not line:
                continue
            raw_lines.append(line.decode("utf-8", "replace").rstrip())
            event = parse_event(line)
            if event is not None and predicate(event):
                return event
        return None

    def _report(
        self,
        rounds: list[dict[str, Any]],
        raw_lines: list[str],
    ) -> dict[str, Any]:
        commands = [item for round_item in rounds for item in round_item["commands"]]
        applicable = [item for item in commands if item.get("status") != "unsupported"]
        passed = [item for item in applicable if item.get("status") == "pass"]
        boot_times = [item["boot_time_ms"] for item in rounds if item["boot_time_ms"] is not None]
        firmware = None
        if self.firmware_artifact is not None:
            firmware = {
                "path": str(self.firmware_artifact),
                "size": self.firmware_artifact.stat().st_size,
                "sha256": file_sha256(self.firmware_artifact),
            }
        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "board": self.board,
            "rtos": self.rtos,
            "firmware_artifact": firmware,
            "rounds": rounds,
            "raw_log": raw_lines,
            "summary": {
                "boot_successes": sum(item["boot_success"] for item in rounds),
                "boot_attempts": len(rounds),
                "boot_success_rate": round(
                    sum(item["boot_success"] for item in rounds) / len(rounds), 4
                ) if rounds else None,
                "boot_time_mean_ms": round(mean(boot_times), 3) if boot_times else None,
                "boot_time_min_ms": min(boot_times) if boot_times else None,
                "boot_time_max_ms": max(boot_times) if boot_times else None,
                "commands_passed": len(passed),
                "commands_applicable": len(applicable),
                "commands_total": len(commands),
                "command_pass_rate": round(len(passed) / len(applicable), 4)
                if applicable
                else None,
                "unsupported": sum(item.get("status") == "unsupported" for item in commands),
                "failed": sum(item.get("status") == "fail" for item in commands),
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BSPForge 跨 RTOS 实板/仿真回归工具")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--port")
    transport.add_argument("--command", help="以标准输入输出运行的仿真器命令")
    parser.add_argument("--board", required=True)
    parser.add_argument("--rtos", choices=["rtthread", "zephyr"], required=True)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--firmware",
        type=Path,
        help="记录本次已烧录固件的路径、大小和 SHA-256",
    )
    parser.add_argument(
        "--test-command",
        action="append",
        choices=DEFAULT_COMMANDS,
        dest="test_commands",
        help="仅运行指定协议命令；可重复提供，默认运行全部命令",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.firmware is not None and not args.firmware.is_file():
        parser.error(f"firmware artifact does not exist: {args.firmware}")
    active_transport: Transport = (
        SerialTransport(args.port, args.baudrate, args.timeout)
        if args.port
        else ProcessTransport(shlex.split(args.command), args.timeout)
    )
    try:
        report = HardwareTestRunner(
            active_transport,
            args.board,
            args.rtos,
            args.timeout,
            args.firmware,
        ).run(args.rounds, commands=args.test_commands)
    finally:
        active_transport.close()
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
