#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_graph import hard_constraint_penalty


FORBIDDEN_ROLES = {"documentation", "example-test", "os-adapter"}


def calls(candidate: dict[str, Any]) -> set[str]:
    marker = "\ncalls:"
    text = candidate.get("candidate_text", "")
    if marker not in text:
        return set()
    return set(text.split(marker, 1)[1].strip().split())


def symbol_tail(symbol: str) -> str:
    return symbol.rsplit("::", 1)[-1]


def safe_public_wrapper(candidate: dict[str, Any]) -> bool:
    features = candidate.get("features", {})
    return (
        candidate.get("source_role") not in FORBIDDEN_ROLES
        and float(features.get("hw-composite-likelihood", 0.0)) < 0.75
        and hard_constraint_penalty(candidate) <= 0.0
        and (
            float(features.get("public-api", 0.0)) > 0.0
            or float(features.get("hw-public-boundary", 0.0)) > 0.0
            or candidate.get("source_role") in {"public-hal", "public-header", "sdk-driver"}
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="分析Top1严格错误中的直接调用等价上界")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--method", default="nested-selected")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    results = read_json(args.results)
    groups = {item["group_id"]: item for item in dataset["groups"] if item["role"] == "train"}
    records = results["cross_validation"]["records"][args.method]
    cases = []
    strict_correct = 0
    safe_wrapper_upper = 0
    any_direct_relation_upper = 0
    hit_at_5 = 0
    positive_counts = []
    recall_upper_bounds = []
    relation_counts: Counter[str] = Counter()
    for record in records:
        group = groups[record["group_id"]]
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for candidate in group["candidates"]:
            by_symbol.setdefault(candidate["symbol"], []).append(candidate)
        positive_symbols = {
            symbol for symbol, items in by_symbol.items()
            if max(int(item["label"]) for item in items) > 0
        }
        positive_counts.append(len(positive_symbols))
        recall_upper_bounds.append(min(5, len(positive_symbols)) / len(positive_symbols))
        predicted = record["selected"]["symbol"]
        if predicted in positive_symbols:
            strict_correct += 1
            safe_wrapper_upper += 1
            any_direct_relation_upper += 1
            continue
        top5_hit = any(item["label"] > 0 for item in record["top5"])
        hit_at_5 += int(top5_hit)
        predicted_items = by_symbol.get(predicted, [])
        positive_items = [item for symbol in positive_symbols for item in by_symbol[symbol]]
        positive_tails = {symbol_tail(item) for item in positive_symbols}
        predicted_tail = symbol_tail(predicted)
        predicted_calls_positive = any(calls(item) & positive_tails for item in predicted_items)
        positive_calls_predicted = any(predicted_tail in calls(item) for item in positive_items)
        safe_wrapper = predicted_calls_positive and any(safe_public_wrapper(item) for item in predicted_items)
        relation = "none"
        if predicted_calls_positive and positive_calls_predicted:
            relation = "bidirectional-direct"
        elif predicted_calls_positive:
            relation = "predicted-wrapper-calls-positive"
        elif positive_calls_predicted:
            relation = "positive-calls-predicted-helper"
        relation_counts[relation] += 1
        safe_wrapper_upper += int(safe_wrapper)
        any_direct_relation_upper += int(predicted_calls_positive or positive_calls_predicted)
        cases.append({
            "group_id": group["group_id"],
            "sdk_id": group["sdk_id"],
            "operation_id": group["operation_id"],
            "predicted_symbol": predicted,
            "positive_symbols": sorted(positive_symbols),
            "top5": record["top5"],
            "top5_contains_positive": top5_hit,
            "direct_relation": relation,
            "safe_predicted_wrapper_upper_bound": safe_wrapper,
        })

    total = len(records)
    strict_failures = total - strict_correct
    report = {
        "schema_version": "top1-call-equivalence-v1",
        "truth_set": dataset.get("truth_set_id"),
        "method": args.method,
        "scope": {
            "groups": total,
            "strict_failures": strict_failures,
            "note": "调用关系仅用于定位可能漏标的包装函数，不自动改写正式正确性。",
        },
        "metrics": {
            "strict_precision_at_1": round(strict_correct / total, 6),
            "safe_direct_wrapper_upper_bound_at_1": round(safe_wrapper_upper / total, 6),
            "any_direct_call_relation_upper_bound_at_1": round(any_direct_relation_upper / total, 6),
            "hit_at_5": round((strict_correct + hit_at_5) / total, 6),
            "mean_unique_positive_symbols": round(mean(positive_counts), 6),
            "mean_recall_at_5_theoretical_ceiling": round(mean(recall_upper_bounds), 6),
        },
        "strict_failure_relation_counts": dict(sorted(relation_counts.items())),
        "cases": cases,
    }
    write_json(args.output, report)
    print(report["metrics"])
    print(report["strict_failure_relation_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
