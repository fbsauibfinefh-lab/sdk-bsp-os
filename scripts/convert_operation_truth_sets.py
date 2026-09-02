#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def operation_ids() -> list[str]:
    return [
        f"{capability}.{operation}"
        for capability, specification in CAPABILITY_SCHEMA.items()
        for operation in specification["operations"]
    ]


def sdk_records(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = payload["sdks"]
    if isinstance(records, dict):
        return {
            sdk_id: {"sdk_id": sdk_id, **record}
            for sdk_id, record in records.items()
        }
    return {record["sdk_id"]: record for record in records}


def operation_records(sdk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = sdk["operations"]
    if isinstance(records, dict):
        return {
            operation_id: {"operation_id": operation_id, **record}
            for operation_id, record in records.items()
        }
    return {record["operation_id"]: record for record in records}


def empty_contract(status: str = "no_positive_label") -> dict[str, Any]:
    return {
        "group_status": status,
        "symbols": [],
        "alternative_symbols": [],
        "related_symbols": [],
        "irrelevant_symbols": [],
    }


def summarize(sdks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    grades: Counter[int] = Counter()
    for sdk in sdks:
        for contract in sdk["operations"].values():
            statuses[contract["group_status"]] += 1
            for grade, field in GRADE_FIELDS.items():
                grades[grade] += len(contract[field])
    return {
        "training_sdks": len(sdks),
        "query_groups": sum(len(sdk["operations"]) for sdk in sdks),
        "group_status_counts": dict(sorted(statuses.items())),
        "grade_counts": {str(grade): grades[grade] for grade in range(4)},
    }


def validate_human_audit(
    payload: dict[str, Any], manifest: dict[str, Any], source_name: str
) -> None:
    expected_operations = set(operation_ids())
    training = {
        item["sdk_id"]: item
        for item in manifest["sdks"]
        if item["role"] == "train"
    }
    external = {
        item["sdk_id"]
        for item in manifest["sdks"]
        if item["role"] == "external-test"
    }
    records = sdk_records(payload)
    errors = []
    if set(records) != set(training):
        errors.append("SDK 集合与训练 manifest 不一致")
    if set(records) & external:
        errors.append(f"混入外部板卡 SDK：{sorted(set(records) & external)}")
    for sdk_id, sdk in records.items():
        if sdk_id not in training:
            continue
        if sdk.get("source_revision") != training[sdk_id].get("revision"):
            errors.append(f"{sdk_id}: source_revision 与 manifest 不一致")
        operations = operation_records(sdk)
        if set(operations) != expected_operations:
            errors.append(f"{sdk_id}: 未完整覆盖 19 个操作")
        for operation_id, operation in operations.items():
            if operation.get("group_status") not in {
                "complete", "no_public_api", "blocked"
            }:
                errors.append(f"{sdk_id}/{operation_id}: 非法 group_status")
            seen = set()
            for item in operation.get("items", []):
                symbol = item.get("symbol")
                grade = item.get("grade")
                if not symbol or grade not in GRADE_FIELDS:
                    errors.append(f"{sdk_id}/{operation_id}: 非法符号或等级")
                if symbol in seen:
                    errors.append(f"{sdk_id}/{operation_id}: 重复符号 {symbol}")
                seen.add(symbol)
    if errors:
        raise ValueError(f"{source_name} 校验失败：\n" + "\n".join(errors[:30]))


def convert_human(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    truth_set_id: str,
    annotator_id: str,
    source_file: Path,
    *,
    truth_source: str = "independent-human-source-audit",
    annotator_independence: str = "confirmed-by-project-owner",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_human_audit(payload, manifest, truth_set_id)
    converted = []
    for sdk_id, sdk in sdk_records(payload).items():
        operations = {}
        for operation_id, operation in operation_records(sdk).items():
            contract = empty_contract(operation["group_status"])
            for grade, field in GRADE_FIELDS.items():
                contract[field] = sorted({
                    item["symbol"]
                    for item in operation.get("items", [])
                    if item["grade"] == grade
                })
            operations[operation_id] = contract
        converted.append({
            "sdk_id": sdk_id,
            "source_revision": sdk.get("source_revision"),
            "operations": operations,
        })
    output = {
        "schema_version": "operation-truth-set-v1",
        "truth_set_id": truth_set_id,
        "truth_source": truth_source,
        "annotator_id": annotator_id,
        "source_metadata_annotator_id": payload.get("annotator_id"),
        "annotator_independence": annotator_independence,
        "source_audit": {
            "file": f"source-audits/{source_file.name}",
            "sha256": sha256(source_file),
        },
        "grade_fields": {str(grade): field for grade, field in GRADE_FIELDS.items()},
        "sdks": converted,
    }
    if extra_metadata:
        output.update(extra_metadata)
    output["summary"] = summarize(converted)
    return output


def convert_automatic(
    dataset: dict[str, Any], manifest: dict[str, Any], source_file: Path
) -> dict[str, Any]:
    training = [item for item in manifest["sdks"] if item["role"] == "train"]
    operations = operation_ids()
    by_sdk = {
        item["sdk_id"]: {
            "sdk_id": item["sdk_id"],
            "source_revision": item.get("revision"),
            "operations": {
                operation_id: empty_contract()
                for operation_id in operations
            },
        }
        for item in training
    }
    for group in dataset["groups"]:
        if group["role"] != "train":
            continue
        sdk_id = group["sdk_id"]
        operation_id = group["operation_id"]
        max_grade_by_symbol: dict[str, int] = {}
        for candidate in group["candidates"]:
            symbol = candidate["symbol"]
            max_grade_by_symbol[symbol] = max(
                max_grade_by_symbol.get(symbol, 0), int(candidate["label"])
            )
        contract = empty_contract("complete")
        for symbol, grade in max_grade_by_symbol.items():
            contract[GRADE_FIELDS[grade]].append(symbol)
        for field in GRADE_FIELDS.values():
            contract[field].sort()
        by_sdk[sdk_id]["operations"][operation_id] = contract
    for item in dataset.get("skipped", []):
        sdk_id = item.get("sdk_id")
        operation_id = item.get("operation") or item.get("operation_id")
        if sdk_id in by_sdk and operation_id in by_sdk[sdk_id]["operations"]:
            by_sdk[sdk_id]["operations"][operation_id]["group_status"] = item.get(
                "reason", "no_positive_label"
            )
    converted = [by_sdk[item["sdk_id"]] for item in training]
    output = {
        "schema_version": "operation-truth-set-v1",
        "truth_set_id": "automatic-v0.9",
        "truth_source": "legacy-auditable-graded-weak-supervision",
        "annotator_id": None,
        "annotator_independence": "not-applicable",
        "source_dataset": {
            "file": source_file.name,
            "sha256": sha256(source_file),
            "schema_version": dataset.get("schema_version"),
        },
        "grade_fields": {str(grade): field for grade, field in GRADE_FIELDS.items()},
        "sdks": converted,
    }
    output["summary"] = summarize(converted)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="转换两份独立人工真值、一份仲裁真值和一份旧自动真值"
    )
    parser.add_argument(
        "--engineer-1-audit",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets/source-audits/human-engineer-1-audit.json"),
    )
    parser.add_argument(
        "--engineer-2-audit",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets/source-audits/human-engineer-2-audit.json"),
    )
    parser.add_argument(
        "--adjudicated-audit",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets/source-audits/human-adjudicated-h03-audit.json"),
    )
    parser.add_argument(
        "--adjudication-summary",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets/source-audits/human-adjudicated-h03-summary.json"),
    )
    parser.add_argument(
        "--adjudication-validation",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets/source-audits/human-adjudicated-h03-validation.json"),
    )
    parser.add_argument(
        "--automatic-dataset",
        type=Path,
        default=Path("experiments/generated/operation-ranking-dataset-v0.9.json"),
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("experiments/operation-ranking/manifest.json")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/operation-ranking/truth-sets"),
    )
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    engineer_1 = convert_human(
        read_json(args.engineer_1_audit), manifest, "human-engineer-1", "H01", args.engineer_1_audit
    )
    engineer_2 = convert_human(
        read_json(args.engineer_2_audit), manifest, "human-engineer-2", "H02", args.engineer_2_audit
    )
    adjudication_summary = read_json(args.adjudication_summary)
    adjudication_validation = read_json(args.adjudication_validation)
    if not adjudication_validation.get("passed"):
        raise ValueError("H03 上游校验报告未通过，拒绝生成项目真值")
    adjudicated = convert_human(
        read_json(args.adjudicated_audit),
        manifest,
        "human-adjudicated-h03",
        "H03",
        args.adjudicated_audit,
        truth_source="human-source-adjudication",
        annotator_independence="derived-from-H01-H02-adjudication",
        extra_metadata={
            "adjudication": {
                "source_truth_sets": ["human-engineer-1", "human-engineer-2"],
                "summary_file": f"source-audits/{args.adjudication_summary.name}",
                "summary_sha256": sha256(args.adjudication_summary),
                "validation_file": f"source-audits/{args.adjudication_validation.name}",
                "validation_sha256": sha256(args.adjudication_validation),
                "validation_passed": True,
                "shared_candidate_quadratic_weighted_kappa": adjudication_summary.get(
                    "shared_only_quadratic_weighted_kappa"
                ),
                "kappa_scope": "shared-candidates-only",
                "full_union_kappa_reportable": False,
                "decision_counts": adjudication_summary.get("decision_counts", {}),
            }
        },
    )
    automatic = convert_automatic(
        read_json(args.automatic_dataset), manifest, args.automatic_dataset
    )
    outputs = {
        "human-engineer-1": engineer_1,
        "human-engineer-2": engineer_2,
        "human-adjudicated-h03": adjudicated,
        "automatic-v0.9": automatic,
    }
    for truth_set_id, payload in outputs.items():
        write_json(args.output_dir / f"{truth_set_id}.json", payload)
    registry = {
        "schema_version": "operation-truth-set-registry-v1",
        "default_truth_set": manifest["training_policy"]["default_truth_set"],
        "truth_sets": {
            truth_set_id: {
                "file": f"{truth_set_id}.json",
                "truth_source": payload["truth_source"],
                "annotator_id": payload["annotator_id"],
                "summary": payload["summary"],
            }
            for truth_set_id, payload in outputs.items()
        },
        "notes": [
            "H01 与 H02 按项目负责人确认视为两名独立工程师。",
            "两份输入审计内部均写为 A01；原值保存在 source_metadata_annotator_id，不据此覆盖规范标注者编号。",
            "H03 是 H01/H02 的源码级仲裁结果，不是第三名独立工程师标注。",
            "四套真值可独立选择，不自动合并，也不自动执行训练。",
        ],
    }
    write_json(args.output_dir / "registry.json", registry)
    print({key: value["summary"] for key, value in outputs.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
