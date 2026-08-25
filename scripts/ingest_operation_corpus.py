#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.ir_store import IRStore
from bspforge.ranking_dataset import latest_ir
from bspforge.sdk_ingestor import SDKIngestor


def main() -> int:
    parser = argparse.ArgumentParser(description="构建操作级排序所需的 SDK IR")
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--store", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--report", type=Path, default=Path("experiments/generated/operation-corpus-report.json"))
    parser.add_argument("--frontend", choices=["hybrid", "regex"], default="hybrid")
    parser.add_argument("--role", action="append", choices=["train", "external-test"])
    parser.add_argument("--reuse-from", type=Path, default=Path("workspace/ir"))
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    store = IRStore(args.store)
    roles = set(args.role or ["train", "external-test"])
    records = []
    for item in manifest["sdks"]:
        if item["role"] not in roles:
            continue
        started = time.monotonic()
        reused = False
        try:
            existing = latest_ir(args.store, item["sdk_id"])
        except FileNotFoundError:
            try:
                existing = latest_ir(args.reuse_from, item["sdk_id"])
            except FileNotFoundError:
                existing = None
        if existing is not None:
            ir = read_json(existing)
            reused = True
        else:
            ir = SDKIngestor(frontend_mode=args.frontend).ingest(
                Path(item["source_path"]), item["sdk_id"]
            )
        destination = store.put(ir)
        record = {
            "sdk_id": item["sdk_id"],
            "role": item["role"],
            "independence_group": item["independence_group"],
            "sdk_digest": ir["sdk"]["digest"],
            "ir_path": str(destination.resolve()),
            "source_path": item["source_path"],
            "reused_existing_ir": reused,
            "stats": ir["stats"],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        records.append(record)
        print(f"{item['sdk_id']}: {ir['stats']['functions']} functions, reused={reused}", flush=True)
    write_json(args.report, {
        "schema_version": "1.0",
        "frontend": args.frontend,
        "records": records,
        "summary": {
            "sdks": len(records),
            "independence_groups": len({item["independence_group"] for item in records if item["role"] == "train"}),
            "files": sum(item["stats"]["files"] for item in records),
            "functions": sum(item["stats"]["functions"] for item in records),
            "duration_seconds": round(sum(item["duration_seconds"] for item in records), 3),
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
