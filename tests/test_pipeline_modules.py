from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.closure_solver import ClosureSolver
from bspforge.common import write_json
from bspforge.evaluation import ExperimentEvaluator
from bspforge.ir_store import IRStore
from bspforge.os_backend import RTThreadBackend, ZephyrBackend
from bspforge.os_backend.artifact_verifier import FirmwareArtifactVerifier
from bspforge.os_backend.native_binding import NativeDriverBindingTracer
from bspforge.os_backend.rtthread_device import RTThreadDeviceModelGenerator
from bspforge.os_backend.rtthread_validation import RTThreadValidationGenerator
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.semantic_resolver import SemanticResolver


class ModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        sdk = self.root / "sdk"
        (sdk / "lib" / "drivers" / "include").mkdir(parents=True)
        (sdk / "lib" / "bsp").mkdir(parents=True)
        (sdk / "lds").mkdir(parents=True)
        (sdk / "lib" / "drivers" / "uart.c").write_text(
            '#include "uart.h"\nvoid uart_init(int baud) { sysctl_clock_enable(); }\n'
            'int uart_global_state;\n'
            'void uart_configure(int channel, int baud, int width, int stop, int parity) { (void)channel; }\n'
            'int uart_send_data(int channel, const char *p, int size) { return p != 0 ? size : channel; }\n'
            'int uart_receive_data(int channel, char *p, int size) { return p != 0 ? size : channel; }\n',
            encoding="utf-8",
        )
        (sdk / "lib" / "drivers" / "gpio.c").write_text(
            '#include "gpio.h"\nvoid gpio_set_drive_mode(int pin, int mode) { (void)pin; (void)mode; }\n',
            encoding="utf-8",
        )
        (sdk / "lib" / "drivers" / "include" / "uart.h").write_text(
            "void uart_init(int baud);\nvoid uart_configure(int, int, int, int, int);\n"
            "int uart_send_data(int, const char *, int);\nint uart_receive_data(int, char *, int);\n",
            encoding="utf-8",
        )
        (sdk / "lib" / "drivers" / "include" / "gpio.h").write_text(
            "void gpio_set_drive_mode(int pin, int mode);\n", encoding="utf-8"
        )
        (sdk / "lib" / "bsp" / "crt.S").write_text(".section .text\n", encoding="utf-8")
        (sdk / "lds" / "target.ld").write_text("SECTIONS { .text : { *(.text*) } }\n", encoding="utf-8")
        (sdk / "CMakeLists.txt").write_text(
            "add_library(drivers lib/drivers/uart.c lib/drivers/gpio.c)\n", encoding="utf-8"
        )
        self.sdk = sdk

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ingest_resolve_and_closure_are_traceable(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        self.assertGreaterEqual(ir["stats"]["functions"], 3)
        self.assertTrue(any(item["name"] == "uart_global_state" for item in ir["symbols"]))
        stored = IRStore(self.root / "store").put(ir)
        self.assertTrue(stored.exists())
        resolution = SemanticResolver().resolve(ir, ["uart", "gpio"], threshold=0.4)
        self.assertEqual(resolution["summary"]["resolved"], 2)
        closure = ClosureSolver().solve(ir, resolution)
        kinds = {item["kind"] for item in closure["selected_files"]}
        self.assertIn("linker", kinds)
        self.assertIn("startup", kinds)
        self.assertGreaterEqual(len(closure["selected_build_rules"]), 1)
        self.assertGreater(len(closure["provenance"]), 0)

    def test_build_diagnostics_become_constraints(self) -> None:
        log = "a.c:3:10: fatal error: board.h: No such file or directory\nld: undefined reference to `uart_init'"
        value = BuildDiagnoser().diagnose(log, 1)
        categories = {item["category"] for item in value["diagnostics"]}
        self.assertEqual(categories, {"missing-header", "undefined-symbol"})

    def test_all_supported_build_failure_categories_are_structured(self) -> None:
        log = "\n".join([
            "ld: multiple definition of `duplicate_symbol'",
            "ld: can't link double-float modules with soft-float modules",
            "ld: region `SRAM' overflowed by 128 bytes",
            "ld: cannot find -lmissing",
            "source.c:7:3: error: incompatible declaration",
        ])
        categories = {
            item["category"] for item in BuildDiagnoser().diagnose(log, 1)["diagnostics"]
        }
        self.assertEqual(categories, {
            "multiple-definition",
            "abi-mismatch",
            "region-overflow",
            "missing-library",
            "compile-error",
        })

    def test_warning_summary_is_stable_and_categorized(self) -> None:
        log = (
            "a.c:1: warning: implicit declaration of function 'foo'\n"
            "b.c:2: warning: unused variable 'value'\n"
        )
        summary = BuildDiagnoser.summarize_warnings(log)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["categories"], {"implicit-declaration": 1, "unused": 1})

    def test_diagnostics_add_provider_source_to_closure(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution)
        diagnoser = BuildDiagnoser()
        diagnosis = diagnoser.diagnose("ld: undefined reference to `uart_send_data'", 1)
        proposal = diagnoser.propose_repairs(ir, diagnosis, closure)
        self.assertEqual(proposal["summary"]["actionable"], 1)
        repaired, changed = ClosureSolver().apply_repairs(ir, closure, proposal, 1)
        self.assertTrue(changed)
        self.assertIn("lib/drivers/uart.c", repaired["repair_sources"])
        self.assertEqual(repaired["summary"]["diagnostic_repairs"], 1)

    def test_global_symbol_diagnostic_finds_provider(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution)
        diagnoser = BuildDiagnoser()
        diagnosis = diagnoser.diagnose("ld: undefined reference to `uart_global_state'", 1)
        proposal = diagnoser.propose_repairs(ir, diagnosis, closure)
        self.assertEqual(proposal["summary"]["unresolved"], 0)
        self.assertEqual(proposal["repairs"][0]["provider_kind"], "global-variable")

    def test_rtthread_backend_preserves_input_and_generates_manifest(self) -> None:
        source = self.root / "rt-thread"
        bsp = source / "bsp" / "k210"
        (bsp / "board").mkdir(parents=True)
        (source / "src").mkdir(parents=True)
        (bsp / "rtconfig.py").write_text(
            "import os\nPREFIX = 'riscv-none-embed-'\n", encoding="utf-8"
        )
        (bsp / "rtconfig.h").write_text(
            "/* Device Drivers */\n#define RT_USING_SERIAL\n", encoding="utf-8"
        )
        (bsp / "SConstruct").write_text("# fixture\n", encoding="utf-8")
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution)
        output = self.root / "generated"
        manifest = RTThreadBackend().generate(source, "k210", output, ir, resolution, closure)
        self.assertTrue((Path(manifest["bsp_path"]) / "board" / "bspforge_sdk_adapter.c").exists())
        self.assertTrue((output / manifest["sdk_package"] / "bspforge-input.json").exists())
        self.assertEqual(manifest["sdk_materialization"], "copied-from-analyzed-input")
        binding = manifest["functional_bindings"]
        self.assertEqual(binding["summary"]["capabilities"], 1)
        generated_binding = output / binding["source"]
        self.assertIn("uart_send_data", generated_binding.read_text(encoding="utf-8"))
        device_model = manifest["device_model"]
        self.assertEqual(device_model["summary"]["serial"], 1)
        generated_devices = output / device_model["sources"][0]
        self.assertIn("bspforge_uart_ops", generated_devices.read_text(encoding="utf-8"))
        self.assertIn("riscv-none-embed-", (bsp / "rtconfig.py").read_text(encoding="utf-8"))
        generated_config = (Path(manifest["bsp_path"]) / "rtconfig.py").read_text(encoding="utf-8")
        self.assertIn("BSPFORGE_TOOLCHAIN_PREFIX", generated_config)

    def test_native_rtthread_device_models_are_generated_from_config(self) -> None:
        bsp = self.root / "native-bsp"
        (bsp / "board").mkdir(parents=True)
        (bsp / "drivers").mkdir()
        binding_manifest = {
            "bindings": [
                {"capability": "uart"},
                {"capability": "gpio"},
                {"capability": "timer"},
            ]
        }
        manifest = RTThreadDeviceModelGenerator().generate(
            bsp,
            binding_manifest,
            {
                "uart": [{"name": "testuart", "channel": 1, "baud_rate": 9600}],
                "pin": {"name": "testpin", "max_pins": 16},
                "hwtimer": [
                    {"name": "testtim", "device": 1, "channel": 2, "frequency": 1000}
                ],
            },
        )
        self.assertEqual(manifest["summary"]["devices"], 3)
        self.assertEqual(
            set(manifest["operation_tables"]),
            {"bspforge_uart_ops", "bspforge_pin_ops", "bspforge_hwtimer_ops"},
        )
        board_source = (bsp / "board" / "bspforge_devices.c").read_text(encoding="utf-8")
        timer_source = (bsp / "drivers" / "drv_hw_timer.c").read_text(encoding="utf-8")
        self.assertIn('rt_hw_serial_register(&bspforge_uart_devices[0], "testuart"', board_source)
        self.assertIn('rt_device_pin_register("testpin"', board_source)
        self.assertIn('rt_device_hwtimer_register(&bspforge_hwtimers[0], "testtim"', timer_source)

    def test_device_configuration_rejects_duplicate_names(self) -> None:
        bsp = self.root / "duplicate-bsp"
        (bsp / "board").mkdir(parents=True)
        (bsp / "drivers").mkdir()
        with self.assertRaisesRegex(ValueError, "Duplicate RT-Thread device name"):
            RTThreadDeviceModelGenerator().generate(
                bsp,
                {"bindings": [{"capability": "uart"}, {"capability": "gpio"}]},
                {
                    "uart": [{"name": "same", "channel": 0}],
                    "pin": {"name": "same", "max_pins": 8},
                    "hwtimer": [],
                },
            )

    def test_native_driver_trace_links_sdk_entities_to_rtos_sources(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        drivers = self.root / "drivers"
        drivers.mkdir()
        (drivers / "native_uart.c").write_text(
            "void native_init(void) { uart_init(115200); }\n", encoding="utf-8"
        )
        manifest = NativeDriverBindingTracer().generate(
            ir, "k210", "zephyr", [drivers]
        )
        uart = next(item for item in manifest["bindings"] if item["capability"] == "uart")
        linked = [item["symbol"] for item in uart["sdk_symbols"] if item["linked_by_native_driver"]]
        self.assertIn("uart_init", linked)
        self.assertEqual(uart["status"], "resolved")

    def test_rtthread_native_validation_source_uses_device_api(self) -> None:
        bsp = self.root / "native-validation"
        manifest = RTThreadValidationGenerator().generate(
            bsp, {"uart": "uart2", "pin": 7}
        )
        source = Path(manifest["source"]).read_text(encoding="utf-8")
        self.assertIn('bspforge_uart_name[] = "uart2"', source)
        self.assertIn("rt_device_write", source)
        self.assertIn("rt_pin_write", source)
        self.assertIn("rt_timer_start", source)

    def test_zephyr_backend_generates_native_application_contract(self) -> None:
        zephyr = self.root / "zephyr"
        (zephyr / "drivers").mkdir(parents=True)
        (zephyr / "CMakeLists.txt").write_text("# fixture\n", encoding="utf-8")
        (zephyr / "drivers" / "uart_fixture.c").write_text(
            "void bind(void) { uart_init(115200); }\n", encoding="utf-8"
        )
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution)
        output = self.root / "zephyr-output"
        manifest = ZephyrBackend().generate(
            zephyr,
            "fixture-board",
            output,
            ir,
            resolution,
            closure,
            {"sdk_profile": "k210"},
        )
        self.assertEqual(manifest["backend"], "zephyr")
        self.assertTrue((output / "app" / "prj.conf").is_file())
        self.assertTrue((output / "app" / "src" / "main.c").is_file())
        self.assertEqual(
            manifest["device_model"]["registration_symbols"],
            ["bspforge_zephyr_validation_init", "bspforge_zephyr_validation_run"],
        )

    def test_zephyr_compiled_source_parser_excludes_unselected_drivers(self) -> None:
        build = self.root / "zephyr-build"
        selected = self.root / "zephyr" / "drivers" / "uart_selected.c"
        unselected = self.root / "zephyr" / "drivers" / "uart_unselected.c"
        build.mkdir()
        selected.parent.mkdir(parents=True)
        selected.write_text("void selected(void) {}\n", encoding="utf-8")
        unselected.write_text("void unselected(void) {}\n", encoding="utf-8")
        (build / "build.ninja").write_text(
            f"build selected.obj: C_COMPILER {selected}\n", encoding="utf-8"
        )
        self.assertEqual(ZephyrBackend._compiled_sources(build), [selected.resolve()])

    def test_experiment_metrics_cover_semantics_bindings_and_devices(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        ground_truth = {
            "id": "fixture-truth",
            "capabilities": {
                "uart": {
                    "semantic_symbols": ["uart_init", "uart_configure"],
                    "binding_symbols": ["uart_init", "uart_configure"],
                    "device_operations": ["configure", "putc", "getc"],
                }
            },
        }
        bindings = {
            "bindings": [{
                "capability": "uart",
                "sdk_symbols": [{"symbol": "uart_init"}, {"symbol": "uart_configure"}],
            }]
        }
        devices = {
            "devices": [{
                "class": "serial",
                "operations": ["configure", "putc", "getc"],
            }]
        }
        metrics = ExperimentEvaluator().evaluate(resolution, bindings, devices, ground_truth)
        self.assertEqual(metrics["summary"]["binding_macro_recall"], 1.0)
        self.assertEqual(metrics["summary"]["device_operation_macro_recall"], 1.0)
        ablations = ExperimentEvaluator().ablate(ir, ground_truth, threshold=0.4, top_k=8)
        self.assertEqual(len(ablations["experiments"]), 8)

    def test_artifact_output_parsers(self) -> None:
        header = FirmwareArtifactVerifier._parse_elf_header(
            "  Class: ELF64\n  Machine: RISC-V\n  Entry point address: 0x80000000\n"
        )
        size = FirmwareArtifactVerifier._parse_size(
            "text data bss dec hex filename\n10 2 3 15 f rtthread.elf\n"
        )
        self.assertEqual(header["Machine"], "RISC-V")
        self.assertEqual(size, {"text": 10, "data": 2, "bss": 3, "dec": 15})


if __name__ == "__main__":
    unittest.main()
