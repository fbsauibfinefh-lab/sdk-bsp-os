#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_channel_ablations import all_names, rows_for_group, train_model
from evaluate_multiview_effect_ranker import record_for_scores
from evaluate_multiview_lambdamart import numeric_feature_names


ALPHAS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 1.0]


def _rank_percentiles(scores: list[float]) -> list[float]:
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    denominator = max(1, len(scores) - 1)
    output = [0.0] * len(scores)
    for rank, index in enumerate(order):
        output[index] = 1.0 - rank / denominator
    return output


def model_scores(
    model: Any,
    group: dict[str, Any],
    cache: MultiViewEffectCache,
    numeric_names: list[str],
    mask: list[int],
) -> list[float]:
    raw = model.predict(rows_for_group(group, cache, numeric_names, mask))
    constrained = [
        float(score) - 8.0 * operation_constraint_penalty(candidate, group["operation_id"])
        for score, candidate in zip(raw, group["candidates"], strict=True)
    ]
    return _rank_percentiles(constrained)


def evaluate_pair(
    base_model: Any,
    contrast_model: Any,
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    numeric_names: list[str],
    base_mask: list[int],
    contrast_mask: list[int],
    alpha: float,
) -> list[dict[str, Any]]:
    records = []
    for group in groups:
        base = model_scores(base_model, group, cache, numeric_names, base_mask)
        contrast = model_scores(
            contrast_model, group, cache, numeric_names, contrast_mask
        )
        scores = [
            (1.0 - alpha) * left + alpha * right
            for left, right in zip(base, contrast, strict=True)
        ]
        records.append(record_for_scores(group, scores))
    return records


def objective(metrics: dict[str, float]) -> float:
    return mean([
        metrics["precision_at_1"], metrics["recall_at_5"],
        metrics["map"], metrics["ndcg_at_10"],
    ])


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="嵌套选择的 v0.3/效果对比排序融合")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    groups = [item for item in dataset["groups"] if item["role"] == "train"]
    numeric_names = numeric_feature_names(groups)
    names = all_names(numeric_names)
    base_mask = [index for index, name in enumerate(names) if not name.startswith("xop-")]
    contrast_mask = list(range(len(names)))
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(fold_assignments(groups, args.folds), start=1):
        outer_train = [item for item in groups if item["independence_group"] not in test_ids]
        test = [item for item in groups if item["independence_group"] in test_ids]
        validation_ids = fold_assignments(outer_train, 4)[0]
        inner_train = [
            item for item in outer_train
            if item["independence_group"] not in validation_ids
        ]
        validation = [
            item for item in outer_train
            if item["independence_group"] in validation_ids
        ]
        inner_base = train_model(
            inner_train, cache, numeric_names, base_mask, args.seed + fold * 100
        )
        inner_contrast = train_model(
            inner_train, cache, numeric_names, contrast_mask, args.seed + fold * 100
        )
        alpha_metrics = {}
        for alpha in ALPHAS:
            metrics = aggregate(evaluate_pair(
                inner_base, inner_contrast, validation, cache, numeric_names,
                base_mask, contrast_mask, alpha,
            ))
            alpha_metrics[str(alpha)] = {
                "metrics": metrics,
                "objective": round(objective(metrics), 6),
            }
        best = max(ALPHAS, key=lambda value: (alpha_metrics[str(value)]["objective"], -value))
        best_objective = alpha_metrics[str(best)]["objective"]
        selected = min(
            alpha for alpha in ALPHAS
            if alpha_metrics[str(alpha)]["objective"] >= best_objective - 0.005
        )
        outer_base = train_model(
            outer_train, cache, numeric_names, base_mask, args.seed + fold * 10
        )
        outer_contrast = train_model(
            outer_train, cache, numeric_names, contrast_mask, args.seed + fold * 10
        )
        base_records = evaluate_pair(
            outer_base, outer_contrast, test, cache, numeric_names,
            base_mask, contrast_mask, 0.0,
        )
        ensemble_records = evaluate_pair(
            outer_base, outer_contrast, test, cache, numeric_names,
            base_mask, contrast_mask, selected,
        )
        records["v0.3-fixed"].extend(base_records)
        records["nested-ensemble"].extend(ensemble_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "validation_independence_groups": sorted(validation_ids),
            "selected_alpha": selected,
            "alpha_metrics": alpha_metrics,
            "base_metrics": aggregate(base_records),
            "ensemble_metrics": aggregate(ensemble_records),
        })
        print(fold_reports[-1], flush=True)

    report = {
        "schema_version": "0.4-ensemble",
        "method": "nested rank-percentile ensemble of v0.3 and effect contrast experts",
        "alphas": ALPHAS,
        "metrics": {name: aggregate(items) for name, items in records.items()},
        "paired_ensemble_vs_base": paired_comparison(
            records["nested-ensemble"], records["v0.3-fixed"], seed=args.seed
        ),
        "fold_reports": fold_reports,
        "records": records,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({"metrics": report["metrics"], "paired": report["paired_ensemble_vs_base"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
