#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.structured_retrieval import complete_structured_scores
from evaluate_hardware_effect_pu_ranker import aggregate
from evaluate_lambdamart_training_optimizations import (
    extended_aggregate,
    numeric_feature_names,
    predict,
)
from evaluate_multiview_effect_ranker import record_for_scores


def standardized(values: list[float]) -> list[float]:
    center = mean(values)
    variance = mean((item - center) ** 2 for item in values)
    scale = max(variance ** 0.5, 1e-8)
    return [(item - center) / scale for item in values]


def evaluate_scores(
    groups: list[dict[str, Any]], scores: dict[str, list[float]]
) -> list[dict[str, Any]]:
    return [record_for_scores(group, scores[group["group_id"]]) for group in groups]


def grouped_metrics(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        value = (
            record["operation_id"].split(".", 1)[0]
            if key == "capability"
            else record[key]
        )
        grouped[value].append(record)
    return {
        name: {"queries": len(items), **extended_aggregate(items)}
        for name, items in sorted(grouped.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只评测冻结LambdaMART，不使用外部板卡标签训练或选参"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--model", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import lightgbm

    dataset = read_json(args.dataset)
    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [
        group for group in dataset["groups"] if group["role"] == "external-test"
    ]
    external_sdk_ids = {group["sdk_id"] for group in external}
    feature_names = numeric_feature_names(training)
    cache = MultiViewEffectCache(
        args.base_metadata,
        args.base_vectors,
        args.focused_metadata,
        args.focused_vectors,
    )

    model_scores: dict[str, dict[str, list[float]]] = {}
    methods: dict[str, list[dict[str, Any]]] = {}
    for model_path in args.model:
        model = lightgbm.Booster(model_file=str(model_path))
        scores = {
            group["group_id"]: predict(model, group, cache, feature_names)
            for group in external
        }
        name = model_path.stem
        model_scores[name] = scores
        methods[name] = evaluate_scores(external, scores)

    ensemble_scores = {}
    for group in external:
        per_model = [
            standardized(scores[group["group_id"]])
            for scores in model_scores.values()
        ]
        ensemble_scores[group["group_id"]] = [
            mean(values) for values in zip(*per_model, strict=True)
        ]
    methods["lambdamart-three-seed-zscore-ensemble"] = evaluate_scores(
        external, ensemble_scores
    )

    q4_scores = {
        group["group_id"]: complete_structured_scores(group)[0]
        for group in external
    }
    methods["hierarchical-field-family-q4"] = evaluate_scores(external, q4_scores)

    method_reports = {}
    for name, records in methods.items():
        method_reports[name] = {
            "metrics": extended_aggregate(records),
            "by_sdk": grouped_metrics(records, "sdk_id"),
            "by_capability": grouped_metrics(records, "capability"),
            "errors": [record for record in records if record["selected"]["label"] == 0],
            "records": records,
        }

    report = {
        "schema_version": "frozen-external-lambdamart-v1",
        "created_at": utc_now(),
        "protocol": {
            "training_included": False,
            "external_labels_used_for_selection": False,
            "ensemble": "query-local z-score mean over three pre-existing random seeds",
            "complete_queries": len(external),
            "skipped_no_public_api": sum(
                item.get("sdk_id") in external_sdk_ids
                and item.get("reason") == "no_public_api"
                for item in dataset.get("skipped", [])
            ),
        },
        "inputs": {
            "dataset": str(args.dataset),
            "dataset_sha256": file_sha256(args.dataset),
            "models": [
                {"path": str(path), "sha256": file_sha256(path)} for path in args.model
            ],
        },
        "feature_names": feature_names,
        "methods": method_reports,
    }
    write_json(args.output, report)
    print({
        name: {
            "metrics": value["metrics"],
            "by_sdk": value["by_sdk"],
            "errors": len(value["errors"]),
        }
        for name, value in method_reports.items()
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
