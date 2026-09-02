#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.field_late_interaction import FieldLateInteractionScorer
from train_operation_encoder import BASE_MODEL, BASE_REVISION


FIELD_SCORE_KEYS = (
    "field-symbol-maxsim",
    "field-signature-maxsim",
    "field-calls-maxsim",
    "field-file-maxsim",
    "field-includes-maxsim",
    "field-late-interaction",
)


def score_key(group: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str]:
    return group["operation_id"], candidate["candidate_text"]


def load_cache(paths: list[Path]) -> dict[tuple[str, str], dict[str, float]]:
    cache: dict[tuple[str, str], dict[str, float]] = {}
    for path in paths:
        dataset = read_json(path)
        for group in dataset["groups"]:
            for candidate in group["candidates"]:
                features = candidate.get("features", {})
                if all(name in features for name in FIELD_SCORE_KEYS):
                    cache[score_key(group, candidate)] = {
                        name: float(features[name]) for name in FIELD_SCORE_KEYS
                    }
    return cache


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复用已有字段迟交互分数，并仅为新增候选执行 MiniLM 推理"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dataset", type=Path, action="append", default=[])
    parser.add_argument("--model", default=BASE_MODEL)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = load_cache(args.cache_dataset)
    reused = 0
    pending_groups = []
    for group in dataset["groups"]:
        pending = []
        for candidate in group["candidates"]:
            cached = cache.get(score_key(group, candidate))
            if cached is None:
                pending.append(candidate)
                continue
            candidate["features"].update(cached)
            reused += 1
        if pending:
            pending_groups.append({
                "group_id": group["group_id"],
                "capability": group["capability"],
                "operation": group["operation"],
                "operation_id": group["operation_id"],
                "candidates": pending,
            })

    inference = {
        "queries": 0,
        "candidate_documents": 0,
        "pairs": 0,
        "seconds": 0.0,
    }
    if pending_groups:
        scorer = FieldLateInteractionScorer(
            args.model,
            revision=args.revision,
            device=args.device,
            batch_size=args.batch_size,
        )
        inference = scorer.score_groups(pending_groups)

    dataset["field_late_interaction"] = {
        **inference,
        "model": args.model,
        "revision": args.revision,
        "method": "field-aware-token-maxsim-v1-with-auditable-cache",
        "cache_datasets": [str(path) for path in args.cache_dataset],
        "reused_pairs": reused,
        "newly_scored_pairs": sum(
            len(group["candidates"]) for group in pending_groups
        ),
    }
    write_json(args.output, dataset)
    print(dataset["field_late_interaction"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
