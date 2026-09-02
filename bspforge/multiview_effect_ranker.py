from __future__ import annotations

from typing import Any

import numpy as np

from bspforge.hardware_effect_graph import (
    FEATURE_NAMES,
    hard_constraint_penalty,
    identifier_tokens,
)
from bspforge.hardware_effect_ranker import OPERATIONS, OPERATION_INDEX, candidate_vector
from bspforge.multiview_effect_encoder import MultiViewEffectCache


STRUCTURED_FEATURE_NAMES = [
    "static_score",
    "field-late-interaction",
    "operation-contract-retrieval",
    "signature-contract-retrieval",
    "symbol-lexical-retrieval",
    "source-role-prior",
    "layer-route-score",
    "generic-operation-fit",
    "graph-neighbor-support",
    "api-family-support",
    "multi-channel-rrf",
    "operation-exact",
    "operation-substring",
    "signature-hint",
    "parameterized-toggle",
    "opposite-action",
    "semantic-conflict",
    "reverse-os-adapter",
    "test-example",
]


def structured_vector(candidate: dict[str, Any]) -> list[float]:
    features = candidate["features"]
    return [
        float(candidate.get("static_score", 0.0))
        if name == "static_score"
        else float(features.get(name, 0.0))
        for name in STRUCTURED_FEATURE_NAMES
    ]


def operation_constraint_penalty(
    candidate: dict[str, Any], operation_id: str
) -> float:
    penalty = hard_constraint_penalty(candidate)
    operation = operation_id.split(".", 1)[1]
    features = candidate["features"]
    tokens = set(identifier_tokens(candidate["symbol"]))
    status_tokens = {"is", "has", "status", "check", "query", "ready", "running"}
    mutating = operation in {
        "initialize", "configure", "enable", "disable", "write",
        "start", "stop", "set_interval", "register", "attach_irq",
    }
    write_evidence = max(
        float(features.get("hw-write-access", 0.0)),
        float(features.get("hw-bitwise-update", 0.0)),
        float(features.get("hw-mmio-access", 0.0)),
    )
    if mutating and tokens & status_tokens and write_evidence < 0.50:
        penalty = max(penalty, 1.0)
    if mutating and tokens & {"get", "read"} and write_evidence < 0.25:
        penalty = max(penalty, 0.75)
    return min(1.0, penalty)


