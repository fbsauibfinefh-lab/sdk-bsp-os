from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FEATURE_NAMES = [
    "name-capability",
    "name-action",
    "path",
    "signature",
    "include",
    "call-context",
    "macro-context",
    "parser-confidence",
]


def candidate_features(candidate: dict[str, Any], function: dict[str, Any]) -> list[float]:
    evidence = {
        item["kind"]: min(1.0, len(item.get("matches", [])) / 4.0)
        for item in candidate.get("evidence", [])
    }
    return [
        evidence.get(name, 0.0) for name in FEATURE_NAMES[:-1]
    ] + [float(function.get("parser_confidence", 0.55))]


class LearnedRanker:
    """Load a LightGBM ranker without making it a mandatory runtime dependency."""

    def __init__(self, model_path: Path) -> None:
        try:
            import lightgbm
        except ImportError as error:
            raise RuntimeError("learned resolver requires the 'learning' optional dependency") from error
        metadata_path = model_path.with_suffix(model_path.suffix + ".json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("feature_names") != FEATURE_NAMES:
            raise ValueError("ranker feature schema does not match this BSPForge version")
        self.model = lightgbm.Booster(model_file=str(model_path))
        self.metadata = metadata

    def score(self, candidates: list[dict[str, Any]], functions: dict[str, dict[str, Any]]) -> None:
        if not candidates:
            return
        matrix = [
            candidate_features(candidate, functions[candidate["entity_id"]])
            for candidate in candidates
        ]
        scores = self.model.predict(matrix)
        for candidate, score in zip(candidates, scores, strict=True):
            candidate["baseline_score"] = candidate["score"]
            candidate["score"] = round(float(score), 6)
            candidate["ranking_method"] = "lightgbm-lambdarank"
