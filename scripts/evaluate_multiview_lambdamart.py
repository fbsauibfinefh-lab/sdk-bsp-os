#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_graph import hard_constraint_penalty, identifier_tokens
from bspforge.hardware_effect_ranker import OPERATIONS
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_effect_ranker import record_for_scores


VARIANTS = {
    "tree-tiny": {
        "n_estimators": 220, "learning_rate": 0.03, "num_leaves": 5,
        "max_depth": 3, "min_child_samples": 32,
        "reg_lambda": 2.5, "reg_alpha": 0.4, "colsample_bytree": 0.85,
    },
    "tree-small-reg": {
        "n_estimators": 240, "learning_rate": 0.025, "num_leaves": 7,
        "max_depth": 4, "min_child_samples": 28,
        "reg_lambda": 2.5, "reg_alpha": 0.35, "colsample_bytree": 0.9,
    },
    "tree-small": {
        "n_estimators": 160, "learning_rate": 0.035, "num_leaves": 9,
        "max_depth": 4, "min_child_samples": 24,
    },
    "tree-small-bagged": {
        "n_estimators": 260, "learning_rate": 0.025, "num_leaves": 9,
        "max_depth": 4, "min_child_samples": 24,
        "reg_lambda": 2.0, "reg_alpha": 0.3, "colsample_bytree": 0.85,
        "subsample": 0.8, "subsample_freq": 1,
    },
    "tree-medium-reg": {
        "n_estimators": 300, "learning_rate": 0.022, "num_leaves": 13,
        "max_depth": 5, "min_child_samples": 28,
        "reg_lambda": 3.0, "reg_alpha": 0.4, "colsample_bytree": 0.85,
    },
}

VARIANT_COMPLEXITY = {name: index for index, name in enumerate(VARIANTS)}
PARSIMONY_TOLERANCE = 0.01


def numeric_feature_names(groups: list[dict[str, Any]]) -> list[str]:
    return sorted({
        name
        for group in groups
        for candidate in group["candidates"]
        for name, value in candidate["features"].items()
        if isinstance(value, (int, float))
    })


def candidate_row(
    group: dict[str, Any],
    candidate: dict[str, Any],
    cache: MultiViewEffectCache,
    feature_names: list[str],
) -> list[float]:
    query = cache.base.query_vector(group["operation_id"])
    base_key = cache.base.candidate_key(candidate, group["sdk_id"])
    full = cache.base.documents[cache.base.document_index[base_key]]
    focused = cache.focused_vector(group, candidate)
    operation_one_hot = [float(group["operation_id"] == item) for item in OPERATIONS]
    tokens = set(identifier_tokens(candidate["symbol"]))
    return [
        float(candidate.get("static_score", 0.0)),
        float(np.dot(query, full)),
        float(np.dot(query, focused)),
        float(np.dot(full, focused)),
        float(operation_constraint_penalty(candidate, group["operation_id"])),
        float(bool(tokens & {"is", "has", "status", "check", "ready", "running"})),
        *[float(candidate["features"].get(name, 0.0)) for name in feature_names],
        *operation_one_hot,
    ]


def matrix(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    feature_names: list[str],
) -> tuple[list[list[float]], list[int], list[int]]:
    values = []
    labels = []
    sizes = []
    for group in groups:
        sizes.append(len(group["candidates"]))
        for candidate in group["candidates"]:
            values.append(candidate_row(group, candidate, cache, feature_names))
            labels.append(int(candidate["label"]))
    return values, labels, sizes


def train_model(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    feature_names: list[str],
    parameters: dict[str, Any],
    *,
    seed: int,
) -> Any:
    import lightgbm

    values, labels, sizes = matrix(groups, cache, feature_names)
    model_parameters = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "reg_lambda": 1.5,
        "reg_alpha": 0.25,
        "random_state": seed,
        "verbosity": -1,
        **parameters,
    }
    model = lightgbm.LGBMRanker(**model_parameters)
    model.fit(values, labels, group=sizes)
    return model


def predict(
    model: Any,
    group: dict[str, Any],
    cache: MultiViewEffectCache,
    feature_names: list[str],
) -> list[float]:
    values = [
        candidate_row(group, candidate, cache, feature_names)
        for candidate in group["candidates"]
    ]
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
    return [
        record_for_scores(group, predict(model, group, cache, feature_names))
        for group in groups
    ]


