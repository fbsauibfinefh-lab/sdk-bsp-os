#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.structured_retrieval import enrich_dataset_with_structured_retrieval


def main() -> int:
    parser = argparse.ArgumentParser(description="为操作数据增加 SDK 结构化多通道召回特征")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = enrich_dataset_with_structured_retrieval(read_json(args.dataset))
    write_json(args.output, dataset)
    print(dataset["structured_retrieval"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
