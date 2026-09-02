#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json


METRICS = ("precision_at_1", "recall_at_5", "map", "ndcg_at_10")


def parse_mapping(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise ValueError(f"expected ID=PATH, got {value!r}")
        result[name] = Path(path)
    return result


def metric_records(report: dict[str, Any], method: str) -> dict[str, dict[str, float]]:
    return {
        item["group_id"]: item["metrics"]
        for item in report["external_records"][method]
    }


def paired_bootstrap(
    baseline: dict[str, dict[str, float]],
    treatment: dict[str, dict[str, float]],
    metric: str,
    seed: int,
    samples: int = 10000,
) -> dict[str, Any]:
    group_ids = sorted(set(baseline) & set(treatment))
    deltas = [treatment[group][metric] - baseline[group][metric] for group in group_ids]
    rng = random.Random(seed)
    estimates = sorted(
        mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(samples)
    )
    return {
        "groups": len(group_ids),
        "mean_delta": round(mean(deltas), 6),
        "ci95": [
            round(estimates[round(0.025 * (samples - 1))], 6),
            round(estimates[round(0.975 * (samples - 1))], 6),
        ],
        "bootstrap_samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总三套平行真值的 461 参数门控公平复跑")
    parser.add_argument("--result", action="append", required=True, help="ID=结果 JSON")
    parser.add_argument("--training", action="append", required=True, help="ID=训练报告 JSON")
    parser.add_argument("--dataset", action="append", required=True, help="ID=结构化数据集 JSON")
    parser.add_argument("--legacy-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260828)
    args = parser.parse_args()

    result_paths = parse_mapping(args.result)
    training_paths = parse_mapping(args.training)
    dataset_paths = parse_mapping(args.dataset)
    reports = {name: read_json(path) for name, path in result_paths.items()}
    training = {name: read_json(path) for name, path in training_paths.items()}
    datasets = {name: read_json(path) for name, path in dataset_paths.items()}
    baseline_id = "automatic-v0.9"
    baseline_records = metric_records(reports[baseline_id], "adaptive-field-gate")

    truth_results = {}
    for truth_id, report in reports.items():
        dataset = datasets[truth_id]
        gate = report["external"]["adaptive-field-gate"]
        truth_results[truth_id] = {
            "dataset": {
                **dataset["summary"],
                "truth_set_id": dataset.get("truth_set_id"),
                "randomization_scope": dataset["sampling"].get("randomization_scope"),
            },
            "training": {
                key: training[truth_id][key]
                for key in (
                    "parameters", "training_groups", "development_groups",
                    "epochs_completed", "best_epoch", "development",
                )
            },
            "selected_on_development": {
                "linear_weights": report["selected_on_development"]["linear_weights"],
                "adaptive_weight": report["selected_on_development"]["adaptive_weight"],
            },
            "external_adaptive_gate": {metric: gate[metric] for metric in METRICS},
            "external_complete_method": {
                metric: report["external"]["complete-method"][metric]
                for metric in METRICS
            },
            "external_final_method": {
                metric: report["external"]["final-method"][metric]
                for metric in METRICS
            },
            "selective_calibration": report["selective_calibration"],
        }

    comparisons = {}
    for index, truth_id in enumerate(("human-engineer-1", "human-engineer-2")):
        treatment = metric_records(reports[truth_id], "adaptive-field-gate")
        comparisons[f"{truth_id}-vs-{baseline_id}"] = {
            metric: paired_bootstrap(
                baseline_records,
                treatment,
                metric,
                args.seed + index * 100 + metric_index,
            )
            for metric_index, metric in enumerate(METRICS)
        }

    legacy = None
    if args.legacy_result:
        report = read_json(args.legacy_result)
        legacy = {
            "warning": "旧结果使用全局随机负例流，外部候选集与公平复跑不完全相同，仅供历史对照。",
            "adaptive_field_gate": {
                metric: report["external"]["adaptive-field-gate"][metric]
                for metric in METRICS
            },
        }

    summary = {
        "schema_version": "adaptive-truth-rerun-summary-v1",
        "experiment_date": "2026-08-28",
        "protocol": {
            "truth_sets": sorted(reports),
            "seed": args.seed,
            "training_seed": 20260826,
            "external_groups": 50,
            "external_candidate_sets_identical": True,
            "model_parameters": 461,
            "status": "single-seed exploratory rerun",
        },
        "truth_results": truth_results,
        "paired_bootstrap_vs_automatic": comparisons,
        "legacy_original_result": legacy,
        "conclusion": {
            "human_truth_improves_external_gate": True,
            "gate_reaches_final_method_targets": False,
            "recommended_role": "negative ablation retained; excluded from final method",
        },
    }
    write_json(args.output, summary)
    print({
        name: values["external_adaptive_gate"]
        for name, values in truth_results.items()
    })
    print(comparisons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
