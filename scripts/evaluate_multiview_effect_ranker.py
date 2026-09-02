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
from bspforge.multiview_effect_encoder import MultiViewEffectCache
from bspforge.multiview_effect_ranker import MultiViewEffectRanker
from evaluate_hardware_effect_pu_ranker import (
    aggregate,
    fold_assignments,
    paired_comparison,
    preference_pairs,
)
from evaluate_operation_ranker import ranking_metrics


CONFIGS = {
    "mv-basic": {"enhanced_pairs": False, "listwise_weight": 0.0, "epochs": 24},
    "mv-family-e12": {"enhanced_pairs": True, "listwise_weight": 0.0, "epochs": 12},
    "mv-family": {"enhanced_pairs": True, "listwise_weight": 0.0, "epochs": 24},
    "mv-family-e36": {"enhanced_pairs": True, "listwise_weight": 0.0, "epochs": 36},
    "mv-family-listwise-002": {
        "enhanced_pairs": True, "listwise_weight": 0.02, "epochs": 24,
    },
    "mv-family-listwise-005": {
        "enhanced_pairs": True, "listwise_weight": 0.05, "epochs": 24,
    },
}

RECIPES = {
    "focus-only": {"full": 0.0, "focused": 1.0, "graph": 0.0, "structured": 0.0},
    "semantic-30-70": {"full": 0.30, "focused": 0.70, "graph": 0.0, "structured": 0.0},
    "effect-balanced": {"full": 0.20, "focused": 0.60, "graph": 0.20, "structured": 0.0},
    "four-view": {"full": 0.15, "focused": 0.55, "graph": 0.15, "structured": 0.15},
    "structure-aware": {"full": 0.10, "focused": 0.50, "graph": 0.15, "structured": 0.25},
    "focus-structure": {"full": 0.0, "focused": 0.65, "graph": 0.10, "structured": 0.25},
}


def unique_indices(group: dict[str, Any], positive: bool) -> list[int]:
    by_symbol: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(group["candidates"]):
        if (candidate["label"] > 0) == positive:
            by_symbol[candidate["symbol"]].append(index)
    return [
        max(
            indices,
            key=lambda index: (
                int(group["candidates"][index]["label"]),
                hardware_heuristic_score(group["candidates"][index]),
                group["candidates"][index]["entity_id"],
            ),
        )
        for indices in by_symbol.values()
    ]


