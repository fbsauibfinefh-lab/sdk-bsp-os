from __future__ import annotations

from typing import Any

import numpy as np

from bspforge.code_effect_encoder import CodeEmbeddingCache
from bspforge.hardware_effect_graph import hardware_heuristic_score
from bspforge.structured_retrieval import complete_structured_scores


def _top_indices(
    group: dict[str, Any], scores: list[float], limit: int
) -> list[int]:
    return [
        index
        for index, _ in sorted(
            enumerate(scores),
            key=lambda item: (
                -item[1], group["candidates"][item[0]]["entity_id"]
            ),
        )[:limit]
    ]


def multichannel_shortlist(
    group: dict[str, Any], cache: CodeEmbeddingCache, *, per_channel: int
) -> list[int]:
    query = cache.query_vector(group["operation_id"])
    code_scores = []
    for candidate in group["candidates"]:
        key = cache.candidate_key(candidate, group["sdk_id"])
        code_scores.append(float(np.dot(query, cache.documents[cache.document_index[key]])))
    structured_scores = complete_structured_scores(group)[0]
    graph_scores = [hardware_heuristic_score(item) for item in group["candidates"]]
    selected = set()
    for scores in (code_scores, structured_scores, graph_scores):
        selected.update(_top_indices(group, scores, per_channel))
    return sorted(selected)


def shortlist_recall(
    groups: list[dict[str, Any]], cache: CodeEmbeddingCache, *, per_channel: int
) -> dict[str, Any]:
    selected_rows = 0
    positive_total = 0
    positive_selected = 0
    groups_with_positive = 0
    for group in groups:
        selected = multichannel_shortlist(group, cache, per_channel=per_channel)
        selected_rows += len(selected)
        truth_symbols = {
            item["symbol"] for item in group["candidates"] if item["label"] > 0
        }
        selected_symbols = {group["candidates"][index]["symbol"] for index in selected}
        positive_total += len(truth_symbols)
        positive_selected += len(truth_symbols & selected_symbols)
        groups_with_positive += int(bool(truth_symbols & selected_symbols))
    return {
        "per_channel": per_channel,
        "groups": len(groups),
        "selected_rows": selected_rows,
        "mean_shortlist_size": round(selected_rows / len(groups), 6),
        "groups_with_positive": groups_with_positive,
        "group_positive_coverage": round(groups_with_positive / len(groups), 6),
        "positive_symbols": positive_total,
        "selected_positive_symbols": positive_selected,
        "positive_symbol_recall": round(positive_selected / positive_total, 6),
    }
