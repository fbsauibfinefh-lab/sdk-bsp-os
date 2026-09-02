#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from bspforge.common import read_json, utc_now, write_json
from bspforge.hardware_effect_graph import FEATURE_NAMES, HardwareEffectGraph
from bspforge.ranking_dataset import latest_ir


def main() -> int:
    parser = argparse.ArgumentParser(description="为操作候选增加函数体、寄存器锚点和跨过程效果图特征")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json"))
    parser.add_argument("--ir-root", type=Path, default=Path("workspace/operation-ir"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    manifest = read_json(args.manifest)
    sdk_config = {item["sdk_id"]: item for item in manifest["sdks"]}
    groups_by_sdk: dict[str, list[dict]] = {}
    for group in dataset["groups"]:
        groups_by_sdk.setdefault(group["sdk_id"], []).append(group)

    sdk_reports = []
    for sdk_id, groups in sorted(groups_by_sdk.items()):
        config = sdk_config[sdk_id]
        ir = read_json(latest_ir(args.ir_root, sdk_id))
        candidate_ids = {
            candidate["entity_id"]
            for group in groups
            for candidate in group["candidates"]
        }
        graph = HardwareEffectGraph(ir, Path(config["source_path"]), candidate_ids)
        analyzed = 0
        anchored = 0
        paths = 0
        status = Counter()
        for group in groups:
            for candidate in group["candidates"]:
                features, evidence = graph.candidate_features(candidate, group["operation_id"])
                candidate["features"].update(features)
                candidate["hardware_effect_evidence"] = evidence
                analyzed += 1
                anchored += features["hw-register-anchor"] > 0
                paths += bool(evidence.get("effect_path"))
                status[evidence["status"]] += 1
        report = {
            "sdk_id": sdk_id,
            "groups": len(groups),
            "candidate_rows": analyzed,
            "unique_entities": len(candidate_ids),
            "register_catalog_entries": len(graph.catalog.capabilities),
            "register_catalog_sources": dict(graph.catalog.evidence),
            "direct_register_anchors": anchored,
            "effect_paths": paths,
            "status": dict(status),
        }
        sdk_reports.append(report)
        print(report, flush=True)

    dataset["hardware_effect_graph"] = {
        "schema_version": "0.1",
        "created_at": utc_now(),
        "method": "register-anchored interprocedural hardware-effect graph",
        "feature_names": FEATURE_NAMES,
        "label_independent": True,
        "sdks": sdk_reports,
        "summary": {
            "sdks": len(sdk_reports),
            "groups": len(dataset["groups"]),
            "candidate_rows": sum(item["candidate_rows"] for item in sdk_reports),
            "unique_entities": sum(item["unique_entities"] for item in sdk_reports),
            "register_catalog_entries": sum(item["register_catalog_entries"] for item in sdk_reports),
            "direct_register_anchors": sum(item["direct_register_anchors"] for item in sdk_reports),
            "effect_paths": sum(item["effect_paths"] for item in sdk_reports),
        },
    }
    write_json(args.output, dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
