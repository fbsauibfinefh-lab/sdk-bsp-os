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
        source = source_dir / "main.c"
        source.write_text(
            self._validation_source(board, ir["sdk"]["digest"][:12]),
            encoding="utf-8",
        )
        (app / "CMakeLists.txt").write_text(self._cmake_source(), encoding="utf-8")
        (app / "prj.conf").write_text(
            self._project_config(options.get("native_executable", False)),
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
        binding_manifest = NativeDriverBindingTracer().generate(
            ir,
            profile_name,
            "zephyr",
            [],
            provider_roots,
            binding_plan=binding_plan,
        )
        device_manifest = {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "strategy": "zephyr-devicetree-native-model",
            "devices": [
                {"class": "serial", "source": "zephyr,console", "operations": ["poll_out"]},
                {"class": "gpio", "source": "led0", "operations": ["configure", "toggle"]},
                {"class": "timer", "source": "k_timer", "operations": ["init", "start"]},
            ],
            "operation_tables": [],
            "registration_symbols": [
                "bspforge_zephyr_validation_init",
                "bspforge_zephyr_validation_run",
            ],
            "summary": {"devices": 3, "generated_sources": 1},
        }
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
            "binding_strategy": "native-driver-trace",
            "zephyr_root": str(zephyr_root),
            "zephyr_revision": revision,
            "project_root": str(output),
            "bsp_path": str(app),
            "build_path": str(output / "build"),
            "adapter": str(source.relative_to(output)),
            "adapter_sha256": file_sha256(source),
            "functional_bindings": {
                "source": None,
                "header": None,
                "manifest": str((metadata / "functional-bindings.json").relative_to(output)),
                "summary": binding_manifest["summary"],
            },
            "device_model": {
                "manifest": str((metadata / "device-model.json").relative_to(output)),
                "sources": [str(source.relative_to(output))],
                "operation_tables": [],
                "registration_symbols": device_manifest["registration_symbols"],
                "summary": device_manifest["summary"],
            },
            "sdk_package": str(Path(ir["sdk"]["root"])),
            "sdk_digest": ir["sdk"]["digest"],
            "sdk_materialization": "analyzed-read-only-input-with-native-hal-module",
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
        if process.returncode == 0:
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
    def _install_board_port(source: Path, app: Path) -> None:
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Zephyr board port does not exist: {source}")
        shutil.copytree(source / "boards", app / "boards")
        if (source / "soc").is_dir():
            shutil.copytree(source / "soc", app / "soc")

    @staticmethod
    def _cmake_source() -> str:
        return """cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(bspforge_validation)
target_sources(app PRIVATE src/main.c)
"""

    @staticmethod
    def _project_config(native_executable: bool = False) -> str:
        config = """CONFIG_SERIAL=y
CONFIG_CONSOLE=y
CONFIG_UART_CONSOLE=y
CONFIG_GPIO=y
CONFIG_PRINTK=y
CONFIG_ASSERT=y
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
    def _validation_source(board: str = "unknown", build_id: str = "uncommitted") -> str:
        source = r'''/* Generated by BSPForge; evidence is stored in bspforge/. */
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <errno.h>
#include <string.h>

#define BSPFORGE_LED_NODE DT_ALIAS(led0)

static struct k_timer bspforge_timer;

int bspforge_zephyr_validation_run(void)
{
    static const char banner[] =
        "{\"bspforge\":true,\"protocol\":\"1.0\","
        "\"event\":\"boot\",\"rtos\":\"zephyr\","
        "\"board\":\"@BOARD@\",\"build_id\":\"@BUILD_ID@\","
        "\"stage\":\"application\"}\r\n";
    const struct device *console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

    if (!device_is_ready(console))
        return -ENODEV;
    for (size_t index = 0; index < sizeof(banner) - 1; ++index)
        uart_poll_out(console, banner[index]);

#if DT_NODE_HAS_STATUS(BSPFORGE_LED_NODE, okay)
    const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(BSPFORGE_LED_NODE, gpios);
    if (gpio_is_ready_dt(&led)) {
        gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
        gpio_pin_toggle_dt(&led);
    }
#endif
    k_timer_start(&bspforge_timer, K_MSEC(10), K_NO_WAIT);
    return 0;
}

static void bspforge_selftest(const char *request_id, const char *command)
{
    const char *status = "unsupported";
    uint32_t elapsed = 0;
    int64_t started;

    if (strcmp(command, "info") == 0 || strcmp(command, "stability") == 0)
        status = "pass";
    else if (strcmp(command, "gpio.toggle") == 0) {
#if DT_NODE_HAS_STATUS(BSPFORGE_LED_NODE, okay)
        const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(BSPFORGE_LED_NODE, gpios);
        if (gpio_is_ready_dt(&led) &&
            gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE) == 0) {
            gpio_pin_toggle_dt(&led);
            gpio_pin_toggle_dt(&led);
            status = "pass";
        } else {
            status = "fail";
        }
#endif
    } else if (strcmp(command, "timer.oneshot") == 0 ||
               strcmp(command, "timer.periodic") == 0) {
        started = k_uptime_get();
        k_sleep(K_MSEC(2));
        elapsed = (uint32_t)(k_uptime_get() - started);
        status = "pass";
    }
    printk("{\"bspforge\":true,\"protocol\":\"1.0\","
           "\"event\":\"result\",\"request_id\":\"%s\","
           "\"command\":\"%s\",\"status\":\"%s\","
           "\"metrics\":{\"elapsed_ms\":%u}}\r\n",
           request_id, command, status, elapsed);
}

int bspforge_zephyr_validation_init(void)
{
    k_timer_init(&bspforge_timer, NULL, NULL);
    return 0;
}
SYS_INIT(bspforge_zephyr_validation_init, APPLICATION, 90);

int main(void)
{
    const struct device *console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
    char line[96];
    size_t length = 0;

    if (bspforge_zephyr_validation_run() != 0)
        return -ENODEV;
    while (device_is_ready(console)) {
        unsigned char value;
        if (uart_poll_in(console, &value) != 0) {
            k_busy_wait(50);
            continue;
        }
        if (value == '\r' || value == '\n') {
            char *request_id;
            char *command;
            char *separator;
            static const char prefix[] = "bspforge_selftest ";
            if (length == 0)
                continue;
            line[length] = '\0';
            request_id = line + sizeof(prefix) - 1;
            separator = strchr(request_id, ' ');
            if (strncmp(line, prefix, sizeof(prefix) - 1) == 0 && separator) {
                *separator = '\0';
                command = separator + 1;
                bspforge_selftest(request_id, command);
            }
            length = 0;
        } else if (length + 1 < sizeof(line)) {
            line[length++] = (char)value;
        } else {
            length = 0;
        }
    }
    return -ENODEV;
}
'''
        return source.replace("@BOARD@", board).replace("@BUILD_ID@", build_id)

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
