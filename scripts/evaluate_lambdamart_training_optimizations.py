#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from copy import copy
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_ranker import OPERATIONS
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_effect_ranker import record_for_scores
from evaluate_multiview_lambdamart import candidate_row, numeric_feature_names


BASE_TREE = {
    "n_estimators": 240,
    "learning_rate": 0.025,
    "num_leaves": 7,
    "max_depth": 4,
    "min_child_samples": 28,
    "reg_lambda": 2.5,
    "reg_alpha": 0.35,
    "colsample_bytree": 0.9,
}

RECIPES = {
    "all-default": {"collapse_symbols": False, "hard_negatives": None, "truncation": 30},
    "all-top5": {"collapse_symbols": False, "hard_negatives": None, "truncation": 5},
    "unique-top5": {"collapse_symbols": True, "hard_negatives": None, "truncation": 5},
    "hard20-top5": {"collapse_symbols": True, "hard_negatives": 20, "truncation": 5},
    "hard40-top5": {"collapse_symbols": True, "hard_negatives": 40, "truncation": 5},
    "hard80-top5": {"collapse_symbols": True, "hard_negatives": 80, "truncation": 5},
    "hard40-top10": {"collapse_symbols": True, "hard_negatives": 40, "truncation": 10},
    "hard40-top5-invariant": {
        "collapse_symbols": True,
        "hard_negatives": 40,
        "truncation": 5,
        "feature_profile": "vendor-invariant-ablation",
    },
    "hard40-top5-tiny": {
        "collapse_symbols": True,
        "hard_negatives": 40,
        "truncation": 5,
        "tree": {
            "n_estimators": 220, "learning_rate": 0.03, "num_leaves": 5,
            "max_depth": 3, "min_child_samples": 32,
            "reg_lambda": 2.5, "reg_alpha": 0.4, "colsample_bytree": 0.85,
        },
    },
    "hard40-top5-medium": {
        "collapse_symbols": True,
        "hard_negatives": 40,
        "truncation": 5,
        "tree": {
            "n_estimators": 300, "learning_rate": 0.022, "num_leaves": 13,
            "max_depth": 5, "min_child_samples": 28,
            "reg_lambda": 3.0, "reg_alpha": 0.4, "colsample_bytree": 0.85,
        },
    },
}
RETAINED_RECIPE = "all-top5"

INVARIANT_EXCLUSIONS = {
    "driver-path",
    "field-file-maxsim",
    "hal-abstraction",
    "private-api",
    "source-role-prior",
    "test-example",
}
HARDNESS_CACHE: dict[tuple[str, str], float] = {}


def recipe_features(all_names: list[str], recipe: dict[str, Any]) -> list[str]:
    if recipe.get("feature_profile") != "vendor-invariant-ablation":
        return all_names
    return [name for name in all_names if name not in INVARIANT_EXCLUSIONS]


def semantic_hardness(
    group: dict[str, Any], candidate: dict[str, Any], cache: MultiViewEffectCache
) -> float:
    import numpy as np

    key = (group["group_id"], candidate["entity_id"])
    if key in HARDNESS_CACHE:
        return HARDNESS_CACHE[key]
    query = cache.base.query_vector(group["operation_id"])
    base_key = cache.base.candidate_key(candidate, group["sdk_id"])
    full = cache.base.documents[cache.base.document_index[base_key]]
    focused = cache.focused_vector(group, candidate)
    features = candidate["features"]
    value = (
        0.30 * float(candidate.get("static_score", 0.0))
        + 0.30 * float(np.dot(query, full))
        + 0.30 * float(np.dot(query, focused))
        + 0.10 * float(features.get("multi-channel-rrf", 0.0))
    )
    HARDNESS_CACHE[key] = value
    return value


def training_view(
    group: dict[str, Any], recipe: dict[str, Any], cache: MultiViewEffectCache
) -> dict[str, Any]:
    if not recipe["collapse_symbols"] and recipe["hard_negatives"] is None:
        return group
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in group["candidates"]:
        by_symbol[candidate["symbol"]].append(candidate)
    representatives = []
    for candidates in by_symbol.values():
        representatives.append(max(
            candidates,
            key=lambda item: (
                int(item["label"]),
                semantic_hardness(group, item, cache),
                item["entity_id"],
            ),
        ))
    positives = [item for item in representatives if int(item["label"]) > 0]
    negatives = sorted(
        (item for item in representatives if int(item["label"]) == 0),
        key=lambda item: (-semantic_hardness(group, item, cache), item["entity_id"]),
    )
    hard_limit = recipe["hard_negatives"]
    if hard_limit is not None:
        negatives = negatives[:hard_limit]
    result = copy(group)
    result["candidates"] = positives + negatives
    return result


