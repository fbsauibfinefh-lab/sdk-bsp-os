from __future__ import annotations

from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA, operation_matches
from bspforge.common import stable_id, utc_now


class BindingPlanner:
    """Convert ranked SDK entities into a target-independent operation plan."""

    def plan(self, ir: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
        functions = {item["id"]: item for item in ir["functions"]}
        mappings = {item["capability"]: item for item in resolution["mappings"]}
        capabilities: list[dict[str, Any]] = []
        for capability, specification in CAPABILITY_SCHEMA.items():
            mapping = mappings.get(capability, {"accepted": [], "candidates": []})
            accepted = mapping.get("accepted", [])
            operations: list[dict[str, Any]] = []
            for operation, aliases in specification["operations"].items():
                candidates = [
                    candidate
                    for candidate in accepted
                    if operation_matches(
                        candidate["symbol"],
                        aliases,
                        candidate.get("operations", []),
                    )
                ]
                candidates.sort(key=lambda item: (-item["score"], item["entity_id"]))
                selected = candidates[0] if candidates else None
                entity = functions.get(selected["entity_id"]) if selected else None
                operations.append({
                    "operation": operation,
                    "status": "inferred" if selected else "missing",
                    "selected_symbol": selected["symbol"] if selected else None,
                    "entity_id": selected["entity_id"] if selected else None,
                    "signature": entity.get("signature") if entity else None,
                    "confidence": selected["score"] if selected else 0.0,
                    "alternatives": [
                        {"symbol": item["symbol"], "entity_id": item["entity_id"], "score": item["score"]}
                        for item in candidates[1:4]
                    ],
                    "parameter_sources": self._parameter_sources(entity),
                    "evidence": selected.get("evidence", []) if selected else [],
                })
            inferred = sum(item["status"] == "inferred" for item in operations)
            capabilities.append({
                "capability": capability,
                "status": (
                    "resolved"
                    if inferred == len(operations)
                    else "partial"
                    if inferred
                    else "unsupported"
                ),
                "operations": operations,
            })
        all_operations = [item for capability in capabilities for item in capability["operations"]]
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "id": stable_id(ir["sdk"]["digest"], "canonical-binding-plan"),
            "sdk_id": ir["sdk"]["id"],
            "method": "capability-schema-and-ranked-evidence",
            "capabilities": capabilities,
            "summary": {
                "capabilities": len(capabilities),
                "resolved_capabilities": sum(item["status"] == "resolved" for item in capabilities),
                "operations": len(all_operations),
                "inferred_operations": sum(item["status"] == "inferred" for item in all_operations),
                "missing_operations": sum(item["status"] == "missing" for item in all_operations),
            },
        }

    @staticmethod
    def _parameter_sources(entity: dict[str, Any] | None) -> list[dict[str, str]]:
        if entity is None:
            return []
        signature = entity.get("signature", "").lower()
        sources: list[dict[str, str]] = []
        for token, source in (
            ("pin", "board-or-sdk-constant"),
            ("baud", "board-policy"),
            ("clock", "sdk-clock-model"),
            ("irq", "sdk-enumeration"),
            ("channel", "board-policy"),
            ("handle", "sdk-instance-object"),
            ("base", "sdk-instance-object"),
        ):
            if token in signature:
                sources.append({"parameter": token, "source": source})
        return sources
