#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def openocd_command(args: argparse.Namespace) -> list[str]:
    command = [
        str(args.openocd),
        "-s", str(args.scripts),
        "-s", str(args.qspi_config.parent),
        "-c", f"set QSPI_FLASHLOADER {args.flash_loader.as_posix()}",
        "-c", "source [find interface/kitprog3.cfg]",
        "-c", "transport select swd",
        "-c", "set ENABLE_CM55 1",
        "-c", "source [find target/infineon/pse84xgxs2.cfg]",
    ]
    if args.action == "probe":
        command += ["-c", "init; flash banks; shutdown"]
    elif args.action == "reset":
        command += ["-c", "init; reset run; shutdown"]
    else:
        image = args.firmware.resolve().as_posix()
        command += [
            "-c",
            (
                "init; reset init; flash probe 0; flash probe 2; "
                f"flash write_image erase {{{image}}}; "
                f"verify_image {{{image}}}; reset run; shutdown"
            ),
        ]
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按 Infineon 配方探测、复位或烧录 PSoC Edge E84"
    )
    parser.add_argument("action", choices=["probe", "reset", "program"])
    parser.add_argument("--firmware", type=Path)
    parser.add_argument(
        "--openocd",
        type=Path,
        default=Path(os.environ.get("PSOC_OPENOCD", "openocd")),
    )
    parser.add_argument(
        "--scripts",
        type=Path,
        default=Path(os.environ.get("PSOC_OPENOCD_SCRIPTS", "scripts")),
    )
    parser.add_argument(
        "--flash-loader",
        type=Path,
        default=Path(os.environ.get("PSOC_E84_SMIF_FLM", "PSE84_SMIF.FLM")),
    )
    parser.add_argument("--qspi-config", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "program" and (
        args.firmware is None or not args.firmware.is_file()
    ):
        parser.error("program requires an existing --firmware file")
    for name in ("openocd", "scripts", "flash_loader", "qspi_config"):
        if not Path(getattr(args, name)).exists():
            parser.error(f"{name} does not exist: {getattr(args, name)}")

    process = subprocess.run(
        openocd_command(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    print(process.stdout, end="")
    if process.returncode != 0:
        return process.returncode
    lowered = process.stdout.lower()
    if "error:" in lowered or "failed" in lowered:
        return 2
    if args.action == "program" and "wrote 0 bytes" in lowered:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