def matrix(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    feature_names: list[str],
    recipe: dict[str, Any],
) -> tuple[list[list[float]], list[int], list[int], dict[str, int]]:
    values: list[list[float]] = []
    labels: list[int] = []
    sizes: list[int] = []
    original_rows = 0
    for group in groups:
        original_rows += len(group["candidates"])
        view = training_view(group, recipe, cache)
        sizes.append(len(view["candidates"]))
        for candidate in view["candidates"]:
            values.append(candidate_row(view, candidate, cache, feature_names))
            labels.append(int(candidate["label"]))
    return values, labels, sizes, {
        "queries": len(groups),
        "original_rows": original_rows,
        "training_rows": len(values),
        "positive_rows": sum(label > 0 for label in labels),
        "unlabeled_rows": sum(label == 0 for label in labels),
    }


def train_model(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    feature_names: list[str],
    recipe: dict[str, Any],
    *,
    seed: int,
) -> tuple[Any, dict[str, int]]:
    import lightgbm

    values, labels, sizes, stats = matrix(groups, cache, feature_names, recipe)
    parameters = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "lambdarank_truncation_level": recipe["truncation"],
        "random_state": seed,
        "verbosity": -1,
        **recipe.get("tree", BASE_TREE),
    }
    model = lightgbm.LGBMRanker(**parameters)
    model.fit(values, labels, group=sizes)
    return model, stats


def predict(
    model: Any,
    group: dict[str, Any],
    cache: MultiViewEffectCache,
    feature_names: list[str],
) -> list[float]:
    values = [candidate_row(group, item, cache, feature_names) for item in group["candidates"]]
    scores = [float(value) for value in model.predict(values)]
    return [
        score - 8.0 * operation_constraint_penalty(candidate, group["operation_id"])
        for score, candidate in zip(scores, group["candidates"], strict=True)
    ]


def evaluate(
    model: Any,
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    feature_names: list[str],
) -> list[dict[str, Any]]:
    return [record_for_scores(group, predict(model, group, cache, feature_names)) for group in groups]


def extended_aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    metrics = aggregate(records)
    metrics["hit_at_5"] = round(mean(
        float(any(item["label"] > 0 for item in record["top5"])) for record in records
    ), 6)
    metrics["mean_first_positive_rank"] = round(mean(
        record["positive_ranks"][0]["rank"] for record in records
    ), 6)
    return metrics


def objective(metrics: dict[str, float]) -> float:
    return round(
        0.35 * metrics["precision_at_1"]
        + 0.30 * metrics["recall_at_5"]
        + 0.20 * metrics["ndcg_at_10"]
        + 0.10 * metrics["map"]
        + 0.05 * metrics["hit_at_5"],
        6,
    )


