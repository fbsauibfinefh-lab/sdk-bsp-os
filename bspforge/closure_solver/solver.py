from __future__ import annotations

import copy
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from bspforge.common import stable_id, utc_now


class ClosureSolver:
    """Compute a typed build closure from accepted semantic entities."""

    def solve(
        self,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        target_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for edge in ir["edges"]:
            adjacency[edge["from"]].append((edge["to"], edge["type"]))

        function_index = {item["id"]: item for item in ir["functions"]}
        file_index = {item["id"]: item for item in ir["files"]}
        build_index = {item["id"]: item for item in ir["build_rules"]}
        definition_file = {
            edge["to"]: edge["from"] for edge in ir["edges"] if edge["type"] == "defines"
        }
        reverse_build: dict[str, list[str]] = defaultdict(list)
        for edge in ir["edges"]:
            if edge["type"] == "builds":
                reverse_build[edge["to"]].append(edge["from"])

        seeds = sorted({
            candidate["entity_id"]
            for mapping in resolution["mappings"]
            for candidate in mapping["accepted"]
        })
        queue = deque((seed, "semantic-seed") for seed in seeds)
        selected: set[str] = set()
        provenance: list[dict[str, str]] = []
        while queue:
            entity_id, reason = queue.popleft()
            if entity_id in selected:
                continue
            selected.add(entity_id)
            provenance.append({"entity_id": entity_id, "reason": reason})
            if entity_id in function_index and entity_id in definition_file:
                queue.append((definition_file[entity_id], "definition-file"))
            for target, edge_type in adjacency.get(entity_id, []):
                if edge_type in {"calls", "includes"}:
                    queue.append((target, edge_type))
            if entity_id in file_index:
                for build_id in reverse_build.get(entity_id, []):
                    queue.append((build_id, "declared-by-build-rule"))

        selected_files = {entity_id for entity_id in selected if entity_id in file_index}
        selected_paths = {file_index[item]["path"] for item in selected_files}
        stems = {Path(path).stem for path in selected_paths}
        for entity_id, item in file_index.items():
            path = Path(item["path"])
            if item["kind"] == "header" and path.stem in stems:
                selected.add(entity_id)
                selected_files.add(entity_id)
                provenance.append({"entity_id": entity_id, "reason": "matching-public-header"})

        asset_decisions = self._select_firmware_assets(
            file_index,
            build_index,
            adjacency,
            selected,
            target_context or {},
        )
        for decision in asset_decisions:
            if decision["selected"]:
                entity_id = decision["entity_id"]
                item = file_index[entity_id]
                selected.add(entity_id)
                selected_files.add(entity_id)
                provenance.append({
                    "entity_id": entity_id,
                    "reason": decision["reason"],
                })

        # Build files on a selected asset's directory ancestry define how that
        # asset enters the native build, even when CMake/SCons uses globbing.
        selected_paths = [Path(file_index[item]["path"]) for item in selected_files]
        for build_id, build in build_index.items():
            build_path = Path(build["path"])
            parent = build_path.parent
            on_ancestry = any(parent == Path(".") or parent in source.parents for source in selected_paths)
            global_rule = build_path.name in {
                "toolchain.cmake",
                "compile-flags.cmake",
                "common.cmake",
                "executable.cmake",
            }
            if on_ancestry or global_rule:
                selected.add(build_id)
                provenance.append({
                    "entity_id": build_id,
                    "reason": "build-directory-ancestry" if on_ancestry else "global-build-contract",
                })

        files = [file_index[item] for item in selected_files]
        builds = [build_index[item] for item in selected if item in build_index]
        unresolved = [item["capability"] for item in resolution["mappings"] if item["status"] != "resolved"]
        return {
            "schema_version": "1.1",
            "created_at": utc_now(),
            "id": stable_id(ir["sdk"]["id"], ir["sdk"]["digest"], "closure"),
            "sdk_id": ir["sdk"]["id"],
            "sdk_root": ir["sdk"]["root"],
            "selected_files": sorted(files, key=lambda item: item["path"]),
            "selected_build_rules": sorted(builds, key=lambda item: item["path"]),
            "seed_entities": seeds,
            "provenance": provenance,
            "repair_sources": [],
            "repair_include_dirs": [],
            "repair_history": [],
            "target_context": target_context or {},
            "firmware_asset_decisions": asset_decisions,
            "unresolved_capabilities": unresolved,
            "summary": {
                "seed_functions": len(seeds),
                "files": len(files),
                "build_rules": len(builds),
                "startup_assets": sum(item["kind"] == "startup" for item in files),
                "linker_assets": sum(item["kind"] == "linker" for item in files),
            },
        }

    @classmethod
    def _select_firmware_assets(
        cls,
        file_index: dict[str, dict[str, Any]],
        build_index: dict[str, dict[str, Any]],
        adjacency: dict[str, list[tuple[str, str]]],
        selected: set[str],
        target: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates = [
            (entity_id, item)
            for entity_id, item in file_index.items()
            if item["kind"] in {"startup", "linker"}
        ]
        policies = {
            "startup": target.get("startup_policy", "select"),
            "linker": target.get("linker_policy", "select"),
        }
        directly_referenced: set[str] = set()
        for build_id in selected.intersection(build_index):
            directly_referenced.update(
                target_id
                for target_id, edge_type in adjacency.get(build_id, [])
                if edge_type == "builds" and target_id in file_index
            )
        if not target:
            return [
                {
                    "entity_id": entity_id,
                    "path": item["path"],
                    "kind": item["kind"],
                    "selected": True,
                    "score": 0,
                    "reason": "firmware-contract-fallback-no-target-context",
                    "evidence": [],
                }
                for entity_id, item in candidates
            ]

        positive = cls._target_tokens(target)
        architecture = str(target.get("architecture", "")).lower()
        conflict_tokens = cls._conflict_tokens(architecture)
        scored: list[dict[str, Any]] = []
        for entity_id, item in candidates:
            path = item["path"].lower()
            metadata = item.get("asset_metadata", {})
            evidence: list[str] = []
            score = 0
            if entity_id in directly_referenced:
                score += 100
                evidence.append("selected-build-rule-reference")
            matches = sorted(token for token in positive if token and token in path)
            score += 10 * len(matches)
            evidence.extend(f"target-token:{token}" for token in matches)
            conflicts = sorted(token for token in conflict_tokens if token in path)
            metadata_architectures = set(metadata.get("architectures", []))
            if architecture:
                expected_architecture = "riscv" if "riscv" in architecture else "arm"
                if expected_architecture in metadata_architectures:
                    score += 30
                    evidence.append(f"metadata-architecture:{expected_architecture}")
                elif metadata_architectures:
                    conflicts.extend(sorted(metadata_architectures))
            expected_core = str(target.get("core", "")).lower()
            metadata_cores = set(metadata.get("cores", []))
            if expected_core and expected_core in metadata_cores:
                score += 30
                evidence.append(f"metadata-core:{expected_core}")
            requested_entries = set(target.get("entry_symbols", []))
            entry_matches = requested_entries.intersection(metadata.get("entry_symbols", []))
            if entry_matches:
                score += 20
                evidence.extend(f"entry-symbol:{item}" for item in sorted(entry_matches))
            if conflicts:
                score -= 100
                evidence.extend(f"architecture-conflict:{token}" for token in conflicts)
            scored.append({
                "entity_id": entity_id,
                "path": item["path"],
                "kind": item["kind"],
                "score": score,
                "evidence": evidence,
            })

        for kind in {"startup", "linker"}:
            if policies[kind] == "backend":
                for item in scored:
                    if item["kind"] == kind:
                        item["selected"] = False
                        item["reason"] = "replaced-by-os-backend"
                        item["evidence"].append("target-policy:backend")
                continue
            group = [item for item in scored if item["kind"] == kind and item["score"] > -100]
            if not group:
                continue
            best = max(item["score"] for item in group)
            for item in group:
                item["selected"] = item["score"] == best
                item["reason"] = (
                    "target-compatible-firmware-asset"
                    if item["selected"]
                    else "lower-ranked-firmware-asset"
                )
        for item in scored:
            if "selected" not in item:
                item["selected"] = False
                item["reason"] = "architecture-conflict"
        return sorted(scored, key=lambda item: (item["kind"], item["path"]))

    @staticmethod
    def _target_tokens(target: dict[str, Any]) -> set[str]:
        values: list[str] = []
        for key in ("architecture", "chip", "core", "board", "sdk_profile", "toolchain"):
            value = target.get(key)
            if value:
                values.extend(str(value).lower().replace("-", "_").split("_"))
                values.append(str(value).lower())
        aliases = {
            "riscv64": {"riscv", "rv64"},
            "riscv32": {"riscv", "rv32"},
            "arm": {"arm", "cortex"},
            "cortex-m3": {"cm3", "cortex-m3", "cortex_m3"},
            "cortex-m33": {"cm33", "cortex-m33", "cortex_m33"},
        }
        for value in list(values):
            values.extend(aliases.get(value, set()))
        return {item for item in values if len(item) >= 3}

    @staticmethod
    def _conflict_tokens(architecture: str) -> set[str]:
        if "riscv" in architecture:
            return {"cortex", "cm0", "cm3", "cm4", "cm7", "arm"}
        if architecture == "arm" or "cortex" in architecture:
            return {"riscv", "rv32", "rv64"}
        return set()

    def apply_repairs(
        self,
        ir: dict[str, Any],
        closure: dict[str, Any],
        repair_proposal: dict[str, Any],
        iteration: int,
        maximum_risk: str = "low",
    ) -> tuple[dict[str, Any], bool]:
        """Apply additive, evidence-backed build constraints to a closure."""
        updated = copy.deepcopy(closure)
        file_index = {item["id"]: item for item in ir["files"]}
        file_by_path = {item["path"]: item for item in ir["files"]}
        selected = {item["path"] for item in updated["selected_files"]}
        repair_sources = set(updated.get("repair_sources", []))
        include_dirs = set(updated.get("repair_include_dirs", []))
        applied: list[dict[str, Any]] = []

        risk_order = {"low": 0, "medium": 1, "high": 2}
        rejected: list[dict[str, Any]] = []
        for repair in repair_proposal["repairs"]:
            risk = repair.get("risk", "low")
            if risk_order.get(risk, 99) > risk_order.get(maximum_risk, 0):
                rejected.append({**repair, "rejection_reason": "risk-policy"})
                continue
            action = repair["action"]
            if action == "add-source":
                path = repair["path"]
                if path not in repair_sources:
                    repair_sources.add(path)
                    applied.append(repair)
                item = file_by_path.get(path)
                if item and path not in selected:
                    updated["selected_files"].append(item)
                    selected.add(path)
                    updated["provenance"].append({
                        "entity_id": item["id"],
                        "reason": f"diagnostic-iteration-{iteration}:undefined-symbol",
                    })
                    stem = Path(path).stem
                    for header in ir["files"]:
                        if header["kind"] == "header" and Path(header["path"]).stem == stem and header["path"] not in selected:
                            updated["selected_files"].append(header)
                            selected.add(header["path"])
                            updated["provenance"].append({
                                "entity_id": header["id"],
                                "reason": f"diagnostic-iteration-{iteration}:provider-header",
                            })
            elif action == "add-include-dir" and repair["path"] not in include_dirs:
                include_dirs.add(repair["path"])
                applied.append(repair)
                entity = file_index.get(repair["entity_id"])
                if entity and entity["path"] not in selected:
                    updated["selected_files"].append(entity)
                    selected.add(entity["path"])
                    updated["provenance"].append({
                        "entity_id": entity["id"],
                        "reason": f"diagnostic-iteration-{iteration}:missing-header",
                    })
            elif action == "add-library":
                path = repair["path"]
                libraries = set(updated.get("repair_libraries", []))
                if path not in libraries:
                    libraries.add(path)
                    updated["repair_libraries"] = sorted(libraries)
                    applied.append(repair)
                item = file_by_path.get(path)
                if item and path not in selected:
                    updated["selected_files"].append(item)
                    selected.add(path)
                    updated["provenance"].append({
                        "entity_id": item["id"],
                        "reason": f"diagnostic-iteration-{iteration}:missing-library",
                    })

        changed = bool(applied)
        updated["repair_sources"] = sorted(repair_sources)
        updated["repair_include_dirs"] = sorted(include_dirs)
        updated.setdefault("repair_history", []).append({
            "iteration": iteration,
            "base_closure_id": closure["id"],
            "maximum_risk": maximum_risk,
            "applied": applied,
            "rejected": rejected,
            "rollback": "regenerate-from-base-closure-id",
        })
        updated["selected_files"] = sorted(updated["selected_files"], key=lambda item: item["path"])
        updated["summary"]["files"] = len(updated["selected_files"])
        updated["summary"]["diagnostic_repairs"] = sum(
            len(item["applied"]) for item in updated["repair_history"]
        )
        if changed:
            updated["id"] = stable_id(closure["id"], "repair", str(iteration), *(item["diagnostic_id"] for item in applied))
            updated["created_at"] = utc_now()
        return updated, changed
