from __future__ import annotations

import re
from typing import Any

import numpy as np

from bspforge.code_effect_encoder import CodeEmbeddingCache, normalize_code
from bspforge.hardware_effect_graph import (
    ACTION_TERMS,
    CAPABILITY_TERMS,
    SourceCorpus,
    identifier_tokens,
)


STATEMENT_RE = re.compile(r"[^;{}]+[;{}]?")
ASSIGNMENT_RE = re.compile(r"(?:->|\.)\s*[A-Za-z_]\w*\s*(?:\|=|&=|\^=|=)")
READ_RE = re.compile(r"\b(?:return|read|recv|receive|get|load|input)\w*\b", re.I)
WRITE_RE = re.compile(r"\b(?:write|send|transmit|put|set|clear|store|output)\w*\b", re.I)


def _statement_score(
    statement: str,
    *,
    capability: str,
    operation: str,
    register_hits: list[str],
    path_symbols: list[str],
) -> float:
    lowered = statement.lower()
    tokens = set(identifier_tokens(statement))
    score = 0.0
    score += 1.5 * len(tokens & CAPABILITY_TERMS[capability])
    score += 1.8 * len(tokens & ACTION_TERMS[operation])
    score += 3.0 * sum(item.lower() in lowered for item in register_hits)
    score += 1.2 * sum(item.lower() in lowered for item in path_symbols[1:])
    if operation in {
        "initialize", "configure", "enable", "disable", "write",
        "start", "stop", "set_interval",
    }:
        score += 1.8 * bool(ASSIGNMENT_RE.search(statement))
        score += 1.0 * bool(WRITE_RE.search(statement))
    if operation in {"read", "get_frequency"}:
        score += 1.8 * bool(READ_RE.search(statement))
    if operation in {"register", "attach_irq"}:
        score += 1.2 * bool(tokens & {"callback", "handler", "vector", "irq", "isr"})
    return score


def operation_effect_slice(
    body: str,
    operation_id: str,
    evidence: dict[str, Any],
    *,
    max_statements: int = 10,
) -> str:
    capability, operation = operation_id.split(".", 1)
    normalized = normalize_code(body, max_characters=12_000)
    statements = [item.strip() for item in STATEMENT_RE.findall(normalized) if item.strip()]
    if not statements:
        return ""
    register_hits = list(evidence.get("register_hits", []))
    path_symbols = list(evidence.get("effect_path", []))
    scored = [
        (
            _statement_score(
                statement,
                capability=capability,
                operation=operation,
                register_hits=register_hits,
                path_symbols=path_symbols,
            ),
            index,
        )
        for index, statement in enumerate(statements)
    ]
    anchors = [index for score, index in sorted(scored, reverse=True) if score > 0][:6]
    if not anchors:
        anchors = list(range(min(4, len(statements))))
    selected = set()
    for index in anchors:
        selected.update({max(0, index - 1), index, min(len(statements) - 1, index + 1)})
    ordered = sorted(selected)[:max_statements]
    return " ".join(statements[index] for index in ordered)


def focused_candidate_document(
    group: dict[str, Any],
    candidate: dict[str, Any],
    function: dict[str, Any],
    corpus: SourceCorpus,
) -> str:
    evidence = candidate.get("hardware_effect_evidence", {})
    path = " -> ".join(evidence.get("effect_path", []))
    registers = " ".join(evidence.get("register_hits", []))
    body_slice = operation_effect_slice(
        corpus.function_body(function), group["operation_id"], evidence
    )
    return (
        f"SDK interface. symbol: {candidate['symbol']}. "
        f"signature: {function.get('signature', '')}. "
        f"source role: {candidate.get('source_role', '')}. "
        f"effect call path: {path}. register identifiers: {registers}. "
        f"operation-relevant code slice: {body_slice}"
    )


def joint_query_candidate_document(query: str, focused_document: str) -> str:
    return f"Required operation: {query} Candidate implementation: {focused_document}"


class MultiViewEffectCache:
    def __init__(
        self,
        base_metadata_path: Any,
        base_vectors_path: Any,
        focused_metadata_path: Any,
        focused_vectors_path: Any,
    ) -> None:
        from bspforge.common import read_json

        self.base = CodeEmbeddingCache(base_metadata_path, base_vectors_path)
        self.metadata = read_json(focused_metadata_path)
        archive = np.load(focused_vectors_path)
        self.focused_keys = self.metadata["focused_keys"]
        self.focused_index = {key: index for index, key in enumerate(self.focused_keys)}
        self.focused = archive["focused"].astype(np.float32)
        self.joint = (
            archive["joint"].astype(np.float32) if "joint" in archive.files else None
        )
        if self.focused.shape[0] != len(self.focused_keys):
            raise ValueError("focused embedding index mismatch")
        if self.joint is not None and self.joint.shape[0] != len(self.focused_keys):
            raise ValueError("joint embedding index mismatch")

    @staticmethod
    def focused_key(group: dict[str, Any], candidate: dict[str, Any]) -> str:
        return f"{group['group_id']}::{candidate['entity_id']}"

    def focused_vector(self, group: dict[str, Any], candidate: dict[str, Any]) -> np.ndarray:
        return self.focused[self.focused_index[self.focused_key(group, candidate)]]

    def joint_vector(self, group: dict[str, Any], candidate: dict[str, Any]) -> np.ndarray:
        if self.joint is None:
            raise ValueError("joint query-candidate vectors are not available")
        return self.joint[self.focused_index[self.focused_key(group, candidate)]]


class JointPairCache:
    def __init__(self, metadata_path: Any, vectors_path: Any) -> None:
        from bspforge.common import read_json

        self.metadata = read_json(metadata_path)
        archive = np.load(vectors_path)
        self.keys = self.metadata["joint_keys"]
        self.index = {key: index for index, key in enumerate(self.keys)}
        self.vectors = archive["joint"].astype(np.float32)
        if self.vectors.shape[0] != len(self.keys):
            raise ValueError("joint pair embedding index mismatch")

    @staticmethod
    def key(group: dict[str, Any], candidate: dict[str, Any]) -> str:
        return f"{group['group_id']}::{candidate['entity_id']}"

    def contains(self, group: dict[str, Any], candidate: dict[str, Any]) -> bool:
        return self.key(group, candidate) in self.index

    def vector(self, group: dict[str, Any], candidate: dict[str, Any]) -> np.ndarray:
        return self.vectors[self.index[self.key(group, candidate)]]
