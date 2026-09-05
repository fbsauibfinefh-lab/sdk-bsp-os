from __future__ import annotations

import re
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA, operation_matches
from bspforge.common import stable_id, utc_now
from bspforge.structured_retrieval import api_family_key


class BindingPlanner:
    """Convert ranked SDK entities into a target-independent operation plan."""

    def plan(
        self,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        decoder: str = "top1",
    ) -> dict[str, Any]:
        if decoder not in {"top1", "signature-family"}:
            raise ValueError(f"Unsupported binding decoder: {decoder}")
        functions = {item["id"]: item for item in ir["functions"]}
        mappings = {item["capability"]: item for item in resolution["mappings"]}
        capabilities: list[dict[str, Any]] = []
        for capability, specification in CAPABILITY_SCHEMA.items():
            mapping = mappings.get(capability, {"accepted": [], "candidates": []})
            accepted = mapping.get("accepted", [])
            decoded = (
                self._decode_signature_family(capability, mapping, functions)
                if decoder == "signature-family"
                else {}
            )
            operations: list[dict[str, Any]] = []
            for operation, aliases in specification["operations"].items():
                if decoder == "signature-family":
                    choice = decoded[operation]
                    candidates = choice["candidates"]
                    selected = choice["selected"]
                else:
                    candidates = [
                        candidate
                        for candidate in accepted
                        if operation in candidate.get("target_operations", [])
                        or (
                            not candidate.get("target_operations")
                            and operation_matches(
                                candidate["symbol"], aliases, candidate.get("operations", [])
                            )
                        )
                    ]
                    selected = None
                candidates.sort(key=lambda item: (-item["score"], item["entity_id"]))
                selected = selected or (candidates[0] if candidates else None)
                entity = functions.get(selected["entity_id"]) if selected else None
                original = choice["original"] if decoder == "signature-family" else selected
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
                    "decoder": (
                        {
                            "method": "signature-family",
                            "api_family": choice["family"],
                            "candidate_rank": choice["rank"],
                            "original_top1_symbol": original["symbol"],
                            "original_top1_entity_id": original["entity_id"],
                            "selection_changed": (
                                selected["entity_id"] != original["entity_id"]
                            ),
                            "rejected_before_selection": choice["rejected"],
                        }
                        if decoder == "signature-family"
                        else {"method": "top1"}
                    ),
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
        selection_fingerprint = "|".join(
            f"{capability['capability']}.{operation['operation']}="
            f"{operation.get('entity_id') or 'missing'}"
            for capability in capabilities
            for operation in capability["operations"]
        )
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "id": stable_id(
                ir["sdk"]["digest"],
                "canonical-binding-plan",
                decoder,
                selection_fingerprint,
            ),
            "sdk_id": ir["sdk"]["id"],
            "method": "capability-schema-and-ranked-evidence",
            "decoder": decoder,
            "capabilities": capabilities,
            "summary": {
                "capabilities": len(capabilities),
                "resolved_capabilities": sum(item["status"] == "resolved" for item in capabilities),
                "operations": len(all_operations),
                "inferred_operations": sum(item["status"] == "inferred" for item in all_operations),
                "missing_operations": sum(item["status"] == "missing" for item in all_operations),
            },
        }

    @classmethod
    def _decode_signature_family(
        cls,
        capability: str,
        mapping: dict[str, Any],
        functions: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        rankings = {
            item["operation"]: item.get("candidates", [])
            for item in mapping.get("operation_rankings", [])
        }
        operations = list(CAPABILITY_SCHEMA[capability]["operations"])
        compatible: dict[str, list[dict[str, Any]]] = {}
        rejected: dict[str, list[dict[str, Any]]] = {}
        for operation in operations:
            rows = rankings.get(operation, [])
            if not rows:
                raise ValueError(
                    f"Signature-family decoder has no candidates: {capability}.{operation}"
                )
            compatible[operation] = []
            rejected[operation] = []
            for rank, row in enumerate(rows, start=1):
                entity = functions.get(row["entity_id"])
                if entity is None:
                    continue
                accepted, reason = cls._signature_compatible(
                    capability,
                    operation,
                    row["symbol"],
                    entity.get("signature", ""),
                )
                enriched = {
                    **row,
                    "candidate_rank": rank,
                    "signature": entity.get("signature"),
                    "file": entity.get("file"),
                    "api_family": cls._compatible_family(
                        capability, row["symbol"]
                    ),
                }
                if accepted:
                    compatible[operation].append(enriched)
                elif len(rejected[operation]) < 8:
                    rejected[operation].append({
                        "rank": rank,
                        "symbol": row["symbol"],
                        "reason": reason,
                    })
            if not compatible[operation]:
                raise ValueError(
                    f"No signature-compatible candidate: {capability}.{operation}"
                )

        common_families = set.intersection(*(
            {item["api_family"] for item in compatible[operation]}
            for operation in operations
        ))
        if not common_families:
            families = {
                operation: sorted({item["api_family"] for item in compatible[operation]})
                for operation in operations
            }
            raise ValueError(
                f"No complete API family for {capability}: {families}"
            )

        family_choices: list[tuple[float, str, dict[str, dict[str, Any]]]] = []
        for family in sorted(common_families):
            selected: dict[str, dict[str, Any]] = {}
            objective = 0.0
            for operation in operations:
                rows = [
                    item for item in compatible[operation]
                    if item["api_family"] == family
                ]
                rows.sort(key=lambda item: (-item["score"], item["entity_id"]))
                selected[operation] = rows[0]
                count = max(1, len(rankings[operation]))
                objective += 1.0 - (rows[0]["candidate_rank"] - 1) / count
            family_choices.append((objective, family, selected))
        _, family, selected = max(family_choices, key=lambda item: (item[0], item[1]))

        return {
            operation: {
                "selected": selected[operation],
                "original": rankings[operation][0],
                "candidates": [
                    item for item in compatible[operation]
                    if item["api_family"] == family
                ],
                "family": family,
                "rank": selected[operation]["candidate_rank"],
                "rejected": rejected[operation],
            }
            for operation in operations
        }

    @staticmethod
    def _compatible_family(capability: str, symbol: str) -> str:
        lowered = symbol.lower()
        if capability == "interrupt" and any(
            marker in lowered for marker in ("sysint", "nvic", "plic")
        ):
            return "system-interrupt-controller"
        return api_family_key(capability, symbol)

    @staticmethod
    def _signature_compatible(
        capability: str,
        operation: str,
        symbol: str,
        signature: str,
    ) -> tuple[bool, str]:
        parameters = BindingPlanner._signature_parameters(signature)
        lowered = " ".join(parameters).lower()
        lowered_symbol = symbol.lower()
        count = len(parameters)
        capability_terms = {
            "clock": ("clock", "clk", "pll", "rcc", "sysctl"),
            "interrupt": ("irq", "interrupt", "plic", "nvic", "sysint"),
            "uart": ("uart", "usart", "serial"),
            "gpio": ("gpio", "pin", "ioport"),
            "timer": ("timer", "counter", "tcpwm", "gptimer"),
        }
        if not any(token in lowered_symbol for token in capability_terms[capability]):
            return False, "symbol-misses-capability"
        aliases = CAPABILITY_SCHEMA[capability]["operations"][operation]
        if not any(alias in lowered_symbol for alias in aliases):
            return False, "symbol-misses-operation"
        contracts: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {
            ("clock", "initialize"): (1, ("freq", "clock", "pll")),
            ("clock", "enable"): (1, ("clock", "pll")),
            ("clock", "disable"): (1, ("clock", "pll")),
            ("clock", "get_frequency"): (1, ("clock", "freq", "pll")),
            ("interrupt", "initialize"): (0, ()),
            ("interrupt", "enable"): (1, ("irq", "interrupt")),
            ("interrupt", "disable"): (1, ("irq", "interrupt")),
            ("interrupt", "register"): (2, ("irq", "callback", "handler")),
            ("uart", "configure"): (2, ("baud", "config", "channel")),
            ("uart", "write"): (2, ("buffer", "data", "size", "len")),
            ("uart", "read"): (2, ("buffer", "data", "size", "len")),
            ("gpio", "configure"): (2, ("pin", "mode", "flag", "direction")),
            ("gpio", "write"): (2, ("pin", "value", "state")),
            ("gpio", "read"): (1, ("pin",)),
            ("gpio", "attach_irq"): (2, ("pin", "callback", "handler", "irq")),
            ("timer", "initialize"): (
                1,
                ("timer", "device", "channel", "counter", "tcpwm", "cnt", "base", "obj"),
            ),
            ("timer", "start"): (
                1,
                ("timer", "device", "channel", "counter", "tcpwm", "cnt", "base", "obj"),
            ),
            ("timer", "stop"): (
                1,
                ("timer", "device", "channel", "counter", "tcpwm", "cnt", "base", "obj"),
            ),
            ("timer", "set_interval"): (
                2,
                ("timer", "interval", "period", "channel", "counter", "tcpwm", "cnt", "base", "obj"),
            ),
        }
        minimum, semantic_tokens = contracts[(capability, operation)]
        if count < minimum:
            return False, f"requires-at-least-{minimum}-parameters"
        if semantic_tokens and not any(token in lowered for token in semantic_tokens):
            return False, "missing-contract-parameter"
        return True, "compatible"

    @staticmethod
    def _signature_parameters(signature: str) -> list[str]:
        match = re.search(r"\((.*)\)", signature)
        if not match:
            return []
        body = match.group(1).strip()
        if not body or body == "void":
            return []
        parameters: list[str] = []
        depth = 0
        start = 0
        for index, character in enumerate(body):
            if character == "(":
                depth += 1
            elif character == ")":
                depth = max(0, depth - 1)
            elif character == "," and depth == 0:
                parameters.append(body[start:index].strip())
                start = index + 1
        parameters.append(body[start:].strip())
        return parameters

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
