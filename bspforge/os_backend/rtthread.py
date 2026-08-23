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
from bspforge.os_backend.artifact_verifier import FirmwareArtifactVerifier
from bspforge.os_backend.native_binding import NativeDriverBindingTracer
from bspforge.os_backend.profiles import sdk_profile
from bspforge.os_backend.rtthread_binding import RTThreadBindingGenerator
from bspforge.os_backend.rtthread_device import RTThreadDeviceModelGenerator
from bspforge.os_backend.rtthread_validation import RTThreadValidationGenerator


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
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options = options or {}
        profile_name = options.get("sdk_profile", "k210")
        profile = sdk_profile(profile_name)
        rtthread_root = rtthread_root.resolve()
        project_template = options.get("project_template")
        if project_template:
            self._materialize_external_project(
                Path(project_template), rtthread_root, output, options
            )
            generated_bsp = output
        else:
            source_bsp = rtthread_root / "bsp" / board
            if not source_bsp.is_dir():
                raise FileNotFoundError(f"RT-Thread BSP does not exist: {source_bsp}")
            self._materialize_build_tree(rtthread_root, board, output)
            generated_bsp = output / "bsp" / board

        metadata = generated_bsp / "bspforge"
        metadata.mkdir(parents=True, exist_ok=True)
        strategy = options.get(
            "binding_strategy",
            "generated-sdk-adapter" if profile_name == "k210" else "native-driver-trace",
        )
        adapter: Path | None = None
        if strategy == "generated-sdk-adapter":
            binding_manifest = RTThreadBindingGenerator().generate(
                generated_bsp / "board", ir, resolution
            )
            device_manifest = RTThreadDeviceModelGenerator().generate(
                generated_bsp, binding_manifest, options.get("devices")
            )
            sdk_package = self._install_sdk_input(
                generated_bsp,
                Path(ir["sdk"]["root"]),
                closure,
                binding_manifest["required_sources"],
                profile_name,
            )
            adapter = generated_bsp / "board" / "bspforge_sdk_adapter.c"
            adapter.write_text(self._adapter_source(resolution), encoding="utf-8")
        elif strategy == "native-driver-trace":
            if profile_name == "stm32f103":
                sdk_package = self._install_sdk_input(
                    generated_bsp, Path(ir["sdk"]["root"]), closure, [], profile_name
                )
            else:
                sdk_package = Path(ir["sdk"]["root"])
            driver_roots = [
                generated_bsp / "board",
                generated_bsp / "drivers",
                generated_bsp / "applications",
            ]
            driver_roots.extend(
                self._option_paths(options.get("native_driver_roots", []), output)
            )
            binding_manifest = NativeDriverBindingTracer().generate(
                ir, profile_name, "rtthread", driver_roots
            )
            device_manifest = RTThreadValidationGenerator().generate(
                generated_bsp, options.get("validation")
            )
        else:
            raise ValueError(f"Unsupported RT-Thread binding strategy: {strategy}")

        write_json(metadata / "sdk-ir.json", ir)
        write_json(metadata / "semantic-resolution.json", resolution)
        write_json(metadata / "build-closure.json", closure)
        write_json(metadata / "functional-bindings.json", binding_manifest)
        write_json(metadata / "device-model.json", device_manifest)

        default_prefix = "riscv-none-embed-" if profile["architecture"] == "riscv64" else "arm-none-eabi-"
        self._make_prefix_configurable(generated_bsp / "rtconfig.py", default_prefix)
        self._enable_rtthread_features(
            generated_bsp / "rtconfig.h",
            device_manifest["required_rtthread_features"],
        )

        device_sources = device_manifest.get("sources", [device_manifest.get("source")])
        device_sources = [item for item in device_sources if item]
        artifacts = options.get("artifacts", {
            "elf": "rtthread.elf" if profile_name == "k210" else "rt-thread.elf",
            "bin": "rtthread.bin" if profile_name == "k210" else "rt-thread.bin",
        })
        manifest = {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "backend": "rtthread",
            "board": board,
            "sdk_profile": profile_name,
            "binding_strategy": strategy,
            "rtthread_root": str(rtthread_root),
            "rtthread_revision": self._git_revision(rtthread_root),
            "project_root": str(output),
            "bsp_path": str(generated_bsp),
            "adapter": str(adapter.relative_to(output)) if adapter else None,
            "adapter_sha256": file_sha256(adapter) if adapter else None,
            "functional_bindings": {
                "source": self._relative_or_none(binding_manifest.get("source"), output),
                "header": self._relative_or_none(binding_manifest.get("header"), output),
                "manifest": str((metadata / "functional-bindings.json").relative_to(output)),
                "summary": binding_manifest["summary"],
            },
            "device_model": {
                "manifest": str((metadata / "device-model.json").relative_to(output)),
                "sources": [
                    self._relative_or_absolute(Path(path), output)
                    for path in device_sources
                ],
                "operation_tables": device_manifest["operation_tables"],
                "registration_symbols": device_manifest["registration_symbols"],
                "summary": device_manifest["summary"],
            },
            "sdk_package": self._relative_or_absolute(sdk_package, output),
            "sdk_digest": ir["sdk"]["digest"],
            "sdk_materialization": "copied-from-analyzed-input",
            "mapping_count": len(resolution["mappings"]),
            "resolved_count": resolution["summary"]["resolved"],
            "closure_files": closure["summary"]["files"],
            "expected_machine": profile["machine"],
            "artifacts": artifacts,
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
        profile_name: str,
    ) -> Path:
        """Replace the baseline package payload with the SDK snapshot just analyzed."""
        if profile_name == "stm32f103":
            return RTThreadBackend._install_stm32_sdk(generated_bsp, sdk_root, closure)
        if profile_name != "k210":
            raise ValueError(f"No RT-Thread SDK materializer for profile: {profile_name}")
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
    def _install_stm32_sdk(
        generated_bsp: Path, sdk_root: Path, closure: dict[str, Any]
    ) -> Path:
        packages = generated_bsp / "packages"
        packages.mkdir(parents=True, exist_ok=True)
        cmsis_core = packages / "CMSIS-Core-latest"
        cmsis_device = packages / "stm32f1_cmsis_driver-latest"
        hal = packages / "stm32f1_hal_driver-latest"
        copytree_filtered(sdk_root / "Drivers" / "CMSIS" / "Include", cmsis_core / "Include")
        copytree_filtered(
            sdk_root / "Drivers" / "CMSIS" / "Device" / "ST" / "STM32F1xx",
            cmsis_device,
        )
        copytree_filtered(sdk_root / "Drivers" / "STM32F1xx_HAL_Driver", hal)
        (cmsis_core / "SConscript").write_text(RTThreadBackend._cmsis_core_sconscript(), encoding="utf-8")
        (cmsis_device / "SConscript").write_text(
            RTThreadBackend._stm32_cmsis_sconscript(), encoding="utf-8"
        )
        (hal / "SConscript").write_text(RTThreadBackend._stm32_hal_sconscript(), encoding="utf-8")
        (packages / "SConscript").write_text(
            "import os\nfrom building import *\nobjs = []\ncwd = GetCurrentDir()\n"
            "for item in os.listdir(cwd):\n"
            "    script = os.path.join(cwd, item, 'SConscript')\n"
            "    if os.path.isfile(script):\n        objs += SConscript(script)\n"
            "Return('objs')\n",
            encoding="utf-8",
        )
        write_json(packages / "bspforge-input.json", {
            "sdk_id": closure["sdk_id"],
            "closure_id": closure["id"],
            "profile": "stm32f103",
            "materialized_assets": [
                "Drivers/CMSIS/Include",
                "Drivers/CMSIS/Device/ST/STM32F1xx",
                "Drivers/STM32F1xx_HAL_Driver",
            ],
            "note": "Package payloads are copied from the analyzed STM32CubeF1 input.",
        })
        return packages

    @staticmethod
    def _cmsis_core_sconscript() -> str:
        return """from building import *
import os
cwd = GetCurrentDir()
group = DefineGroup('CMSIS-Core', [], depend=['PKG_USING_CMSIS_CORE'], CPPPATH=[os.path.join(cwd, 'Include')])
Return('group')
"""

    @staticmethod
    def _stm32_cmsis_sconscript() -> str:
        return """from building import *
import os
Import('env')
cwd = GetCurrentDir()
path = [os.path.join(cwd, 'Include')]
src = [os.path.join(cwd, 'Source', 'Templates', 'system_stm32f1xx.c')]
startup = {'STM32F103xB': 'startup_stm32f103xb.s', 'STM32F103xE': 'startup_stm32f103xe.s'}
defines = [item[0] if isinstance(item, tuple) else item for item in env.get('CPPDEFINES', [])]
for mcu, filename in startup.items():
    if mcu in defines:
        src.append(os.path.join(cwd, 'Source', 'Templates', 'gcc', filename))
        break
group = DefineGroup('STM32F1-CMSIS', src, depend=['PKG_USING_STM32F1_CMSIS_DRIVER'], CPPPATH=path)
Return('group')
"""

    @staticmethod
    def _stm32_hal_sconscript() -> str:
        return """from building import *
import os
cwd = GetCurrentDir()
src_path = os.path.join(cwd, 'Src')
names = ['stm32f1xx_hal.c', 'stm32f1xx_hal_cortex.c', 'stm32f1xx_hal_dma.c',
         'stm32f1xx_hal_gpio.c', 'stm32f1xx_hal_gpio_ex.c', 'stm32f1xx_hal_pwr.c',
         'stm32f1xx_hal_rcc.c', 'stm32f1xx_hal_rcc_ex.c', 'stm32f1xx_hal_uart.c',
         'stm32f1xx_hal_usart.c']
src = [os.path.join(src_path, name) for name in names]
group = DefineGroup('STM32F1-HAL', src, depend=['PKG_USING_STM32F1_HAL_DRIVER'],
                    CPPPATH=[os.path.join(cwd, 'Inc')], CPPDEFINES=['USE_HAL_DRIVER'])
Return('group')
"""

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
        board_family = Path(board).parent
        shared_libraries = rtthread_root / "bsp" / board_family / "libraries"
        if board_family != Path(".") and shared_libraries.is_dir():
            RTThreadBackend._link_or_copy(
                shared_libraries, output / "bsp" / board_family / "libraries"
            )

    @staticmethod
    def _materialize_external_project(
        project_template: Path,
        rtthread_root: Path,
        output: Path,
        options: dict[str, Any],
    ) -> None:
        project_template = project_template.resolve()
        if not (project_template / "SConstruct").is_file():
            raise FileNotFoundError(f"RT-Thread project template is invalid: {project_template}")
        marker = output / ".bspforge-generated"
        if output.exists():
            if not marker.exists():
                raise RuntimeError(f"Refusing to replace non-BSPForge directory: {output}")
            shutil.rmtree(output)
        copytree_filtered(project_template, output)
        marker.write_text("generated RT-Thread external project\n", encoding="utf-8")
        RTThreadBackend._link_or_copy(rtthread_root, output / "rt-thread")
        for key, destination in (("libraries_root", "libraries"), ("libs_root", "libs")):
            value = options.get(key)
            if value:
                RTThreadBackend._link_or_copy(Path(value), output / destination)

    @staticmethod
    def _link_or_copy(source: Path, destination: Path) -> None:
        source = source.resolve()
        if destination.exists() or destination.is_symlink():
            return
        try:
            destination.symlink_to(source, target_is_directory=True)
        except OSError:
            copytree_filtered(source, destination)

    def build(self, project: Path, toolchain_bin: Path, jobs: int = 1) -> tuple[int, str]:
        manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
        bsp = Path(manifest["bsp_path"])
        environment = os.environ.copy()
        for name in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
            environment.pop(name, None)
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

    def verify(self, project: Path, toolchain_bin: Path) -> dict[str, Any]:
        manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
        expected = [
            *manifest["device_model"]["operation_tables"],
            *manifest["device_model"]["registration_symbols"],
        ]
        artifacts = manifest["artifacts"]
        return FirmwareArtifactVerifier().verify(
            Path(manifest["bsp_path"]),
            toolchain_bin,
            self._detect_prefix(toolchain_bin),
            expected,
            elf_name=artifacts["elf"],
            binary_name=artifacts.get("bin"),
            expected_machine=manifest["expected_machine"],
        )

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
    def _make_prefix_configurable(path: Path, default_prefix: str) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        replacement = f"PREFIX  = os.getenv('BSPFORGE_TOOLCHAIN_PREFIX', '{default_prefix}')"
        text, count = re.subn(r"PREFIX\s*=\s*['\"][^'\"]+['\"]", replacement, text, count=1)
        if count != 1:
            raise RuntimeError(f"Could not locate toolchain PREFIX in {path}")
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _enable_rtthread_features(path: Path, features: list[str]) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [feature for feature in features if f"#define {feature}" not in text]
        if not missing:
            return
        marker = "/* Device Drivers */"
        declarations = "\n".join(f"#define {feature}" for feature in missing)
        if marker in text:
            text = text.replace(marker, f"{marker}\n\n{declarations}", 1)
        else:
            text = f"{text.rstrip()}\n\n{declarations}\n"
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _detect_prefix(toolchain_bin: Path) -> str:
        for prefix in (
            "riscv-none-embed-",
            "riscv-none-elf-",
            "riscv64-unknown-elf-",
            "arm-none-eabi-",
        ):
            if (toolchain_bin / f"{prefix}gcc").exists():
                return prefix
        raise FileNotFoundError(f"No supported cross GCC found in {toolchain_bin}")

    @staticmethod
    def _option_paths(values: list[str], output: Path) -> list[Path]:
        paths: list[Path] = []
        for value in values:
            path = Path(value).expanduser()
            paths.append(path if path.is_absolute() else output / path)
        return paths

    @staticmethod
    def _relative_or_absolute(path: Path, root: Path) -> str:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _relative_or_none(value: str | None, root: Path) -> str | None:
        if not value:
            return None
        return RTThreadBackend._relative_or_absolute(Path(value), root)
