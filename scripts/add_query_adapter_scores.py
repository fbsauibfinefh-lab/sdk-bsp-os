#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from bspforge.common import read_json, write_json
from bspforge.operation_encoder import operation_encoder_query
from bspforge.semantic_adapter import QueryResidualAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="使用冻结编码器与查询适配器生成 IR 语义分数")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--roles", nargs="+", choices=("train", "external-test"), default=("external-test",))
    args = parser.parse_args()

    import torch
    from sentence_transformers import SentenceTransformer

    payload = torch.load(args.adapter, map_location="cpu", weights_only=True)
    model = SentenceTransformer(
        payload["base_model"],
        revision=payload["base_revision"],
        device=args.device,
    )
    model.max_seq_length = 128
    adapter = QueryResidualAdapter(payload["dimension"], payload["rank"], args.device)
    adapter.module.load_state_dict(payload["state_dict"])
    adapter.eval()
    dataset = read_json(args.dataset)
    groups = [item for item in dataset["groups"] if item["role"] in args.roles]
    queries = sorted({operation_encoder_query(item, payload["query_format"]) for item in groups})
    documents = sorted({candidate["candidate_text"] for group in groups for candidate in group["candidates"]})
    base_queries = model.encode(
        queries,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_tensor=True,
    ).to(args.device)
    with torch.no_grad():
        adapted_queries = adapter(base_queries).cpu().numpy()
    document_values = model.encode(
        documents,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    query_index = {item: index for index, item in enumerate(queries)}
    document_index = {item: index for index, item in enumerate(documents)}
    for group in groups:
        query = operation_encoder_query(group, payload["query_format"])
        query_vector = adapted_queries[query_index[query]]
        for candidate in group["candidates"]:
            cosine = float(np.dot(query_vector, document_values[document_index[candidate["candidate_text"]]]))
            candidate["features"]["code-embedding"] = round((cosine + 1.0) / 2.0, 6)
    dataset["embedding"] = {
        "model": payload["base_model"],
        "revision": payload["base_revision"],
        "adapter": str(args.adapter),
        "query_format": payload["query_format"],
        "queries": len(queries),
        "unique_candidate_documents": len(documents),
        "normalized": True,
        "max_seq_length": 128,
        "roles": list(args.roles),
    }
    write_json(args.output, dataset)
    print(dataset["embedding"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
