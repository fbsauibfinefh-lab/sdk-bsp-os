#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from bspforge.common import read_json, write_json
from bspforge.ir_store import IRStore
from bspforge.sdk_ingestor import SDKIngestor


def main() -> int:
    parser = argparse.ArgumentParser(description="为语义排序实验构建全部 SDK IR")
    parser.add_argument("--manifest", type=Path, default=Path("experiments/semantic-ground-truth/manifest.json"))
    parser.add_argument("--store", type=Path, default=Path("workspace/ir"))
    parser.add_argument("--report", type=Path, default=Path("experiments/generated/corpus-ingest-report.json"))
    parser.add_argument("--frontend", choices=["hybrid", "regex"], default="hybrid")
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    store = IRStore(args.store)
    records = []
    for item in manifest["sdks"]:
        source = Path(item["source_path"])
        started = time.monotonic()
        ir = SDKIngestor(frontend_mode=args.frontend).ingest(source, item["sdk_id"])
        destination = store.put(ir)
        record = {
            "sdk_id": item["sdk_id"],
            "sdk_digest": ir["sdk"]["digest"],
            "source_path": str(source.resolve()),
            "ir_path": str(destination.resolve()),
            "frontend": ir["frontend"]["selected_counts"],
            "stats": ir["stats"],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        records.append(record)
        print(
            f"{item['sdk_id']}: {record['stats']['functions']} functions, "
            f"{record['duration_seconds']} s",
            flush=True,
        )
    write_json(args.report, {
        "schema_version": "1.0",
        "frontend": args.frontend,
        "sdks": records,
        "summary": {
            "sdk_count": len(records),
            "files": sum(item["stats"]["files"] for item in records),
            "functions": sum(item["stats"]["functions"] for item in records),
            "duration_seconds": round(sum(item["duration_seconds"] for item in records), 3),
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
