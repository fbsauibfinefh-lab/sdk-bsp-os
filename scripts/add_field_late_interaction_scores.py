#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.field_late_interaction import FieldLateInteractionScorer
from train_operation_encoder import BASE_MODEL, BASE_REVISION


def main() -> int:
    parser = argparse.ArgumentParser(description="为操作候选增加字段感知 token 迟交互分数")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=BASE_MODEL)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument(
        "--roles",
        nargs="+",
        choices=("train", "external-test"),
        default=("train", "external-test"),
    )
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    groups = [item for item in dataset["groups"] if item["role"] in args.roles]
    scorer = FieldLateInteractionScorer(
        args.model,
        revision=args.revision,
        device=args.device,
        batch_size=args.batch_size,
    )
    metadata = scorer.score_groups(groups)
    metadata.update({
        "model": args.model,
        "revision": args.revision,
        "roles": list(args.roles),
        "method": "field-aware-token-maxsim-v1",
    })
    dataset["field_late_interaction"] = metadata
    write_json(args.output, dataset)
    print(metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
