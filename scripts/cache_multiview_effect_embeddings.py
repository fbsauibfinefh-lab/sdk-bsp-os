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
    text_sha256,
)
from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.hardware_effect_graph import SourceCorpus
from bspforge.multiview_effect_encoder import focused_candidate_document
from bspforge.ranking_dataset import latest_ir


def main() -> int:
    parser = argparse.ArgumentParser(description="缓存操作条件化效果切片的多视图向量")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-metadata", type=Path, required=True)
    parser.add_argument("--output-vectors", type=Path, required=True)
    parser.add_argument("--cache-metadata", type=Path)
    parser.add_argument("--cache-vectors", type=Path)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=192)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    started = time.perf_counter()
    dataset = read_json(args.dataset)
    manifest = read_json(args.manifest)
    sdk_config = {item["sdk_id"]: item for item in manifest["sdks"]}
    groups_by_sdk: dict[str, list[dict]] = {}
    for group in dataset["groups"]:
        groups_by_sdk.setdefault(group["sdk_id"], []).append(group)

    focused_keys = []
    focused_texts = []
    focused_hashes = []
    sdk_stats = []
    for sdk_id, groups in sorted(groups_by_sdk.items()):
        ir = read_json(latest_ir(args.ir_root, sdk_id))
        functions = {item["id"]: item for item in ir["functions"]}
        corpus = SourceCorpus(Path(sdk_config[sdk_id]["source_path"]))
        added = 0
        missing = 0
        for group in groups:
            for candidate in group["candidates"]:
                function = functions.get(candidate["entity_id"])
                if function is None:
                    missing += 1
                    continue
                text = focused_candidate_document(group, candidate, function, corpus)
                focused_keys.append(f"{group['group_id']}::{candidate['entity_id']}")
                focused_texts.append(text)
                focused_hashes.append(text_sha256(text))
                added += 1
        sdk_stats.append({
            "sdk_id": sdk_id,
            "focused_documents": added,
            "missing_ir_entities": missing,
        })
        print(sdk_stats[-1], flush=True)

    if len(set(focused_keys)) != len(focused_keys):
        raise ValueError("focused query-candidate keys must be unique")
    del dataset, manifest, sdk_config, groups_by_sdk
    gc.collect()
    if bool(args.cache_metadata) != bool(args.cache_vectors):
        parser.error("--cache-metadata and --cache-vectors must be supplied together")
    cached: dict[tuple[str, str], np.ndarray] = {}
    if args.cache_metadata and args.cache_vectors:
        metadata = read_json(args.cache_metadata)
        with np.load(args.cache_vectors) as archive:
            vectors = archive["focused"]
        cached = {
            (key, digest): vectors[index]
            for index, (key, digest) in enumerate(zip(
                metadata["focused_keys"], metadata["focused_text_sha256"], strict=True
            ))
        }
        del metadata
    rows: list[np.ndarray | None] = []
    missing_indices = []
    for index, key in enumerate(zip(focused_keys, focused_hashes, strict=True)):
        row = cached.get(key)
        rows.append(row)
        if row is None:
            missing_indices.append(index)
        else:
            focused_texts[index] = ""
    cached.clear()
    gc.collect()
    print({
        "reused_documents": len(focused_texts) - len(missing_indices),
        "new_documents": len(missing_indices),
    }, flush=True)
    encoder = None
    if missing_indices:
        encoder = FrozenCodeEncoder(
            args.model, max_length=args.max_length, threads=args.threads
        )
    for start in range(0, len(missing_indices), 512):
        indices = missing_indices[start : start + 512]
        encoded = encoder.encode(
            [focused_texts[index] for index in indices], batch_size=args.batch_size
        )
        for index, row in zip(indices, encoded, strict=True):
            rows[index] = row
        print({"encoded_new": min(start + 512, len(missing_indices)), "new_total": len(missing_indices)}, flush=True)
    focused_vectors = np.stack(rows)
    dimension = int(focused_vectors.shape[1])

    args.output_vectors.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output_vectors, focused=focused_vectors.astype(np.float16)
    )
    metadata = {
        "schema_version": "0.3",
        "created_at": utc_now(),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "code_revision": MODEL_CODE_REVISION,
            "local_path": str(args.model),
            "weights_sha256": file_sha256(args.model / "model.safetensors"),
            "dimension": dimension,
            "max_length": args.max_length,
            "frozen": True,
        },
        "dataset": str(args.dataset),
        "dataset_sha256": file_sha256(args.dataset),
        "serialization": {
            "view": "symbol, signature, source role, effect path, register identifiers, operation-conditioned code slice",
            "slice": "top operation/capability/register statements plus one-statement context",
        },
        "focused_keys": focused_keys,
        "focused_text_sha256": focused_hashes,
        "incremental_cache": {
            "metadata": str(args.cache_metadata) if args.cache_metadata else None,
            "vectors": str(args.cache_vectors) if args.cache_vectors else None,
            "reused_documents": len(focused_texts) - len(missing_indices),
            "encoded_documents": len(missing_indices),
        },
        "sdk_stats": sdk_stats,
        "summary": {
            "focused_documents": len(focused_keys),
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
