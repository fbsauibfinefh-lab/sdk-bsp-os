from __future__ import annotations

from statistics import mean
from typing import Any


def _top_index(group: dict[str, Any], scores: list[float]) -> int:
    return min(
        range(len(scores)),
        key=lambda index: (-scores[index], group["candidates"][index]["entity_id"]),
    )


def _unique_margin(
    group: dict[str, Any], scores: list[float], selected_index: int
) -> float:
    selected_symbol = group["candidates"][selected_index]["symbol"]
    alternatives = [
        score
        for candidate, score in zip(group["candidates"], scores, strict=True)
        if candidate["symbol"] != selected_symbol
    ]
    return scores[selected_index] - max(alternatives, default=0.0)


def deterministic_ranking_evidence(
    group: dict[str, Any], final_scores: list[float], diagnostics: dict[str, Any]
) -> dict[str, Any]:
    """Describe the Top1 decision and flag weak evidence without rejecting it."""
    candidates = group["candidates"]
    selected_index = _top_index(group, final_scores)
    selected = candidates[selected_index]
    static = [float(item["static_score"]) for item in candidates]
    field = [
        float(item["features"].get("field-late-interaction", 0.0))
        for item in candidates
    ]
    contract = [
        float(item["features"].get("operation-contract-retrieval", 0.0))
        for item in candidates
    ]
    layer = [
        float(item["features"].get("layer-route-score", 0.0))
        for item in candidates
    ]
    rrf = [
        float(item["features"].get("multi-channel-rrf", 0.0))
        for item in candidates
    ]
    generic_fit = [
        float(item["features"].get("generic-operation-fit", 0.0))
        for item in candidates
    ]
    role = [
        float(item["features"].get("source-role-prior", 0.0))
        for item in candidates
    ]
    precision = [
        0.50 * lexical + 0.50 * semantic
        for lexical, semantic in zip(static, field, strict=True)
    ]
    hierarchy = [
        0.25 * lexical + 0.25 * semantic + 0.25 * rule + 0.25 * route
        for lexical, semantic, rule, route in zip(
            static, field, contract, layer, strict=True
        )
    ]
    certified_hierarchy = [
        value + 0.16 * fit + 0.05 * source_role
        for value, fit, source_role in zip(hierarchy, generic_fit, role, strict=True)
    ]
    contract_fusion = [
        0.35 * lexical + 0.35 * semantic + 0.30 * rule
        for lexical, semantic, rule in zip(static, field, contract, strict=True)
    ]
    channels = {
        "static": static,
        "field": field,
        "contract": contract,
        "layer": layer,
        "rrf": rrf,
        "precision": precision,
        "certified-hierarchy": certified_hierarchy,
        "contract-fusion": contract_fusion,
    }
    channel_tops = {
        name: _top_index(group, values) for name, values in channels.items()
    }
    family = selected.get("api_family")
    entity_agreement = mean(index == selected_index for index in channel_tops.values())
    family_agreement = mean(
        candidates[index].get("api_family") == family for index in channel_tops.values()
    )
    margin = _unique_margin(group, final_scores, selected_index)
    selected_contract = contract[selected_index]
    selected_rrf = rrf[selected_index]
    selected_role = role[selected_index]
    selected_field = field[selected_index]
    selected_generic_fit = generic_fit[selected_index]
    selected_final_score = float(final_scores[selected_index])

    reasons = []
    if selected_final_score < 0.50:
        reasons.append("low-final-ranking-score")
    if selected_field < 0.50:
        reasons.append("low-field-semantic-score")
    if selected_contract < 0.45:
        reasons.append("weak-operation-contract")
    if selected_role < 0.78:
        reasons.append("low-callable-layer-evidence")
    if selected_rrf < 0.50:
        reasons.append("weak-multi-channel-retrieval")
    if entity_agreement < 0.25 and family_agreement < 0.50 and margin < 0.002:
        reasons.append("weak-decision-consensus")

    confidence = (
        0.25 * max(0.0, min(1.0, margin / 0.05))
        + 0.25 * entity_agreement
        + 0.20 * family_agreement
        + 0.15 * selected_contract
        + 0.10 * selected_rrf
        + 0.05 * selected_role
    )
    return {
        "schema_version": "1.0",
        "selected_entity_id": selected["entity_id"],
        "selected_symbol": selected["symbol"],
        "low_score": bool(reasons),
        "low_score_reasons": reasons,
        "confidence": round(confidence, 6),
        "final_ranking_score": round(selected_final_score, 6),
        "decision_margin": round(margin, 6),
        "entity_agreement": round(entity_agreement, 6),
        "family_agreement": round(family_agreement, 6),
        "field_semantic_score": round(selected_field, 6),
        "contract": round(selected_contract, 6),
        "generic_operation_fit": round(selected_generic_fit, 6),
        "rrf": round(selected_rrf, 6),
        "role": round(selected_role, 6),
        "channel_top_symbols": {
            name: candidates[index]["symbol"] for name, index in channel_tops.items()
        },
    }
