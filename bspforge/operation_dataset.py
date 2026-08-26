from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.common import read_json, utc_now
from bspforge.operation_ranking import (
    candidate_code_text,
    operation_feature_map,
    operation_query_text,
    operation_static_score,
    graded_relevance,
)
from bspforge.ranking_dataset import GroundTruthError, latest_ir
from bspforge.semantic_resolver import SemanticResolver


def load_operation_inputs(
    manifest_path: Path,
    ir_root: Path,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, Path]]:
    manifest = read_json(manifest_path)
    inputs = []
    for item in manifest["sdks"]:
        ir_path = latest_ir(ir_root, item["sdk_id"])
        ir = read_json(ir_path)
        if ir["sdk"]["id"] != item["sdk_id"]:
            raise GroundTruthError(f"SDK identity mismatch for {item['sdk_id']}")
        truth = None
        if item.get("ground_truth"):
            truth = read_json((manifest_path.parent / item["ground_truth"]).resolve())
            if truth["sdk_id"] != item["sdk_id"]:
                raise GroundTruthError(f"operation truth identity mismatch for {item['sdk_id']}")
        inputs.append((item, ir, truth, ir_path))
    return inputs


def build_operation_dataset(
    inputs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, Path]],
    hard_negatives: int = 60,
    random_negatives: int = 20,
    seed: int = 20260825,
) -> dict[str, Any]:
    resolver = SemanticResolver()
    rng = random.Random(seed)
    groups = []
    skipped = []
    for manifest_item, ir, truth, _ in inputs:
        functions = {item["id"]: item for item in ir["functions"]}
        for capability, specification in CAPABILITY_SCHEMA.items():
            pool = resolver.candidate_pool(ir, capability)
            for operation in specification["operations"]:
                operation_id = f"{capability}.{operation}"
                truth_contract = truth["operations"].get(operation_id) if truth else None
                if truth_contract and not truth_contract.get("supported", True):
                    skipped.append({"sdk_id": ir["sdk"]["id"], "operation": operation_id, "reason": "not-supported"})
                    continue
                primary_truth = set(truth_contract.get("symbols", [])) if truth_contract else set()
                alternative_truth = set(
                    truth_contract.get("alternative_symbols", [])
                ) if truth_contract else set()
                truth_symbols = primary_truth | alternative_truth
                rows = []
                for candidate in pool:
                    function = functions[candidate["entity_id"]]
                    features = operation_feature_map(capability, operation, candidate, function)
                    if truth is not None:
                        if candidate["symbol"] in primary_truth:
                            label = 3
                            label_evidence = ["source-audited-primary-symbol"]
                            label_confidence = 1.0
                        elif candidate["symbol"] in alternative_truth:
                            label = 2
                            label_evidence = ["source-audited-alternative-symbol"]
                            label_confidence = 0.95
                        else:
                            label = 0
                            label_evidence = ["not-in-source-audited-truth"]
                            label_confidence = 1.0
                    else:
                        label, label_evidence, label_confidence = graded_relevance(features)
                    rows.append({
                        "entity_id": candidate["entity_id"],
                        "symbol": candidate["symbol"],
                        "file": function["file"],
                        "line": function["line"],
                        "label": label,
                        "label_source": "source-audited" if truth is not None else "auditable-graded-supervision",
                        "label_evidence": label_evidence,
                        "label_confidence": label_confidence,
                        "static_score": operation_static_score(features),
                        "features": features,
                        "candidate_text": candidate_code_text(function),
                    })
                positives = [item for item in rows if item["label"] > 0]
                if truth_symbols:
                    recovered = {item["symbol"] for item in positives}
                    missing = sorted(truth_symbols - recovered)
                    if missing:
                        raise GroundTruthError(
                            f"unretrievable operation truth for {ir['sdk']['id']}/{operation_id}: {missing}"
                        )
                if not positives:
                    skipped.append({"sdk_id": ir["sdk"]["id"], "operation": operation_id, "reason": "no-positive-label"})
                    continue
                positives.sort(key=lambda item: (-item["static_score"], item["entity_id"]))
                if truth is None:
                    positives = positives[:6]
                negatives = sorted(
                    (item for item in rows if item["label"] == 0),
                    key=lambda item: (-item["static_score"], item["entity_id"]),
                )
                hard = negatives[:hard_negatives]
                easy_pool = negatives[hard_negatives:]
                easy = rng.sample(easy_pool, min(random_negatives, len(easy_pool)))
                selected = positives + hard + easy
                rng.shuffle(selected)
                groups.append({
                    "group_id": f"{ir['sdk']['id']}::{operation_id}",
                    "sdk_id": ir["sdk"]["id"],
                    "vendor": manifest_item["vendor"],
                    "independence_group": manifest_item["independence_group"],
                    "role": manifest_item["role"],
                    "capability": capability,
                    "operation": operation,
                    "operation_id": operation_id,
                    "query_text": operation_query_text(capability, operation),
                    "truth_symbols": sorted(truth_symbols),
                    "candidate_pool_size": len(pool),
                    "candidates": selected,
                })
    roles = sorted({item["role"] for item in groups})
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "sampling": {
            "seed": seed,
            "hard_negatives_per_group": hard_negatives,
            "random_negatives_per_group": random_negatives,
            "graded_positive_limit": 6,
        },
        "summary": {
            "sdks": len({item["sdk_id"] for item in groups}),
            "training_sdks": len({item["sdk_id"] for item in groups if item["role"] == "train"}),
            "training_independence_groups": len({item["independence_group"] for item in groups if item["role"] == "train"}),
            "groups": len(groups),
            "candidates": sum(len(item["candidates"]) for item in groups),
            "positive_candidates": sum(candidate["label"] > 0 for item in groups for candidate in item["candidates"]),
            "groups_by_role": {role: sum(item["role"] == role for item in groups) for role in roles},
            "skipped_groups": len(skipped),
        },
        "skipped": skipped,
        "groups": groups,
    }
