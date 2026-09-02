#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.code_effect_encoder import CodeEmbeddingCache
from bspforge.common import read_json, write_json
from bspforge.hardware_effect_graph import hard_constraint_penalty
from bspforge.pretrained_effect_ranker import PretrainedEffectPURanker
from bspforge.structured_retrieval import complete_structured_scores
from evaluate_hardware_effect_pu_ranker import (
    aggregate,
    fold_assignments,
    paired_comparison,
    preference_pairs,
)
from evaluate_operation_ranker import ranking_metrics


def train_ranker(
    groups: list[dict[str, Any]],
    cache: CodeEmbeddingCache,
    *,
    seed: int,
    epochs: int,
    device: str,
) -> tuple[PretrainedEffectPURanker, dict[str, Any]]:
    import torch

    started = time.perf_counter()
    random.seed(seed)
    torch.manual_seed(seed)
    ranker = PretrainedEffectPURanker(cache, device=device)
    ranker.fit_scaler([candidate for group in groups for candidate in group["candidates"]])
    pairs = preference_pairs(groups, seed)
    optimizer = torch.optim.AdamW(
        ranker.network.parameters(), lr=0.0035, weight_decay=0.006
    )
    history = []
    for epoch in range(epochs):
        order = list(range(len(pairs)))
        random.Random(seed + epoch).shuffle(order)
        losses = []
        for start in range(0, len(order), 192):
            batch = [pairs[index] for index in order[start : start + 192]]
            batch_groups = [item[0] for item in batch]
            operation_ids = [item[0]["operation_id"] for item in batch]
            operations = ranker.operation_tensor(operation_ids)
            queries = ranker.query_tensor(operation_ids)
            positive_indices = [item[1] for item in batch]
            unlabeled_indices = [item[2] for item in batch]
            positive_candidates = [
                group["candidates"][index]
                for group, index in zip(batch_groups, positive_indices, strict=True)
            ]
            unlabeled_candidates = [
                group["candidates"][index]
                for group, index in zip(batch_groups, unlabeled_indices, strict=True)
            ]
            positive_scores = ranker.network(
                queries,
                ranker.document_tensor(batch_groups, positive_indices),
                ranker.graph_tensor(positive_candidates),
                operations,
            )
            unlabeled_scores = ranker.network(
                queries,
                ranker.document_tensor(batch_groups, unlabeled_indices),
                ranker.graph_tensor(unlabeled_candidates),
                operations,
            )
            weights = torch.tensor(
                [item[3] for item in batch], dtype=torch.float32, device=device
            )
            pair_loss = (
                torch.nn.functional.softplus(-(positive_scores - unlabeled_scores))
                * weights
            ).mean()
            adapter_penalty = 0.0005 * ranker.network.query_up.weight.square().mean()
            loss = pair_loss + adapter_penalty
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(ranker.network.parameters(), 2.0)
            optimizer.step()
            losses.append(float(loss.detach()))
        history.append(round(mean(losses), 6))
    ranker.network.eval()
    return ranker, {
        "pairs": len(pairs),
        "epochs": epochs,
        "final_loss": history[-1],
        "loss_history": history,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def standardized(values: list[float]) -> list[float]:
    center = mean(values)
    variance = mean((item - center) ** 2 for item in values)
    scale = max(variance ** 0.5, 1e-6)
    return [(item - center) / scale for item in values]


def calibrated_fusion_scores(
    group: dict[str, Any],
    components: dict[str, list[float]],
    *,
    code_weight: float,
) -> list[float]:
    code = standardized(components["adapted"])
    graph = standardized([
        score - 4.0 * hard_constraint_penalty(candidate)
        for score, candidate in zip(
            components["graph"], group["candidates"], strict=True
        )
    ])
    return [
        code_weight * code_score + (1.0 - code_weight) * graph_score
        for code_score, graph_score in zip(code, graph, strict=True)
    ]


def method_scores(
    group: dict[str, Any], ranker: PretrainedEffectPURanker, *, code_weight: float
) -> dict[str, list[float]]:
    components = ranker.group_components(group)
    return {
        "pretrained-code-zero-shot": components["base"],
        "pretrained-code-adapted": components["adapted"],
        "pretrained-code-graph-fusion": components["fusion"],
        "pretrained-code-calibrated-fusion": calibrated_fusion_scores(
            group, components, code_weight=code_weight
        ),
        "existing-q4": complete_structured_scores(group)[0],
    }


def evaluate_group(
    group: dict[str, Any], ranker: PretrainedEffectPURanker, *, code_weight: float
) -> dict[str, dict[str, Any]]:
    output = {}
    for method, scores in method_scores(
        group, ranker, code_weight=code_weight
    ).items():
        ranked = sorted(
            zip(group["candidates"], scores, strict=True),
            key=lambda item: (-item[1], item[0]["entity_id"]),
        )
        unique = []
        seen = set()
        for candidate, score in ranked:
            if candidate["symbol"] in seen:
                continue
            seen.add(candidate["symbol"])
            unique.append((candidate, score))
        output[method] = {
            "metrics": ranking_metrics(group["candidates"], scores),
            "selected": {
                "symbol": unique[0][0]["symbol"],
                "label": unique[0][0]["label"],
                "score": round(float(unique[0][1]), 6),
            },
            "positive_ranks": [
                {
                    "rank": rank,
                    "symbol": candidate["symbol"],
                    "label": candidate["label"],
                    "score": round(float(score), 6),
                }
                for rank, (candidate, score) in enumerate(unique, start=1)
                if candidate["label"] > 0
            ],
            "top5": [
                {
                    "symbol": candidate["symbol"],
                    "label": candidate["label"],
                    "score": round(float(score), 6),
                }
                for candidate, score in unique[:5]
            ],
        }
    return output


def select_code_weight(
    groups: list[dict[str, Any]],
    cache: CodeEmbeddingCache,
    *,
    seed: int,
    device: str,
) -> tuple[float, dict[str, Any]]:
    validation_ids = fold_assignments(groups, 4)[0]
    inner_train = [
        item for item in groups if item["independence_group"] not in validation_ids
    ]
    validation = [
        item for item in groups if item["independence_group"] in validation_ids
    ]
    ranker, training = train_ranker(
        inner_train, cache, seed=seed, epochs=24, device=device
    )
    candidates = [0.50, 0.65, 0.80, 0.90, 1.00]
    metrics_by_weight = {}
    for weight in candidates:
        records = []
        for group in validation:
            scores = calibrated_fusion_scores(
                group, ranker.group_components(group), code_weight=weight
            )
            records.append({"metrics": ranking_metrics(group["candidates"], scores)})
        metrics_by_weight[str(weight)] = aggregate(records)

    def objective(weight: float) -> tuple[float, float]:
        metrics = metrics_by_weight[str(weight)]
        primary = mean([
            metrics["precision_at_1"],
            metrics["recall_at_5"],
            metrics["map"],
            metrics["ndcg_at_10"],
        ])
        return primary, weight

    selected = max(candidates, key=objective)
    return selected, {
        "unit": "independence_group/vendor",
        "validation_independence_groups": sorted(validation_ids),
        "inner_train_groups": len(inner_train),
        "validation_groups": len(validation),
        "candidate_code_weights": candidates,
        "metrics_by_weight": metrics_by_weight,
        "selected_code_weight": selected,
        "objective": "mean(P@1, Recall@5, MAP, nDCG@10); ties prefer more code weight",
        "training": training,
    }


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="评估预训练代码编码器增强的硬件效果PU排序")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--embedding-metadata", type=Path, required=True)
    parser.add_argument("--embedding-vectors", type=Path, required=True)
    parser.add_argument("--v01-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = CodeEmbeddingCache(args.embedding_metadata, args.embedding_vectors)
    training_groups = [item for item in dataset["groups"] if item["role"] == "train"]
    external_groups = [item for item in dataset["groups"] if item["role"] == "external-test"]
    assignments = fold_assignments(training_groups, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        train = [item for item in training_groups if item["independence_group"] not in test_ids]
        test = [item for item in training_groups if item["independence_group"] in test_ids]
        code_weight, calibration_report = select_code_weight(
            train, cache, seed=args.seed + 100 + fold, device=args.device
        )
        ranker, training_report = train_ranker(
            train, cache, seed=args.seed + fold, epochs=args.epochs, device=args.device
        )
        fold_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for group in test:
            for method, result in evaluate_group(
                group, ranker, code_weight=code_weight
            ).items():
                record = {
                    "group_id": group["group_id"],
                    "sdk_id": group["sdk_id"],
                    "operation_id": group["operation_id"],
                    **result,
                }
                records[method].append(record)
                fold_records[method].append(record)
        metrics = {method: aggregate(items) for method, items in fold_records.items()}
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "train_groups": len(train),
            "test_groups": len(test),
            "training": training_report,
            "calibration": calibration_report,
            "metrics": metrics,
        })
        print({"fold": fold, "test": sorted(test_ids), "metrics": metrics}, flush=True)

    final_code_weight, final_calibration = select_code_weight(
        training_groups, cache, seed=args.seed + 200, device=args.device
    )
    final_ranker, final_training = train_ranker(
        training_groups, cache, seed=args.seed, epochs=args.epochs, device=args.device
    )
    external_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in external_groups:
        for method, result in evaluate_group(
            group, final_ranker, code_weight=final_code_weight
        ).items():
            external_records[method].append({
                "group_id": group["group_id"],
                "sdk_id": group["sdk_id"],
                "operation_id": group["operation_id"],
                **result,
            })
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_ranker.torch.save(final_ranker.state_payload(), args.output_model)

    v01 = read_json(args.v01_results)
    report = {
        "schema_version": "0.2",
        "truth_set": dataset.get("truth_set_id", "human-engineer-2-H02"),
        "method": "frozen Jina code encoder, effect-aware serialization, low-rank query adapter, hardware graph fusion, nested calibration, and PU pairwise ranking",
        "training_boundary": {
            "positive": "H02 label > 0",
            "unlabeled": "H02 label == 0 with reduced-confidence pairwise sampling",
            "no_public_api": "excluded by the input dataset and not modeled in v0.2",
            "encoder_frozen": True,
        },
        "embedding_cache": cache.metadata,
        "cross_validation": {
            "unit": "independence_group/vendor",
            "folds": args.folds,
            "groups": len(training_groups),
            "sdks": len({item["sdk_id"] for item in training_groups}),
            "metrics": {method: aggregate(items) for method, items in records.items()},
            "v01_hardware_effect_metrics": v01["cross_validation"]["metrics"],
            "paired_calibrated_fusion_vs_q4": paired_comparison(
                records["pretrained-code-calibrated-fusion"], records["existing-q4"], seed=args.seed
            ),
            "paired_calibrated_fusion_vs_v01": None,
            "fold_reports": fold_reports,
            "records": records,
        },
        "external_board_diagnostic": {
            "excluded_from_training": True,
            "historically_inspected": True,
            "groups": len(external_groups),
            "metrics": {
                method: aggregate(items) for method, items in external_records.items()
            },
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "trainable_parameters": final_ranker.parameter_count(),
            "frozen_encoder_parameters": 161_000_000,
            "training": final_training,
            "calibration": final_calibration,
        },
        "evaluation_elapsed_seconds": None,
    }
    v01_records = v01["cross_validation"]["records"]["hardware-effect-pu-residual"]
    report["cross_validation"]["paired_calibrated_fusion_vs_v01"] = paired_comparison(
        records["pretrained-code-calibrated-fusion"], v01_records, seed=args.seed + 1
    )
    report["evaluation_elapsed_seconds"] = round(time.perf_counter() - started, 3)
    write_json(args.output, report)
    print({
        "cross_validation": report["cross_validation"]["metrics"],
        "v01": report["cross_validation"]["v01_hardware_effect_metrics"]["hardware-effect-pu-residual"],
        "external": report["external_board_diagnostic"]["metrics"],
        "parameters": report["final_model"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
