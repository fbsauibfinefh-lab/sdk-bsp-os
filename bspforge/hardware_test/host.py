from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Protocol

from bspforge.common import utc_now, write_json
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


@dataclass
class HardwareTestRunner:
    transport: Transport
    board: str
    rtos: str
    timeout: float = 5.0

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
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "board": self.board,
            "rtos": self.rtos,
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
    parser = argparse.ArgumentParser(description="BSPForge 跨 RTOS 实板回归工具")
    parser.add_argument("--port", required=True)
    parser.add_argument("--board", required=True)
    parser.add_argument("--rtos", choices=["rtthread", "zephyr"], required=True)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    transport = SerialTransport(args.port, args.baudrate, args.timeout)
    try:
        report = HardwareTestRunner(
            transport, args.board, args.rtos, args.timeout
        ).run(args.rounds)
    finally:
        transport.close()
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
