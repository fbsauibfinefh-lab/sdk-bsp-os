#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_graph import hardware_heuristic_score
from bspforge.joint_pair_ranker import JointPairRanker
from bspforge.multiview_effect_encoder import JointPairCache, MultiViewEffectCache
from evaluate_hardware_effect_pu_ranker import aggregate, fold_assignments, paired_comparison
from evaluate_multiview_effect_ranker import record_for_scores


CONFIGS = {
    "joint-e12": {"epochs": 12, "listwise_weight": 0.0},
    "joint-e24": {"epochs": 24, "listwise_weight": 0.0},
    "joint-e36": {"epochs": 36, "listwise_weight": 0.0},
    "joint-listwise-002": {"epochs": 24, "listwise_weight": 0.02},
    "joint-listwise-005": {"epochs": 24, "listwise_weight": 0.05},
}

JOINT_WEIGHTS = [0.50, 0.70, 0.85, 1.00]


def joint_preference_pairs(
    groups: list[dict[str, Any]], ranker: JointPairRanker, seed: int
) -> list[tuple[dict[str, Any], int, int, float]]:
    pairs = []
    for group in groups:
        indices = ranker.shortlist_indices(group)
        positives = [index for index in indices if group["candidates"][index]["label"] > 0]
        unlabeled = [index for index in indices if group["candidates"][index]["label"] == 0]
        hard = sorted(
            unlabeled,
            key=lambda index: (
                -hardware_heuristic_score(group["candidates"][index]),
                group["candidates"][index]["entity_id"],
            ),
        )
        for positive in positives:
            positive_candidate = group["candidates"][positive]
            family = positive_candidate.get("api_family", "")
            same_family = [
                index for index in hard
                if family and group["candidates"][index].get("api_family") == family
            ][:8]
            general = [index for index in hard if index not in same_family][:10]
            remainder = [index for index in unlabeled if index not in same_family and index not in general]
            rng = random.Random(f"{seed}:{group['group_id']}:{positive_candidate['symbol']}")
            sampled = rng.sample(remainder, min(4, len(remainder)))
            grade = float(positive_candidate["label"]) / 3.0
            confidence = float(positive_candidate.get("label_confidence", 1.0))
            positive_weight = confidence * (0.65 + 0.35 * grade)
            for index in same_family:
                pairs.append((group, positive, index, 0.70 * positive_weight))
            for index in general:
                pairs.append((group, positive, index, 0.55 * positive_weight))
            for index in sampled:
                pairs.append((group, positive, index, 0.35 * positive_weight))
    return pairs


