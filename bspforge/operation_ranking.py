from __future__ import annotations

import re
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA


CAPABILITY_TERMS = {
    "clock": ["sysctl", "clock", "clk", "pll", "frequency", "rcc"],
    "interrupt": ["plic", "interrupt", "irq", "isr", "intr", "nvic", "sysint", "trap"],
    "uart": ["uart", "uarths", "serial", "usart", "sci", "baud"],
    "gpio": ["gpio", "gpiohs", "pin", "fpioa", "port", "dio"],
    "timer": ["timer", "tim", "gptimer", "ctimer", "tcpwm", "alarm", "tick", "counter", "tmr"],
}


OPERATION_FEATURE_NAMES = [
    "capability-name",
    "operation-exact",
    "operation-substring",
    "canonical-order",
    "signature-hint",
    "call-context",
    "public-api",
    "hal-abstraction",
    "controller-api",
    "driver-path",
    "parser-confidence",
    "capability-baseline",
    "opposite-action",
    "semantic-conflict",
    "parameterized-toggle",
    "reverse-os-adapter",
    "private-api",
    "test-example",
    "symbol-specificity",
    "code-embedding",
    "cross-reranker",
    "field-late-interaction",
    "field-symbol-maxsim",
    "field-signature-maxsim",
    "field-calls-maxsim",
    "field-file-maxsim",
    "field-includes-maxsim",
    "source-role-prior",
    "symbol-lexical-retrieval",
    "signature-contract-retrieval",
    "operation-contract-retrieval",
    "layer-route-score",
    "graph-neighbor-support",
    "api-family-support",
    "multi-channel-rrf",
]

OPERATION_DESCRIPTIONS = {
    "clock.initialize": "initialize or configure the chip clock tree and clock source",
    "clock.enable": "enable a peripheral or system clock",
    "clock.disable": "disable a peripheral or system clock",
    "clock.get_frequency": "return the current clock frequency in hertz",
    "interrupt.initialize": "initialize the interrupt controller or configure interrupt priority",
    "interrupt.enable": "enable or unmask an interrupt request",
    "interrupt.disable": "disable or mask an interrupt request",
    "interrupt.register": "register or attach an interrupt handler or vector",
    "uart.configure": "initialize and configure a UART peripheral including baud rate",
    "uart.write": "transmit bytes through a UART peripheral",
    "uart.read": "receive bytes from a UART peripheral",
    "gpio.configure": "configure GPIO pin direction mode pull and drive attributes",
    "gpio.write": "write or toggle a GPIO output level",
    "gpio.read": "read a GPIO input level",
    "gpio.attach_irq": "attach or configure a GPIO interrupt callback",
    "timer.initialize": "initialize or configure a hardware timer",
    "timer.start": "start or enable a hardware timer",
    "timer.stop": "stop or disable a hardware timer",
    "timer.set_interval": "set a timer period interval compare or reload value",
}

SIGNATURE_HINTS = {
    "get_frequency": ("freq", "clock", "hz", "uint"),
    "register": ("handler", "callback", "vector", "irq", "isr"),
    "configure": ("config", "baud", "mode", "pin", "handle"),
    "write": ("data", "buffer", "buf", "size", "len", "value", "pin"),
    "read": ("data", "buffer", "buf", "size", "len", "value", "pin"),
    "attach_irq": ("handler", "callback", "edge", "event", "pin", "irq"),
    "set_interval": ("interval", "period", "compare", "reload", "tick"),
    "initialize": ("config", "clock", "timer", "irq"),
    "enable": ("clock", "irq", "timer", "enable"),
    "disable": ("clock", "irq", "timer", "disable"),
    "start": ("timer", "channel", "period"),
    "stop": ("timer", "channel"),
}

OPPOSITE_ACTIONS = {
    "enable": {"disable", "stop"},
    "disable": {"enable", "start"},
    "start": {"stop", "disable"},
    "stop": {"start", "enable"},
    "write": {"read", "receive", "get"},
    "read": {"write", "send", "transmit", "put"},
}

# These are operation-contract conflicts rather than SDK-specific symbol lists.
# They prevent a compilable but behaviorally different API from being promoted.
SEMANTIC_CONFLICTS = {
    "clock.initialize": {"get", "frequency", "freq", "disable", "deinit"},
    "clock.enable": {"disable", "get", "frequency", "freq"},
    "clock.disable": {"enable", "get", "frequency", "freq"},
    "clock.get_frequency": {"enable", "disable", "init", "configure", "set"},
    "interrupt.initialize": {"enable", "disable", "register", "attach", "deinit"},
    "interrupt.enable": {"disable", "register", "attach"},
    "interrupt.disable": {"enable", "register", "attach"},
    "interrupt.register": {"enable", "disable"},
    "uart.configure": {"read", "receive", "write", "send", "transmit", "put", "deinit"},
    "uart.write": {"read", "receive", "get", "init", "configure", "setup"},
    "uart.read": {"write", "send", "transmit", "put", "init", "configure", "setup"},
    "gpio.configure": {"read", "write", "set", "get", "irq", "interrupt", "deinit"},
    "gpio.write": {"read", "get", "mode", "drive", "setup", "irq", "interrupt"},
    "gpio.read": {"write", "set", "mode", "drive", "setup", "irq", "interrupt"},
    "gpio.attach_irq": {"read", "write", "get", "mode", "drive"},
    "timer.initialize": {"start", "stop", "enable", "disable", "interval", "period", "deinit", "pwm"},
    "timer.start": {"stop", "disable", "interval", "period", "compare", "pwm"},
    "timer.stop": {"start", "enable", "interval", "period", "compare", "pwm"},
    "timer.set_interval": {"start", "stop", "enable", "disable", "clint", "mtime", "systick"},
}

