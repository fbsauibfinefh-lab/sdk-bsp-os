#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.cross_operation_coherence import FEATURE_NAMES
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_channel_ablations import (
    all_names,
    evaluate,
    train_model,
)
from evaluate_multiview_lambdamart import numeric_feature_names


CONTRAST_FEATURES = {
    name for name in FEATURE_NAMES
    if name in {
        "xop-effect-margin", "xop-paired-effect-margin", "xop-action-selectivity",
        "xop-contract-margin", "xop-lexical-margin", "xop-generic-fit-margin",
        "xop-consensus-margin", "xop-signal-agreement",
    }
}
FAMILY_FEATURES = set(FEATURE_NAMES) - CONTRAST_FEATURES


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="跨操作对比和 API 家族一致性消融")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--v03-results", type=Path, required=True)
    parser.add_argument("--v04-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260907)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    groups = [item for item in dataset["groups"] if item["role"] == "train"]
    numeric_names = numeric_feature_names(groups)
    names = all_names(numeric_names)
    base = {name for name in names if not name.startswith("xop-")}
    feature_sets = {
        "v0.3": base,
        "v0.3-plus-contrast": base | CONTRAST_FEATURES,
        "v0.3-plus-family": base | FAMILY_FEATURES,
        "v0.4-all": set(names),
    }
    masks = {
        name: [index for index, feature in enumerate(names) if feature in selected]
        for name, selected in feature_sets.items()
    }
    records: dict[str, list[dict]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(fold_assignments(groups, args.folds), start=1):
        train = [item for item in groups if item["independence_group"] not in test_ids]
        test = [item for item in groups if item["independence_group"] in test_ids]
        metrics = {}
        for name, mask in masks.items():
            model = train_model(train, cache, numeric_names, mask, args.seed + fold * 10)
            fold_records = evaluate(model, test, cache, numeric_names, mask)
            records[name].extend(fold_records)
            metrics[name] = aggregate(fold_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "metrics": metrics,
        })
        print({"fold": fold, "metrics": metrics}, flush=True)

    comparisons = {
        f"{name}-vs-v0.3": paired_comparison(records[name], records["v0.3"], seed=args.seed)
        for name in feature_sets if name != "v0.3"
    }
    old_nested = read_json(args.v03_results)["cross_validation"]["records"][
        "multiview-lambdamart-nested"
    ]
    new_nested = read_json(args.v04_results)["cross_validation"]["records"][
        "multiview-lambdamart-nested"
    ]
    report = {
        "schema_version": "0.4-ablation",
        "method": "fixed small-bagged label-free cross-operation coherence ablation",
        "feature_sets": {name: sorted(values) for name, values in feature_sets.items()},
        "metrics": {name: aggregate(items) for name, items in records.items()},
        "paired_comparisons": comparisons,
        "strict_nested_v04_vs_v03": paired_comparison(new_nested, old_nested, seed=args.seed),
        "fold_reports": fold_reports,
        "records": records,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({"metrics": report["metrics"], "comparisons": comparisons})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
