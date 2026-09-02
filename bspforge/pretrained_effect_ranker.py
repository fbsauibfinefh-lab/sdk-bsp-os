from __future__ import annotations

from typing import Any

import numpy as np

from bspforge.code_effect_encoder import CodeEmbeddingCache
from bspforge.hardware_effect_graph import FEATURE_NAMES, hard_constraint_penalty
from bspforge.hardware_effect_ranker import OPERATIONS, OPERATION_INDEX, candidate_vector


class PretrainedEffectPURanker:
    """Frozen code embeddings with a low-rank query adapter and graph fusion head."""

    def __init__(
        self,
        cache: CodeEmbeddingCache,
        *,
        adapter_rank: int = 8,
        graph_hidden: int = 12,
        device: str = "cpu",
    ) -> None:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("pretrained effect ranking requires torch") from error
        self.torch = torch
        self.cache = cache
        self.device = device
        dimension = int(cache.documents.shape[1])
        feature_count = len(FEATURE_NAMES)

        class Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.query_down = torch.nn.Linear(dimension, adapter_rank, bias=False)
                self.query_up = torch.nn.Linear(adapter_rank, dimension, bias=False)
                self.graph = torch.nn.Sequential(
                    torch.nn.Linear(feature_count, graph_hidden),
                    torch.nn.Tanh(),
                    torch.nn.Linear(graph_hidden, 1, bias=False),
                )
                self.operation_gate = torch.nn.Embedding(len(OPERATIONS), 3)
                self.fusion = torch.nn.Linear(3, 1, bias=False)
                torch.nn.init.normal_(self.query_down.weight, mean=0.0, std=0.02)
                torch.nn.init.zeros_(self.query_up.weight)
                torch.nn.init.xavier_uniform_(self.graph[0].weight, gain=0.35)
                torch.nn.init.zeros_(self.graph[0].bias)
                torch.nn.init.xavier_uniform_(self.graph[2].weight, gain=0.35)
                torch.nn.init.zeros_(self.operation_gate.weight)
                with torch.no_grad():
                    self.fusion.weight.copy_(
                        torch.tensor([[0.20, 0.55, 0.25]], dtype=torch.float32)
                    )

            def components(
                self, query: Any, document: Any, graph_features: Any, operations: Any
            ) -> tuple[Any, Any, Any, Any]:
                adapted_query = torch.nn.functional.normalize(
                    query + self.query_up(torch.tanh(self.query_down(query))), dim=-1
                )
                base_similarity = (query * document).sum(dim=-1)
                adapted_similarity = (adapted_query * document).sum(dim=-1)
                graph_score = self.graph(graph_features).squeeze(-1)
                values = torch.stack(
                    [base_similarity, adapted_similarity, graph_score], dim=-1
                )
                gate = 1.0 + 0.30 * torch.tanh(self.operation_gate(operations))
                score = self.fusion(values * gate).squeeze(-1)
                return score, base_similarity, adapted_similarity, graph_score

            def forward(
                self, query: Any, document: Any, graph_features: Any, operations: Any
            ) -> Any:
                return self.components(query, document, graph_features, operations)[0]

        self.network = Network().to(device)
        self.graph_mean = torch.zeros(feature_count, dtype=torch.float32, device=device)
        self.graph_scale = torch.ones(feature_count, dtype=torch.float32, device=device)

    def fit_scaler(self, candidates: list[dict[str, Any]]) -> None:
        values = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        self.graph_mean = values.mean(dim=0)
        self.graph_scale = values.std(dim=0).clamp_min(0.05)

    def graph_tensor(self, candidates: list[dict[str, Any]]) -> Any:
        values = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        return (values - self.graph_mean) / self.graph_scale

    def query_tensor(self, operation_ids: list[str]) -> Any:
        return self.torch.tensor(
            np.stack([self.cache.query_vector(item) for item in operation_ids]),
            dtype=self.torch.float32,
            device=self.device,
        )

    def document_tensor(
        self, groups: list[dict[str, Any]], indices: list[int]
    ) -> Any:
        values = []
        for group, index in zip(groups, indices, strict=True):
            candidate = group["candidates"][index]
            key = self.cache.candidate_key(candidate, group["sdk_id"])
            values.append(self.cache.documents[self.cache.document_index[key]])
        return self.torch.tensor(
            np.stack(values), dtype=self.torch.float32, device=self.device
        )

    def operation_tensor(self, operation_ids: list[str]) -> Any:
        return self.torch.tensor(
            [OPERATION_INDEX[item] for item in operation_ids],
            dtype=self.torch.long,
            device=self.device,
        )

    def group_components(self, group: dict[str, Any]) -> dict[str, list[float]]:
        size = len(group["candidates"])
        operation_ids = [group["operation_id"]] * size
        indices = list(range(size))
        with self.torch.no_grad():
            values = self.network.components(
                self.query_tensor(operation_ids),
                self.document_tensor([group] * size, indices),
                self.graph_tensor(group["candidates"]),
                self.operation_tensor(operation_ids),
            )
        names = ["fusion", "base", "adapted", "graph"]
        output = {
            name: [float(item) for item in tensor.detach().cpu()]
            for name, tensor in zip(names, values, strict=True)
        }
        for name in ("fusion", "base", "adapted"):
            output[name] = [
                score - 4.0 * hard_constraint_penalty(candidate)
                for score, candidate in zip(
                    output[name], group["candidates"], strict=True
                )
            ]
        return output

    def parameter_count(self) -> int:
        return sum(item.numel() for item in self.network.parameters())

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "0.2",
            "method": "frozen pretrained code encoder with low-rank query adaptation and hardware graph fusion",
            "feature_names": FEATURE_NAMES,
            "operations": OPERATIONS,
            "embedding_metadata": self.cache.metadata["model"],
            "graph_mean": self.graph_mean.detach().cpu(),
            "graph_scale": self.graph_scale.detach().cpu(),
            "state_dict": self.network.state_dict(),
        }
