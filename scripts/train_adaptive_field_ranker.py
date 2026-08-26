#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.adaptive_field_ranker import AdaptiveFieldRanker
from bspforge.common import read_json, write_json
from evaluate_operation_ranker import METRICS, ranking_metrics


def aggregate(groups: list[dict[str, Any]], ranker: AdaptiveFieldRanker) -> dict[str, float]:
    records = [ranking_metrics(group["candidates"], ranker.predict(group)) for group in groups]
    return {name: round(mean(item[name] for item in records), 6) for name in METRICS}


def curriculum_pairs(
    group: dict[str, Any], epoch: int, epochs: int, seed: int, limit: int = 48
) -> list[tuple[int, int, float]]:
    candidates = group["candidates"]
    positives = [index for index, item in enumerate(candidates) if item["label"] > 0]
    lower = sorted(
        range(len(candidates)),
        key=lambda index: (
            -float(candidates[index]["features"].get("multi-channel-rrf", 0.0)),
            candidates[index]["entity_id"],
        ),
    )
    progress = epoch / max(1, epochs - 1)
    pairs = []
    rng = random.Random(seed + epoch * 1009 + sum(ord(item) for item in group["group_id"]))
    for positive in positives:
        valid = [
            index for index in lower
            if candidates[index]["label"] < candidates[positive]["label"]
        ]
        if not valid:
            continue
        hard_count = max(2, round(2 + 8 * progress))
        hard = valid[:hard_count]
        easy_pool = valid[hard_count:]
        easy = rng.sample(easy_pool, min(max(1, 5 - hard_count // 2), len(easy_pool)))
        for negative in hard + easy:
            grade_gap = candidates[positive]["label"] - candidates[negative]["label"]
            confidence = min(
                float(candidates[positive].get("label_confidence", 1.0)),
                float(candidates[negative].get("label_confidence", 1.0)),
            )
            pairs.append((positive, negative, confidence * max(1.0, grade_gap)))
    rng.shuffle(pairs)
    return pairs[:limit]


def group_loss(
    ranker: AdaptiveFieldRanker,
    group: dict[str, Any],
    epoch: int,
    epochs: int,
    seed: int,
) -> Any:
    torch = ranker.torch
    scores = ranker.score_tensor(group)
    labels = torch.tensor(
        [float(item["label"]) for item in group["candidates"]],
        dtype=torch.float32,
        device=ranker.device,
    )
    gains = torch.pow(2.0, labels) - 1.0
    target = gains / gains.sum().clamp_min(1.0)
    listwise = -(target * torch.log_softmax(scores, dim=0)).sum()
    pairs = curriculum_pairs(group, epoch, epochs, seed)
    if pairs:
        positive = torch.tensor([item[0] for item in pairs], dtype=torch.long, device=ranker.device)
        negative = torch.tensor([item[1] for item in pairs], dtype=torch.long, device=ranker.device)
        weights = torch.tensor([item[2] for item in pairs], dtype=torch.float32, device=ranker.device)
        pairwise = (torch.nn.functional.softplus(-(scores[positive] - scores[negative])) * weights).mean()
    else:
        pairwise = scores.sum() * 0.0
    return listwise + (0.35 + 0.35 * epoch / max(1, epochs - 1)) * pairwise


def main() -> int:
    parser = argparse.ArgumentParser(description="训练能力自适应字段门控排序器")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--learning-rate", type=float, default=0.008)
    parser.add_argument("--weight-decay", type=float, default=0.002)
    parser.add_argument("--patience", type=int, default=14)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    development_ids = set(read_json(args.split)["development_groups"])
    training = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] not in development_ids
    ]
    development = [
        item for item in dataset["groups"]
        if item["role"] == "train" and item["independence_group"] in development_ids
    ]
    external_ids = sorted({
        item["sdk_id"] for item in dataset["groups"] if item["role"] == "external-test"
    })
    random.seed(args.seed)
    import torch
    torch.manual_seed(args.seed)
    ranker = AdaptiveFieldRanker(device=args.device)
    optimizer = torch.optim.AdamW(
        ranker.network.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    history = []
    best_map = -math.inf
    best_state = None
    stale = 0
    for epoch in range(args.epochs):
        ranker.network.train()
        random.Random(args.seed + epoch).shuffle(training)
        losses = []
        optimizer.zero_grad()
        for index, group in enumerate(training, start=1):
            loss = group_loss(ranker, group, epoch, args.epochs, args.seed) / 8.0
            loss.backward()
            losses.append(float(loss.detach()) * 8.0)
            if index % 8 == 0 or index == len(training):
                torch.nn.utils.clip_grad_norm_(ranker.network.parameters(), 2.0)
                optimizer.step()
                optimizer.zero_grad()
        ranker.network.eval()
        metrics = aggregate(development, ranker)
        history.append({"epoch": epoch + 1, "loss": round(mean(losses), 6), "development": metrics})
        if metrics["map"] > best_map + 1e-5:
            best_map = metrics["map"]
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in ranker.network.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
        if stale >= args.patience:
            break
    if best_state is None:
        raise RuntimeError("adaptive ranker training produced no checkpoint")
    ranker.network.load_state_dict(best_state)
    ranker.network.eval()
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ranker.state_payload(), args.output_model)
    report = {
        "schema_version": "1.0",
        "method": "frozen MiniLM field scores with capability-adaptive gates, graded listwise loss and curriculum hard negatives",
        "seed": args.seed,
        "parameters": ranker.parameter_count(),
        "training_groups": len(training),
        "development_groups": len(development),
        "training_independence_groups": sorted({item["independence_group"] for item in training}),
        "development_independence_groups": sorted(development_ids),
        "excluded_external_sdks": external_ids,
        "epochs_completed": len(history),
        "best_epoch": max(history, key=lambda item: item["development"]["map"])["epoch"],
        "development": aggregate(development, ranker),
        "history": history,
        "learned_gates": ranker.gate_report(),
    }
    write_json(args.report, report)
    print({key: report[key] for key in ("parameters", "epochs_completed", "best_epoch", "development")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
