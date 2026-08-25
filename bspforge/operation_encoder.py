from __future__ import annotations

from typing import Any


IR_OPERATION_QUERY_FORMAT = "ir-operation-v1"


def operation_encoder_query(group: dict[str, Any], query_format: str) -> str:
    if query_format == "raw":
        return group["query_text"]
    if query_format != IR_OPERATION_QUERY_FORMAT:
        raise ValueError(f"unknown operation query format: {query_format}")
    return (
        "SDK migration operation\n"
        f"capability: {group['capability']}\n"
        f"operation: {group['operation']}\n"
        f"contract: {group['query_text']}"
    )


class OperationEncoder:
    """Lazy sentence-transformer wrapper for operation-to-IR scoring."""

    def __init__(
        self,
        model_name_or_path: str,
        *,
        device: str = "cpu",
        revision: str | None = None,
        query_format: str = IR_OPERATION_QUERY_FORMAT,
        batch_size: int = 64,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "operation encoder requires the 'retrieval' optional dependency"
            ) from error
        self.model = SentenceTransformer(
            model_name_or_path,
            revision=revision,
            device=device,
        )
        self.model.max_seq_length = 128
        self.query_format = query_format
        self.batch_size = batch_size

    def scores(self, group: dict[str, Any]) -> list[float]:
        import numpy as np

        query = operation_encoder_query(group, self.query_format)
        documents = [item["candidate_text"] for item in group["candidates"]]
        query_vector = self.model.encode(
            [query],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        document_vectors = self.model.encode(
            documents,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [round((float(np.dot(query_vector, item)) + 1.0) / 2.0, 6) for item in document_vectors]
