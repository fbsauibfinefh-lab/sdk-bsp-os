from __future__ import annotations

import re
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA


def validate_operation_plan(
    ir: dict[str, Any],
    binding_plan: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Validate and index every operation selected by the semantic stage."""
    if binding_plan is None:
        raise ValueError("generated SDK bindings require a canonical binding plan")
    entities = {item["id"]: item for item in ir["functions"]}
    capabilities = {
        item["capability"]: item for item in binding_plan.get("capabilities", [])
        if item.get("status") in {"resolved", "partial"}
    }
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for capability, planned in capabilities.items():
        specification = CAPABILITY_SCHEMA.get(capability)
        if specification is None:
            raise ValueError(f"binding plan has unknown capability: {capability}")
        operations = {item["operation"]: item for item in planned["operations"]}
        result[capability] = {}
        for operation in specification["operations"]:
            item = operations.get(operation)
            if item is None or item.get("status") != "inferred":
                raise ValueError(f"binding plan misses operation: {capability}.{operation}")
            entity = entities.get(item.get("entity_id"))
            if entity is None:
                raise ValueError(
                    f"binding plan entity is absent from IR: {capability}.{operation}"
                )
            if entity["name"] != item.get("selected_symbol"):
                raise ValueError(
                    f"binding plan symbol/entity mismatch: {capability}.{operation}"
                )
            result[capability][operation] = {
                **item,
                "signature": entity.get("signature"),
                "source": entity.get("evidence"),
                "file": entity.get("file"),
            }
    return result


def render_operation_symbols(
    template: str,
    selections: dict[str, dict[str, dict[str, Any]]],
) -> str:
    rendered = template
    for capability, operations in selections.items():
        for operation, item in operations.items():
            rendered = rendered.replace(
                f"@OP:{capability}.{operation}@", item["selected_symbol"]
            )
    unresolved = sorted(set(re.findall(r"@OP:[a-z_.]+@", rendered)))
    if unresolved:
        raise ValueError(f"unresolved operation placeholders: {', '.join(unresolved)}")
    return rendered


def function_declarations(
    function_index: dict[str, list[dict[str, Any]]],
    symbols: list[str],
) -> list[str]:
    """Render evidence-backed prototypes for callable SDK definitions."""
    declarations = []
    for symbol in dict.fromkeys(symbols):
        matches = function_index.get(symbol, [])
        if not matches:
            continue
        signature = str(matches[0].get("signature", "")).strip().rstrip(";")
        if signature:
            declarations.append(f"{signature};")
    return sorted(set(declarations))


def operation_manifest(
    selections: dict[str, dict[str, dict[str, Any]]],
    generated_source: str,
    *,
    replaced_operations: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    replaced = replaced_operations or set()
    records = []
    for capability, operations in selections.items():
        for operation, item in operations.items():
            symbol = item["selected_symbol"]
            disposition = (
                "replaced-by-os-backend"
                if (capability, operation) in replaced
                else "direct-generated-call"
            )
            direct_call = bool(
                re.search(rf"\b{re.escape(symbol)}\s*\(", generated_source)
            )
            if disposition == "direct-generated-call" and not direct_call:
                raise ValueError(
                    f"generated source does not call selected operation: "
                    f"{capability}.{operation} -> {symbol}"
                )
            records.append({
                "capability": capability,
                "operation": operation,
                "selected_symbol": symbol,
                "entity_id": item["entity_id"],
                "signature": item["signature"],
                "source": item["source"],
                "decoder": item.get("decoder"),
                "disposition": disposition,
                "direct_call_in_generated_source": direct_call,
            })
    return records
