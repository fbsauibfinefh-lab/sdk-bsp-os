#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.semantic_resolver.learning import FEATURE_NAMES
from bspforge.semantic_resolver.resolver import DEFAULT_CAPABILITIES


METRICS = ["precision_at_1", "recall_at_5", "recall_at_10", "mrr", "map", "ndcg_at_10"]
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def ranking_metrics(candidates: list[dict[str, Any]], scores: list[float]) -> dict[str, float]:
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-item[1], item[0]["entity_id"]),
    )
    unique_ranked = []
    seen_symbols: set[str] = set()
    for candidate, score in ranked:
        if candidate["symbol"] in seen_symbols:
            continue
        seen_symbols.add(candidate["symbol"])
        unique_ranked.append((candidate, score))
    labels = [int(item[0]["label"] > 0) for item in unique_ranked]
    relevant = sum(labels)
    positive_ranks = [index + 1 for index, label in enumerate(labels) if label]
    precision_at_1 = float(labels[0]) if labels else 0.0
    recall_at_5 = sum(labels[:5]) / relevant if relevant else 0.0
    recall_at_10 = sum(labels[:10]) / relevant if relevant else 0.0
    mrr = 1.0 / positive_ranks[0] if positive_ranks else 0.0
    running = 0
    precisions = []
    for index, label in enumerate(labels, start=1):
        if label:
            running += 1
            precisions.append(running / index)
    average_precision = sum(precisions) / relevant if relevant else 0.0
    dcg = sum(label / math.log2(index + 2) for index, label in enumerate(labels[:10]))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(relevant, 10)))
    return {
        "precision_at_1": precision_at_1,
        "recall_at_5": recall_at_5,
        "recall_at_10": recall_at_10,
        "mrr": mrr,
        "map": average_precision,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
    }


