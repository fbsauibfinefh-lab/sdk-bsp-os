#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.code_effect_encoder import CodeEmbeddingCache
from bspforge.common import read_json, write_json
from bspforge.joint_shortlist import shortlist_recall


def main() -> int:
    parser = argparse.ArgumentParser(description="分析Top-K联合编码候选并集的正例覆盖")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    cache = CodeEmbeddingCache(args.base_metadata, args.base_vectors)
    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [group for group in dataset["groups"] if group["role"] == "external-test"]
    report = {
        "schema_version": "0.3-shortlist",
        "selection": "union of label-free full-code zero-shot, q4 structured, and hardware graph rankings",
        "training": [
            shortlist_recall(training, cache, per_channel=value)
            for value in (8, 10, 15)
        ],
        "external_diagnostic": [
            shortlist_recall(external, cache, per_channel=value)
            for value in (8, 10, 15)
        ],
    }
    write_json(args.output, report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
