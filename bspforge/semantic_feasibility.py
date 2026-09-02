from __future__ import annotations

from typing import Any

from bspforge.hardware_effect_graph import identifier_tokens
from bspforge.multiview_effect_ranker import operation_constraint_penalty


NON_DRIVER_ROLES = {"documentation", "middleware", "os-adapter"}
STRONG_INTERRUPT_CONTROLLER_TERMS = {
    "clic", "eclic", "gic", "intc", "nvic", "plic", "vector"
}
INTERRUPT_CONTROLLER_TERMS = STRONG_INTERRUPT_CONTROLLER_TERMS | {
    "interrupt", "irq", "priority"
}
DEVICE_SUBSYSTEM_TERMS = {
    "audio",
    "camera",
    "display",
    "eth",
    "ethernet",
    "ethosu",
    "gfx",
    "gpu",
    "i2c",
    "lcd",
    "sd",
    "spi",
    "systick",
    "timer",
    "lptimer",
    "usb",
    "usbd",
    "usbh",
    "viv",
}
REGISTER_ACTION_TERMS = {"attach", "callback", "handler", "install", "register", "vector"}


def _path_tokens(path: str) -> set[str]:
    return set(identifier_tokens(path.replace("\\", "/")))


def _architecture_penalty(path: str, target_architecture: str | None) -> float:
    if not target_architecture:
        return 0.0
    normalized = "/" + path.lower().replace("\\", "/") + "/"
    architecture = target_architecture.lower().replace("_", "-")
    if "cortex-m" in architecture or architecture.startswith("armv7-m") or architecture.startswith("armv8-m"):
        if "/core_a/" in normalized or "/core_r/" in normalized:
            return 1.0
        if "/gic" in normalized or "irq_ctrl_gic" in normalized:
            return 1.0
    if "riscv" in architecture and "/cmsis/" in normalized:
        return 1.0
    return 0.0


def semantic_feasibility_penalty(
    group: dict[str, Any],
    candidate: dict[str, Any],
    *,
    target_architecture: str | None = None,
) -> float:
    """Return a label-independent exclusion penalty for infeasible SDK bindings."""
    penalty = operation_constraint_penalty(candidate, group["operation_id"])
    features = candidate["features"]
    source_role = candidate.get("source_role", "unknown")
    if source_role in NON_DRIVER_ROLES:
        penalty = max(penalty, 1.0)
    if source_role == "example-test" and (
        float(features.get("test-example", 0.0)) > 0.0
        or float(features.get("hw-example-likelihood", 0.0)) >= 0.5
        or float(features.get("hw-internal-callback-likelihood", 0.0)) >= 0.5
    ):
        penalty = max(penalty, 1.0)

    path = candidate.get("file", "")
    penalty = max(penalty, _architecture_penalty(path, target_architecture))
    capability, action = group["operation_id"].split(".", 1)
    tokens = set(identifier_tokens(candidate["symbol"])) | _path_tokens(path)
    callback_terms = {"callback", "handler", "isr"}
    if action not in {"register", "attach_irq"} and tokens & callback_terms:
        write_effect = max(
            float(features.get("hw-write-access", 0.0)),
            float(features.get("hw-bitwise-update", 0.0)),
            float(features.get("hw-mmio-access", 0.0)),
        )
        if write_effect < 0.25:
            penalty = max(penalty, 1.0)
    if capability != "interrupt":
        return min(1.0, penalty)

    has_strong_controller_scope = bool(tokens & STRONG_INTERRUPT_CONTROLLER_TERMS)
    has_controller_scope = bool(tokens & INTERRUPT_CONTROLLER_TERMS)
    has_device_scope = bool(tokens & DEVICE_SUBSYSTEM_TERMS)
    if action == "register" and not (tokens & REGISTER_ACTION_TERMS):
        penalty = max(penalty, 1.0)
    if action == "initialize" and not (
        tokens & {"config", "configure", "grouping", "init", "initialize", "priority", "setup"}
    ):
        penalty = max(penalty, 1.0)
    if action in {"enable", "disable"} and not has_controller_scope:
        penalty = max(penalty, 1.0)
    if action in {"initialize", "enable", "disable", "register"}:
        if has_device_scope and not has_strong_controller_scope:
            penalty = max(penalty, 1.0)
    return min(1.0, penalty)
