#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from evaluate_operation_ranker import METRICS, ranking_metrics


def keyed_groups(dataset: dict[str, Any], role: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (group["sdk_id"], group["operation_id"]): group
        for group in dataset["groups"]
        if group["role"] == role
    }


def keyed_scores(group: dict[str, Any]) -> dict[str, float]:
    return {
        candidate["entity_id"]: float(candidate["features"]["code-embedding"])
        for candidate in group["candidates"]
    }


def aggregate(records: list[dict[str, float]]) -> dict[str, float]:
    return {name: round(mean(item[name] for item in records), 6) for name in METRICS}


def bootstrap_delta(
    baseline: list[dict[str, float]],
    treatment: list[dict[str, float]],
    metric: str,
    seed: int,
    samples: int = 10000,
) -> dict[str, float]:
    deltas = [right[metric] - left[metric] for left, right in zip(baseline, treatment, strict=True)]
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choice(deltas) for _ in deltas) for _ in range(samples))
    return {
        "mean_delta": round(mean(deltas), 6),
        "ci95_low": round(estimates[int(samples * 0.025)], 6),
        "ci95_high": round(estimates[int(samples * 0.975)], 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="评估静态、基础语义与调优语义三路固定权重集成")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--tuned", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("train", "external-test"), default="external-test")
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--top-k", type=int, default=0, help="仅在静态 Top-K 候选池内集成；0 表示全量")
    args = parser.parse_args()

    base_dataset = read_json(args.base)
    tuned_dataset = read_json(args.tuned)
    base_groups = keyed_groups(base_dataset, args.role)
    tuned_groups = keyed_groups(tuned_dataset, args.role)
    if base_groups.keys() != tuned_groups.keys():
        raise SystemExit("两个语义数据集的查询组不一致")
    count = round(1.0 / args.step)
    results = {}
    record_sets = {}
    for static_units in range(count + 1):
        for base_units in range(count - static_units + 1):
            tuned_units = count - static_units - base_units
            weights = (
                static_units / count,
                base_units / count,
                tuned_units / count,
            )
            records = []
            for key, base_group in base_groups.items():
                tuned_scores = keyed_scores(tuned_groups[key])
                pool = {
                    item["entity_id"]
                    for item in sorted(
                        base_group["candidates"],
                        key=lambda item: (-float(item["static_score"]), item["entity_id"]),
                    )[:args.top_k]
                } if args.top_k else None
                scores = []
                for candidate in base_group["candidates"]:
                    blended = (
                        weights[0] * float(candidate["static_score"])
                        + weights[1] * float(candidate["features"]["code-embedding"])
                        + weights[2] * tuned_scores[candidate["entity_id"]]
                    )
                    scores.append(
                        2.0 + blended
                        if pool is not None and candidate["entity_id"] in pool
                        else blended if pool is None
                        else float(candidate["static_score"])
                    )
                records.append(ranking_metrics(base_group["candidates"], scores))
            name = f"static={weights[0]:.2f},base={weights[1]:.2f},tuned={weights[2]:.2f}"
            results[name] = aggregate(records)
            record_sets[name] = records
    ordered = sorted(
        results.items(),
        key=lambda item: (-item[1]["map"], -item[1]["precision_at_1"], item[0]),
    )
    baseline_name = "static=0.50,base=0.50,tuned=0.00"
    best_name = ordered[0][0]
    report = {
        "schema_version": "1.0",
        "role": args.role,
        "groups": len(base_groups),
        "grid_step": args.step,
        "static_candidate_top_k": args.top_k,
        "base_embedding": base_dataset.get("embedding", {}),
        "tuned_embedding": tuned_dataset.get("embedding", {}),
        "best_by_map": {"weights": ordered[0][0], "metrics": ordered[0][1]},
        "comparison_vs_v0.7_equal_fusion": {
            metric: bootstrap_delta(
                record_sets[baseline_name], record_sets[best_name], metric, 20260825 + index
            )
            for index, metric in enumerate(("precision_at_1", "recall_at_5", "map", "ndcg_at_10"))
        } if baseline_name in record_sets else None,
        "all_results": dict(ordered),
    }
    write_json(args.output, report)
    print(report["best_by_map"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
