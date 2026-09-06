#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


DEFAULT_JLINK = Path(
    os.environ.get("JLINK_EXE", r"C:\Program Files\SEGGER\JLink_V910\JLink.exe")
)


def commander_script(
    action: str,
    firmware: Path | None,
    addresses: list[str] | None = None,
    no_reset: bool = False,
) -> str:
    commands = ["halt"] if action == "read" and no_reset else ["reset", "halt"]
    if action == "probe":
        commands.append("mem32 0xE0042000, 1")
    elif action == "read":
        commands.extend(f"mem32 {address}, 1" for address in addresses or [])
    elif action == "program":
        assert firmware is not None
        image = str(firmware.resolve())
        commands.extend([
            f"loadbin {image} 0x08000000",
            f"verifybin {image}, 0x08000000",
        ])
    if action in {"probe", "reset", "program"}:
        commands.append("reset")
    commands.extend(["go", "exit"])
    return "\n".join(commands) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="使用 J-Link 探测、复位或烧录 STM32F103ZE"
    )
    parser.add_argument("action", choices=["probe", "read", "reset", "program"])
    parser.add_argument("--firmware", type=Path)
    parser.add_argument(
        "--address",
        action="append",
        default=[],
        help="read action 的 32 位寄存器地址；可重复提供",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="read action 直接暂停当前程序，不先复位",
    )
    parser.add_argument("--jlink", type=Path, default=DEFAULT_JLINK)
    parser.add_argument("--device", default="STM32F103ZE")
    parser.add_argument("--speed", type=int, default=4000)
    args = parser.parse_args()
    if args.action == "program" and (
        args.firmware is None or not args.firmware.is_file()
    ):
        parser.error("program requires an existing --firmware file")
    if args.action == "read" and not args.address:
        parser.error("read requires at least one --address")
    if not args.jlink.is_file():
        parser.error(f"J-Link executable does not exist: {args.jlink}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jlink", encoding="ascii", delete=False
    ) as handle:
        handle.write(commander_script(
            args.action, args.firmware, args.address, args.no_reset
        ))
        script = Path(handle.name)
    try:
        process = subprocess.run(
            [
                str(args.jlink),
                "-NoGui", "1",
                "-Device", args.device,
                "-If", "SWD",
                "-Speed", str(args.speed),
                "-AutoConnect", "1",
                "-CommanderScript", str(script),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    finally:
        script.unlink(missing_ok=True)
    print(process.stdout, end="")
    lowered = process.stdout.lower()
    if (
        process.returncode != 0
        or "cannot connect" in lowered
        or "error while parsing" in lowered
        or "failed" in lowered
    ):
        return process.returncode or 2
    if args.action == "program" and (
        "verifying flash" not in lowered and "verify successful" not in lowered
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
