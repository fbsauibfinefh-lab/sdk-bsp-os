#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.hardware_effect_graph import hard_constraint_penalty, hardware_heuristic_score
from bspforge.hardware_effect_ranker import HardwareEffectPURanker, OPERATION_INDEX
from bspforge.structured_retrieval import complete_structured_scores
from evaluate_operation_ranker import METRICS, ranking_metrics


def aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {
        metric: round(mean(item["metrics"][metric] for item in records), 6)
        for metric in METRICS
    }


def paired_comparison(
    challenger: list[dict[str, Any]], baseline: list[dict[str, Any]], *, seed: int
) -> dict[str, Any]:
    baseline_by_group = {item["group_id"]: item for item in baseline}
    pairs = [
        (item, baseline_by_group[item["group_id"]])
        for item in challenger
        if item["group_id"] in baseline_by_group
    ]
    rng = random.Random(seed)
    output = {}
    for metric in METRICS:
        differences = [
            left["metrics"][metric] - right["metrics"][metric]
            for left, right in pairs
        ]
        bootstrap = []
        for _ in range(4000):
            bootstrap.append(mean(rng.choice(differences) for _ in differences))
        bootstrap.sort()
        wins = sum(item > 1e-12 for item in differences)
        losses = sum(item < -1e-12 for item in differences)
        output[metric] = {
            "mean_difference": round(mean(differences), 6),
            "bootstrap_95_ci": [
                round(bootstrap[int(0.025 * len(bootstrap))], 6),
                round(bootstrap[int(0.975 * len(bootstrap))], 6),
            ],
            "wins_ties_losses": [wins, len(differences) - wins - losses, losses],
        }
    return {"paired_groups": len(pairs), "metrics": output}


def _unique_indices(group: dict[str, Any], *, positive: bool) -> list[int]:
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


def preference_pairs(
    groups: list[dict[str, Any]], seed: int, hard_limit: int = 8, random_limit: int = 8
) -> list[tuple[dict[str, Any], int, int, float]]:
    pairs = []
    for group in groups:
        positives = _unique_indices(group, positive=True)
        unlabeled = _unique_indices(group, positive=False)
        ranked_unlabeled = sorted(
            unlabeled,
            key=lambda index: (
                -hardware_heuristic_score(group["candidates"][index]),
                group["candidates"][index]["entity_id"],
            ),
        )
        hard = ranked_unlabeled[:hard_limit]
        remaining = ranked_unlabeled[hard_limit:]
        rng = random.Random(f"{seed}:{group['group_id']}")
        sampled = rng.sample(remaining, min(random_limit, len(remaining)))
        for positive in positives:
            confidence = float(group["candidates"][positive].get("label_confidence", 1.0))
            for unlabeled_index in hard + sampled:
                # High-scoring unlabeled APIs are more likely to be missing positives,
                # so their preference constraint receives a smaller PU confidence.
                unlabeled_score = hardware_heuristic_score(group["candidates"][unlabeled_index])
                weight = confidence * (0.35 + 0.45 * max(0.0, 1.0 - unlabeled_score))
                pairs.append((group, positive, unlabeled_index, weight))
    return pairs


def train_ranker(
    groups: list[dict[str, Any]], *, seed: int, epochs: int, device: str
) -> tuple[HardwareEffectPURanker, dict[str, Any]]:
    import torch

    random.seed(seed)
    torch.manual_seed(seed)
    ranker = HardwareEffectPURanker(device=device)
    ranker.fit_scaler([candidate for group in groups for candidate in group["candidates"]])
    pairs = preference_pairs(groups, seed)
    optimizer = torch.optim.AdamW(
        ranker.network.parameters(), lr=0.006, weight_decay=0.004
    )
    history = []
    for epoch in range(epochs):
        order = list(range(len(pairs)))
        random.Random(seed + epoch).shuffle(order)
        losses = []
        for start in range(0, len(order), 192):
            batch = [pairs[index] for index in order[start : start + 192]]
            positive_features = ranker.feature_tensor(
                [group["candidates"][positive] for group, positive, _, _ in batch]
            )
            unlabeled_features = ranker.feature_tensor(
                [group["candidates"][unlabeled] for group, _, unlabeled, _ in batch]
            )
            operations = torch.tensor(
                [
                    OPERATION_INDEX[group["operation_id"]]
                    for group, _, _, _ in batch
                ],
                dtype=torch.long,
                device=device,
            )
            weights = torch.tensor(
                [weight for _, _, _, weight in batch], dtype=torch.float32, device=device
            )
            positive_scores = ranker.network(positive_features, operations)
            unlabeled_scores = ranker.network(unlabeled_features, operations)
            loss = (
                torch.nn.functional.softplus(-(positive_scores - unlabeled_scores)) * weights
            ).mean()
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
    }


def protected_hardware_scores(group: dict[str, Any], *, transitive: bool) -> list[float]:
    return [
        hardware_heuristic_score(candidate, transitive=transitive)
        - 4.0 * hard_constraint_penalty(candidate)
        for candidate in group["candidates"]
    ]


def standardized(values: list[float]) -> list[float]:
    center = mean(values)
    variance = mean((item - center) ** 2 for item in values)
    scale = max(variance ** 0.5, 1e-6)
    return [(item - center) / scale for item in values]


