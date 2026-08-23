from __future__ import annotations

from typing import Any

from bspforge.common import stable_id, utc_now


DEFAULT_CAPABILITIES = {
    "uart": {
        "terms": ["uart", "uarths", "serial", "baud"],
        "actions": ["init", "configure", "send", "receive", "irq"],
        "target_api": "RT-Thread serial device",
    },
    "gpio": {
        "terms": ["gpio", "gpiohs", "pin", "fpioa"],
        "actions": ["init", "drive", "set", "get", "mode", "irq"],
        "target_api": "RT-Thread pin device",
    },
    "timer": {
        "terms": ["timer", "tick", "clint", "mtime"],
        "actions": ["init", "start", "stop", "irq", "interval"],
        "target_api": "RT-Thread timer/tick service",
    },
    "interrupt": {
        "terms": ["plic", "interrupt", "irq", "trap"],
        "actions": ["init", "enable", "disable", "register", "claim"],
        "target_api": "RT-Thread interrupt subsystem",
    },
    "clock": {
        "terms": ["sysctl", "clock", "pll", "frequency"],
        "actions": ["init", "enable", "disable", "set", "get"],
        "target_api": "RT-Thread board clock initialization",
    },
}


class SemanticResolver:
    """Rank SDK functions using independent, auditable static evidence."""

    def resolve(
        self,
        ir: dict[str, Any],
        capability_names: list[str] | None = None,
        threshold: float = 0.42,
        top_k: int = 8,
    ) -> dict[str, Any]:
        capabilities = capability_names or list(DEFAULT_CAPABILITIES)
        mappings: list[dict[str, Any]] = []
        for capability in capabilities:
            spec = DEFAULT_CAPABILITIES.get(capability)
            if spec is None:
                raise ValueError(f"Unknown capability: {capability}")
            candidates = [self._candidate(capability, spec, function) for function in ir["functions"]]
            candidates = [item for item in candidates if item["score"] > 0]
            candidates.sort(key=lambda item: (-item["score"], item["entity_id"]))
            accepted = self._operation_cover(candidates[:top_k], threshold)
            mappings.append({
                "id": stable_id(ir["sdk"]["id"], "mapping", capability),
                "capability": capability,
                "target_api": spec["target_api"],
                "threshold": threshold,
                "accepted": accepted,
                "candidates": candidates[:top_k],
                "status": "resolved" if accepted else "unresolved",
            })
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "sdk_id": ir["sdk"]["id"],
            "sdk_digest": ir["sdk"]["digest"],
            "method": "weighted-multi-evidence-static-resolution",
            "mappings": mappings,
            "summary": {
                "requested": len(mappings),
                "resolved": sum(item["status"] == "resolved" for item in mappings),
                "accepted_entities": sum(len(item["accepted"]) for item in mappings),
            },
        }

    @staticmethod
    def _operation_cover(candidates: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
        """Keep high-scoring candidates that add a distinct device operation."""
        accepted: list[dict[str, Any]] = []
        covered: set[str] = set()
        for candidate in candidates:
            if candidate["score"] < threshold:
                continue
            operations = set(candidate["operations"])
            if not accepted or operations.difference(covered):
                accepted.append(candidate)
                covered.update(operations)
        return accepted

    @staticmethod
    def _candidate(capability: str, spec: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
        name = function["name"].lower()
        path = function["file"].lower()
        signature = function["signature"].lower()
        includes = " ".join(function["includes"]).lower()
        calls = " ".join(function["calls"]).lower()
        macros = " ".join(function["nearby_macros"]).lower()
        terms = spec["terms"]
        actions = spec["actions"]

        evidence: list[dict[str, Any]] = []
        score = 0.0

        def add(kind: str, weight: float, matches: list[str]) -> None:
            nonlocal score
            if matches:
                score += weight
                evidence.append({"kind": kind, "weight": weight, "matches": sorted(set(matches))})

        add("name-capability", 0.30, [term for term in terms if term in name])
        add("name-action", 0.16, [term for term in actions if term in name])
        add("path", 0.16, [term for term in terms if term in path])
        add("signature", 0.10, [term for term in terms if term in signature])
        add("include", 0.10, [term for term in terms if term in includes])
        add("call-context", 0.10, [term for term in terms if term in calls])
        add("macro-context", 0.08, [term for term in terms if term in macros])
        return {
            "entity_id": function["id"],
            "symbol": function["name"],
            "score": round(min(score, 1.0), 3),
            "source": function["evidence"],
            "evidence": evidence,
            "capability": capability,
            "operations": sorted({term for term in actions if term in name}),
        }
