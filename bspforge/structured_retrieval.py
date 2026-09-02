from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.field_late_interaction import candidate_fields
from bspforge.operation_ranking import (
    CAPABILITY_TERMS,
    SIGNATURE_HINTS,
    identifier_tokens,
)


STRUCTURED_RETRIEVAL_FEATURES = [
    "source-role-prior",
    "symbol-lexical-retrieval",
    "signature-contract-retrieval",
    "operation-contract-retrieval",
    "generic-operation-fit",
    "layer-route-score",
    "graph-neighbor-support",
    "api-family-support",
    "multi-channel-rrf",
]

_PATH_SPLIT = re.compile(r"[^a-z0-9]+")

CONTRACT_TERMS = {
    "clock.initialize": {
        "prefer": {"clock", "clk", "rcc", "osc", "pll", "sysclk", "freq", "source", "config", "init"},
        "reject": {
            "uart", "usart", "i2c", "i2s", "spi", "usb", "adc", "timer", "rtc",
            "disable", "enabled",
        },
    },
    "clock.enable": {
        "prefer": {"clock", "clk", "rcc", "enable", "enabled", "gate"},
        "reject": {"disable", "timer", "uart", "usart", "i2c", "spi"},
    },
    "clock.disable": {
        "prefer": {"clock", "clk", "rcc", "disable", "enabled", "gate"},
        "reject": {"enable", "timer", "uart", "usart", "i2c", "spi"},
    },
    "clock.get_frequency": {
        "prefer": {"clock", "clk", "rcc", "freq", "frequency", "hz", "get"},
        "reject": {"set", "enable", "disable", "uart", "timer", "sdhc", "spi"},
    },
    "interrupt.initialize": {
        "prefer": {"interrupt", "irq", "plic", "nvic", "intc", "sysint", "config", "init"},
        "reject": {
            "uart", "timer", "gpio", "sdio", "wifi", "hall", "encoder",
            "priority", "claim", "complete", "unregister",
        },
    },
    "interrupt.enable": {
        "prefer": {"interrupt", "irq", "plic", "nvic", "intc", "sysint", "enable", "unmask"},
        "reject": {"disable", "uart", "timer", "gpio", "sdio", "wifi"},
    },
    "interrupt.disable": {
        "prefer": {"interrupt", "irq", "plic", "nvic", "intc", "sysint", "disable", "mask"},
        "reject": {"enable", "uart", "timer", "gpio", "sdio", "wifi"},
    },
    "interrupt.register": {
        "prefer": {"interrupt", "irq", "plic", "nvic", "intc", "sysint", "vector", "handler", "register"},
        "reject": {"uart", "timer", "gpio", "sdio", "wifi", "bus", "spi"},
    },
    "uart.configure": {
        "prefer": {"uart", "usart", "serial", "sci", "baud", "setup", "config", "init"},
        "reject": {"gpio", "timer", "spi", "i2c", "memory"},
    },
    "uart.write": {
        "prefer": {"uart", "usart", "serial", "sci", "write", "send", "transmit", "put"},
        "reject": {"read", "receive", "gpio", "timer", "spi", "i2c"},
    },
    "uart.read": {
        "prefer": {"uart", "usart", "serial", "sci", "read", "receive", "get"},
        "reject": {"write", "send", "transmit", "gpio", "timer", "spi", "i2c"},
    },
    "gpio.configure": {
        "prefer": {"gpio", "pin", "port", "drive", "mode", "setup", "config", "init"},
        "reject": {"sdio", "wifi", "spi", "uart", "timer"},
    },
    "gpio.write": {
        "prefer": {"gpio", "pin", "port", "write", "set", "toggle", "output"},
        "reject": {"read", "sdio", "wifi", "spi", "uart", "timer", "hsiom"},
    },
    "gpio.read": {
        "prefer": {"gpio", "pin", "port", "read", "get", "input"},
        "reject": {"write", "sdio", "wifi", "spi", "uart", "timer", "hsiom"},
    },
    "gpio.attach_irq": {
        "prefer": {"gpio", "pin", "port", "irq", "interrupt", "callback", "event", "register"},
        "reject": {"sdio", "wifi", "spi", "uart", "timer", "bus"},
    },
    "timer.initialize": {
        "prefer": {"timer", "tim", "counter", "tcpwm", "base", "gptimer", "ctimer", "init", "setup"},
        "reject": {"pwm", "encoder", "hall", "onepulse", "one", "pulse", "alarm", "rtc", "systick", "software"},
    },
    "timer.start": {
        "prefer": {"timer", "tim", "counter", "tcpwm", "base", "gptimer", "ctimer", "start", "enable"},
        "reject": {"pwm", "encoder", "hall", "onepulse", "one", "pulse", "alarm", "rtc", "systick", "software", "stop", "dma"},
    },
    "timer.stop": {
        "prefer": {"timer", "tim", "counter", "tcpwm", "base", "gptimer", "ctimer", "stop", "disable"},
        "reject": {"pwm", "encoder", "hall", "onepulse", "one", "pulse", "alarm", "rtc", "systick", "software", "start", "dma"},
    },
    "timer.set_interval": {
        "prefer": {"timer", "tim", "counter", "tcpwm", "base", "period", "interval", "reload", "compare"},
        "reject": {"pwm", "encoder", "hall", "onepulse", "one", "pulse", "alarm", "rtc", "systick", "software"},
    },
}

