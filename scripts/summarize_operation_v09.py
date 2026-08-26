#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, utc_now, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可提交的 v0.9 紧凑实验摘要")
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--structured", type=Path, required=True)
    parser.add_argument("--truth-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ranking = read_json(args.ranking)
    structured = read_json(args.structured)
    audit = read_json(args.truth_audit)
    output = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "protocol": ranking["protocol"],
        "dataset_summary": ranking["dataset_summary"],
        "truth_audit": {
            "passed": audit["passed"],
            "label_counts": audit["label_counts"],
            "group_coverage": audit["group_coverage"],
            "checks": audit["checks"],
        },
        "ranking": ranking["aggregate"],
        "structured": {
            "selected": structured["selected"],
            "external": structured["external"],
            "selective_calibration": structured["selective_calibration"],
        },
        "interpretation": {
            "status": "exploratory-external-test",
            "target": {
                "precision_at_1": 0.80,
                "recall_at_5": 0.90,
                "map": 0.80,
                "ndcg_at_10": 0.80,
                "selective_precision": 0.95,
            },
            "warning": (
                "板卡结果已用于多轮错误分析和真值完整性修订；正式论文需冻结方法后"
                "增加未查看 SDK，并对板卡真值进行第二人复核。"
            ),
        },
    }
    write_json(args.output, output)
    print({"output": str(args.output), "ranking_methods": len(output["ranking"])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
