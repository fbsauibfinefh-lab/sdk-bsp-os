from __future__ import annotations

from statistics import mean
from typing import Any

from bspforge.common import utc_now
from bspforge.semantic_resolver import SemanticResolver
from bspforge.semantic_resolver.resolver import DEFAULT_EVIDENCE_WEIGHTS


class ExperimentEvaluator:
    """Compute reproducible semantic, binding, and device-model metrics."""

    def evaluate(
        self,
        resolution: dict[str, Any],
        bindings: dict[str, Any],
        devices: dict[str, Any],
        ground_truth: dict[str, Any],
    ) -> dict[str, Any]:
        semantic = self.evaluate_resolution(resolution, ground_truth)
        binding_index = {
            item["capability"]: {symbol["symbol"] for symbol in item["sdk_symbols"]}
            for item in bindings.get("bindings", [])
        }
        class_to_capability = {"serial": "uart", "pin": "gpio", "hwtimer": "timer"}
        operation_index: dict[str, set[str]] = {}
        for item in devices.get("devices", []):
            capability = class_to_capability.get(item["class"])
            if capability:
                operation_index.setdefault(capability, set()).update(item["operations"])

        per_capability: dict[str, Any] = {}
        for capability, truth in ground_truth["capabilities"].items():
            binding_metrics = self._set_metrics(
                binding_index.get(capability, set()),
                set(truth.get("binding_symbols", [])),
            )
            device_metrics = self._set_metrics(
                operation_index.get(capability, set()),
                set(truth.get("device_operations", [])),
            )
            per_capability[capability] = {
                "binding": binding_metrics,
                "device_model": device_metrics,
            }

        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "ground_truth_id": ground_truth.get("id", "unknown"),
            "semantic_resolution": semantic,
            "per_capability": per_capability,
            "summary": {
                "semantic_macro_precision": semantic["summary"]["macro_precision"],
                "semantic_macro_recall": semantic["summary"]["macro_recall"],
                "semantic_macro_f1": semantic["summary"]["macro_f1"],
                "semantic_mrr": semantic["summary"]["mrr"],
                "binding_macro_recall": self._macro(per_capability, "binding", "recall"),
                "device_operation_macro_recall": self._macro(
                    per_capability, "device_model", "recall"
                ),
            },
        }

    def evaluate_resolution(
        self,
        resolution: dict[str, Any],
        ground_truth: dict[str, Any],
    ) -> dict[str, Any]:
        mapping_index = {item["capability"]: item for item in resolution["mappings"]}
        per_capability: dict[str, Any] = {}
        reciprocal_ranks: list[float] = []
        for capability, truth in ground_truth["capabilities"].items():
            relevant = set(truth.get("semantic_symbols", truth.get("binding_symbols", [])))
            mapping = mapping_index.get(capability, {"accepted": [], "candidates": []})
            accepted = {item["symbol"] for item in mapping["accepted"]}
            ranked = [item["symbol"] for item in mapping["candidates"]]
            metrics = self._set_metrics(accepted, relevant)
            ranks = [index + 1 for index, symbol in enumerate(ranked) if symbol in relevant]
            reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0
            reciprocal_ranks.append(reciprocal_rank)
            metrics.update({
                "relevant": sorted(relevant),
                "accepted": sorted(accepted),
                "ranked_candidates": ranked,
                "recall_at_k": self._ratio(len(relevant.intersection(ranked)), len(relevant)),
                "reciprocal_rank": round(reciprocal_rank, 4),
            })
            per_capability[capability] = metrics
        return {
            "per_capability": per_capability,
            "summary": {
                "macro_precision": self._flat_macro(per_capability, "precision"),
                "macro_recall": self._flat_macro(per_capability, "recall"),
                "macro_f1": self._flat_macro(per_capability, "f1"),
                "macro_recall_at_k": self._flat_macro(per_capability, "recall_at_k"),
                "mrr": round(mean(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
            },
        }

    def ablate(
        self,
        ir: dict[str, Any],
        ground_truth: dict[str, Any],
        threshold: float,
        top_k: int,
    ) -> dict[str, Any]:
        capabilities = list(ground_truth["capabilities"])
        experiments: list[dict[str, Any]] = []
        variants: list[tuple[str, dict[str, float]]] = [("baseline", {})]
        variants.extend(
            (f"without-{kind}", {kind: 0.0}) for kind in DEFAULT_EVIDENCE_WEIGHTS
        )
        for name, weights in variants:
            resolution = SemanticResolver().resolve(
                ir,
                capability_names=capabilities,
                threshold=threshold,
                top_k=top_k,
                evidence_weights=weights,
            )
            metrics = self.evaluate_resolution(resolution, ground_truth)
            experiments.append({
                "name": name,
                "disabled_evidence": name.removeprefix("without-") if name != "baseline" else None,
                "weights": resolution["evidence_weights"],
                "metrics": metrics["summary"],
            })
        baseline = experiments[0]["metrics"]
        for experiment in experiments:
            experiment["delta_macro_f1"] = round(
                experiment["metrics"]["macro_f1"] - baseline["macro_f1"], 4
            )
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "ground_truth_id": ground_truth.get("id", "unknown"),
            "threshold": threshold,
            "top_k": top_k,
            "experiments": experiments,
        }

    @classmethod
    def _set_metrics(cls, predicted: set[str], relevant: set[str]) -> dict[str, Any]:
        true_positive = len(predicted.intersection(relevant))
        precision = cls._ratio(true_positive, len(predicted))
        recall = cls._ratio(true_positive, len(relevant))
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        return {
            "true_positive": true_positive,
            "predicted": len(predicted),
            "relevant": len(relevant),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "false_positive": sorted(predicted.difference(relevant)),
            "false_negative": sorted(relevant.difference(predicted)),
        }

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 1.0

    @staticmethod
    def _flat_macro(values: dict[str, Any], metric: str) -> float:
        return round(mean(item[metric] for item in values.values()), 4) if values else 0.0

    @staticmethod
    def _macro(values: dict[str, Any], section: str, metric: str) -> float:
        return round(mean(item[section][metric] for item in values.values()), 4) if values else 0.0
