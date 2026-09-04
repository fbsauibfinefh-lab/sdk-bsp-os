from __future__ import annotations

from typing import Any

from bspforge.common import utc_now


def _diagnostic_text(diagnosis: dict[str, Any]) -> str:
    values = []
    for item in diagnosis.get("diagnostics", []):
        values.extend(str(value) for value in item.values())
    return " ".join(values).lower()


def create_compile_feedback(
    resolution: dict[str, Any],
    build_result: dict[str, Any],
    binding_plan: dict[str, Any] | None = None,
    operation_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map a build result to selected operation bindings without claiming runtime correctness."""
    diagnosis_text = _diagnostic_text(build_result.get("diagnosis", {}))
    generation_evidence = {
        (item["capability"], item["operation"]): item
        for item in (operation_bindings or [])
    }
    if binding_plan is not None:
        selected_operations = [
            {
                "capability": capability["capability"],
                "operation": operation["operation"],
                "selected_symbol": operation.get("selected_symbol"),
                "selected_entity_id": operation.get("entity_id"),
            }
            for capability in binding_plan.get("capabilities", [])
            for operation in capability.get("operations", [])
        ]
    else:
        selected_operations = [
            {"capability": mapping["capability"], **ranking}
            for mapping in resolution.get("mappings", [])
            for ranking in mapping.get("operation_rankings", [])
        ]
    records = []
    for ranking in selected_operations:
        capability = ranking["capability"]
        operation = ranking["operation"]
        symbol = ranking.get("selected_symbol")
        entity_id = ranking.get("selected_entity_id")
        generated = generation_evidence.get((capability, operation))
        if not symbol or not entity_id:
            status = "abstained"
            score = 0.5
            evidence = ["resolver-abstained"]
        elif symbol.lower() in diagnosis_text:
            status = "diagnostic-implicated"
            score = 0.0
            evidence = ["selected-symbol-mentioned-by-build-diagnostic"]
        elif build_result.get("success") and generated is not None:
            status = (
                "os-replacement-compiled-and-artifact-verified"
                if generated["disposition"] == "replaced-by-os-backend"
                else "generated-call-compiled-and-artifact-verified"
            )
            score = 1.0
            evidence = [
                "whole-project-build-and-artifact-verification-passed",
                generated["disposition"],
            ]
        elif build_result.get("success") and operation_bindings is None:
            status = "compiled-linked-and-artifact-verified"
            score = 1.0
            evidence = ["whole-project-build-and-artifact-verification-passed"]
        elif build_result.get("success"):
            status = "build-passed-without-generated-call-evidence"
            score = 0.5
            evidence = ["selected-operation-absent-from-generation-evidence"]
        elif build_result.get("skipped"):
            status = "not-observed"
            score = 0.5
            evidence = ["build-skipped"]
        else:
            status = "build-failed-unattributed"
            score = 0.35
            evidence = ["build-failed-without-selected-symbol-attribution"]
        records.append({
            "capability": capability,
            "operation": operation,
            "entity_id": entity_id,
            "symbol": symbol,
            "status": status,
            "calibration_score": score,
            "evidence": evidence,
            "semantic_correctness_proven": False,
            "generation_disposition": (
                generated.get("disposition") if generated else None
            ),
        })
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "sdk_id": resolution.get("sdk_id"),
        "build_success": bool(build_result.get("success")),
        "scope": "compile-link-artifact feedback only; runtime device semantics excluded",
        "records": records,
        "summary": {
            "bindings": len(records),
            "compiled": sum(item["calibration_score"] == 1.0 for item in records),
            "implicated": sum(item["calibration_score"] == 0.0 for item in records),
            "unobserved": sum(item["calibration_score"] not in {0.0, 1.0} for item in records),
        },
    }


def feedback_index(payload: dict[str, Any]) -> dict[tuple[str, str, str], float]:
    return {
        (item["capability"], item["operation"], item["entity_id"]): float(
            item["calibration_score"]
        )
        for item in payload.get("records", [])
        if item.get("entity_id")
    }
