from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.binding_planner import BindingPlanner
from bspforge.closure_solver import ClosureSolver
from bspforge.compile_feedback import create_compile_feedback
from bspforge.common import write_json
from bspforge.evaluation import ExperimentEvaluator
from bspforge.ir_store import IRStore
from bspforge.hardware_test.host import HardwareTestRunner, ProcessTransport
from bspforge.os_backend import RTThreadBackend, ZephyrBackend
from bspforge.os_backend.artifact_verifier import FirmwareArtifactVerifier
from bspforge.os_backend.native_binding import NativeDriverBindingTracer
from bspforge.os_backend.rtthread_device import RTThreadDeviceModelGenerator
from bspforge.os_backend.rtthread_validation import RTThreadValidationGenerator
from bspforge.operation_dataset import build_operation_dataset
from bspforge.operation_constraints import contract_adjustment
from bspforge.operation_ranking import (
    graded_relevance,
    identifier_tokens,
    operation_feature_map,
    operation_static_score,
    weak_relevance,
)
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.ranking_dataset import audit_ground_truth, build_ranking_dataset
from bspforge.semantic_resolver import SemanticResolver
from bspforge.semantic_resolver.learning import FEATURE_NAMES
from bspforge.structured_retrieval import (
    api_family_key,
    classify_source_role,
    complete_structured_scores,
    enrich_group_with_structured_retrieval,
)
from scripts.evaluate_ranker_cv import bm25_scores, ranking_metrics


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

    def test_hybrid_and_regex_frontends_remain_comparable(self) -> None:
        hybrid = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "hybrid-sdk")
        regex = SDKIngestor(frontend_mode="regex").ingest(self.sdk, "regex-sdk")
        self.assertEqual(hybrid["frontend"]["mode"], "hybrid")
        self.assertGreaterEqual(regex["frontend"]["selected_counts"]["regex"], 3)
        self.assertGreaterEqual(hybrid["stats"]["functions"], regex["stats"]["functions"])
        self.assertTrue(all("parser" in item for item in hybrid["functions"]))

    def test_header_inline_functions_are_ingested(self) -> None:
        (self.sdk / "lib" / "drivers" / "include" / "irq.h").write_text(
            "static inline void irq_enable(int irq) { (void)irq; }\n",
            encoding="utf-8",
        )
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "header-sdk")
        entity = next(item for item in ir["functions"] if item["name"] == "irq_enable")
        self.assertEqual(entity["file"], "lib/drivers/include/irq.h")
        self.assertEqual(entity["parser"], "tree-sitter")

    def test_ingestor_skips_broken_sdk_symlinks(self) -> None:
        broken = self.sdk / "lib" / "drivers" / "missing.c"
        try:
            broken.symlink_to(self.sdk / "not-checked-out.c")
        except OSError:
            self.skipTest("当前文件系统不支持符号链接")
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "broken-link-sdk")
        skipped = [
            item for item in ir["frontend"]["files"]
            if item.get("selected_frontend") == "skipped-unreadable"
        ]
        self.assertEqual(skipped[0]["file"], "lib/drivers/missing.c")

    def test_ground_truth_audit_and_dataset_are_sdk_grouped(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        truth = {
            "sdk": {"id": "fixture-sdk"},
            "capabilities": {
                "uart": {"semantic_symbols": ["uart_init"]},
                "gpio": {"semantic_symbols": ["gpio_set_drive_mode"]},
            },
        }
        inputs = [(ir, truth, self.root / "sdk-ir.json")]
        audit = audit_ground_truth(inputs)
        self.assertTrue(audit["summary"]["passed"])
        dataset = build_ranking_dataset(
            inputs, hard_negatives=4, random_negatives=2, positive_instances=1
        )
        self.assertEqual(dataset["summary"]["sdks"], 1)
        self.assertEqual(dataset["summary"]["groups"], 2)
        self.assertTrue(all(item["sdk_id"] == "fixture-sdk" for item in dataset["groups"]))
        candidate = dataset["groups"][0]["candidates"][0]
        self.assertEqual(set(candidate["features"]), set(FEATURE_NAMES))

    def test_bm25_lexical_baseline_prefers_matching_sdk_api(self) -> None:
        group = {
            "capability": "uart",
            "candidates": [
                {"entity_id": "1", "symbol": "uart_send", "file": "drivers/uart.c", "label": 1},
                {"entity_id": "2", "symbol": "clock_setup", "file": "system/clock.c", "label": 0},
            ],
        }
        scores = bm25_scores(group)
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(ranking_metrics(group["candidates"], scores)["precision_at_1"], 1.0)

    def test_operation_ranker_separates_opposite_actions(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        functions = {item["id"]: item for item in ir["functions"]}
        candidates = SemanticResolver().candidate_pool(ir, "uart")
        send = next(item for item in candidates if item["symbol"] == "uart_send_data")
        receive = next(item for item in candidates if item["symbol"] == "uart_receive_data")
        send_score = operation_static_score(
            operation_feature_map("uart", "write", send, functions[send["entity_id"]])
        )
        receive_score = operation_static_score(
            operation_feature_map("uart", "write", receive, functions[receive["entity_id"]])
        )
        self.assertGreater(send_score, receive_score)

    def test_operation_ranker_keeps_parameterized_toggle_for_stop(self) -> None:
        candidate = {"entity_id": "toggle", "symbol": "timer_set_enable", "score": 0.7}
        function = {
            "file": "drivers/timer.c",
            "signature": "void timer_set_enable(unsigned channel, bool enable)",
            "calls": [],
            "parser_confidence": 1.0,
        }
        features = operation_feature_map("timer", "stop", candidate, function)
        self.assertEqual(features["parameterized-toggle"], 1.0)
        self.assertEqual(features["opposite-action"], 0.0)

    def test_source_role_router_separates_hal_from_middleware(self) -> None:
        hal = classify_source_role(
            "components/device/hal/source/mtb_hal_gpio.c", "mtb_hal_gpio_setup"
        )
        middleware = classify_source_role(
            "Middlewares/Third_Party/FreeRTOS/Source/timers.c", "xTimerStart"
        )
        self.assertEqual(hal[0], "public-hal")
        self.assertEqual(middleware[0], "middleware")
        self.assertGreater(hal[1], middleware[1])

    def test_api_family_keeps_base_timer_separate_from_extended_modes(self) -> None:
        self.assertEqual(api_family_key("timer", "HAL_TIM_Base_Start"), "hal_tim_base")
        self.assertEqual(api_family_key("timer", "HAL_TIMEx_PWMN_Start"), "hal_tim_ex")

    def test_structured_policy_recovers_public_hal_siblings(self) -> None:
        group = {
            "group_id": "fixture::clock.initialize",
            "capability": "clock",
            "operation": "initialize",
            "operation_id": "clock.initialize",
            "candidates": [
                {
                    "entity_id": "ll",
                    "symbol": "LL_USART_ClockInit",
                    "file": "Drivers/STM32/Inc/stm32_ll_usart.h",
                    "static_score": 0.92,
                    "candidate_text": "file: Drivers/STM32/Inc/stm32_ll_usart.h\nsymbol: LL_USART_ClockInit\nsignature: void LL_USART_ClockInit(void)\nincludes:\ncalls:",
                    "features": {"operation-exact": 1.0, "operation-substring": 0.0, "parameterized-toggle": 0.0, "field-late-interaction": 0.93},
                },
                {
                    "entity_id": "clock",
                    "symbol": "HAL_RCC_ClockConfig",
                    "file": "Drivers/STM32_HAL_Driver/Src/stm32_hal_rcc.c",
                    "static_score": 0.72,
                    "candidate_text": "file: Drivers/STM32_HAL_Driver/Src/stm32_hal_rcc.c\nsymbol: HAL_RCC_ClockConfig\nsignature: int HAL_RCC_ClockConfig(void *config)\nincludes:\ncalls:",
                    "features": {"operation-exact": 1.0, "operation-substring": 0.0, "parameterized-toggle": 0.0, "field-late-interaction": 0.75},
                },
                {
                    "entity_id": "osc",
                    "symbol": "HAL_RCC_OscConfig",
                    "file": "Drivers/STM32_HAL_Driver/Src/stm32_hal_rcc.c",
                    "static_score": 0.70,
                    "candidate_text": "file: Drivers/STM32_HAL_Driver/Src/stm32_hal_rcc.c\nsymbol: HAL_RCC_OscConfig\nsignature: int HAL_RCC_OscConfig(void *config)\nincludes:\ncalls:",
                    "features": {"operation-exact": 1.0, "operation-substring": 0.0, "parameterized-toggle": 0.0, "field-late-interaction": 0.74},
                },
            ],
        }
        enrich_group_with_structured_retrieval(group)
        scores, policy = complete_structured_scores(group)
        ranked = sorted(
            zip(group["candidates"], scores, strict=True),
            key=lambda item: (-item[1], item[0]["entity_id"]),
        )
        self.assertTrue(policy["leader_fallback"])
        self.assertEqual(
            {item["symbol"] for item, _ in ranked[:2]},
            {"HAL_RCC_ClockConfig", "HAL_RCC_OscConfig"},
        )

    def test_operation_tokens_normalize_inflected_and_deinit_actions(self) -> None:
        self.assertIn("enable", identifier_tokens("clock_enabled"))
        self.assertIn("deinit", identifier_tokens("HAL_RCC_DeInit"))

    def test_public_header_inline_internal_is_not_private(self) -> None:
        candidate = {"entity_id": "inline", "symbol": "mtb_hal_gpio_write_internal", "score": 0.7}
        function = {
            "file": "hal/include/mtb_hal_gpio_impl.h",
            "signature": "static inline void mtb_hal_gpio_write_internal(void *obj, bool value)",
            "calls": [],
            "parser_confidence": 1.0,
        }
        features = operation_feature_map("gpio", "write", candidate, function)
        self.assertEqual(features["private-api"], 0.0)
        self.assertGreaterEqual(graded_relevance(features)[0], 2)

    def test_contract_adjustment_rejects_semantic_conflict(self) -> None:
        candidate = {
            "features": {
                "capability-name": 1.0,
                "operation-exact": 1.0,
                "operation-substring": 0.0,
                "parameterized-toggle": 0.0,
                "signature-hint": 0.0,
                "controller-api": 0.0,
                "hal-abstraction": 1.0,
                "opposite-action": 0.0,
                "semantic-conflict": 1.0,
                "reverse-os-adapter": 0.0,
                "private-api": 0.0,
                "test-example": 0.0,
            }
        }
        adjustment, evidence = contract_adjustment(candidate)
        self.assertLess(adjustment, 0.0)
        self.assertIn("reject:semantic-conflict", evidence)

    def test_compile_feedback_does_not_claim_runtime_semantics(self) -> None:
        resolution = {
            "sdk_id": "fixture-sdk",
            "mappings": [{
                "capability": "uart",
                "operation_rankings": [{
                    "operation": "write",
                    "selected_entity_id": "fn-uart-write",
                    "selected_symbol": "uart_send_data",
                }],
            }],
        }
        feedback = create_compile_feedback(
            resolution, {"success": True, "skipped": False, "diagnosis": {"diagnostics": []}}
        )
        self.assertEqual(feedback["records"][0]["calibration_score"], 1.0)
        self.assertFalse(feedback["records"][0]["semantic_correctness_proven"])

    def test_operation_ranker_rejects_reverse_os_adapter(self) -> None:
        candidate = {"entity_id": "reverse", "symbol": "cyhal_gpio_write", "score": 0.7}
        function = {
            "file": "middleware/wifi-host-driver/porting/src/hal/cyhal_gpio.c",
            "signature": "void cyhal_gpio_write(unsigned pin, bool value)",
            "calls": ["rt_pin_write"],
            "parser_confidence": 1.0,
        }
        features = operation_feature_map("gpio", "write", candidate, function)
        self.assertEqual(features["reverse-os-adapter"], 1.0)
        self.assertEqual(weak_relevance(features), 0)

    def test_operation_resolver_preserves_binding_planner_contract(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(
            ir, ["uart", "gpio"], method="operation-weighted", threshold=0.3
        )
        plan = BindingPlanner().plan(ir, resolution)
        uart = next(item for item in plan["capabilities"] if item["capability"] == "uart")
        selected = {item["operation"]: item["selected_symbol"] for item in uart["operations"]}
        self.assertEqual(selected["write"], "uart_send_data")
        self.assertEqual(selected["read"], "uart_receive_data")

    def test_operation_resolver_can_abstain_on_small_margin(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(
            ir,
            ["uart"],
            method="operation-weighted",
            threshold=0.3,
            operation_min_margin=1.0,
        )
        rankings = resolution["mappings"][0]["operation_rankings"]
        self.assertTrue(all(item["selected_symbol"] is None for item in rankings))
        self.assertTrue(all(item["abstained"] for item in rankings))

    def test_operation_semantic_fusion_can_rerank_static_candidates(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        resolver = SemanticResolver()
        candidates = resolver.candidate_pool(ir, "uart")
        functions = {item["id"]: item for item in ir["functions"]}

        class FixedSemanticRanker:
            def score_operations(self, capability, operations, ranked, function_map):
                del capability, function_map
                return {
                    operation: {
                        item["entity_id"]: {
                            "base": float(item["symbol"] == "uart_receive_data"),
                            "adapted": float(item["symbol"] == "uart_receive_data"),
                        }
                        for item in ranked
                    }
                    for operation in operations
                }

        result = resolver._resolve_operations(
            "uart",
            candidates,
            functions,
            threshold=0.3,
            top_k=8,
            minimum_margin=0.0,
            semantic_ranker=FixedSemanticRanker(),
            semantic_weights={"static": 0.0, "base": 0.5, "adapted": 0.5},
        )
        write_ranking = next(
            item for item in result["operation_rankings"] if item["operation"] == "write"
        )
        self.assertEqual(write_ranking["selected_symbol"], "uart_receive_data")
        self.assertEqual(write_ranking["candidates"][0]["semantic_scores"]["adapted"], 1.0)

    def test_operation_dataset_keeps_external_labels_out_of_training(self) -> None:
        train_ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "train-sdk")
        test_ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "test-sdk")
        train_meta = {
            "sdk_id": "train-sdk",
            "vendor": "Train",
            "independence_group": "train-vendor",
            "role": "train",
        }
        test_meta = {
            "sdk_id": "test-sdk",
            "vendor": "Test",
            "independence_group": "board-test",
            "role": "external-test",
        }
        truth = {
            "sdk_id": "test-sdk",
            "operations": {
                "uart.configure": {"symbols": ["uart_configure"]},
                "uart.write": {"symbols": ["uart_send_data"]},
                "uart.read": {"symbols": ["uart_receive_data"]},
            },
        }
        dataset = build_operation_dataset([
            (train_meta, train_ir, None, self.root / "train-ir.json"),
            (test_meta, test_ir, truth, self.root / "test-ir.json"),
        ])
        training = [item for item in dataset["groups"] if item["role"] == "train"]
        external = [item for item in dataset["groups"] if item["role"] == "external-test"]
        self.assertTrue(training)
        self.assertEqual(
            {item["label_source"] for group in training for item in group["candidates"]},
            {"auditable-graded-supervision"},
        )
        self.assertEqual({item["label_source"] for group in external for item in group["candidates"]}, {"source-audited"})

    def test_process_transport_reuses_hardware_protocol(self) -> None:
        simulator = self.root / "simulator.py"
        simulator.write_text(
            "import json, sys\n"
            "print(json.dumps({'bspforge': True, 'protocol': '1.0', 'event': 'boot'}), flush=True)\n"
            "for line in sys.stdin:\n"
            "    parts = line.strip().split()\n"
            "    if len(parts) == 3:\n"
            "        print(json.dumps({'bspforge': True, 'protocol': '1.0', 'event': 'result', "
            "'request_id': parts[1], 'command': parts[2], 'status': 'pass'}), flush=True)\n",
            encoding="utf-8",
        )
        transport = ProcessTransport([sys.executable, "-u", str(simulator)], timeout=1.0)
        try:
            report = HardwareTestRunner(transport, "sim", "zephyr", timeout=1.0).run(
                rounds=2, commands=["info"]
            )
        finally:
            transport.close()
        self.assertEqual(report["summary"]["boot_success_rate"], 1.0)
        self.assertEqual(report["summary"]["command_pass_rate"], 1.0)

    def test_hybrid_frontend_handles_deep_syntax_trees(self) -> None:
        nested = "(" * 1200 + "1" + ")" * 1200
        (self.sdk / "lib" / "drivers" / "deep.c").write_text(
            f"int deeply_nested(void) {{ return {nested}; }}\n",
            encoding="utf-8",
        )
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "deep-sdk")
        self.assertTrue(any(item["name"] == "deeply_nested" for item in ir["functions"]))

    def test_binding_planner_maps_operations_without_profile_symbols(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        plan = BindingPlanner().plan(ir, resolution)
        uart = next(item for item in plan["capabilities"] if item["capability"] == "uart")
        write = next(item for item in uart["operations"] if item["operation"] == "write")
        self.assertEqual(write["selected_symbol"], "uart_send_data")
        self.assertEqual(write["status"], "inferred")

    def test_target_aware_closure_rejects_foreign_architecture_assets(self) -> None:
        (self.sdk / "lib" / "bsp" / "startup_arm.S").write_text(".section .text\n")
        (self.sdk / "lib" / "bsp" / "startup_riscv.S").write_text(".section .text\n")
        (self.sdk / "lds" / "arm.ld").write_text("ENTRY(Reset_Handler)\n")
        (self.sdk / "lds" / "riscv.ld").write_text("ENTRY(_start)\n")
        ir = SDKIngestor().ingest(self.sdk, "mixed-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution, {"architecture": "riscv64"})
        selected = {item["path"] for item in closure["selected_files"]}
        self.assertIn("lib/bsp/startup_riscv.S", selected)
        self.assertIn("lds/riscv.ld", selected)
        self.assertNotIn("lib/bsp/startup_arm.S", selected)
        self.assertNotIn("lds/arm.ld", selected)

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

    def test_missing_library_repair_is_medium_risk(self) -> None:
        (self.sdk / "libdrivers.a").write_bytes(b"!<arch>\n")
        ir = SDKIngestor().ingest(self.sdk, "library-sdk")
        resolution = SemanticResolver().resolve(ir, ["uart"], threshold=0.4)
        closure = ClosureSolver().solve(ir, resolution)
        diagnosis = BuildDiagnoser().diagnose("ld: cannot find -ldrivers", 1)
        proposal = BuildDiagnoser().propose_repairs(ir, diagnosis, closure)
        self.assertEqual(proposal["repairs"][0]["action"], "add-library")
        self.assertEqual(proposal["repairs"][0]["risk"], "medium")
        _, changed = ClosureSolver().apply_repairs(
            ir, closure, proposal, 1, maximum_risk="low"
        )
        self.assertFalse(changed)

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
        generated_devices = output / next(
            item for item in device_model["sources"] if item.endswith("bspforge_devices.c")
        )
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

    def test_not_applicable_metrics_do_not_inflate_macro_average(self) -> None:
        resolution = {
            "mappings": [{
                "capability": "clock",
                "accepted": [],
                "candidates": [],
            }]
        }
        truth = {"id": "n-a", "capabilities": {
            "clock": {
                "supported": False,
                "semantic_symbols": [],
                "binding_symbols": [],
                "device_operations": [],
            }
        }}
        metrics = ExperimentEvaluator().evaluate(
            resolution, {"bindings": []}, {"devices": []}, truth
        )
        self.assertIsNone(metrics["summary"]["semantic_macro_f1"])
        self.assertIsNone(metrics["summary"]["binding_macro_recall"])

    def test_hardware_protocol_report_excludes_unsupported_commands(self) -> None:
        class FakeTransport:
            def __init__(self) -> None:
                self.lines = [
                    b'{"bspforge":true,"protocol":"1.0","event":"boot"}\n'
                ]

            def write(self, value: bytes) -> int:
                _, request_id, command = value.decode().strip().split()
                status = "unsupported" if command == "gpio.irq" else "pass"
                self.lines.append(
                    (
                        '{"bspforge":true,"protocol":"1.0","event":"result",'
                        f'"request_id":"{request_id}","command":"{command}",'
                        f'"status":"{status}","metrics":{{}}}}\n'
                    ).encode()
                )
                return len(value)

            def readline(self) -> bytes:
                return self.lines.pop(0) if self.lines else b""

            def close(self) -> None:
                pass

        report = HardwareTestRunner(
            FakeTransport(), "fixture", "rtthread", timeout=0.1
        ).run(commands=["info", "gpio.irq"])
        self.assertEqual(report["summary"]["commands_passed"], 1)
        self.assertEqual(report["summary"]["commands_applicable"], 1)
        self.assertEqual(report["summary"]["unsupported"], 1)

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
