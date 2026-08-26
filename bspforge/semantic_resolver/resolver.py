from __future__ import annotations

from typing import Any
from pathlib import Path
from statistics import mean

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.common import stable_id, utc_now
from bspforge.compile_feedback import feedback_index
from bspforge.operation_constraints import compatibility, contract_adjustment
from bspforge.operation_ranking import operation_feature_map, operation_static_score
from bspforge.semantic_adapter import OperationSemanticRanker
from bspforge.semantic_resolver.learning import LearnedRanker


DEFAULT_CAPABILITIES = {
    "uart": {
        "terms": ["uart", "uarths", "serial", "usart", "sci", "baud"],
        "actions": ["init", "deinit", "configure", "send", "receive", "read", "write", "irq"],
        "target_api": "RT-Thread serial device",
    },
    "gpio": {
        "terms": ["gpio", "gpiohs", "pin", "fpioa", "port", "dio"],
        "actions": ["init", "deinit", "configure", "drive", "set", "get", "read", "write", "toggle", "mode", "irq"],
        "target_api": "RT-Thread pin device",
    },
    "timer": {
        "terms": ["timer", "tim", "gptimer", "ctimer", "tcpwm", "alarm", "tick", "clint", "mtime", "counter", "tmr"],
        "actions": ["init", "deinit", "start", "stop", "enable", "disable", "setup", "read", "capture", "register", "irq", "interval"],
        "target_api": "RT-Thread timer/tick service",
    },
    "interrupt": {
        "terms": ["plic", "interrupt", "irq", "isr", "intr", "nvic", "sysint", "trap"],
        "actions": ["init", "enable", "disable", "register", "alloc", "free", "set", "clear", "priority", "pending", "claim", "handler", "trigger"],
        "target_api": "RT-Thread interrupt subsystem",
    },
    "clock": {
        "terms": ["sysctl", "clock", "clk", "pll", "frequency", "rcc"],
        "actions": ["init", "configure", "enable", "disable", "start", "stop", "set", "get", "freq"],
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

DEFAULT_SEMANTIC_WEIGHTS = {
    "static": 0.30,
    "base": 0.20,
    "adapted": 0.50,
    "field": 0.0,
}


class SemanticResolver:
    """Rank SDK functions using independent, auditable static evidence."""

    def candidate_pool(
        self,
        ir: dict[str, Any],
        capability: str,
        evidence_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        spec = DEFAULT_CAPABILITIES.get(capability)
        if spec is None:
            raise ValueError(f"Unknown capability: {capability}")
        weights = {**DEFAULT_EVIDENCE_WEIGHTS, **(evidence_weights or {})}
        unknown = set(weights).difference(DEFAULT_EVIDENCE_WEIGHTS)
        if unknown:
            raise ValueError(f"Unknown evidence types: {sorted(unknown)}")
        if any(value < 0 for value in weights.values()):
            raise ValueError("Evidence weights must be non-negative")
        candidates = [
            self._candidate(capability, spec, function, weights)
            for function in ir["functions"]
        ]
        candidates = [item for item in candidates if item["score"] > 0]
        candidates.sort(key=lambda item: (-item["score"], item["entity_id"]))
        return candidates

    def resolve(
        self,
        ir: dict[str, Any],
        capability_names: list[str] | None = None,
        threshold: float = 0.42,
        top_k: int = 8,
        evidence_weights: dict[str, float] | None = None,
        method: str = "weighted",
        model_path: Path | None = None,
        hybrid_weight: float | None = None,
        operation_min_margin: float = 0.0,
        semantic_weights: dict[str, float] | None = None,
        semantic_candidate_top_k: int = 0,
        semantic_device: str = "cpu",
        operation_constraint_weight: float = 0.0,
        compile_feedback: dict[str, Any] | None = None,
        compile_feedback_weight: float = 0.0,
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
            if method in {"learned", "hybrid"} and model_path is not None
            else None
        )
        semantic_ranker = (
            OperationSemanticRanker(model_path, device=semantic_device)
            if method == "operation-semantic" and model_path is not None
            else None
        )
        if method in {"learned", "hybrid"} and ranker is None:
            raise ValueError(f"{method} resolver requires model_path")
        if method == "operation-semantic" and semantic_ranker is None:
            raise ValueError("operation-semantic resolver requires model_path")
        if method not in {
            "weighted", "learned", "hybrid", "operation-weighted", "operation-semantic"
        }:
            raise ValueError(
                "unsupported resolver method"
            )
        if operation_min_margin < 0.0:
            raise ValueError("operation_min_margin must be non-negative")
        selected_semantic_weights = {
            **DEFAULT_SEMANTIC_WEIGHTS,
            **(semantic_weights or {}),
        }
        unknown_semantic = set(selected_semantic_weights).difference(DEFAULT_SEMANTIC_WEIGHTS)
        if unknown_semantic:
            raise ValueError(f"Unknown semantic weights: {sorted(unknown_semantic)}")
        if any(value < 0 for value in selected_semantic_weights.values()):
            raise ValueError("semantic weights must be non-negative")
        if not abs(sum(selected_semantic_weights.values()) - 1.0) < 1e-9:
            raise ValueError("semantic weights must sum to 1.0")
        if semantic_candidate_top_k < 0:
            raise ValueError("semantic_candidate_top_k must be non-negative")
        if operation_constraint_weight < 0.0:
            raise ValueError("operation_constraint_weight must be non-negative")
        if not 0.0 <= compile_feedback_weight <= 1.0:
            raise ValueError("compile_feedback_weight must be between 0 and 1")
        previous_feedback = feedback_index(compile_feedback or {})
        selected_hybrid_weight = 0.0
        if method == "hybrid":
            assert ranker is not None
            selected_hybrid_weight = float(
                hybrid_weight
                if hybrid_weight is not None
                else ranker.metadata.get("recommended_hybrid_weight", 0.75)
            )
            if not 0.0 <= selected_hybrid_weight <= 1.0:
                raise ValueError("hybrid_weight must be between 0 and 1")
        mappings: list[dict[str, Any]] = []
        for capability in capabilities:
            spec = DEFAULT_CAPABILITIES.get(capability)
            if spec is None:
                raise ValueError(f"Unknown capability: {capability}")
            candidates = self.candidate_pool(ir, capability, weights)
            if method in {"operation-weighted", "operation-semantic"}:
                operation_resolution = self._resolve_operations(
                    capability,
                    candidates,
                    {item["id"]: item for item in ir["functions"]},
                    threshold,
                    top_k,
                    operation_min_margin,
                    semantic_ranker=semantic_ranker,
                    semantic_weights=selected_semantic_weights,
                    semantic_candidate_top_k=semantic_candidate_top_k,
                    operation_constraint_weight=operation_constraint_weight,
                    compile_feedback=previous_feedback,
                    compile_feedback_weight=compile_feedback_weight,
                )
                mappings.append({
                    "id": stable_id(ir["sdk"]["id"], "mapping", capability),
                    "capability": capability,
                    "target_api": spec["target_api"],
                    "threshold": threshold,
                    "accepted": operation_resolution["accepted"],
                    "candidates": operation_resolution["candidates"],
                    "operation_rankings": operation_resolution["operation_rankings"],
                    "minimum_margin": operation_min_margin,
                    "semantic_candidate_top_k": semantic_candidate_top_k,
                    "status": "resolved" if operation_resolution["accepted"] else "unresolved",
                })
                continue
            if method in {"learned", "hybrid"}:
                assert ranker is not None
                ranker.score(
                    candidates,
                    {item["id"]: item for item in ir["functions"]},
                    baseline_weight=selected_hybrid_weight,
                )
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
                "operation-aware-semantic-adapter-resolution"
                if method == "operation-semantic"
                else "operation-aware-static-resolution"
                if method == "operation-weighted"
                else (
                    "weighted-lightgbm-hybrid-resolution"
                    if method == "hybrid"
                    else (
                        "lightgbm-lambdarank-multi-evidence-resolution"
                        if method == "learned"
                        else "weighted-multi-evidence-static-resolution"
                    )
                )
            ),
            "baseline_method": "weighted-multi-evidence-static-resolution",
            "hybrid_weight": selected_hybrid_weight if method == "hybrid" else None,
            "semantic_weights": selected_semantic_weights if method == "operation-semantic" else None,
            "semantic_model": semantic_ranker.metadata if semantic_ranker is not None else None,
            "operation_constraint_weight": operation_constraint_weight,
            "compile_feedback_weight": compile_feedback_weight,
            "evidence_weights": weights,
            "mappings": mappings,
            "summary": {
                "requested": len(mappings),
                "resolved": sum(item["status"] == "resolved" for item in mappings),
                "accepted_entities": sum(len(item["accepted"]) for item in mappings),
            },
        }

    @staticmethod
    def _resolve_operations(
        capability: str,
        candidates: list[dict[str, Any]],
        functions: dict[str, dict[str, Any]],
        threshold: float,
        top_k: int,
        minimum_margin: float,
        semantic_ranker: OperationSemanticRanker | None = None,
        semantic_weights: dict[str, float] | None = None,
        semantic_candidate_top_k: int = 0,
        operation_constraint_weight: float = 0.0,
        compile_feedback: dict[tuple[str, str, str], float] | None = None,
        compile_feedback_weight: float = 0.0,
    ) -> dict[str, Any]:
        operation_rankings = []
        accepted_by_entity: dict[str, dict[str, Any]] = {}
        all_ranked: dict[str, dict[str, Any]] = {}
        operations = list(CAPABILITY_SCHEMA[capability]["operations"])
        semantic_scores = (
            semantic_ranker.score_operations(capability, operations, candidates, functions)
            if semantic_ranker is not None
            else None
        )
        selected_semantic_weights = {
            **DEFAULT_SEMANTIC_WEIGHTS,
            **(semantic_weights or {}),
        }
        selected_for_capability: list[tuple[str, dict[str, Any]]] = []
        for operation in operations:
            ranked = []
            for candidate in candidates:
                item = dict(candidate)
                features = operation_feature_map(
                    capability, operation, item, functions[item["entity_id"]]
                )
                item["baseline_score"] = candidate["score"]
                item["operation_score"] = operation_static_score(features)
                item["score"] = item["operation_score"]
                item["operation_features"] = features
                item["target_operations"] = [operation]
                ranked.append(item)
            if semantic_scores is not None:
                static_ranked = sorted(
                    ranked, key=lambda item: (-item["operation_score"], item["entity_id"])
                )
                pool = {
                    item["entity_id"]
                    for item in static_ranked[:semantic_candidate_top_k]
                } if semantic_candidate_top_k else {item["entity_id"] for item in ranked}
                for item in ranked:
                    values = semantic_scores[operation][item["entity_id"]]
                    item["semantic_scores"] = {
                        "base": round(values["base"], 6),
                        "adapted": round(values["adapted"], 6),
                        "field": round(values.get("field", 0.0), 6),
                    }
                    item["semantic_candidate"] = item["entity_id"] in pool
                    if item["semantic_candidate"]:
                        item["score"] = round(
                            selected_semantic_weights["static"] * item["operation_score"]
                            + selected_semantic_weights["base"] * values["base"]
                            + selected_semantic_weights["adapted"] * values["adapted"]
                            + selected_semantic_weights["field"] * values.get("field", 0.0),
                            6,
                        )
            if operation_constraint_weight:
                for item in ranked:
                    adjustment, constraint_evidence = contract_adjustment(item)
                    pair_values = [
                        compatibility(
                            capability, operation, item, previous_operation, previous
                        )[0]
                        for previous_operation, previous in selected_for_capability
                    ]
                    pair_support = mean(pair_values) if pair_values else 0.0
                    item["constraint_scores"] = {
                        "contract": round(adjustment, 6),
                        "api_family": round(pair_support, 6),
                        "evidence": constraint_evidence,
                    }
                    item["score"] = round(
                        item["score"] + operation_constraint_weight * (adjustment + pair_support),
                        6,
                    )
            if compile_feedback_weight:
                for item in ranked:
                    feedback_score = (compile_feedback or {}).get(
                        (capability, operation, item["entity_id"]), 0.5
                    )
                    item["compile_feedback_score"] = feedback_score
                    item["score"] = round(
                        (1.0 - compile_feedback_weight) * item["score"]
                        + compile_feedback_weight * feedback_score,
                        6,
                    )
            if semantic_scores is not None:
                ranked.sort(
                    key=lambda item: (
                        -int(item.get("semantic_candidate", True)),
                        -item["score"],
                        item["entity_id"],
                    )
                )
            else:
                ranked.sort(key=lambda item: (-item["score"], item["entity_id"]))
            top = ranked[:top_k]
            runner_up = next(
                (item for item in top[1:] if top and item["symbol"] != top[0]["symbol"]),
                None,
            )
            margin = (
                top[0]["score"] - runner_up["score"]
                if top and runner_up is not None
                else top[0]["score"] if top else 0.0
            )
            selected = (
                top[0]
                if top
                and top[0]["score"] >= min(threshold, 0.30)
                and margin >= minimum_margin
                else None
            )
            operation_rankings.append({
                "operation": operation,
                "selected_entity_id": selected["entity_id"] if selected else None,
                "selected_symbol": selected["symbol"] if selected else None,
                "confidence_margin": round(margin, 6),
                "abstained": bool(top and selected is None),
                "candidates": top,
            })
            for item in top:
                current = all_ranked.get(item["entity_id"])
                if current is None or item["score"] > current["score"]:
                    all_ranked[item["entity_id"]] = dict(item)
            if selected:
                selected_for_capability.append((operation, selected))
                current = accepted_by_entity.get(selected["entity_id"])
                if current is None:
                    accepted_by_entity[selected["entity_id"]] = dict(selected)
                else:
                    current["target_operations"] = sorted(
                        set(current["target_operations"] + [operation])
                    )
                    current["score"] = max(current["score"], selected["score"])
        accepted = sorted(
            accepted_by_entity.values(), key=lambda item: (-item["score"], item["entity_id"])
        )
        ranked_candidates = sorted(
            all_ranked.values(), key=lambda item: (-item["score"], item["entity_id"])
        )
        return {
            "accepted": accepted,
            "candidates": ranked_candidates[:top_k],
            "operation_rankings": operation_rankings,
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
