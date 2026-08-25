#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import write_json
from bspforge.operation_dataset import build_operation_dataset, load_operation_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description="生成操作级语义排序数据集")
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--output", type=Path, default=Path("experiments/generated/operation-ranking-dataset.json"))
    args = parser.parse_args()
    inputs = load_operation_inputs(args.manifest.resolve(), args.ir_root.resolve())
    dataset = build_operation_dataset(inputs)
    write_json(args.output, dataset)
    print(dataset["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
