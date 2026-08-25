from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from bspforge.common import read_json, utc_now
from bspforge.semantic_resolver import SemanticResolver
from bspforge.semantic_resolver.learning import candidate_feature_map


class GroundTruthError(ValueError):
    pass


def latest_ir(ir_root: Path, sdk_id: str) -> Path:
    matches = sorted(
        (ir_root / sdk_id).glob("*/sdk-ir.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.as_posix()),
    )
    if not matches:
        raise FileNotFoundError(f"missing IR for {sdk_id} under {ir_root}")
    return matches[-1]


def load_experiment_inputs(
    manifest_path: Path,
    ir_root: Path,
) -> list[tuple[dict[str, Any], dict[str, Any], Path]]:
    manifest = read_json(manifest_path)
    inputs = []
    for item in manifest["sdks"]:
        truth_path = (manifest_path.parent / item["ground_truth"]).resolve()
        ir_path = latest_ir(ir_root, item["sdk_id"])
        truth = read_json(truth_path)
        ir = read_json(ir_path)
        if truth["sdk"]["id"] != item["sdk_id"] or ir["sdk"]["id"] != item["sdk_id"]:
            raise GroundTruthError(f"SDK identity mismatch for {item['sdk_id']}")
        inputs.append((ir, truth, ir_path))
    return inputs


def audit_ground_truth(
    inputs: list[tuple[dict[str, Any], dict[str, Any], Path]],
) -> dict[str, Any]:
    resolver = SemanticResolver()
    sdk_reports = []
    total_symbols = 0
    missing_symbols = 0
    unretrievable_symbols = 0
    for ir, truth, ir_path in inputs:
        by_name: dict[str, list[dict[str, Any]]] = {}
        for function in ir["functions"]:
            by_name.setdefault(function["name"], []).append(function)
        capability_reports = []
        for capability, contract in truth["capabilities"].items():
            if not contract.get("supported", True):
                continue
            pool = resolver.candidate_pool(ir, capability)
            retrievable = {item["symbol"] for item in pool}
            symbol_reports = []
            for symbol in contract.get("semantic_symbols", []):
                definitions = by_name.get(symbol, [])
                total_symbols += 1
                missing_symbols += not definitions
                unretrievable_symbols += bool(definitions) and symbol not in retrievable
                symbol_reports.append({
                    "symbol": symbol,
                    "definition_count": len(definitions),
                    "retrievable": symbol in retrievable,
                    "evidence": [
                        {
                            "file": item["file"],
                            "line": item["line"],
                            "parser": item.get("parser"),
                            "parser_confidence": item.get("parser_confidence"),
                        }
                        for item in definitions[:5]
                    ],
                })
            capability_reports.append({
                "capability": capability,
                "truth_symbols": len(symbol_reports),
                "candidate_pool": len(pool),
                "symbols": symbol_reports,
            })
        sdk_reports.append({
            "sdk_id": ir["sdk"]["id"],
            "sdk_digest": ir["sdk"]["digest"],
            "ir_path": str(ir_path),
            "functions": len(ir["functions"]),
            "capabilities": capability_reports,
        })
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "summary": {
            "sdks": len(sdk_reports),
            "truth_symbols": total_symbols,
            "missing_symbols": missing_symbols,
            "unretrievable_symbols": unretrievable_symbols,
            "passed": missing_symbols == 0 and unretrievable_symbols == 0,
        },
        "sdks": sdk_reports,
    }


def build_ranking_dataset(
    inputs: list[tuple[dict[str, Any], dict[str, Any], Path]],
    hard_negatives: int = 80,
    random_negatives: int = 40,
    positive_instances: int = 3,
    seed: int = 20260825,
) -> dict[str, Any]:
    resolver = SemanticResolver()
    rng = random.Random(seed)
    groups = []
    for ir, truth, _ in inputs:
        functions = {item["id"]: item for item in ir["functions"]}
        for capability, contract in truth["capabilities"].items():
            if not contract.get("supported", True):
                continue
            relevant = set(contract.get("semantic_symbols", []))
            if not relevant:
                continue
            pool = resolver.candidate_pool(ir, capability)
            positives_by_symbol: dict[str, list[dict[str, Any]]] = {}
            negatives = []
            for candidate in pool:
                if candidate["symbol"] in relevant:
                    positives_by_symbol.setdefault(candidate["symbol"], []).append(candidate)
                else:
                    negatives.append(candidate)
            absent = sorted(relevant.difference(positives_by_symbol))
            if absent:
                raise GroundTruthError(
                    f"unretrievable truth symbols for {ir['sdk']['id']}/{capability}: {absent}"
                )
            positives = []
            for symbol in sorted(positives_by_symbol):
                ranked = sorted(
                    positives_by_symbol[symbol],
                    key=lambda item: (
                        -float(functions[item["entity_id"]].get("parser_confidence", 0.0)),
                        len(functions[item["entity_id"]]["file"]),
                        item["entity_id"],
                    ),
                )
                positives.extend(ranked[:positive_instances])
            hard = negatives[:hard_negatives]
            hard_ids = {item["entity_id"] for item in hard}
            easy_pool = [item for item in negatives[hard_negatives:] if item["entity_id"] not in hard_ids]
            easy = rng.sample(easy_pool, min(random_negatives, len(easy_pool)))
            selected = positives + hard + easy
            rng.shuffle(selected)
            candidates = []
            for candidate in selected:
                function = functions[candidate["entity_id"]]
                candidates.append({
                    "entity_id": candidate["entity_id"],
                    "symbol": candidate["symbol"],
                    "file": function["file"],
                    "line": function["line"],
                    "label": 2 if candidate["symbol"] in relevant else 0,
                    "baseline_score": candidate["score"],
                    "features": candidate_feature_map(candidate, function),
                })
            groups.append({
                "group_id": f"{ir['sdk']['id']}::{capability}",
                "sdk_id": ir["sdk"]["id"],
                "sdk_digest": ir["sdk"]["digest"],
                "capability": capability,
                "truth_symbols": sorted(relevant),
                "candidate_pool_size": len(pool),
                "candidates": candidates,
            })
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "sampling": {
            "seed": seed,
            "hard_negatives_per_group": hard_negatives,
            "random_negatives_per_group": random_negatives,
            "positive_instances_per_symbol": positive_instances,
        },
        "summary": {
            "sdks": len({item["sdk_id"] for item in groups}),
            "groups": len(groups),
            "candidates": sum(len(item["candidates"]) for item in groups),
            "positive_candidates": sum(
                candidate["label"] > 0
                for item in groups
                for candidate in item["candidates"]
            ),
        },
        "groups": groups,
    }
