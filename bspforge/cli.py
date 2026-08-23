from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.closure_solver import ClosureSolver
from bspforge.common import read_json, write_json
from bspforge.evaluation import ExperimentEvaluator
from bspforge.ir_store import IRStore
from bspforge.pipeline import Pipeline
from bspforge.sdk_ingestor import SDKIngestor
from bspforge.semantic_resolver import SemanticResolver


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bspforge", description="SDK-to-RTOS BSP research prototype")
    root.add_argument("--repo-root", type=Path, default=Path.cwd())
    commands = root.add_subparsers(dest="command", required=True)

    pipeline = commands.add_parser("pipeline", help="run ingest, resolve, closure, generation, and build")
    pipeline.add_argument("--config", type=Path, required=True)
    pipeline.add_argument("--no-build", action="store_true")

    ingest = commands.add_parser("ingest", help="create and store SDK migration IR")
    ingest.add_argument("--sdk", type=Path, required=True)
    ingest.add_argument("--sdk-id", required=True)
    ingest.add_argument("--store", type=Path, default=Path("workspace/ir"))

    resolve = commands.add_parser("resolve", help="rank SDK entities for migration capabilities")
    resolve.add_argument("--ir", type=Path, required=True)
    resolve.add_argument("--out", type=Path, required=True)
    resolve.add_argument("--threshold", type=float, default=0.42)
    resolve.add_argument("--capability", action="append", dest="capabilities")

    closure = commands.add_parser("closure", help="solve the typed build closure")
    closure.add_argument("--ir", type=Path, required=True)
    closure.add_argument("--resolution", type=Path, required=True)
    closure.add_argument("--out", type=Path, required=True)

    diagnose = commands.add_parser("diagnose", help="structure a compiler/linker log")
    diagnose.add_argument("--log", type=Path, required=True)
    diagnose.add_argument("--returncode", type=int, default=1)
    diagnose.add_argument("--out", type=Path, required=True)

    evaluate = commands.add_parser("evaluate", help="evaluate mappings, bindings, and devices")
    evaluate.add_argument("--resolution", type=Path, required=True)
    evaluate.add_argument("--bindings", type=Path, required=True)
    evaluate.add_argument("--devices", type=Path, required=True)
    evaluate.add_argument("--ground-truth", type=Path, required=True)
    evaluate.add_argument("--out", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "pipeline":
        report = Pipeline(repo_root).run(args.config, build=not args.no_build)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["build"].get("success", True) else 2
    if args.command == "ingest":
        ir = SDKIngestor().ingest(args.sdk, args.sdk_id)
        destination = IRStore(args.store).put(ir)
        print(destination)
        return 0
    if args.command == "resolve":
        value = SemanticResolver().resolve(
            read_json(args.ir), capability_names=args.capabilities, threshold=args.threshold
        )
        write_json(args.out, value)
        print(args.out)
        return 0
    if args.command == "closure":
        value = ClosureSolver().solve(read_json(args.ir), read_json(args.resolution))
        write_json(args.out, value)
        print(args.out)
        return 0
    if args.command == "diagnose":
        value = BuildDiagnoser().diagnose(
            args.log.read_text(encoding="utf-8", errors="replace"), args.returncode
        )
        write_json(args.out, value)
        print(args.out)
        return 0
    if args.command == "evaluate":
        value = ExperimentEvaluator().evaluate(
            read_json(args.resolution),
            read_json(args.bindings),
            read_json(args.devices),
            read_json(args.ground_truth),
        )
        write_json(args.out, value)
        print(args.out)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