TOKEN_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")


def identifier_tokens(value: str) -> list[str]:
    tokens = []
    for part in re.split(r"[^A-Za-z0-9]+", value):
        tokens.extend(item.lower() for item in TOKEN_PATTERN.findall(part) if item)
    normalized = []
    inflections = {
        "enabled": "enable",
        "disabled": "disable",
        "started": "start",
        "stopped": "stop",
        "initialized": "init",
        "configured": "configure",
        "registered": "register",
        "attached": "attach",
    }
    for index, token in enumerate(tokens):
        normalized.append(inflections.get(token, token))
        if index + 1 < len(tokens) and token == "de" and tokens[index + 1] == "init":
            normalized.append("deinit")
    return normalized


def operation_feature_map(
    capability: str,
    operation: str,
    candidate: dict[str, Any],
    function: dict[str, Any],
) -> dict[str, float]:
    aliases = CAPABILITY_SCHEMA[capability]["operations"][operation]
    capability_terms = CAPABILITY_TERMS[capability]
    symbol = candidate["symbol"].lower()
    symbol_tokens = identifier_tokens(candidate["symbol"])
    path = function.get("file", "").lower()
    signature = function.get("signature", "").lower()
    calls = " ".join(function.get("calls", [])).lower()
    exact_actions = [alias for alias in aliases if alias in symbol_tokens]
    substring_actions = [alias for alias in aliases if alias in symbol and alias not in exact_actions]
    capability_matches = [term for term in capability_terms if term in symbol_tokens or term in symbol]
    parameterized_toggle = (
        operation in {"enable", "disable", "start", "stop"}
        and "set" in symbol_tokens
        and any(item in signature for item in ("bool", "enable", "state", "uint"))
    )
    opposite = OPPOSITE_ACTIONS.get(operation, set())
    opposite_matches = [] if parameterized_toggle else [item for item in opposite if item in symbol_tokens]
    conflicts = SEMANTIC_CONFLICTS.get(f"{capability}.{operation}", set())
    conflict_matches = [] if parameterized_toggle else [item for item in conflicts if item in symbol_tokens]
    hints = SIGNATURE_HINTS.get(operation, ())
    public_path = any(token in path for token in ("/include/", "/inc/", "include/", "driver", "/hal/", "_hal/", "emlib"))
    private_path = any(token in path for token in ("/internal", "private", "/mock", "/port/"))
    test_path = any(token in path for token in ("/test", "test/", "/example", "examples/", "/sample", "samples/"))
    # Public SDK headers often expose a macro through a static-inline *_internal body.
    # Such entities remain callable through the header and must not be treated as private.
    private_symbol = (
        symbol.startswith("_")
        or symbol.endswith(("_impl_s", "_impl_ns"))
        or (("internal" in symbol or "private" in symbol) and not public_path)
    )
    hal_abstraction = (
        "hal" in symbol_tokens
        or symbol.startswith(("hal_", "mtb_hal_", "cyhal_"))
        or any(token in path for token in ("/hal/include/", "/hal/source/", "/drivers/hal/"))
    )
    controller_api = capability == "interrupt" and any(
        token in symbol_tokens for token in ("plic", "nvic", "gic", "intc", "sysint")
    )
    reverse_os_adapter = (
        any(token in path for token in (
            "/porting/", "wifi-host-driver", "/middleware/", "/rtos/", "/rtos2/"
        ))
        and (
            symbol.startswith(("rt_", "k_", "os_", "zephyr_"))
            or any(
                call.startswith(("rt_", "k_", "os_", "zephyr_"))
                for call in function.get("calls", [])
            )
        )
    )
    operation_position = min((symbol.find(alias) for alias in aliases if alias in symbol), default=-1)
    capability_position = min((symbol.find(term) for term in capability_terms if term in symbol), default=-1)
    canonical = operation_position >= 0 and capability_position >= 0 and capability_position <= operation_position
    specificity = min(1.0, len(symbol_tokens) / 6.0)
    return {
        "capability-name": float(bool(capability_matches)),
        "operation-exact": float(bool(exact_actions)),
        "operation-substring": float(bool(substring_actions)),
        "canonical-order": float(canonical),
        "signature-hint": min(1.0, sum(item in signature for item in hints) / 3.0),
        "call-context": min(1.0, sum(item in calls for item in aliases) / 2.0),
        "public-api": float(public_path and not private_path and not private_symbol),
        "hal-abstraction": float(hal_abstraction),
        "controller-api": float(controller_api),
        "driver-path": float(any(token in path for token in ("driver", "/hal/", "_hal/", "emlib", "peripheral"))),
        "parser-confidence": float(function.get("parser_confidence", 0.55)),
        "capability-baseline": float(candidate.get("baseline_score", candidate.get("score", 0.0))),
        "opposite-action": min(1.0, len(opposite_matches) / 2.0),
        "semantic-conflict": min(1.0, len(conflict_matches) / 2.0),
        "parameterized-toggle": float(parameterized_toggle),
        "reverse-os-adapter": float(reverse_os_adapter),
        "private-api": float(private_path or private_symbol),
        "test-example": float(test_path),
        "symbol-specificity": specificity,
        "code-embedding": 0.0,
        "cross-reranker": 0.0,
        "field-late-interaction": 0.0,
        "field-symbol-maxsim": 0.0,
        "field-signature-maxsim": 0.0,
        "field-calls-maxsim": 0.0,
        "field-file-maxsim": 0.0,
        "field-includes-maxsim": 0.0,
        "source-role-prior": 0.0,
        "symbol-lexical-retrieval": 0.0,
        "signature-contract-retrieval": 0.0,
        "operation-contract-retrieval": 0.0,
        "layer-route-score": 0.0,
        "graph-neighbor-support": 0.0,
        "api-family-support": 0.0,
        "multi-channel-rrf": 0.0,
    }


