#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.common import file_sha256, read_json, utc_now, write_json
from bspforge.operation_ranking import (
    candidate_code_text,
    operation_feature_map,
    operation_query_text,
    operation_static_score,
)
from bspforge.semantic_resolver import SemanticResolver


def build_runtime_dataset(
    manifest: dict[str, Any], ir: dict[str, Any], ir_path: Path
) -> dict[str, Any]:
    sdk_id = ir["sdk"]["id"]
    manifest_items = {item["sdk_id"]: item for item in manifest["sdks"]}
    if sdk_id not in manifest_items:
        raise ValueError(f"SDK absent from manifest: {sdk_id}")
    sdk = manifest_items[sdk_id]
    functions = {item["id"]: item for item in ir["functions"]}
    resolver = SemanticResolver()
    groups = []
    for capability, specification in CAPABILITY_SCHEMA.items():
        pool = resolver.candidate_pool(ir, capability)
        for operation in specification["operations"]:
            operation_id = f"{capability}.{operation}"
            candidates = []
            for candidate in pool:
                function = functions[candidate["entity_id"]]
                features = operation_feature_map(
                    capability, operation, candidate, function
                )
                candidates.append(
                    {
                        "entity_id": candidate["entity_id"],
                        "symbol": candidate["symbol"],
                        "file": function["file"],
                        "line": function["line"],
                        "static_score": operation_static_score(features),
                        "features": features,
                        "candidate_text": candidate_code_text(function),
                    }
                )
            if not candidates:
                raise ValueError(f"no runtime candidates for {sdk_id}/{operation_id}")
            groups.append(
                {
                    "group_id": f"{sdk_id}::{operation_id}",
                    "sdk_id": sdk_id,
                    "vendor": sdk["vendor"],
                    "independence_group": sdk["independence_group"],
                    "role": "runtime-inference",
                    "capability": capability,
                    "operation": operation,
                    "operation_id": operation_id,
                    "query_text": operation_query_text(capability, operation),
                    "candidate_pool_size": len(pool),
                    "candidates": candidates,
                }
            )
    return {
        "schema_version": "runtime-operation-dataset-v1",
        "created_at": utc_now(),
        "contains_labels": False,
        "candidate_policy": {
            "name": "all-positive-capability-evidence",
            "description": (
                "Keep every IR function with positive capability-level static "
                "evidence; no truth symbol or relevance label is read."
            ),
            "truth_independent": True,
            "post_inference_pruning": True,
        },
        "source": {
            "sdk_id": sdk_id,
            "sdk_digest": ir["sdk"]["digest"],
            "ir": str(ir_path.resolve()),
            "ir_sha256": file_sha256(ir_path),
        },
        "summary": {
            "sdks": 1,
            "groups": len(groups),
            "candidate_rows": sum(len(item["candidates"]) for item in groups),
            "unique_entities": len(
                {
                    candidate["entity_id"]
                    for group in groups
                    for candidate in group["candidates"]
                }
            ),
        },
        "groups": groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 SDK IR 构造不读取真值的运行时操作候选数据集"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/operation-ranking/manifest.json"),
    )
    parser.add_argument("--ir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ir_path = args.ir
    ir = read_json(ir_path)
    if "sdk" not in ir and "path" in ir:
        ir_path = Path(ir["path"])
        ir = read_json(ir_path)
    dataset = build_runtime_dataset(read_json(args.manifest), ir, ir_path)
    write_json(args.output, dataset)
    print(dataset["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
