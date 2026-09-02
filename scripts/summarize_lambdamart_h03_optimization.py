#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean, pstdev

from bspforge.common import read_json, write_json
from evaluate_hardware_effect_pu_ranker import paired_comparison


METHODS = (
    "all-default",
    "all-top5",
    "unique-top5",
    "hard20-top5",
    "hard40-top5",
    "hard80-top5",
    "hard40-top10",
    "hard40-top5-invariant",
)
METRICS = (
    "precision_at_1",
    "recall_at_5",
    "map",
    "ndcg_at_10",
    "hit_at_5",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总H03 LambdaMART多随机种子结果")
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--h02-baseline", type=Path, required=True)
    parser.add_argument("--h03-baseline", type=Path, required=True)
    parser.add_argument("--call-equivalence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reports = [read_json(path) for path in args.result]
    methods = {}
    for method in METHODS:
        runs = [item["cross_validation"]["metrics"][method] for item in reports]
        methods[method] = {
            metric: {
                "mean": round(mean(run[metric] for run in runs), 6),
                "population_std": round(pstdev(run[metric] for run in runs), 6),
                "values": [run[metric] for run in runs],
            }
            for metric in METRICS
        }
    h02 = read_json(args.h02_baseline)["cross_validation"]["metrics"][
        "multiview-lambdamart-nested"
    ]
    h03_report = read_json(args.h03_baseline)
    h03 = h03_report["cross_validation"]["metrics"][
        "multiview-lambdamart-nested"
    ]
    baseline_records = h03_report["cross_validation"]["records"]
    report = {
        "schema_version": "lambdamart-h03-multiseed-summary-v1",
        "truth_calibration": {
            "h02": h02,
            "h03": h03,
            "h03_minus_h02": {
                metric: round(h03[metric] - h02[metric], 6)
                for metric in ("precision_at_1", "recall_at_5", "map", "ndcg_at_10")
            },
        },
        "seeds": [item.get("seed", path.stem) for item, path in zip(reports, args.result, strict=True)],
        "methods": methods,
        "paired_all_top5_vs_h03": [
            {
                "run": index + 1,
                "vs_nested": paired_comparison(
                    item["cross_validation"]["records"]["all-top5"],
                    baseline_records["multiview-lambdamart-nested"],
                    seed=20261000 + index,
                ),
                "vs_fixed_small_reg": paired_comparison(
                    item["cross_validation"]["records"]["all-top5"],
                    baseline_records["multiview-lambdamart-tree-small-reg"],
                    seed=20261100 + index,
                ),
            }
            for index, item in enumerate(reports)
        ],
        "retained_method": {
            "name": "all-top5",
            "reason": "三随机种子P@1稳定提升；硬负样本最优值未跨种子复现。",
        },
        "call_equivalence": read_json(args.call_equivalence),
    }
    write_json(args.output, report)
    print(report["truth_calibration"])
    print(report["methods"]["all-top5"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
