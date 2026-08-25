#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.operation_encoder import IR_OPERATION_QUERY_FORMAT, operation_encoder_query
from train_operation_reranker import pair_scores


BASE_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


def main() -> int:
    parser = argparse.ArgumentParser(description="为操作候选增加轻量交叉编码器分数")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--roles",
        nargs="+",
        choices=("train", "external-test"),
        default=("external-test",),
    )
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    dataset = read_json(args.dataset)
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        revision=args.revision,
    ).to(args.device)
    selected_groups = [item for item in dataset["groups"] if item["role"] in args.roles]
    pairs = 0
    with torch.no_grad():
        for index, group in enumerate(selected_groups, start=1):
            query = operation_encoder_query(group, IR_OPERATION_QUERY_FORMAT)
            documents = [item["candidate_text"] for item in group["candidates"]]
            scores = pair_scores(
                model,
                tokenizer,
                [query] * len(documents),
                documents,
                args.batch_size,
                args.device,
            )
            probabilities = torch.sigmoid(torch.tensor(scores)).tolist()
            for candidate, score in zip(group["candidates"], probabilities, strict=True):
                candidate["features"]["cross-reranker"] = round(float(score), 6)
            pairs += len(documents)
            if index % 10 == 0:
                print({"groups": index, "pairs": pairs}, flush=True)
    dataset["cross_reranker"] = {
        "model": args.model,
        "revision": args.revision or "upstream-default",
        "query_format": IR_OPERATION_QUERY_FORMAT,
        "roles": list(args.roles),
        "pairs": pairs,
        "max_length": 192,
    }
    write_json(args.output, dataset)
    print(dataset["cross_reranker"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
