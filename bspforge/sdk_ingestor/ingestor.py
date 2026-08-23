from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bspforge.common import file_sha256, relative_files, stable_id, utc_now


FUNCTION_RE = re.compile(
    r"(?m)^[ \t]*(?!if\b|for\b|while\b|switch\b)"
    r"(?P<signature>(?:[A-Za-z_]\w*[ \t\n\r\*]+)+"
    r"(?P<name>[A-Za-z_]\w*)[ \t]*\([^;{}]*\))[ \t\n\r]*\{"
)
INCLUDE_RE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
MACRO_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)", re.MULTILINE)
BUILD_TOKEN_RE = re.compile(r"[A-Za-z0-9_./+\-]+\.(?:c|cc|cpp|cxx|S|s|h|a|ld|lds)\b")
GLOBAL_RE = re.compile(
    r"^(?!static\b|typedef\b|extern\b)"
    r"(?P<type>(?:(?:const|volatile)\s+)*(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*)*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*(?:=\s*[^;]+)?;$"
)

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".s", ".S"}
HEADER_SUFFIXES = {".h", ".hpp"}
BUILD_NAMES = {"CMakeLists.txt", "Makefile", "SConstruct", "SConscript"}
BUILD_SUFFIXES = {".cmake", ".mk"}
LINKER_SUFFIXES = {".ld", ".lds"}