def bm25_scores(group: dict[str, Any], k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Return a reproducible lexical baseline over function names and source paths."""
    spec = DEFAULT_CAPABILITIES[group["capability"]]
    query = set(spec["terms"] + spec["actions"])
    documents = []
    for candidate in group["candidates"]:
        name_tokens = TOKEN_PATTERN.findall(candidate["symbol"].lower().replace("_", " "))
        path_tokens = TOKEN_PATTERN.findall(candidate["file"].lower().replace("_", " "))
        documents.append(name_tokens * 2 + path_tokens)
    average_length = mean(len(document) for document in documents) if documents else 1.0
    document_frequency = Counter(
        token for token in query for document in documents if token in set(document)
    )
    scores = []
    for document in documents:
        frequencies = Counter(document)
        score = 0.0
        for token in query:
            frequency = frequencies[token]
            if not frequency:
                continue
            frequency_docs = document_frequency[token]
            inverse_document_frequency = math.log(
                1.0 + (len(documents) - frequency_docs + 0.5) / (frequency_docs + 0.5)
            )
            denominator = frequency + k1 * (
                1.0 - b + b * len(document) / max(average_length, 1.0)
            )
            score += inverse_document_frequency * frequency * (k1 + 1.0) / denominator
        scores.append(score)
    return scores


def matrix(groups: list[dict[str, Any]], features: list[str]) -> tuple[list[list[float]], list[int], list[int]]:
    values: list[list[float]] = []
    labels: list[int] = []
    sizes: list[int] = []
    for group in groups:
        sizes.append(len(group["candidates"]))
        for candidate in group["candidates"]:
            values.append([float(candidate["features"][name]) for name in features])
            labels.append(int(candidate["label"]))
    return values, labels, sizes


def train_model(groups: list[dict[str, Any]], features: list[str], seed: int) -> Any:
    try:
        import lightgbm
    except ImportError as error:
        raise SystemExit("请先安装 BSPForge learning 可选依赖") from error
    values, labels, sizes = matrix(groups, features)
    model = lightgbm.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=180,
        learning_rate=0.04,
        num_leaves=15,
        min_child_samples=8,
        reg_lambda=0.2,
        random_state=seed,
        verbosity=-1,
    )
    model.fit(values, labels, group=sizes, feature_name=features)
    return model


def aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {name: round(mean(item["metrics"][name] for item in records), 6) for name in METRICS}


def bootstrap_delta(
    baseline: list[float],
    treatment: list[float],
    seed: int,
    samples: int = 10000,
) -> dict[str, float]:
    deltas = [right - left for left, right in zip(baseline, treatment, strict=True)]
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        estimates.append(mean(rng.choice(deltas) for _ in deltas))
    estimates.sort()
    return {
        "mean_delta": round(mean(deltas), 6),
        "ci95_low": round(estimates[int(samples * 0.025)], 6),
        "ci95_high": round(estimates[int(samples * 0.975)], 6),
    }


def paired_permutation_pvalue(
    baseline: list[float],
    treatment: list[float],
    seed: int,
    samples: int = 20000,
) -> float:
    deltas = [right - left for left, right in zip(baseline, treatment, strict=True)]
    observed = abs(mean(deltas))
    rng = random.Random(seed)
    exceed = 0
    for _ in range(samples):
        estimate = abs(mean(value if rng.random() < 0.5 else -value for value in deltas))
        exceed += estimate >= observed
    return round((exceed + 1) / (samples + 1), 6)


def select_hybrid_weight(
    training_groups: list[dict[str, Any]],
    choices: tuple[float, ...],
    seed: int,
) -> tuple[float, dict[str, float]]:
    sdk_ids = sorted({item["sdk_id"] for item in training_groups})
    scores = {weight: [] for weight in choices}
    for inner_index, held_out in enumerate(sdk_ids):
        inner_train = [item for item in training_groups if item["sdk_id"] != held_out]
        inner_test = [item for item in training_groups if item["sdk_id"] == held_out]
        model = train_model(inner_train, FEATURE_NAMES, seed + inner_index)
        for group in inner_test:
            values = [
                [float(item["features"][name]) for name in FEATURE_NAMES]
                for item in group["candidates"]
            ]
            learned = [float(value) for value in model.booster_.predict(values)]
            low = min(learned)
            span = max(learned) - low
            normalized = [(value - low) / span if span > 1e-12 else 0.0 for value in learned]
            baseline = [float(item["baseline_score"]) for item in group["candidates"]]
            for weight in choices:
                blended = [
                    weight * base + (1.0 - weight) * learned_score
                    for base, learned_score in zip(baseline, normalized, strict=True)
                ]
                scores[weight].append(ranking_metrics(group["candidates"], blended)["map"])
    means = {weight: mean(values) for weight, values in scores.items()}
    selected = max(choices, key=lambda weight: (means[weight], weight))
    return selected, {f"{weight:.2f}": round(value, 6) for weight, value in means.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="执行按 SDK 留一的排序交叉验证和特征消融")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    groups = dataset["groups"]
    sdk_ids = sorted({item["sdk_id"] for item in groups})
    if len(sdk_ids) < 3:
        raise SystemExit("交叉验证至少需要三个独立 SDK")

    methods = {"weighted": None, "learned-full": FEATURE_NAMES}
    methods.update({f"learned-without-{name}": [item for item in FEATURE_NAMES if item != name] for name in FEATURE_NAMES})
    hybrid_weights = (0.25, 0.5, 0.75)
    nested_choices = (0.0, 0.25, 0.5, 0.75, 1.0)
    records: dict[str, list[dict[str, Any]]] = {name: [] for name in methods}
    records["bm25-lexical"] = []
    records.update({f"hybrid-weighted-{weight:.2f}": [] for weight in hybrid_weights})
    records["hybrid-nested"] = []
    folds = []
    for fold_index, held_out in enumerate(sdk_ids):
        train = [item for item in groups if item["sdk_id"] != held_out]
        test = [item for item in groups if item["sdk_id"] == held_out]
        selected_weight, inner_scores = select_hybrid_weight(
            train, nested_choices, args.seed + 1000 + fold_index * 100
        )
        fold_models = {
            name: train_model(train, features, args.seed + fold_index)
            for name, features in methods.items()
            if features is not None
        }
        fold_results = []
        for group in test:
            score_cache: dict[str, list[float]] = {}
            bm25_result = {
                "group_id": group["group_id"],
                "sdk_id": held_out,
                "capability": group["capability"],
                "method": "bm25-lexical",
                "metrics": ranking_metrics(group["candidates"], bm25_scores(group)),
            }
            records["bm25-lexical"].append(bm25_result)
            fold_results.append(bm25_result)
            for method, features in methods.items():
                if features is None:
                    scores = [float(item["baseline_score"]) for item in group["candidates"]]
                else:
                    values = [[float(item["features"][name]) for name in features] for item in group["candidates"]]
                    scores = [float(value) for value in fold_models[method].booster_.predict(values)]
                score_cache[method] = scores
                result = {
                    "group_id": group["group_id"],
                    "sdk_id": held_out,
                    "capability": group["capability"],
                    "method": method,
                    "metrics": ranking_metrics(group["candidates"], scores),
                }
                records[method].append(result)
                fold_results.append(result)
            learned = score_cache["learned-full"]
            low = min(learned)
            span = max(learned) - low
            normalized = [(value - low) / span if span > 1e-12 else 0.0 for value in learned]
            for weight in hybrid_weights:
                method = f"hybrid-weighted-{weight:.2f}"
                scores = [
                    weight * baseline + (1.0 - weight) * learned_score
                    for baseline, learned_score in zip(score_cache["weighted"], normalized, strict=True)
                ]
                result = {
                    "group_id": group["group_id"],
                    "sdk_id": held_out,
                    "capability": group["capability"],
                    "method": method,
                    "metrics": ranking_metrics(group["candidates"], scores),
                }
                records[method].append(result)
                fold_results.append(result)
            nested_scores = [
                selected_weight * baseline + (1.0 - selected_weight) * learned_score
                for baseline, learned_score in zip(score_cache["weighted"], normalized, strict=True)
            ]
            nested_result = {
                "group_id": group["group_id"],
                "sdk_id": held_out,
                "capability": group["capability"],
                "method": "hybrid-nested",
                "selected_weight": selected_weight,
                "metrics": ranking_metrics(group["candidates"], nested_scores),
            }
            records["hybrid-nested"].append(nested_result)
            fold_results.append(nested_result)
        folds.append({
            "held_out_sdk": held_out,
            "training_sdks": sorted(set(sdk_ids) - {held_out}),
            "training_groups": len(train),
            "test_groups": len(test),
            "selected_hybrid_weight": selected_weight,
            "inner_validation_map": inner_scores,
            "results": fold_results,
        })

    aggregate_results = {name: aggregate(items) for name, items in records.items()}
    significance = {}
    for comparison_index, treatment in enumerate(("bm25-lexical", "learned-full", "hybrid-nested", *[f"hybrid-weighted-{weight:.2f}" for weight in hybrid_weights])):
        significance[treatment] = {}
        for metric_index, metric in enumerate(METRICS):
            baseline = [item["metrics"][metric] for item in records["weighted"]]
            learned = [item["metrics"][metric] for item in records[treatment]]
            significance[treatment][metric] = {
                **bootstrap_delta(baseline, learned, args.seed + comparison_index * 20 + metric_index),
                "paired_permutation_p": paired_permutation_pvalue(
                    baseline, learned, args.seed + 100 + comparison_index * 20 + metric_index
                ),
            }
    ablations = {}
    for name, values in aggregate_results.items():
        if not name.startswith("learned-without-"):
            continue
        ablations[name.removeprefix("learned-without-")] = {
            metric: round(values[metric] - aggregate_results["learned-full"][metric], 6)
            for metric in METRICS
        }
    write_json(args.output, {
        "schema_version": "1.0",
        "protocol": "leave-one-SDK-out; no entity from the held-out SDK appears in training",
        "seed": args.seed,
        "dataset_summary": dataset["summary"],
        "folds": folds,
        "aggregate": aggregate_results,
        "comparisons_vs_weighted": significance,
        "learned_feature_ablation_delta": ablations,
    })
    print(f"result: {args.output}")
    print({name: aggregate_results[name] for name in ("bm25-lexical", "weighted", "learned-full", "hybrid-nested")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
