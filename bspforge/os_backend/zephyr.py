from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, utc_now, write_json
from bspforge.os_backend.artifact_verifier import FirmwareArtifactVerifier
from bspforge.os_backend.base import OSBackend
from bspforge.os_backend.native_binding import NativeDriverBindingTracer
from bspforge.os_backend.profiles import sdk_profile
from bspforge.os_backend.zephyr_binding import ZephyrBindingGenerator
from bspforge.os_backend.zephyr_device import ZephyrDeviceModelGenerator
from bspforge.os_backend.zephyr_validation import ZephyrValidationGenerator


class ZephyrBackend(OSBackend):
    """Generate an isolated Zephyr application and build it with west/CMake."""

    def generate(
        self,
        zephyr_root: Path,
        board: str,
        output: Path,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        closure: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options = options or {}
        zephyr_root = zephyr_root.resolve()
        if not (zephyr_root / "CMakeLists.txt").is_file():
            raise FileNotFoundError(f"Zephyr source tree is invalid: {zephyr_root}")
        self._prepare_output(output)
        app = output / "app"
        source_dir = app / "src"
        metadata = app / "bspforge"
        source_dir.mkdir(parents=True)
        metadata.mkdir(parents=True)

        profile_name = options["sdk_profile"]
        profile = sdk_profile(profile_name)
        binding_plan = options.get("_binding_plan")
        strategy = options.get("binding_strategy", "native-driver-trace")
        validation_options = dict(options.get("validation", {}))
        build_id = str(
            validation_options.get("firmware_build_id", ir["sdk"]["digest"][:12])
        )
        if strategy == "generated-sdk-adapter":
            binding_manifest = ZephyrBindingGenerator().generate(
                source_dir, ir, binding_plan, options
            )
            device_manifest = ZephyrDeviceModelGenerator().generate(
                source_dir, options
            )
        elif strategy == "native-driver-trace":
            binding_manifest = None
            device_manifest = None
        else:
            raise ValueError(f"Unsupported Zephyr binding strategy: {strategy}")
        protocol_manifest = ZephyrValidationGenerator().generate(
            source_dir,
            board,
            build_id,
            functional=strategy == "generated-sdk-adapter",
            native_devices=strategy == "generated-sdk-adapter",
        )
        source = Path(protocol_manifest["source"])
        (app / "CMakeLists.txt").write_text(
            self._cmake_source(
                Path(ir["sdk"]["root"]),
                binding_manifest.get("required_sources", []) if binding_manifest else [],
                binding_manifest is not None,
                device_manifest is not None,
            ),
            encoding="utf-8",
        )
        (app / "prj.conf").write_text(
            self._project_config(
                options.get("native_executable", False),
                device_manifest is not None,
            ),
            encoding="utf-8",
        )
        overlay = options.get("overlay")
        if overlay:
            (app / "app.overlay").write_text(str(overlay).rstrip() + "\n", encoding="utf-8")

        board_port = options.get("board_port")
        cmake_args = list(options.get("cmake_args", []))
        if board_port:
            self._install_board_port(Path(board_port), app)
            cmake_args.extend([f"-DBOARD_ROOT={app}", f"-DSOC_ROOT={app}"])
        if options.get("objcopy_in_place_workaround", False):
            wrapper = app / "bspforge_objcopy.py"
            wrapper.write_text(self._objcopy_wrapper(), encoding="utf-8")
            wrapper.chmod(0o755)
            cmake_args.append(f"-DCMAKE_OBJCOPY={wrapper}")

        driver_roots = [
            zephyr_root.parent / item for item in options.get("native_driver_roots", [])
        ] or [zephyr_root / "drivers"]
        if board_port:
            driver_roots.extend([app / "soc", app / "boards"])
        provider_roots = [
            zephyr_root.parent / item for item in options.get("native_provider_roots", [])
        ]
        # Build-specific driver references are refreshed from build.ninja after linking.
        if binding_manifest is None:
            binding_manifest = NativeDriverBindingTracer().generate(
                ir,
                profile_name,
                "zephyr",
                [],
                provider_roots,
                binding_plan=binding_plan,
            )
        if device_manifest is None:
            devices = [
                {"class": "serial", "source": "zephyr,console", "operations": ["poll_out"]},
                {"class": "gpio", "source": "led0", "operations": ["configure", "toggle"]},
                {"class": "timer", "source": "k_timer", "operations": ["init", "start"]},
            ]
            device_manifest = {
                "schema_version": "1.0",
                "created_at": utc_now(),
                "backend": "zephyr",
                "strategy": "zephyr-devicetree-native-model",
                "devices": devices,
                "sources": [protocol_manifest["source"]],
                "operation_tables": [],
                "registration_symbols": protocol_manifest["registration_symbols"],
                "summary": {"devices": len(devices), "generated_sources": 1},
            }
        else:
            device_manifest["sources"] = sorted(set(
                device_manifest["sources"] + [protocol_manifest["source"]]
            ))
            device_manifest["registration_symbols"] = sorted(set(
                device_manifest["registration_symbols"]
                + protocol_manifest["registration_symbols"]
            ))
            device_manifest["selftest_protocol"] = {
                "version": protocol_manifest["protocol_version"],
                "strategy": protocol_manifest["strategy"],
                "source": protocol_manifest["source"],
            }
            device_manifest["summary"]["generated_sources"] = 3
        write_json(metadata / "sdk-ir.json", ir)
        write_json(metadata / "semantic-resolution.json", resolution)
        if binding_plan is not None:
            write_json(metadata / "canonical-binding-plan.json", binding_plan)
        write_json(metadata / "build-closure.json", closure)
        write_json(metadata / "functional-bindings.json", binding_manifest)
        write_json(metadata / "device-model.json", device_manifest)

        revision = self._git_revision(zephyr_root)
        manifest = {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "backend": "zephyr",
            "board": board,
            "sdk_profile": profile_name,
            "binding_strategy": strategy,
            "zephyr_root": str(zephyr_root),
            "zephyr_revision": revision,
            "project_root": str(output),
            "bsp_path": str(app),
            "build_path": str(output / "build"),
            "adapter": str(source.relative_to(output)),
            "adapter_sha256": file_sha256(source),
            "functional_bindings": {
                "source": self._relative_or_none(binding_manifest.get("source"), output),
                "header": self._relative_or_none(binding_manifest.get("header"), output),
                "manifest": str((metadata / "functional-bindings.json").relative_to(output)),
                "summary": binding_manifest["summary"],
            },
            "device_model": {
                "manifest": str((metadata / "device-model.json").relative_to(output)),
                "sources": [
                    self._relative_or_none(item, output)
                    for item in device_manifest["sources"]
                ],
                "operation_tables": device_manifest["operation_tables"],
                "registration_symbols": device_manifest["registration_symbols"],
                "summary": device_manifest["summary"],
            },
            "sdk_package": str(Path(ir["sdk"]["root"])),
            "sdk_digest": ir["sdk"]["digest"],
            "sdk_materialization": (
                "analyzed-read-only-input-compiled-by-generated-adapter"
                if strategy == "generated-sdk-adapter"
                else "analyzed-read-only-input-with-native-hal-module"
            ),
            "mapping_count": len(resolution["mappings"]),
            "resolved_count": resolution["summary"]["resolved"],
            "binding_plan": binding_plan["summary"] if binding_plan else None,
            "closure_files": closure["summary"]["files"],
            "expected_machine": profile["machine"],
            "artifacts": {
                "elf": "build/zephyr/zephyr.elf",
                "bin": None if options.get("native_executable", False) else "build/zephyr/zephyr.bin",
                "executable": "build/zephyr/zephyr.exe" if options.get("native_executable", False) else None,
            },
            "toolchain_variant": options.get("toolchain_variant", "gnuarmemb"),
            "cmake_args": cmake_args,
            "native_driver_roots": [str(path.resolve()) for path in driver_roots],
            "native_provider_roots": [str(path.resolve()) for path in provider_roots],
            "build_command": ["west", "build", "-b", board],
        }
        write_json(metadata / "generation-manifest.json", manifest)
        return manifest

    def build(self, project: Path, toolchain_bin: Path, jobs: int = 1) -> tuple[int, str]:
        manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
        app = Path(manifest["bsp_path"])
        output = Path(manifest["project_root"])
        environment = os.environ.copy()
        for name in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
            environment.pop(name, None)
        environment["ZEPHYR_TOOLCHAIN_VARIANT"] = manifest["toolchain_variant"]
        environment["CMAKE_BUILD_PARALLEL_LEVEL"] = str(max(1, jobs))
        if manifest["toolchain_variant"] == "host":
            pass
        elif manifest["toolchain_variant"] == "gnuarmemb":
            environment["GNUARMEMB_TOOLCHAIN_PATH"] = str(toolchain_bin.resolve().parent)
        else:
            environment["CROSS_COMPILE"] = str(toolchain_bin / self._detect_prefix(toolchain_bin))
        if manifest["toolchain_variant"] != "host":
            environment["BSPFORGE_REAL_OBJCOPY"] = str(
                toolchain_bin / f"{self._detect_prefix(toolchain_bin)}objcopy"
            )
        command = [
            "west", "build", "-p", "always", "-d", str(output / "build"),
            "-b", manifest["board"], str(app), "--",
            f"-DUSER_CACHE_DIR={output / '.zephyr-cache'}",
            *manifest["cmake_args"],
        ]
        process = subprocess.run(
            command,
            cwd=Path(manifest["zephyr_root"]).parent,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
        )
        if process.returncode == 0 and manifest["binding_strategy"] == "native-driver-trace":
            self._refresh_binding_manifest(project, output / "build")
        return process.returncode, process.stdout

    def verify(self, project: Path, toolchain_bin: Path) -> dict[str, Any]:
        manifest = json.loads((project / "generation-manifest.json").read_text(encoding="utf-8"))
        expected = manifest["device_model"]["registration_symbols"]
        return FirmwareArtifactVerifier().verify(
            Path(manifest["project_root"]),
            toolchain_bin,
            self._detect_prefix(toolchain_bin),
            expected,
            elf_name=manifest["artifacts"]["elf"],
            binary_name=manifest["artifacts"].get("bin"),
            expected_machine=manifest["expected_machine"],
        )

    @staticmethod
    def _compiled_sources(build_root: Path) -> list[Path]:
        ninja = build_root / "build.ninja"
        if not ninja.is_file():
            return []
        text = ninja.read_text(encoding="utf-8", errors="replace")
        paths = re.findall(r"(?<!\S)(/[^\s|]+\.(?:c|cc|cpp))(?=\s|$)", text)
        return sorted({Path(item).resolve() for item in paths if Path(item).is_file()})

    @staticmethod
    def _under(path: Path, roots: list[Path]) -> bool:
        return any(path.is_relative_to(root) for root in roots)

    def _refresh_binding_manifest(self, metadata: Path, build_root: Path) -> None:
        manifest_path = metadata / "generation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ir = json.loads((metadata / "sdk-ir.json").read_text(encoding="utf-8"))
        driver_roots = [Path(item).resolve() for item in manifest["native_driver_roots"]]
        provider_roots = [Path(item).resolve() for item in manifest["native_provider_roots"]]
        compiled_drivers = [
            path for path in self._compiled_sources(build_root)
            if self._under(path, driver_roots)
        ]
        bindings = NativeDriverBindingTracer().generate(
            ir,
            manifest["sdk_profile"],
            "zephyr",
            compiled_drivers,
            provider_roots,
        )
        bindings["compiled_driver_sources"] = [str(path) for path in compiled_drivers]
        write_json(metadata / "functional-bindings.json", bindings)
        manifest["functional_bindings"]["summary"] = bindings["summary"]
        write_json(manifest_path, manifest)

    @staticmethod
    def _prepare_output(output: Path) -> None:
        marker = output / ".bspforge-generated"
        if output.exists():
            if not marker.exists():
                raise RuntimeError(f"Refusing to replace non-BSPForge directory: {output}")
            shutil.rmtree(output)
        output.mkdir(parents=True)
        marker.write_text("generated Zephyr application\n", encoding="utf-8")

    @staticmethod
    def _relative_or_none(value: str | None, root: Path) -> str | None:
        if not value:
            return None
        path = Path(value)
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    @staticmethod
    def _install_board_port(source: Path, app: Path) -> None:
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Zephyr board port does not exist: {source}")
        shutil.copytree(source / "boards", app / "boards")
        if (source / "soc").is_dir():
            shutil.copytree(source / "soc", app / "soc")

    @staticmethod
    def _cmake_source(
        sdk_root: Path,
        sdk_sources: list[str],
        functional: bool,
        native_devices: bool = False,
    ) -> str:
        extra_sources = ""
        include_dirs = ""
        if functional:
            paths = ["src/bspforge_bindings.c"]
            if native_devices:
                paths.append("src/bspforge_zephyr_devices.c")
            paths += [
                str((sdk_root / item).resolve()) for item in sdk_sources
            ]
            extra_sources = "\n".join(f"    {item}" for item in paths)
            include_dirs = f"""
target_include_directories(app PRIVATE
    ${{CMAKE_CURRENT_SOURCE_DIR}}/src
    {sdk_root / 'lib/drivers/include'}
    {sdk_root / 'lib/bsp/include'}
    {sdk_root / 'lib/utils/include'}
)
target_compile_options(app PRIVATE -std=gnu17)
if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
    target_compile_options(app PRIVATE -fstrict-volatile-bitfields)
endif()
target_compile_definitions(app PRIVATE asm=__asm__ typeof=__typeof__)
"""
        return f"""cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{{ZEPHYR_BASE}})
project(bspforge_validation)
target_sources(app PRIVATE src/main.c
{extra_sources}
)
{include_dirs}
"""

    @staticmethod
    def _project_config(
        native_executable: bool = False,
        native_devices: bool = False,
    ) -> str:
        config = """CONFIG_SERIAL=y
CONFIG_CONSOLE=y
CONFIG_UART_CONSOLE=y
CONFIG_GPIO=y
CONFIG_PRINTK=y
CONFIG_ASSERT=y
CONFIG_MAIN_STACK_SIZE=4096
"""
        if native_devices:
            config += """CONFIG_CLOCK_CONTROL=y
CONFIG_COUNTER=y
CONFIG_UART_USE_RUNTIME_CONFIGURE=y
"""
        if native_executable:
            config += "CONFIG_UART_NATIVE_PTY_0_ON_STDINOUT=y\n"
        return config

    @staticmethod
    def _objcopy_wrapper() -> str:
        return r'''#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

real_objcopy = os.environ["BSPFORGE_REAL_OBJCOPY"]
arguments = sys.argv[1:]
state = Path(".bspforge-lma-adjustment")
if len(arguments) >= 2 and arguments[-1] == arguments[-2]:
    try:
        index = arguments.index("--change-section-lma")
        state.write_text(arguments[index + 1], encoding="ascii")
    except (ValueError, IndexError):
        raise SystemExit("unsupported in-place objcopy command")
    raise SystemExit(0)
if state.is_file() and "--output-target=ihex" in arguments:
    arguments = ["--change-section-lma", state.read_text(encoding="ascii"), *arguments]
raise SystemExit(subprocess.run([real_objcopy, *arguments], check=False).returncode)
'''

    @staticmethod
    def _detect_prefix(toolchain_bin: Path) -> str:
        if (toolchain_bin / "gcc").is_file() and (toolchain_bin / "readelf").is_file():
            return ""
        for prefix in (
            "arm-none-eabi-", "riscv-none-embed-", "riscv-none-elf-", "riscv64-unknown-elf-"
        ):
            if (toolchain_bin / f"{prefix}gcc").is_file():
                return prefix
        raise FileNotFoundError(f"No supported cross GCC found in {toolchain_bin}")

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