_GENERIC_MODE_TOKENS = {
    "clock": {"uart", "usart", "i2c", "i2s", "spi", "usb", "adc", "timer", "rtc"},
    "timer": {
        "pwm", "pwmn", "hall", "sensor", "encoder", "onepulse", "pulse",
        "lptimer", "oc", "ocn", "ic",
    },
}

_PRIMARY_ACTION_TOKENS = {
    "initialize": {"init", "config", "configure", "setup"},
    "enable": {"enable", "unmask"},
    "disable": {"disable", "mask"},
    "register": {"register", "attach", "vector", "callback"},
    "configure": {"config", "configure", "setup", "init"},
    "write": {"write", "send", "transmit", "put"},
    "read": {"read", "receive", "get"},
    "attach_irq": {"register", "attach", "callback", "irq", "interrupt"},
    "start": {"start", "enable"},
    "stop": {"stop", "disable"},
    "set_interval": {"interval", "period", "reload", "compare", "set"},
    "get_frequency": {"get", "frequency", "freq", "hz"},
}


def classify_source_role(path: str, symbol: str = "") -> tuple[str, float, list[str]]:
    """Classify an SDK entity without relying on a vendor-specific symbol list."""
    value = path.replace("\\", "/").lower()
    name = symbol.lower()
    evidence: list[str] = []
    if any(token in value for token in ("/docs/", "/doc/", "/html/", "docs/html")):
        return "documentation", 0.02, ["documentation-path"]
    if any(token in value for token in (
        "/test/", "/tests/", "/example/", "/examples/", "/sample/", "/samples/",
        "/projects/", "/applications/",
    )):
        return "example-test", 0.06, ["example-or-test-path"]
    if any(token in value for token in (
        "/freertos/", "/rtos/", "/rtos2/", "/lwip/", "/lvgl", "wifi-host-driver",
        "/middleware/", "/middlewares/third_party/",
    )):
        return "middleware", 0.10, ["middleware-or-rtos-path"]
    if any(token in value for token in ("/porting/", "/ports/", "hal_drivers/drv_")):
        return "os-adapter", 0.16, ["porting-layer-path"]
    if (
        any(token in value for token in ("/hal/source/", "/hal/include/", "_hal_driver/", "/drivers/hal/"))
        or name.startswith(("hal_", "mtb_hal_", "cyhal_"))
    ):
        evidence.append("public-hal-layer")
        return "public-hal", 1.0, evidence
    if any(token in value for token in ("/pdl/", "/driverlib/", "/peripheral/", "/emlib/")):
        return "vendor-low-level", 0.86, ["vendor-low-level-driver"]
    if any(token in value for token in ("/drivers/", "/driver/", "lib/drivers/")):
        return "sdk-driver", 0.90, ["sdk-driver-path"]
    if any(token in value for token in ("/inc/", "/include/")):
        return "public-header", 0.78, ["public-header-path"]
    if "/src/" in value or value.endswith((".c", ".cc", ".cpp")):
        return "sdk-source", 0.58, ["sdk-source-path"]
    return "unknown", 0.40, ["unclassified-source-role"]


