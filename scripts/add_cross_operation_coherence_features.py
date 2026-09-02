#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.cross_operation_coherence import (
    FEATURE_NAMES,
    enrich_dataset_with_cross_operation_coherence,
)


EFFECT_CONTRAST_FEATURES = {
    "xop-effect-margin", "xop-paired-effect-margin", "xop-action-selectivity",
}
CONTRAST_FEATURES = {
    name for name in FEATURE_NAMES
    if name in {
        "xop-effect-margin", "xop-paired-effect-margin", "xop-action-selectivity",
        "xop-contract-margin", "xop-lexical-margin", "xop-generic-fit-margin",
        "xop-consensus-margin", "xop-signal-agreement",
    }
}


def main() -> int:
    parser = argparse.ArgumentParser(description="添加跨操作对比和 API 家族一致性特征")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--feature-set",
        choices=("all", "effect-contrast", "contrast", "family"),
        default="all",
    )
    args = parser.parse_args()
    dataset = enrich_dataset_with_cross_operation_coherence(read_json(args.input))
    selected = set(FEATURE_NAMES)
    if args.feature_set == "contrast":
        selected = CONTRAST_FEATURES
    elif args.feature_set == "effect-contrast":
        selected = EFFECT_CONTRAST_FEATURES
    elif args.feature_set == "family":
        selected -= CONTRAST_FEATURES
    removed = set(FEATURE_NAMES) - selected
    for group in dataset["groups"]:
        for candidate in group["candidates"]:
            for name in removed:
                candidate["features"].pop(name, None)
    dataset["cross_operation_coherence"]["feature_set"] = args.feature_set
    dataset["cross_operation_coherence"]["features"] = sorted(selected)
    write_json(args.output, dataset)
    print(dataset["cross_operation_coherence"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
