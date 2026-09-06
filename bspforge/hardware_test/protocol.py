from __future__ import annotations

import json
from typing import Any


PROTOCOL_VERSION = "1.0"
DEFAULT_COMMANDS = [
    "info",
    "clock.basic",
    "interrupt.basic",
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
    marker = '{"bspforge":'
    marker_index = text.find(marker)
    if marker_index < 0:
        return None
    # RTOS consoles may leave an ANSI reset sequence or shell prompt on the
    # same physical line immediately before the machine-readable event.
    text = text[marker_index:]
    try:
        event, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"invalid BSPForge event: {error}") from error
    if event.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version: {event.get('protocol')}")
    return event
