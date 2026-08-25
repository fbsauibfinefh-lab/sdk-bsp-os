from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.binding_planner import BindingPlanner
from bspforge.closure_solver import ClosureSolver
from bspforge.common import read_json, write_json
from bspforge.evaluation import ExperimentEvaluator
from bspforge.ir_store import IRStore
from bspforge.os_backend import RTThreadBackend, ZephyrBackend
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.semantic_resolver import SemanticResolver


class Pipeline:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def run(self, config_path: Path, build: bool = True) -> dict[str, Any]:
        run_started = perf_counter()
        timings: dict[str, Any] = {}
        config = read_json(config_path.resolve())
        run_id = config.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_root = self._path(config.get("workspace", "workspace")) / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)

        stage_started = perf_counter()
        sdk_root = self._path(config["sdk"]["path"])
        ingestor_config = config.get("ingestor", {})
        compile_commands = ingestor_config.get("compile_commands")
        ir = SDKIngestor(
            frontend_mode=ingestor_config.get("mode", "hybrid"),
            compile_commands=self._path(compile_commands) if compile_commands else None,
            clang_binary=ingestor_config.get("clang_binary", "clang"),
        ).ingest(sdk_root, config["sdk"]["id"])
        store = IRStore(self._path(config.get("ir_store", "workspace/ir")))
        ir_path = store.put(ir)
        write_json(run_root / "01-sdk-ir.json", ir)
        timings["sdk_ingest_seconds"] = round(perf_counter() - stage_started, 6)

        stage_started = perf_counter()
        resolver_config = config.get("resolver", {})
        resolution = SemanticResolver().resolve(
            ir,
            capability_names=resolver_config.get("capabilities"),
            threshold=float(resolver_config.get("threshold", 0.42)),
            top_k=int(resolver_config.get("top_k", 8)),
            evidence_weights=resolver_config.get("weights"),
            method=resolver_config.get("method", "weighted"),
            model_path=(
                self._path(resolver_config["model_path"])
                if resolver_config.get("model_path")
                else None
            ),
            hybrid_weight=resolver_config.get("hybrid_weight"),
        )
        write_json(run_root / "02-semantic-resolution.json", resolution)
        binding_plan = BindingPlanner().plan(ir, resolution)
        write_json(run_root / "02b-canonical-binding-plan.json", binding_plan)
        timings["semantic_resolution_seconds"] = round(perf_counter() - stage_started, 6)

        stage_started = perf_counter()
        target_context = {
            "architecture": config.get("toolchain", {}).get("architecture"),
            "toolchain": config.get("toolchain", {}).get("prefix"),
            "board": config.get("backend", {}).get("board"),
            "sdk_profile": config.get("backend", {}).get("sdk_profile"),
            **config.get("closure", {}).get("target", {}),
        }
        closure = ClosureSolver().solve(ir, resolution, target_context)
        write_json(run_root / "03-build-closure.json", closure)
        timings["closure_solver_seconds"] = round(perf_counter() - stage_started, 6)

        backend_config = dict(config["backend"])
        backend_config["_binding_plan"] = binding_plan
        for key in ("project_template", "libraries_root", "libs_root", "board_port"):
            if backend_config.get(key):
                backend_config[key] = str(self._path(backend_config[key]))
        if backend_config["type"] == "rtthread":
            backend = RTThreadBackend()
            os_root = self._path(backend_config["rtthread_root"])
        elif backend_config["type"] == "zephyr":
            backend = ZephyrBackend()
            os_root = self._path(backend_config["zephyr_root"])
        else:
            raise ValueError(f"Unsupported backend: {backend_config['type']}")
        generated_root = self._path(backend_config.get("output", f"workspace/generated/{run_id}"))
        stage_started = perf_counter()
        generation = backend.generate(
            os_root,
            backend_config["board"],
            generated_root,
            ir,
            resolution,
            closure,
            backend_config,
        )
        write_json(run_root / "04-generation.json", generation)
        timings["initial_generation_seconds"] = round(perf_counter() - stage_started, 6)

        build_result: dict[str, Any] = {"skipped": True}
        if build:
            toolchain_bin = self._path(config["toolchain"]["bin"])
            build_config = config.get("build", {})
            jobs = int(build_config.get("jobs", max(1, min(os.cpu_count() or 1, 8))))
            max_iterations = max(1, int(build_config.get("max_iterations", 3)))
            maximum_repair_risk = build_config.get("max_auto_repair_risk", "low")
            diagnoser = BuildDiagnoser()
            solver = ClosureSolver()
            iterations: list[dict[str, Any]] = []
            repair_transactions: list[dict[str, Any]] = []
            pending_transaction: dict[str, Any] | None = None
            repairs_applied = 0
            stop_reason = "max-iterations"
            returncode = 1
            output = ""
            diagnosis: dict[str, Any] = {}
            build_seconds = 0.0
            regeneration_seconds = 0.0

            for iteration in range(1, max_iterations + 1):
                metadata_dir = Path(generation["bsp_path"]) / "bspforge"
                iteration_started = perf_counter()
                returncode, output = backend.build(metadata_dir, toolchain_bin, jobs=jobs)
                iteration_seconds = round(perf_counter() - iteration_started, 6)
                build_seconds += iteration_seconds
                iteration_log = run_root / f"05-build-iteration-{iteration:02d}.log"
                iteration_log.write_text(output, encoding="utf-8")
                diagnosis = diagnoser.diagnose(output, returncode)
                repair_rolled_back = False
                if pending_transaction is not None:
                    pending_transaction["result_diagnostic_cost"] = self._diagnostic_cost(diagnosis)
                    if returncode == 0:
                        pending_transaction["status"] = "committed"
                    elif (
                        pending_transaction["result_diagnostic_cost"]
                        > pending_transaction["base_diagnostic_cost"]
                    ):
                        pending_transaction["status"] = "rolled-back"
                        pending_transaction["reason"] = "diagnostic-cost-regression"
                        closure = pending_transaction["base_closure"]
                        regeneration_started = perf_counter()
                        generation = backend.generate(
                            os_root,
                            backend_config["board"],
                            generated_root,
                            ir,
                            resolution,
                            closure,
                            backend_config,
                        )
                        regeneration_seconds += perf_counter() - regeneration_started
                        stop_reason = "repair-regression-rolled-back"
                        repair_rolled_back = True
                    else:
                        pending_transaction["status"] = "retained"
                    pending_transaction = None
                repair_proposal = diagnoser.propose_repairs(ir, diagnosis, closure)
                iteration_record = {
                    "iteration": iteration,
                    "returncode": returncode,
                    "success": returncode == 0,
                    "log": str(iteration_log),
                    "diagnosis": diagnosis,
                    "repair_proposal": repair_proposal,
                    "closure_id": closure["id"],
                    "duration_seconds": iteration_seconds,
                    "repair_rolled_back": repair_rolled_back,
                }
                iterations.append(iteration_record)
                write_json(run_root / f"06-diagnosis-iteration-{iteration:02d}.json", iteration_record)

                if repair_rolled_back:
                    break
                if returncode == 0:
                    stop_reason = "build-succeeded"
                    break
                if iteration >= max_iterations:
                    stop_reason = "max-iterations"
                    break

                base_closure = closure
                repaired_closure, changed = solver.apply_repairs(
                    ir,
                    closure,
                    repair_proposal,
                    iteration,
                    maximum_risk=maximum_repair_risk,
                )
                if not changed:
                    stop_reason = "no-new-actionable-constraint"
                    break
                transaction = {
                    "iteration": iteration,
                    "base_closure_id": base_closure["id"],
                    "candidate_closure_id": repaired_closure["id"],
                    "base_diagnostic_cost": self._diagnostic_cost(diagnosis),
                    "status": "pending",
                    "base_closure": base_closure,
                }
                repair_transactions.append(transaction)
                pending_transaction = transaction
                closure = repaired_closure
                repairs_applied += len(closure["repair_history"][-1]["applied"])
                write_json(run_root / f"03-build-closure-iteration-{iteration + 1:02d}.json", closure)
                regeneration_started = perf_counter()
                generation = backend.generate(
                    os_root,
                    backend_config["board"],
                    generated_root,
                    ir,
                    resolution,
                    closure,
                    backend_config,
                )
                regeneration_seconds += perf_counter() - regeneration_started
                write_json(run_root / f"04-generation-iteration-{iteration + 1:02d}.json", generation)

            log_path = run_root / "05-build.log"
            log_path.write_text(output, encoding="utf-8")
            write_json(run_root / "06-build-diagnosis.json", diagnosis)
            write_json(run_root / "03-build-closure.json", closure)
            write_json(run_root / "04-generation.json", generation)
            bsp_path = Path(generation["bsp_path"])
            verification = (
                backend.verify(bsp_path / "bspforge", toolchain_bin)
                if returncode == 0
                else {"success": False, "skipped": True, "reason": "link-failed"}
            )
            write_json(run_root / "08-artifact-verification.json", verification)
            artifacts = [item["path"] for item in verification.get("artifacts", [])]
            verified_success = returncode == 0 and verification["success"]
            if returncode == 0 and not verification["success"]:
                stop_reason = "artifact-verification-failed"
            write_json(run_root / "07-build-iterations.json", {
                "max_iterations": max_iterations,
                "attempts": len(iterations),
                "stop_reason": stop_reason,
                "repairs_applied": repairs_applied,
                "iterations": iterations,
                "repair_transactions": [
                    {key: value for key, value in item.items() if key != "base_closure"}
                    for item in repair_transactions
                ],
            })
            build_result = {
                "skipped": False,
                "returncode": returncode,
                "success": verified_success,
                "log": str(log_path),
                "diagnosis": diagnosis,
                "warnings": diagnoser.summarize_warnings(output),
                "artifacts": artifacts,
                "artifact_verification": verification,
                "attempts": len(iterations),
                "max_iterations": max_iterations,
                "stop_reason": stop_reason,
                "repairs_applied": repairs_applied,
                "iterations": iterations,
            }
            timings["build_seconds"] = round(build_seconds, 6)
            timings["diagnostic_regeneration_seconds"] = round(regeneration_seconds, 6)

        evaluation_result: dict[str, Any] = {"skipped": True}
        evaluation_config = config.get("evaluation", {})
        if evaluation_config.get("ground_truth"):
            evaluation_started = perf_counter()
            evaluator = ExperimentEvaluator()
            ground_truth = read_json(self._path(evaluation_config["ground_truth"]))
            metadata = Path(generation["bsp_path"]) / "bspforge"
            metrics = evaluator.evaluate(
                resolution,
                read_json(metadata / "functional-bindings.json"),
                read_json(metadata / "device-model.json"),
                ground_truth,
            )
            metrics_path = run_root / "09-method-evaluation.json"
            write_json(metrics_path, metrics)
            evaluation_result = {
                "skipped": False,
                "ground_truth_id": ground_truth.get("id", "unknown"),
                "metrics": str(metrics_path),
                "summary": metrics["summary"],
            }
            if evaluation_config.get("run_ablations", False):
                ablations = evaluator.ablate(
                    ir,
                    ground_truth,
                    threshold=float(resolver_config.get("threshold", 0.42)),
                    top_k=int(resolver_config.get("top_k", 8)),
                )
                ablation_path = run_root / "10-evidence-ablations.json"
                write_json(ablation_path, ablations)
                evaluation_result["ablations"] = str(ablation_path)
            timings["evaluation_seconds"] = round(perf_counter() - evaluation_started, 6)

        timings["total_seconds"] = round(perf_counter() - run_started, 6)
        report = {
            "run_id": run_id,
            "config": str(config_path.resolve()),
            "environment": self._environment(),
            "ir_store_path": str(ir_path),
            "run_root": str(run_root),
            "generated_root": str(generated_root),
            "sdk_stats": ir["stats"],
            "resolution": resolution["summary"],
            "binding_plan": binding_plan["summary"],
            "closure": closure["summary"],
            "build": build_result,
            "evaluation": evaluation_result,
            "timings": timings,
        }
        write_json(run_root / "report.json", report)
        return report

    def _path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.repository_root / path

    @staticmethod
    def _environment() -> dict[str, str]:
        try:
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            revision = "uncommitted"
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "git_revision": revision,
            "conda_environment": os.getenv("CONDA_DEFAULT_ENV", ""),
        }

    @staticmethod
    def _diagnostic_cost(diagnosis: dict[str, Any]) -> int:
        weights = {
            "unknown-build-failure": 8,
            "region-overflow": 7,
            "abi-mismatch": 7,
            "multiple-definition": 6,
            "compile-error": 5,
            "missing-library": 4,
            "undefined-symbol": 2,
            "missing-header": 1,
        }
        return sum(weights.get(item["category"], 5) for item in diagnosis["diagnostics"])
