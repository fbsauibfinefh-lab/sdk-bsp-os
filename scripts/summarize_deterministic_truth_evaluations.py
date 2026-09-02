#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总确定性方法的平行真值全量评测")
    parser.add_argument("--automatic", type=Path, required=True)
    parser.add_argument("--h01", type=Path, required=True)
    parser.add_argument("--h02", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reports = {
        "automatic-v0.9": read_json(args.automatic),
        "human-engineer-1-H01": read_json(args.h01),
        "human-engineer-2-H02": read_json(args.h02),
    }
    summary = {
        "schema_version": "1.0",
        "method": "training-free deterministic structured ranking v1.2",
        "evaluation_scope": "all query groups with reachable truth in each parallel truth set",
        "truth_sets_are_parallel_not_merged": True,
        "results": {
            name: {
                "sdks": report["sdks"],
                "groups": report["groups"],
                "groups_by_role": report["groups_by_role"],
                "metrics": report["metrics"],
                "score_diagnostics": report["score_diagnostics"],
            }
            for name, report in reports.items()
        },
        "interpretation": {
            "external_50_is_diagnostic_only": True,
            "top1_is_always_returned": True,
            "low_score_is_diagnostic_only": True,
            "board_results_do_not_replace_full_corpus_results": True,
        },
    }
    write_json(args.output, summary)
    print(summary["results"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
