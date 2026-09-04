from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

import numpy as np

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.code_effect_encoder import CodeEmbeddingCache, normalize_code, operation_query_text
from bspforge.binding_planner import BindingPlanner
from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.closure_solver import ClosureSolver
from bspforge.compile_feedback import create_compile_feedback
from bspforge.common import write_json
from bspforge.cross_operation_coherence import (
    coherence_family_key,
    enrich_dataset_with_cross_operation_coherence,
)
from bspforge.evaluation import ExperimentEvaluator
from bspforge.frozen_operation_ranker import FrozenOperationRanker
from bspforge.ir_store import IRStore
from bspforge.hardware_effect_graph import HardwareEffectGraph
from bspforge.hardware_test.host import HardwareTestRunner, ProcessTransport
from bspforge.os_backend import RTThreadBackend, ZephyrBackend
from bspforge.os_backend.artifact_verifier import FirmwareArtifactVerifier
from bspforge.os_backend.native_binding import NativeDriverBindingTracer
from bspforge.os_backend.rtthread_device import RTThreadDeviceModelGenerator
from bspforge.os_backend.rtthread_validation import RTThreadValidationGenerator
from bspforge.os_backend.zephyr_binding import ZephyrBindingGenerator
from bspforge.os_backend.zephyr_device import ZephyrDeviceModelGenerator
from bspforge.os_backend.zephyr_validation import ZephyrValidationGenerator
from bspforge.operation_dataset import build_operation_dataset
from bspforge.operation_constraints import contract_adjustment
from bspforge.operation_ranking import (
    graded_relevance,
    identifier_tokens,
    operation_feature_map,
    operation_static_score,
    weak_relevance,
)
from bspforge.pretrained_effect_ranker import PretrainedEffectPURanker
from bspforge.multiview_effect_encoder import (
    JointPairCache,
    MultiViewEffectCache,
    operation_effect_slice,
)
from bspforge.multiview_effect_ranker import (
    MultiViewEffectRanker,
    operation_constraint_penalty,
)
from bspforge.joint_pair_ranker import JointPairRanker
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.ranking_dataset import GroundTruthError, audit_ground_truth, build_ranking_dataset
from bspforge.semantic_resolver import SemanticResolver
from bspforge.ranking_diagnostics import deterministic_ranking_evidence
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

    def test_hardware_effect_graph_recovers_public_wrapper_path(self) -> None:
        (self.sdk / "lib" / "drivers" / "uart.c").write_text(
            '#include "uart.h"\n#include "uart_regs.h"\n'
            "static void uart_channel_putc(int value) { UART0->THR = value; }\n"
            "int uart_send_data(const char *data, int size) { "
            "for (int i = 0; i < size; ++i) uart_channel_putc(data[i]); return size; }\n"
            "static void uart_irq_handler(void) { UART0->IER |= 1; }\n",
            encoding="utf-8",
        )
        (self.sdk / "lib" / "drivers" / "include" / "uart.h").write_text(
            "int uart_send_data(const char *data, int size);\n", encoding="utf-8"
        )
        (self.sdk / "lib" / "drivers" / "include" / "uart_regs.h").write_text(
            "typedef struct { volatile int THR; volatile int IER; } UART_Type;\n"
            "#define UART0 ((UART_Type *)0x40000000)\n",
            encoding="utf-8",
        )
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "effect-sdk")
        functions = {item["name"]: item for item in ir["functions"]}
        graph = HardwareEffectGraph(
            ir, self.sdk, {item["id"] for item in functions.values()}
        )
        send, evidence = graph.candidate_features(
            {"entity_id": functions["uart_send_data"]["id"]}, "uart.write"
        )
        leaf, _ = graph.candidate_features(
            {"entity_id": functions["uart_channel_putc"]["id"]}, "uart.write"
        )
        handler, _ = graph.candidate_features(
            {"entity_id": functions["uart_irq_handler"]["id"]}, "uart.write"
        )
        self.assertEqual(evidence["effect_path"][:2], ["uart_send_data", "uart_channel_putc"])
        self.assertGreater(send["hw-transitive-operation-effect"], send["hw-direct-operation-effect"])
        self.assertGreater(send["hw-api-boundary-depth"], leaf["hw-api-boundary-depth"])
        self.assertEqual(send["hw-public-boundary"], 1.0)
        self.assertEqual(handler["hw-internal-callback-likelihood"], 1.0)

    def test_code_effect_serialization_normalizes_unstable_literals(self) -> None:
        normalized = normalize_code(
            '/* comment */ UART0->THR = 0x40001000; send("hello", 32); // tail\n'
        )
        self.assertNotIn("comment", normalized)
        self.assertNotIn("40001000", normalized)
        self.assertNotIn("hello", normalized)
        self.assertIn("HEX_LITERAL", normalized)
        self.assertIn("INT_LITERAL", normalized)
        self.assertIn("required effect", operation_query_text("uart.write"))

    def test_pretrained_effect_cache_and_ranker_contract(self) -> None:
        metadata_path = self.root / "embedding-metadata.json"
        vectors_path = self.root / "embedding-vectors.npz"
        write_json(metadata_path, {
            "model": {"id": "fixture", "dimension": 4},
            "document_keys": ["fixture-sdk::entity-1", "fixture-sdk::entity-2"],
            "operation_ids": [
                f"{capability}.{operation}"
                for capability, specification in CAPABILITY_SCHEMA.items()
                for operation in specification["operations"]
            ],
        })
        np.savez_compressed(
            vectors_path,
            documents=np.asarray([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float16),
            queries=np.ones((19, 4), dtype=np.float16) / 2,
        )
        cache = CodeEmbeddingCache(metadata_path, vectors_path)
        group = {
            "sdk_id": "fixture-sdk",
            "operation_id": "uart.write",
            "candidates": [
                {"entity_id": "entity-1", "features": {}},
                {"entity_id": "entity-2", "features": {}},
            ],
        }
        ranker = PretrainedEffectPURanker(cache)
        ranker.fit_scaler(group["candidates"])
        components = ranker.group_components(group)
        self.assertEqual(set(components), {"fusion", "base", "adapted", "graph"})
        self.assertTrue(all(len(values) == 2 for values in components.values()))

    def test_operation_effect_slice_prioritizes_register_write(self) -> None:
        body = (
            "{ validate(value); log_start(); while (!(UART->STATUS & TX_READY)) {} "
            "UART->TXDATA = value; log_done(); }"
        )
        selected = operation_effect_slice(
            body,
            "uart.write",
            {"register_hits": ["UART->TXDATA"], "effect_path": ["uart_write"]},
            max_statements=4,
        )
        self.assertIn("TXDATA", selected)
        self.assertIn("value", selected)

    def test_multiview_ranker_and_status_query_constraint(self) -> None:
        base_metadata = self.root / "base-metadata.json"
        base_vectors = self.root / "base-vectors.npz"
        focused_metadata = self.root / "focused-metadata.json"
        focused_vectors = self.root / "focused-vectors.npz"
        operation_ids = [
            f"{capability}.{operation}"
            for capability, specification in CAPABILITY_SCHEMA.items()
            for operation in specification["operations"]
        ]
        write_json(base_metadata, {
            "model": {"id": "fixture", "dimension": 4},
            "document_keys": ["fixture-sdk::entity-1", "fixture-sdk::entity-2"],
            "operation_ids": operation_ids,
        })
        np.savez_compressed(
            base_vectors,
            documents=np.asarray([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float16),
            queries=np.ones((19, 4), dtype=np.float16) / 2,
        )
        write_json(focused_metadata, {
            "focused_keys": [
                "fixture-sdk::uart.write::entity-1",
                "fixture-sdk::uart.write::entity-2",
            ]
        })
        np.savez_compressed(
            focused_vectors,
            focused=np.asarray([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float16),
        )
        cache = MultiViewEffectCache(
            base_metadata, base_vectors, focused_metadata, focused_vectors
        )
        group = {
            "group_id": "fixture-sdk::uart.write",
            "sdk_id": "fixture-sdk",
            "operation_id": "uart.write",
            "candidates": [
                {"entity_id": "entity-1", "symbol": "uart_write", "features": {}, "static_score": 0.1},
                {"entity_id": "entity-2", "symbol": "uart_status", "features": {}, "static_score": 0.1},
            ],
        }
        ranker = MultiViewEffectRanker(cache)
        ranker.fit_scaler(group["candidates"])
        components = ranker.group_components(group)
        self.assertEqual(
            set(components), {"fusion", "full", "focused", "graph", "structured"}
        )
        self.assertEqual(operation_constraint_penalty(group["candidates"][0], "uart.write"), 0.0)
        self.assertEqual(operation_constraint_penalty(group["candidates"][1], "uart.write"), 1.0)

        joint_metadata = self.root / "joint-metadata.json"
        joint_vectors = self.root / "joint-vectors.npz"
        write_json(joint_metadata, {
            "joint_keys": [
                "fixture-sdk::uart.write::entity-1",
                "fixture-sdk::uart.write::entity-2",
            ],
            "shortlist": {"per_channel": 15},
        })
        np.savez_compressed(
            joint_vectors,
            joint=np.asarray([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float16),
        )
        joint_cache = JointPairCache(joint_metadata, joint_vectors)
        joint_ranker = JointPairRanker(cache, joint_cache)
        joint_ranker.fit_scaler([group])
        joint_components = joint_ranker.group_components(group)
        self.assertEqual(
            set(joint_components), {"fusion", "joint", "scalar", "indices"}
        )
        self.assertEqual(joint_components["indices"], [0, 1])

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
        self.assertIn("sysint", identifier_tokens("Cy_SysInt_SetVector"))
        self.assertIn("i2s", identifier_tokens("LL_RCC_SetI2SClockSource"))

    def test_cross_operation_coherence_rewards_complete_public_api_family(self) -> None:
        groups = []
        for operation, effect in (("configure", 0.7), ("write", 0.9), ("read", 0.8)):
            candidates = [{
                "entity_id": f"public-{operation}",
                "symbol": f"uart_{operation}",
                "file": "drivers/uart.c",
                "api_family": "uart",
                "source_role": "sdk-driver",
                "features": {
                    "hw-transitive-operation-effect": effect,
                    "operation-contract-retrieval": 0.8,
                    "generic-operation-fit": 0.9,
                    "source-role-prior": 0.9,
                    "hw-public-boundary": 1.0,
                },
                "label": 0,
            }]
            if operation == "write":
                candidates.append({
                    "entity_id": "debug-write",
                    "symbol": "debug_uart_write",
                    "file": "examples/debug_uart.c",
                    "api_family": "debug_uart",
                    "source_role": "example-test",
                    "features": {
                        "hw-transitive-operation-effect": 0.95,
                        "operation-contract-retrieval": 0.75,
                        "generic-operation-fit": 0.55,
                        "source-role-prior": 0.06,
                    },
                    "label": 1,
                })
            groups.append({
                "group_id": f"fixture::uart.{operation}",
                "sdk_id": "fixture",
                "capability": "uart",
                "operation": operation,
                "operation_id": f"uart.{operation}",
                "candidates": candidates,
            })
        enriched = enrich_dataset_with_cross_operation_coherence({"groups": groups})
        write_group = next(
            item for item in enriched["groups"] if item["operation_id"] == "uart.write"
        )
        public, debug = write_group["candidates"]
        self.assertGreater(
            public["features"]["xop-family-operation-coverage"],
            debug["features"]["xop-family-operation-coverage"],
        )
        self.assertGreater(
            public["features"]["xop-family-complement-support"],
            debug["features"]["xop-family-complement-support"],
        )
        self.assertIn("xop-consensus-margin", public["features"])
        self.assertIn("xop-signal-agreement", public["features"])
        self.assertEqual(enriched["cross_operation_coherence"]["leakage_control"],
                         "labels and truth metadata are not read")

    def test_coherence_family_key_removes_action_but_keeps_timer_mode(self) -> None:
        self.assertEqual(
            coherence_family_key("uart", {"symbol": "HAL_UART_Transmit"}),
            "hal_uart",
        )
        self.assertEqual(
            coherence_family_key("uart", {"symbol": "HAL_UART_Receive"}),
            "hal_uart",
        )
        self.assertEqual(
            coherence_family_key("timer", {"symbol": "HAL_TIM_Base_Start"}),
            "hal_tim_base",
        )

    def test_ranking_diagnostics_preserve_contract_dominant_public_api(self) -> None:
        group = {
            "group_id": "fixture::timer.start",
            "capability": "timer",
            "operation": "start",
            "operation_id": "timer.start",
            "candidates": [
                {
                    "entity_id": "base",
                    "symbol": "HAL_TIM_Base_Start",
                    "file": "Drivers/STM32_HAL_Driver/Src/stm32_hal_tim.c",
                    "static_score": 0.80,
                    "candidate_text": "file: Drivers/STM32_HAL_Driver/Src/stm32_hal_tim.c\nsymbol: HAL_TIM_Base_Start\nsignature: int HAL_TIM_Base_Start(void *handle)\nincludes:\ncalls:",
                    "features": {
                        "operation-exact": 1.0,
                        "operation-substring": 0.0,
                        "parameterized-toggle": 0.0,
                        "field-late-interaction": 0.78,
                    },
                },
                {
                    "entity_id": "pwm",
                    "symbol": "HAL_TIMEx_PWMN_Start_DMA",
                    "file": "Drivers/STM32_HAL_Driver/Src/stm32_hal_tim_ex.c",
                    "static_score": 0.90,
                    "candidate_text": "file: Drivers/STM32_HAL_Driver/Src/stm32_hal_tim_ex.c\nsymbol: HAL_TIMEx_PWMN_Start_DMA\nsignature: int HAL_TIMEx_PWMN_Start_DMA(void *handle)\nincludes:\ncalls:",
                    "features": {
                        "operation-exact": 1.0,
                        "operation-substring": 0.0,
                        "parameterized-toggle": 0.0,
                        "field-late-interaction": 0.84,
                    },
                },
            ],
        }
        enrich_group_with_structured_retrieval(group)
        scores, diagnostics = complete_structured_scores(group)
        selected = max(range(len(scores)), key=scores.__getitem__)
        evidence = deterministic_ranking_evidence(group, scores, diagnostics)
        self.assertEqual(group["candidates"][selected]["symbol"], "HAL_TIM_Base_Start")
        self.assertEqual(evidence["selected_symbol"], "HAL_TIM_Base_Start")
        self.assertFalse(evidence["low_score"])

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

    def test_frozen_lambdamart_bundle_drives_operation_resolver(self) -> None:
        ir = SDKIngestor().ingest(self.sdk, "fixture-sdk")
        resolver = SemanticResolver()
        pool = resolver.candidate_pool(ir, "uart")
        preferred = {
            "configure": "uart_configure",
            "write": "uart_send_data",
            "read": "uart_receive_data",
        }
        operations = {}
        for operation, symbol in preferred.items():
            rows = [
                {
                    "entity_id": item["entity_id"],
                    "symbol": item["symbol"],
                    "score": 2.0 if item["symbol"] == symbol else -1.0,
                    "rank": 1 if item["symbol"] == symbol else 2,
                }
                for item in pool
            ]
            rows.sort(key=lambda item: (-item["score"], item["entity_id"]))
            operations[f"uart.{operation}"] = {
                "candidate_count": len(rows),
                "selected_entity_id": rows[0]["entity_id"],
                "selected_symbol": rows[0]["symbol"],
                "candidates": rows,
            }
        bundle = self.root / "frozen-ranking.json"
        write_json(bundle, {
            "schema_version": "frozen-operation-ranking-v1",
            "contains_labels": False,
            "method": "fixture-lambdamart",
            "sdk": {"id": ir["sdk"]["id"], "digest": ir["sdk"]["digest"]},
            "model": {"sha256": "fixture"},
            "feature_contract": {"operation_count": 3},
            "operations": operations,
        })
        resolution = resolver.resolve(
            ir,
            ["uart"],
            method="operation-lambdamart",
            model_path=bundle,
        )
        rankings = resolution["mappings"][0]["operation_rankings"]
        self.assertEqual(
            {item["operation"]: item["selected_symbol"] for item in rankings},
            preferred,
        )
        self.assertEqual(
            resolution["method"], "frozen-multiview-lambdamart-operation-resolution"
        )
        self.assertIn("bundle_sha256", resolution["operation_ranking_model"])

    def test_frozen_lambdamart_bundle_rejects_nonfinite_scores(self) -> None:
        bundle = self.root / "invalid-frozen-ranking.json"
        write_json(bundle, {
            "schema_version": "frozen-operation-ranking-v1",
            "contains_labels": False,
            "method": "fixture-lambdamart",
            "sdk": {"id": "fixture-sdk", "digest": "fixture"},
            "model": {"sha256": "fixture"},
            "feature_contract": {"operation_count": 1},
            "operations": {
                "uart.write": {
                    "candidate_count": 1,
                    "selected_entity_id": "candidate",
                    "selected_symbol": "uart_write",
                    "candidates": [{
                        "entity_id": "candidate",
                        "symbol": "uart_write",
                        "score": float("inf"),
                        "rank": 1,
                    }],
                }
            },
        })
        with self.assertRaisesRegex(ValueError, "non-finite candidate score"):
            FrozenOperationRanker(bundle)

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

    def test_structured_runtime_always_selects_top1_and_keeps_diagnostics(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "fixture-sdk")
        resolver = SemanticResolver()
        candidates = resolver.candidate_pool(ir, "uart")
        functions = {item["id"]: item for item in ir["functions"]}

        class FixedFieldRanker:
            def score_operations(self, capability, operations, ranked, function_map):
                del capability, function_map
                return {
                    operation: {
                        item["entity_id"]: {
                            "base": 0.0,
                            "adapted": 0.0,
                            "field": float(
                                operation == "write" and item["symbol"] == "uart_send_data"
                            ),
                        }
                        for item in ranked
                    }
                    for operation in operations
                }

        result = resolver._resolve_operations(
            "uart",
            candidates,
            functions,
            threshold=0.99,
            top_k=8,
            minimum_margin=1.0,
            semantic_ranker=FixedFieldRanker(),
            semantic_weights={"static": 0.0, "base": 0.0, "adapted": 0.0, "field": 1.0},
            structured_retrieval=True,
            compile_feedback={
                ("uart", operation, item["entity_id"]): float(
                    item["symbol"] == "uart_receive_data"
                )
                for operation in CAPABILITY_SCHEMA["uart"]["operations"]
                for item in candidates
            },
            compile_feedback_weight=1.0,
        )
        write_ranking = next(
            item for item in result["operation_rankings"] if item["operation"] == "write"
        )
        evidence = write_ranking["ranking_evidence"]
        self.assertIsNotNone(write_ranking["selected_entity_id"])
        self.assertEqual(write_ranking["selected_entity_id"], evidence["selected_entity_id"])
        self.assertEqual(write_ranking["selected_symbol"], "uart_receive_data")

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

    def test_operation_dataset_records_unretrievable_human_truth(self) -> None:
        ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "train-sdk")
        meta = {
            "sdk_id": "train-sdk",
            "vendor": "Train",
            "independence_group": "train-vendor",
            "role": "train",
        }
        truth = {
            "sdk_id": "train-sdk",
            "operations": {
                "uart.configure": {
                    "group_status": "complete",
                    "symbols": ["HardwareSerial::begin"],
                },
            },
        }
        with self.assertRaises(GroundTruthError):
            build_operation_dataset([(meta, ir, truth, self.root / "train-ir.json")])

        dataset = build_operation_dataset(
            [(meta, ir, truth, self.root / "train-ir.json")],
            unretrievable_truth_policy="skip-missing",
        )
        self.assertEqual(dataset["summary"]["truth_alignment_groups"], 1)
        self.assertEqual(dataset["summary"]["unretrievable_truth_symbols"], 1)
        self.assertTrue(any(
            item["reason"] == "unretrievable-positive-label"
            for item in dataset["skipped"]
        ))

    def test_operation_dataset_sampling_is_independent_between_groups(self) -> None:
        train_ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "train-sdk")
        external_ir = SDKIngestor(frontend_mode="hybrid").ingest(self.sdk, "external-sdk")
        train_meta = {
            "sdk_id": "train-sdk",
            "vendor": "Train",
            "independence_group": "train-vendor",
            "role": "train",
        }
        external_meta = {
            "sdk_id": "external-sdk",
            "vendor": "External",
            "independence_group": "external-board",
            "role": "external-test",
        }
        truth = {
            "sdk_id": "external-sdk",
            "operations": {
                "uart.configure": {"symbols": ["uart_configure"]},
                "uart.write": {"symbols": ["uart_send_data"]},
                "uart.read": {"symbols": ["uart_receive_data"]},
            },
        }
        external_only = build_operation_dataset([
            (external_meta, external_ir, truth, self.root / "external-ir.json"),
        ])
        with_training = build_operation_dataset([
            (train_meta, train_ir, None, self.root / "train-ir.json"),
            (external_meta, external_ir, truth, self.root / "external-ir.json"),
        ])

        def external_candidates(dataset):
            return {
                group["group_id"]: [item["entity_id"] for item in group["candidates"]]
                for group in dataset["groups"]
                if group["role"] == "external-test"
            }

        self.assertEqual(
            external_candidates(external_only),
            external_candidates(with_training),
        )

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
        self.assertIn('rt_device_find("pin") == RT_NULL', board_source)
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
        self.assertIn('rt_kprintf("%s", banner)', source)
        self.assertIn("rt_device_open", source)
        self.assertIn("rt_pin_write", source)
        self.assertIn("rt_timer_start", source)
        self.assertIn('rt_device_find(bspforge_hwtimer_name)', source)

    def test_k210_binding_validation_emits_observable_hardware_tests(self) -> None:
        bsp = self.root / "k210-binding-validation"
        RTThreadValidationGenerator().generate(
            bsp,
            {
                "board": "k210",
                "binding_validation": True,
                "hwtimer": "bsptim0",
                "uart": "bspuart1",
                "uart_channel": 0,
                "uart_tx_fpioa_io": 7,
                "uart_rx_fpioa_io": 6,
                "gpio_fpioa_io": 8,
                "gpio_binding_pin": 29,
                "gpio_input_fpioa_io": 9,
                "gpio_input_binding_pin": 28,
            },
        )
        source = (bsp / "applications" / "bspforge_validation.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("bspforge_clock_frequency", source)
        self.assertIn("FUNC_UART1_TX + 2 * 0", source)
        self.assertIn("FUNC_UART1_RX + 2 * 0", source)
        self.assertIn("FUNC_GPIOHS0 + 29", source)
        self.assertIn("FUNC_GPIOHS0 + 28", source)
        self.assertIn("output_val.u32[0]", source)
        self.assertIn("HWTIMER_MODE_ONESHOT", source)
        self.assertIn('strcmp(command, "interrupt.basic")', source)
        self.assertIn('strcmp(command, "uart.loopback")', source)
        self.assertIn('strcmp(command, "gpio.irq")', source)

    def test_rtthread_backend_can_disable_nonrequired_board_feature(self) -> None:
        config = self.root / "rtconfig.h"
        config.write_text(
            "#define RT_USING_SMP\n#define RT_CPUS_NR 2\n#define RT_USING_SERIAL\n",
            encoding="utf-8",
        )
        RTThreadBackend._disable_rtthread_features(config, ["RT_USING_SMP"])
        value = config.read_text(encoding="utf-8")
        self.assertNotIn("#define RT_USING_SMP", value)
        self.assertIn("#define RT_CPUS_NR 2", value)
        self.assertIn("#define RT_USING_SERIAL", value)

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
            {
                "sdk_profile": "k210",
                "binding_strategy": "generated-sdk-adapter",
                "_binding_plan": {
                    "capabilities": [{"capability": "uart", "status": "resolved"}],
                    "summary": {"resolved": 1},
                },
            },
        )
        self.assertEqual(manifest["backend"], "zephyr")
        self.assertTrue((output / "app" / "prj.conf").is_file())
        self.assertTrue((output / "app" / "src" / "main.c").is_file())
        self.assertEqual(manifest["device_model"]["summary"]["devices"], 4)
        self.assertIn(
            "bspforge_zephyr_uart_device",
            manifest["device_model"]["registration_symbols"],
        )
        self.assertIn(
            "bspforge_zephyr_validation_run",
            manifest["device_model"]["registration_symbols"],
        )
        source = (output / "app" / "src" / "main.c").read_text(encoding="utf-8")
        self.assertIn("if (bspforge_zephyr_validation_run() != 0)", source)
        self.assertIn("k_busy_wait(50);", source)

    def test_zephyr_native_device_model_registers_standard_driver_apis(self) -> None:
        source_dir = self.root / "zephyr-devices"
        source_dir.mkdir()
        manifest = ZephyrDeviceModelGenerator().generate(source_dir)
        source = Path(manifest["source"]).read_text(encoding="utf-8")
        self.assertEqual(manifest["summary"]["devices"], 4)
        for api in ("clock_control", "uart", "gpio", "counter"):
            self.assertIn(f"DEVICE_API({api},", source)
        for device in ("clock", "uart", "gpio", "counter"):
            self.assertIn(f"DEVICE_DEFINE(bspforge_{device}", source)
            self.assertIn(f"bspforge_zephyr_{device}_device", source)
        self.assertIn("gpio_fire_callbacks", source)
        self.assertIn("counter_alarm_callback_t", source)

    def test_zephyr_native_validation_uses_only_standard_device_apis(self) -> None:
        source_dir = self.root / "zephyr-native-validation"
        source_dir.mkdir()
        manifest = ZephyrValidationGenerator().generate(
            source_dir,
            "k210",
            "native-device-test",
            functional=True,
            native_devices=True,
        )
        source = Path(manifest["source"]).read_text(encoding="utf-8")
        self.assertIn('#include "bspforge_zephyr_devices.h"', source)
        self.assertNotIn('#include "bspforge_bindings.h"', source)
        for call in (
            "clock_control_get_rate",
            "uart_configure",
            "uart_poll_out",
            "gpio_pin_configure",
            "gpio_add_callback",
            "counter_set_channel_alarm",
            "counter_set_top_value",
        ):
            self.assertIn(call, source)
        self.assertNotIn("bspforge_uart_write", source)
        self.assertNotIn("bspforge_gpio_write", source)

    def test_zephyr_functional_validation_covers_common_board_protocol(self) -> None:
        source_dir = self.root / "zephyr-functional"
        source_dir.mkdir()
        manifest = ZephyrValidationGenerator().generate(
            source_dir, "k210", "fixture-build", functional=True
        )
        source = Path(manifest["source"]).read_text(encoding="utf-8")
        for command in (
            "info",
            "clock.basic",
            "interrupt.basic",
            "uart.loopback",
            "gpio.toggle",
            "gpio.irq",
            "timer.oneshot",
            "timer.periodic",
            "stability",
        ):
            self.assertIn(f'"{command}"', source)
        self.assertIn('#include "bspforge_bindings.h"', source)
        self.assertIn("bspforge_timer_target = expected", source)
        self.assertIn("bspforge_timer_quiesce();", source)
        self.assertNotIn('const char *status = "unsupported"', source)

    def test_zephyr_functional_cmake_compiles_analyzed_sdk_sources(self) -> None:
        cmake = ZephyrBackend._cmake_source(
            self.sdk, ["lib/drivers/uart.c"], functional=True, native_devices=True
        )
        self.assertIn("src/bspforge_bindings.c", cmake)
        self.assertIn("src/bspforge_zephyr_devices.c", cmake)
        self.assertIn(str((self.sdk / "lib/drivers/uart.c").resolve()), cmake)
        self.assertIn("target_include_directories(app PRIVATE", cmake)
        self.assertIn("asm=__asm__", cmake)

    def test_zephyr_k210_binding_validates_and_uses_configured_timer_irq(self) -> None:
        source = ZephyrBindingGenerator._source(
            {"timer_device": 2, "timer_channel": 3}
        )
        self.assertIn("#define BSPFORGE_TIMER_DEVICE 2U", source)
        self.assertIn("#define BSPFORGE_TIMER_CHANNEL 3U", source)
        self.assertIn("BSPFORGE_TIMER_CHANNEL / 2U", source)
        with self.assertRaisesRegex(ValueError, "timer device/channel"):
            ZephyrBindingGenerator._source({"timer_device": 3})

    def test_k210_zephyr_port_enables_fpioa_clock_before_pin_mapping(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "ports/zephyr-k210/soc/bspforge/k210/soc.c"
        ).read_text(encoding="utf-8")
        clock_enable = source.index("*clk_en_peri |= K210_SYSCTL_FPIOA_CLK_EN")
        rx_mapping = source.index("fpioa[K210_UARTHS_RX_PIN]")
        self.assertLess(clock_enable, rx_mapping)

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

    def test_device_contract_is_not_compared_across_rtos_backends(self) -> None:
        resolution = {"mappings": []}
        truth = {
            "id": "rtthread-only-contract",
            "device_model": {"backend": "rtthread"},
            "capabilities": {
                "uart": {
                    "semantic_symbols": [],
                    "binding_symbols": [],
                    "device_operations": ["configure", "putc", "getc"],
                }
            },
        }
        metrics = ExperimentEvaluator().evaluate(
            resolution,
            {"bindings": []},
            {"backend": "zephyr", "devices": []},
            truth,
        )
        self.assertFalse(metrics["device_model_contract"]["matches"])
        self.assertIsNone(metrics["summary"]["device_operation_macro_recall"])

    def test_hardware_protocol_report_excludes_unsupported_commands(self) -> None:
        class FakeTransport:
            def __init__(self) -> None:
                self.lines = [
                    b'\x1b[0m{"bspforge":true,"protocol":"1.0","event":"boot"}\n'
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

        firmware = self.root / "fixture.bin"
        firmware.write_bytes(b"firmware")
        report = HardwareTestRunner(
            FakeTransport(),
            "fixture",
            "rtthread",
            timeout=0.1,
            firmware_artifact=firmware,
        ).run(commands=["info", "gpio.irq"])
        self.assertEqual(report["summary"]["boot_successes"], 1)
        self.assertEqual(report["summary"]["commands_passed"], 1)
        self.assertEqual(report["summary"]["commands_applicable"], 1)
        self.assertEqual(report["summary"]["unsupported"], 1)
        self.assertEqual(report["firmware_artifact"]["size"], 8)
        self.assertEqual(len(report["firmware_artifact"]["sha256"]), 64)

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
