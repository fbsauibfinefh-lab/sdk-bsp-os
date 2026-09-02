#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import write_json
from bspforge.ranking_dataset import (
    audit_ground_truth,
    build_ranking_dataset,
    load_experiment_inputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="审计真值并构建跨 SDK 语义排序数据集")
    parser.add_argument("--manifest", type=Path, default=Path("experiments/semantic-ground-truth/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/ir"))
    parser.add_argument("--dataset", type=Path, default=Path("experiments/generated/semantic-ranking-dataset.json"))
    parser.add_argument("--audit", type=Path, default=Path("experiments/generated/ground-truth-audit.json"))
    parser.add_argument("--hard-negatives", type=int, default=80)
    parser.add_argument("--random-negatives", type=int, default=40)
    parser.add_argument("--positive-instances", type=int, default=3)
    args = parser.parse_args()

    inputs = load_experiment_inputs(args.manifest.resolve(), args.ir_root.resolve())
    audit = audit_ground_truth(inputs)
    write_json(args.audit, audit)
    if not audit["summary"]["passed"]:
        raise SystemExit(f"真值审计失败，详见 {args.audit}")
    dataset = build_ranking_dataset(
        inputs,
        hard_negatives=args.hard_negatives,
        random_negatives=args.random_negatives,
        positive_instances=args.positive_instances,
    )
    write_json(args.dataset, dataset)
    print(f"audit: {args.audit}")
    print(f"dataset: {args.dataset}")
    print(dataset["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
