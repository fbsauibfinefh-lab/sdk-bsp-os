from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, read_json


class FrozenOperationRanker:
    """Serve label-free operation scores exported by a frozen ranking pipeline."""

    SCHEMA_VERSION = "frozen-operation-ranking-v1"

    def __init__(self, bundle_path: Path) -> None:
        self.path = bundle_path.resolve()
        self.payload = read_json(self.path)
        if self.payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported frozen operation ranking bundle")
        if self.payload.get("contains_labels", True):
            raise ValueError("runtime ranking bundle must not contain labels")
        self._operations = self.payload.get("operations", {})
        if not self._operations:
            raise ValueError("runtime ranking bundle has no operations")
        self._scores: dict[str, dict[str, float]] = {}
        for operation_id, operation in self._operations.items():
            rows = operation.get("candidates", [])
            if not rows:
                raise ValueError(f"runtime bundle has no candidates: {operation_id}")
            if operation.get("candidate_count") != len(rows):
                raise ValueError(f"candidate count mismatch: {operation_id}")
            scores = {row["entity_id"]: float(row["score"]) for row in rows}
            if len(scores) != len(rows):
                raise ValueError(f"duplicate entities in runtime bundle: {operation_id}")
            if not all(math.isfinite(score) for score in scores.values()):
                raise ValueError(f"non-finite candidate score: {operation_id}")
            ordered = sorted(scores, key=lambda entity_id: (-scores[entity_id], entity_id))
            if operation.get("selected_entity_id") != ordered[0]:
                raise ValueError(f"selected entity does not match frozen Top1: {operation_id}")
            self._scores[operation_id] = scores

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.payload["schema_version"],
            "bundle": str(self.path),
            "bundle_sha256": file_sha256(self.path),
            "method": self.payload["method"],
            "sdk": self.payload["sdk"],
            "model": self.payload["model"],
            "feature_contract": self.payload["feature_contract"],
        }

    def validate_ir(self, ir: dict[str, Any]) -> None:
        expected = self.payload["sdk"]
        actual = ir["sdk"]
        if actual["id"] != expected["id"]:
            raise ValueError(
                f"frozen ranking SDK mismatch: {actual['id']} != {expected['id']}"
            )
        if actual["digest"] != expected["digest"]:
            raise ValueError(
                "frozen ranking bundle does not match the ingested SDK digest"
            )

    def score_candidates(
        self, operation_id: str, entity_ids: list[str]
    ) -> dict[str, float]:
        if operation_id not in self._scores:
            raise ValueError(f"operation absent from frozen ranking bundle: {operation_id}")
        stored = self._scores[operation_id]
        missing = sorted(set(stored).difference(entity_ids))
        if missing:
            preview = ", ".join(missing[:3])
            raise ValueError(
                f"runtime IR misses {len(missing)} frozen candidates for "
                f"{operation_id}: {preview}"
            )
        return dict(stored)
