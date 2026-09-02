#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.common import read_json, write_json


GRADE_FIELDS = {
    3: "symbols",
    2: "alternative_symbols",
    1: "related_symbols",
    0: "irrelevant_symbols",
}

BASE_TRUTH_SET_ID = "external-board-h03"


def apply_adjudication(
    audit: dict[str, Any], adjudication: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not adjudication:
        return audit, []
    result = deepcopy(audit)
    applied = []
    operations = {
        operation["operation_id"]: operation for operation in result["operations"]
    }
    for item in adjudication.get("items", []):
        if item.get("sdk_id") != result.get("sdk_id"):
            continue
        if item.get("source_revision") != result.get("source_revision"):
            raise ValueError(
                f"{result['sdk_id']} 仲裁项的源码修订与真值审计不一致"
            )
        operation_id = item["operation_id"]
        if operation_id not in operations:
            raise ValueError(f"未知仲裁操作：{operation_id}")
        operation = operations[operation_id]
        if any(existing.get("symbol") == item["symbol"] for existing in operation["items"]):
            raise ValueError(
                f"{result['sdk_id']}::{operation_id} 已包含 {item['symbol']}"
            )
        operation["items"].append(
            {
                "symbol": item["symbol"],
                "canonical_symbol": item["symbol"],
                "grade": int(item["grade"]),
                "declaration_file": item["declaration_file"],
                "declaration_line": int(item["declaration_line"]),
                "definition_file": item["definition_file"],
                "definition_line": int(item["definition_line"]),
                "signature": item["signature"],
                "api_layer": item["api_layer"],
                "callable_kind": item["callable_kind"],
                "call_direction": "app_to_sdk",
                "preconditions": item.get("preconditions", []),
                "discovery_source": [
                    "post_error_source_audit",
                    "declaration_review",
                    "definition_review",
                ],
                "rationale": item["rationale"],
                "evidence_snippet": item["evidence_snippet"],
                "review_status": "post_error_adjudicated",
            }
        )
        applied.append(item)
    return result, applied


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_operation_ids() -> set[str]:
    return {
        f"{capability}.{operation}"
        for capability, specification in CAPABILITY_SCHEMA.items()
        for operation in specification["operations"]
    }


def empty_contract(status: str) -> dict[str, Any]:
    return {
        "group_status": status,
        "symbols": [],
        "alternative_symbols": [],
        "related_symbols": [],
        "irrelevant_symbols": [],
    }


def validate_source_audit(
    audit: dict[str, Any],
    source_item: dict[str, Any],
    project_item: dict[str, Any],
) -> None:
    sdk_id = source_item["sdk_id"]
    errors = []
    if audit.get("sdk_id") != sdk_id:
        errors.append("审计文件 sdk_id 与外部评估 manifest 不一致")
    if audit.get("role") != "external-test" or audit.get("training_included") is not False:
        errors.append("审计文件未声明为仅 external-test")
    if source_item.get("role") != "external-test" or source_item.get("training_included") is not False:
        errors.append("外部评估 manifest 未声明为仅 external-test")
    if project_item.get("role") != "external-test" or project_item.get("training_included") is not False:
        errors.append("项目 manifest 未锁定 external-test/training_included=false")
    revision = source_item.get("source_revision")
    if audit.get("source_revision") != revision:
        errors.append("审计文件源码修订与外部评估 manifest 不一致")
    if project_item.get("revision") != revision:
        errors.append("项目 manifest 源码修订与外部评估 manifest 不一致")

    operations = audit.get("operations", [])
    by_id = {operation.get("operation_id"): operation for operation in operations}
    if len(by_id) != len(operations):
        errors.append("存在重复或缺失 operation_id")
    if set(by_id) != expected_operation_ids():
        errors.append("未完整覆盖项目定义的 19 个操作")
    for operation_id, operation in by_id.items():
        if operation.get("group_status") not in {"complete", "no_public_api"}:
            errors.append(f"{operation_id}: 非法 group_status")
        symbols = set()
        for item in operation.get("items", []):
            symbol = item.get("symbol")
            grade = item.get("grade")
            if not symbol or grade not in GRADE_FIELDS:
                errors.append(f"{operation_id}: 非法符号或等级")
            if symbol in symbols:
                errors.append(f"{operation_id}: 重复符号 {symbol}")
            symbols.add(symbol)
    if errors:
        raise ValueError(f"{sdk_id} 外部测试真值校验失败：\n" + "\n".join(errors))


def convert_one(
    audit: dict[str, Any],
    source_item: dict[str, Any],
    project_item: dict[str, Any],
    audit_path: Path,
    operation_root: Path,
    adjudication_path: Path | None = None,
    applied_adjudication: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_source_audit(audit, source_item, project_item)
    statuses: Counter[str] = Counter()
    grades: Counter[int] = Counter()
    operations = {}
    for operation in audit["operations"]:
        operation_id = operation["operation_id"]
        contract = empty_contract(operation["group_status"])
        statuses[operation["group_status"]] += 1
        for item in operation.get("items", []):
            grade = int(item["grade"])
            contract[GRADE_FIELDS[grade]].append(item["symbol"])
            grades[grade] += 1
        for field in GRADE_FIELDS.values():
            contract[field] = sorted(set(contract[field]))
        operations[operation_id] = contract

    truth_set_id = (
        "external-board-h03-equivalence-r1"
        if applied_adjudication
        else BASE_TRUTH_SET_ID
    )
    result = {
        "schema_version": "operation-truth-v1",
        "truth_set_id": truth_set_id,
        "truth_source": "human-source-audited-external-adjudication",
        "sdk_id": audit["sdk_id"],
        "role": "external-test",
        "training_included": False,
        "source_revision": audit["source_revision"],
        "annotator_id": audit.get("annotator_id"),
        "review_method": audit.get("review_method"),
        "source_audit": {
            "file": audit_path.relative_to(operation_root).as_posix(),
            "sha256": sha256(audit_path),
        },
        "grade_fields": {str(grade): field for grade, field in GRADE_FIELDS.items()},
        "operations": operations,
        "summary": {
            "query_groups": len(operations),
            "group_status_counts": dict(sorted(statuses.items())),
            "grade_counts": {str(grade): grades[grade] for grade in range(4)},
        },
    }
    if applied_adjudication and adjudication_path is not None:
        result["post_error_adjudication"] = {
            "file": adjudication_path.relative_to(operation_root).as_posix(),
            "sha256": sha256(adjudication_path),
            "items_applied": len(applied_adjudication),
            "external_labels_used_for_training": False,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="转换三块开发板的外部测试人工真值")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("experiments/operation-ranking/external-test-truth/source"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/operation-ranking/manifest.json"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("experiments/operation-ranking/external-test-truth/registry.json"),
    )
    parser.add_argument(
        "--adjudication",
        type=Path,
        default=Path(
            "experiments/operation-ranking/external-test-truth/source/"
            "equivalence-adjudication-20260902.json"
        ),
    )
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    source_manifest_path = source_dir / "evaluation-manifest.json"
    validation_path = source_dir / "validation.json"
    source_manifest = read_json(source_manifest_path)
    validation = read_json(validation_path)
    if validation.get("status") != "pass":
        raise ValueError("外部测试真值的上游验证报告未通过")

    project_manifest = read_json(args.manifest)
    project_external = {
        item["sdk_id"]: item
        for item in project_manifest["sdks"]
        if item.get("role") == "external-test"
    }
    source_external = {item["sdk_id"]: item for item in source_manifest["sdks"]}
    if set(project_external) != set(source_external):
        raise ValueError("项目与外部评估 manifest 的 SDK 集合不一致")

    operation_root = args.manifest.parent.resolve()
    adjudication_path = args.adjudication.resolve()
    adjudication = read_json(adjudication_path) if adjudication_path.exists() else None
    converted = {}
    aggregate_statuses: Counter[str] = Counter()
    aggregate_grades: Counter[int] = Counter()
    for sdk_id, source_item in source_external.items():
        project_item = project_external[sdk_id]
        audit_path = (source_dir / source_item["audit_file"]).resolve()
        audit, applied_adjudication = apply_adjudication(
            read_json(audit_path), adjudication
        )
        output = convert_one(
            audit,
            source_item,
            project_item,
            audit_path,
            operation_root,
            adjudication_path if adjudication else None,
            applied_adjudication,
        )
        output_path = (args.manifest.parent / project_item["ground_truth"]).resolve()
        write_json(output_path, output)
        converted[sdk_id] = {
            "file": output_path.relative_to(operation_root).as_posix(),
            "source_revision": output["source_revision"],
            "source_audit": output["source_audit"],
            "summary": output["summary"],
        }
        if output.get("post_error_adjudication"):
            converted[sdk_id]["post_error_adjudication"] = output[
                "post_error_adjudication"
            ]
        aggregate_statuses.update(output["summary"]["group_status_counts"])
        aggregate_grades.update(
            {int(grade): count for grade, count in output["summary"]["grade_counts"].items()}
        )

    registry = {
        "schema_version": "external-operation-truth-registry-v1",
        "truth_set_id": (
            "external-board-h03-equivalence-r1"
            if adjudication
            else BASE_TRUTH_SET_ID
        ),
        "role": "external-test",
        "training_included": False,
        "source_manifest": {
            "file": source_manifest_path.relative_to(operation_root).as_posix(),
            "sha256": sha256(source_manifest_path),
        },
        "source_validation": {
            "file": validation_path.relative_to(operation_root).as_posix(),
            "sha256": sha256(validation_path),
            "status": validation["status"],
        },
        "sdks": converted,
        "summary": {
            "external_test_sdks": len(converted),
            "query_groups": sum(item["summary"]["query_groups"] for item in converted.values()),
            "group_status_counts": dict(sorted(aggregate_statuses.items())),
            "grade_counts": {str(grade): aggregate_grades[grade] for grade in range(4)},
        },
    }
    if adjudication:
        registry["post_error_adjudication"] = {
            "file": adjudication_path.relative_to(operation_root).as_posix(),
            "sha256": sha256(adjudication_path),
            "items": len(adjudication.get("items", [])),
            "protocol": adjudication.get("protocol"),
        }
    write_json(args.registry, registry)
    print(registry["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
