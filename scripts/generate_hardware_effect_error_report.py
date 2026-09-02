#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bspforge.common import read_json, write_json


def candidate_by_symbol(group: dict[str, Any], symbol: str) -> dict[str, Any]:
    matches = [item for item in group["candidates"] if item["symbol"] == symbol]
    if not matches:
        return {"symbol": symbol, "features": {}, "hardware_effect_evidence": {}}
    return max(
        matches,
        key=lambda item: (
            int(item.get("label", 0)),
            float(item["features"].get("hw-transitive-operation-effect", 0.0)),
            item["entity_id"],
        ),
    )


def primary_cause(
    group: dict[str, Any], prediction: dict[str, Any], truths: list[dict[str, Any]]
) -> tuple[str, str]:
    features = prediction["features"]
    truth_effect = max(
        float(item["features"].get("hw-transitive-operation-effect", 0.0))
        for item in truths
    )
    truth_families = {item.get("api_family") for item in truths if item.get("api_family")}
    if truth_effect <= 0.05:
        return "truth-path-missing", "真值函数没有恢复出足够的目标操作效果路径"
    if prediction.get("api_family") in truth_families:
        return "same-family-operation-confusion", "预测项与真值属于同一 API 家族，但动作或子操作不一致"
    if float(features.get("hw-internal-callback-likelihood", 0.0)) > 0:
        return "internal-role-overranked", "内部 handler/callback/dispatch 角色被排到公共接口之前"
    if float(features.get("hw-example-likelihood", 0.0)) > 0:
        return "example-overranked", "示例或测试入口被排到 SDK 公共接口之前"
    if float(features.get("hw-os-adapter-likelihood", 0.0)) > 0:
        return "reverse-layer-overranked", "OS 适配层或反向调用入口被错误优先"
    predicted_depth = prediction.get("hardware_effect_evidence", {}).get("anchor_depth")
    truth_depths = [
        item.get("hardware_effect_evidence", {}).get("anchor_depth") for item in truths
    ]
    truth_depths = [item for item in truth_depths if item is not None]
    if predicted_depth == 0 and any(item >= 1 for item in truth_depths):
        return "abstraction-level-mismatch", "直接效果层与 H02 指定的可迁移 API 层级不一致"
    if float(features.get("hw-composite-likelihood", 0.0)) >= 0.40:
        return "composite-entry-overranked", "复合初始化或多能力入口的硬件效果过强"
    predicted_effect = float(features.get("hw-transitive-operation-effect", 0.0))
    if predicted_effect > truth_effect + 0.15:
        return "effect-strength-confusion", "错误候选的寄存器效果强度压过了接口契约"
    return "ranking-model-confusion", "现有图特征和 PU 权重不能区分两个相近候选"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成硬件效果PU排序的完整错误报告")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--method", default="hardware-effect-pu-residual")
    parser.add_argument("--title")
    args = parser.parse_args()

    dataset = read_json(args.dataset)
    results = read_json(args.results)
    groups = {item["group_id"]: item for item in dataset["groups"]}
    records = results["cross_validation"]["records"][args.method]
    errors = []
    correct = 0
    for record in records:
        group = groups[record["group_id"]]
        selected = record.get("selected", record["top5"][0])
        prediction = candidate_by_symbol(group, selected["symbol"])
        truths = []
        seen = set()
        for candidate in group["candidates"]:
            if candidate["label"] <= 0 or candidate["symbol"] in seen:
                continue
            seen.add(candidate["symbol"])
            truths.append(candidate)
        if prediction.get("label", 0) > 0:
            correct += 1
            continue
        cause, explanation = primary_cause(group, prediction, truths)
        ranks = {item["symbol"]: item["rank"] for item in record.get("positive_ranks", [])}
        errors.append({
            "group_id": group["group_id"],
            "sdk_id": group["sdk_id"],
            "independence_group": group["independence_group"],
            "operation_id": group["operation_id"],
            "prediction": {
                "symbol": prediction["symbol"],
                "score": selected["score"],
                "file": prediction.get("file"),
                "effect_path": prediction.get("hardware_effect_evidence", {}).get("effect_path", []),
                "anchor_depth": prediction.get("hardware_effect_evidence", {}).get("anchor_depth"),
            },
            "truth": [
                {
                    "symbol": item["symbol"],
                    "grade": item["label"],
                    "rank": ranks.get(item["symbol"]),
                    "file": item.get("file"),
                    "effect_path": item.get("hardware_effect_evidence", {}).get("effect_path", []),
                    "anchor_depth": item.get("hardware_effect_evidence", {}).get("anchor_depth"),
                }
                for item in sorted(truths, key=lambda value: (-value["label"], value["symbol"]))
            ],
            "top5": record["top5"],
            "cause": cause,
            "explanation": explanation,
        })

    cause_counts = Counter(item["cause"] for item in errors)
    operation_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    sdk_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        group = groups[record["group_id"]]
        operation_counts[group["operation_id"]][1] += 1
        sdk_counts[group["sdk_id"]][1] += 1
    for item in errors:
        operation_counts[item["operation_id"]][0] += 1
        sdk_counts[item["sdk_id"]][0] += 1

    payload = {
        "schema_version": "0.1",
        "method": args.method,
        "truth_set": "human-engineer-2-H02",
        "scope": "out-of-fold predictions for role=train groups only",
        "summary": {
            "queries": len(records),
            "correct_top1": correct,
            "incorrect_top1": len(errors),
            "precision_at_1": round(correct / len(records), 6),
            "cause_counts": dict(cause_counts),
        },
        "errors": errors,
    }
    write_json(args.output_json, payload)

    title = args.title or (
        "预训练代码效果排序完整错误报告 v0.2"
        if args.method.startswith("pretrained-code-")
        else "寄存器效果图 PU 排序完整错误报告 v0.1"
    )
    lines = [
        f"# {title}",
        "",
        "## 1. 报告口径",
        "",
        f"本报告使用 H02 和 `{args.method}` 的跨独立组五折 out-of-fold 预测。"
        "每个查询只由未见过该 independence group 的模型预测。板卡外部诊断不并入本报告。",
        "",
        f"- 有效查询：{len(records)}",
        f"- Top1 正确：{correct}",
        f"- Top1 错误：{len(errors)}",
        f"- P@1：{correct / len(records):.6f}",
        "- 完整机器可读记录："
        f"`{args.output_json.as_posix()}`",
        "",
        "## 2. 主错误归因",
        "",
        "归因是基于当前图证据的可复现诊断规则，不等同于人工确认的唯一根因。",
        "",
        "| 主归因 | 错误数 | 占全部错误 |",
        "| --- | ---: | ---: |",
    ]
    for cause, count in cause_counts.most_common():
        lines.append(f"| `{cause}` | {count} | {count / len(errors):.1%} |")
    lines.extend(["", "## 3. 按操作统计", "", "| 操作 | 错误/总数 | 错误率 |", "| --- | ---: | ---: |"])
    for operation, (failed, total) in sorted(
        operation_counts.items(), key=lambda item: (-item[1][0] / item[1][1], item[0])
    ):
        lines.append(f"| `{operation}` | {failed}/{total} | {failed / total:.1%} |")
    lines.extend(["", "## 4. 按 SDK 统计", "", "| SDK | 错误/总数 | 错误率 |", "| --- | ---: | ---: |"])
    for sdk_id, (failed, total) in sorted(
        sdk_counts.items(), key=lambda item: (-item[1][0] / item[1][1], item[0])
    ):
        lines.append(f"| `{sdk_id}` | {failed}/{total} | {failed / total:.1%} |")

    lines.extend(["", "## 5. 代表性错误详解", ""])
    representatives = []
    represented = set()
    for item in errors:
        if item["cause"] not in represented:
            representatives.append(item)
            represented.add(item["cause"])
    for index, item in enumerate(representatives, start=1):
        truth_text = ", ".join(
            f"`{truth['symbol']}`(grade={truth['grade']}, rank={truth['rank'] or '>候选表末端'})"
            for truth in item["truth"]
        )
        lines.extend([
            f"### 5.{index} `{item['group_id']}`",
            "",
            f"- 系统 Top1：`{item['prediction']['symbol']}`，分数 {item['prediction']['score']}。",
            f"- 系统效果路径：`{' -> '.join(item['prediction']['effect_path']) or '无'}`。",
            f"- H02 真值：{truth_text}。",
            f"- 主归因：`{item['cause']}`，{item['explanation']}。",
            "- Top5：" + ", ".join(
                f"`{top['symbol']}`(label={top['label']}, score={top['score']})"
                for top in item["top5"]
            ) + "。",
            "",
        ])

    lines.extend([
        "## 6. 全部 Top1 错误清单",
        "",
        "真值排名来自该折完整唯一符号排序；每一行同时保留系统 Top1、效果路径以及全部 H02 正例。",
        "",
        "| # | SDK / 操作 | 系统 Top1 | H02 真值（等级；排名） | 主归因 |",
        "| ---: | --- | --- | --- | --- |",
    ])
    for index, item in enumerate(errors, start=1):
        truths = "<br>".join(
            f"`{truth['symbol']}` ({truth['grade']}; {truth['rank'] or 'n/a'})"
            for truth in item["truth"]
        )
        lines.append(
            f"| {index} | `{item['sdk_id']}`<br>`{item['operation_id']}` | "
            f"`{item['prediction']['symbol']}`<br>{' -> '.join(item['prediction']['effect_path']) or '无路径'} | "
            f"{truths} | `{item['cause']}` |"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(payload["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
