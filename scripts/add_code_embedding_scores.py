#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from bspforge.common import read_json, write_json
from bspforge.operation_encoder import IR_OPERATION_QUERY_FORMAT, operation_encoder_query


QUERY_PREFIX = "Represent this query for searching relevant code: "
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CODERANK_REVISION = "27ac5266d41729256c793e7744a20adf458657bd"


def main() -> int:
    parser = argparse.ArgumentParser(description="为操作级候选增加代码检索嵌入相似度")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="nomic-ai/CodeRankEmbed")
    parser.add_argument("--revision")
    parser.add_argument("--query-prefix")
    parser.add_argument(
        "--query-format",
        choices=("raw", IR_OPERATION_QUERY_FORMAT),
        default="raw",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=192)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--roles",
        nargs="+",
        choices=("train", "external-test"),
        default=("train", "external-test"),
        help="只为指定数据角色计算嵌入；CPU 快速评估可仅选 external-test",
    )
    args = parser.parse_args()
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise SystemExit("请安装 sentence-transformers 后再生成代码嵌入") from error

    dataset = read_json(args.dataset)
    selected_groups = [item for item in dataset["groups"] if item["role"] in args.roles]
    queries = sorted({operation_encoder_query(item, args.query_format) for item in selected_groups})
    documents = sorted({candidate["candidate_text"] for group in selected_groups for candidate in group["candidates"]})
    revision = args.revision or (CODERANK_REVISION if args.model == "nomic-ai/CodeRankEmbed" else None)
    query_prefix = (
        args.query_prefix
        if args.query_prefix is not None
        else QUERY_PREFIX if args.model == "nomic-ai/CodeRankEmbed"
        else BGE_QUERY_PREFIX if args.model == "BAAI/bge-small-en-v1.5"
        else ""
    )
    model = SentenceTransformer(
        args.model,
        revision=revision,
        trust_remote_code=True,
        device=args.device,
    )
    model.max_seq_length = args.max_seq_length
    query_vectors = model.encode(
        [query_prefix + item for item in queries],
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    document_vectors = model.encode(
        documents,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    query_index = {item: index for index, item in enumerate(queries)}
    document_index = {item: index for index, item in enumerate(documents)}
    for group in selected_groups:
        query = operation_encoder_query(group, args.query_format)
        query_vector = query_vectors[query_index[query]]
        for candidate in group["candidates"]:
            document_vector = document_vectors[document_index[candidate["candidate_text"]]]
            cosine = float(np.dot(query_vector, document_vector))
            candidate["features"]["code-embedding"] = round((cosine + 1.0) / 2.0, 6)
    dataset["embedding"] = {
        "model": args.model,
        "revision": revision or "upstream-default",
        "query_prefix": query_prefix,
        "query_format": args.query_format,
        "queries": len(queries),
        "unique_candidate_documents": len(documents),
        "normalized": True,
        "max_seq_length": args.max_seq_length,
        "roles": list(args.roles),
    }
    write_json(args.output, dataset)
    print(dataset["embedding"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