def feature_importance(model: Any, feature_names: list[str]) -> list[dict[str, Any]]:
    names = [
        "static_score", "full_code_cosine", "focused_code_cosine",
        "full_focus_cosine", "operation_constraint", "status_query",
        *feature_names,
        *[f"operation::{operation}" for operation in OPERATIONS],
    ]
    gains = model.booster_.feature_importance(importance_type="gain")
    splits = model.booster_.feature_importance(importance_type="split")
    return sorted([
        {"feature": name, "gain": round(float(gain), 6), "splits": int(split)}
        for name, gain, split in zip(names, gains, splits, strict=True)
    ], key=lambda item: (-item["gain"], item["feature"]))


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="评估LambdaMART头部目标和硬负样本优化")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    training = [item for item in dataset["groups"] if item["role"] == "train"]
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    all_features = numeric_feature_names(training)
    assignments = fold_assignments(training, args.folds)
    all_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        outer_train = [item for item in training if item["independence_group"] not in test_ids]
        test = [item for item in training if item["independence_group"] in test_ids]
        validation_ids = fold_assignments(outer_train, 4)[0]
        inner_train = [item for item in outer_train if item["independence_group"] not in validation_ids]
        validation = [item for item in outer_train if item["independence_group"] in validation_ids]
        candidates = {}
        outer_models = {}
        for index, (name, recipe) in enumerate(RECIPES.items()):
            features = recipe_features(all_features, recipe)
            inner_model, inner_stats = train_model(
                inner_train, cache, features, recipe, seed=args.seed + fold * 100 + index
            )
            inner_metrics = extended_aggregate(evaluate(inner_model, validation, cache, features))
            outer_model, outer_stats = train_model(
                outer_train, cache, features, recipe, seed=args.seed + fold * 10 + index
            )
            outer_models[name] = (outer_model, features)
            records = evaluate(outer_model, test, cache, features)
            all_records[name].extend(records)
            candidates[name] = {
                "inner_metrics": inner_metrics,
                "inner_objective": objective(inner_metrics),
                "outer_metrics": extended_aggregate(records),
                "inner_training": inner_stats,
                "outer_training": outer_stats,
            }
        selected = max(RECIPES, key=lambda name: (candidates[name]["inner_objective"], name))
        model, features = outer_models[selected]
        selected_records = evaluate(model, test, cache, features)
        all_records["nested-selected"].extend(selected_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "validation_independence_groups": sorted(validation_ids),
            "selected_recipe": selected,
            "selected_metrics": extended_aggregate(selected_records),
            "recipes": candidates,
        })
        print({
            "fold": fold, "selected": selected,
            "metrics": extended_aggregate(selected_records),
        }, flush=True)

    final_validation_ids = fold_assignments(training, 4)[0]
    final_train = [item for item in training if item["independence_group"] not in final_validation_ids]
    final_validation = [item for item in training if item["independence_group"] in final_validation_ids]
    final_selection = {}
    for index, (name, recipe) in enumerate(RECIPES.items()):
        features = recipe_features(all_features, recipe)
        model, stats = train_model(
            final_train, cache, features, recipe, seed=args.seed + 1000 + index
        )
        metrics = extended_aggregate(evaluate(model, final_validation, cache, features))
        final_selection[name] = {"metrics": metrics, "objective": objective(metrics), "training": stats}
    exploratory_final_recipe = max(
        RECIPES, key=lambda name: (final_selection[name]["objective"], name)
    )
    final_recipe_name = RETAINED_RECIPE
    final_recipe = RECIPES[final_recipe_name]
    final_features = recipe_features(all_features, final_recipe)
    final_model, final_stats = train_model(
        training, cache, final_features, final_recipe, seed=args.seed
    )
    external_records = evaluate(final_model, external, cache, final_features)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_model.booster_.save_model(str(args.output_model))

    baseline = read_json(args.baseline_results)
    baseline_records = baseline["cross_validation"]["records"]["multiview-lambdamart-nested"]
    report = {
        "schema_version": "0.5",
        "seed": args.seed,
        "truth_set": dataset.get("truth_set_id"),
        "method": "nested LambdaMART top-k truncation, symbol collapse, and semantic hard-negative mining",
        "recipes": RECIPES,
        "feature_invariance_exclusions": sorted(INVARIANT_EXCLUSIONS),
        "cross_validation": {
            "unit": "independence_group/vendor",
            "groups": len(training),
            "metrics": {name: extended_aggregate(records) for name, records in all_records.items()},
            "paired_nested_vs_v03": paired_comparison(
                all_records["nested-selected"], baseline_records, seed=args.seed
            ),
            "fold_reports": fold_reports,
            "records": all_records,
        },
        "external_board_diagnostic": {
            "excluded_from_training": True,
            "selected_recipe": final_recipe_name,
            "metrics": extended_aggregate(external_records),
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "selected_recipe": final_recipe_name,
            "exploratory_validation_best": exploratory_final_recipe,
            "selection": final_selection,
            "training": final_stats,
            "features": final_features,
            "feature_importance": feature_importance(final_model, final_features),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({
        "metrics": report["cross_validation"]["metrics"],
        "external_metrics": report["external_board_diagnostic"]["metrics"],
        "final_recipe": final_recipe_name,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
