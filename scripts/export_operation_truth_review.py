#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from bspforge.common import read_json, write_json


def compact(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": candidate["symbol"],
        "file": candidate["file"],
        "signature": next(
            (
                line.partition(":")[2].strip()
                for line in candidate["candidate_text"].splitlines()
                if line.startswith("signature:")
            ),
            "",
        ),
        "static_score": candidate["static_score"],
        "generated_grade": candidate["label"],
        "generated_evidence": candidate.get("label_evidence", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出开发 SDK 的人工真值复核候选")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    development = set(read_json(args.split)["development_groups"])
    output = []
    for group in dataset["groups"]:
        if group["role"] != "train" or group["independence_group"] not in development:
            continue
        ranked = sorted(
            group["candidates"],
            key=lambda item: (-float(item["static_score"]), item["entity_id"]),
        )
        generated_positive = [item for item in ranked if item["label"] >= 2]
        selected = []
        seen = set()
        for item in ranked[:args.top_k] + generated_positive:
            if item["symbol"] in seen:
                continue
            seen.add(item["symbol"])
            selected.append(compact(item))
        output.append({
            "sdk_id": group["sdk_id"],
            "operation_id": group["operation_id"],
            "candidates": selected,
        })
    write_json(args.output, {
        "schema_version": "1.0",
        "purpose": "人工源码审计工作表；不包含板卡外部测试 SDK",
        "development_independence_groups": sorted(development),
        "groups": output,
    })
    print({"groups": len(output), "sdks": sorted({item["sdk_id"] for item in output})})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
