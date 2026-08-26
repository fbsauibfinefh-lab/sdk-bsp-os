#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.adaptive_field_ranker import AdaptiveFieldRanker
from bspforge.common import read_json, write_json
from bspforge.structured_retrieval import complete_structured_scores, family_diversified_scores
from evaluate_operation_ranker import METRICS, bootstrap_delta, ranking_metrics


def aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {
        name: round(mean(item["metrics"][name] for item in records), 6)
        for name in METRICS
    }


def normalize(scores: list[float]) -> list[float]:
    low = min(scores)
    span = max(scores) - low
    return [(item - low) / span if span > 1e-12 else 0.0 for item in scores]


def score_channels(group: dict[str, Any], ranker: AdaptiveFieldRanker) -> dict[str, list[float]]:
    static = [float(item["static_score"]) for item in group["candidates"]]
    field = [float(item["features"]["field-late-interaction"]) for item in group["candidates"]]
    rrf = [float(item["features"]["multi-channel-rrf"]) for item in group["candidates"]]
    contract = [
        float(item["features"]["operation-contract-retrieval"])
        for item in group["candidates"]
    ]
    layer = [float(item["features"]["layer-route-score"]) for item in group["candidates"]]
    adaptive = normalize(ranker.predict(group))
    return {
        "static": static,
        "field": field,
        "structured-rrf": rrf,
        "contract": contract,
        "layer": layer,
        "adaptive": adaptive,
    }


def blend_scores(channels: dict[str, list[float]], weights: tuple[float, float, float]) -> list[float]:
    return [
        weights[0] * static + weights[1] * field + weights[2] * rrf
        for static, field, rrf in zip(
            channels["static"], channels["field"], channels["structured-rrf"], strict=True
        )
    ]


def contract_fallback_leader(
    group: dict[str, Any], precision: list[float], hierarchy: list[float]
) -> list[float]:
    base_top = max(
        range(len(precision)),
        key=lambda index: (precision[index], group["candidates"][index]["entity_id"]),
    )
    candidate = group["candidates"][base_top]
    features = candidate["features"]
    role = float(features.get("source-role-prior", 0.0))
    contract = float(features.get("operation-contract-retrieval", 0.0))
    best_public_layer = max(
        (
            float(item["features"].get("layer-route-score", 0.0))
            for item in group["candidates"]
            if float(item["features"].get("source-role-prior", 0.0)) >= 0.90
        ),
        default=0.0,
    )
    if contract < 0.18 or role < 0.78 or (role < 0.90 and best_public_layer >= 0.45):
        return hierarchy
    return precision


def select_linear_weights(
    groups: list[dict[str, Any]], ranker: AdaptiveFieldRanker
) -> tuple[tuple[float, float, float], list[dict[str, Any]]]:
    grid = []
    choices = [index / 10.0 for index in range(11)]
    for static_weight in choices:
        for field_weight in choices:
            if static_weight + field_weight > 1.0:
                continue
            weights = (static_weight, field_weight, 1.0 - static_weight - field_weight)
            records = []
            for group in groups:
                metrics = ranking_metrics(
                    group["candidates"], blend_scores(score_channels(group, ranker), weights)
                )
                records.append({"metrics": metrics})
            grid.append({"weights": weights, "development": aggregate(records)})
    selected = max(
        grid,
        key=lambda item: (
            item["development"]["map"],
            item["development"]["recall_at_5"],
            item["development"]["precision_at_1"],
        ),
    )
    return tuple(selected["weights"]), grid


def select_adaptive_blend(
    groups: list[dict[str, Any]], ranker: AdaptiveFieldRanker, linear_weights: tuple[float, float, float]
) -> tuple[float, list[dict[str, Any]]]:
    grid = []
    for adaptive_weight in (0.50, 0.65, 0.80, 0.90, 1.0):
        records = []
        for group in groups:
            channels = score_channels(group, ranker)
            linear = blend_scores(channels, linear_weights)
            scores = [
                adaptive_weight * adaptive + (1.0 - adaptive_weight) * base
                for adaptive, base in zip(channels["adaptive"], linear, strict=True)
            ]
            records.append({"metrics": ranking_metrics(group["candidates"], scores)})
        grid.append({"adaptive_weight": adaptive_weight, "development": aggregate(records)})
    selected = max(
        grid,
        key=lambda item: (
            item["development"]["map"],
            item["development"]["recall_at_5"],
            item["development"]["precision_at_1"],
        ),
    )
    return float(selected["adaptive_weight"]), grid


