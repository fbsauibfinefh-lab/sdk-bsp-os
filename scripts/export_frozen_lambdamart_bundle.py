#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import lightgbm

from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from evaluate_structural_prior_lambdamart import (
    StructuralPriorCache,
    learned_scores,
    residual_scores,
)


def sorted_candidates(
    group: dict[str, Any], learned: list[float], final: list[float]
) -> list[dict[str, Any]]:
    rows = [
        {
            "entity_id": candidate["entity_id"],
            "symbol": candidate["symbol"],
            "score": round(float(score), 9),
            "learned_score": round(float(learned_score), 9),
        }
        for candidate, learned_score, score in zip(
            group["candidates"], learned, final, strict=True
        )
    ]
    rows.sort(key=lambda item: (-item["score"], item["entity_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导出不含真值标签的冻结 LambdaMART 运行时排序包"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--ir", type=Path, required=True)
    parser.add_argument("--sdk-id", required=True)
    parser.add_argument("--target-architecture", required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--max-bundle-candidates", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    if dataset.get("contains_labels", True):
        raise ValueError("runtime export requires a dataset declaring contains_labels=false")
    leaked = [
        f"{group['group_id']}::{candidate['entity_id']}"
        for group in dataset.get("groups", [])
        for candidate in group.get("candidates", [])
        if "label" in candidate
    ]
    if leaked:
        raise ValueError(f"runtime dataset contains relevance labels: {leaked[0]}")
    if args.max_bundle_candidates <= 0:
        raise ValueError("--max-bundle-candidates must be positive")
    report = read_json(args.report)
    ir = read_json(args.ir)
    if ir["sdk"]["id"] != args.sdk_id:
        raise ValueError("IR and requested SDK ID do not match")
    groups = [
        group for group in dataset["groups"] if group["sdk_id"] == args.sdk_id
    ]
    if not groups:
        raise ValueError(f"SDK absent from ranking dataset: {args.sdk_id}")
    feature_names = report["features"]["numeric_candidate_features"]
    cache = MultiViewEffectCache(
        args.base_metadata,
        args.base_vectors,
        args.focused_metadata,
        args.focused_vectors,
    )
    prior_cache = StructuralPriorCache()
    model = lightgbm.Booster(model_file=str(args.model))
    residual_weight = float(report["final_model"]["selected_residual_weight"])

    operations = {}
    for group in sorted(groups, key=lambda item: item["operation_id"]):
        learned = learned_scores(
            model,
            group,
            cache,
            prior_cache,
            feature_names,
            args.target_architecture,
        )
        final = residual_scores(
            group,
            learned,
            prior_cache,
            residual_weight,
            args.target_architecture,
        )
        scored_count = len(group["candidates"])
        rows = sorted_candidates(group, learned, final)[
            : args.max_bundle_candidates
        ]
        operations[group["operation_id"]] = {
            "candidate_count": len(rows),
            "scored_candidate_count": scored_count,
            "selected_entity_id": rows[0]["entity_id"],
            "selected_symbol": rows[0]["symbol"],
            "candidates": rows,
        }

    payload = {
        "schema_version": "frozen-operation-ranking-v1",
        "created_at": utc_now(),
        "contains_labels": False,
        "method": "structural-prior-feasible-lambdamart-residual-v2.1",
        "sdk": {
            "id": ir["sdk"]["id"],
            "digest": ir["sdk"]["digest"],
            "ir_sha256": file_sha256(args.ir),
            "target_architecture": args.target_architecture,
        },
        "model": {
            "path": str(args.model),
            "sha256": file_sha256(args.model),
            "report": str(args.report),
            "report_sha256": file_sha256(args.report),
            "selected_residual_weight": residual_weight,
        },
        "feature_contract": {
            "candidate_policy": (
                "score every label-free capability-evidence candidate, then retain "
                "the deterministic model Top-K in the frozen runtime package"
            ),
            "source_contains_labels": False,
            "truth_independent": True,
            "max_bundle_candidates_per_operation": args.max_bundle_candidates,
            "scored_candidates": sum(
                item["scored_candidate_count"] for item in operations.values()
            ),
            "numeric_candidate_features": feature_names,
            "model_feature_names": report["features"]["model_feature_names"],
            "dataset_sha256": file_sha256(args.dataset),
            "base_vectors_sha256": file_sha256(args.base_vectors),
            "focused_vectors_sha256": file_sha256(args.focused_vectors),
            "operation_count": len(operations),
        },
        "operations": operations,
    }
    write_json(args.output, payload)
    print(
        {
            "output": str(args.output),
            "sdk_digest": ir["sdk"]["digest"],
            "operations": len(operations),
            "candidates": sum(item["candidate_count"] for item in operations.values()),
            "contains_labels": False,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
