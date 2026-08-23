from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now


class FirmwareArtifactVerifier:
    """Validate firmware artifacts and generated symbols after a successful link."""

    def verify(
        self,
        bsp: Path,
        toolchain_bin: Path,
        toolchain_prefix: str,
        expected_symbols: list[str],
        *,
        elf_name: str = "rtthread.elf",
        binary_name: str | None = "rtthread.bin",
        expected_machine: str = "RISC-V",
    ) -> dict[str, Any]:
        elf = bsp / elf_name
        binary = bsp / binary_name if binary_name else None
        checks: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []

        candidates = [("elf", elf)]
        if binary is not None:
            image_kind = binary.suffix.lower().lstrip(".") or "bin"
            candidates.append((image_kind, binary))
        for kind, path in candidates:
            exists = path.is_file() and path.stat().st_size > 0
            checks.append({"name": f"{kind}-exists", "success": exists})
            if exists:
                artifacts.append({
                    "kind": kind,
                    "path": str(path),
                    "size": path.stat().st_size,
                    "sha256": file_sha256(path),
                })

        elf_header: dict[str, str] = {}
        size: dict[str, int] = {}
        present_symbols: list[str] = []
        missing_symbols = list(expected_symbols)
        if elf.is_file():
            readelf = self._run(toolchain_bin / f"{toolchain_prefix}readelf", ["-h", str(elf)])
            elf_header = self._parse_elf_header(readelf)
            architecture_ok = expected_machine.lower() in elf_header.get("Machine", "").lower()
            checks.append({
                "name": "elf-machine",
                "success": architecture_ok,
                "expected": expected_machine,
                "observed": elf_header.get("Machine", "unknown"),
            })

            size_output = self._run(toolchain_bin / f"{toolchain_prefix}size", [str(elf)])
            size = self._parse_size(size_output)
            checks.append({"name": "elf-sections-readable", "success": bool(size)})

            nm_output = self._run(
                toolchain_bin / f"{toolchain_prefix}nm", ["--defined-only", str(elf)]
            )
            defined = {
                line.split()[-1]
                for line in nm_output.splitlines()
                if len(line.split()) >= 2
            }
            present_symbols = sorted(set(expected_symbols).intersection(defined))
            missing_symbols = sorted(set(expected_symbols).difference(defined))
            checks.append({
                "name": "generated-device-symbols-linked",
                "success": not missing_symbols,
                "expected": sorted(expected_symbols),
                "present": present_symbols,
                "missing": missing_symbols,
            })

        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "success": all(item["success"] for item in checks),
            "checks": checks,
            "artifacts": artifacts,
            "elf_header": elf_header,
            "section_sizes": size,
            "expected_symbols": sorted(expected_symbols),
            "present_symbols": present_symbols,
            "missing_symbols": missing_symbols,
            "expected_machine": expected_machine,
        }

    @staticmethod
    def _run(executable: Path, arguments: list[str]) -> str:
        if not executable.is_file():
            return ""
        try:
            return subprocess.check_output(
                [str(executable), *arguments],
                text=True,
                stderr=subprocess.STDOUT,
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return ""

    @staticmethod
    def _parse_elf_header(output: str) -> dict[str, str]:
        wanted = {"Class", "Data", "Type", "Machine", "Entry point address"}
        result: dict[str, str] = {}
        for line in output.splitlines():
            match = re.match(r"\s*([^:]+):\s*(.+)$", line)
            if match and match.group(1).strip() in wanted:
                result[match.group(1).strip()] = match.group(2).strip()
        return result

    @staticmethod
    def _parse_size(output: str) -> dict[str, int]:
        lines = [line.split() for line in output.splitlines() if line.strip()]
        if len(lines) < 2:
            return {}
        header = lines[-2]
        values = lines[-1]
        if len(header) < 4 or len(values) < 4:
            return {}
        result: dict[str, int] = {}
        for name, value in zip(header[:4], values[:4]):
            try:
                result[name] = int(value, 0)
            except ValueError:
                return {}
        return result