def confidence_record(
    group: dict[str, Any], scores: list[float], channels: dict[str, list[float]]
) -> dict[str, Any]:
    ranked = sorted(
        zip(group["candidates"], scores, strict=True),
        key=lambda item: (-item[1], item[0]["entity_id"]),
    )
    unique = []
    seen = set()
    for candidate, score in ranked:
        if candidate["symbol"] in seen:
            continue
        seen.add(candidate["symbol"])
        unique.append((candidate, float(score)))
    top, top_score = unique[0]
    margin = top_score - unique[1][1] if len(unique) > 1 else top_score
    channel_top = []
    for values in channels.values():
        index = max(range(len(values)), key=lambda item: (values[item], group["candidates"][item]["entity_id"]))
        channel_top.append(group["candidates"][index]["entity_id"])
    agreement = sum(item == top["entity_id"] for item in channel_top) / len(channel_top)
    role = float(top["features"].get("source-role-prior", 0.0))
    confidence = 0.45 * min(1.0, max(0.0, margin) / 0.30) + 0.35 * agreement + 0.20 * role
    return {
        "group_id": group["group_id"],
        "sdk_id": group["sdk_id"],
        "operation_id": group["operation_id"],
        "top_symbol": top["symbol"],
        "correct": int(top["label"] > 0),
        "margin": round(margin, 6),
        "agreement": round(agreement, 6),
        "source_role_prior": round(role, 6),
        "confidence": round(confidence, 6),
    }


def calibrate_selective(
    development: list[dict[str, Any]], external: list[dict[str, Any]]
) -> dict[str, Any]:
    thresholds = sorted({item["confidence"] for item in development})
    feasible = []
    for threshold in thresholds:
        accepted = [item for item in development if item["confidence"] >= threshold]
        if len(accepted) >= 5 and mean(item["correct"] for item in accepted) >= 0.95:
            feasible.append((len(accepted), threshold))
    if not feasible:
        return {"status": "no-feasible-threshold", "target_precision": 0.95}
    accepted_count, threshold = max(feasible, key=lambda item: (item[0], item[1]))
    development_accepted = [item for item in development if item["confidence"] >= threshold]
    external_accepted = [item for item in external if item["confidence"] >= threshold]
    return {
        "status": "calibrated-on-development-only",
        "target_precision": 0.95,
        "threshold": threshold,
        "development": {
            "accepted": accepted_count,
            "coverage": round(accepted_count / len(development), 6),
            "precision": round(mean(item["correct"] for item in development_accepted), 6),
        },
        "external": {
            "accepted": len(external_accepted),
            "coverage": round(len(external_accepted) / len(external), 6),
            "precision": round(mean(item["correct"] for item in external_accepted), 6)
            if external_accepted else None,
        },
    }


