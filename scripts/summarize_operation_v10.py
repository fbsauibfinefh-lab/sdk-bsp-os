#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.common import read_json, utc_now, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可提交的 v1.0 结构化排序实验摘要")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--pipeline-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = read_json(args.baseline)
    ranking = read_json(args.ranking)
    training = read_json(args.training)
    pipeline = read_json(args.pipeline_report)
    final = ranking["external"]["final-method"]
    targets = {
        "precision_at_1": 0.80,
        "recall_at_5": 0.90,
        "map": 0.80,
        "ndcg_at_10": 0.80,
        "selective_precision": 0.95,
    }
    output = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "status": "exploratory-external-test",
        "protocol": ranking["protocol"],
        "dataset_summary": baseline["dataset_summary"],
        "truth_audit": baseline["truth_audit"],
        "method": {
            "name": "hierarchy-constrained field late interaction with API-family coverage decoding",
            "runtime_resolver": "operation-structured",
            "family_quota": 4,
            "trainable_gate_parameters": training["parameters"],
            "adaptive_gate_role": "negative ablation; excluded from final score",
        },
        "external": {
            "v0.9_best_map_configuration": baseline["ranking"]["static-field-late-0.25"],
            "operation_static": ranking["external"]["operation-static"],
            "field_late_interaction": ranking["external"]["field-late-interaction"],
            "structured_rrf": ranking["external"]["structured-rrf"],
            "hierarchical_fusion": ranking["external"]["hierarchical-fusion"],
            "final_method": final,
            "by_sdk": ranking["external_by_sdk"],
            "by_capability": ranking["external_by_capability"],
            "selective_calibration": ranking["selective_calibration"],
            "bootstrap_vs_operation_static": ranking["comparisons_vs_operation_static"]["final-method"],
        },
        "targets": {
            **targets,
            "passed": {
                "precision_at_1": final["precision_at_1"] >= targets["precision_at_1"],
                "recall_at_5": final["recall_at_5"] >= targets["recall_at_5"],
                "map": final["map"] >= targets["map"],
                "ndcg_at_10": final["ndcg_at_10"] >= targets["ndcg_at_10"],
                "selective_precision": (
                    ranking["selective_calibration"]["external"]["precision"]
                    >= targets["selective_precision"]
                ),
            },
        },
        "k210_pipeline": {
            "method": "operation-structured",
            "total_seconds": pipeline["timings"]["total_seconds"],
            "semantic_resolution_seconds": pipeline["timings"]["semantic_resolution_seconds"],
            "build_success": pipeline["build"]["success"],
            "build_attempts": pipeline["build"]["attempts"],
            "repairs_applied": pipeline["build"]["repairs_applied"],
            "artifacts": pipeline["build"]["artifact_verification"]["artifacts"],
            "compile_feedback": pipeline["compile_feedback"]["summary"],
            "legacy_capability_metric_warning": (
                "旧 K210 能力级真值不包含操作级替代符号，不能与 50 组分级操作主表直接比较。"
            ),
        },
        "limitations": [
            "三套板卡 SDK 已用于错误分析，因此结果属于探索性外部测试。",
            "正式论文需冻结方法后增加未查看 SDK 做一次性确认测试。",
            "当前单人源码真值仍需第二名标注者复核。",
            "编译反馈不证明上板运行语义。",
        ],
    }
    write_json(args.output, output)
    print({"output": str(args.output), "final": final, "passed": output["targets"]["passed"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
