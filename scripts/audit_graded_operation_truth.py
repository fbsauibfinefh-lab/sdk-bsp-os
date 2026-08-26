#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="审计分级操作真值及数据隔离")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    labels: Counter[int] = Counter()
    sources: Counter[str] = Counter()
    evidence: Counter[str] = Counter()
    confidences: dict[int, list[float]] = defaultdict(list)
    group_coverage: Counter[str] = Counter()
    weak_positive_examples = []
    train_ids = set()
    external_ids = set()
    for group in dataset["groups"]:
        target_ids = external_ids if group["role"] == "external-test" else train_ids
        target_ids.add(group["independence_group"])
        group_labels = []
        for candidate in group["candidates"]:
            label = int(candidate["label"])
            labels[label] += 1
            group_labels.append(label)
            sources[candidate["label_source"]] += 1
            confidences[label].append(float(candidate.get("label_confidence", 0.0)))
            for item in candidate.get("label_evidence", []):
                evidence[item] += 1
            if 0 < label < 2 and len(weak_positive_examples) < 100:
                weak_positive_examples.append({
                    "group_id": group["group_id"],
                    "entity_id": candidate["entity_id"],
                    "symbol": candidate["symbol"],
                    "label": label,
                    "confidence": candidate.get("label_confidence"),
                    "evidence": candidate.get("label_evidence", []),
                })
        group_coverage[
            "strong-positive" if any(item >= 2 for item in group_labels)
            else "weak-positive-only" if any(item == 1 for item in group_labels)
            else "no-positive"
        ] += 1
    overlap = sorted(train_ids.intersection(external_ids))
    external_sources = {
        candidate["label_source"]
        for group in dataset["groups"] if group["role"] == "external-test"
        for candidate in group["candidates"]
    }
    checks = {
        "at_least_20_training_independence_groups": dataset["summary"]["training_independence_groups"] >= 20,
        "training_external_group_disjoint": not overlap,
        "external_labels_source_audited": external_sources == {"source-audited"},
        "graded_training_labels_present": all(labels[index] > 0 for index in (0, 1, 2, 3)),
    }
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "method": "evidence-backed four-grade truth audit",
        "dataset_summary": dataset["summary"],
        "label_counts": {str(key): value for key, value in sorted(labels.items())},
        "label_sources": dict(sorted(sources.items())),
        "mean_confidence_by_label": {
            str(key): round(mean(values), 6) for key, values in sorted(confidences.items())
        },
        "evidence_counts": dict(evidence.most_common()),
        "group_coverage": dict(group_coverage),
        "data_isolation": {
            "training_groups": sorted(train_ids),
            "external_groups": sorted(external_ids),
            "overlap": overlap,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "weak_positive_review_sample": weak_positive_examples,
        "publication_boundary": (
            "自动分级真值用于训练和开发；三块板卡真值来自源码审计。"
            "正式论文发布前仍需第二名标注者独立复核并报告一致性。"
        ),
    }
    write_json(args.output, report)
    print({"passed": report["passed"], "labels": report["label_counts"], "coverage": report["group_coverage"]})
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
