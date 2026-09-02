from __future__ import annotations

from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.hardware_effect_graph import FEATURE_NAMES, hard_constraint_penalty


OPERATIONS = [
    f"{capability}.{operation}"
    for capability, specification in CAPABILITY_SCHEMA.items()
    for operation in specification["operations"]
]
OPERATION_INDEX = {name: index for index, name in enumerate(OPERATIONS)}


def candidate_vector(candidate: dict[str, Any]) -> list[float]:
    return [float(candidate["features"].get(name, 0.0)) for name in FEATURE_NAMES]


class HardwareEffectPURanker:
    """Small operation-gated ranker trained only on positive-unlabeled preferences."""

    def __init__(self, *, hidden_size: int = 12, device: str = "cpu") -> None:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("hardware-effect PU ranking requires torch") from error
        self.torch = torch
        self.device = device
        feature_count = len(FEATURE_NAMES)

        class Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.operation_gate = torch.nn.Embedding(len(OPERATIONS), feature_count)
                self.hidden = torch.nn.Sequential(
                    torch.nn.Linear(feature_count, hidden_size),
                    torch.nn.Tanh(),
                    torch.nn.Linear(hidden_size, 1, bias=False),
                )
                self.linear = torch.nn.Linear(feature_count, 1, bias=False)
                torch.nn.init.zeros_(self.operation_gate.weight)
                torch.nn.init.xavier_uniform_(self.hidden[0].weight, gain=0.5)
                torch.nn.init.zeros_(self.hidden[0].bias)
                torch.nn.init.xavier_uniform_(self.hidden[2].weight, gain=0.5)
                initial = torch.tensor(
                    [0.16, 0.55, 0.08, -0.04, 0.20, 0.08, 0.08, 0.10, -0.08,
                     0.03, 0.08, 0.04, 0.04, 0.04, 0.03, 0.10, 0.20, -0.14,
                     -0.12, -0.08, -0.18, -0.12],
                    dtype=torch.float32,
                )
                with torch.no_grad():
                    self.linear.weight.copy_(initial[None, :])

            def forward(self, features: Any, operations: Any) -> Any:
                gate = 1.0 + 0.35 * torch.tanh(self.operation_gate(operations))
                gated = features * gate
                return self.linear(gated).squeeze(-1) + 0.20 * self.hidden(gated).squeeze(-1)

        self.network = Network().to(device)
        self.mean = torch.zeros(feature_count, dtype=torch.float32, device=device)
        self.scale = torch.ones(feature_count, dtype=torch.float32, device=device)

    def fit_scaler(self, candidates: list[dict[str, Any]]) -> None:
        values = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        self.mean = values.mean(dim=0)
        self.scale = values.std(dim=0).clamp_min(0.05)

    def feature_tensor(self, candidates: list[dict[str, Any]]) -> Any:
        values = self.torch.tensor(
            [candidate_vector(item) for item in candidates],
            dtype=self.torch.float32,
            device=self.device,
        )
        return (values - self.mean) / self.scale

    def operation_tensor(self, operation_id: str, size: int) -> Any:
        return self.torch.full(
            (size,), OPERATION_INDEX[operation_id], dtype=self.torch.long, device=self.device
        )

    def score_tensor(self, candidates: list[dict[str, Any]], operation_id: str) -> Any:
        return self.network(
            self.feature_tensor(candidates), self.operation_tensor(operation_id, len(candidates))
        )

    def predict(self, group: dict[str, Any], *, protect: bool = True) -> list[float]:
        with self.torch.no_grad():
            scores = [float(item) for item in self.score_tensor(
                group["candidates"], group["operation_id"]
            ).cpu()]
        if protect:
            scores = [
                score - 4.0 * hard_constraint_penalty(candidate)
                for score, candidate in zip(scores, group["candidates"], strict=True)
            ]
        return scores

    def parameter_count(self) -> int:
        return sum(item.numel() for item in self.network.parameters())

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1",
            "method": "register-anchored hardware-effect graph PU pairwise ranker",
            "feature_names": FEATURE_NAMES,
            "operations": OPERATIONS,
            "mean": self.mean.detach().cpu(),
            "scale": self.scale.detach().cpu(),
            "state_dict": self.network.state_dict(),
        }

    def load_payload(self, payload: dict[str, Any]) -> None:
        if payload["feature_names"] != FEATURE_NAMES or payload["operations"] != OPERATIONS:
            raise ValueError("hardware-effect ranker feature contract mismatch")
        self.network.load_state_dict(payload["state_dict"])
        self.mean = payload["mean"].to(self.device)
        self.scale = payload["scale"].to(self.device)
