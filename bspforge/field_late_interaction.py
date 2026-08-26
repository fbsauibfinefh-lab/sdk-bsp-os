from __future__ import annotations

from time import perf_counter
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.operation_ranking import CAPABILITY_TERMS, SIGNATURE_HINTS, operation_query_text


FIELD_WEIGHTS = {
    "symbol": 0.34,
    "signature": 0.28,
    "calls": 0.18,
    "file": 0.12,
    "includes": 0.08,
}


def candidate_fields(candidate_text: str) -> dict[str, str]:
    fields = {name: "" for name in FIELD_WEIGHTS}
    for line in candidate_text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name in fields:
            fields[name] = value.strip()
    return fields


def operation_late_queries(group: dict[str, Any]) -> dict[str, str]:
    capability = group["capability"]
    operation = group["operation"]
    aliases = CAPABILITY_SCHEMA[capability]["operations"][operation]
    hints = SIGNATURE_HINTS.get(operation, ())
    capability_text = " ".join([capability, *CAPABILITY_TERMS[capability]])
    action_text = " ".join([operation.replace("_", " "), *aliases])
    contract = operation_query_text(capability, operation)
    return {
        # Symbol names are terse; repeating the capability block prevents generic
        # verbs such as init/get/set from dominating token MaxSim.
        "symbol": f"{capability_text} {capability_text} {action_text}",
        "signature": f"{capability_text} {action_text} {contract} {' '.join(hints)}",
        "calls": f"{capability_text} {action_text} {action_text}",
        "file": f"{capability_text} driver hal peripheral",
        "includes": f"{capability_text} driver hal header",
    }


def operation_late_query(group: dict[str, Any]) -> str:
    """Compatibility representation used in reports and cache keys."""
    return "\n".join(
        f"{field}: {value}" for field, value in operation_late_queries(group).items()
    )


class FieldLateInteractionScorer:
    """Token-level MaxSim over independently weighted SDK IR fields."""

    def __init__(
        self,
        model_name_or_path: str,
        *,
        revision: str | None = None,
        device: str = "cpu",
        batch_size: int = 128,
        max_query_length: int = 48,
        max_field_length: int = 64,
        field_weights: dict[str, float] | None = None,
        model: Any | None = None,
    ) -> None:
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "field late interaction requires the 'retrieval' optional dependency"
            ) from error
        self.torch = torch
        self.device = device
        self.batch_size = batch_size
        self.max_query_length = max_query_length
        self.max_field_length = max_field_length
        self.model = model or SentenceTransformer(
            model_name_or_path, revision=revision, device=device
        )
        self.transformer = self.model[0]
        self.special_ids = set(self.model.tokenizer.all_special_ids)
        self.weights = {**FIELD_WEIGHTS, **(field_weights or {})}
        if set(self.weights) != set(FIELD_WEIGHTS):
            raise ValueError("field weights must use the documented IR fields")
        if any(value < 0 for value in self.weights.values()):
            raise ValueError("field weights must be non-negative")
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("field weights must have positive sum")
        self.weights = {name: value / total for name, value in self.weights.items()}

    def _token_vectors(self, texts: list[str], max_length: int) -> tuple[Any, Any]:
        torch = self.torch
        features = self.model.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        features = {name: value.to(self.device) for name, value in features.items()}
        with torch.no_grad():
            output = self.transformer(features)
            vectors = torch.nn.functional.normalize(output["token_embeddings"], dim=-1)
        mask = features["attention_mask"].bool()
        for special_id in self.special_ids:
            mask &= features["input_ids"] != special_id
        return vectors, mask

    def score_groups(self, groups: list[dict[str, Any]]) -> dict[str, Any]:
        torch = self.torch
        started = perf_counter()
        query_keys = sorted({operation_late_query(group) for group in groups})
        query_index = {text: index for index, text in enumerate(query_keys)}
        parsed = {
            candidate["candidate_text"]: candidate_fields(candidate["candidate_text"])
            for group in groups
            for candidate in group["candidates"]
        }
        field_scores: dict[str, dict[str, list[float]]] = {}
        field_value_counts = {}
        for field in FIELD_WEIGHTS:
            field_queries = [
                operation_late_queries(
                    next(group for group in groups if operation_late_query(group) == key)
                )[field]
                for key in query_keys
            ]
            query_vectors, query_masks = self._token_vectors(
                field_queries, self.max_query_length
            )
            values = sorted({item[field] for item in parsed.values() if item[field]})
            field_value_counts[field] = len(values)
            scores_by_value: dict[str, list[float]] = {}
            for offset in range(0, len(values), self.batch_size):
                batch = values[offset:offset + self.batch_size]
                document_vectors, document_masks = self._token_vectors(
                    batch, self.max_field_length
                )
                similarities = torch.einsum(
                    "qld,bmd->qblm", query_vectors, document_vectors
                )
                similarities = similarities.masked_fill(
                    ~document_masks[None, :, None, :], -1.0
                )
                maxima = similarities.max(dim=-1).values
                maxima = maxima.masked_fill(~query_masks[:, None, :], 0.0)
                denominators = query_masks.sum(dim=-1).clamp_min(1)[:, None]
                batch_scores = (maxima.sum(dim=-1) / denominators).cpu()
                for index, value in enumerate(batch):
                    scores_by_value[value] = [
                        float(item) for item in batch_scores[:, index]
                    ]
            field_scores[field] = scores_by_value
        pairs = 0
        for group in groups:
            query = operation_late_query(group)
            qid = query_index[query]
            for candidate in group["candidates"]:
                fields = parsed[candidate["candidate_text"]]
                available = {
                    field: self.weights[field]
                    for field, value in fields.items()
                    if value and value in field_scores[field]
                }
                total = sum(available.values()) or 1.0
                for field in FIELD_WEIGHTS:
                    field_value = (
                        field_scores[field][fields[field]][qid]
                        if fields[field] and fields[field] in field_scores[field]
                        else -1.0
                    )
                    candidate["features"][f"field-{field}-maxsim"] = round(
                        (field_value + 1.0) / 2.0, 6
                    )
                raw = sum(
                    weight * field_scores[field][fields[field]][qid]
                    for field, weight in available.items()
                ) / total
                candidate["features"]["field-late-interaction"] = round(
                    (raw + 1.0) / 2.0, 6
                )
                pairs += 1
        return {
            "queries": len(query_keys),
            "candidate_documents": len(parsed),
            "field_value_counts": field_value_counts,
            "pairs": pairs,
            "field_weights": self.weights,
            "max_query_length": self.max_query_length,
            "max_field_length": self.max_field_length,
            "seconds": round(perf_counter() - started, 3),
        }