def train_ranker(
    groups: list[dict[str, Any]],
    multiview_cache: MultiViewEffectCache,
    joint_cache: JointPairCache,
    config: dict[str, Any],
    *,
    seed: int,
    device: str,
) -> tuple[JointPairRanker, dict[str, Any]]:
    import torch

    started = time.perf_counter()
    random.seed(seed)
    torch.manual_seed(seed)
    ranker = JointPairRanker(multiview_cache, joint_cache, device=device)
    ranker.fit_scaler(groups)
    pairs = joint_preference_pairs(groups, ranker, seed)
    optimizer = torch.optim.AdamW(
        ranker.network.parameters(), lr=0.002, weight_decay=0.015
    )
    history = []
    eligible_groups = [
        group for group in groups
        if any(
            group["candidates"][index]["label"] > 0
            for index in ranker.shortlist_indices(group)
        )
    ]
    for epoch in range(int(config["epochs"])):
        ranker.network.train()
        order = list(range(len(pairs)))
        random.Random(seed + epoch).shuffle(order)
        group_order = list(range(len(eligible_groups)))
        random.Random(seed + 10_000 + epoch).shuffle(group_order)
        losses = []
        list_losses = []
        for step, start in enumerate(range(0, len(order), 192)):
            batch = [pairs[index] for index in order[start : start + 192]]
            batch_groups = [item[0] for item in batch]
            positive_scores = ranker.score_tensor(
                batch_groups, [item[1] for item in batch]
            )
            unlabeled_scores = ranker.score_tensor(
                batch_groups, [item[2] for item in batch]
            )
            weights = torch.tensor(
                [item[3] for item in batch], dtype=torch.float32, device=device
            )
            pair_loss = (
                torch.nn.functional.softplus(-(positive_scores - unlabeled_scores))
                * weights
            ).mean()
            list_loss = torch.zeros((), dtype=torch.float32, device=device)
            if config["listwise_weight"] > 0:
                group = eligible_groups[group_order[step % len(group_order)]]
                indices = ranker.shortlist_indices(group)
                logits = ranker.score_tensor([group] * len(indices), indices)
                labels = torch.tensor(
                    [float(group["candidates"][index]["label"]) for index in indices],
                    dtype=torch.float32,
                    device=device,
                )
                mask = labels > 0
                target = torch.softmax(labels[mask] / 0.70, dim=0)
                list_loss = -(target * torch.log_softmax(logits, dim=0)[mask]).sum()
            loss = pair_loss + float(config["listwise_weight"]) * list_loss
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(ranker.network.parameters(), 2.0)
            optimizer.step()
            losses.append(float(loss.detach()))
            if config["listwise_weight"] > 0:
                list_losses.append(float(list_loss.detach()))
        history.append({
            "loss": round(mean(losses), 6),
            "listwise_loss": round(mean(list_losses), 6) if list_losses else None,
        })
    ranker.network.eval()
    return ranker, {
        "pairs": len(pairs),
        "eligible_groups": len(eligible_groups),
        "epochs": int(config["epochs"]),
        "listwise_weight": float(config["listwise_weight"]),
        "final_loss": history[-1],
        "loss_history": history,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def standardized(values: list[float]) -> list[float]:
    center = mean(values)
    variance = mean((value - center) ** 2 for value in values)
    scale = max(variance ** 0.5, 1e-6)
    return [(value - center) / scale for value in values]


def scores_for_weight(
    group: dict[str, Any], ranker: JointPairRanker, joint_weight: float
) -> list[float]:
    components = ranker.group_components(group)
    joint = standardized(components["joint"])
    scalar = standardized(components["scalar"])
    shortlist_scores = [
        joint_weight * left + (1.0 - joint_weight) * right
        for left, right in zip(joint, scalar, strict=True)
    ]
    scores = [-100.0] * len(group["candidates"])
    for index, score in zip(components["indices"], shortlist_scores, strict=True):
        scores[index] = score
    return scores


def evaluate(
    groups: list[dict[str, Any]], ranker: JointPairRanker, joint_weight: float
) -> list[dict[str, Any]]:
    return [
        record_for_scores(group, scores_for_weight(group, ranker, joint_weight))
        for group in groups
    ]


def objective(metrics: dict[str, float]) -> float:
    return mean([
        metrics["precision_at_1"], metrics["recall_at_5"],
        metrics["map"], metrics["ndcg_at_10"],
    ])


def select_weight(
    groups: list[dict[str, Any]],
    multiview_cache: MultiViewEffectCache,
    joint_cache: JointPairCache,
    config: dict[str, Any],
    *,
    seed: int,
    device: str,
) -> tuple[float, dict[str, Any]]:
    validation_ids = fold_assignments(groups, 4)[0]
    inner_train = [group for group in groups if group["independence_group"] not in validation_ids]
    validation = [group for group in groups if group["independence_group"] in validation_ids]
    ranker, training = train_ranker(
        inner_train, multiview_cache, joint_cache, config,
        seed=seed, device=device,
    )
    metrics = {
        str(weight): aggregate(evaluate(validation, ranker, weight))
        for weight in JOINT_WEIGHTS
    }
    selected = max(
        JOINT_WEIGHTS, key=lambda weight: (objective(metrics[str(weight)]), weight)
    )
    return selected, {
        "validation_independence_groups": sorted(validation_ids),
        "metrics_by_weight": metrics,
        "selected_weight": selected,
        "selected_objective": round(objective(metrics[str(selected)]), 6),
        "training": training,
    }


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="评估Top-K冻结联合编码重排")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--joint-metadata", type=Path, required=True)
    parser.add_argument("--joint-vectors", type=Path, required=True)
    parser.add_argument("--v02-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    multiview_cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    joint_cache = JointPairCache(args.joint_metadata, args.joint_vectors)
    training = [group for group in dataset["groups"] if group["role"] == "train"]
    external = [group for group in dataset["groups"] if group["role"] == "external-test"]
    assignments = fold_assignments(training, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        outer_train = [group for group in training if group["independence_group"] not in test_ids]
        test = [group for group in training if group["independence_group"] in test_ids]
        config_reports = {}
        outer_rankers = {}
        for index, (name, config) in enumerate(CONFIGS.items()):
            weight, selection = select_weight(
                outer_train, multiview_cache, joint_cache, config,
                seed=args.seed + fold * 100, device=args.device,
            )
            ranker, training_report = train_ranker(
                outer_train, multiview_cache, joint_cache, config,
                seed=args.seed + fold * 10, device=args.device,
            )
            outer_rankers[name] = ranker
            outer_records = evaluate(test, ranker, weight)
            records[f"{name}-calibrated"].extend(outer_records)
            config_reports[name] = {
                "selection": selection,
                "outer_training": training_report,
                "outer_metrics": aggregate(outer_records),
            }
        selected_config = max(
            CONFIGS,
            key=lambda name: (config_reports[name]["selection"]["selected_objective"], name),
        )
        selected_weight = config_reports[selected_config]["selection"]["selected_weight"]
        nested_records = evaluate(test, outer_rankers[selected_config], selected_weight)
        records["joint-nested-selected"].extend(nested_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "selected_config": selected_config,
            "selected_weight": selected_weight,
            "metrics": aggregate(nested_records),
            "configurations": config_reports,
        })
        print({
            "fold": fold, "selected": [selected_config, selected_weight],
            "metrics": aggregate(nested_records),
        }, flush=True)

    final_reports = {}
    for index, (name, config) in enumerate(CONFIGS.items()):
        weight, selection = select_weight(
            training, multiview_cache, joint_cache, config,
            seed=args.seed + 1000, device=args.device,
        )
        final_reports[name] = {"weight": weight, "selection": selection}
    final_config = max(
        CONFIGS,
        key=lambda name: (final_reports[name]["selection"]["selected_objective"], name),
    )
    final_weight = final_reports[final_config]["weight"]
    final_ranker, final_training = train_ranker(
        training, multiview_cache, joint_cache, CONFIGS[final_config],
        seed=args.seed, device=args.device,
    )
    external_records = evaluate(external, final_ranker, final_weight)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_ranker.torch.save(final_ranker.state_payload(), args.output_model)

    v02 = read_json(args.v02_results)
    v02_records = v02["cross_validation"]["records"]["pretrained-code-calibrated-fusion"]
    report = {
        "schema_version": "0.3-joint",
        "method": "Top-K frozen joint query-candidate encoding with operation FiLM, family hard negatives, listwise trials, and nested calibration",
        "configurations": CONFIGS,
        "joint_weights": JOINT_WEIGHTS,
        "shortlist": joint_cache.metadata["shortlist"],
        "cross_validation": {
            "unit": "independence_group/vendor",
            "metrics": {name: aggregate(items) for name, items in records.items()},
            "paired_nested_vs_v02": paired_comparison(
                records["joint-nested-selected"], v02_records, seed=args.seed
            ),
            "fold_reports": fold_reports,
            "records": records,
        },
        "external_board_diagnostic": {
            "selected_config": final_config,
            "selected_weight": final_weight,
            "metrics": aggregate(external_records),
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "selected_config": final_config,
            "selected_weight": final_weight,
            "trainable_parameters": final_ranker.parameter_count(),
            "training": final_training,
            "selection": final_reports,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({
        "metrics": report["cross_validation"]["metrics"],
        "external": report["external_board_diagnostic"],
        "final": report["final_model"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
