from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bspforge.common import stable_id, utc_now


PATTERNS = [
    ("missing-header", re.compile(r"fatal error: ([^:]+): No such file or directory"), "add include path or header to closure"),
    ("undefined-symbol", re.compile(r"undefined reference to [`']([^`']+)[`']"), "add defining source/library and its build rule"),
    ("multiple-definition", re.compile(r"multiple definition of [`']([^`']+)[`']"), "remove duplicate provider or select one implementation"),
    ("abi-mismatch", re.compile(r"(can't link double-float|can't link soft-float|ABI is incompatible)", re.I), "align -march/-mabi across objects and libraries"),
    ("region-overflow", re.compile(r"region [`']([^`']+)[`'] overflowed by (\d+) bytes"), "revise memory placement or reduce selected closure"),
    ("missing-library", re.compile(r"cannot find -l([^\s:]+)"), "add the archive/library and its search path to the closure"),
    ("compile-error", re.compile(r"([^:\n]+):(\d+)(?::\d+)?: error: (.+)"), "inspect source/configuration evidence at the reported location"),
]

WARNING_CATEGORIES = [
    ("implicit-declaration", re.compile(r"implicit declaration", re.I)),
    ("incompatible-pointer", re.compile(r"incompatible pointer|pointer type", re.I)),
    ("multichar-literal", re.compile(r"multi-character character constant", re.I)),
    ("unused", re.compile(r"unused (?:variable|function|parameter)", re.I)),
    ("conversion", re.compile(r"conversion|changes value|different size", re.I)),
]


class BuildDiagnoser:
    """Map raw GCC/binutils diagnostics to feedback constraints."""

    def diagnose(self, output: str, returncode: int) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for line in output.splitlines():
            for category, pattern, repair in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                subject = match.group(1) if match.groups() else line.strip()
                key = (category, subject)
                if key in seen:
                    break
                seen.add(key)
                diagnostics.append({
                    "id": stable_id(category, subject, line),
                    "category": category,
                    "subject": subject,
                    "message": line.strip(),
                    "constraint": repair,
                })
                break
        if returncode and not diagnostics:
            diagnostics.append({
                "id": stable_id("unknown-build-failure", str(returncode), output[-500:]),
                "category": "unknown-build-failure",
                "subject": f"exit-{returncode}",
                "message": output.splitlines()[-1] if output.splitlines() else "build failed",
                "constraint": "retain full log and add a target-specific diagnostic pattern",
            })
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "returncode": returncode,
            "success": returncode == 0,
            "diagnostics": diagnostics,
            "summary": {"count": len(diagnostics), "categories": sorted({item["category"] for item in diagnostics})},
        }

    def propose_repairs(
        self,
        ir: dict[str, Any],
        diagnosis: dict[str, Any],
        closure: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve actionable diagnostics back to SDK IR entities."""
        selected_paths = {item["path"] for item in closure["selected_files"]}
        files_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in ir["files"]:
            files_by_name.setdefault(Path(item["path"]).name, []).append(item)
        functions_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in ir["functions"]:
            functions_by_name.setdefault(item["name"], []).append(item)
        symbols_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in ir.get("symbols", []):
            symbols_by_name.setdefault(item["name"], []).append(item)

        repairs: list[dict[str, Any]] = []
        unresolved: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for diagnostic in diagnosis["diagnostics"]:
            category = diagnostic["category"]
            subject = diagnostic["subject"].strip()
            if category == "missing-header":
                matches = files_by_name.get(Path(subject).name, [])
                if not matches:
                    unresolved.append({"diagnostic_id": diagnostic["id"], "reason": "IR 中未找到头文件"})
                    continue
                header = min(matches, key=lambda item: len(Path(item["path"]).parts))
                include_dir = Path(header["path"]).parent.as_posix()
                key = ("add-include-dir", include_dir)
                if key not in seen:
                    seen.add(key)
                    repairs.append({
                        "action": "add-include-dir",
                        "path": include_dir,
                        "entity_id": header["id"],
                        "diagnostic_id": diagnostic["id"],
                        "reason": f"补充缺失头文件 {subject} 的包含目录",
                        "already_selected": header["path"] in selected_paths,
                    })
            elif category == "undefined-symbol":
                matches = functions_by_name.get(subject, []) or symbols_by_name.get(subject, [])
                if not matches and subject.startswith("_"):
                    normalized = subject.lstrip("_")
                    matches = functions_by_name.get(normalized, []) or symbols_by_name.get(normalized, [])
                if not matches:
                    unresolved.append({"diagnostic_id": diagnostic["id"], "reason": "IR 中未找到符号定义"})
                    continue
                provider = matches[0]
                key = ("add-source", provider["file"])
                if key not in seen:
                    seen.add(key)
                    repairs.append({
                        "action": "add-source",
                        "path": provider["file"],
                        "entity_id": provider["id"],
                        "symbol": provider["name"],
                        "provider_kind": provider.get("symbol_kind", "function"),
                        "diagnostic_id": diagnostic["id"],
                        "reason": f"加入未定义符号 {subject} 的实现文件",
                        "already_selected": provider["file"] in selected_paths,
                    })
            else:
                unresolved.append({
                    "diagnostic_id": diagnostic["id"],
                    "reason": f"{category} 不能通过安全的闭包增量自动修复",
                })

        existing_sources = set(closure.get("repair_sources", []))
        existing_includes = set(closure.get("repair_include_dirs", []))
        actionable = [
            item for item in repairs
            if (item["action"] == "add-source" and item["path"] not in existing_sources)
            or (item["action"] == "add-include-dir" and item["path"] not in existing_includes)
        ]
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "repairs": repairs,
            "unresolved": unresolved,
            "summary": {
                "proposed": len(repairs),
                "actionable": len(actionable),
                "unresolved": len(unresolved),
            },
        }

    @staticmethod
    def summarize_warnings(output: str) -> dict[str, Any]:
        warnings = [line.strip() for line in output.splitlines() if "warning:" in line.lower()]
        categories: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        for line in warnings:
            category = "other"
            for name, pattern in WARNING_CATEGORIES:
                if pattern.search(line):
                    category = name
                    break
            categories[category] = categories.get(category, 0) + 1
            samples.setdefault(category, [])
            if len(samples[category]) < 3:
                samples[category].append(line)
        return {
            "count": len(warnings),
            "categories": dict(sorted(categories.items())),
            "samples": samples,
        }
