from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.operation_ranking import CAPABILITY_TERMS, identifier_tokens


COMPLEMENTARY_OPERATIONS = {
    frozenset(("enable", "disable")),
    frozenset(("start", "stop")),
    frozenset(("read", "write")),
}

GENERIC_TOKENS = {
    "hal", "driver", "device", "api", "base", "instance", "channel",
    "handle", "config", "init", "deinit", "set", "get",
}

FAMILY_ROOTS = {
    "sysctl", "rcc", "nvic", "plic", "sysint", "uart", "usart", "gpio",
    "gpiohs", "timer", "tim", "gptimer", "tcpwm", "mtb", "cyhal", "cy",
    "hal", "ll", "nrfx", "esp", "r", "ioport",
}


def api_family_tokens(capability: str, operation: str, candidate: dict[str, Any]) -> set[str]:
    aliases = set(CAPABILITY_SCHEMA[capability]["operations"][operation])
    removed = aliases | set(CAPABILITY_TERMS[capability]) | GENERIC_TOKENS
    tokens = identifier_tokens(candidate["symbol"])
    return {
        token for token in identifier_tokens(candidate["symbol"])
        if (token not in removed and len(token) > 1) or token in FAMILY_ROOTS
    } | set(tokens[:1])


def contract_adjustment(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Apply vendor-independent admissibility rules before API-set decoding."""
    features = candidate["features"]
    evidence = []
    adjustment = 0.0
    if not (
        features.get("capability-name")
        or features.get("controller-api")
        or features.get("hal-abstraction")
    ):
        adjustment -= 0.35
        evidence.append("missing-capability-evidence")
    if not (
        features.get("operation-exact")
        or features.get("operation-substring")
        or features.get("parameterized-toggle")
        or features.get("signature-hint")
    ):
        adjustment -= 0.25
        evidence.append("missing-operation-contract")
    for name in (
        "opposite-action", "semantic-conflict", "reverse-os-adapter",
        "private-api", "test-example",
    ):
        if features.get(name):
            adjustment -= 0.55 if name in {"opposite-action", "semantic-conflict"} else 0.35
            evidence.append(f"reject:{name}")
    return adjustment, evidence


def signature_type_tokens(candidate: dict[str, Any]) -> set[str]:
    fields = candidate.get("candidate_text", "")
    signature = next(
        (line.partition(":")[2] for line in fields.splitlines() if line.startswith("signature:")),
        "",
    )
    return {
        token for token in identifier_tokens(signature)
        if token.endswith("t") or "handle" in token or "callback" in token or "config" in token
    }


def compatibility(
    capability: str,
    left_operation: str,
    left: dict[str, Any],
    right_operation: str,
    right: dict[str, Any],
) -> tuple[float, list[str]]:
    score = 0.0
    evidence = []
    if left["entity_id"] == right["entity_id"]:
        complementary = frozenset((left_operation, right_operation)) in COMPLEMENTARY_OPERATIONS
        parameterized = bool(
            left["features"].get("parameterized-toggle")
            or right["features"].get("parameterized-toggle")
        )
        if complementary and parameterized:
            score += 0.30
            evidence.append("parameterized-complement")
        elif left_operation != right_operation:
            score -= 0.45
            evidence.append("unjustified-entity-reuse")
    left_family = api_family_tokens(capability, left_operation, left)
    right_family = api_family_tokens(capability, right_operation, right)
    shared_family = left_family.intersection(right_family)
    if shared_family:
        score += min(0.24, 0.12 * len(shared_family))
        evidence.append("shared-api-family")
    left_path = PurePosixPath(left["file"])
    right_path = PurePosixPath(right["file"])
    if left_path.parent == right_path.parent:
        score += 0.10
        evidence.append("shared-source-directory")
    elif left_path.parts[:2] == right_path.parts[:2]:
        score += 0.04
        evidence.append("shared-source-root")
    shared_types = signature_type_tokens(left).intersection(signature_type_tokens(right))
    if shared_types:
        score += min(0.20, 0.10 * len(shared_types))
        evidence.append("shared-signature-type")
    if left["features"].get("hal-abstraction") == right["features"].get("hal-abstraction") == 1.0:
        score += 0.06
        evidence.append("shared-hal-layer")
    return score, evidence


def constrained_rerank(
    capability: str,
    operation_groups: list[dict[str, Any]],
    unary_scores: dict[str, dict[str, float]],
    *,
    pair_weight: float,
    top_candidates: int = 10,
    beam_width: int = 64,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    ordered_groups = sorted(operation_groups, key=lambda item: item["operation"])
    adjusted_unary = {
        group["group_id"]: {
            candidate["entity_id"]: (
                unary_scores[group["group_id"]][candidate["entity_id"]]
                + contract_adjustment(candidate)[0]
            )
            for candidate in group["candidates"]
        }
        for group in ordered_groups
    }
    beams: list[tuple[float, list[tuple[str, dict[str, Any]]]]] = [(0.0, [])]
    for group in ordered_groups:
        operation = group["operation"]
        candidates = sorted(
            group["candidates"],
            key=lambda item: (-adjusted_unary[group["group_id"]][item["entity_id"]], item["entity_id"]),
        )[:top_candidates]
        expanded = []
        for beam_score, assignments in beams:
            for candidate in candidates:
                pair_score = sum(
                    compatibility(capability, previous_operation, previous, operation, candidate)[0]
                    for previous_operation, previous in assignments
                )
                expanded.append((
                    beam_score
                    + adjusted_unary[group["group_id"]][candidate["entity_id"]]
                    + pair_weight * pair_score,
                    assignments + [(operation, candidate)],
                ))
        beams = sorted(expanded, key=lambda item: -item[0])[:beam_width]
    best_score, best = beams[0]
    selected = {operation: candidate for operation, candidate in best}
    output = {}
    evidence = {}
    for group in ordered_groups:
        operation = group["operation"]
        values = []
        for candidate in group["candidates"]:
            pair_values = []
            pair_evidence = []
            for other_operation, other in best:
                if other_operation == operation:
                    continue
                value, reasons = compatibility(
                    capability, operation, candidate, other_operation, other
                )
                pair_values.append(value)
                pair_evidence.extend(reasons)
            support = sum(pair_values) / len(pair_values) if pair_values else 0.0
            contract_value, contract_evidence = contract_adjustment(candidate)
            values.append(
                unary_scores[group["group_id"]][candidate["entity_id"]]
                + contract_value
                + pair_weight * support
            )
            evidence[f"{group['group_id']}::{candidate['entity_id']}"] = sorted(
                set(pair_evidence + contract_evidence)
            )
        output[group["group_id"]] = values
    return output, {
        "objective": round(best_score, 6),
        "selected": {operation: candidate["entity_id"] for operation, candidate in best},
        "evidence": evidence,
    }