class MultiViewEffectRanker:
    """Operation-conditioned full/focused code views with graph and structured evidence."""

    def __init__(
        self,
        cache: MultiViewEffectCache,
        *,
        adapter_rank: int = 8,
        hidden: int = 12,
        dropout: float = 0.10,
        device: str = "cpu",
    ) -> None:
        import torch

        self.torch = torch
        self.cache = cache
        self.device = device
        dimension = int(cache.base.documents.shape[1])

        class Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.query_down = torch.nn.Linear(dimension, adapter_rank, bias=False)
                self.query_up = torch.nn.Linear(adapter_rank, dimension, bias=False)
                self.focus_down = torch.nn.Linear(dimension, adapter_rank, bias=False)
                self.focus_up = torch.nn.Linear(adapter_rank, dimension, bias=False)
                self.graph = torch.nn.Sequential(
                    torch.nn.Linear(len(FEATURE_NAMES), hidden),
                    torch.nn.Tanh(),
                    torch.nn.Dropout(dropout),
                    torch.nn.Linear(hidden, 1, bias=False),
                )
                self.structured = torch.nn.Sequential(
                    torch.nn.Linear(len(STRUCTURED_FEATURE_NAMES), hidden),
                    torch.nn.Tanh(),
                    torch.nn.Dropout(dropout),
                    torch.nn.Linear(hidden, 1, bias=False),
                )
                self.operation_gate = torch.nn.Embedding(len(OPERATIONS), 4)
                self.fusion = torch.nn.Linear(4, 1, bias=False)
                torch.nn.init.normal_(self.query_down.weight, std=0.02)
                torch.nn.init.zeros_(self.query_up.weight)
                torch.nn.init.normal_(self.focus_down.weight, std=0.02)
                torch.nn.init.zeros_(self.focus_up.weight)
                torch.nn.init.zeros_(self.operation_gate.weight)
                with torch.no_grad():
                    self.fusion.weight.copy_(
                        torch.tensor([[0.20, 0.50, 0.15, 0.15]], dtype=torch.float32)
                    )

            def components(
                self,
                query: Any,
                full_document: Any,
                focused_document: Any,
                graph_features: Any,
                structured_features: Any,
                operations: Any,
            ) -> tuple[Any, Any, Any, Any, Any]:
                adapted_query = torch.nn.functional.normalize(
                    query + self.query_up(torch.tanh(self.query_down(query))), dim=-1
                )
                adapted_focus = torch.nn.functional.normalize(
                    focused_document
                    + self.focus_up(torch.tanh(self.focus_down(focused_document))),
                    dim=-1,
                )
                full_score = (adapted_query * full_document).sum(dim=-1)
                focused_score = (adapted_query * adapted_focus).sum(dim=-1)
                graph_score = self.graph(graph_features).squeeze(-1)
                structured_score = self.structured(structured_features).squeeze(-1)
                values = torch.stack(
                    [full_score, focused_score, graph_score, structured_score], dim=-1
                )
                gate = 1.0 + 0.30 * torch.tanh(self.operation_gate(operations))
                fusion = self.fusion(values * gate).squeeze(-1)
                return fusion, full_score, focused_score, graph_score, structured_score

            def forward(self, *args: Any) -> Any:
                return self.components(*args)[0]

        self.network = Network().to(device)
        self.graph_mean = torch.zeros(len(FEATURE_NAMES), device=device)
        self.graph_scale = torch.ones(len(FEATURE_NAMES), device=device)
        self.structured_mean = torch.zeros(len(STRUCTURED_FEATURE_NAMES), device=device)
        self.structured_scale = torch.ones(len(STRUCTURED_FEATURE_NAMES), device=device)

    def fit_scaler(self, candidates: list[dict[str, Any]]) -> None:
        graph = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        structured = self.torch.tensor(
            [structured_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        self.graph_mean = graph.mean(dim=0)
        self.graph_scale = graph.std(dim=0).clamp_min(0.05)
        self.structured_mean = structured.mean(dim=0)
        self.structured_scale = structured.std(dim=0).clamp_min(0.05)

    def query_tensor(self, operation_ids: list[str]) -> Any:
        return self.torch.tensor(
            np.stack([self.cache.base.query_vector(item) for item in operation_ids]),
            dtype=self.torch.float32,
            device=self.device,
        )

    def operation_tensor(self, operation_ids: list[str]) -> Any:
        return self.torch.tensor(
            [OPERATION_INDEX[item] for item in operation_ids],
            dtype=self.torch.long,
            device=self.device,
        )

    def _selected_candidates(
        self, groups: list[dict[str, Any]], indices: list[int]
    ) -> list[dict[str, Any]]:
        return [
            group["candidates"][index]
            for group, index in zip(groups, indices, strict=True)
        ]

    def input_tensors(
        self, groups: list[dict[str, Any]], indices: list[int]
    ) -> tuple[Any, Any, Any, Any, Any, Any]:
        candidates = self._selected_candidates(groups, indices)
        operation_ids = [group["operation_id"] for group in groups]
        full = []
        focused = []
        for group, candidate in zip(groups, candidates, strict=True):
            base_key = self.cache.base.candidate_key(candidate, group["sdk_id"])
            full.append(self.cache.base.documents[self.cache.base.document_index[base_key]])
            focused.append(self.cache.focused_vector(group, candidate))
        graph = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        structured = self.torch.tensor(
            [structured_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        return (
            self.query_tensor(operation_ids),
            self.torch.tensor(np.stack(full), dtype=self.torch.float32, device=self.device),
            self.torch.tensor(np.stack(focused), dtype=self.torch.float32, device=self.device),
            (graph - self.graph_mean) / self.graph_scale,
            (structured - self.structured_mean) / self.structured_scale,
            self.operation_tensor(operation_ids),
        )

    def score_tensor(self, groups: list[dict[str, Any]], indices: list[int]) -> Any:
        return self.network(*self.input_tensors(groups, indices))

    def group_components(self, group: dict[str, Any]) -> dict[str, list[float]]:
        size = len(group["candidates"])
        with self.torch.no_grad():
            tensors = self.network.components(
                *self.input_tensors([group] * size, list(range(size)))
            )
        names = ["fusion", "full", "focused", "graph", "structured"]
        output = {
            name: [float(item) for item in tensor.detach().cpu()]
            for name, tensor in zip(names, tensors, strict=True)
        }
        for name in output:
            output[name] = [
                score - 4.0 * operation_constraint_penalty(
                    candidate, group["operation_id"]
                )
                for score, candidate in zip(
                    output[name], group["candidates"], strict=True
                )
            ]
        return output

    def parameter_count(self) -> int:
        return sum(item.numel() for item in self.network.parameters())

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "0.3",
            "method": "operation-conditioned multiview effect-slice ranking",
            "graph_feature_names": FEATURE_NAMES,
            "structured_feature_names": STRUCTURED_FEATURE_NAMES,
            "operations": OPERATIONS,
            "graph_mean": self.graph_mean.detach().cpu(),
            "graph_scale": self.graph_scale.detach().cpu(),
            "structured_mean": self.structured_mean.detach().cpu(),
            "structured_scale": self.structured_scale.detach().cpu(),
            "state_dict": self.network.state_dict(),
        }
