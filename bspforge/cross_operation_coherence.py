from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from bspforge.operation_ranking import CAPABILITY_TERMS, identifier_tokens


FEATURE_NAMES = [
    "xop-effect-margin",
    "xop-paired-effect-margin",
    "xop-action-selectivity",
    "xop-contract-margin",
    "xop-lexical-margin",
    "xop-generic-fit-margin",
    "xop-consensus-margin",
    "xop-signal-agreement",
    "xop-family-operation-coverage",
    "xop-family-hard-coverage",
    "xop-family-complement-support",
    "xop-family-public-ratio",
    "xop-family-role-coherence",
    "xop-family-target-strength",
    "xop-family-specialization-risk",
]

OPPOSITE_OPERATIONS = {
    "clock.enable": "clock.disable",
    "clock.disable": "clock.enable",
    "interrupt.enable": "interrupt.disable",
    "interrupt.disable": "interrupt.enable",
    "uart.write": "uart.read",
    "uart.read": "uart.write",
    "gpio.write": "gpio.read",
    "gpio.read": "gpio.write",
    "timer.start": "timer.stop",
    "timer.stop": "timer.start",
    "timer.initialize": "timer.set_interval",
    "timer.set_interval": "timer.initialize",
}

SPECIALIZED_TOKENS = {
    "clock": {
        "adc", "can", "canfd", "eth", "ethernet", "i2c", "i2s", "rtc",
        "sd", "sdio", "spi", "timer", "uart", "usart", "usb",
    },
    "interrupt": {
        "adc", "can", "dma", "eth", "gpio", "i2c", "sdio", "spi",
        "timer", "uart", "usb", "wifi",
    },
    "timer": {
        "alarm", "encoder", "hall", "lptimer", "onepulse", "pwm", "rtc",
        "software", "systick",
    },
}

FAMILY_MODE_TOKENS = {
    "timer": {"base", "counter", "ctimer", "gptimer", "tcpwm"},
}


def coherence_family_key(capability: str, candidate: dict[str, Any]) -> str:
    """Recover an action-invariant family such as ``hal_uart`` or ``hal_tim_base``."""
    tokens = identifier_tokens(candidate.get("symbol", ""))
    anchors = set(CAPABILITY_TERMS[capability]) | {capability}
    if capability == "clock":
        anchors.update({"rcc", "sysclk", "sysctl"})
    elif capability == "interrupt":
        anchors.update({"gic", "intc", "nvic", "plic", "sysint"})
    for index, token in enumerate(tokens):
        if token not in anchors:
            continue
        width = index + 1
        if (
            index + 1 < len(tokens)
            and tokens[index + 1] in FAMILY_MODE_TOKENS.get(capability, set())
        ):
            width += 1
        return "_".join(tokens[:width])
    fallback = candidate.get("api_family", "")
    return fallback or "_".join(tokens[:2])


def _tokens(value: str) -> set[str]:
    normalized = value.replace("\\", "/").replace("-", "_").replace("/", "_")
    output: set[str] = set()
    current = ""
    for character in normalized:
        if character.isalnum():
            if character.isupper() and current and not current[-1].isupper():
                output.add(current.lower())
                current = character
            else:
                current += character
        elif current:
            output.add(current.lower())
            current = ""
    if current:
        output.add(current.lower())
    return output


def _effect(candidate: dict[str, Any]) -> float:
    return float(candidate.get("features", {}).get("hw-transitive-operation-effect", 0.0))


def _signals(candidate: dict[str, Any]) -> dict[str, float]:
    features = candidate.get("features", {})
    return {
        "effect": _effect(candidate),
        "contract": float(features.get("operation-contract-retrieval", 0.0)),
        "lexical": float(features.get("symbol-lexical-retrieval", 0.0)),
        "generic": float(features.get("generic-operation-fit", 0.0)),
    }


def _support(candidate: dict[str, Any]) -> float:
    features = candidate.get("features", {})
    return max(
        _effect(candidate),
        float(features.get("operation-contract-retrieval", 0.0)),
        float(features.get("generic-operation-fit", 0.0)),
        float(features.get("symbol-lexical-retrieval", 0.0)),
    )


def _public_score(candidate: dict[str, Any]) -> float:
    features = candidate.get("features", {})
    boundary = max(
        float(features.get("hw-public-boundary", 0.0)),
        float(features.get("public-api", 0.0)),
    )
    role = float(features.get("source-role-prior", 0.0))
    return max(boundary, role)


