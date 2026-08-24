from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable


CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
INCLUDE_RE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE)
MACRO_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)", re.MULTILINE)


class HybridFrontend:
    """Recover C functions using Clang, tree-sitter, then a regex fallback."""

    def __init__(
        self,
        mode: str = "hybrid",
        compile_commands: Path | None = None,
        clang_binary: str = "clang",
    ) -> None:
        if mode not in {"hybrid", "regex"}:
            raise ValueError("ingestor mode must be 'hybrid' or 'regex'")
        self.mode = mode
        self.compile_commands = compile_commands
        self.clang_binary = clang_binary
        self._commands = self._load_commands(compile_commands)
        self._tree_available = self._load_tree_sitter() is not None
        self._thread_local = threading.local()

    def extract(
        self,
        sdk_id: str,
        relative: str,
        absolute: Path,
        text: str,
        regex_extractor: Callable[[str, str, str], list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        attempts: list[dict[str, str]] = []
        if self.mode == "hybrid":
            functions = self._clang_functions(sdk_id, relative, absolute, text, attempts)
            if functions:
                return functions, self._report(relative, "clang-ast", attempts)
            functions = self._tree_sitter_functions(sdk_id, relative, text, attempts)
            if functions:
                return functions, self._report(relative, "tree-sitter", attempts)

        functions = regex_extractor(sdk_id, relative, text)
        for function in functions:
            function["parser"] = "regex"
            function["parser_confidence"] = 0.55
        attempts.append({"frontend": "regex", "status": "success"})
        return functions, self._report(relative, "regex", attempts)

    @staticmethod
    def _report(relative: str, selected: str, attempts: list[dict[str, str]]) -> dict[str, Any]:
        return {"path": relative, "selected_frontend": selected, "attempts": attempts}

    def _clang_functions(
        self,
        sdk_id: str,
        relative: str,
        absolute: Path,
        text: str,
        attempts: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        command = self._commands.get(str(absolute.resolve()))
        clang = shutil.which(self.clang_binary)
        if command is None or clang is None:
            attempts.append({
                "frontend": "clang-ast",
                "status": "unavailable",
                "reason": "missing compile command or clang executable",
            })
            return []
        arguments = list(command.get("arguments") or [])
        if not arguments:
            arguments = command.get("command", "").split()
        if not arguments:
            attempts.append({"frontend": "clang-ast", "status": "failed", "reason": "empty command"})
            return []
        filtered: list[str] = []
        skip = False
        for index, argument in enumerate(arguments[1:]):
            if skip:
                skip = False
                continue
            if argument in {"-c", "-MMD", "-MD", "-MP"}:
                continue
            if argument in {"-o", "-MF", "-MT", "-MQ"}:
                skip = True
                continue
            if Path(argument).name == absolute.name:
                continue
            filtered.append(argument)
        invocation = [
            clang,
            *filtered,
            "-fsyntax-only",
            "-Xclang",
            "-ast-dump=json",
            str(absolute),
        ]
        try:
            result = subprocess.run(
                invocation,
                cwd=command.get("directory") or absolute.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                attempts.append({
                    "frontend": "clang-ast",
                    "status": "failed",
                    "reason": result.stderr.splitlines()[-1][:240] if result.stderr else "clang failed",
                })
                return []
            ast = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            attempts.append({"frontend": "clang-ast", "status": "failed", "reason": str(error)})
            return []
        output: list[dict[str, Any]] = []
        self._walk_clang(ast, sdk_id, relative, text, output)
        attempts.append({"frontend": "clang-ast", "status": "success" if output else "empty"})
        return output

    def _walk_clang(
        self,
        node: dict[str, Any],
        sdk_id: str,
        relative: str,
        text: str,
        output: list[dict[str, Any]],
    ) -> None:
        if node.get("kind") == "FunctionDecl" and any(
            child.get("kind") == "CompoundStmt" for child in node.get("inner", [])
        ):
            location = node.get("loc", {})
            line = int(location.get("line", 1))
            name = node.get("name")
            if name:
                calls = sorted({
                    child.get("referencedDecl", {}).get("name")
                    for child in self._descendants(node)
                    if child.get("kind") == "DeclRefExpr"
                    and child.get("referencedDecl", {}).get("kind") == "FunctionDecl"
                } - {None, name})
                output.append(self._entity(
                    sdk_id,
                    relative,
                    name,
                    node.get("type", {}).get("qualType", name + "()"),
                    line,
                    calls,
                    text,
                    "clang-ast",
                    1.0,
                ))
        for child in node.get("inner", []):
            self._walk_clang(child, sdk_id, relative, text, output)

    @classmethod
    def _descendants(cls, node: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for child in node.get("inner", []):
            result.append(child)
            result.extend(cls._descendants(child))
        return result

    def _tree_sitter_functions(
        self,
        sdk_id: str,
        relative: str,
        text: str,
        attempts: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not self._tree_available or Path(relative).suffix not in {".c", ".h"}:
            attempts.append({
                "frontend": "tree-sitter",
                "status": "unavailable",
                "reason": "parser unavailable or language not C",
            })
            return []
        parser = getattr(self._thread_local, "tree_parser", None)
        if parser is None:
            parser = self._load_tree_sitter()
            self._thread_local.tree_parser = parser
        encoded = text.encode("utf-8")
        tree = parser.parse(encoded)
        output: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                body = node.child_by_field_name("body")
                name_node = self._identifier(declarator)
                if name_node is not None and body is not None:
                    name = encoded[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
                    signature = encoded[node.start_byte:body.start_byte].decode("utf-8", "replace").strip()
                    body_text = encoded[body.start_byte:body.end_byte].decode("utf-8", "replace")
                    calls = sorted({item for item in CALL_RE.findall(body_text) if item != name})
                    output.append(self._entity(
                        sdk_id,
                        relative,
                        name,
                        " ".join(signature.split()),
                        node.start_point[0] + 1,
                        calls,
                        text,
                        "tree-sitter",
                        0.9,
                    ))
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        attempts.append({"frontend": "tree-sitter", "status": "success" if output else "empty"})
        return output

    @classmethod
    def _identifier(cls, node: Any) -> Any:
        if node is None:
            return None
        if node.type in {"identifier", "field_identifier"}:
            return node
        for child in node.children:
            found = cls._identifier(child)
            if found is not None:
                return found
        return None

    @staticmethod
    def _entity(
        sdk_id: str,
        relative: str,
        name: str,
        signature: str,
        line: int,
        calls: list[str],
        text: str,
        parser: str,
        confidence: float,
    ) -> dict[str, Any]:
        from bspforge.common import stable_id

        return {
            "id": stable_id(sdk_id, "function", relative, name, str(line)),
            "name": name,
            "signature": signature,
            "file": relative,
            "line": line,
            "calls": calls,
            "includes": INCLUDE_RE.findall(text),
            "nearby_macros": MACRO_RE.findall(text)[:64],
            "parser": parser,
            "parser_confidence": confidence,
            "evidence": {
                "path": relative,
                "line": line,
                "kind": "definition",
                "parser": parser,
                "confidence": confidence,
            },
        }

    @staticmethod
    def _load_commands(path: Path | None) -> dict[str, dict[str, Any]]:
        if path is None or not path.is_file():
            return {}
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            str((Path(item["directory"]) / item["file"]).resolve()): item
            for item in entries
            if item.get("directory") and item.get("file")
        }

    @staticmethod
    def _load_tree_sitter() -> Any:
        try:
            import tree_sitter
            import tree_sitter_c

            return tree_sitter.Parser(tree_sitter.Language(tree_sitter_c.language()))
        except (ImportError, TypeError, AttributeError):
            return None
