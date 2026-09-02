#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_ranker import OPERATIONS
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_effect_ranker import record_for_scores
from evaluate_multiview_lambdamart import candidate_row, numeric_feature_names


PARAMETERS = {
    "n_estimators": 260,
    "learning_rate": 0.025,
    "num_leaves": 9,
    "max_depth": 4,
    "min_child_samples": 24,
    "reg_lambda": 2.0,
    "reg_alpha": 0.3,
    "colsample_bytree": 0.85,
    "subsample": 0.8,
    "subsample_freq": 1,
}


def all_names(numeric_names: list[str]) -> list[str]:
    return [
        "static_score",
        "full_code_cosine",
        "focused_code_cosine",
        "full_focus_cosine",
        "operation_constraint",
        "status_query",
        *numeric_names,
        *[f"operation::{item}" for item in OPERATIONS],
    ]


def masks(names: list[str]) -> dict[str, list[int]]:
    control = {
        "operation_constraint",
        "status_query",
        *[f"operation::{item}" for item in OPERATIONS],
    }
    semantic = {"full_code_cosine", *control}
    focused = {
        "full_code_cosine",
        "focused_code_cosine",
        "full_focus_cosine",
        *control,
    }
    graph = {name for name in names if name.startswith("hw-")}
    selected = {
        "full-code": semantic,
        "full-plus-focused": focused,
        "full-focused-graph": focused | graph,
        "all-channels": set(names),
    }
    return {
        key: [index for index, name in enumerate(names) if name in values]
        for key, values in selected.items()
    }


def rows_for_group(
    group: dict[str, Any],
    cache: MultiViewEffectCache,
    numeric_names: list[str],
    mask: list[int],
) -> list[list[float]]:
    return [
        [value[index] for index in mask]
        for candidate in group["candidates"]
        for value in [candidate_row(group, candidate, cache, numeric_names)]
    ]


def train_model(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    numeric_names: list[str],
    mask: list[int],
    seed: int,
) -> Any:
    import lightgbm

    values = []
    labels = []
    sizes = []
    for group in groups:
        group_rows = rows_for_group(group, cache, numeric_names, mask)
        values.extend(group_rows)
        labels.extend(int(item["label"]) for item in group["candidates"])
        sizes.append(len(group_rows))
    model = lightgbm.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        random_state=seed,
        verbosity=-1,
        **PARAMETERS,
    )
    model.fit(values, labels, group=sizes)
    return model


def evaluate(
    model: Any,
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    numeric_names: list[str],
    mask: list[int],
) -> list[dict[str, Any]]:
    records = []
    for group in groups:
        raw = model.predict(rows_for_group(group, cache, numeric_names, mask))
        scores = [
            float(score) - 8.0 * operation_constraint_penalty(candidate, group["operation_id"])
            for score, candidate in zip(raw, group["candidates"], strict=True)
        ]
        records.append(record_for_scores(group, scores))
    return records


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="固定树配置的多视图通道消融")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata,
        args.base_vectors,
        args.focused_metadata,
        args.focused_vectors,
    )
    groups = [item for item in dataset["groups"] if item["role"] == "train"]
    numeric_names = numeric_feature_names(groups)
    names = all_names(numeric_names)
    channel_masks = masks(names)
    assignments = fold_assignments(groups, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        train = [item for item in groups if item["independence_group"] not in test_ids]
        test = [item for item in groups if item["independence_group"] in test_ids]
        metrics = {}
        for name, mask in channel_masks.items():
            model = train_model(
                train, cache, numeric_names, mask, seed=args.seed + fold * 10
            )
            fold_records = evaluate(model, test, cache, numeric_names, mask)
            records[name].extend(fold_records)
            metrics[name] = aggregate(fold_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "metrics": metrics,
        })
        print({"fold": fold, "metrics": metrics}, flush=True)

    comparisons = {}
    order = list(channel_masks)
    for left, right in zip(order[:-1], order[1:], strict=True):
        comparisons[f"{right}-vs-{left}"] = paired_comparison(
            records[right], records[left], seed=args.seed
        )
    report = {
        "schema_version": "0.3-ablation",
        "method": "fixed small-bagged LambdaMART channel ablation",
        "parameters": PARAMETERS,
        "feature_sets": {
            name: [names[index] for index in mask]
            for name, mask in channel_masks.items()
        },
        "metrics": {name: aggregate(items) for name, items in records.items()},
        "paired_incremental_comparisons": comparisons,
        "fold_reports": fold_reports,
        "records": records,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({"metrics": report["metrics"], "elapsed_seconds": report["elapsed_seconds"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
