from __future__ import annotations

import copy
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from bspforge.common import stable_id, utc_now


class ClosureSolver:
    """Compute a typed build closure from accepted semantic entities."""

    def solve(self, ir: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
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

        # Startup and linker assets are indivisible target contracts for firmware.
        for entity_id, item in file_index.items():
            if item["kind"] in {"startup", "linker"}:
                selected.add(entity_id)
                selected_files.add(entity_id)
                provenance.append({"entity_id": entity_id, "reason": "firmware-contract-asset"})

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
            "schema_version": "1.0",
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
            "unresolved_capabilities": unresolved,
            "summary": {
                "seed_functions": len(seeds),
                "files": len(files),
                "build_rules": len(builds),
                "startup_assets": sum(item["kind"] == "startup" for item in files),
                "linker_assets": sum(item["kind"] == "linker" for item in files),
            },
        }

    def apply_repairs(
        self,
        ir: dict[str, Any],
        closure: dict[str, Any],
        repair_proposal: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], bool]:
        """Apply additive, evidence-backed build constraints to a closure."""
        updated = copy.deepcopy(closure)
        file_index = {item["id"]: item for item in ir["files"]}
        file_by_path = {item["path"]: item for item in ir["files"]}
        selected = {item["path"] for item in updated["selected_files"]}
        repair_sources = set(updated.get("repair_sources", []))
        include_dirs = set(updated.get("repair_include_dirs", []))
        applied: list[dict[str, Any]] = []

        for repair in repair_proposal["repairs"]:
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

        changed = bool(applied)
        updated["repair_sources"] = sorted(repair_sources)
        updated["repair_include_dirs"] = sorted(include_dirs)
        updated.setdefault("repair_history", []).append({
            "iteration": iteration,
            "applied": applied,
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
