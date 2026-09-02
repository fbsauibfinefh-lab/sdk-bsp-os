#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import time
from pathlib import Path

import numpy as np

from bspforge.code_effect_encoder import (
    MODEL_CODE_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    FrozenCodeEncoder,
    candidate_document,
    operation_query_text,
    text_sha256,
)
from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.hardware_effect_graph import SourceCorpus
from bspforge.ranking_dataset import latest_ir


def main() -> int:
    parser = argparse.ArgumentParser(description="缓存冻结Jina代码编码器的查询和SDK实体向量")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-metadata", type=Path, required=True)
    parser.add_argument("--output-vectors", type=Path, required=True)
    parser.add_argument("--cache-metadata", type=Path)
    parser.add_argument("--cache-vectors", type=Path)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    started = time.perf_counter()
    dataset = read_json(args.dataset)
    manifest = read_json(args.manifest)
    sdk_config = {item["sdk_id"]: item for item in manifest["sdks"]}
    groups_by_sdk = {}
    for group in dataset["groups"]:
        groups_by_sdk.setdefault(group["sdk_id"], []).append(group)

    documents = []
    document_keys = []
    document_hashes = []
    sdk_stats = []
    for sdk_id, groups in sorted(groups_by_sdk.items()):
        ir = read_json(latest_ir(args.ir_root, sdk_id))
        functions = {item["id"]: item for item in ir["functions"]}
        corpus = SourceCorpus(Path(sdk_config[sdk_id]["source_path"]))
        candidates = {}
        for group in groups:
            for candidate in group["candidates"]:
                candidates.setdefault(candidate["entity_id"], candidate)
        added = 0
        missing = 0
        for entity_id, candidate in sorted(candidates.items()):
            function = functions.get(entity_id)
            if function is None:
                missing += 1
                continue
            text = candidate_document(candidate, function, corpus)
            documents.append(text)
            document_keys.append(f"{sdk_id}::{entity_id}")
            document_hashes.append(text_sha256(text))
            added += 1
        sdk_stats.append({"sdk_id": sdk_id, "documents": added, "missing_ir_entities": missing})
        print(sdk_stats[-1], flush=True)

    operation_ids = sorted({item["operation_id"] for item in dataset["groups"]})
    queries = [operation_query_text(item) for item in operation_ids]
    del dataset, manifest, sdk_config, groups_by_sdk
    gc.collect()
    if bool(args.cache_metadata) != bool(args.cache_vectors):
        parser.error("--cache-metadata and --cache-vectors must be supplied together")
    cached_documents: dict[tuple[str, str], np.ndarray] = {}
    cached_queries: dict[tuple[str, str], np.ndarray] = {}
    if args.cache_metadata and args.cache_vectors:
        metadata = read_json(args.cache_metadata)
        with np.load(args.cache_vectors) as vectors:
            cached_document_vectors = vectors["documents"]
            cached_query_vectors = vectors["queries"]
        cached_documents = {
            (key, digest): cached_document_vectors[index]
            for index, (key, digest) in enumerate(zip(
                metadata["document_keys"], metadata["document_text_sha256"], strict=True
            ))
        }
        cached_queries = {
            (operation_id, digest): cached_query_vectors[index]
            for index, (operation_id, digest) in enumerate(zip(
                metadata["operation_ids"], metadata["query_text_sha256"], strict=True
            ))
        }
        del metadata

    document_rows: list[np.ndarray | None] = []
    missing_indices = []
    for index, key in enumerate(zip(document_keys, document_hashes, strict=True)):
        row = cached_documents.get(key)
        document_rows.append(row)
        if row is None:
            missing_indices.append(index)
        else:
            documents[index] = ""
    query_hashes = [text_sha256(item) for item in queries]
    query_rows: list[np.ndarray | None] = []
    missing_query_indices = []
    for index, key in enumerate(zip(operation_ids, query_hashes, strict=True)):
        row = cached_queries.get(key)
        query_rows.append(row)
        if row is None:
            missing_query_indices.append(index)
    cached_documents.clear()
    cached_queries.clear()
    gc.collect()
    print({
        "reused_documents": len(documents) - len(missing_indices),
        "new_documents": len(missing_indices),
        "reused_queries": len(queries) - len(missing_query_indices),
        "new_queries": len(missing_query_indices),
    }, flush=True)

    encoder = None
    if missing_indices or missing_query_indices:
        encoder = FrozenCodeEncoder(
            args.model,
            max_length=args.max_length,
            threads=args.threads,
        )
    if missing_query_indices:
        encoded = encoder.encode(
            [queries[index] for index in missing_query_indices], batch_size=args.batch_size
        )
        for index, row in zip(missing_query_indices, encoded, strict=True):
            query_rows[index] = row
    for start in range(0, len(missing_indices), 512):
        indices = missing_indices[start : start + 512]
        encoded = encoder.encode(
            [documents[index] for index in indices], batch_size=args.batch_size
        )
        for index, row in zip(indices, encoded, strict=True):
            document_rows[index] = row
        print({"encoded_new": min(start + 512, len(missing_indices)), "new_total": len(missing_indices)}, flush=True)
    document_vectors = np.stack(document_rows)
    query_vectors = np.stack(query_rows)
    dimension = int(document_vectors.shape[1])

    args.output_vectors.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output_vectors,
        documents=document_vectors.astype(np.float16),
        queries=query_vectors.astype(np.float16),
    )
    metadata = {
        "schema_version": "0.2",
        "created_at": utc_now(),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "code_revision": MODEL_CODE_REVISION,
            "local_path": str(args.model),
            "weights_sha256": file_sha256(args.model / "model.safetensors"),
            "dimension": dimension,
            "max_length": args.max_length,
            "pooling": "attention-mask mean pooling then L2 normalization",
            "frozen": True,
        },
        "serialization": {
            "query": "operation contract with capability, action, aliases, and API preference",
            "document": "symbol, signature, file, source role, calls, includes, register identifiers, normalized body",
            "normalization": "strip comments; replace strings, chars, hex, and numeric literals; truncate 2200 chars",
        },
        "dataset": str(args.dataset),
        "dataset_sha256": file_sha256(args.dataset),
        "document_keys": document_keys,
        "document_text_sha256": document_hashes,
        "operation_ids": operation_ids,
        "query_text_sha256": query_hashes,
        "incremental_cache": {
            "metadata": str(args.cache_metadata) if args.cache_metadata else None,
            "vectors": str(args.cache_vectors) if args.cache_vectors else None,
            "reused_documents": len(documents) - len(missing_indices),
            "encoded_documents": len(missing_indices),
            "reused_queries": len(queries) - len(missing_query_indices),
            "encoded_queries": len(missing_query_indices),
        },
        "sdk_stats": sdk_stats,
        "summary": {
            "documents": len(document_keys),
            "queries": len(operation_ids),
            "dimension": dimension,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "vectors_file": str(args.output_vectors),
            "vectors_sha256": file_sha256(args.output_vectors),
        },
    }
    write_json(args.output_metadata, metadata)
    print(metadata["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
