from __future__ import annotations

from typing import Any
from pathlib import Path

from bspforge.common import stable_id, utc_now
from bspforge.semantic_resolver.learning import LearnedRanker


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

DEFAULT_EVIDENCE_WEIGHTS = {
    "name-capability": 0.30,
    "name-action": 0.16,
    "path": 0.16,
    "signature": 0.10,
    "include": 0.10,
    "call-context": 0.10,
    "macro-context": 0.08,
}


class SemanticResolver:
    """Rank SDK functions using independent, auditable static evidence."""

    def resolve(
        self,
        ir: dict[str, Any],
        capability_names: list[str] | None = None,
        threshold: float = 0.42,
        top_k: int = 8,
        evidence_weights: dict[str, float] | None = None,
        method: str = "weighted",
        model_path: Path | None = None,
    ) -> dict[str, Any]:
        weights = {**DEFAULT_EVIDENCE_WEIGHTS, **(evidence_weights or {})}
        unknown = set(weights).difference(DEFAULT_EVIDENCE_WEIGHTS)
        if unknown:
            raise ValueError(f"Unknown evidence types: {sorted(unknown)}")
        if any(value < 0 for value in weights.values()):
            raise ValueError("Evidence weights must be non-negative")
        capabilities = capability_names or list(DEFAULT_CAPABILITIES)
        ranker = (
            LearnedRanker(model_path)
            if method == "learned" and model_path is not None
            else None
        )
        if method == "learned" and ranker is None:
            raise ValueError("learned resolver requires model_path")
        if method not in {"weighted", "learned"}:
            raise ValueError("resolver method must be 'weighted' or 'learned'")
        mappings: list[dict[str, Any]] = []
        for capability in capabilities:
            spec = DEFAULT_CAPABILITIES.get(capability)
            if spec is None:
                raise ValueError(f"Unknown capability: {capability}")
            candidates = [
                self._candidate(capability, spec, function, weights)
                for function in ir["functions"]
            ]
            candidates = [item for item in candidates if item["score"] > 0]
            if method == "learned":
                assert ranker is not None
                ranker.score(candidates, {item["id"]: item for item in ir["functions"]})
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
            "method": (
                "lightgbm-lambdarank-multi-evidence-resolution"
                if method == "learned"
                else "weighted-multi-evidence-static-resolution"
            ),
            "baseline_method": "weighted-multi-evidence-static-resolution",
            "evidence_weights": weights,
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
    def _candidate(
        capability: str,
        spec: dict[str, Any],
        function: dict[str, Any],
        weights: dict[str, float],
    ) -> dict[str, Any]:
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

        name_terms = [term for term in terms if term in name]
        action_terms = [term for term in actions if term in name]
        canonical_bonus = 0.0
        for term in name_terms:
            for action in action_terms:
                prefix = f"{term}_{action}"
                if name == prefix or name.startswith(f"{prefix}_"):
                    suffix_parts = max(0, name.count("_") - prefix.count("_"))
                    canonical_bonus = max(
                        canonical_bonus,
                        weights["name-action"] * 0.5 / (1 + suffix_parts),
                    )
        add("name-capability", weights["name-capability"], name_terms)
        add("name-action", weights["name-action"] + canonical_bonus, action_terms)
        add("path", weights["path"], [term for term in terms if term in path])
        add("signature", weights["signature"], [term for term in terms if term in signature])
        add("include", weights["include"], [term for term in terms if term in includes])
        add("call-context", weights["call-context"], [term for term in terms if term in calls])
        add("macro-context", weights["macro-context"], [term for term in terms if term in macros])
        return {
            "entity_id": function["id"],
            "symbol": function["name"],
            "score": round(min(score, 1.0), 3),
            "source": function["evidence"],
            "evidence": evidence,
            "capability": capability,
            "operations": sorted({term for term in actions if term in name}),
        }
