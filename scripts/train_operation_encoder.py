#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import random
import shutil
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import numpy as np

from bspforge.common import read_json, utc_now, write_json
from bspforge.operation_encoder import IR_OPERATION_QUERY_FORMAT, operation_encoder_query


BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BASE_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def ranking_metrics(group: dict[str, Any], scores: list[float]) -> dict[str, float]:
    ranked = sorted(
        zip(group["candidates"], scores, strict=True),
        key=lambda item: (-item[1], item[0]["entity_id"]),
    )
    unique = []
    seen = set()
    for candidate, _ in ranked:
        if candidate["symbol"] in seen:
            continue
        seen.add(candidate["symbol"])
        unique.append(candidate)
    labels = [int(item["label"] > 0) for item in unique]
    relevant = sum(labels)
    ranks = [index for index, label in enumerate(labels, start=1) if label]
    found = 0
    precisions = []
    for index, label in enumerate(labels, start=1):
        if label:
            found += 1
            precisions.append(found / index)
    dcg = sum(label / math.log2(index + 2) for index, label in enumerate(labels[:10]))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(relevant, 10)))
    return {
        "precision_at_1": float(labels[0]) if labels else 0.0,
        "recall_at_5": sum(labels[:5]) / relevant if relevant else 0.0,
        "mrr": 1.0 / ranks[0] if ranks else 0.0,
        "map": sum(precisions) / relevant if relevant else 0.0,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
    }


def evaluate(model: Any, groups: list[dict[str, Any]], batch_size: int) -> dict[str, float]:
    queries = sorted({operation_encoder_query(item, IR_OPERATION_QUERY_FORMAT) for item in groups})
    documents = sorted({candidate["candidate_text"] for group in groups for candidate in group["candidates"]})
    query_vectors = model.encode(
        queries,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    document_vectors = model.encode(
        documents,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_index = {item: index for index, item in enumerate(queries)}
    document_index = {item: index for index, item in enumerate(documents)}
    records = []
    for group in groups:
        query = operation_encoder_query(group, IR_OPERATION_QUERY_FORMAT)
        query_vector = query_vectors[query_index[query]]
        scores = [
            float(np.dot(query_vector, document_vectors[document_index[item["candidate_text"]]]))
            for item in group["candidates"]
        ]
        records.append(ranking_metrics(group, scores))
    return {
        name: round(mean(item[name] for item in records), 6)
        for name in ("precision_at_1", "recall_at_5", "mrr", "map", "ndcg_at_10")
    }


def build_triplets(
    groups: list[dict[str, Any]],
    positives_per_group: int,
    negatives_per_positive: int,
) -> list[tuple[str, str, str]]:
    triplets = []
    for group in groups:
        query = operation_encoder_query(group, IR_OPERATION_QUERY_FORMAT)
        positives = sorted(
            (item for item in group["candidates"] if item["label"] >= 2),
            key=lambda item: (-item["static_score"], item["entity_id"]),
        )[:positives_per_group]
        negatives = sorted(
            (item for item in group["candidates"] if item["label"] == 0),
            key=lambda item: (
                -item["features"].get("opposite-action", 0.0),
                -item["features"].get("semantic-conflict", 0.0),
                -item["static_score"],
                item["entity_id"],
            ),
        )
        for positive in positives:
            for negative in negatives[:negatives_per_positive]:
                triplets.append((query, positive["candidate_text"], negative["candidate_text"]))
    return triplets


def freeze_for_cpu(model: Any, train_last_layers: int) -> tuple[int, int]:
    transformer = model[0].auto_model
    for parameter in transformer.parameters():
        parameter.requires_grad = False
    layers = transformer.encoder.layer
    for layer in layers[-train_last_layers:]:
        for parameter in layer.parameters():
            parameter.requires_grad = True
    trainable = sum(item.numel() for item in model.parameters() if item.requires_grad)
    total = sum(item.numel() for item in model.parameters())
    return trainable, total


def train_epoch(
    model: Any,
    triplets: list[tuple[str, str, str]],
    optimizer: Any,
    batch_size: int,
    margin: float,
    rng: random.Random,
) -> float:
    import torch
    import torch.nn.functional as functional

    rng.shuffle(triplets)
    losses = []
    model.train()
    for offset in range(0, len(triplets), batch_size):
        batch = triplets[offset:offset + batch_size]
        embeddings = []
        for column in range(3):
            features = model.tokenize([item[column] for item in batch])
            embeddings.append(functional.normalize(model(features)["sentence_embedding"], dim=1))
        positive_similarity = functional.cosine_similarity(embeddings[0], embeddings[1])
        negative_similarity = functional.cosine_similarity(embeddings[0], embeddings[2])
        loss = functional.relu(negative_similarity - positive_similarity + margin).mean()
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
    parser = argparse.ArgumentParser(description="在独立 SDK 分组上调优轻量 IR 操作编码器")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--encode-batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--margin", type=float, default=0.15)
    parser.add_argument("--train-last-layers", type=int, default=2)
    parser.add_argument("--positives-per-group", type=int, default=2)
    parser.add_argument("--negatives-per-positive", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()

    import torch
    from sentence_transformers import SentenceTransformer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    dataset = read_json(args.dataset)
    split = read_json(args.split)
    development_groups = set(split["development_groups"])
    external = [item for item in dataset["groups"] if item["role"] == "external-test"]
    if external and any(item.get("label_source") != "source-audited" for group in external for item in group["candidates"]):
        raise SystemExit("外部测试标签来源异常")
    development = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] in development_groups
    ]
    training = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] not in development_groups
    ]
    if {item["independence_group"] for item in training}.intersection(development_groups):
        raise SystemExit("训练和开发独立性分组发生泄漏")
    triplets = build_triplets(
        training,
        args.positives_per_group,
        args.negatives_per_positive,
    )
    model = SentenceTransformer(
        args.base_model,
        revision=args.revision,
        device=args.device,
    )
    model.max_seq_length = 128
    trainable, total = freeze_for_cpu(model, args.train_last_layers)
    optimizer = torch.optim.AdamW(
        [item for item in model.parameters() if item.requires_grad],
        lr=args.learning_rate,
        weight_decay=0.01,
    )
    baseline = evaluate(model, development, args.encode_batch_size)
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
        loss = train_epoch(model, triplets, optimizer, args.batch_size, args.margin, rng)
        metrics = evaluate(model, development, args.encode_batch_size)
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
            model.save_pretrained(str(temporary))
    if best_epoch == 0:
        if temporary.exists():
            shutil.rmtree(temporary)
        model = SentenceTransformer(
            args.base_model,
            revision=args.revision,
            device=args.device,
        )
        model.save_pretrained(str(temporary))
    if args.output_model.exists():
        shutil.rmtree(args.output_model)
    temporary.rename(args.output_model)
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "method": "IR-aware cosine triplet adaptation with grouped SDK development split",
        "base_model": args.base_model,
        "base_revision": args.revision,
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
            "margin": args.margin,
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
    }
    write_json(args.report, report)
    print({"best_epoch": best_epoch, "best_map": best_map, "model": str(args.output_model)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