def operation_static_score(features: dict[str, float]) -> float:
    positive = (
        0.22 * features["capability-name"]
        + 0.34 * features["operation-exact"]
        + 0.10 * features["operation-substring"]
        + 0.05 * features["canonical-order"]
        + 0.08 * features["signature-hint"]
        + 0.03 * features["call-context"]
        + 0.06 * features["public-api"]
        + 0.08 * features["hal-abstraction"]
        + 0.10 * features["controller-api"]
        + 0.04 * features["driver-path"]
        + 0.04 * features["parser-confidence"]
        + 0.04 * features["capability-baseline"]
    )
    penalty = (
        0.30 * features["opposite-action"]
        + 0.24 * features["semantic-conflict"]
        + 0.30 * features["reverse-os-adapter"]
        + 0.12 * features["private-api"]
        + 0.10 * features["test-example"]
    )
    return round(max(0.0, min(1.0, positive - penalty)), 6)


def weak_relevance(features: dict[str, float]) -> int:
    if (
        features["opposite-action"]
        or features["semantic-conflict"]
        or features["reverse-os-adapter"]
        or features["private-api"]
        or features["test-example"]
    ):
        return 0
    if features["operation-exact"] and features["capability-name"]:
        return 2
    if features["operation-exact"] and (features["driver-path"] or features["signature-hint"]):
        return 1
    return 0


def graded_relevance(features: dict[str, float]) -> tuple[int, list[str], float]:
    """Return an auditable four-level relevance grade for development corpora."""
    evidence = []
    rejection = []
    for name in (
        "opposite-action",
        "semantic-conflict",
        "reverse-os-adapter",
        "private-api",
        "test-example",
    ):
        if features[name]:
            rejection.append(name)
    if rejection:
        return 0, [f"reject:{name}" for name in rejection], 0.98
    if features["operation-exact"]:
        evidence.append("exact-operation-token")
    if features["capability-name"]:
        evidence.append("capability-token")
    if features["signature-hint"]:
        evidence.append("signature-contract")
    if features["call-context"]:
        evidence.append("call-context")
    if features["public-api"]:
        evidence.append("public-api")
    if features["hal-abstraction"]:
        evidence.append("hal-layer")
    if features["controller-api"]:
        evidence.append("controller-api")
    if features["driver-path"]:
        evidence.append("driver-path")
    if features["parameterized-toggle"]:
        evidence.append("parameterized-toggle")
    layer_support = max(
        features["public-api"],
        features["hal-abstraction"],
        features["controller-api"],
        features["driver-path"],
    )
    contract_support = max(
        features["signature-hint"],
        features["call-context"],
        features["parameterized-toggle"],
    )
    if features["operation-exact"] and features["capability-name"] and layer_support and contract_support:
        return 3, evidence, 0.94
    if features["operation-exact"] and features["capability-name"] and (layer_support or contract_support):
        return 2, evidence, 0.86
    if features["operation-exact"] and (features["capability-name"] or contract_support):
        return 1, evidence, 0.68
    return 0, evidence or ["insufficient-positive-evidence"], 0.80


def operation_query_text(capability: str, operation: str) -> str:
    return OPERATION_DESCRIPTIONS[f"{capability}.{operation}"]


def candidate_code_text(function: dict[str, Any]) -> str:
    includes = " ".join(function.get("includes", [])[:12])
    calls = " ".join(function.get("calls", [])[:20])
    return (
        f"file: {function.get('file', '')}\n"
        f"symbol: {function.get('name', '')}\n"
        f"signature: {function.get('signature', '')}\n"
        f"includes: {includes}\n"
        f"calls: {calls}"
    )
