from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bspforge.common import copytree_filtered, file_sha256, utc_now, write_json
from bspforge.os_backend.base import OSBackend
from bspforge.os_backend.rtthread_binding import RTThreadBindingGenerator


class RTThreadBackend(OSBackend):
    """Materialize and validate an isolated RT-Thread native BSP tree."""

    def generate(
        self,
        rtthread_root: Path,
        board: str,
        output: Path,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        closure: dict[str, Any],
    ) -> dict[str, Any]:
        rtthread_root = rtthread_root.resolve()
        source_bsp = rtthread_root / "bsp" / board
        if not source_bsp.is_dir():
            raise FileNotFoundError(f"RT-Thread BSP does not exist: {source_bsp}")

        self._materialize_build_tree(rtthread_root, board, output)
        generated_bsp = output / "bsp" / board
        metadata = generated_bsp / "bspforge"
        metadata.mkdir(parents=True, exist_ok=True)
        binding_manifest = RTThreadBindingGenerator().generate(
            generated_bsp / "board", ir, resolution
        )
        sdk_package = self._install_sdk_input(
            generated_bsp,
            Path(ir["sdk"]["root"]),
            closure,
            binding_manifest["required_sources"],
        )
        write_json(metadata / "sdk-ir.json", ir)
        write_json(metadata / "semantic-resolution.json", resolution)
        write_json(metadata / "build-closure.json", closure)
        write_json(metadata / "functional-bindings.json", binding_manifest)

        adapter = generated_bsp / "board" / "bspforge_sdk_adapter.c"
        adapter.write_text(self._adapter_source(resolution), encoding="utf-8")
        self._make_prefix_configurable(generated_bsp / "rtconfig.py")

        manifest = {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "backend": "rtthread",
            "board": board,
            "rtthread_root": str(rtthread_root),
            "rtthread_revision": self._git_revision(rtthread_root),
            "project_root": str(output),
            "bsp_path": str(generated_bsp),
            "adapter": str(adapter.relative_to(output)),
            "adapter_sha256": file_sha256(adapter),
            "functional_bindings": {
                "source": str(Path(binding_manifest["source"]).relative_to(output)),
                "header": str(Path(binding_manifest["header"]).relative_to(output)),
                "manifest": str((metadata / "functional-bindings.json").relative_to(output)),
                "summary": binding_manifest["summary"],
            },
            "sdk_package": str(sdk_package.relative_to(output)),
            "sdk_digest": ir["sdk"]["digest"],
            "sdk_materialization": "copied-from-analyzed-input",
            "mapping_count": len(resolution["mappings"]),
            "resolved_count": resolution["summary"]["resolved"],
            "closure_files": closure["summary"]["files"],
            "build_command": ["scons", "--exec-path=<toolchain-bin>"],
        }
        write_json(metadata / "generation-manifest.json", manifest)
        return manifest

    @staticmethod
    def _git_revision(root: Path) -> str:
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return "unknown"

    @staticmethod
    def _install_sdk_input(
        generated_bsp: Path,
        sdk_root: Path,
        closure: dict[str, Any],
        binding_sources: list[str],
    ) -> Path:
        """Replace the baseline package payload with the SDK snapshot just analyzed."""
        package = generated_bsp / "packages" / "K210-SDK-latest"
        integration = package / "SConscript"
        scons_text = integration.read_text(encoding="utf-8", errors="replace") if integration.exists() else ""
        copytree_filtered(sdk_root.resolve(), package)
        if not scons_text:
            sources = [
                item["path"]
                for item in closure["selected_files"]
                if item["kind"] in {"source", "startup", "assembly"}
            ]
            includes = sorted({str(Path(item["path"]).parent) for item in closure["selected_files"] if item["kind"] == "header"})
            scons_text = (
                "from building import *\n"
                "cwd = GetCurrentDir()\n"
                "src = Split('''\n%s\n''')\n"
                "CPPPATH = [cwd + '/%s']\n"
                "group = DefineGroup('BSPForge-SDK', src, depend=[''], CPPPATH=CPPPATH)\n"
                "Return('group')\n"
            ) % ("\n".join(sources), "', cwd + '/".join(includes))
        else:
            repair_sources = closure.get("repair_sources", [])
            additions = sorted({*binding_sources, *repair_sources})
            additions = [source for source in additions if source not in scons_text]
            if additions:
                declaration = "\n# BSPForge：功能绑定与诊断修复所需源码\nsrc += Split('''\n%s\n''')\n" % "\n".join(additions)
                marker = "group = DefineGroup("
                if marker not in scons_text:
                    raise RuntimeError("无法在 SDK SConscript 中定位 DefineGroup")
                scons_text = scons_text.replace(marker, declaration + "\n" + marker, 1)
            include_dirs = [item for item in closure.get("repair_include_dirs", []) if item]
            if include_dirs:
                paths = ", ".join("cwd + '/%s'" % item for item in sorted(set(include_dirs)))
                marker = "group = DefineGroup("
                scons_text = scons_text.replace(marker, "CPPPATH += [%s]\n\n%s" % (paths, marker), 1)
        integration.write_text(scons_text, encoding="utf-8")
        write_json(package / "bspforge-input.json", {
            "sdk_id": closure["sdk_id"],
            "closure_id": closure["id"],
            "selected_files": len(closure["selected_files"]),
            "binding_sources": sorted(binding_sources),
            "repair_sources": sorted(closure.get("repair_sources", [])),
            "repair_include_dirs": sorted(closure.get("repair_include_dirs", [])),
            "note": "Payload copied from the analyzed SDK; SConscript is the RT-Thread integration contract.",
        })
        return package

    @staticmethod
    def _materialize_build_tree(rtthread_root: Path, board: str, output: Path) -> None:
        """Create an isolated BSP while linking immutable upstream RTOS sources."""
        marker = output / ".bspforge-generated"
        if output.exists():
            if not marker.exists():
                raise RuntimeError(f"Refusing to replace non-BSPForge directory: {output}")
            shutil.rmtree(output)
        output.mkdir(parents=True)
        marker.write_text("generated RT-Thread build tree\n", encoding="utf-8")

        for child in rtthread_root.iterdir():
            if child.name in {".git", "bsp"}:
                continue
            destination = output / child.name
            if child.is_dir():
                try:
                    destination.symlink_to(child.resolve(), target_is_directory=True)
                except OSError:
                    # Windows without Developer Mode may reject directory links.
                    copytree_filtered(child, destination)
            elif child.suffix not in {".o", ".elf", ".bin", ".map", ".pyc"}:
                shutil.copy2(child, destination)

        (output / "bsp").mkdir()
        copytree_filtered(rtthread_root / "bsp" / board, output / "bsp" / board)

    def build(self, project: Path, toolchain_bin: Path, jobs: int = 1) -> tuple[int, str]:
        manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
        bsp = Path(manifest["bsp_path"])
        environment = os.environ.copy()
        environment["RTT_EXEC_PATH"] = str(toolchain_bin.resolve())
        environment["BSPFORGE_TOOLCHAIN_PREFIX"] = self._detect_prefix(toolchain_bin)
        command = ["scons", f"--exec-path={toolchain_bin.resolve()}", f"-j{max(1, jobs)}"]
        process = subprocess.run(
            command,
            cwd=bsp,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
        )
        return process.returncode, process.stdout

    @staticmethod
    def _adapter_source(resolution: dict[str, Any]) -> str:
        rows: list[str] = []
        for mapping in resolution["mappings"]:
            symbols = ",".join(item["symbol"] for item in mapping["accepted"][:4]) or "unresolved"
            rows.append(
                '    {"%s", "%s", "%s"},'
                % (mapping["capability"], mapping["target_api"], symbols)
            )
        return """/* Generated by BSPForge. Evidence is in bspforge/semantic-resolution.json. */
#include <rtthread.h>

struct bspforge_mapping
{
    const char *capability;
    const char *target_contract;
    const char *sdk_symbols;
};

static const struct bspforge_mapping bspforge_mappings[] =
{
%s
};

int bspforge_mapping_count(void)
{
    return (int)(sizeof(bspforge_mappings) / sizeof(bspforge_mappings[0]));
}
""" % "\n".join(rows)

    @staticmethod
    def _make_prefix_configurable(path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        replacement = "PREFIX  = os.getenv('BSPFORGE_TOOLCHAIN_PREFIX', 'riscv-none-embed-')"
        text, count = re.subn(r"PREFIX\s*=\s*['\"][^'\"]+['\"]", replacement, text, count=1)
        if count != 1:
            raise RuntimeError(f"Could not locate toolchain PREFIX in {path}")
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _detect_prefix(toolchain_bin: Path) -> str:
        for prefix in ("riscv-none-embed-", "riscv-none-elf-", "riscv64-unknown-elf-"):
            if (toolchain_bin / f"{prefix}gcc").exists():
                return prefix
        raise FileNotFoundError(f"No supported RISC-V GCC found in {toolchain_bin}")
