#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from evaluate_operation_ranker import ranking_diagnostics, ranking_metrics


def score(group: dict[str, Any], static_weight: float) -> list[float]:
    return [
        static_weight * float(item["static_score"])
        + (1.0 - static_weight)
        * float(item["features"].get("field-late-interaction", 0.0))
        for item in group["candidates"]
    ]


def aggregate(groups: list[dict[str, Any]], static_weight: float) -> dict[str, float]:
    records = [ranking_metrics(item["candidates"], score(item, static_weight)) for item in groups]
    return {
        key: round(mean(item[key] for item in records), 6)
        for key in records[0]
    } if records else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="按 SDK 和操作分析语义排序错误")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--static-weight", type=float, default=0.5)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    groups = [item for item in dataset["groups"] if item["role"] == "external-test"]
    by_sdk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_capability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors = []
    for group in groups:
        values = score(group, args.static_weight)
        diagnostics = ranking_diagnostics(group["candidates"], values)
        by_sdk[group["sdk_id"]].append(group)
        by_capability[group["capability"]].append(group)
        if diagnostics["top_candidates"] and not diagnostics["top_candidates"][0]["label"]:
            errors.append({
                "sdk_id": group["sdk_id"],
                "operation_id": group["operation_id"],
                "first_positive_rank": diagnostics["first_positive_rank"],
                "top_candidates": diagnostics["top_candidates"],
            })
    report = {
        "schema_version": "1.0",
        "static_weight": args.static_weight,
        "overall": aggregate(groups, args.static_weight),
        "by_sdk": {
            name: aggregate(items, args.static_weight) for name, items in sorted(by_sdk.items())
        },
        "by_capability": {
            name: aggregate(items, args.static_weight)
            for name, items in sorted(by_capability.items())
        },
        "top1_errors": errors,
    }
    write_json(args.output, report)
    print({"overall": report["overall"], "top1_errors": len(errors)})
    for item in errors:
        top = item["top_candidates"][0]
        print(
            item["sdk_id"], item["operation_id"],
            f"truth-rank={item['first_positive_rank']}", f"top={top['symbol']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