def enhanced_preference_pairs(
    groups: list[dict[str, Any]], seed: int
) -> list[tuple[dict[str, Any], int, int, float]]:
    pairs = []
    for group in groups:
        positives = unique_indices(group, True)
        unlabeled = unique_indices(group, False)
        hard = sorted(
            unlabeled,
            key=lambda index: (
                -hardware_heuristic_score(group["candidates"][index]),
                -float(group["candidates"][index]["features"].get("field-late-interaction", 0.0)),
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
            general = [index for index in hard if index not in same_family][:8]
            remainder = [index for index in unlabeled if index not in same_family and index not in general]
            rng = random.Random(f"{seed}:{group['group_id']}:{positive_candidate['symbol']}")
            sampled = rng.sample(remainder, min(4, len(remainder)))
            grade = float(positive_candidate["label"]) / 3.0
            confidence = float(positive_candidate.get("label_confidence", 1.0))
            positive_weight = confidence * (0.65 + 0.35 * grade)
            for index in same_family:
                pairs.append((group, positive, index, 0.70 * positive_weight))
            for index in general:
                score = hardware_heuristic_score(group["candidates"][index])
                pairs.append((group, positive, index, positive_weight * (0.35 + 0.30 * max(0.0, 1.0 - score))))
            for index in sampled:
                pairs.append((group, positive, index, 0.35 * positive_weight))
    return pairs


def train_ranker(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    config: dict[str, Any],
    *,
    seed: int,
    device: str,
) -> tuple[MultiViewEffectRanker, dict[str, Any]]:
    import torch

    started = time.perf_counter()
    random.seed(seed)
    torch.manual_seed(seed)
    ranker = MultiViewEffectRanker(cache, device=device)
    ranker.fit_scaler([candidate for group in groups for candidate in group["candidates"]])
    pairs = (
        enhanced_preference_pairs(groups, seed)
        if config["enhanced_pairs"]
        else preference_pairs(groups, seed)
    )
    optimizer = torch.optim.AdamW(
        ranker.network.parameters(), lr=0.0025, weight_decay=0.012
    )
    history = []
    epochs = int(config["epochs"])
    listwise_weight = float(config["listwise_weight"])
    for epoch in range(epochs):
        ranker.network.train()
        order = list(range(len(pairs)))
        random.Random(seed + epoch).shuffle(order)
        group_order = list(range(len(groups)))
        random.Random(seed + 10_000 + epoch).shuffle(group_order)
        losses = []
        list_losses = []
        for step, start in enumerate(range(0, len(order), 192)):
            batch = [pairs[index] for index in order[start : start + 192]]
            batch_groups = [item[0] for item in batch]
            positive = [item[1] for item in batch]
            unlabeled = [item[2] for item in batch]
            positive_scores = ranker.score_tensor(batch_groups, positive)
            unlabeled_scores = ranker.score_tensor(batch_groups, unlabeled)
            weights = torch.tensor(
                [item[3] for item in batch], dtype=torch.float32, device=device
            )
            pair_loss = (
                torch.nn.functional.softplus(-(positive_scores - unlabeled_scores))
                * weights
            ).mean()
            list_loss = torch.zeros((), dtype=torch.float32, device=device)
            if listwise_weight > 0:
                group = groups[group_order[step % len(group_order)]]
                indices = list(range(len(group["candidates"])))
                logits = ranker.score_tensor([group] * len(indices), indices)
                labels = torch.tensor(
                    [float(item["label"]) for item in group["candidates"]],
                    dtype=torch.float32,
                    device=device,
                )
                mask = labels > 0
                target = torch.softmax(labels[mask] / 0.70, dim=0)
                list_loss = -(target * torch.log_softmax(logits, dim=0)[mask]).sum()
            adapter_penalty = 0.0008 * (
                ranker.network.query_up.weight.square().mean()
                + ranker.network.focus_up.weight.square().mean()
            )
            loss = pair_loss + listwise_weight * list_loss + adapter_penalty
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(ranker.network.parameters(), 2.0)
            optimizer.step()
            losses.append(float(loss.detach()))
            if listwise_weight > 0:
                list_losses.append(float(list_loss.detach()))
        history.append({
            "loss": round(mean(losses), 6),
            "listwise_loss": round(mean(list_losses), 6) if list_losses else None,
        })
    ranker.network.eval()
    return ranker, {
        "pairs": len(pairs),
        "epochs": epochs,
        "enhanced_pairs": bool(config["enhanced_pairs"]),
        "listwise_weight": listwise_weight,
        "final_loss": history[-1],
        "loss_history": history,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def standardized(values: list[float]) -> list[float]:
    center = mean(values)
    variance = mean((value - center) ** 2 for value in values)
    scale = max(variance ** 0.5, 1e-6)
    return [(value - center) / scale for value in values]


def recipe_scores(
    components: dict[str, list[float]], recipe: dict[str, float]
) -> list[float]:
    channels = {name: standardized(components[name]) for name in recipe}
    return [
        sum(recipe[name] * channels[name][index] for name in recipe)
        for index in range(len(next(iter(channels.values()))))
    ]


def record_for_scores(
    group: dict[str, Any], scores: list[float]
) -> dict[str, Any]:
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
    return {
        "group_id": group["group_id"],
        "sdk_id": group["sdk_id"],
        "operation_id": group["operation_id"],
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


def evaluate_recipe(
    groups: list[dict[str, Any]],
    ranker: MultiViewEffectRanker,
    recipe: dict[str, float],
) -> list[dict[str, Any]]:
    return [
        record_for_scores(
            group, recipe_scores(ranker.group_components(group), recipe)
        )
        for group in groups
    ]


def select_recipe(
    groups: list[dict[str, Any]],
    cache: MultiViewEffectCache,
    config: dict[str, Any],
    *,
    seed: int,
    device: str,
) -> tuple[str, dict[str, Any]]:
    validation_ids = fold_assignments(groups, 4)[0]
    inner_train = [
        group for group in groups if group["independence_group"] not in validation_ids
    ]
    validation = [
        group for group in groups if group["independence_group"] in validation_ids
    ]
    ranker, training = train_ranker(
        inner_train, cache, config, seed=seed, device=device
    )
    metrics = {
        name: aggregate(evaluate_recipe(validation, ranker, recipe))
        for name, recipe in RECIPES.items()
    }

    def objective(name: str) -> tuple[float, str]:
        values = metrics[name]
        return mean([
            values["precision_at_1"], values["recall_at_5"],
            values["map"], values["ndcg_at_10"],
        ]), name

    selected = max(RECIPES, key=objective)
    return selected, {
        "validation_independence_groups": sorted(validation_ids),
        "inner_train_groups": len(inner_train),
        "validation_groups": len(validation),
        "recipe_metrics": metrics,
        "selected_recipe": selected,
        "selected_objective": round(objective(selected)[0], 6),
        "training": training,
    }


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description="评估操作条件化多视图效果排序")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-metadata", type=Path, required=True)
    parser.add_argument("--base-vectors", type=Path, required=True)
    parser.add_argument("--focused-metadata", type=Path, required=True)
    parser.add_argument("--focused-vectors", type=Path, required=True)
    parser.add_argument("--v02-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    cache = MultiViewEffectCache(
        args.base_metadata, args.base_vectors,
        args.focused_metadata, args.focused_vectors,
    )
    training_groups = [group for group in dataset["groups"] if group["role"] == "train"]
    external_groups = [group for group in dataset["groups"] if group["role"] == "external-test"]
    assignments = fold_assignments(training_groups, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []

    for fold, test_ids in enumerate(assignments, start=1):
        train = [group for group in training_groups if group["independence_group"] not in test_ids]
        test = [group for group in training_groups if group["independence_group"] in test_ids]
        config_reports = {}
        outer_rankers = {}
        for config_index, (config_name, config) in enumerate(CONFIGS.items()):
            recipe_name, selection = select_recipe(
                train, cache, config,
                seed=args.seed + fold * 100,
                device=args.device,
            )
            ranker, training = train_ranker(
                train, cache, config,
                seed=args.seed + fold * 10,
                device=args.device,
            )
            outer_rankers[config_name] = ranker
            method = f"{config_name}-calibrated"
            fold_records = evaluate_recipe(test, ranker, RECIPES[recipe_name])
            records[method].extend(fold_records)
            config_reports[config_name] = {
                "recipe_selection": selection,
                "outer_training": training,
                "outer_metrics": aggregate(fold_records),
            }
        selected_config = max(
            CONFIGS,
            key=lambda name: (
                config_reports[name]["recipe_selection"]["selected_objective"], name
            ),
        )
        selected_recipe = config_reports[selected_config]["recipe_selection"]["selected_recipe"]
        nested_records = evaluate_recipe(
            test, outer_rankers[selected_config], RECIPES[selected_recipe]
        )
        records["v0.3-nested-selected"].extend(nested_records)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "selected_config": selected_config,
            "selected_recipe": selected_recipe,
            "metrics": aggregate(nested_records),
            "configurations": config_reports,
        })
        print({
            "fold": fold,
            "selected": [selected_config, selected_recipe],
            "metrics": aggregate(nested_records),
        }, flush=True)

    final_config_reports = {}
    for config_index, (config_name, config) in enumerate(CONFIGS.items()):
        recipe_name, selection = select_recipe(
            training_groups, cache, config,
            seed=args.seed + 1000,
            device=args.device,
        )
        final_config_reports[config_name] = {
            "recipe_selection": selection,
            "selected_recipe": recipe_name,
        }
    final_config_name = max(
        CONFIGS,
        key=lambda name: (
            final_config_reports[name]["recipe_selection"]["selected_objective"], name
        ),
    )
    final_recipe_name = final_config_reports[final_config_name]["selected_recipe"]
    final_ranker, final_training = train_ranker(
        training_groups, cache, CONFIGS[final_config_name],
        seed=args.seed, device=args.device,
    )
    external_records = evaluate_recipe(
        external_groups, final_ranker, RECIPES[final_recipe_name]
    )
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_ranker.torch.save(final_ranker.state_payload(), args.output_model)

    v02 = read_json(args.v02_results)
    v02_records = v02["cross_validation"]["records"]["pretrained-code-calibrated-fusion"]
    report = {
        "schema_version": "0.3",
        "method": "operation-conditioned effect-slice multiview ranking with family hard negatives, graded listwise trials, and nested evidence calibration",
        "truth_set": dataset.get("truth_set_id", "human-engineer-2-H02"),
        "boundary": {
            "no_public_api": "excluded by the input dataset",
            "external_board_groups": "diagnostic only and excluded from all selection",
        },
        "configurations": CONFIGS,
        "recipes": RECIPES,
        "cross_validation": {
            "unit": "independence_group/vendor",
            "groups": len(training_groups),
            "metrics": {name: aggregate(items) for name, items in records.items()},
            "paired_nested_vs_v02": paired_comparison(
                records["v0.3-nested-selected"], v02_records, seed=args.seed
            ),
            "fold_reports": fold_reports,
            "records": records,
        },
        "external_board_diagnostic": {
            "groups": len(external_groups),
            "selected_config": final_config_name,
            "selected_recipe": final_recipe_name,
            "metrics": aggregate(external_records),
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "selected_config": final_config_name,
            "selected_recipe": final_recipe_name,
            "trainable_parameters": final_ranker.parameter_count(),
            "training": final_training,
            "selection": final_config_reports,
        },
        "evaluation_elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(args.output, report)
    print({
        "metrics": report["cross_validation"]["metrics"],
        "external": report["external_board_diagnostic"]["metrics"],
        "final": report["final_model"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
