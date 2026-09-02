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
    truth_set_id: str | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, Path]]:
    manifest = read_json(manifest_path)
    policy = manifest.get("training_policy", {})
    truth_sets = policy.get("truth_sets", {})
    selected_truth_set = truth_set_id or policy.get("default_truth_set")
    truth_by_sdk: dict[str, dict[str, Any]] = {}
    if selected_truth_set:
        if selected_truth_set not in truth_sets:
            raise GroundTruthError(
                f"unknown truth set {selected_truth_set!r}; available={sorted(truth_sets)}"
            )
        bundle = read_json((manifest_path.parent / truth_sets[selected_truth_set]).resolve())
        records = bundle.get("sdks", [])
        if isinstance(records, dict):
            truth_by_sdk = {
                sdk_id: {
                    "sdk_id": sdk_id,
                    "_truth_source": bundle.get("truth_source"),
                    **record,
                }
                for sdk_id, record in records.items()
            }
        else:
            truth_by_sdk = {
                record["sdk_id"]: {
                    "_truth_source": bundle.get("truth_source"),
                    **record,
                }
                for record in records
            }
    inputs = []
    for item in manifest["sdks"]:
        ir_path = latest_ir(ir_root, item["sdk_id"])
        ir = read_json(ir_path)
        if ir["sdk"]["id"] != item["sdk_id"]:
            raise GroundTruthError(f"SDK identity mismatch for {item['sdk_id']}")
        truth = truth_by_sdk.get(item["sdk_id"])
        if item.get("ground_truth"):
            truth = read_json((manifest_path.parent / item["ground_truth"]).resolve())
        if truth is not None:
            if truth["sdk_id"] != item["sdk_id"]:
                raise GroundTruthError(f"operation truth identity mismatch for {item['sdk_id']}")
            expected_revision = item.get("revision")
            if expected_revision and truth.get("source_revision") != expected_revision:
                raise GroundTruthError(
                    f"operation truth revision mismatch for {item['sdk_id']}: "
                    f"{truth.get('source_revision')} != {expected_revision}"
                )
        inputs.append((item, ir, truth, ir_path))
    return inputs


def build_operation_dataset(
    inputs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, Path]],
    hard_negatives: int = 60,
    random_negatives: int = 20,
    seed: int = 20260825,
    unretrievable_truth_policy: str = "error",
) -> dict[str, Any]:
    if unretrievable_truth_policy not in {"error", "skip-missing"}:
        raise ValueError(
            "unretrievable_truth_policy must be 'error' or 'skip-missing'"
        )
    resolver = SemanticResolver()
    groups = []
    skipped = []
    truth_alignment = []
    for manifest_item, ir, truth, _ in inputs:
        functions = {item["id"]: item for item in ir["functions"]}
        for capability, specification in CAPABILITY_SCHEMA.items():
            pool = resolver.candidate_pool(ir, capability)
            for operation in specification["operations"]:
                operation_id = f"{capability}.{operation}"
                truth_contract = truth["operations"].get(operation_id) if truth else None
                if truth_contract and truth_contract.get("group_status") not in {
                    None, "complete"
                }:
                    skipped.append({
                        "sdk_id": ir["sdk"]["id"],
                        "operation": operation_id,
                        "reason": truth_contract["group_status"],
                    })
                    continue
                if truth_contract and not truth_contract.get("supported", True):
                    skipped.append({"sdk_id": ir["sdk"]["id"], "operation": operation_id, "reason": "not-supported"})
                    continue
                primary_truth = set(truth_contract.get("symbols", [])) if truth_contract else set()
                alternative_truth = set(
                    truth_contract.get("alternative_symbols", [])
                ) if truth_contract else set()
                related_truth = set(
                    truth_contract.get("related_symbols", [])
                ) if truth_contract else set()
                truth_symbols = primary_truth | alternative_truth | related_truth
                rows = []
                for candidate in pool:
                    function = functions[candidate["entity_id"]]
                    features = operation_feature_map(capability, operation, candidate, function)
                    if truth is not None:
                        if candidate["symbol"] in primary_truth:
                            label = 3
                            label_evidence = ["truth-set-grade-3-symbol"]
                            label_confidence = 1.0
                        elif candidate["symbol"] in alternative_truth:
                            label = 2
                            label_evidence = ["truth-set-grade-2-symbol"]
                            label_confidence = 0.95
                        elif candidate["symbol"] in related_truth:
                            label = 1
                            label_evidence = ["truth-set-grade-1-symbol"]
                            label_confidence = 0.9
                        else:
                            label = 0
                            label_evidence = ["not-positive-in-selected-truth-set"]
                            label_confidence = 1.0
                    else:
                        label, label_evidence, label_confidence = graded_relevance(features)
                    rows.append({
                        "entity_id": candidate["entity_id"],
                        "symbol": candidate["symbol"],
                        "file": function["file"],
                        "line": function["line"],
                        "label": label,
                        "label_source": truth.get(
                            "_truth_source", "source-audited"
                        ) if truth is not None else "auditable-graded-supervision",
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
                        alignment = {
                            "sdk_id": ir["sdk"]["id"],
                            "operation": operation_id,
                            "missing_symbols": missing,
                            "recovered_symbols": sorted(recovered),
                            "policy": unretrievable_truth_policy,
                        }
                        truth_alignment.append(alignment)
                        if unretrievable_truth_policy == "error":
                            raise GroundTruthError(
                                f"unretrievable operation truth for "
                                f"{ir['sdk']['id']}/{operation_id}: {missing}"
                            )
                        if not positives:
                            skipped.append({
                                "sdk_id": ir["sdk"]["id"],
                                "operation": operation_id,
                                "reason": "unretrievable-positive-label",
                                "missing_symbols": missing,
                            })
                            continue
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
                group_rng = random.Random(
                    f"{seed}:{ir['sdk']['id']}:{operation_id}"
                )
                easy = group_rng.sample(
                    easy_pool, min(random_negatives, len(easy_pool))
                )
                selected = positives + hard + easy
                group_rng.shuffle(selected)
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
            "unretrievable_truth_policy": unretrievable_truth_policy,
            "randomization_scope": "per-sdk-operation-group",
        },
        "summary": {
            "sdks": len({item["sdk_id"] for item in groups}),
            "training_sdks": len({item["sdk_id"] for item in groups if item["role"] == "train"}),
            "training_independence_groups": len({item["independence_group"] for item in groups if item["role"] == "train"}),
            "groups": len(groups),
            "candidates": sum(len(item["candidates"]) for item in groups),
            "positive_candidates": sum(candidate["label"] > 0 for item in groups for candidate in item["candidates"]),
            "truth_alignment_groups": len(truth_alignment),
            "unretrievable_truth_symbols": sum(
                len(item["missing_symbols"]) for item in truth_alignment
            ),
            "groups_by_role": {role: sum(item["role"] == role for item in groups) for role in roles},
            "skipped_groups": len(skipped),
        },
        "truth_alignment": truth_alignment,
        "skipped": skipped,
        "groups": groups,
    }
