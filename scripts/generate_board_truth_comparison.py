#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from bspforge.common import read_json
from bspforge.ranking_diagnostics import deterministic_ranking_evidence
from bspforge.structured_retrieval import complete_structured_scores


BOARDS = (
    ("Kendryte K210", "kendryte-k210-standalone-sdk-0.5.6"),
    ("STM32F103", "stm32cube-f1"),
    ("PSoC E84 EDGI-Talk", "psoc-e84-edgi-talk-sdk"),
)
RTOS_BACKENDS = ("RT-Thread", "Zephyr")
CAPABILITY_ORDER = {"clock": 0, "interrupt": 1, "uart": 2, "gpio": 3, "timer": 4}


def _group_map(dataset: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (group["sdk_id"], group["operation_id"]): group
        for group in dataset["groups"]
    }


def _truth_symbols(group: dict[str, Any] | None) -> list[str]:
    if group is None:
        return []
    positives = [
        (int(candidate["label"]), candidate["symbol"])
        for candidate in group["candidates"]
        if int(candidate.get("label", 0)) > 0
    ]
    return [symbol for _, symbol in sorted(positives, key=lambda item: (-item[0], item[1]))]


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_symbols(symbols: list[str]) -> str:
    return "<br>".join(f"`{_escape(symbol)}`" for symbol in symbols) if symbols else "—"


def _decision(group: dict[str, Any]) -> dict[str, Any]:
    scores, diagnostics = complete_structured_scores(group)
    index = min(
        range(len(scores)),
        key=lambda item: (-scores[item], group["candidates"][item]["entity_id"]),
    )
    candidate = group["candidates"][index]
    evidence = deterministic_ranking_evidence(group, scores, diagnostics)
    return {
        "symbol": candidate["symbol"],
        "file": candidate["file"],
        "score": float(scores[index]),
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成三块开发板、两个 RTOS 的语义选择真值对照表")
    parser.add_argument("--system", type=Path, required=True, help="系统候选与特征数据集")
    parser.add_argument("--h01", type=Path, required=True, help="H01 平行真值数据集")
    parser.add_argument("--h02", type=Path, required=True, help="H02 平行真值数据集")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    system_groups = _group_map(read_json(args.system))
    h01_groups = _group_map(read_json(args.h01))
    h02_groups = _group_map(read_json(args.h02))
    lines = [
        "# 六套上板组合的能力操作语义选择对照",
        "",
        "> 本文档由 `scripts/generate_board_truth_comparison.py` 自动生成。系统对每个存在候选的能力操作始终输出最终分数最高的 Top1；低分标记只提示复核，不会取消选择。",
        "",
        "## 口径说明",
        "",
        "- 六套组合由三款开发板 SDK 与 RT-Thread、Zephyr 两个后端交叉形成。",
        "- 语义排序发生在 SDK 侧，因此同一开发板的两个 RTOS 后端共享同一个 SDK API 选择结果；二者后续生成的设备对象、注册代码和构建资产不同。表格保留六套组合，是为了直接服务后续逐组合编译和上板记录。",
        "- `H01` 与 `H02` 列列出对应平行真值中标签大于 0 的全部可接受符号。系统 Top1 落入该集合即记为一致。",
        "- 当前三块板卡的 H01/H02 条目继承同一套 `source-audited` 板卡标注，不代表两位工程师分别对板卡样本完成了独立复核。",
        "- `低分/弱证据` 不属于正确性判定指标，也不影响 Top1 输出。其用途是指出应优先人工检查的操作。",
        "",
        "## 汇总",
        "",
        "| 组合 | 操作数 | H01 一致 | H02 一致 | 双真值一致 | 低分/弱证据 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    sections: list[str] = []
    summary_rows: list[str] = []

    for board_name, sdk_id in BOARDS:
        keys = sorted(
            [key for key in system_groups if key[0] == sdk_id],
            key=lambda key: (
                CAPABILITY_ORDER.get(system_groups[key]["capability"], 99),
                system_groups[key]["operation_id"],
            ),
        )
        if not keys:
            raise ValueError(f"系统数据集中不存在板卡 SDK：{sdk_id}")
        decisions = {key: _decision(system_groups[key]) for key in keys}
        for rtos in RTOS_BACKENDS:
            counts = Counter()
            table = [
                f"## {board_name} + {rtos}",
                "",
                f"SDK 标识：`{sdk_id}`；OS 后端：`{rtos}`。",
                "",
                "| 能力操作 | 系统 Top1 | 来源文件 | 最终分数 | 低分/弱证据 | H01 真值 | H01 一致 | H02 真值 | H02 一致 |",
                "|---|---|---|---:|---|---|:---:|---|:---:|",
            ]
            for key in keys:
                group = system_groups[key]
                decision = decisions[key]
                h01_symbols = _truth_symbols(h01_groups.get(key))
                h02_symbols = _truth_symbols(h02_groups.get(key))
                h01_match = decision["symbol"] in h01_symbols
                h02_match = decision["symbol"] in h02_symbols
                reasons = decision["evidence"]["low_score_reasons"]
                counts["operations"] += 1
                counts["h01"] += int(h01_match)
                counts["h02"] += int(h02_match)
                counts["both"] += int(h01_match and h02_match)
                counts["low"] += int(bool(reasons))
                table.append(
                    "| {operation} | `{symbol}` | `{file}` | {score:.6f} | {low} | {h01} | {h01_match} | {h02} | {h02_match} |".format(
                        operation=group["operation_id"],
                        symbol=_escape(decision["symbol"]),
                        file=_escape(decision["file"]),
                        score=decision["score"],
                        low="<br>".join(f"`{reason}`" for reason in reasons) if reasons else "否",
                        h01=_format_symbols(h01_symbols),
                        h01_match="是" if h01_match else "否",
                        h02=_format_symbols(h02_symbols),
                        h02_match="是" if h02_match else "否",
                    )
                )
            table.extend(["", ""])
            sections.extend(table)
            summary_rows.append(
                f"| {board_name} + {rtos} | {counts['operations']} | {counts['h01']} | {counts['h02']} | {counts['both']} | {counts['low']} |"
            )

    lines.extend(summary_rows)
    lines.extend(["", *sections])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"generated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
