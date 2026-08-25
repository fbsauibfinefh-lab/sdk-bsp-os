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
from bspforge.operation_ranking import OPERATION_FEATURE_NAMES


METRICS = ["precision_at_1", "recall_at_3", "recall_at_5", "mrr", "map", "ndcg_at_10"]
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def ranking_metrics(candidates: list[dict[str, Any]], scores: list[float]) -> dict[str, float]:
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-item[1], item[0]["entity_id"]),
    )
    unique = []
    seen = set()
    for candidate, score in ranked:
        if candidate["symbol"] in seen:
            continue
        seen.add(candidate["symbol"])
        unique.append((candidate, score))
    labels = [int(item[0]["label"] > 0) for item in unique]
    relevant = sum(labels)
    positive_ranks = [index + 1 for index, label in enumerate(labels) if label]
    precisions = []
    found = 0
    for index, label in enumerate(labels, start=1):
        if label:
            found += 1
            precisions.append(found / index)
    dcg = sum(label / math.log2(index + 2) for index, label in enumerate(labels[:10]))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(relevant, 10)))
    return {
        "precision_at_1": float(labels[0]) if labels else 0.0,
        "recall_at_3": sum(labels[:3]) / relevant if relevant else 0.0,
        "recall_at_5": sum(labels[:5]) / relevant if relevant else 0.0,
        "mrr": 1.0 / positive_ranks[0] if positive_ranks else 0.0,
        "map": sum(precisions) / relevant if relevant else 0.0,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
    }


def ranking_diagnostics(candidates: list[dict[str, Any]], scores: list[float]) -> dict[str, Any]:
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-item[1], item[0]["entity_id"]),
    )
    unique = []
    seen = set()
    for candidate, score in ranked:
        if candidate["symbol"] in seen:
            continue
        seen.add(candidate["symbol"])
        unique.append((candidate, score))
    positive_ranks = [
        index
        for index, (candidate, _) in enumerate(unique, start=1)
        if candidate["label"] > 0
    ]
    return {
        "first_positive_rank": positive_ranks[0] if positive_ranks else None,
        "top_candidates": [
            {
                "rank": index,
                "symbol": candidate["symbol"],
                "file": candidate["file"],
                "score": round(float(score), 6),
                "label": candidate["label"],
            }
            for index, (candidate, score) in enumerate(unique[:5], start=1)
        ],
    }


def selective_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    output = {}
    for threshold in (0.0, 0.02, 0.05, 0.10, 0.20):
        accepted = []
        for record in records:
            top = record["diagnostics"]["top_candidates"]
            if not top:
                continue
            margin = top[0]["score"] - top[1]["score"] if len(top) > 1 else top[0]["score"]
            if margin >= threshold:
                accepted.append(int(top[0]["label"] > 0))
        output[f"margin_{threshold:.2f}"] = {
            "coverage": round(len(accepted) / len(records), 6) if records else 0.0,
            "selective_precision": round(mean(accepted), 6) if accepted else 0.0,
            "accepted_groups": len(accepted),
        }
    return output


def matrix(groups: list[dict[str, Any]], features: list[str]) -> tuple[list[list[float]], list[int], list[int]]:
    values = []
    labels = []
    sizes = []
    for group in groups:
        sizes.append(len(group["candidates"]))
        for candidate in group["candidates"]:
            values.append([float(candidate["features"].get(name, 0.0)) for name in features])
            labels.append(int(candidate["label"]))
    return values, labels, sizes


def train_model(groups: list[dict[str, Any]], features: list[str], seed: int) -> Any:
    import lightgbm

    values, labels, sizes = matrix(groups, features)
    model = lightgbm.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=120,
        learning_rate=0.035,
        num_leaves=9,
        max_depth=5,
        min_child_samples=20,
        reg_lambda=1.0,
        reg_alpha=0.2,
        random_state=seed,
        verbosity=-1,
    )
    model.fit(values, labels, group=sizes, feature_name=features)
    return model


def predict(model: Any, group: dict[str, Any], features: list[str]) -> list[float]:
    values = [
        [float(candidate["features"].get(name, 0.0)) for name in features]
        for candidate in group["candidates"]
    ]
    raw = [float(item) for item in model.booster_.predict(values)]
    low = min(raw)
    span = max(raw) - low
    return [(item - low) / span if span > 1e-12 else 0.0 for item in raw]


def bm25_scores(group: dict[str, Any], k1: float = 1.2, b: float = 0.75) -> list[float]:
    query = set(TOKEN_PATTERN.findall(group["query_text"].lower()))
    documents = [TOKEN_PATTERN.findall(item["candidate_text"].lower()) for item in group["candidates"]]
    average_length = mean(len(item) for item in documents) if documents else 1.0
    frequencies = Counter(token for token in query for document in documents if token in set(document))
    scores = []
    for document in documents:
        counts = Counter(document)
        score = 0.0
        for token in query:
            count = counts[token]
            if not count:
                continue
            document_count = frequencies[token]
            inverse = math.log(1.0 + (len(documents) - document_count + 0.5) / (document_count + 0.5))
            denominator = count + k1 * (1.0 - b + b * len(document) / max(average_length, 1.0))
            score += inverse * count * (k1 + 1.0) / denominator
        scores.append(score)
    return scores


def aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {name: round(mean(item["metrics"][name] for item in records), 6) for name in METRICS}


