from __future__ import annotations

import math
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA


FIELD_FEATURES = [
    "field-symbol-maxsim",
    "field-signature-maxsim",
    "field-calls-maxsim",
    "field-file-maxsim",
    "field-includes-maxsim",
]

STRUCTURE_FEATURES = [
    "static-score",
    "source-role-prior",
    "symbol-lexical-retrieval",
    "signature-contract-retrieval",
    "operation-contract-retrieval",
    "layer-route-score",
    "graph-neighbor-support",
    "api-family-support",
    "multi-channel-rrf",
    "opposite-action",
    "semantic-conflict",
    "reverse-os-adapter",
    "private-api",
    "test-example",
]

CAPABILITIES = list(CAPABILITY_SCHEMA)
OPERATIONS = [
    f"{capability}.{operation}"
    for capability, specification in CAPABILITY_SCHEMA.items()
    for operation in specification["operations"]
]
CAPABILITY_INDEX = {name: index for index, name in enumerate(CAPABILITIES)}
OPERATION_INDEX = {name: index for index, name in enumerate(OPERATIONS)}


def candidate_vector(candidate: dict[str, Any]) -> tuple[list[float], list[float]]:
    features = candidate["features"]
    fields = [float(features.get(name, 0.0)) for name in FIELD_FEATURES]
    structure = []
    for name in STRUCTURE_FEATURES:
        value = candidate["static_score"] if name == "static-score" else features.get(name, 0.0)
        structure.append(float(value))
    return fields, structure


class AdaptiveFieldRanker:
    """Small query/candidate-aware gate over frozen field MaxSim features."""

    def __init__(self, *, hidden_size: int = 12, device: str = "cpu") -> None:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("adaptive field ranking requires torch") from error
        self.torch = torch
        self.device = device

        class Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                base = [0.34, 0.28, 0.18, 0.12, 0.08]
                self.base_field_logits = torch.nn.Parameter(
                    torch.tensor([math.log(item) for item in base], dtype=torch.float32)
                )
                self.capability_gate = torch.nn.Embedding(len(CAPABILITIES), len(FIELD_FEATURES))
                self.operation_gate = torch.nn.Embedding(len(OPERATIONS), len(FIELD_FEATURES))
                self.candidate_gate = torch.nn.Linear(
                    len(STRUCTURE_FEATURES), len(FIELD_FEATURES), bias=False
                )
                self.structure = torch.nn.Linear(len(STRUCTURE_FEATURES), 1, bias=False)
                self.residual = torch.nn.Sequential(
                    torch.nn.Linear(len(FIELD_FEATURES) + len(STRUCTURE_FEATURES), hidden_size),
                    torch.nn.Tanh(),
                    torch.nn.Linear(hidden_size, 1, bias=False),
                )
                torch.nn.init.zeros_(self.capability_gate.weight)
                torch.nn.init.zeros_(self.operation_gate.weight)
                torch.nn.init.zeros_(self.candidate_gate.weight)
                torch.nn.init.zeros_(self.residual[0].bias)
                torch.nn.init.normal_(self.residual[0].weight, std=0.02)
                torch.nn.init.normal_(self.residual[2].weight, std=0.02)
                initial = torch.tensor(
                    [0.22, 0.03, 0.07, 0.03, 0.15, 0.16, 0.04, 0.08, 0.25, -0.08, -0.08, -0.10, -0.05, -0.05],
                    dtype=torch.float32,
                )
                with torch.no_grad():
                    self.structure.weight.copy_(initial[None, :])

            def forward(self, fields: Any, structure: Any, capability: Any, operation: Any) -> Any:
                query_gate = (
                    self.base_field_logits
                    + self.capability_gate(capability)
                    + self.operation_gate(operation)
                )
                gates = self.candidate_gate(structure) * 0.20 + query_gate
                gates = torch.softmax(gates, dim=-1)
                field_score = (gates * fields).sum(dim=-1)
                structure_score = self.structure(structure).squeeze(-1)
                residual = self.residual(torch.cat((fields, structure), dim=-1)).squeeze(-1)
                frozen_baseline = 0.25 * structure[:, 0] + 0.75 * (
                    0.34 * fields[:, 0]
                    + 0.28 * fields[:, 1]
                    + 0.18 * fields[:, 2]
                    + 0.12 * fields[:, 3]
                    + 0.08 * fields[:, 4]
                )
                learned = 0.55 * field_score + 0.45 * structure_score + 0.10 * residual
                return frozen_baseline + 0.12 * torch.tanh(learned - frozen_baseline)

        self.network = Network().to(device)

    def tensors(self, group: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        torch = self.torch
        vectors = [candidate_vector(item) for item in group["candidates"]]
        fields = torch.tensor([item[0] for item in vectors], dtype=torch.float32, device=self.device)
        structure = torch.tensor([item[1] for item in vectors], dtype=torch.float32, device=self.device)
        capability = torch.full(
            (len(vectors),), CAPABILITY_INDEX[group["capability"]], dtype=torch.long, device=self.device
        )
        operation = torch.full(
            (len(vectors),), OPERATION_INDEX[group["operation_id"]], dtype=torch.long, device=self.device
        )
        return fields, structure, capability, operation

    def score_tensor(self, group: dict[str, Any]) -> Any:
        return self.network(*self.tensors(group))

    def predict(self, group: dict[str, Any]) -> list[float]:
        with self.torch.no_grad():
            return [float(item) for item in self.score_tensor(group).cpu()]

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "method": "capability-adaptive field gate with structural residual",
            "field_features": FIELD_FEATURES,
            "structure_features": STRUCTURE_FEATURES,
            "capabilities": CAPABILITIES,
            "operations": OPERATIONS,
            "state_dict": self.network.state_dict(),
        }

    def load_payload(self, payload: dict[str, Any]) -> None:
        if payload["field_features"] != FIELD_FEATURES or payload["structure_features"] != STRUCTURE_FEATURES:
            raise ValueError("adaptive field ranker feature contract mismatch")
        self.network.load_state_dict(payload["state_dict"])

    def parameter_count(self) -> int:
        return sum(item.numel() for item in self.network.parameters())

    def gate_report(self) -> dict[str, Any]:
        torch = self.torch
        network = self.network
        output = {"capabilities": {}, "operations": {}}
        with torch.no_grad():
            for capability, index in CAPABILITY_INDEX.items():
                logits = network.base_field_logits + network.capability_gate.weight[index]
                output["capabilities"][capability] = {
                    name: round(float(value), 6)
                    for name, value in zip(FIELD_FEATURES, torch.softmax(logits, dim=-1), strict=True)
                }
            for operation, index in OPERATION_INDEX.items():
                capability = operation.partition(".")[0]
                logits = (
                    network.base_field_logits
                    + network.capability_gate.weight[CAPABILITY_INDEX[capability]]
                    + network.operation_gate.weight[index]
                )
                output["operations"][operation] = {
                    name: round(float(value), 6)
                    for name, value in zip(FIELD_FEATURES, torch.softmax(logits, dim=-1), strict=True)
                }
        return output
