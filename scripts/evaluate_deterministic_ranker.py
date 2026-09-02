#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.ranking_diagnostics import deterministic_ranking_evidence
from bspforge.structured_retrieval import complete_structured_scores
from evaluate_operation_ranker import METRICS, ranking_metrics


def _aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {
        metric: round(mean(item["metrics"][metric] for item in records), 6)
        for metric in METRICS
    }


def _breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        groups[item[key]].append(item)
    return {name: _aggregate(items) for name, items in sorted(groups.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="评估无需训练的确定性语义排序与低分诊断")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--role",
        default="all",
        help="评测角色；默认 all，external-test 仅用于板卡诊断子集",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    groups = (
        list(dataset["groups"])
        if args.role == "all"
        else [item for item in dataset["groups"] if item["role"] == args.role]
    )
    records = []
    for group in groups:
        scores, diagnostics = complete_structured_scores(group)
        metrics = ranking_metrics(group["candidates"], scores)
        selected_index = min(
            range(len(scores)),
            key=lambda index: (
                -scores[index], group["candidates"][index]["entity_id"]
            ),
        )
        selected = group["candidates"][selected_index]
        evidence = deterministic_ranking_evidence(group, scores, diagnostics)
        records.append({
            "group_id": group["group_id"],
            "sdk_id": group["sdk_id"],
            "capability": group["capability"],
            "operation_id": group["operation_id"],
            "selected_symbol": selected["symbol"],
            "selected_label": selected["label"],
            "metrics": metrics,
            "ranking_evidence": evidence,
            "diagnostics": diagnostics,
        })

    low_score = [item for item in records if item["ranking_evidence"]["low_score"]]
    reason_counts = Counter(
        reason
        for item in low_score
        for reason in item["ranking_evidence"]["low_score_reasons"]
    )
    score_diagnostics = {
        "low_score_groups": len(low_score),
        "total_groups": len(records),
        "reason_counts": dict(sorted(reason_counts.items())),
        "group_ids": [item["group_id"] for item in low_score],
    }
    report = {
        "schema_version": "1.2",
        "method": "training-free generic-operation contract ranking with low-score diagnostics",
        "scope": "no SDK supervised training or learned field gate",
        "role": args.role,
        "groups": len(records),
        "sdks": len({item["sdk_id"] for item in records}),
        "groups_by_role": dict(sorted(Counter(
            group["role"] for group in groups
        ).items())),
        "metrics": _aggregate(records),
        "score_diagnostics": score_diagnostics,
        "by_sdk": _breakdown(records, "sdk_id"),
        "by_capability": _breakdown(records, "capability"),
        "records": records,
    }
    write_json(args.output, report)
    print({"metrics": report["metrics"], "score_diagnostics": score_diagnostics})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
