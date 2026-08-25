#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bspforge.semantic_resolver.learning import FEATURE_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="训练 BSPForge LightGBM LambdaRank 排序器")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hybrid-weight", type=float, default=0.75)
    args = parser.parse_args()
    try:
        import lightgbm
    except ImportError as error:
        raise SystemExit("请先安装 BSPForge learning 可选依赖") from error
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    groups = dataset["groups"]
    sdk_ids = {item["sdk_id"] for item in groups}
    if len(sdk_ids) < 2:
        raise SystemExit("训练数据至少需要两个独立 SDK；正式实验应采用 leave-one-SDK-out")
    features: list[list[float]] = []
    labels: list[int] = []
    group_sizes: list[int] = []
    for group in groups:
        candidates = group["candidates"]
        group_sizes.append(len(candidates))
        for candidate in candidates:
            features.append([float(candidate["features"].get(name, 0.0)) for name in FEATURE_NAMES])
            labels.append(int(candidate["label"]))
    model = lightgbm.LGBMRanker(
        objective="lambdarank",
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=15,
        random_state=20260824,
    )
    model.fit(features, labels, group=group_sizes, feature_name=FEATURE_NAMES)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(args.output))
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "feature_names": FEATURE_NAMES,
            "sdk_ids": sorted(sdk_ids),
            "groups": len(groups),
            "candidates": len(features),
            "dataset_summary": dataset.get("summary", {}),
            "training_protocol": "grouped-by-sdk-capability; evaluate with leave-one-sdk-out",
            "recommended_method": "hybrid",
            "recommended_hybrid_weight": args.hybrid_weight,
            "model": {
                "objective": "lambdarank",
                "n_estimators": 120,
                "learning_rate": 0.05,
                "num_leaves": 15,
                "random_state": 20260824
            }
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
