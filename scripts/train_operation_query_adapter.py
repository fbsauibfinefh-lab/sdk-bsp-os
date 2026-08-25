#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import random
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import numpy as np

from bspforge.common import read_json, utc_now, write_json
from bspforge.operation_encoder import IR_OPERATION_QUERY_FORMAT, operation_encoder_query
from bspforge.semantic_adapter import QueryResidualAdapter
from train_operation_encoder import BASE_MODEL, BASE_REVISION, build_triplets, ranking_metrics


def encode_corpus(
    model: Any,
    groups: list[dict[str, Any]],
    batch_size: int,
    query_format: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import torch

    queries = sorted({operation_encoder_query(item, query_format) for item in groups})
    documents = sorted({candidate["candidate_text"] for group in groups for candidate in group["candidates"]})
    query_values = model.encode(
        queries,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_tensor=True,
    ).cpu()
    document_values = model.encode(
        documents,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_tensor=True,
    ).cpu()
    return (
        {text: tensor for text, tensor in zip(queries, query_values, strict=True)},
        {text: tensor for text, tensor in zip(documents, document_values, strict=True)},
    )


def evaluate_adapter(
    adapter: QueryResidualAdapter,
    groups: list[dict[str, Any]],
    query_vectors: dict[str, Any],
    document_vectors: dict[str, Any],
    device: str,
    query_format: str,
) -> dict[str, float]:
    import torch

    adapter.eval()
    records = []
    with torch.no_grad():
        for group in groups:
            query = operation_encoder_query(group, query_format)
            query_vector = adapter(query_vectors[query].to(device).unsqueeze(0))[0].cpu()
            scores = [
                float(torch.dot(query_vector, document_vectors[item["candidate_text"]]))
                for item in group["candidates"]
            ]
            records.append(ranking_metrics(group, scores))
    return {
        name: round(mean(item[name] for item in records), 6)
        for name in ("precision_at_1", "recall_at_5", "mrr", "map", "ndcg_at_10")
    }


def directory_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="训练冻结编码器上的 IR 查询低秩残差适配器")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-adapter", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--revision", default=BASE_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--query-format", choices=("raw", IR_OPERATION_QUERY_FORMAT), default="raw")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--eval-every", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--encode-batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=2e-3)
    parser.add_argument("--margin", type=float, default=0.12)
    parser.add_argument("--identity-weight", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional
    from sentence_transformers import SentenceTransformer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    dataset = read_json(args.dataset)
    split = read_json(args.split)
    development_ids = set(split["development_groups"])
    training = [
        group for group in dataset["groups"]
        if group["role"] == "train" and group["independence_group"] not in development_ids
    ]
    development = [
        group for group in dataset["groups"]
        if group["role"] == "train" and group["independence_group"] in development_ids
    ]
    external = [group for group in dataset["groups"] if group["role"] == "external-test"]
    triplets = build_triplets(training, positives_per_group=2, negatives_per_positive=2)
    model = SentenceTransformer(args.base_model, revision=args.revision, device=args.device)
    model.max_seq_length = 128
    for parameter in model.parameters():
        parameter.requires_grad = False
    query_vectors, document_vectors = encode_corpus(
        model,
        training + development,
        args.encode_batch_size,
        args.query_format,
    )
    dimension = model.get_sentence_embedding_dimension()
    adapter = QueryResidualAdapter(dimension, args.rank, args.device)
    optimizer = torch.optim.AdamW(adapter.parameters(), lr=args.learning_rate, weight_decay=0.01)
    baseline_adapter = QueryResidualAdapter(dimension, args.rank, args.device)
    baseline = evaluate_adapter(
        baseline_adapter,
        development,
        query_vectors,
        document_vectors,
        args.device,
        args.query_format,
    )
    indexed = [
        (
            query_vectors[query],
            document_vectors[positive],
            document_vectors[negative],
        )
        for query, positive, negative in triplets
    ]
    best_map = baseline["map"]
    best_epoch = 0
    best_state = None
    history = []
    started = perf_counter()
    rng = random.Random(args.seed)
    for epoch in range(1, args.epochs + 1):
        rng.shuffle(indexed)
        losses = []
        adapter.train()
        for offset in range(0, len(indexed), args.batch_size):
            batch = indexed[offset:offset + args.batch_size]
            base_query = torch.stack([item[0] for item in batch]).to(args.device)
            positive = torch.stack([item[1] for item in batch]).to(args.device)
            negative = torch.stack([item[2] for item in batch]).to(args.device)
            adapted = adapter(base_query)
            positive_score = functional.cosine_similarity(adapted, positive)
            negative_score = functional.cosine_similarity(adapted, negative)
            ranking_loss = functional.relu(negative_score - positive_score + args.margin).mean()
            identity_loss = (1.0 - functional.cosine_similarity(adapted, base_query)).mean()
            loss = ranking_loss + args.identity_weight * identity_loss
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(list(adapter.parameters()), 1.0)
            optimizer.step()
            losses.append(float(loss.detach()))
        if epoch % args.eval_every != 0 and epoch != args.epochs:
            continue
        metrics = evaluate_adapter(
            adapter,
            development,
            query_vectors,
            document_vectors,
            args.device,
            args.query_format,
        )
        record = {"epoch": epoch, "loss": round(mean(losses), 6), "development": metrics}
        history.append(record)
        print(record, flush=True)
        if metrics["map"] > best_map:
            best_map = metrics["map"]
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in adapter.module.state_dict().items()}
    if best_state is None:
        best_state = baseline_adapter.module.state_dict()
    args.output_adapter.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "method": "frozen MiniLM IR query low-rank residual adapter",
        "base_model": args.base_model,
        "base_revision": args.revision,
        "query_format": args.query_format,
        "dimension": dimension,
        "rank": args.rank,
        "state_dict": best_state,
    }
    torch.save(payload, args.output_adapter)
    trainable = sum(value.numel() for value in best_state.values())
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "method": payload["method"],
        "base_model": args.base_model,
        "base_revision": args.revision,
        "query_format": args.query_format,
        "dataset_summary": dataset["summary"],
        "split": {
            "training_independence_groups": sorted({item["independence_group"] for item in training}),
            "development_independence_groups": sorted(development_ids),
            "external_test_sdks_excluded": sorted({item["sdk_id"] for item in external}),
            "training_query_groups": len(training),
            "development_query_groups": len(development),
        },
        "training": {
            "triplets": len(triplets),
            "epochs_requested": args.epochs,
            "best_epoch": best_epoch,
            "rank": args.rank,
            "trainable_parameters": trainable,
            "base_parameters": sum(item.numel() for item in model.parameters()),
            "learning_rate": args.learning_rate,
            "margin": args.margin,
            "identity_weight": args.identity_weight,
            "seconds": round(perf_counter() - started, 3),
            "seed": args.seed,
        },
        "development_baseline": baseline,
        "best_development_map": best_map,
        "history": history,
        "adapter_sha256": directory_digest(args.output_adapter),
    }
    write_json(args.report, report)
    print({"best_epoch": best_epoch, "best_map": best_map, "adapter": str(args.output_adapter)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