def enrich_dataset_with_cross_operation_coherence(
    dataset: dict[str, Any],
) -> dict[str, Any]:
    """Add label-free contrasts across operations and public API families.

    The computation intentionally ignores ``label`` and truth metadata.  It is
    therefore valid for an unseen SDK at inference time: all statistics are
    recovered only from that SDK's candidate graph and structured features.
    """
    output = deepcopy(dataset)
    groups = output["groups"]
    operations_by_capability: dict[str, set[str]] = defaultdict(set)
    entity_effects: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    entity_signals: dict[
        tuple[str, str], dict[str, dict[str, float]]
    ] = defaultdict(dict)
    family_operation_support: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    family_entities: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)

    for group in groups:
        sdk_id = group["sdk_id"]
        capability = group["capability"]
        operation_id = group["operation_id"]
        operations_by_capability[capability].add(operation_id)
        for candidate in group["candidates"]:
            entity_key = (sdk_id, candidate["entity_id"])
            entity_effects[entity_key][operation_id] = max(
                entity_effects[entity_key].get(operation_id, 0.0),
                _effect(candidate),
            )
            signals = _signals(candidate)
            previous = entity_signals[entity_key].get(operation_id, {})
            entity_signals[entity_key][operation_id] = {
                name: max(previous.get(name, 0.0), value)
                for name, value in signals.items()
            }
            family = coherence_family_key(capability, candidate)
            candidate["coherence_family"] = family
            family_key = (sdk_id, capability, family)
            support = _support(candidate)
            family_operation_support[family_key][operation_id] = max(
                family_operation_support[family_key].get(operation_id, 0.0),
                support,
            )
            family_entities[family_key][candidate["entity_id"]] = candidate

    family_statistics: dict[tuple[str, str, str], dict[str, float]] = {}
    for family_key, operation_support in family_operation_support.items():
        _, capability, family = family_key
        expected = sorted(operations_by_capability[capability])
        support_values = [operation_support.get(operation, 0.0) for operation in expected]
        entities = list(family_entities[family_key].values())
        roles = Counter(item.get("source_role", "unknown") for item in entities)
        public_ratio = (
            sum(_public_score(item) for item in entities) / len(entities)
            if entities else 0.0
        )
        role_coherence = max(roles.values(), default=0) / max(1, len(entities))
        family_statistics[family_key] = {
            "coverage": sum(support_values) / max(1, len(support_values)),
            "hard_coverage": sum(value >= 0.45 for value in support_values) / max(1, len(support_values)),
            "public_ratio": public_ratio,
            "role_coherence": role_coherence,
            "family_empty": float(not family),
        }

    for group in groups:
        sdk_id = group["sdk_id"]
        capability = group["capability"]
        operation_id = group["operation_id"]
        expected = operations_by_capability[capability]
        opposite = OPPOSITE_OPERATIONS.get(operation_id)
        for candidate in group["candidates"]:
            profile = entity_effects[(sdk_id, candidate["entity_id"])]
            target = profile.get(operation_id, 0.0)
            competing = [
                profile.get(operation, 0.0)
                for operation in expected if operation != operation_id
            ]
            strongest_competitor = max(competing, default=0.0)
            paired = profile.get(opposite, 0.0) if opposite else strongest_competitor
            selectivity = target / max(0.20, sum(profile.get(item, 0.0) for item in expected))
            signal_profile = entity_signals[(sdk_id, candidate["entity_id"])]
            signal_margins: dict[str, float] = {}
            for signal in ("effect", "contract", "lexical", "generic"):
                target_signal = signal_profile.get(operation_id, {}).get(signal, 0.0)
                competitor_signal = max(
                    (
                        signal_profile.get(operation, {}).get(signal, 0.0)
                        for operation in expected if operation != operation_id
                    ),
                    default=0.0,
                )
                signal_margins[signal] = target_signal - competitor_signal

            family = coherence_family_key(capability, candidate)
            candidate["coherence_family"] = family
            family_key = (sdk_id, capability, family)
            statistics = family_statistics[family_key]
            operation_support = family_operation_support[family_key]
            target_support = operation_support.get(operation_id, 0.0)
            complement_support = (
                min(target_support, operation_support.get(opposite, 0.0))
                if opposite else statistics["coverage"]
            )
            candidate_tokens = _tokens(
                f"{candidate.get('symbol', '')} {candidate.get('file', '')}"
            )
            specialized = float(bool(candidate_tokens & SPECIALIZED_TOKENS.get(capability, set())))
            sparse_family = 1.0 - statistics["hard_coverage"]
            specialization_risk = specialized * sparse_family

            features = candidate["features"]
            values = {
                "xop-effect-margin": target - strongest_competitor,
                "xop-paired-effect-margin": target - paired,
                "xop-action-selectivity": min(1.0, selectivity),
                "xop-contract-margin": signal_margins["contract"],
                "xop-lexical-margin": signal_margins["lexical"],
                "xop-generic-fit-margin": signal_margins["generic"],
                "xop-consensus-margin": sum(signal_margins.values()) / len(signal_margins),
                "xop-signal-agreement": sum(
                    value > 0.02 for value in signal_margins.values()
                ) / len(signal_margins),
                "xop-family-operation-coverage": statistics["coverage"],
                "xop-family-hard-coverage": statistics["hard_coverage"],
                "xop-family-complement-support": complement_support,
                "xop-family-public-ratio": statistics["public_ratio"],
                "xop-family-role-coherence": statistics["role_coherence"],
                "xop-family-target-strength": target_support,
                "xop-family-specialization-risk": specialization_risk,
            }
            for name, value in values.items():
                features[name] = round(float(value), 6)

    output["cross_operation_coherence"] = {
        "schema_version": "0.4",
        "method": "label-free cross-operation contrast and API-family coherence",
        "features": FEATURE_NAMES,
        "opposite_operation_pairs": OPPOSITE_OPERATIONS,
        "families": len(family_statistics),
        "entity_profiles": len(entity_effects),
        "leakage_control": "labels and truth metadata are not read",
    }
    return output
