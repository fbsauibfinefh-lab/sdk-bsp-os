#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.evaluation import ExperimentEvaluator
from bspforge.semantic_resolver import SemanticResolver


def main() -> int:
    parser = argparse.ArgumentParser(description="比较固定权重与学习排序语义恢复")
    parser.add_argument("--ir", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.42)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ir = read_json(args.ir)
    truth = read_json(args.ground_truth)
    capabilities = list(truth["capabilities"])
    evaluator = ExperimentEvaluator()
    results = []
    for method in ("weighted", "learned", "hybrid"):
        resolution = SemanticResolver().resolve(
            ir,
            capabilities,
            threshold=args.threshold,
            top_k=args.top_k,
            method=method,
            model_path=args.model if method in {"learned", "hybrid"} else None,
        )
        metrics = evaluator.evaluate_resolution(resolution, truth)
        results.append({
            "method": method,
            "resolution_method": resolution["method"],
            "metrics": metrics["summary"],
        })
    weighted = results[0]
    for result in results[1:]:
        result["delta_macro_f1"] = (
            round(result["metrics"]["macro_f1"] - weighted["metrics"]["macro_f1"], 4)
            if result["metrics"]["macro_f1"] is not None
            and weighted["metrics"]["macro_f1"] is not None
            else None
        )
    write_json(args.output, {
        "schema_version": "1.0",
        "ground_truth_id": truth.get("id", "unknown"),
        "protocol": "test SDK must be excluded from ranker training",
        "results": results,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