def _char_ngrams(value: str, size: int = 3) -> set[str]:
    compact = "".join(_PATH_SPLIT.split(value.lower()))
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index:index + size] for index in range(len(compact) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _symbol_lexical_score(group: dict[str, Any], candidate: dict[str, Any]) -> float:
    capability = group["capability"]
    operation = group["operation"]
    aliases = CAPABILITY_SCHEMA[capability]["operations"][operation]
    symbol_tokens = set(identifier_tokens(candidate["symbol"]))
    capability_terms = set(CAPABILITY_TERMS[capability]) | {capability}
    operation_terms = set(aliases) | set(operation.split("_"))
    capability_match = len(symbol_tokens & capability_terms) / max(1, min(2, len(capability_terms)))
    operation_match = len(symbol_tokens & operation_terms) / max(1, min(2, len(operation_terms)))
    canonical = max(
        (_jaccard(_char_ngrams(candidate["symbol"]), _char_ngrams(f"{term}_{alias}"))
         for term in capability_terms for alias in operation_terms),
        default=0.0,
    )
    return max(0.0, min(1.0, 0.42 * capability_match + 0.43 * operation_match + 0.15 * canonical))


def _signature_contract_score(group: dict[str, Any], candidate: dict[str, Any]) -> float:
    fields = candidate_fields(candidate.get("candidate_text", ""))
    signature_tokens = set(identifier_tokens(fields["signature"]))
    hints = set(SIGNATURE_HINTS.get(group["operation"], ()))
    aliases = set(CAPABILITY_SCHEMA[group["capability"]]["operations"][group["operation"]])
    hint_score = len(signature_tokens & hints) / max(1, min(3, len(hints)))
    alias_score = len(signature_tokens & aliases) / max(1, min(2, len(aliases)))
    typed = float(bool(signature_tokens & {"uint", "int", "bool", "void", "callback", "handler"}))
    return max(0.0, min(1.0, 0.62 * hint_score + 0.23 * alias_score + 0.15 * typed))


def _operation_contract_score(
    group: dict[str, Any], candidate: dict[str, Any], role_prior: float
) -> float:
    contract = CONTRACT_TERMS[group["operation_id"]]
    fields = candidate_fields(candidate.get("candidate_text", ""))
    symbol_tokens = set(identifier_tokens(candidate["symbol"]))
    signature_tokens = set(identifier_tokens(fields["signature"]))
    path_tokens = set(_PATH_SPLIT.split(candidate.get("file", "").lower()))
    prefer = contract["prefer"]
    reject = set(contract["reject"])
    parameterized_toggle = bool(candidate["features"].get("parameterized-toggle", 0.0))
    if parameterized_toggle:
        reject -= {"enable", "disable", "start", "stop", "enabled"}
    positive_symbol = len(symbol_tokens & prefer) / max(1, min(4, len(prefer)))
    positive_context = len((signature_tokens | path_tokens) & prefer) / max(1, min(3, len(prefer)))
    negative = len((symbol_tokens | path_tokens) & reject) / max(1, min(3, len(reject)))
    toggle_bonus = 0.18 if parameterized_toggle else 0.0
    score = (
        0.50 * positive_symbol
        + 0.16 * positive_context
        + 0.34 * role_prior
        + toggle_bonus
        - 0.55 * negative
    )
    return max(0.0, min(1.0, score))


def _generic_operation_fit(group: dict[str, Any], candidate: dict[str, Any]) -> float:
    """Estimate whether an API implements the generic operation rather than a sub-mode."""
    capability = group["capability"]
    operation = group["operation"]
    ordered_tokens = identifier_tokens(candidate["symbol"])
    tokens = set(ordered_tokens)
    action_terms = set(_PRIMARY_ACTION_TOKENS[operation])
    if capability == "clock" and operation == "initialize":
        action_terms.update({"set", "select"})
    action = float(bool(tokens & action_terms))
    if candidate["features"].get("parameterized-toggle", 0.0):
        action = max(action, 0.9)
    capability_terms = set(CAPABILITY_TERMS[capability]) | {capability}
    if capability == "clock":
        capability_terms = {"clock", "rcc", "sysctl", "sysclk"}
    capability_match = float(bool(tokens & capability_terms))
    mode_hits = tokens & _GENERIC_MODE_TOKENS.get(capability, set())
    mode_penalty = min(0.60, 0.24 * len(mode_hits))
    if capability == "clock" and "clk" in tokens and not tokens & capability_terms:
        mode_penalty = max(mode_penalty, 0.40)
    if capability == "clock" and operation == "initialize" and "source" in tokens:
        mode_penalty = max(mode_penalty, 0.32)
    if operation == "initialize" and tokens & {"enable", "disable"}:
        mode_penalty = max(mode_penalty, 0.50)
    controller_bonus = 0.0
    controllers = {"plic", "nvic", "gic", "intc", "sysint"}
    if capability == "interrupt" and tokens & controllers:
        controller_bonus = 0.22
    if capability == "interrupt" and operation == "register" and not tokens & controllers:
        generic_tokens = action_terms | {"interrupt", "irq", "isr", "handler"}
        if any(token not in generic_tokens for token in ordered_tokens[:3]):
            mode_penalty = max(mode_penalty, 0.32)
    broad_family_bonus = 0.0
    if capability == "timer" and tokens & {"timer", "tim", "base", "gptimer", "ctimer", "tcpwm"}:
        broad_family_bonus = 0.10
    if capability == "clock" and tokens & {"clock", "rcc", "sysctl", "sysclk"}:
        broad_family_bonus = 0.10
    score = 0.52 * action + 0.28 * capability_match + controller_bonus + broad_family_bonus
    return max(0.0, min(1.0, score - mode_penalty))


def api_family_key(capability: str, symbol: str) -> str:
    """Recover a stable public API family from identifier morphology."""
    tokens = identifier_tokens(symbol)
    if not tokens:
        return ""
    if tokens[:2] == ["mtb", "hal"] and len(tokens) >= 3:
        return "_".join(tokens[:3])
    if tokens[0] in {"hal", "ll"} and len(tokens) >= 2:
        if len(tokens) >= 3 and tokens[1] == "tim":
            return "_".join(tokens[:3])
        return "_".join(tokens[:2])
    if tokens[0] == "cy" and len(tokens) >= 2:
        width = 3 if len(tokens) >= 3 and tokens[1] in {"sys", "tcpwm"} else 2
        return "_".join(tokens[:width])
    if tokens[0] in {"sysctl", "gpiohs", "plic", "uart", "uarths", "timer", "gpio"}:
        width = 2 if len(tokens) >= 2 and tokens[0] == "sysctl" else 1
        return "_".join(tokens[:width])
    capability_terms = set(CAPABILITY_TERMS[capability]) | {capability}
    positions = [index for index, token in enumerate(tokens) if token in capability_terms]
    if positions:
        return "_".join(tokens[:min(len(tokens), positions[0] + 1, 3)])
    return "_".join(tokens[:min(2, len(tokens))])


def _rank_values(
    candidates: list[dict[str, Any]], scores: dict[str, float]
) -> dict[str, int]:
    ordered = sorted(
        candidates,
        key=lambda item: (-scores[item["entity_id"]], item["entity_id"]),
    )
    return {item["entity_id"]: index for index, item in enumerate(ordered, start=1)}


def _normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low = min(values.values())
    span = max(values.values()) - low
    if span <= 1e-12:
        return {key: 0.0 for key in values}
    return {key: (value - low) / span for key, value in values.items()}


def enrich_group_with_structured_retrieval(group: dict[str, Any]) -> dict[str, Any]:
    candidates = group["candidates"]
    symbols = defaultdict(list)
    calls: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = defaultdict(set)
    channel_scores: dict[str, dict[str, float]] = {
        "static": {},
        "field": {},
        "lexical": {},
        "scope": {},
    }
    family_members: dict[str, list[str]] = defaultdict(list)
    role_counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        entity_id = candidate["entity_id"]
        symbols[candidate["symbol"]].append(entity_id)
        fields = candidate_fields(candidate.get("candidate_text", ""))
        calls[entity_id] = set(fields["calls"].split())
        role, prior, evidence = classify_source_role(candidate.get("file", ""), candidate["symbol"])
        lexical = _symbol_lexical_score(group, candidate)
        signature = _signature_contract_score(group, candidate)
        contract = _operation_contract_score(group, candidate, prior)
        generic_fit = _generic_operation_fit(group, candidate)
        features = candidate["features"]
        capability_match = float(bool(
            set(identifier_tokens(candidate["symbol"]))
            & (set(CAPABILITY_TERMS[group["capability"]]) | {group["capability"]})
        ))
        operation_match = max(
            float(features.get("operation-exact", 0.0)),
            float(features.get("operation-substring", 0.0)),
            float(features.get("parameterized-toggle", 0.0)),
            min(1.0, contract * 1.35),
        )
        layer_route = prior * capability_match * operation_match
        role_counts[role] += 1
        family = api_family_key(group["capability"], candidate["symbol"])
        family_members[family].append(entity_id)
        candidate["source_role"] = role
        candidate["api_family"] = family
        candidate["source_role_evidence"] = evidence
        candidate["features"]["source-role-prior"] = round(prior, 6)
        candidate["features"]["symbol-lexical-retrieval"] = round(lexical, 6)
        candidate["features"]["signature-contract-retrieval"] = round(signature, 6)
        candidate["features"]["operation-contract-retrieval"] = round(contract, 6)
        candidate["features"]["generic-operation-fit"] = round(generic_fit, 6)
        candidate["features"]["layer-route-score"] = round(layer_route, 6)
        channel_scores["static"][entity_id] = float(candidate["static_score"])
        channel_scores["field"][entity_id] = float(
            candidate["features"].get("field-late-interaction", 0.0)
        )
        channel_scores["lexical"][entity_id] = 0.78 * lexical + 0.22 * signature
        channel_scores["scope"][entity_id] = 0.68 * prior + 0.32 * lexical
        channel_scores.setdefault("contract", {})[entity_id] = contract
        channel_scores.setdefault("layer", {})[entity_id] = layer_route
    for source_id, called_symbols in calls.items():
        for symbol in called_symbols:
            for target_id in symbols.get(symbol, []):
                reverse[target_id].add(source_id)
    seed = {
        entity_id: 0.45 * channel_scores["static"][entity_id]
        + 0.30 * channel_scores["field"][entity_id]
        + 0.25 * channel_scores["lexical"][entity_id]
        for entity_id in channel_scores["static"]
    }
    graph_scores = {}
    for candidate in candidates:
        entity_id = candidate["entity_id"]
        neighbors = set(reverse.get(entity_id, set()))
        for called_symbol in calls[entity_id]:
            neighbors.update(symbols.get(called_symbol, []))
        neighbors.discard(entity_id)
        one_hop = max((seed[item] for item in neighbors), default=0.0)
        graph_scores[entity_id] = max(0.55 * seed[entity_id], 0.72 * one_hop)
        candidate["features"]["graph-neighbor-support"] = round(graph_scores[entity_id], 6)
    channel_scores["graph"] = graph_scores
    family_seed = {
        entity_id: 0.25 * channel_scores["static"][entity_id]
        + 0.55 * channel_scores["field"][entity_id]
        + 0.20 * channel_scores["lexical"][entity_id]
        for entity_id in channel_scores["static"]
    }
    family_scores = {}
    for family, members in family_members.items():
        support = max((family_seed[item] for item in members), default=0.0)
        for entity_id in members:
            family_scores[entity_id] = 0.62 * family_seed[entity_id] + 0.38 * support
    channel_scores["family"] = family_scores
    for candidate in candidates:
        candidate["features"]["api-family-support"] = round(
            family_scores[candidate["entity_id"]], 6
        )
    channel_weights = {
        "static": 1.0,
        "field": 1.2,
        "lexical": 1.3,
        "scope": 0.9,
        "contract": 1.5,
        "layer": 1.6,
        "graph": 0.7,
        "family": 1.1,
    }
    ranks = {
        name: _rank_values(candidates, values)
        for name, values in channel_scores.items()
    }
    rrf_raw = {
        candidate["entity_id"]: sum(
            channel_weights[name] / (40.0 + ranks[name][candidate["entity_id"]])
            for name in channel_weights
        )
        for candidate in candidates
    }
    rrf = _normalize(rrf_raw)
    for candidate in candidates:
        candidate["features"]["multi-channel-rrf"] = round(rrf[candidate["entity_id"]], 6)
    return {
        "group_id": group["group_id"],
        "roles": dict(sorted(role_counts.items())),
        "channels": channel_weights,
        "graph_edges": sum(len(items) for items in reverse.values()),
    }


def enrich_dataset_with_structured_retrieval(dataset: dict[str, Any]) -> dict[str, Any]:
    reports = [enrich_group_with_structured_retrieval(group) for group in dataset["groups"]]
    source_roles: dict[str, int] = defaultdict(int)
    for report in reports:
        for role, count in report["roles"].items():
            source_roles[role] += count
    dataset["structured_retrieval"] = {
        "schema_version": "1.0",
        "method": "source-role-aware multi-channel RRF with bounded call-graph expansion",
        "features": STRUCTURED_RETRIEVAL_FEATURES,
        "groups": len(reports),
        "graph_edges": sum(item["graph_edges"] for item in reports),
        "source_roles": dict(sorted(source_roles.items())),
    }
    return dataset


def family_diversified_scores(
    group: dict[str, Any],
    base_scores: list[float],
    *,
    leader_scores: list[float] | None = None,
    family_quota: int = 4,
) -> list[float]:
    """Preserve the best candidate and expose compatible siblings in its API family."""
    candidates = group["candidates"]
    ranked = sorted(
        range(len(candidates)),
        key=lambda index: (-base_scores[index], candidates[index]["entity_id"]),
    )
    leader_ranked = sorted(
        range(len(candidates)),
        key=lambda index: (
            -(leader_scores or base_scores)[index], candidates[index]["entity_id"]
        ),
    )
    selected: list[int] = []
    seen_symbols: set[str] = set()

    def append(index: int) -> None:
        symbol = candidates[index]["symbol"]
        if symbol not in seen_symbols:
            selected.append(index)
            seen_symbols.add(symbol)

    append(leader_ranked[0])
    leader = candidates[leader_ranked[0]]
    leader_family = leader.get("api_family", "")
    leader_role = float(leader["features"].get("source-role-prior", 0.0))
    if leader_family and leader_role >= 0.58:
        siblings = [
            index for index in ranked
            if index != leader_ranked[0]
            and candidates[index].get("api_family") == leader_family
            and (
                candidates[index]["features"].get("operation-exact", 0.0)
                or candidates[index]["features"].get("operation-substring", 0.0)
                or candidates[index]["features"].get("parameterized-toggle", 0.0)
                or candidates[index]["features"].get("operation-contract-retrieval", 0.0) >= 0.40
            )
        ]
        siblings.sort(
            key=lambda index: (
                -float(candidates[index]["features"].get("operation-contract-retrieval", 0.0)),
                -float(candidates[index]["features"].get("operation-exact", 0.0)),
                -float(candidates[index]["features"].get("operation-substring", 0.0)),
                -base_scores[index],
                candidates[index]["entity_id"],
            )
        )
        siblings = siblings[:max(0, family_quota - 1)]
    else:
        siblings = []
    representatives = []
    represented = {leader_family}
    for index in sorted(
        ranked,
        key=lambda item: (
            -float(candidates[item]["features"].get("source-role-prior", 0.0)),
            -float(candidates[item]["features"].get("layer-route-score", 0.0)),
            -float(candidates[item]["features"].get("operation-contract-retrieval", 0.0)),
            -base_scores[item],
            candidates[item]["entity_id"],
        ),
    ):
        family = candidates[index].get("api_family", "")
        features = candidates[index]["features"]
        if (
            family
            and family not in represented
            and float(features.get("source-role-prior", 0.0)) >= 0.78
            and float(features.get("operation-contract-retrieval", 0.0)) >= 0.22
            and (
                features.get("capability-name", 0.0)
                or features.get("symbol-lexical-retrieval", 0.0) >= 0.20
            )
        ):
            representatives.append(index)
            represented.add(family)
        if len(representatives) >= 2:
            break
    representative_siblings = []
    if representatives:
        representative_family = candidates[representatives[0]].get("api_family", "")
        representative_siblings = [
            index for index in ranked
            if index != representatives[0]
            and candidates[index].get("api_family") == representative_family
            and float(candidates[index]["features"].get("operation-contract-retrieval", 0.0)) >= 0.30
        ]
        representative_siblings.sort(
            key=lambda index: (
                -float(candidates[index]["features"].get("operation-contract-retrieval", 0.0)),
                -float(candidates[index]["features"].get("operation-exact", 0.0)),
                -base_scores[index],
                candidates[index]["entity_id"],
            )
        )
    if leader_role >= 0.90:
        for index in siblings[:2]:
            append(index)
        for index in representatives[:1]:
            append(index)
        for index in representative_siblings[:1]:
            append(index)
        for index in siblings[2:]:
            append(index)
    else:
        for index in representatives[:1]:
            append(index)
        for index in representative_siblings[:1]:
            append(index)
        for index in siblings[:1]:
            append(index)
        for index in representatives[1:2]:
            append(index)
        for index in siblings[1:]:
            append(index)
    for index in ranked:
        append(index)
    synthetic = [0.0] * len(candidates)
    for position, index in enumerate(selected):
        synthetic[index] = float(len(selected) - position)
    return synthetic


def complete_structured_scores(
    group: dict[str, Any], *, family_quota: int = 4
) -> tuple[list[float], dict[str, Any]]:
    """Apply the frozen v1.0 hierarchy/contract/family policy."""
    static = [float(item["static_score"]) for item in group["candidates"]]
    field = [
        float(item["features"].get("field-late-interaction", 0.0))
        for item in group["candidates"]
    ]
    contract = [
        float(item["features"].get("operation-contract-retrieval", 0.0))
        for item in group["candidates"]
    ]
    layer = [
        float(item["features"].get("layer-route-score", 0.0))
        for item in group["candidates"]
    ]
    hierarchy = [
        0.25 * left + 0.25 * semantic + 0.25 * rule + 0.25 * route
        for left, semantic, rule, route in zip(static, field, contract, layer, strict=True)
    ]
    generic_fit = [
        float(item["features"].get("generic-operation-fit", 0.0))
        for item in group["candidates"]
    ]
    role = [
        float(item["features"].get("source-role-prior", 0.0))
        for item in group["candidates"]
    ]
    certified_hierarchy = [
        value + 0.16 * fit + 0.05 * source_role
        for value, fit, source_role in zip(hierarchy, generic_fit, role, strict=True)
    ]
    precision = [
        0.50 * left + 0.50 * semantic
        for left, semantic in zip(static, field, strict=True)
    ]
    leader = max(
        range(len(precision)),
        key=lambda index: (precision[index], group["candidates"][index]["entity_id"]),
    )
    leader_candidate = group["candidates"][leader]
    leader_role = float(leader_candidate["features"].get("source-role-prior", 0.0))
    leader_contract = float(
        leader_candidate["features"].get("operation-contract-retrieval", 0.0)
    )
    best_public_layer = max(
        (
            float(item["features"].get("layer-route-score", 0.0))
            for item in group["candidates"]
            if float(item["features"].get("source-role-prior", 0.0)) >= 0.90
        ),
        default=0.0,
    )
    hierarchy_leader = max(
        range(len(certified_hierarchy)),
        key=lambda index: (
            certified_hierarchy[index], group["candidates"][index]["entity_id"]
        ),
    )
    hierarchy_candidate = group["candidates"][hierarchy_leader]
    hierarchy_contract = contract[hierarchy_leader]
    hierarchy_role = role[hierarchy_leader]
    precision_gap = precision[leader] - precision[hierarchy_leader]
    hierarchy_conflict = float(
        hierarchy_candidate["features"].get("semantic-conflict", 0.0)
        + hierarchy_candidate["features"].get("opposite-action", 0.0)
    )
    stronger_contract = (
        hierarchy_contract - leader_contract >= 0.15
        and precision_gap <= 0.10
        and hierarchy_conflict <= 0.0
    )
    stronger_generic_fit = (
        generic_fit[hierarchy_leader] - generic_fit[leader] >= 0.30
        and precision_gap <= 0.14
        and hierarchy_contract >= leader_contract - 0.05
        and (
            hierarchy_conflict <= 0.0
            or (
                generic_fit[hierarchy_leader] - generic_fit[leader] >= 0.45
                and hierarchy_contract >= leader_contract + 0.10
            )
        )
    )
    stronger_public_route = (
        hierarchy_role >= 0.90
        and leader_role < 0.90
        and certified_hierarchy[hierarchy_leader] >= certified_hierarchy[leader] - 0.01
        and hierarchy_conflict <= 0.0
    )
    fallback = (
        leader_contract < 0.18
        or leader_role < 0.78
        or (leader_role < 0.90 and best_public_layer >= 0.45)
        or stronger_contract
        or stronger_generic_fit
        or stronger_public_route
    )
    scores = family_diversified_scores(
        group,
        certified_hierarchy,
        leader_scores=certified_hierarchy if fallback else precision,
        family_quota=family_quota,
    )
    scale = max(scores) or 1.0
    return [item / scale for item in scores], {
        "policy": "hierarchy-contract-family-q4",
        "family_quota": family_quota,
        "leader_fallback": fallback,
        "precision_leader_entity_id": leader_candidate["entity_id"],
        "precision_leader_symbol": leader_candidate["symbol"],
        "precision_leader_role": leader_candidate.get("source_role"),
        "precision_leader_contract": round(leader_contract, 6),
        "certified_hierarchy_leader_entity_id": hierarchy_candidate["entity_id"],
        "certified_hierarchy_leader_symbol": hierarchy_candidate["symbol"],
        "contract_fallback": stronger_contract,
        "generic_fit_fallback": stronger_generic_fit,
        "public_route_fallback": stronger_public_route,
        "best_public_layer": round(best_public_layer, 6),
    }
