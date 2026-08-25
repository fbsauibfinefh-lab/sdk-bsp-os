#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import random
import shutil
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import numpy as np

from bspforge.common import read_json, utc_now, write_json
from bspforge.operation_encoder import IR_OPERATION_QUERY_FORMAT, operation_encoder_query
from train_operation_encoder import build_triplets, ranking_metrics


BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
BASE_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


def pair_scores(
    model: Any,
    tokenizer: Any,
    queries: list[str],
    documents: list[str],
    batch_size: int,
    device: str,
) -> list[float]:
    import torch

    output = []
    model.eval()
    with torch.no_grad():
        for offset in range(0, len(queries), batch_size):
            encoded = tokenizer(
                queries[offset:offset + batch_size],
                documents[offset:offset + batch_size],
                padding=True,
                truncation=True,
                max_length=192,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits.reshape(-1)
            output.extend(float(item) for item in logits.cpu())
    return output


def evaluate(
    model: Any,
    tokenizer: Any,
    groups: list[dict[str, Any]],
    batch_size: int,
    device: str,
) -> dict[str, float]:
    records = []
    for group in groups:
        query = operation_encoder_query(group, IR_OPERATION_QUERY_FORMAT)
        documents = [item["candidate_text"] for item in group["candidates"]]
        scores = pair_scores(
            model,
            tokenizer,
            [query] * len(documents),
            documents,
            batch_size,
            device,
        )
        records.append(ranking_metrics(group, scores))
    return {
        name: round(mean(item[name] for item in records), 6)
        for name in ("precision_at_1", "recall_at_5", "mrr", "map", "ndcg_at_10")
    }


def freeze_for_cpu(model: Any, train_last_layers: int) -> tuple[int, int]:
    for parameter in model.base_model.parameters():
        parameter.requires_grad = False
    layers = model.base_model.encoder.layer
    for layer in layers[-train_last_layers:]:
        for parameter in layer.parameters():
            parameter.requires_grad = True
    for parameter in model.classifier.parameters():
        parameter.requires_grad = True
    trainable = sum(item.numel() for item in model.parameters() if item.requires_grad)
    total = sum(item.numel() for item in model.parameters())
    return trainable, total


def train_epoch(
    model: Any,
    tokenizer: Any,
    triplets: list[tuple[str, str, str]],
    optimizer: Any,
    batch_size: int,
    device: str,
    rng: random.Random,
) -> float:
    import torch
    import torch.nn.functional as functional

    rng.shuffle(triplets)
    losses = []
    model.train()
    for offset in range(0, len(triplets), batch_size):
        batch = triplets[offset:offset + batch_size]
        queries = [item[0] for item in batch]
        documents = [item[1] for item in batch] + [item[2] for item in batch]
        encoded = tokenizer(
            queries + queries,
            documents,
            padding=True,
            truncation=True,
            max_length=192,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        logits = model(**encoded).logits.reshape(-1)
        positive, negative = logits[:len(batch)], logits[len(batch):]
        loss = functional.softplus(negative - positive).mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            [item for item in model.parameters() if item.requires_grad], 1.0
        )
        optimizer.step()
        losses.append(float(loss.detach()))
    return mean(losses)


def directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="调优轻量 IR 操作交叉编码重排器")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--eval-batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--train-last-layers", type=int, default=2)
    parser.add_argument("--positives-per-group", type=int, default=2)
    parser.add_argument("--negatives-per-positive", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    dataset = read_json(args.dataset)
    split = read_json(args.split)
    development_groups = set(split["development_groups"])
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    development = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] in development_groups
    ]
    training = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] not in development_groups
    ]
    triplets = build_triplets(
        training,
        args.positives_per_group,
        args.negatives_per_positive,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, revision=args.revision)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        revision=args.revision,
    ).to(args.device)
    trainable, total = freeze_for_cpu(model, args.train_last_layers)
    optimizer = torch.optim.AdamW(
        [item for item in model.parameters() if item.requires_grad],
        lr=args.learning_rate,
        weight_decay=0.01,
    )
    baseline = evaluate(model, tokenizer, development, args.eval_batch_size, args.device)
    history = []
    best_map = baseline["map"]
    best_epoch = 0
    started = perf_counter()
    temporary = args.output_model.with_name(args.output_model.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    rng = random.Random(args.seed)
    for epoch in range(1, args.epochs + 1):
        epoch_started = perf_counter()
        loss = train_epoch(
            model,
            tokenizer,
            triplets,
            optimizer,
            args.batch_size,
            args.device,
            rng,
        )
        metrics = evaluate(model, tokenizer, development, args.eval_batch_size, args.device)
        record = {
            "epoch": epoch,
            "loss": round(loss, 6),
            "development": metrics,
            "seconds": round(perf_counter() - epoch_started, 3),
        }
        history.append(record)
        print(record, flush=True)
        if metrics["map"] > best_map:
            best_map = metrics["map"]
            best_epoch = epoch
            if temporary.exists():
                shutil.rmtree(temporary)
            model.save_pretrained(temporary)
            tokenizer.save_pretrained(temporary)
    if best_epoch == 0:
        model.save_pretrained(temporary)
        tokenizer.save_pretrained(temporary)
    if args.output_model.exists():
        shutil.rmtree(args.output_model)
    temporary.rename(args.output_model)
    write_json(args.report, {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "method": "IR-aware pairwise RankNet adaptation of a compact cross-encoder",
        "base_model": args.base_model,
        "base_revision": args.revision or "upstream-default",
        "query_format": IR_OPERATION_QUERY_FORMAT,
        "dataset_summary": dataset["summary"],
        "split": {
            "training_independence_groups": sorted({item["independence_group"] for item in training}),
            "development_independence_groups": sorted(development_groups),
            "external_test_sdks_excluded": sorted({item["sdk_id"] for item in external}),
            "training_query_groups": len(training),
            "development_query_groups": len(development),
        },
        "training": {
            "triplets": len(triplets),
            "epochs_requested": args.epochs,
            "best_epoch": best_epoch,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "train_last_layers": args.train_last_layers,
            "trainable_parameters": trainable,
            "total_parameters": total,
            "trainable_ratio": round(trainable / total, 6),
            "seed": args.seed,
            "seconds": round(perf_counter() - started, 3),
        },
        "development_baseline": baseline,
        "history": history,
        "best_development_map": best_map,
        "model_sha256": directory_digest(args.output_model),
    })
    print({"best_epoch": best_epoch, "best_map": best_map, "model": str(args.output_model)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
