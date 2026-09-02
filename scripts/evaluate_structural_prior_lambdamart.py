#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.hardware_effect_ranker import OPERATIONS
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.semantic_feasibility import semantic_feasibility_penalty
from bspforge.structured_retrieval import complete_structured_scores
from evaluate_hardware_effect_pu_ranker import fold_assignments, paired_comparison
from evaluate_lambdamart_training_optimizations import (
    BASE_TREE,
    extended_aggregate,
    numeric_feature_names,
    objective,
)
from evaluate_multiview_effect_ranker import record_for_scores
from evaluate_multiview_lambdamart import candidate_row


PRIOR_FEATURE_NAMES = [
    "semantic_feasibility_penalty",
    "structured_prior_score",
    "structured_prior_percentile",
    "structured_prior_reciprocal_rank",
    "structured_prior_leader_gap",
    "structured_prior_top1",
    "structured_prior_top3",
    "structured_prior_top5",
]
RESIDUAL_WEIGHTS = [0.10, 0.20, 0.35, 0.50, 0.75, 1.00]
TRUNCATION_LEVEL = 5


class StructuralPriorCache:
    def __init__(self) -> None:
        self._values: dict[str, dict[str, list[float]]] = {}

    def values(self, group: dict[str, Any]) -> dict[str, list[float]]:
        group_id = group["group_id"]
        if group_id in self._values:
            return self._values[group_id]
        scores, _ = complete_structured_scores(group)
        ranked = sorted(
            range(len(scores)),
            key=lambda index: (-scores[index], group["candidates"][index]["entity_id"]),
        )
        ranks = [0] * len(scores)
        for rank, index in enumerate(ranked, start=1):
            ranks[index] = rank
        count = max(len(scores), 1)
        leader = max(scores)
        result = {
            "scores": scores,
            "ranks": [float(rank) for rank in ranks],
            "percentiles": [
                1.0 - (rank - 1.0) / max(count - 1.0, 1.0) for rank in ranks
            ],
            "reciprocal_ranks": [1.0 / rank for rank in ranks],
            "leader_gaps": [score - leader for score in scores],
        }
        self._values[group_id] = result
        return result


def standardized(values: list[float]) -> list[float]:
    center = float(np.mean(values))
    scale = max(float(np.std(values)), 1e-8)
    return [(value - center) / scale for value in values]


def prior_row(
    group: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
    target_architecture: str | None = None,
) -> list[float]:
    prior = prior_cache.values(group)
    rank = int(prior["ranks"][index])
    return [
        *candidate_row(group, candidate, cache, feature_names),
        semantic_feasibility_penalty(
            group, candidate, target_architecture=target_architecture
        ),
        prior["scores"][index],
        prior["percentiles"][index],
        prior["reciprocal_ranks"][index],
        prior["leader_gaps"][index],
        float(rank == 1),
        float(rank <= 3),
        float(rank <= 5),
    ]


def matrix(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
) -> tuple[list[list[float]], list[int], list[int]]:
    values: list[list[float]] = []
    labels: list[int] = []
    sizes: list[int] = []
    for group in groups:
        sizes.append(len(group["candidates"]))
        for index, candidate in enumerate(group["candidates"]):
            values.append(
                prior_row(group, candidate, index, cache, prior_cache, feature_names)
            )
            labels.append(int(candidate["label"]))
    return values, labels, sizes


def train_model(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
    *,
    seed: int,
) -> Any:
    import lightgbm

    values, labels, sizes = matrix(groups, cache, prior_cache, feature_names)
    model = lightgbm.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        lambdarank_truncation_level=TRUNCATION_LEVEL,
        random_state=seed,
        verbosity=-1,
        **BASE_TREE,
    )
    model.fit(values, labels, group=sizes)
    return model


def learned_scores(
    model: Any,
    group: dict[str, Any],
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
    target_architecture: str | None = None,
) -> list[float]:
    values = [
        prior_row(
            group,
            candidate,
            index,
            cache,
            prior_cache,
            feature_names,
            target_architecture,
        )
        for index, candidate in enumerate(group["candidates"])
    ]
    scores = [float(value) for value in model.predict(values)]
    return [
        score
        - 8.0
        * semantic_feasibility_penalty(
            group, candidate, target_architecture=target_architecture
        )
        for score, candidate in zip(scores, group["candidates"], strict=True)
    ]


def residual_scores(
    group: dict[str, Any],
    model_scores: list[float],
    prior_cache: StructuralPriorCache,
    weight: float,
    target_architecture: str | None = None,
) -> list[float]:
    prior = standardized(prior_cache.values(group)["scores"])
    learned = standardized(model_scores)
    return [
        prior_score
        + weight * learned_score
        - 8.0
        * semantic_feasibility_penalty(
            group, candidate, target_architecture=target_architecture
        )
        for prior_score, learned_score, candidate in zip(
            prior, learned, group["candidates"], strict=True
        )
    ]


