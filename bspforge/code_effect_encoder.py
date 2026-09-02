from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np

from bspforge.capability_schema import CAPABILITY_SCHEMA
from bspforge.hardware_effect_graph import SourceCorpus


MODEL_ID = "jinaai/jina-embeddings-v2-base-code"
MODEL_REVISION = "516f4baf13dec4ddddda8631e019b5737c8bc250"
MODEL_CODE_REVISION = "3baf9e3ac750e76e8edd3019170176884695fb94"

CAPABILITY_DESCRIPTIONS = {
    "clock": "clock tree oscillator pll frequency and peripheral clock gate",
    "interrupt": "interrupt controller irq vector handler mask and priority",
    "uart": "UART serial port transmit receive baud format and data fifo",
    "gpio": "GPIO pin direction level pull mode and external interrupt",
    "timer": "hardware timer counter period compare reload start and stop",
}

OPERATION_DESCRIPTIONS = {
    "initialize": "initialize hardware state and establish required configuration",
    "configure": "configure operating parameters and mode",
    "enable": "enable or unmask the requested hardware resource",
    "disable": "disable or mask the requested hardware resource",
    "get_frequency": "read the effective clock frequency in hertz",
    "register": "register an interrupt callback or vector handler",
    "write": "write or transmit payload data to the peripheral",
    "read": "read or receive payload data from the peripheral",
    "attach_irq": "configure and attach a GPIO interrupt callback",
    "start": "start or resume hardware timer counting",
    "stop": "stop or pause hardware timer counting",
    "set_interval": "set timer period timeout compare or reload value",
}

COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
CHAR_RE = re.compile(r"'(?:\\.|[^'\\])*'")
HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
SPACE_RE = re.compile(r"\s+")


def operation_query_text(operation_id: str) -> str:
    capability, operation = operation_id.split(".", 1)
    aliases = " ".join(CAPABILITY_SCHEMA[capability]["operations"][operation])
    return (
        f"embedded SDK operation: {operation_id}. "
        f"hardware capability: {CAPABILITY_DESCRIPTIONS[capability]}. "
        f"required effect: {OPERATION_DESCRIPTIONS[operation]}. "
        f"action aliases: {aliases}. "
        "Prefer a stable public C or C++ SDK API that directly performs this effect; "
        "avoid examples, status queries, opposite actions, middleware, and unrelated peripherals."
    )


def normalize_code(body: str, *, max_characters: int = 2200) -> str:
    body = COMMENT_RE.sub(" ", body)
    body = STRING_RE.sub('"STRING_LITERAL"', body)
    body = CHAR_RE.sub("'CHAR_LITERAL'", body)
    body = HEX_RE.sub("HEX_LITERAL", body)
    body = NUMBER_RE.sub("INT_LITERAL", body)
    body = SPACE_RE.sub(" ", body).strip()
    return body[:max_characters]


def candidate_document(
    candidate: dict[str, Any], function: dict[str, Any], corpus: SourceCorpus
) -> str:
    body = normalize_code(corpus.function_body(function))
    evidence = candidate.get("hardware_effect_evidence", {})
    registers = " ".join(evidence.get("register_hits", []))
    calls = " ".join(function.get("calls", [])[:40])
    includes = " ".join(function.get("includes", [])[:24])
    return (
        f"SDK callable. symbol: {candidate['symbol']}. "
        f"signature: {function.get('signature', '')}. "
        f"source file: {function.get('file', candidate.get('file', ''))}. "
        f"source role: {candidate.get('source_role', '')}. "
        f"calls: {calls}. includes: {includes}. "
        f"register identifiers: {registers}. normalized function body: {body}"
    )


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FrozenCodeEncoder:
    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cpu",
        max_length: int = 256,
        threads: int = 8,
    ) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(max(1, threads))
        self.torch = torch
        self.device = device
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModel.from_pretrained(
            model_path,
            trust_remote_code=True,
            code_revision=MODEL_CODE_REVISION,
        ).to(device)
        self.model.eval()
        self.dimension = int(self.model.config.hidden_size)

    def encode(self, texts: list[str], *, batch_size: int = 16) -> np.ndarray:
        vectors = []
        with self.torch.no_grad():
            for start in range(0, len(texts), batch_size):
                encoded = self.tokenizer(
                    texts[start : start + batch_size],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                output = self.model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(output.dtype)
                pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
                pooled = self.torch.nn.functional.normalize(pooled, dim=-1)
                vectors.append(pooled.cpu().numpy())
        return np.concatenate(vectors, axis=0).astype(np.float32)


class CodeEmbeddingCache:
    def __init__(self, metadata_path: Path, vectors_path: Path) -> None:
        from bspforge.common import read_json

        metadata = read_json(metadata_path)
        archive = np.load(vectors_path)
        self.metadata = metadata
        self.document_keys = metadata["document_keys"]
        self.operation_ids = metadata["operation_ids"]
        self.document_index = {key: index for index, key in enumerate(self.document_keys)}
        self.operation_index = {key: index for index, key in enumerate(self.operation_ids)}
        self.documents = archive["documents"].astype(np.float32)
        self.queries = archive["queries"].astype(np.float32)
        if self.documents.shape[0] != len(self.document_keys):
            raise ValueError("code embedding document index mismatch")
        if self.queries.shape[0] != len(self.operation_ids):
            raise ValueError("code embedding query index mismatch")

    @staticmethod
    def candidate_key(candidate: dict[str, Any], sdk_id: str) -> str:
        return f"{sdk_id}::{candidate['entity_id']}"

    def document_vectors(self, group: dict[str, Any]) -> np.ndarray:
        return np.stack([
            self.documents[self.document_index[self.candidate_key(candidate, group["sdk_id"])]]
            for candidate in group["candidates"]
        ])

    def query_vector(self, operation_id: str) -> np.ndarray:
        return self.queries[self.operation_index[operation_id]]
