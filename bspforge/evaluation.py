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
        class_to_capability = {
            "serial": "uart",
            "uart": "uart",
            "pin": "gpio",
            "gpio": "gpio",
            "hwtimer": "timer",
            "counter": "timer",
            "clock_control": "clock",
        }
        expected_device_backend = ground_truth.get("device_model", {}).get("backend")
        observed_device_backend = devices.get("backend")
        device_contract_matches = (
            expected_device_backend is None
            or observed_device_backend is None
            or expected_device_backend == observed_device_backend
        )
        operation_index: dict[str, set[str]] = {}
        for item in devices.get("devices", []):
            capability = class_to_capability.get(item["class"])
            if capability:
                operation_index.setdefault(capability, set()).update(item["operations"])

        per_capability: dict[str, Any] = {}
        for capability, truth in ground_truth["capabilities"].items():
            supported = truth.get("supported", True)
            binding_metrics = self._set_metrics(
                binding_index.get(capability, set()),
                set(truth.get("binding_symbols", [])),
                applicable=supported,
            )
            device_metrics = self._set_metrics(
                operation_index.get(capability, set()),
                set(truth.get("device_operations", [])),
                applicable=supported and device_contract_matches,
            )
            per_capability[capability] = {
                "supported_by_sdk": supported,
                "binding": binding_metrics,
                "device_model": device_metrics,
            }

        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "ground_truth_id": ground_truth.get("id", "unknown"),
            "device_model_contract": {
                "expected_backend": expected_device_backend,
                "observed_backend": observed_device_backend,
                "matches": device_contract_matches,
            },
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
                "unsupported_capability_claims": sum(
                    not item["supported_by_sdk"]
                    and (
                        item["binding"]["predicted"] > 0
                        or item["device_model"]["predicted"] > 0
                    )
                    for item in per_capability.values()
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
            supported = truth.get("supported", True)
            relevant = set(truth.get("semantic_symbols", truth.get("binding_symbols", [])))
            mapping = mapping_index.get(capability, {"accepted": [], "candidates": []})
            accepted = {item["symbol"] for item in mapping["accepted"]}
            ranked = [item["symbol"] for item in mapping["candidates"]]
            metrics = self._set_metrics(accepted, relevant, applicable=supported)
            ranks = [index + 1 for index, symbol in enumerate(ranked) if symbol in relevant]
            reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0
            if supported and relevant:
                reciprocal_ranks.append(reciprocal_rank)
            metrics.update({
                "relevant": sorted(relevant),
                "accepted": sorted(accepted),
                "ranked_candidates": ranked,
                "recall_at_k": (
                    self._ratio(len(relevant.intersection(ranked)), len(relevant))
                    if supported
                    else None
                ),
                "reciprocal_rank": round(reciprocal_rank, 4) if supported and relevant else None,
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
            current = experiment["metrics"]["macro_f1"]
            base = baseline["macro_f1"]
            experiment["delta_macro_f1"] = (
                round(current - base, 4) if current is not None and base is not None else None
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
    def _set_metrics(
        cls,
        predicted: set[str],
        relevant: set[str],
        applicable: bool = True,
    ) -> dict[str, Any]:
        true_positive = len(predicted.intersection(relevant))
        if not applicable or not relevant:
            return {
                "applicable": False,
                "true_positive": true_positive,
                "predicted": len(predicted),
                "relevant": len(relevant),
                "precision": 0.0 if predicted else None,
                "recall": None,
                "f1": None,
                "unsupported_claim": bool(predicted) and not applicable,
                "false_positive": sorted(predicted.difference(relevant)),
                "false_negative": [],
            }
        precision = cls._ratio(true_positive, len(predicted)) if predicted else 0.0
        recall = cls._ratio(true_positive, len(relevant))
        assert precision is not None and recall is not None
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        return {
            "applicable": True,
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
    def _ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    @staticmethod
    def _flat_macro(values: dict[str, Any], metric: str) -> float | None:
        applicable = [item[metric] for item in values.values() if item.get(metric) is not None]
        return round(mean(applicable), 4) if applicable else None

    @staticmethod
    def _macro(values: dict[str, Any], section: str, metric: str) -> float | None:
        applicable = [
            item[section][metric]
            for item in values.values()
            if item[section].get(metric) is not None
        ]
        return round(mean(applicable), 4) if applicable else None