def evaluate(
    model: Any,
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
    *,
    weight: float | None,
    target_profiles: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    records = []
    for group in groups:
        profile = (target_profiles or {}).get(group["sdk_id"], {})
        target_architecture = profile.get("target_architecture")
        scores = learned_scores(
            model,
            group,
            cache,
            prior_cache,
            feature_names,
            target_architecture,
        )
        if weight is not None:
            scores = residual_scores(
                group,
                scores,
                prior_cache,
                weight,
                target_architecture,
            )
        records.append(record_for_scores(group, scores))
    return records


def evaluate_prior(
    groups: list[dict[str, Any]],
    prior_cache: StructuralPriorCache,
    target_profiles: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    records = []
    for group in groups:
        profile = (target_profiles or {}).get(group["sdk_id"], {})
        target_architecture = profile.get("target_architecture")
        scores = [
            score
            - 8.0
            * semantic_feasibility_penalty(
                group, candidate, target_architecture=target_architecture
            )
            for score, candidate in zip(
                prior_cache.values(group)["scores"],
                group["candidates"],
                strict=True,
            )
        ]
        records.append(record_for_scores(group, scores))
    return records


def select_weight(
    model: Any,
    validation: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    prior_cache: StructuralPriorCache,
    feature_names: list[str],
) -> tuple[float, dict[str, Any]]:
    reports = {}
    for weight in RESIDUAL_WEIGHTS:
        metrics = extended_aggregate(
            evaluate(
                model,
                validation,
                cache,
                prior_cache,
                feature_names,
                weight=weight,
            )
        )
        reports[str(weight)] = {"metrics": metrics, "objective": objective(metrics)}
    selected = max(
        RESIDUAL_WEIGHTS,
        key=lambda weight: (reports[str(weight)]["objective"], -weight),
    )
    return selected, reports


def grouped_metrics(
    records: list[dict[str, Any]], key: str
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record[key]].append(record)
    return {
        name: {"queries": len(items), **extended_aggregate(items)}
        for name, items in sorted(grouped.items())
    }


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(
        description="Evaluate structural-prior augmented LambdaMART without external-label selection"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--target-profiles", type=Path)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260902)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [
        group for group in dataset["groups"] if group["role"] == "external-test"
    ]
    feature_names = numeric_feature_names(training)
    cache = MultiViewEffectCache(
        args.base_metadata,
        args.base_vectors,
        args.focused_metadata,
        args.focused_vectors,
    )
    prior_cache = StructuralPriorCache()
    target_profiles = (
        read_json(args.target_profiles).get("profiles", {})
        if args.target_profiles
        else {}
    )
    assignments = fold_assignments(training, args.folds)
    nested_records: list[dict[str, Any]] = []
    learned_records: list[dict[str, Any]] = []
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        outer_train = [
            group for group in training if group["independence_group"] not in test_ids
        ]
        test = [
            group for group in training if group["independence_group"] in test_ids
        ]
        validation_ids = fold_assignments(outer_train, 4)[0]
        inner_train = [
            group
            for group in outer_train
            if group["independence_group"] not in validation_ids
        ]
        validation = [
            group
            for group in outer_train
            if group["independence_group"] in validation_ids
        ]
        inner_model = train_model(
            inner_train,
            cache,
            prior_cache,
            feature_names,
            seed=args.seed + fold * 100,
        )
        selected_weight, weight_reports = select_weight(
            inner_model, validation, cache, prior_cache, feature_names
        )
        outer_model = train_model(
            outer_train,
            cache,
            prior_cache,
            feature_names,
            seed=args.seed + fold * 10,
        )
        fold_learned = evaluate(
            outer_model,
            test,
            cache,
            prior_cache,
            feature_names,
            weight=None,
        )
        fold_nested = evaluate(
            outer_model,
            test,
            cache,
            prior_cache,
            feature_names,
            weight=selected_weight,
        )
        learned_records.extend(fold_learned)
        nested_records.extend(fold_nested)
        fold_reports.append(
            {
                "fold": fold,
                "test_independence_groups": sorted(test_ids),
                "validation_independence_groups": sorted(validation_ids),
                "selected_residual_weight": selected_weight,
                "weight_selection": weight_reports,
                "learned_only_metrics": extended_aggregate(fold_learned),
                "nested_metrics": extended_aggregate(fold_nested),
            }
        )
        print(
            {
                "fold": fold,
                "selected_weight": selected_weight,
                "nested": extended_aggregate(fold_nested),
            },
            flush=True,
        )

    prior_training_records = evaluate_prior(training, prior_cache)
    final_validation_ids = fold_assignments(training, 4)[0]
    final_train = [
        group
        for group in training
        if group["independence_group"] not in final_validation_ids
    ]
    final_validation = [
        group
        for group in training
        if group["independence_group"] in final_validation_ids
    ]
    selection_model = train_model(
        final_train,
        cache,
        prior_cache,
        feature_names,
        seed=args.seed + 1000,
    )
    final_weight, final_weight_reports = select_weight(
        selection_model, final_validation, cache, prior_cache, feature_names
    )
    final_model = train_model(
        training,
        cache,
        prior_cache,
        feature_names,
        seed=args.seed,
    )
    external_learned = evaluate(
        final_model,
        external,
        cache,
        prior_cache,
        feature_names,
        weight=None,
        target_profiles=target_profiles,
    )
    external_residual = evaluate(
        final_model,
        external,
        cache,
        prior_cache,
        feature_names,
        weight=final_weight,
        target_profiles=target_profiles,
    )
    external_prior = evaluate_prior(external, prior_cache, target_profiles)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_model.booster_.save_model(str(args.output_model))

    model_feature_names = [
        "static_score",
        "full_code_cosine",
        "focused_code_cosine",
        "full_focus_cosine",
        "operation_constraint",
        "status_query",
        *feature_names,
        *[f"operation::{operation}" for operation in OPERATIONS],
        *PRIOR_FEATURE_NAMES,
    ]
    gains = final_model.booster_.feature_importance(importance_type="gain")
    splits = final_model.booster_.feature_importance(importance_type="split")
    importance = sorted(
        [
            {"feature": name, "gain": round(float(gain), 6), "splits": int(split)}
            for name, gain, split in zip(
                model_feature_names, gains, splits, strict=True
            )
        ],
        key=lambda item: (-item["gain"], item["feature"]),
    )
    report = {
        "schema_version": "structural-prior-lambdamart-v1",
        "created_at": utc_now(),
        "method": (
            "structural-prior augmented LambdaMART with training-only nested "
            "residual-weight selection"
        ),
        "protocol": {
            "cross_validation_unit": "independence_group/vendor",
            "external_labels_used_for_training": False,
            "external_labels_used_for_model_or_weight_selection": False,
            "external_board_set_role": "development diagnostic after truth revision",
            "target_architecture_profiles": str(args.target_profiles) if args.target_profiles else None,
            "residual_formula": "z(structured_prior) + weight * z(LambdaMART)",
            "residual_weight_candidates": RESIDUAL_WEIGHTS,
        },
        "inputs": {
            "dataset": str(args.dataset),
            "dataset_sha256": file_sha256(args.dataset),
            "base_metadata": str(args.base_metadata),
            "focused_metadata": str(args.focused_metadata),
        },
        "features": {
            "numeric_candidate_features": feature_names,
            "structural_prior_features": PRIOR_FEATURE_NAMES,
            "model_feature_names": model_feature_names,
        },
        "cross_validation": {
            "queries": len(training),
            "folds": args.folds,
            "structured_prior_metrics": extended_aggregate(prior_training_records),
            "learned_only_metrics": extended_aggregate(learned_records),
            "nested_residual_metrics": extended_aggregate(nested_records),
            "paired_residual_vs_prior": paired_comparison(
                nested_records, prior_training_records, seed=args.seed
            ),
            "fold_reports": fold_reports,
            "records": {
                "structured_prior": prior_training_records,
                "learned_only": learned_records,
                "nested_residual": nested_records,
            },
        },
        "final_model": {
            "path": str(args.output_model),
            "sha256": file_sha256(args.output_model),
            "selected_residual_weight": final_weight,
            "weight_selection": final_weight_reports,
            "feature_importance": importance,
        },
        "external_board_diagnostic": {
            "queries": len(external),
            "structured_prior_metrics": extended_aggregate(external_prior),
            "learned_only_metrics": extended_aggregate(external_learned),
            "residual_metrics": extended_aggregate(external_residual),
            "residual_by_sdk": grouped_metrics(external_residual, "sdk_id"),
            "structured_prior_by_sdk": grouped_metrics(external_prior, "sdk_id"),
            "paired_residual_vs_prior": paired_comparison(
                external_residual, external_prior, seed=args.seed
            ),
            "records": {
                "structured_prior": external_prior,
                "learned_only": external_learned,
                "residual": external_residual,
            },
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print(
        {
            "cross_validation": {
                "prior": report["cross_validation"]["structured_prior_metrics"],
                "learned": report["cross_validation"]["learned_only_metrics"],
                "residual": report["cross_validation"]["nested_residual_metrics"],
            },
            "final_weight": final_weight,
            "external": {
                "prior": report["external_board_diagnostic"][
                    "structured_prior_metrics"
                ],
                "learned": report["external_board_diagnostic"][
                    "learned_only_metrics"
                ],
                "residual": report["external_board_diagnostic"]["residual_metrics"],
                "by_sdk": report["external_board_diagnostic"]["residual_by_sdk"],
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
