#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from bspforge.code_effect_encoder import (
    MODEL_CODE_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    CodeEmbeddingCache,
    FrozenCodeEncoder,
    operation_query_text,
    text_sha256,
)
from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.hardware_effect_graph import SourceCorpus
from bspforge.joint_shortlist import multichannel_shortlist, shortlist_recall
from bspforge.multiview_effect_encoder import (
    focused_candidate_document,
    joint_query_candidate_document,
)
from bspforge.ranking_dataset import latest_ir


def main() -> int:
    parser = argparse.ArgumentParser(description="缓存Top-K查询-候选联合编码向量")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-metadata", type=Path, required=True)
    parser.add_argument("--output-vectors", type=Path, required=True)
    parser.add_argument("--per-channel", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    started = time.perf_counter()
    dataset = read_json(args.dataset)
    manifest = read_json(args.manifest)
    sdk_config = {item["sdk_id"]: item for item in manifest["sdks"]}
    base_cache = CodeEmbeddingCache(args.base_metadata, args.base_vectors)
    groups_by_sdk: dict[str, list[dict]] = {}
    for group in dataset["groups"]:
        groups_by_sdk.setdefault(group["sdk_id"], []).append(group)

    keys = []
    texts = []
    hashes = []
    sdk_stats = []
    for sdk_id, groups in sorted(groups_by_sdk.items()):
        ir = read_json(latest_ir(args.ir_root, sdk_id))
        functions = {item["id"]: item for item in ir["functions"]}
        corpus = SourceCorpus(Path(sdk_config[sdk_id]["source_path"]))
        added = 0
        missing = 0
        for group in groups:
            query = operation_query_text(group["operation_id"])
            for index in multichannel_shortlist(
                group, base_cache, per_channel=args.per_channel
            ):
                candidate = group["candidates"][index]
                function = functions.get(candidate["entity_id"])
                if function is None:
                    missing += 1
                    continue
                focused = focused_candidate_document(group, candidate, function, corpus)
                text = joint_query_candidate_document(query, focused)
                keys.append(f"{group['group_id']}::{candidate['entity_id']}")
                texts.append(text)
                hashes.append(text_sha256(text))
                added += 1
        sdk_stats.append({"sdk_id": sdk_id, "joint_pairs": added, "missing": missing})
        print(sdk_stats[-1], flush=True)

    if len(set(keys)) != len(keys):
        raise ValueError("joint pair keys must be unique")
    encoder = FrozenCodeEncoder(
        args.model, max_length=args.max_length, threads=args.threads
    )
    blocks = []
    for start in range(0, len(texts), 512):
        blocks.append(encoder.encode(texts[start : start + 512], batch_size=args.batch_size))
        print({"encoded": min(start + 512, len(texts)), "total": len(texts)}, flush=True)
    vectors = np.concatenate(blocks, axis=0)
    args.output_vectors.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output_vectors, joint=vectors.astype(np.float16))

    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [group for group in dataset["groups"] if group["role"] == "external-test"]
    metadata = {
        "schema_version": "0.3-joint",
        "created_at": utc_now(),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "code_revision": MODEL_CODE_REVISION,
            "weights_sha256": file_sha256(args.model / "model.safetensors"),
            "dimension": encoder.dimension,
            "max_length": args.max_length,
            "frozen": True,
        },
        "dataset": str(args.dataset),
        "dataset_sha256": file_sha256(args.dataset),
        "shortlist": {
            "per_channel": args.per_channel,
            "selection": "union of full-code zero-shot, q4 structured, and hardware graph",
            "training_recall": shortlist_recall(
                training, base_cache, per_channel=args.per_channel
            ),
            "external_recall": shortlist_recall(
                external, base_cache, per_channel=args.per_channel
            ),
        },
        "joint_keys": keys,
        "joint_text_sha256": hashes,
        "sdk_stats": sdk_stats,
        "summary": {
            "joint_pairs": len(keys),
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