def evaluate_group(
    group: dict[str, Any], ranker: HardwareEffectPURanker
) -> dict[str, dict[str, Any]]:
    learned = ranker.predict(group, protect=False)
    graph_raw = [hardware_heuristic_score(candidate) for candidate in group["candidates"]]
    graph_calibrated = standardized(graph_raw)
    protected_learned = [
        score - 4.0 * hard_constraint_penalty(candidate)
        for score, candidate in zip(learned, group["candidates"], strict=True)
    ]
    residual_scores = [
        score + 0.35 * graph_score - 4.0 * hard_constraint_penalty(candidate)
        for score, graph_score, candidate in zip(
            learned, graph_calibrated, group["candidates"], strict=True
        )
    ]
    methods = {
        "body-effect-heuristic": protected_hardware_scores(group, transitive=False),
        "graph-effect-heuristic": protected_hardware_scores(group, transitive=True),
        "hardware-effect-pu-ranker": protected_learned,
        "hardware-effect-pu-residual": residual_scores,
        "existing-q4": complete_structured_scores(group)[0],
    }
    output = {}
    for method, scores in methods.items():
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


def fold_assignments(groups: list[dict[str, Any]], folds: int) -> list[set[str]]:
    counts: dict[str, int] = defaultdict(int)
    for group in groups:
        counts[group["independence_group"]] += 1
    buckets: list[tuple[int, set[str]]] = [(0, set()) for _ in range(folds)]
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        index = min(range(folds), key=lambda item: buckets[item][0])
        total, names = buckets[index]
        names.add(name)
        buckets[index] = total + count, names
    return [names for _, names in buckets]


def main() -> int:
    parser = argparse.ArgumentParser(description="评估寄存器效果图与H02正例-未标注偏好排序")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=36)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    training_groups = [item for item in dataset["groups"] if item["role"] == "train"]
    external_groups = [item for item in dataset["groups"] if item["role"] == "external-test"]
    assignments = fold_assignments(training_groups, args.folds)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fold_reports = []
    for fold, test_ids in enumerate(assignments, start=1):
        train = [item for item in training_groups if item["independence_group"] not in test_ids]
        test = [item for item in training_groups if item["independence_group"] in test_ids]
        ranker, training_report = train_ranker(
            train, seed=args.seed + fold, epochs=args.epochs, device=args.device
        )
        fold_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for group in test:
            evaluated = evaluate_group(group, ranker)
            for method, result in evaluated.items():
                record = {
                    "group_id": group["group_id"],
                    "sdk_id": group["sdk_id"],
                    "operation_id": group["operation_id"],
                    **result,
                }
                records[method].append(record)
                fold_records[method].append(record)
        fold_reports.append({
            "fold": fold,
            "test_independence_groups": sorted(test_ids),
            "train_groups": len(train),
            "test_groups": len(test),
            "training": training_report,
            "metrics": {method: aggregate(items) for method, items in fold_records.items()},
        })
        print({"fold": fold, "test": sorted(test_ids), "metrics": fold_reports[-1]["metrics"]}, flush=True)

    final_ranker, final_training = train_ranker(
        training_groups, seed=args.seed, epochs=args.epochs, device=args.device
    )
    external_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in external_groups:
        for method, result in evaluate_group(group, final_ranker).items():
            external_records[method].append({
                "group_id": group["group_id"],
                "sdk_id": group["sdk_id"],
                "operation_id": group["operation_id"],
                **result,
            })
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    final_ranker.torch.save(final_ranker.state_payload(), args.output_model)

    by_sdk = {}
    for sdk_id in sorted({item["sdk_id"] for items in records.values() for item in items}):
        by_sdk[sdk_id] = {
            method: aggregate([item for item in items if item["sdk_id"] == sdk_id])
            for method, items in records.items()
        }
    report = {
        "schema_version": "0.1",
        "truth_set": dataset.get("truth_set_id", "human-engineer-2-H02"),
        "method": "standalone register-anchored interprocedural graph with hard-protected PU pairwise ranking",
        "positive_unlabeled_policy": {
            "positive": "label > 0; grades are not ordered during training",
            "unlabeled": "label == 0; sampled as lower-preference with reduced confidence, not asserted semantic negatives",
            "pair_contract": "within one query, an audited positive should rank above sampled unlabeled candidates",
        },
        "feature_boundary": "only hardware-effect graph features plus hard conflict penalties; no q4 soft score or field score is used by the learned ranker",
        "cross_validation": {
            "unit": "independence_group/vendor",
            "folds": args.folds,
            "groups": len(training_groups),
            "sdks": len({item["sdk_id"] for item in training_groups}),
            "metrics": {method: aggregate(items) for method, items in records.items()},
            "paired_vs_existing_q4": paired_comparison(
                records["hardware-effect-pu-residual"], records["existing-q4"], seed=args.seed
            ),
            "fold_reports": fold_reports,
            "by_sdk": by_sdk,
            "records": records,
        },
        "external_board_diagnostic": {
            "excluded_from_training": True,
            "groups": len(external_groups),
            "sdks": sorted({item["sdk_id"] for item in external_groups}),
            "metrics": {
                method: aggregate(items) for method, items in external_records.items()
            },
            "records": external_records,
        },
        "final_model": {
            "path": str(args.output_model),
            "parameters": final_ranker.parameter_count(),
            "training": final_training,
        },
    }
    write_json(args.output, report)
    print({
        "cross_validation": report["cross_validation"]["metrics"],
        "external": report["external_board_diagnostic"]["metrics"],
        "parameters": report["final_model"]["parameters"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