class SDKIngestor:
    """Extract a traceable migration IR from a vendor SDK tree."""

    def __init__(self, max_file_bytes: int = 2 * 1024 * 1024) -> None:
        self.max_file_bytes = max_file_bytes

    def ingest(self, sdk_root: Path, sdk_id: str) -> dict[str, Any]:
        sdk_root = sdk_root.resolve()
        if not sdk_root.is_dir():
            raise FileNotFoundError(f"SDK root does not exist: {sdk_root}")

        paths = relative_files(
            sdk_root,
            SOURCE_SUFFIXES | HEADER_SUFFIXES | BUILD_SUFFIXES | LINKER_SUFFIXES,
        )
        records: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        symbols: list[dict[str, Any]] = []
        build_rules: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        basename_index: dict[str, list[str]] = defaultdict(list)
        texts: dict[str, str] = {}

        for path in paths:
            relative = path.relative_to(sdk_root).as_posix()
            basename_index[path.name].append(relative)
            size = path.stat().st_size
            kind = self._kind(path)
            record = {
                "id": stable_id(sdk_id, "file", relative),
                "path": relative,
                "kind": kind,
                "size": size,
                "sha256": file_sha256(path),
            }
            records.append(record)
            if size <= self.max_file_bytes:
                texts[relative] = path.read_text(encoding="utf-8", errors="replace")

        function_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relative, text in texts.items():
            path = Path(relative)
            if path.suffix in SOURCE_SUFFIXES:
                for entity in self._extract_functions(sdk_id, relative, text):
                    functions.append(entity)
                    function_by_name[entity["name"]].append(entity)
                symbols.extend(self._extract_global_symbols(sdk_id, relative, text))

        for relative, text in texts.items():
            file_id = stable_id(sdk_id, "file", relative)
            includes = INCLUDE_RE.findall(text)
            for include in includes:
                matches = basename_index.get(Path(include).name, [])
                if matches:
                    edges.append({
                        "type": "includes",
                        "from": file_id,
                        "to": stable_id(sdk_id, "file", self._best_match(relative, include, matches)),
                    })
            if Path(relative).name in BUILD_NAMES or Path(relative).suffix in BUILD_SUFFIXES:
                refs = sorted(set(BUILD_TOKEN_RE.findall(text)))
                build_id = stable_id(sdk_id, "build", relative)
                build_rules.append({
                    "id": build_id,
                    "path": relative,
                    "system": self._build_system(Path(relative)),
                    "references": refs,
                    "evidence": {"path": relative, "line": 1, "kind": "build-rule"},
                })
                for token in refs:
                    matches = basename_index.get(Path(token).name, [])
                    if matches:
                        edges.append({
                            "type": "builds",
                            "from": build_id,
                            "to": stable_id(sdk_id, "file", self._best_match(relative, token, matches)),
                        })

        for function in functions:
            for call in function["calls"]:
                for target in function_by_name.get(call, [])[:1]:
                    edges.append({"type": "calls", "from": function["id"], "to": target["id"]})
            edges.append({
                "type": "defines",
                "from": stable_id(sdk_id, "file", function["file"]),
                "to": function["id"],
            })
        for symbol in symbols:
            edges.append({
                "type": "defines",
                "from": stable_id(sdk_id, "file", symbol["file"]),
                "to": symbol["id"],
            })

        digest_material = "".join(item["sha256"] for item in records)
        sdk_digest = stable_id(sdk_id, digest_material)
        kind_counts = Counter(item["kind"] for item in records)
        return {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "sdk": {"id": sdk_id, "root": str(sdk_root), "digest": sdk_digest},
            "files": records,
            "functions": functions,
            "symbols": symbols,
            "build_rules": build_rules,
            "edges": edges,
            "stats": {
                "files": len(records),
                "functions": len(functions),
                "symbols": len(symbols),
                "build_rules": len(build_rules),
                "edges": len(edges),
                "file_kinds": dict(sorted(kind_counts.items())),
            },
        }

    @staticmethod
    def _extract_global_symbols(sdk_id: str, relative: str, text: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        depth = 0
        in_block_comment = False
        for line_number, original in enumerate(text.splitlines(), start=1):
            line = original.strip()
            if in_block_comment:
                if "*/" in line:
                    line = line.split("*/", 1)[1].strip()
                    in_block_comment = False
                else:
                    continue
            if "/*" in line:
                before, after = line.split("/*", 1)
                line = before.strip()
                if "*/" not in after:
                    in_block_comment = True
            line = line.split("//", 1)[0].strip()
            if depth == 0 and line and "(" not in line and not line.startswith("#"):
                match = GLOBAL_RE.match(line)
                if match:
                    name = match.group("name")
                    output.append({
                        "id": stable_id(sdk_id, "symbol", relative, name, str(line_number)),
                        "name": name,
                        "symbol_kind": "global-variable",
                        "type": " ".join(match.group("type").split()),
                        "file": relative,
                        "line": line_number,
                        "evidence": {"path": relative, "line": line_number, "kind": "definition"},
                    })
            depth += line.count("{") - line.count("}")
            depth = max(depth, 0)
        return output

    def _extract_functions(self, sdk_id: str, relative: str, text: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        includes = INCLUDE_RE.findall(text)
        macros = MACRO_RE.findall(text)
        for match in FUNCTION_RE.finditer(text):
            name = match.group("name")
            end = self._body_end(text, match.end() - 1)
            body = text[match.end():end]
            calls = sorted({call for call in CALL_RE.findall(body) if call != name})
            line = text.count("\n", 0, match.start()) + 1
            signature = " ".join(match.group("signature").split())
            output.append({
                "id": stable_id(sdk_id, "function", relative, name, str(line)),
                "name": name,
                "signature": signature,
                "file": relative,
                "line": line,
                "calls": calls,
                "includes": includes,
                "nearby_macros": macros[:64],
                "evidence": {"path": relative, "line": line, "kind": "definition"},
            })
        return output

    @staticmethod
    def _body_end(text: str, opening: int) -> int:
        depth = 0
        for index in range(opening, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return index
        return len(text)

    @staticmethod
    def _best_match(origin: str, token: str, matches: list[str]) -> str:
        normalized = token.lstrip("./")
        exact = [item for item in matches if item.endswith(normalized)]
        if exact:
            return min(exact, key=len)
        origin_parts = set(Path(origin).parts)
        return max(matches, key=lambda item: len(origin_parts.intersection(Path(item).parts)))

    @staticmethod
    def _kind(path: Path) -> str:
        if path.name in BUILD_NAMES or path.suffix in BUILD_SUFFIXES:
            return "build"
        if path.suffix in LINKER_SUFFIXES:
            return "linker"
        if path.suffix in HEADER_SUFFIXES:
            return "header"
        if path.suffix.lower() in {".s"}:
            lowered = path.name.lower()
            return "startup" if any(word in lowered for word in ("crt", "start", "entry")) else "assembly"
        return "source"

    @staticmethod
    def _build_system(path: Path) -> str:
        if path.name == "CMakeLists.txt" or path.suffix == ".cmake":
            return "cmake"
        if path.name in {"SConstruct", "SConscript"}:
            return "scons"
        return "make"
