from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from bspforge.common import read_json, write_json


class IRStore:
    """Versioned JSON store with small evidence-oriented query helpers."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, sdk_ir: dict[str, Any]) -> Path:
        sdk_id = sdk_ir["sdk"]["id"]
        digest = sdk_ir["sdk"]["digest"]
        destination = self.root / sdk_id / digest / "sdk-ir.json"
        write_json(destination, sdk_ir)
        write_json(self.root / sdk_id / "latest.json", {"digest": digest, "path": str(destination)})
        return destination

    def get(self, sdk_id: str, digest: str | None = None) -> dict[str, Any]:
        if digest is None:
            pointer = read_json(self.root / sdk_id / "latest.json")
            digest = pointer["digest"]
        return read_json(self.root / sdk_id / digest / "sdk-ir.json")

    @staticmethod
    def entities(ir: dict[str, Any], ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = set(ids)
        pools = (
            ir.get("files", []),
            ir.get("functions", []),
            ir.get("symbols", []),
            ir.get("build_rules", []),
        )
        return [item for pool in pools for item in pool if item["id"] in wanted]

    @staticmethod
    def evidence(ir: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
        matches = IRStore.entities(ir, [entity_id])
        return matches[0].get("evidence") if matches else None
