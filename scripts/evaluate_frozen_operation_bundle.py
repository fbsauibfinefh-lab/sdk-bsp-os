#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import file_sha256, read_json, utc_now, write_json


METRICS = ("precision_at_1", "recall_at_5", "map", "ndcg_at_10", "hit_at_5")


def truth_by_operation(
    truth: dict[str, Any], adjudication: dict[str, Any] | None
) -> dict[str, dict[str, int]]:
    result = {
        operation["operation_id"]: {
            item["canonical_symbol"]: int(item["grade"])
            for item in operation["items"]
            if int(item["grade"]) > 0
        }
        for operation in truth["operations"]
        if operation.get("group_status") == "complete"
    }
    for item in (adjudication or {}).get("items", []):
        if item["sdk_id"] != truth["sdk_id"]:
            continue
        result.setdefault(item["operation_id"], {})[item["symbol"]] = int(
            item["grade"]
        )
    return result


def operation_metrics(ranked: list[str], truth: dict[str, int]) -> dict[str, float]:
    relevant = set(truth)
    found = 0
    precision_sum = 0.0
    for rank, symbol in enumerate(ranked, start=1):
        if symbol in relevant:
            found += 1
            precision_sum += found / rank
    binary_dcg = sum(
        (1.0 if symbol in relevant else 0.0) / math.log2(rank + 1)
        for rank, symbol in enumerate(ranked[:10], start=1)
    )
    ideal_dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(len(relevant), 10) + 1)
    )
    return {
        "precision_at_1": float(bool(ranked) and ranked[0] in relevant),
        "recall_at_5": len(set(ranked[:5]) & relevant) / len(relevant),
        "map": precision_sum / len(relevant),
        "ndcg_at_10": binary_dcg / ideal_dcg if ideal_dcg else 0.0,
        "hit_at_5": float(bool(set(ranked[:5]) & relevant)),
    }


def unique_symbols(rows: list[dict[str, Any]]) -> list[str]:
    output = []
    seen = set()
    for row in rows:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        output.append(row["symbol"])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在冻结推理完成后使用独立真值评测运行时排序包"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--runtime-dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    bundle = read_json(args.bundle)
    truth = read_json(args.truth)
    adjudication = read_json(args.adjudication) if args.adjudication else None
    truth_groups = truth_by_operation(truth, adjudication)
    if bundle["sdk"]["id"] != truth["sdk_id"]:
        raise ValueError("bundle and truth SDK IDs differ")
    dataset_symbols: dict[str, set[str]] = {}
    if args.runtime_dataset:
        dataset = read_json(args.runtime_dataset)
        if dataset.get("contains_labels", True):
            raise ValueError("runtime dataset must declare contains_labels=false")
        dataset_symbols = {
            group["operation_id"]: {
                candidate["symbol"] for candidate in group["candidates"]
            }
            for group in dataset["groups"]
        }

    records = []
    for operation_id, operation in sorted(bundle["operations"].items()):
        relevant = truth_groups[operation_id]
        ranked = unique_symbols(operation["candidates"])
        metrics = operation_metrics(ranked, relevant)
        available = dataset_symbols.get(operation_id, set(ranked))
        records.append(
            {
                "operation_id": operation_id,
                "selected_symbol": ranked[0],
                "selected_grade": relevant.get(ranked[0], 0),
                "truth_symbols": sorted(relevant),
                "truth_symbols_in_label_free_pool": sorted(set(relevant) & available),
                "missing_truth_symbols_from_label_free_pool": sorted(
                    set(relevant) - available
                ),
                "metrics": {name: round(value, 6) for name, value in metrics.items()},
                "top5": ranked[:5],
            }
        )
    aggregate = {
        name: round(mean(item["metrics"][name] for item in records), 6)
        for name in METRICS
    }
    payload = {
        "schema_version": "frozen-operation-bundle-evaluation-v1",
        "created_at": utc_now(),
        "post_hoc_truth_only": True,
        "bundle": str(args.bundle),
        "bundle_sha256": file_sha256(args.bundle),
        "truth": str(args.truth),
        "truth_sha256": file_sha256(args.truth),
        "adjudication": str(args.adjudication) if args.adjudication else None,
        "aggregate": aggregate,
        "summary": {
            "operations": len(records),
            "truth_symbols": sum(len(item["truth_symbols"]) for item in records),
            "truth_symbols_missing_from_label_free_pool": sum(
                len(item["missing_truth_symbols_from_label_free_pool"])
                for item in records
            ),
        },
        "records": records,
    }
    write_json(args.output, payload)
    print({**payload["summary"], **aggregate})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
