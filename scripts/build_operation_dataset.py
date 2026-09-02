#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.operation_dataset import build_operation_dataset, load_operation_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description="生成操作级语义排序数据集")
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--output", type=Path, default=Path("experiments/generated/operation-ranking-dataset.json"))
    parser.add_argument(
        "--truth-set",
        help="选择 manifest.training_policy.truth_sets 中的一套训练真值",
    )
    parser.add_argument(
        "--unretrievable-truth-policy",
        choices=("error", "skip-missing"),
        default="error",
        help=(
            "真值符号不在函数候选空间时的策略；skip-missing 会记录缺失符号，"
            "并跳过没有任何可达正例的查询组"
        ),
    )
    args = parser.parse_args()
    inputs = load_operation_inputs(
        args.manifest.resolve(), args.ir_root.resolve(), args.truth_set
    )
    dataset = build_operation_dataset(
        inputs,
        unretrievable_truth_policy=args.unretrievable_truth_policy,
    )
    dataset["truth_set_id"] = args.truth_set or read_json(args.manifest)[
        "training_policy"
    ].get("default_truth_set")
    write_json(args.output, dataset)
    print(dataset["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
