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
    "baseline-score",
    "evidence-kind-count",
    "name-capability-action-joint",
    "canonical-name-order",
    "driver-hal-path",
    "public-include-path",
    "test-example-path",
    "internal-private-path",
    "private-symbol",
    "identifier-token-count",
    "identifier-length",
]


def candidate_features(candidate: dict[str, Any], function: dict[str, Any]) -> list[float]:
    values = candidate_feature_map(candidate, function)
    return [values[name] for name in FEATURE_NAMES]


def candidate_feature_map(candidate: dict[str, Any], function: dict[str, Any]) -> dict[str, float]:
    evidence_items = candidate.get("evidence", [])
    evidence = {
        item["kind"]: min(1.0, len(item.get("matches", [])) / 4.0)
        for item in evidence_items
    }
    values = {name: evidence.get(name, 0.0) for name in FEATURE_NAMES[:-1]}
    values["parser-confidence"] = float(function.get("parser_confidence", 0.55))
    values["baseline-score"] = float(candidate.get("baseline_score", candidate.get("score", 0.0)))
    values["evidence-kind-count"] = min(1.0, len(evidence_items) / 7.0)
    name_capability = next((item for item in evidence_items if item["kind"] == "name-capability"), None)
    name_action = next((item for item in evidence_items if item["kind"] == "name-action"), None)
    values["name-capability-action-joint"] = float(bool(name_capability and name_action))
    symbol = candidate.get("symbol", "").lower()
    capability_matches = name_capability.get("matches", []) if name_capability else []
    action_matches = name_action.get("matches", []) if name_action else []
    values["canonical-name-order"] = float(any(
        symbol.find(capability) <= symbol.find(action)
        for capability in capability_matches
        for action in action_matches
        if symbol.find(capability) >= 0 and symbol.find(action) >= 0
    ))
    path = function.get("file", "").lower()
    values["driver-hal-path"] = float(any(token in path for token in ("driver", "/hal/", "_hal/", "/pdl/")))
    values["public-include-path"] = float(any(token in path for token in ("/include/", "/inc/", "include/")))
    values["test-example-path"] = float(any(token in path for token in ("/test", "test/", "/example", "examples/", "/sample")))
    values["internal-private-path"] = float(any(token in path for token in ("/internal", "private", "/port/", "/mock")))
    values["private-symbol"] = float(symbol.startswith("_") or "internal" in symbol or "private" in symbol)
    values["identifier-token-count"] = min(1.0, len([item for item in symbol.split("_") if item]) / 8.0)
    values["identifier-length"] = min(1.0, len(symbol) / 64.0)
    return values


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

    def score(
        self,
        candidates: list[dict[str, Any]],
        functions: dict[str, dict[str, Any]],
        baseline_weight: float = 0.0,
    ) -> None:
        if not candidates:
            return
        if not 0.0 <= baseline_weight <= 1.0:
            raise ValueError("baseline_weight must be between 0 and 1")
        matrix = [
            candidate_features(candidate, functions[candidate["entity_id"]])
            for candidate in candidates
        ]
        scores = self.model.predict(matrix)
        low = float(min(scores))
        high = float(max(scores))
        span = high - low
        for candidate, score in zip(candidates, scores, strict=True):
            baseline_score = float(candidate["score"])
            learned_score = (float(score) - low) / span if span > 1e-12 else 0.0
            candidate["baseline_score"] = baseline_score
            candidate["raw_ranking_score"] = round(float(score), 6)
            candidate["learned_score"] = round(learned_score, 6)
            candidate["score"] = round(
                baseline_weight * baseline_score + (1.0 - baseline_weight) * learned_score,
                6,
            )
            candidate["ranking_method"] = (
                "weighted-lightgbm-hybrid" if baseline_weight else "lightgbm-lambdarank"
            )
