from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.closure_solver import ClosureSolver
from bspforge.common import read_json, write_json
from bspforge.ir_store import IRStore
from bspforge.os_backend import RTThreadBackend
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.semantic_resolver import SemanticResolver


class Pipeline:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()

    def run(self, config_path: Path, build: bool = True) -> dict[str, Any]:
        config = read_json(config_path.resolve())
        run_id = config.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_root = self._path(config.get("workspace", "workspace")) / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)

        sdk_root = self._path(config["sdk"]["path"])
        ir = SDKIngestor().ingest(sdk_root, config["sdk"]["id"])
        store = IRStore(self._path(config.get("ir_store", "workspace/ir")))
        ir_path = store.put(ir)
        write_json(run_root / "01-sdk-ir.json", ir)

        resolver_config = config.get("resolver", {})
        resolution = SemanticResolver().resolve(
            ir,
            capability_names=resolver_config.get("capabilities"),
            threshold=float(resolver_config.get("threshold", 0.42)),
            top_k=int(resolver_config.get("top_k", 8)),
        )
        write_json(run_root / "02-semantic-resolution.json", resolution)

        closure = ClosureSolver().solve(ir, resolution)
        write_json(run_root / "03-build-closure.json", closure)

        backend_config = config["backend"]
        if backend_config["type"] != "rtthread":
            raise ValueError(f"Unsupported backend: {backend_config['type']}")
        backend = RTThreadBackend()
        generated_root = self._path(backend_config.get("output", f"workspace/generated/{run_id}"))
        generation = backend.generate(
            self._path(backend_config["rtthread_root"]),
            backend_config["board"],
            generated_root,
            ir,
            resolution,
            closure,
        )
        write_json(run_root / "04-generation.json", generation)

        build_result: dict[str, Any] = {"skipped": True}
        if build:
            toolchain_bin = self._path(config["toolchain"]["bin"])
            build_config = config.get("build", {})
            jobs = int(build_config.get("jobs", max(1, min(os.cpu_count() or 1, 8))))
            max_iterations = max(1, int(build_config.get("max_iterations", 3)))
            diagnoser = BuildDiagnoser()
            solver = ClosureSolver()
            iterations: list[dict[str, Any]] = []
            repairs_applied = 0
            stop_reason = "max-iterations"
            returncode = 1
            output = ""
            diagnosis: dict[str, Any] = {}

            for iteration in range(1, max_iterations + 1):
                metadata_dir = Path(generation["bsp_path"]) / "bspforge"
                returncode, output = backend.build(metadata_dir, toolchain_bin, jobs=jobs)
                iteration_log = run_root / f"05-build-iteration-{iteration:02d}.log"
                iteration_log.write_text(output, encoding="utf-8")
                diagnosis = diagnoser.diagnose(output, returncode)
                repair_proposal = diagnoser.propose_repairs(ir, diagnosis, closure)
                iteration_record = {
                    "iteration": iteration,
                    "returncode": returncode,
                    "success": returncode == 0,
                    "log": str(iteration_log),
                    "diagnosis": diagnosis,
                    "repair_proposal": repair_proposal,
                    "closure_id": closure["id"],
                }
                iterations.append(iteration_record)
                write_json(run_root / f"06-diagnosis-iteration-{iteration:02d}.json", iteration_record)

                if returncode == 0:
                    stop_reason = "build-succeeded"
                    break
                if iteration >= max_iterations:
                    stop_reason = "max-iterations"
                    break

                closure, changed = solver.apply_repairs(ir, closure, repair_proposal, iteration)
                if not changed:
                    stop_reason = "no-new-actionable-constraint"
                    break
                repairs_applied += len(closure["repair_history"][-1]["applied"])
                write_json(run_root / f"03-build-closure-iteration-{iteration + 1:02d}.json", closure)
                generation = backend.generate(
                    self._path(backend_config["rtthread_root"]),
                    backend_config["board"],
                    generated_root,
                    ir,
                    resolution,
                    closure,
                )
                write_json(run_root / f"04-generation-iteration-{iteration + 1:02d}.json", generation)

            log_path = run_root / "05-build.log"
            log_path.write_text(output, encoding="utf-8")
            write_json(run_root / "06-build-diagnosis.json", diagnosis)
            write_json(run_root / "07-build-iterations.json", {
                "max_iterations": max_iterations,
                "attempts": len(iterations),
                "stop_reason": stop_reason,
                "repairs_applied": repairs_applied,
                "iterations": iterations,
            })
            write_json(run_root / "03-build-closure.json", closure)
            write_json(run_root / "04-generation.json", generation)
            bsp_path = Path(generation["bsp_path"])
            artifacts = [
                str(path) for path in (bsp_path / "rtthread.elf", bsp_path / "rtthread.bin") if path.exists()
            ]
            build_result = {
                "skipped": False,
                "returncode": returncode,
                "success": returncode == 0,
                "log": str(log_path),
                "diagnosis": diagnosis,
                "artifacts": artifacts,
                "attempts": len(iterations),
                "max_iterations": max_iterations,
                "stop_reason": stop_reason,
                "repairs_applied": repairs_applied,
                "iterations": iterations,
            }

        report = {
            "run_id": run_id,
            "config": str(config_path.resolve()),
            "environment": self._environment(),
            "ir_store_path": str(ir_path),
            "run_root": str(run_root),
            "generated_root": str(generated_root),
            "sdk_stats": ir["stats"],
            "resolution": resolution["summary"],
            "closure": closure["summary"],
            "build": build_result,
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
