#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean
from typing import Any

from bspforge.common import read_json, write_json
from bspforge.structured_retrieval import complete_structured_scores


def top_index(group: dict[str, Any], scores: list[float]) -> int:
    return max(
        range(len(scores)),
        key=lambda index: (scores[index], group["candidates"][index]["entity_id"]),
    )


def unique_margin(
    group: dict[str, Any], scores: list[float], selected_index: int
) -> float:
    selected_symbol = group["candidates"][selected_index]["symbol"]
    alternatives = [
        score for candidate, score in zip(group["candidates"], scores, strict=True)
        if candidate["symbol"] != selected_symbol
    ]
    return scores[selected_index] - max(alternatives, default=0.0)


def record(group: dict[str, Any]) -> dict[str, Any]:
    candidates = group["candidates"]
    final_scores, diagnostics = complete_structured_scores(group)
    final_top = top_index(group, final_scores)
    static = [float(item["static_score"]) for item in candidates]
    field = [float(item["features"].get("field-late-interaction", 0.0)) for item in candidates]
    contract = [float(item["features"].get("operation-contract-retrieval", 0.0)) for item in candidates]
    layer = [float(item["features"].get("layer-route-score", 0.0)) for item in candidates]
    rrf = [float(item["features"].get("multi-channel-rrf", 0.0)) for item in candidates]
    precision = [0.5 * left + 0.5 * semantic for left, semantic in zip(static, field, strict=True)]
    hierarchy = [
        0.25 * left + 0.25 * semantic + 0.25 * rule + 0.25 * route
        for left, semantic, rule, route in zip(static, field, contract, layer, strict=True)
    ]
    contract_fusion = [
        0.35 * left + 0.35 * semantic + 0.30 * rule
        for left, semantic, rule in zip(static, field, contract, strict=True)
    ]
    channels = {
        "static": static,
        "field": field,
        "contract": contract,
        "layer": layer,
        "rrf": rrf,
        "precision": precision,
        "hierarchy": hierarchy,
        "contract_fusion": contract_fusion,
    }
    channel_tops = {name: top_index(group, values) for name, values in channels.items()}
    selected = candidates[final_top]
    selected_family = selected.get("api_family")
    entity_agreement = mean(index == final_top for index in channel_tops.values())
    family_agreement = mean(
        candidates[index].get("api_family") == selected_family
        for index in channel_tops.values()
    )
    decision_scores = hierarchy if diagnostics["leader_fallback"] else precision
    features = selected["features"]
    ranked = sorted(
        range(len(candidates)),
        key=lambda index: (-final_scores[index], candidates[index]["entity_id"]),
    )
    unique = []
    seen_symbols = set()
    for index in ranked:
        candidate = candidates[index]
        if candidate["symbol"] in seen_symbols:
            continue
        seen_symbols.add(candidate["symbol"])
        unique.append({
            "symbol": candidate["symbol"],
            "label": candidate["label"],
            "file": candidate["file"],
            "source_role": candidate.get("source_role"),
            "api_family": candidate.get("api_family"),
            "static": round(static[index], 6),
            "field": round(field[index], 6),
            "contract": round(contract[index], 6),
            "layer": round(layer[index], 6),
            "rrf": round(rrf[index], 6),
            "precision": round(precision[index], 6),
            "hierarchy": round(hierarchy[index], 6),
        })
        if len(unique) == 10:
            break
    return {
        "group_id": group["group_id"],
        "sdk_id": group["sdk_id"],
        "operation_id": group["operation_id"],
        "capability": group["capability"],
        "top_symbol": selected["symbol"],
        "top_label": selected["label"],
        "correct": int(selected["label"] > 0),
        "candidate_count": len(candidates),
        "fallback": diagnostics["leader_fallback"],
        "source_role": selected.get("source_role"),
        "api_family": selected_family,
        "decision_margin": round(unique_margin(group, decision_scores, final_top), 6),
        "precision_margin": round(unique_margin(group, precision, final_top), 6),
        "hierarchy_margin": round(unique_margin(group, hierarchy, final_top), 6),
        "entity_agreement": round(entity_agreement, 6),
        "family_agreement": round(family_agreement, 6),
        "static": round(static[final_top], 6),
        "field": round(field[final_top], 6),
        "contract": round(contract[final_top], 6),
        "layer": round(layer[final_top], 6),
        "rrf": round(rrf[final_top], 6),
        "role": round(float(features.get("source-role-prior", 0.0)), 6),
        "operation_exact": round(float(features.get("operation-exact", 0.0)), 6),
        "operation_substring": round(float(features.get("operation-substring", 0.0)), 6),
        "parameterized_toggle": round(float(features.get("parameterized-toggle", 0.0)), 6),
        "opposite_action": round(float(features.get("opposite-action", 0.0)), 6),
        "channel_top_symbols": {
            name: candidates[index]["symbol"] for name, index in channel_tops.items()
        },
        "top_candidates": unique,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="分析确定性 q4 首位的置信证据")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--role", default="external-test")
    parser.add_argument("--split", type=Path)
    parser.add_argument(
        "--partition", choices=("all", "development", "training"), default="all"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    groups = [group for group in dataset["groups"] if group["role"] == args.role]
    if args.partition != "all":
        if args.split is None:
            parser.error("--partition development/training requires --split")
        development = set(read_json(args.split)["development_groups"])
        groups = [
            group for group in groups
            if (group["independence_group"] in development)
            == (args.partition == "development")
        ]
    records = [record(group) for group in groups]
    correct = [item for item in records if item["correct"]]
    errors = [item for item in records if not item["correct"]]
    summary = {
        "groups": len(records),
        "correct": len(correct),
        "errors": len(errors),
        "precision_at_1": round(len(correct) / len(records), 6),
        "means": {
            field: {
                "correct": round(mean(item[field] for item in correct), 6) if correct else None,
                "error": round(mean(item[field] for item in errors), 6) if errors else None,
            }
            for field in (
                "decision_margin", "precision_margin", "hierarchy_margin",
                "entity_agreement", "family_agreement", "static", "field",
                "contract", "layer", "rrf", "role",
            )
        },
    }
    write_json(args.output, {"summary": summary, "records": records})
    print(summary)
    for item in errors:
        print({key: item[key] for key in (
            "group_id", "top_symbol", "fallback", "source_role", "decision_margin",
            "entity_agreement", "family_agreement", "contract", "layer", "role",
        )})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