def select_weight(
    groups: list[dict[str, Any]],
    features: list[str],
    choices: tuple[float, ...],
    seed: int,
) -> tuple[float, dict[str, float]]:
    independence_groups = sorted({item["independence_group"] for item in groups})
    scores = {weight: [] for weight in choices}
    for index, held_out in enumerate(independence_groups):
        training = [item for item in groups if item["independence_group"] != held_out]
        validation = [item for item in groups if item["independence_group"] == held_out]
        model = train_model(training, features, seed + index)
        for group in validation:
            learned = predict(model, group, features)
            static = [float(item["static_score"]) for item in group["candidates"]]
            for weight in choices:
                blended = [weight * base + (1.0 - weight) * learned_score for base, learned_score in zip(static, learned, strict=True)]
                scores[weight].append(ranking_metrics(group["candidates"], blended)["map"])
    averages = {weight: mean(values) for weight, values in scores.items()}
    selected = max(choices, key=lambda item: (averages[item], item))
    return selected, {f"{key:.2f}": round(value, 6) for key, value in averages.items()}


def bootstrap_delta(
    baseline: list[float], treatment: list[float], seed: int, samples: int = 10000
) -> dict[str, float]:
    deltas = [right - left for left, right in zip(baseline, treatment, strict=True)]
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choice(deltas) for _ in deltas) for _ in range(samples))
    return {
        "mean_delta": round(mean(deltas), 6),
        "ci95_low": round(estimates[int(samples * 0.025)], 6),
        "ci95_high": round(estimates[int(samples * 0.975)], 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="训练操作级排序器并在三块实板 SDK 上执行外部测试")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("models/operation-ranker.txt"))
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    training = [item for item in dataset["groups"] if item["role"] == "train"]
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    if len({item["independence_group"] for item in training}) < 20:
        raise SystemExit("训练数据必须包含至少 20 个独立性分组")
    learning_features = [
        name
        for name in OPERATION_FEATURE_NAMES
        if name != "code-embedding"
        or any(candidate["features"].get(name, 0.0) for group in training for candidate in group["candidates"])
    ]
    has_external_embedding = any(
        candidate["features"].get("code-embedding", 0.0)
        for group in external
        for candidate in group["candidates"]
    )
    selected_weight, validation_scores = select_weight(
        training, learning_features, (0.0, 0.25, 0.5, 0.75, 1.0), args.seed
    )
    model = train_model(training, learning_features, args.seed)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(args.model))
    records = {name: [] for name in ("bm25-lexical", "operation-static", "learned-weak", "hybrid-selected")}
    if has_external_embedding:
        records["embedding-only"] = []
        for weight in (0.25, 0.5, 0.75):
            records[f"static-embedding-{weight:.2f}"] = []
    for group in external:
        score_sets = {
            "bm25-lexical": bm25_scores(group),
            "operation-static": [float(item["static_score"]) for item in group["candidates"]],
            "learned-weak": predict(model, group, learning_features),
        }
        score_sets["hybrid-selected"] = [
            selected_weight * base + (1.0 - selected_weight) * learned
            for base, learned in zip(score_sets["operation-static"], score_sets["learned-weak"], strict=True)
        ]
        if "embedding-only" in records:
            score_sets["embedding-only"] = [float(item["features"]["code-embedding"]) for item in group["candidates"]]
            for weight in (0.25, 0.5, 0.75):
                score_sets[f"static-embedding-{weight:.2f}"] = [
                    weight * static + (1.0 - weight) * embedding
                    for static, embedding in zip(
                        score_sets["operation-static"], score_sets["embedding-only"], strict=True
                    )
                ]
        for method, scores in score_sets.items():
            records[method].append({
                "group_id": group["group_id"],
                "sdk_id": group["sdk_id"],
                "operation_id": group["operation_id"],
                "method": method,
                "metrics": ranking_metrics(group["candidates"], scores),
                "diagnostics": ranking_diagnostics(group["candidates"], scores),
            })
    aggregates = {name: aggregate(items) for name, items in records.items()}
    selective = {name: selective_metrics(items) for name, items in records.items()}
    comparisons = {}
    for index, method in enumerate(name for name in records if name != "operation-static"):
        comparisons[method] = {
            metric: bootstrap_delta(
                [item["metrics"][metric] for item in records["operation-static"]],
                [item["metrics"][metric] for item in records[method]],
                args.seed + index * 20 + metric_index,
            )
            for metric_index, metric in enumerate(METRICS)
        }
    write_json(args.output, {
        "schema_version": "1.0",
        "protocol": "22 training corpora / 20 independence groups; three board SDKs are external test only",
        "dataset_summary": dataset["summary"],
        "active_features": learning_features,
        "external_embedding_evaluated": has_external_embedding,
        "embedding": dataset.get("embedding"),
        "selected_static_weight": selected_weight,
        "training_group_validation_map": validation_scores,
        "aggregate": aggregates,
        "selective": selective,
        "comparisons_vs_operation_static": comparisons,
        "external_results": records,
    })
    write_json(args.model.with_suffix(args.model.suffix + ".json"), {
        "feature_names": learning_features,
        "selected_static_weight": selected_weight,
        "training_sdks": sorted({item["sdk_id"] for item in training}),
        "excluded_external_sdks": sorted({item["sdk_id"] for item in external}),
    })
    print(aggregates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
