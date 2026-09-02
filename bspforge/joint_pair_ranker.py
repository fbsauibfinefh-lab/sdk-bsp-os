from __future__ import annotations

from typing import Any

import numpy as np

from bspforge.hardware_effect_graph import hardware_heuristic_score
from bspforge.hardware_effect_ranker import OPERATIONS, OPERATION_INDEX
from bspforge.multiview_effect_encoder import JointPairCache, MultiViewEffectCache
from bspforge.multiview_effect_ranker import operation_constraint_penalty
from bspforge.structured_retrieval import complete_structured_scores


SCALAR_FEATURE_NAMES = [
    "full-code-cosine",
    "focused-code-cosine",
    "full-focused-cosine",
    "q4-structured-score",
    "hardware-graph-score",
    "static-score",
    "field-late-interaction",
    "generic-operation-fit",
    "operation-contract-retrieval",
    "signature-contract-retrieval",
]


class JointPairRanker:
    def __init__(
        self,
        multiview_cache: MultiViewEffectCache,
        joint_cache: JointPairCache,
        *,
        hidden: int = 32,
        dropout: float = 0.15,
        device: str = "cpu",
    ) -> None:
        import torch

        self.torch = torch
        self.multiview_cache = multiview_cache
        self.joint_cache = joint_cache
        self.device = device
        self._scalar_cache: dict[str, np.ndarray] = {}
        dimension = int(joint_cache.vectors.shape[1])

        class Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.joint_down = torch.nn.Linear(dimension, hidden)
                self.operation_film = torch.nn.Embedding(len(OPERATIONS), hidden * 2)
                self.joint_out = torch.nn.Linear(hidden, 1, bias=False)
                self.scalar = torch.nn.Sequential(
                    torch.nn.Linear(len(SCALAR_FEATURE_NAMES), 12),
                    torch.nn.Tanh(),
                    torch.nn.Dropout(dropout),
                    torch.nn.Linear(12, 1, bias=False),
                )
                self.fusion = torch.nn.Linear(2, 1, bias=False)
                self.dropout = torch.nn.Dropout(dropout)
                torch.nn.init.zeros_(self.operation_film.weight)
                with torch.no_grad():
                    self.fusion.weight.copy_(
                        torch.tensor([[0.70, 0.30]], dtype=torch.float32)
                    )

            def components(
                self, joint: Any, scalar: Any, operations: Any
            ) -> tuple[Any, Any, Any]:
                hidden_value = torch.tanh(self.joint_down(joint))
                scale, shift = self.operation_film(operations).chunk(2, dim=-1)
                hidden_value = hidden_value * (1.0 + 0.20 * torch.tanh(scale)) + 0.20 * shift
                joint_score = self.joint_out(self.dropout(hidden_value)).squeeze(-1)
                scalar_score = self.scalar(scalar).squeeze(-1)
                fusion = self.fusion(
                    torch.stack([joint_score, scalar_score], dim=-1)
                ).squeeze(-1)
                return fusion, joint_score, scalar_score

            def forward(self, joint: Any, scalar: Any, operations: Any) -> Any:
                return self.components(joint, scalar, operations)[0]

        self.network = Network().to(device)
        self.scalar_mean = torch.zeros(len(SCALAR_FEATURE_NAMES), device=device)
        self.scalar_scale = torch.ones(len(SCALAR_FEATURE_NAMES), device=device)

    def shortlist_indices(self, group: dict[str, Any]) -> list[int]:
        return [
            index for index, candidate in enumerate(group["candidates"])
            if self.joint_cache.contains(group, candidate)
        ]

    def _group_scalars(self, group: dict[str, Any]) -> np.ndarray:
        if group["group_id"] in self._scalar_cache:
            return self._scalar_cache[group["group_id"]]
        query = self.multiview_cache.base.query_vector(group["operation_id"])
        q4 = complete_structured_scores(group)[0]
        rows = []
        for index, candidate in enumerate(group["candidates"]):
            base_key = self.multiview_cache.base.candidate_key(candidate, group["sdk_id"])
            full = self.multiview_cache.base.documents[
                self.multiview_cache.base.document_index[base_key]
            ]
            focused = self.multiview_cache.focused_vector(group, candidate)
            features = candidate["features"]
            rows.append([
                float(np.dot(query, full)),
                float(np.dot(query, focused)),
                float(np.dot(full, focused)),
                float(q4[index]),
                float(hardware_heuristic_score(candidate)),
                float(candidate.get("static_score", 0.0)),
                float(features.get("field-late-interaction", 0.0)),
                float(features.get("generic-operation-fit", 0.0)),
                float(features.get("operation-contract-retrieval", 0.0)),
                float(features.get("signature-contract-retrieval", 0.0)),
            ])
        values = np.asarray(rows, dtype=np.float32)
        self._scalar_cache[group["group_id"]] = values
        return values

    def fit_scaler(self, groups: list[dict[str, Any]]) -> None:
        rows = []
        for group in groups:
            indices = self.shortlist_indices(group)
            rows.extend(self._group_scalars(group)[indices])
        values = self.torch.tensor(
            np.asarray(rows), dtype=self.torch.float32, device=self.device
        )
        self.scalar_mean = values.mean(dim=0)
        self.scalar_scale = values.std(dim=0).clamp_min(0.05)

    def input_tensors(
        self, groups: list[dict[str, Any]], indices: list[int]
    ) -> tuple[Any, Any, Any]:
        vectors = []
        scalars = []
        operations = []
        for group, index in zip(groups, indices, strict=True):
            candidate = group["candidates"][index]
            vectors.append(self.joint_cache.vector(group, candidate))
            scalars.append(self._group_scalars(group)[index])
            operations.append(OPERATION_INDEX[group["operation_id"]])
        scalar_tensor = self.torch.tensor(
            np.asarray(scalars), dtype=self.torch.float32, device=self.device
        )
        return (
            self.torch.tensor(
                np.stack(vectors), dtype=self.torch.float32, device=self.device
            ),
            (scalar_tensor - self.scalar_mean) / self.scalar_scale,
            self.torch.tensor(operations, dtype=self.torch.long, device=self.device),
        )

    def score_tensor(self, groups: list[dict[str, Any]], indices: list[int]) -> Any:
        return self.network(*self.input_tensors(groups, indices))

    def group_components(self, group: dict[str, Any]) -> dict[str, list[float]]:
        indices = self.shortlist_indices(group)
        with self.torch.no_grad():
            tensors = self.network.components(
                *self.input_tensors([group] * len(indices), indices)
            )
        output = {}
        for name, tensor in zip(
            ("fusion", "joint", "scalar"), tensors, strict=True
        ):
            output[name] = [
                float(score) - 8.0 * operation_constraint_penalty(
                    group["candidates"][index], group["operation_id"]
                )
                for score, index in zip(tensor.detach().cpu(), indices, strict=True)
            ]
        output["indices"] = indices
        return output

    def parameter_count(self) -> int:
        return sum(item.numel() for item in self.network.parameters())

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "0.3-joint",
            "method": "frozen joint query-candidate encoding with operation FiLM and scalar evidence",
            "scalar_feature_names": SCALAR_FEATURE_NAMES,
            "operations": OPERATIONS,
            "scalar_mean": self.scalar_mean.detach().cpu(),
            "scalar_scale": self.scalar_scale.detach().cpu(),
            "state_dict": self.network.state_dict(),
        }
