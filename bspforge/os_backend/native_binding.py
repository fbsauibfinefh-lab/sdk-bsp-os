from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bspforge.common import utc_now
from bspforge.os_backend.profiles import sdk_profile


class NativeDriverBindingTracer:
    """Trace mature RTOS drivers back to function entities in the input SDK."""

    def generate(
        self,
        ir: dict[str, Any],
        profile_name: str,
        backend: str,
        driver_roots: list[Path],
        provider_roots: list[Path] | None = None,
    ) -> dict[str, Any]:
        profile = sdk_profile(profile_name)
        entities = {item["name"]: item for item in ir["functions"]}
        searchable = self._searchable_files(driver_roots)
        providers = self._searchable_files(provider_roots or [])
        bindings: list[dict[str, Any]] = []

        for capability, expected in profile["capabilities"].items():
            symbols: list[dict[str, Any]] = []
            for name in expected:
                entity = entities.get(name)
                if entity is None:
                    continue
                references = self._references(name, searchable)
                provider_references = self._references(name, providers)
                symbols.append({
                    "symbol": name,
                    "entity_id": entity["id"],
                    "signature": entity["signature"],
                    "source": entity["evidence"],
                    "driver_references": references,
                    "provider_references": provider_references,
                    "linked_by_native_driver": bool(references),
                    "present_in_native_provider": bool(provider_references),
                })
            bindings.append({
                "capability": capability,
                "strategy": "native-driver-trace",
                "sdk_symbols": symbols,
                "status": (
                    "resolved"
                    if any(item["linked_by_native_driver"] for item in symbols)
                    else "provider-only"
                    if any(item["present_in_native_provider"] for item in symbols)
                    else "evidence-only"
                ),
            })

        linked = sum(
            item["linked_by_native_driver"]
            for binding in bindings
            for item in binding["sdk_symbols"]
        )
        provider_symbols = sum(
            item["present_in_native_provider"]
            for binding in bindings
            for item in binding["sdk_symbols"]
        )
        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "backend": backend,
            "sdk_profile": profile_name,
            "strategy": "native-driver-trace",
            "bindings": bindings,
            "required_sources": [],
            "summary": {
                "capabilities": len(bindings),
                "resolved_capabilities": sum(item["status"] == "resolved" for item in bindings),
                "sdk_symbols": sum(len(item["sdk_symbols"]) for item in bindings),
                "driver_linked_symbols": linked,
                "provider_symbols": provider_symbols,
            },
        }

    @staticmethod
    def _searchable_files(roots: list[Path]) -> list[Path]:
        result: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            if root.is_file():
                if root.suffix.lower() in {".c", ".h", ".cc", ".cpp"}:
                    if root.stat().st_size <= 2 * 1024 * 1024:
                        result.append(root)
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".c", ".h", ".cc", ".cpp"}:
                    if path.stat().st_size <= 2 * 1024 * 1024:
                        result.append(path)
        return sorted(set(result))

    @staticmethod
    def _references(symbol: str, paths: list[Path]) -> list[dict[str, Any]]:
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        references: list[dict[str, Any]] = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    references.append({"path": str(path), "line": line_number})
                    break
        return references[:8]