def evaluate_groups(
    groups: list[dict[str, Any]],
    ranker: AdaptiveFieldRanker,
    linear_weights: tuple[float, float, float],
    adaptive_weight: float,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confidence = []
    for group in groups:
        channels = score_channels(group, ranker)
        linear = blend_scores(channels, linear_weights)
        complete = [
            adaptive_weight * adaptive + (1.0 - adaptive_weight) * base
            for adaptive, base in zip(channels["adaptive"], linear, strict=True)
        ]
        contract_fusion = [
            0.35 * static + 0.35 * field + 0.30 * contract
            for static, field, contract in zip(
                channels["static"], channels["field"], channels["contract"], strict=True
            )
        ]
        hierarchical_fusion = [
            0.25 * static + 0.25 * field + 0.25 * contract + 0.25 * layer
            for static, field, contract, layer in zip(
                channels["static"],
                channels["field"],
                channels["contract"],
                channels["layer"],
                strict=True,
            )
        ]
        precision_scores = [
            0.50 * static + 0.50 * field
            for static, field in zip(channels["static"], channels["field"], strict=True)
        ]
        precision_leader = contract_fallback_leader(
            group, precision_scores, hierarchical_fusion
        )
        family_variants = {
            f"family-diversified-q{quota}": family_diversified_scores(
                group,
                hierarchical_fusion,
                leader_scores=precision_leader,
                family_quota=quota,
            )
            for quota in (2, 3, 4, 5)
        }
        final_scores, _ = complete_structured_scores(group, family_quota=4)
        methods = {
            "operation-static": channels["static"],
            "field-late-interaction": channels["field"],
            "structured-rrf": channels["structured-rrf"],
            "operation-contract": channels["contract"],
            "layer-route": channels["layer"],
            "contract-fusion": contract_fusion,
            "hierarchical-fusion": hierarchical_fusion,
            "development-selected-linear": linear,
            "adaptive-field-gate": channels["adaptive"],
            "complete-method": complete,
            **family_variants,
            "final-method": final_scores,
        }
        for method, scores in methods.items():
            ranked = sorted(
                zip(group["candidates"], scores, strict=True),
                key=lambda item: (-item[1], item[0]["entity_id"]),
            )
            unique = []
            seen = set()
            for candidate, value in ranked:
                if candidate["symbol"] in seen:
                    continue
                seen.add(candidate["symbol"])
                unique.append((candidate, value))
            records[method].append({
                "group_id": group["group_id"],
                "sdk_id": group["sdk_id"],
                "capability": group["capability"],
                "operation_id": group["operation_id"],
                "metrics": ranking_metrics(group["candidates"], scores),
                "top5": [
                    {"symbol": item["symbol"], "label": item["label"], "family": item.get("api_family")}
                    for item, _ in unique[:5]
                ],
                "positive_ranks": [
                    index for index, (item, _) in enumerate(unique, start=1) if item["label"] > 0
                ],
            })
        confidence.append(confidence_record(group, final_scores, channels))
    return records, confidence


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[item[key]].append(item)
    return {name: aggregate(items) for name, items in sorted(grouped.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="评估结构化多通道召回与自适应字段门控")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260826)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    development_ids = set(read_json(args.split)["development_groups"])
    development = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] in development_ids
    ]
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    ranker = AdaptiveFieldRanker()
    ranker.load_payload(ranker.torch.load(args.model, map_location="cpu", weights_only=True))
    ranker.network.eval()
    linear_weights, linear_grid = select_linear_weights(development, ranker)
    adaptive_weight, adaptive_grid = select_adaptive_blend(development, ranker, linear_weights)
    development_records, development_confidence = evaluate_groups(
        development, ranker, linear_weights, adaptive_weight
    )
    external_records, external_confidence = evaluate_groups(
        external, ranker, linear_weights, adaptive_weight
    )
    aggregates = {name: aggregate(items) for name, items in external_records.items()}
    baseline = external_records["operation-static"]
    comparisons = {
        method: {
            metric: bootstrap_delta(
                [item["metrics"][metric] for item in baseline],
                [item["metrics"][metric] for item in records],
                args.seed + method_index * 20 + metric_index,
            )
            for metric_index, metric in enumerate(METRICS)
        }
        for method_index, (method, records) in enumerate(external_records.items())
        if method != "operation-static"
    }
    complete = external_records["final-method"]
    report = {
        "schema_version": "1.0",
        "method": "source-role-aware multi-channel retrieval plus capability-adaptive field late interaction",
        "protocol": "16 training independence groups; 4 development groups; 3 board SDKs external only",
        "selected_on_development": {
            "linear_weights": {
                "static": linear_weights[0], "field": linear_weights[1], "structured_rrf": linear_weights[2]
            },
            "adaptive_weight": adaptive_weight,
            "linear_grid": linear_grid,
            "adaptive_grid": adaptive_grid,
        },
        "development": {name: aggregate(items) for name, items in development_records.items()},
        "external": aggregates,
        "external_by_sdk": breakdown(complete, "sdk_id"),
        "external_by_capability": breakdown(complete, "capability"),
        "comparisons_vs_operation_static": comparisons,
        "selective_calibration": calibrate_selective(
            development_confidence, external_confidence
        ),
        "external_confidence_records": external_confidence,
        "external_records": external_records,
    }
    write_json(args.output, report)
    print({
        "selected": report["selected_on_development"],
        "external": report["external"],
        "selective": report["selective_calibration"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
