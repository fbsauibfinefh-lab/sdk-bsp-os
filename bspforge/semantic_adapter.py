from __future__ import annotations

from pathlib import Path
from typing import Any

from bspforge.operation_encoder import operation_encoder_query
from bspforge.operation_ranking import candidate_code_text, operation_query_text


class QueryResidualAdapter:
    """Small query-side residual module without a mandatory torch import at package load."""

    def __init__(self, dimension: int, rank: int, device: str) -> None:
        import torch

        self.module = torch.nn.Sequential(
            torch.nn.Linear(dimension, rank, bias=False),
            torch.nn.Tanh(),
            torch.nn.Linear(rank, dimension, bias=False),
        ).to(device)
        torch.nn.init.normal_(self.module[0].weight, mean=0.0, std=0.02)
        torch.nn.init.zeros_(self.module[2].weight)

    def parameters(self) -> Any:
        return self.module.parameters()

    def train(self) -> None:
        self.module.train()

    def eval(self) -> None:
        self.module.eval()

    def __call__(self, values: Any) -> Any:
        import torch.nn.functional as functional

        return functional.normalize(values + self.module(values), dim=-1)


class OperationSemanticRanker:
    """Score operation-to-function pairs with a frozen encoder and query adapter."""

    def __init__(self, adapter_path: Path, device: str = "cpu", batch_size: int = 128) -> None:
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "operation-semantic resolver requires the 'retrieval' optional dependency"
            ) from error
        self.torch = torch
        self.device = device
        self.batch_size = batch_size
        self.payload = torch.load(adapter_path, map_location="cpu", weights_only=True)
        self.model = SentenceTransformer(
            self.payload["base_model"],
            revision=self.payload["base_revision"],
            device=device,
        )
        self.model.max_seq_length = 128
        self.adapter = QueryResidualAdapter(
            self.payload["dimension"], self.payload["rank"], device
        )
        self.adapter.module.load_state_dict(self.payload["state_dict"])
        self.adapter.eval()

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "base_model": self.payload["base_model"],
            "base_revision": self.payload["base_revision"],
            "query_format": self.payload["query_format"],
            "adapter_rank": self.payload["rank"],
        }

    def score_operations(
        self,
        capability: str,
        operations: list[str],
        candidates: list[dict[str, Any]],
        functions: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, dict[str, float]]]:
        import numpy as np

        groups = [
            {
                "capability": capability,
                "operation": operation,
                "query_text": operation_query_text(capability, operation),
            }
            for operation in operations
        ]
        documents = [candidate_code_text(functions[item["entity_id"]]) for item in candidates]
        document_vectors = self.model.encode(
            documents,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        base_queries = self.model.encode(
            [operation_encoder_query(group, "raw") for group in groups],
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        adapted_base = self.model.encode(
            [operation_encoder_query(group, self.payload["query_format"]) for group in groups],
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_tensor=True,
        ).to(self.device)
        with self.torch.no_grad():
            adapted_queries = self.adapter(adapted_base).cpu().numpy()
        output: dict[str, dict[str, dict[str, float]]] = {}
        for index, operation in enumerate(operations):
            operation_scores = {}
            for candidate, document in zip(candidates, document_vectors, strict=True):
                operation_scores[candidate["entity_id"]] = {
                    "base": (float(np.dot(base_queries[index], document)) + 1.0) / 2.0,
                    "adapted": (float(np.dot(adapted_queries[index], document)) + 1.0) / 2.0,
                }
            output[operation] = operation_scores
        return output
