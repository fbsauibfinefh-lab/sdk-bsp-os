from __future__ import annotations

from typing import Any


CAPABILITY_SCHEMA: dict[str, dict[str, Any]] = {
    "clock": {
        "operations": {
            "initialize": ["init", "configure", "set"],
            "enable": ["enable"],
            "disable": ["disable"],
            "get_frequency": ["get", "frequency", "freq"],
        },
    },
    "interrupt": {
        "operations": {
            "initialize": ["init", "priority", "configure"],
            "enable": ["enable"],
            "disable": ["disable"],
            "register": ["register", "attach", "setvector"],
        },
    },
    "uart": {
        "operations": {
            "configure": ["init", "configure", "setup"],
            "write": ["send", "write", "put", "transmit"],
            "read": ["receive", "read", "get"],
        },
    },
    "gpio": {
        "operations": {
            "configure": ["init", "mode", "drive", "setup"],
            "write": ["write", "set"],
            "read": ["read", "get"],
            "attach_irq": ["irq", "interrupt", "register"],
        },
    },
    "timer": {
        "operations": {
            "initialize": ["init", "configure"],
            "start": ["start", "enable"],
            "stop": ["stop", "disable"],
            "set_interval": ["interval", "period", "compare"],
        },
    },
}


def operation_matches(symbol: str, aliases: list[str], inferred: list[str]) -> bool:
    normalized = symbol.lower().replace("_", "")
    return any(alias in normalized for alias in aliases) or bool(set(aliases).intersection(inferred))