def objective(metrics: dict[str, float]) -> float:
    return mean([
        metrics["precision_at_1"], metrics["recall_at_5"],
        metrics["map"], metrics["ndcg_at_10"],
    ])


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="评估多视图分级LambdaMART架构")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--v02-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [group for group in dataset["groups"] if group["role"] == "external-test"]
    feature_names = numeric_feature_names(training)
    assignments = fold_assignments(training, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        outer_train = [group for group in training if group["independence_group"] not in test_ids]
        test = [group for group in training if group["independence_group"] in test_ids]
        validation_ids = fold_assignments(outer_train, 4)[0]
        inner_train = [group for group in outer_train if group["independence_group"] not in validation_ids]
        validation = [group for group in outer_train if group["independence_group"] in validation_ids]
        variant_reports = {}
        outer_models = {}
        for index, (name, parameters) in enumerate(VARIANTS.items()):
            inner_model = train_model(
                inner_train, cache, feature_names, parameters,
                seed=args.seed + fold * 100,
            )
            inner_metrics = aggregate(evaluate(
                inner_model, validation, cache, feature_names
            ))
            outer_model = train_model(
                outer_train, cache, feature_names, parameters,
                seed=args.seed + fold * 10,
            )
            outer_models[name] = outer_model
            outer_records = evaluate(outer_model, test, cache, feature_names)
            records[f"multiview-lambdamart-{name}"].extend(outer_records)
            variant_reports[name] = {
                "inner_metrics": inner_metrics,
                "inner_objective": round(objective(inner_metrics), 6),
                "outer_metrics": aggregate(outer_records),
            }
        selected = max(
            VARIANTS, key=lambda name: (variant_reports[name]["inner_objective"], name)
        )
        best_inner = variant_reports[selected]["inner_objective"]
        parsimonious = min(
            (
                name for name in VARIANTS
                if variant_reports[name]["inner_objective"] >= best_inner - PARSIMONY_TOLERANCE
            ),
            key=lambda name: VARIANT_COMPLEXITY[name],
        )
        selected_records = evaluate(
            outer_models[selected], test, cache, feature_names
        )
        records["multiview-lambdamart-nested"].extend(selected_records)
        parsimonious_records = evaluate(
            outer_models[parsimonious], test, cache, feature_names
        )
        records["multiview-lambdamart-nested-parsimonious"].extend(
            parsimonious_records
        )
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "validation_independence_groups": sorted(validation_ids),
            "selected_variant": selected,
            "parsimonious_variant": parsimonious,
            "metrics": aggregate(selected_records),
            "parsimonious_metrics": aggregate(parsimonious_records),
            "variants": variant_reports,
        })
        print({
            "fold": fold, "selected": selected, "parsimonious": parsimonious,
            "metrics": aggregate(selected_records),
            "parsimonious_metrics": aggregate(parsimonious_records),
        }, flush=True)

    final_validation_ids = fold_assignments(training, 4)[0]
    final_inner = [group for group in training if group["independence_group"] not in final_validation_ids]
    final_validation = [group for group in training if group["independence_group"] in final_validation_ids]
    final_selection = {}
    for index, (name, parameters) in enumerate(VARIANTS.items()):
        model = train_model(
            final_inner, cache, feature_names, parameters,
            seed=args.seed + 1000,
        )
        metrics = aggregate(evaluate(model, final_validation, cache, feature_names))
        final_selection[name] = {"metrics": metrics, "objective": round(objective(metrics), 6)}
    final_variant = max(
        VARIANTS, key=lambda name: (final_selection[name]["objective"], name)
    )
    final_model = train_model(
        training, cache, feature_names, VARIANTS[final_variant], seed=args.seed
    )
    external_records = evaluate(final_model, external, cache, feature_names)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_model.booster_.save_model(str(args.output_model))
    all_feature_names = [
        "static_score", "full_code_cosine", "focused_code_cosine",
        "full_focus_cosine", "operation_constraint", "status_query",
        *feature_names, *[f"operation::{item}" for item in OPERATIONS],
    ]
    gain_importance = final_model.booster_.feature_importance(
        importance_type="gain"
    )
    split_importance = final_model.booster_.feature_importance(
        importance_type="split"
    )
    feature_importance = sorted(
        [
            {
                "feature": name,
                "gain": round(float(gain), 6),
                "splits": int(splits),
            }
            for name, gain, splits in zip(
                all_feature_names, gain_importance, split_importance, strict=True
            )
        ],
        key=lambda item: (-item["gain"], item["feature"]),
    )

    v02 = read_json(args.v02_results)
    v02_records = v02["cross_validation"]["records"]["pretrained-code-calibrated-fusion"]
    report = {
        "schema_version": "0.3-tree",
        "method": "graded multiview LambdaMART with nested model-size selection",
        "variants": VARIANTS,
        "parsimonious_selection_tolerance": PARSIMONY_TOLERANCE,
        "feature_names": all_feature_names,
        "cross_validation": {
            "unit": "independence_group/vendor",
            "metrics": {name: aggregate(items) for name, items in records.items()},
            "paired_nested_vs_v02": paired_comparison(
                records["multiview-lambdamart-nested"], v02_records, seed=args.seed
            ),
            "paired_parsimonious_vs_v02": paired_comparison(
                records["multiview-lambdamart-nested-parsimonious"],
                v02_records,
                seed=args.seed,
            ),
            "fold_reports": fold_reports,
            "records": records,
        },
        "external_board_diagnostic": {
            "selected_variant": final_variant,
            "metrics": aggregate(external_records),
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "selected_variant": final_variant,
            "selection": final_selection,
            "feature_importance": feature_importance,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({
        "metrics": report["cross_validation"]["metrics"],
        "external": report["external_board_diagnostic"],
        "final": report["final_model"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
