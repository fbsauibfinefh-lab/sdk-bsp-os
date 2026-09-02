#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, read_json, utc_now, write_json


LABEL_FIELDS = ("label", "label_confidence", "label_evidence", "label_source")
GROUP_FIELDS = ("truth_symbols", "role", "independence_group", "vendor")


def candidate_index(group: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {candidate["entity_id"]: candidate for candidate in group["candidates"]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将新版真值标签合并到既有、与标签无关的特征数据集"
    )
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    labels = read_json(args.labels)
    features = read_json(args.features)
    label_groups = {group["group_id"]: group for group in labels["groups"]}
    missing_groups = sorted(
        group["group_id"]
        for group in features["groups"]
        if group["group_id"] not in label_groups
    )
    if missing_groups:
        raise ValueError(f"标签数据缺少 {len(missing_groups)} 个查询组")

    updated_candidates = 0
    changed_candidates = 0
    entity_matches = 0
    symbol_fallbacks = 0
    for group in features["groups"]:
        label_group = label_groups[group["group_id"]]
        for field in GROUP_FIELDS:
            if field in label_group:
                group[field] = label_group[field]
        source_candidates = candidate_index(label_group)
        target_symbols = {candidate["symbol"] for candidate in group["candidates"]}
        source_symbols = {
            candidate["symbol"] for candidate in label_group["candidates"]
        }
        recoverable_truth = set(label_group.get("truth_symbols", [])) & source_symbols
        missing_truth = recoverable_truth - target_symbols
        if missing_truth:
            raise ValueError(
                f"{group['group_id']} 的旧特征数据缺少真值符号："
                + ", ".join(sorted(missing_truth))
            )
        source_by_symbol: dict[str, dict[str, Any]] = {}
        for source in label_group["candidates"]:
            current = source_by_symbol.get(source["symbol"])
            if current is None or int(source["label"]) > int(current["label"]):
                source_by_symbol[source["symbol"]] = source
        for candidate in group["candidates"]:
            source = source_candidates.get(candidate["entity_id"])
            if source is not None:
                entity_matches += 1
            else:
                source = source_by_symbol.get(candidate["symbol"])
                symbol_fallbacks += 1
            if source is None:
                source = {
                    "label": 0,
                    "label_confidence": 1.0,
                    "label_evidence": ["not-positive-in-selected-truth-set"],
                    "label_source": "source-audited",
                }
            old_label = candidate.get("label")
            for field in LABEL_FIELDS:
                candidate[field] = source[field]
            updated_candidates += 1
            changed_candidates += int(old_label != candidate["label"])

    features["truth_set_id"] = labels.get("truth_set_id")
    features["summary"] = labels.get("summary", features.get("summary", {}))
    features["relabeling"] = {
        "schema_version": "operation-dataset-relabel-v1",
        "created_at": utc_now(),
        "labels": str(args.labels),
        "labels_sha256": file_sha256(args.labels),
        "features": str(args.features),
        "features_sha256": file_sha256(args.features),
        "updated_candidates": updated_candidates,
        "changed_candidates": changed_candidates,
        "entity_matches": entity_matches,
        "symbol_or_negative_fallbacks": symbol_fallbacks,
        "feature_values_reused": True,
    }
    write_json(args.output, features)
    print(features["relabeling"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
