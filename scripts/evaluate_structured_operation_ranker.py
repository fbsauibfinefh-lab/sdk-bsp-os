#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.operation_constraints import constrained_rerank, contract_adjustment
from evaluate_operation_ranker import METRICS, ranking_metrics


def aggregate(records: list[dict[str, float]]) -> dict[str, float]:
    return {name: round(mean(item[name] for item in records), 6) for name in METRICS}


def unary_scores(groups: list[dict[str, Any]], static_weight: float) -> dict[str, dict[str, float]]:
    output = {}
    for group in groups:
        output[group["group_id"]] = {
            item["entity_id"]: (
                static_weight * float(item["static_score"])
                + (1.0 - static_weight) * float(item["features"]["field-late-interaction"])
            )
            for item in group["candidates"]
        }
    return output


def evaluate(
    groups: list[dict[str, Any]],
    static_weight: float,
    pair_weight: float,
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    scores = unary_scores(groups, static_weight)
    capability_sets = defaultdict(list)
    for group in groups:
        capability_sets[(group["sdk_id"], group["capability"])].append(group)
    structured = {}
    diagnostics = []
    for (sdk_id, capability), capability_groups in capability_sets.items():
        values, detail = constrained_rerank(
            capability,
            capability_groups,
            scores,
            pair_weight=pair_weight,
        )
        structured.update(values)
        diagnostics.append({"sdk_id": sdk_id, "capability": capability, **detail})
    records = []
    confidence_records = []
    for group in groups:
        values = structured[group["group_id"]]
        metrics = ranking_metrics(group["candidates"], values)
        records.append(metrics)
        ranked = sorted(
            zip(group["candidates"], values, strict=True),
            key=lambda item: (-item[1], item[0]["entity_id"]),
        )
        unique = []
        seen = set()
        for candidate, value in ranked:
            if candidate["symbol"] in seen:
                continue
            seen.add(candidate["symbol"])
            unique.append((candidate, float(value)))
        top, top_score = unique[0]
        margin = top_score - unique[1][1] if len(unique) > 1 else top_score
        static_top = max(
            group["candidates"], key=lambda item: (float(item["static_score"]), item["entity_id"])
        )["entity_id"]
        field_top = max(
            group["candidates"],
            key=lambda item: (
                float(item["features"].get("field-late-interaction", 0.0)), item["entity_id"]
            ),
        )["entity_id"]
        adjustment, adjustment_evidence = contract_adjustment(top)
        readiness = 1.0 if adjustment >= 0.0 else max(0.0, 1.0 + adjustment)
        agreement = (int(top["entity_id"] == static_top) + int(top["entity_id"] == field_top)) / 2.0
        confidence = (
            0.40 * min(1.0, max(0.0, margin) / 0.20)
            + 0.25 * agreement
            + 0.20 * readiness
            + 0.15 * min(1.0, max(0.0, top_score))
        )
        confidence_records.append({
            "group_id": group["group_id"],
            "sdk_id": group["sdk_id"],
            "operation_id": group["operation_id"],
            "top_entity_id": top["entity_id"],
            "top_symbol": top["symbol"],
            "correct": int(top["label"] > 0),
            "score": round(top_score, 6),
            "margin": round(margin, 6),
            "static_field_agreement": agreement,
            "contract_readiness": round(readiness, 6),
            "contract_evidence": adjustment_evidence,
            "confidence": round(confidence, 6),
        })
    return aggregate(records), diagnostics, confidence_records


def calibrate_selective(
    development: list[dict[str, Any]],
    external: list[dict[str, Any]],
    target_precision: float = 0.95,
) -> dict[str, Any]:
    # Weak development truth is optimistic. Require a perfect empirical subset
    # in every held-out SDK and deploy the most conservative per-SDK threshold.
    required_precision = 1.0
    per_sdk = {}
    for sdk_id in sorted({item["sdk_id"] for item in development}):
        sdk_records = [item for item in development if item["sdk_id"] == sdk_id]
        choices = []
        for threshold in sorted({item["confidence"] for item in sdk_records}):
            accepted = [item for item in sdk_records if item["confidence"] >= threshold]
            if accepted and mean(item["correct"] for item in accepted) >= required_precision:
                choices.append((len(accepted), threshold))
        if choices:
            accepted_count, threshold = max(choices, key=lambda item: (item[0], item[1]))
            per_sdk[sdk_id] = {"threshold": threshold, "accepted": accepted_count}
    if len(per_sdk) != len({item["sdk_id"] for item in development}):
        return {"target_precision": target_precision, "status": "no-feasible-threshold"}
    threshold = max(item["threshold"] for item in per_sdk.values())
    development_accepted = [item for item in development if item["confidence"] >= threshold]
    external_accepted = [item for item in external if item["confidence"] >= threshold]
    return {
        "target_precision": target_precision,
        "status": "calibrated-on-development-only",
        "threshold": threshold,
        "required_empirical_precision": required_precision,
        "per_sdk_thresholds": per_sdk,
        "development": {
            "accepted": len(development_accepted),
            "coverage": round(len(development_accepted) / len(development), 6),
            "precision": round(mean(item["correct"] for item in development_accepted), 6),
        },
        "external": {
            "accepted": len(external_accepted),
            "coverage": round(len(external_accepted) / len(external), 6),
            "precision": (
                round(mean(item["correct"] for item in external_accepted), 6)
                if external_accepted else None
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="评估字段迟交互与能力级组合约束解码")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    split = read_json(args.split)
    development_ids = set(split["development_groups"])
    development = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] in development_ids
    ]
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    grid = []
    for static_weight in (0.0, 0.25, 0.50, 0.75, 1.0):
        for pair_weight in (0.0, 0.05, 0.10, 0.20, 0.35):
            metrics, _, _ = evaluate(development, static_weight, pair_weight)
            grid.append({
                "static_weight": static_weight,
                "field_weight": 1.0 - static_weight,
                "pair_weight": pair_weight,
                "development": metrics,
            })
    selected = max(
        grid,
        key=lambda item: (
            item["development"]["map"],
            item["development"]["precision_at_1"],
            item["development"]["recall_at_5"],
        ),
    )
    external_metrics, diagnostics, external_confidence = evaluate(
        external,
        selected["static_weight"],
        selected["pair_weight"],
    )
    development_metrics, _, development_confidence = evaluate(
        development, selected["static_weight"], selected["pair_weight"]
    )
    static_metrics, _, _ = evaluate(external, 1.0, 0.0)
    field_metrics, _, _ = evaluate(external, 0.0, 0.0)
    selective = calibrate_selective(development_confidence, external_confidence)
    report = {
        "schema_version": "1.0",
        "method": "field-aware late interaction with capability-level constrained decoding",
        "development_independence_groups": sorted(development_ids),
        "external_test_sdks": sorted({item["sdk_id"] for item in external}),
        "selection_grid": grid,
        "selected": selected,
        "external": {
            "operation-static": static_metrics,
            "field-late-interaction": field_metrics,
            "structured-selected": external_metrics,
        },
        "selected_development": development_metrics,
        "selective_calibration": selective,
        "external_confidence_records": external_confidence,
        "diagnostics": diagnostics,
    }
    write_json(args.output, report)
    print({"selected": selected, "external": report["external"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
