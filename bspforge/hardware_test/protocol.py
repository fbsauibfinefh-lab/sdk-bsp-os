from __future__ import annotations

import json
from typing import Any


PROTOCOL_VERSION = "1.0"
DEFAULT_COMMANDS = [
    "info",
    "uart.loopback",
    "gpio.toggle",
    "gpio.irq",
    "timer.oneshot",
    "timer.periodic",
    "stability",
]


class ProtocolError(ValueError):
    pass


def request_line(request_id: str, command: str) -> bytes:
    if command not in DEFAULT_COMMANDS:
        raise ProtocolError(f"unknown self-test command: {command}")
    return f"bspforge_selftest {request_id} {command}\r\n".encode("ascii")


def parse_event(line: bytes | str) -> dict[str, Any] | None:
    text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
    text = text.strip()
    if not text.startswith('{"bspforge":'):
        return None
    try:
        event = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"invalid BSPForge event: {error}") from error
    if event.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version: {event.get('protocol')}")
    return event
