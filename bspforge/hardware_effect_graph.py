from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bspforge.capability_schema import CAPABILITY_SCHEMA


CAPABILITY_TERMS = {
    "clock": {"clock", "clk", "pll", "osc", "frequency", "freq", "rcc", "sysclk"},
    "interrupt": {"interrupt", "irq", "isr", "vector", "intc", "nvic", "plic", "handler"},
    "uart": {"uart", "usart", "serial", "sci", "lpuart"},
    "gpio": {"gpio", "pin", "port", "pad", "ioport", "iomux", "pinmux"},
    "timer": {"timer", "tim", "counter", "alarm", "tick", "period", "reload", "compare", "capture"},
}

ACTION_TERMS = {
    "initialize": {"init", "initialize", "setup", "reset", "configure", "config"},
    "configure": {"config", "configure", "setup", "mode", "baud", "format"},
    "enable": {"enable", "start", "unmask", "set", "open"},
    "disable": {"disable", "stop", "mask", "clear", "close"},
    "get_frequency": {"get", "read", "frequency", "freq", "rate", "hz"},
    "register": {"register", "attach", "vector", "callback", "handler", "install"},
    "write": {"write", "send", "transmit", "put", "output", "set"},
    "read": {"read", "receive", "recv", "get", "input", "fetch"},
    "attach_irq": {"attach", "register", "callback", "irq", "interrupt", "event"},
    "start": {"start", "enable", "run", "resume", "trigger"},
    "stop": {"stop", "disable", "halt", "pause", "suspend"},
    "set_interval": {"period", "interval", "reload", "compare", "timeout", "match", "set"},
}

FEATURE_NAMES = [
    "hw-direct-operation-effect",
    "hw-transitive-operation-effect",
    "hw-register-anchor",
    "hw-anchor-depth-score",
    "hw-api-boundary-depth",
    "hw-capability-effect",
    "hw-action-effect",
    "hw-effect-purity",
    "hw-effect-breadth",
    "hw-read-access",
    "hw-write-access",
    "hw-bitwise-update",
    "hw-mmio-access",
    "hw-caller-fanin",
    "hw-callee-fanout",
    "hw-public-boundary",
    "hw-signature-contract",
    "hw-internal-callback-likelihood",
    "hw-static-internal",
    "hw-composite-likelihood",
    "hw-example-likelihood",
    "hw-os-adapter-likelihood",
]

INTERNAL_ROLE_TERMS = {
    "handler", "handle", "isr", "callback", "dispatch", "worker", "bottom",
    "internal", "private", "service", "trampoline",
}

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MEMBER_RE = re.compile(r"([A-Za-z_]\w*)\s*(?:->|\.)\s*([A-Za-z_]\w*)")
MACRO_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s*(.*)$", re.MULTILINE)
REGISTER_FIELD_RE = re.compile(
    r"(?:__IOM|__IO|__IM|__I|volatile)\s+[A-Za-z_]\w*(?:\s+\w+)*\s+([A-Za-z_]\w*)\s*(?:\[[^]]+\])?\s*;"
)
REGISTER_HINTS = {
    "reg", "register", "base", "mask", "bit", "msk", "pos", "offset",
    "ctrl", "control", "status", "data", "fifo", "enable", "disable",
    "set", "clear", "clr", "cfg", "config", "period", "reload", "compare",
}
REGISTER_ACTION_TERMS = {
    "initialize": {"reset", "rst", "init"},
    "configure": {"cfg", "config", "mode", "baud", "div", "lcr", "format"},
    "enable": {"enable", "en", "start"},
    "disable": {"disable", "dis", "stop"},
    "get_frequency": {"freq", "frequency", "rate", "hz", "clock", "clk"},
    "register": {"irq", "interrupt", "vector", "callback", "isr"},
    "write": {"tx", "transmit", "tdr", "thr", "txbuf", "dout", "output"},
    "read": {"rx", "receive", "rdr", "rbr", "rxbuf", "din", "input"},
    "attach_irq": {"irq", "interrupt", "vector", "callback", "isr"},
    "start": {"start", "run", "trigger", "enable"},
    "stop": {"stop", "halt", "disable"},
    "set_interval": {"period", "interval", "reload", "compare", "timeout", "match"},
}
PROTOTYPE_RE = re.compile(
    r"(?:^|\n)\s*(?:extern\s+)?(?:[A-Za-z_]\w*[\s*]+)+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;",
    re.MULTILINE,
)


def identifier_tokens(value: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return [item for item in re.split(r"[^A-Za-z0-9]+", normalized.lower()) if item]


def _ratio(tokens: list[str], expected: set[str], denominator: float = 2.0) -> float:
    count = sum(token in expected for token in tokens)
    return min(1.0, count / denominator)


def _path_likelihood(path: str, markers: tuple[str, ...]) -> float:
    lowered = "/" + path.lower().replace("\\", "/") + "/"
    return float(any(marker in lowered for marker in markers))


class SourceCorpus:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._texts: dict[str, str] = {}
        self._bodies: dict[tuple[str, int, str], str] = {}

    def text(self, relative: str) -> str:
        if relative not in self._texts:
            path = self.root / relative
            try:
                self._texts[relative] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._texts[relative] = ""
        return self._texts[relative]

    def function_body(self, function: dict[str, Any]) -> str:
        key = (function["file"], int(function.get("line", 1)), function["name"])
        if key in self._bodies:
            return self._bodies[key]
        text = self.text(function["file"])
        if not text:
            self._bodies[key] = ""
            return ""
        line = max(1, int(function.get("line", 1)))
        offsets = [0]
        offsets.extend(match.end() for match in re.finditer(r"\n", text))
        offset = offsets[min(line - 1, len(offsets) - 1)]
        function_name = function["name"]
        name_at = text.find(function_name, max(0, offset - 256), min(len(text), offset + 4096))
        if name_at < 0 and "::" in function_name:
            name_at = text.find(
                function_name.rsplit("::", 1)[-1],
                max(0, offset - 256),
                min(len(text), offset + 4096),
            )
        search_from = name_at if name_at >= 0 else offset
        opening = text.find("{", search_from, min(len(text), search_from + 8192))
        semicolon = text.find(";", search_from, min(len(text), search_from + 8192))
        if opening < 0 or (semicolon >= 0 and semicolon < opening):
            self._bodies[key] = ""
            return ""
        closing = self._balanced_brace_end(text, opening)
        body = text[opening : min(closing, opening + 50000)]
        self._bodies[key] = body
        return body

    @staticmethod
    def _balanced_brace_end(text: str, opening: int) -> int:
        depth = 0
        quote = ""
        escaped = False
        line_comment = False
        block_comment = False
        index = opening
        while index < len(text):
            char = text[index]
            following = text[index + 1] if index + 1 < len(text) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
                index += 1
                continue
            if block_comment:
                if char == "*" and following == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue
            if char == "/" and following == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and following == "*":
                block_comment = True
                index += 2
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        return len(text)


class RegisterCatalog:
    def __init__(self) -> None:
        self.capabilities: dict[str, set[str]] = defaultdict(set)
        self.actions: dict[str, set[str]] = defaultdict(set)
        self.public_symbols: set[str] = set()
        self.evidence = Counter()

    @classmethod
    def build(
        cls, ir: dict[str, Any], corpus: SourceCorpus, candidate_functions: list[dict[str, Any]]
    ) -> "RegisterCatalog":
        catalog = cls()
        files = {item["path"]: item for item in ir["files"]}
        basename: dict[str, list[str]] = defaultdict(list)
        for path in files:
            basename[Path(path).name].append(path)
        headers: set[str] = set()
        for function in candidate_functions:
            if Path(function["file"]).suffix.lower() in {".h", ".hpp"}:
                headers.add(function["file"])
            for include in function.get("includes", []):
                matches = basename.get(Path(include).name, [])
                if matches:
                    headers.add(min(matches, key=lambda item: len(Path(item).parts)))
        for path in headers:
            catalog._scan_header(path, corpus.text(path))
        for path in files:
            if Path(path).suffix.lower() == ".svd":
                catalog._scan_svd(corpus.root / path)
        return catalog

    def _scan_header(self, path: str, text: str) -> None:
        if not text or len(text) > 4_000_000:
            return
        path_tokens = identifier_tokens(path)
        self.public_symbols.update(PROTOTYPE_RE.findall(text))
        for name, value in MACRO_RE.findall(text):
            tokens = identifier_tokens(name + " " + value)
            looks_register = bool(
                set(tokens) & REGISTER_HINTS
                or re.search(r"0x[0-9A-Fa-f]+|__IO|volatile|\bBIT\s*\(", value)
            )
            if looks_register:
                self._add(name, tokens + path_tokens, "header-macro")
        for match in REGISTER_FIELD_RE.finditer(text):
            start = max(0, match.start() - 300)
            context = text[start : match.end()]
            self._add(match.group(1), identifier_tokens(context) + path_tokens, "register-field")

    def _scan_svd(self, path: Path) -> None:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return
        for peripheral in root.findall(".//{*}peripheral"):
            p_name = peripheral.findtext("{*}name", default="")
            p_desc = peripheral.findtext("{*}description", default="")
            for register in peripheral.findall(".//{*}register"):
                name = register.findtext("{*}name", default="")
                desc = register.findtext("{*}description", default="")
                self._add(name, identifier_tokens(f"{p_name} {p_desc} {name} {desc}"), "cmsis-svd")

    def _add(self, name: str, context_tokens: list[str], source: str) -> None:
        token_set = set(context_tokens)
        matches = {
            capability
            for capability, terms in CAPABILITY_TERMS.items()
            if token_set & terms
        }
        if matches:
            self.capabilities[name.lower()].update(matches)
            for operation, terms in REGISTER_ACTION_TERMS.items():
                if token_set & terms:
                    self.actions[name.lower()].add(operation)
            self.evidence[source] += 1

    def classify(self, identifier: str) -> set[str]:
        lowered = identifier.lower()
        matches = set(self.capabilities.get(lowered, set()))
        tokens = set(identifier_tokens(identifier))
        for capability, terms in CAPABILITY_TERMS.items():
            if tokens & terms:
                matches.add(capability)
        return matches

    def classify_actions(self, identifier: str) -> set[str]:
        lowered = identifier.lower()
        matches = set(self.actions.get(lowered, set()))
        tokens = set(identifier_tokens(identifier))
        for operation, terms in REGISTER_ACTION_TERMS.items():
            if tokens & terms:
                matches.add(operation)
        return matches


class HardwareEffectGraph:
    """Build query-independent body/register summaries and propagate them over calls."""

    def __init__(self, ir: dict[str, Any], source_root: Path, candidate_ids: set[str]) -> None:
        self.ir = ir
        self.corpus = SourceCorpus(source_root)
        self.functions = {item["id"]: item for item in ir["functions"]}
        self.by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for function in ir["functions"]:
            self.by_name[function["name"]].append(function)
            if "::" in function["name"]:
                self.by_name[function["name"].rsplit("::", 1)[-1]].append(function)
        candidate_functions = [self.functions[item] for item in candidate_ids if item in self.functions]
        self.catalog = RegisterCatalog.build(ir, self.corpus, candidate_functions)
        self.adjacency = {
            entity_id: self._resolve_calls(function)
            for entity_id, function in self.functions.items()
            if function.get("calls")
        }
        self.reverse_count = Counter(
            target for targets in self.adjacency.values() for target in targets
        )
        self._direct_cache: dict[str, dict[str, Any]] = {}
        self._effect_cache: dict[tuple[str, str, int], tuple[float, int | None, list[str]]] = {}

    def _resolve_calls(self, function: dict[str, Any]) -> list[str]:
        output = []
        source = Path(function["file"])
        for name in function.get("calls", []):
            providers = self.by_name.get(name, [])
            if not providers and "::" in name:
                providers = self.by_name.get(name.rsplit("::", 1)[-1], [])
            if not providers:
                continue
            provider = max(
                providers,
                key=lambda item: (
                    len(set(source.parts).intersection(Path(item["file"]).parts)),
                    -abs(int(item.get("line", 1)) - int(function.get("line", 1)))
                    if item["file"] == function["file"] else -10**9,
                    item["id"],
                ),
            )
            output.append(provider["id"])
        return sorted(set(output))

    def _direct_summary(self, entity_id: str) -> dict[str, Any]:
        if entity_id in self._direct_cache:
            return self._direct_cache[entity_id]
        function = self.functions[entity_id]
        body = self.corpus.function_body(function)
        identifiers = IDENTIFIER_RE.findall(body)
        tokens = identifier_tokens(" ".join(identifiers + function.get("calls", [])))
        register_hits: list[tuple[str, set[str], set[str]]] = []
        for base, field in MEMBER_RE.findall(body):
            capabilities = self.catalog.classify(base + "_" + field)
            field_known = field.lower() in self.catalog.capabilities
            field_register_hint = bool(set(identifier_tokens(field)) & REGISTER_HINTS)
            if field_known or field_register_hint:
                register_hits.append((
                    f"{base}->{field}", capabilities,
                    self.catalog.classify_actions(base + "_" + field),
                ))
        for identifier in identifiers:
            capabilities = self.catalog.classify(identifier)
            if identifier.lower() in self.catalog.capabilities:
                register_hits.append((
                    identifier, capabilities, self.catalog.classify_actions(identifier)
                ))
        register_caps = Counter(
            capability for _, capabilities, _ in register_hits for capability in capabilities
        )
        register_actions = Counter(
            operation for _, _, actions in register_hits for operation in actions
        )
        capability_scores = {
            capability: min(
                1.0,
                0.34 * _ratio(tokens, terms, 2.0)
                + 0.66 * min(1.0, register_caps[capability] / 2.0),
            )
            for capability, terms in CAPABILITY_TERMS.items()
        }
        lowered = body.lower()
        assignment = bool(re.search(r"(?:->|\.)\s*[A-Za-z_]\w*\s*(?:\|=|&=|\^=|=)", body))
        write_access = float(
            assignment
            or bool(re.search(r"\b(?:write|set|clear|modify|store|out)\w*\s*\(", lowered))
        )
        read_access = float(
            bool(re.search(r"\b(?:return\s+.*(?:->|\.)|read|get|load|in)\w*\s*\(", lowered))
            or bool(re.search(r"=\s*[^;]*(?:->|\.)\s*[A-Za-z_]\w*", body))
        )
        bitwise = float(bool(re.search(r"\|=|&=|\^=|<<|>>|\bBIT\s*\(", body)))
        mmio = float(bool(re.search(r"\bvolatile\b|0x[0-9A-Fa-f]{6,}|\bMMIO\b|\bHWREG\b", body)))
        register_anchor = min(1.0, len({item[0] for item in register_hits}) / 2.0 + 0.35 * mmio)
        summary = {
            "body": body,
            "tokens": tokens,
            "capability_scores": capability_scores,
            "register_action_scores": {
                operation: min(1.0, register_actions[operation] / 2.0)
                for operation in REGISTER_ACTION_TERMS
            },
            "register_anchor": register_anchor,
            "register_hits": [item[0] for item in register_hits[:12]],
            "read_access": read_access,
            "write_access": write_access,
            "bitwise": bitwise,
            "mmio": mmio,
            "body_size": min(1.0, math.log1p(len(body)) / math.log(50001.0)),
        }
        self._direct_cache[entity_id] = summary
        return summary

    def _direct_operation(self, entity_id: str, operation_id: str) -> tuple[float, float, float]:
        capability, operation = operation_id.split(".", 1)
        summary = self._direct_summary(entity_id)
        capability_score = float(summary["capability_scores"][capability])
        body_action_score = _ratio(summary["tokens"], ACTION_TERMS[operation], 2.0)
        register_action_score = float(summary["register_action_scores"][operation])
        action_score = min(1.0, 0.60 * body_action_score + 0.40 * register_action_score)
        if operation in {"write", "enable", "disable", "start", "stop", "set_interval", "configure", "initialize"}:
            access_score = summary["write_access"]
        elif operation in {"read", "get_frequency"}:
            access_score = summary["read_access"]
        else:
            access_score = max(summary["read_access"], summary["write_access"])
        effect = capability_score * (
            0.48 * action_score
            + 0.17 * access_score
            + 0.15 * summary["register_anchor"]
            + 0.20 * register_action_score
        )
        return min(1.0, effect), action_score, capability_score

    def _propagated_effect(
        self, entity_id: str, operation_id: str, depth: int = 3, visiting: set[str] | None = None
    ) -> tuple[float, int | None, list[str]]:
        key = (entity_id, operation_id, depth)
        if key in self._effect_cache:
            return self._effect_cache[key]
        visiting = set(visiting or ())
        if entity_id in visiting:
            return 0.0, None, []
        visiting.add(entity_id)
        direct, _, _ = self._direct_operation(entity_id, operation_id)
        best = direct
        best_depth = 0 if self._direct_summary(entity_id)["register_anchor"] > 0 else None
        path = [self.functions[entity_id]["name"]] if direct > 0 else []
        if depth > 0:
            for child in self.adjacency.get(entity_id, []):
                child_score, child_depth, child_path = self._propagated_effect(
                    child, operation_id, depth - 1, visiting
                )
                propagated = 0.78 * child_score
                if propagated > best:
                    best = propagated
                    best_depth = child_depth + 1 if child_depth is not None else None
                    path = [self.functions[entity_id]["name"], *child_path]
        result = min(1.0, best), best_depth, path[:6]
        self._effect_cache[key] = result
        return result

    def candidate_features(self, candidate: dict[str, Any], operation_id: str) -> tuple[dict[str, float], dict[str, Any]]:
        entity_id = candidate["entity_id"]
        function = self.functions.get(entity_id)
        if function is None:
            return {name: 0.0 for name in FEATURE_NAMES}, {"status": "missing-ir-entity"}
        direct, action, capability_score = self._direct_operation(entity_id, operation_id)
        propagated, anchor_depth, path = self._propagated_effect(entity_id, operation_id)
        summary = self._direct_summary(entity_id)
        operation_effects = {
            f"{capability}.{operation}": self._propagated_effect(
                entity_id, f"{capability}.{operation}"
            )[0]
            for capability, specification in CAPABILITY_SCHEMA.items()
            for operation in specification["operations"]
        }
        capability_max = {
            capability: max(
                operation_effects[f"{capability}.{operation}"]
                for operation in specification["operations"]
            )
            for capability, specification in CAPABILITY_SCHEMA.items()
        }
        total = sum(capability_max.values())
        breadth = sum(value >= 0.20 for value in capability_max.values()) / len(capability_max)
        purity = propagated / total if total > 1e-9 else 0.0
        path_text = function["file"].lower().replace("\\", "/")
        example = _path_likelihood(path_text, ("/example/", "/examples/", "/demo/", "/test/", "/tests/"))
        os_adapter = _path_likelihood(path_text, ("/porting/", "/adapter/", "/rt-thread/", "/zephyr/"))
        middleware = _path_likelihood(path_text, ("/middleware/", "/protocol/", "/application/", "/apps/"))
        public_boundary = float(
            Path(function["file"]).suffix.lower() in {".h", ".hpp"}
            or any(
                Path(item["file"]).suffix.lower() in {".h", ".hpp"}
                for item in self.by_name.get(function["name"], [])
            )
            or function["name"] in self.catalog.public_symbols
        )
        signature = str(function.get("signature", ""))
        interface_tokens = identifier_tokens(f"{function['name']} {signature}")
        capability, operation = operation_id.split(".", 1)
        signature_contract = min(
            1.0,
            0.50 * _ratio(interface_tokens, CAPABILITY_TERMS[capability], 1.0)
            + 0.50 * _ratio(interface_tokens, ACTION_TERMS[operation], 1.0),
        )
        name_tokens = set(identifier_tokens(function["name"]))
        internal_callback = float(bool(name_tokens & INTERNAL_ROLE_TERMS))
        static_internal = float(bool(re.search(r"\bstatic\b", signature)))
        if anchor_depth is None:
            api_boundary_depth = 0.0
        else:
            depth_preference = {0: 0.35, 1: 1.0, 2: 0.82, 3: 0.58}
            api_boundary_depth = depth_preference.get(anchor_depth, 0.35)
            if not public_boundary:
                api_boundary_depth *= 0.72
        fanin = min(1.0, math.log1p(self.reverse_count[entity_id]) / math.log(17.0))
        fanout = min(1.0, math.log1p(len(self.adjacency.get(entity_id, []))) / math.log(17.0))
        composite = min(1.0, 0.55 * breadth + 0.25 * fanout + 0.20 * middleware)
        features = {
            "hw-direct-operation-effect": direct,
            "hw-transitive-operation-effect": propagated,
            "hw-register-anchor": float(summary["register_anchor"]),
            "hw-anchor-depth-score": 1.0 / (1.0 + anchor_depth) if anchor_depth is not None else 0.0,
            "hw-api-boundary-depth": api_boundary_depth,
            "hw-capability-effect": capability_score,
            "hw-action-effect": action,
            "hw-effect-purity": min(1.0, purity),
            "hw-effect-breadth": breadth,
            "hw-read-access": float(summary["read_access"]),
            "hw-write-access": float(summary["write_access"]),
            "hw-bitwise-update": float(summary["bitwise"]),
            "hw-mmio-access": float(summary["mmio"]),
            "hw-caller-fanin": fanin,
            "hw-callee-fanout": fanout,
            "hw-public-boundary": public_boundary,
            "hw-signature-contract": signature_contract,
            "hw-internal-callback-likelihood": internal_callback,
            "hw-static-internal": static_internal,
            "hw-composite-likelihood": composite,
            "hw-example-likelihood": example,
            "hw-os-adapter-likelihood": os_adapter,
        }
        evidence = {
            "status": "analyzed",
            "effect_path": path,
            "register_hits": summary["register_hits"],
            "anchor_depth": anchor_depth,
            "capability_effects": {key: round(value, 6) for key, value in capability_max.items()},
        }
        return {key: round(value, 6) for key, value in features.items()}, evidence


def hardware_heuristic_score(candidate: dict[str, Any], *, transitive: bool = True) -> float:
    features = candidate["features"]
    effect = float(features.get(
        "hw-transitive-operation-effect" if transitive else "hw-direct-operation-effect", 0.0
    ))
    score = (
        0.55 * effect
        + 0.12 * float(features.get("hw-register-anchor", 0.0))
        + 0.10 * float(features.get("hw-anchor-depth-score", 0.0))
        + 0.16 * float(features.get("hw-api-boundary-depth", 0.0))
        + 0.10 * float(features.get("hw-effect-purity", 0.0))
        + 0.08 * float(features.get("hw-public-boundary", 0.0))
        + 0.16 * float(features.get("hw-signature-contract", 0.0))
        + 0.05 * float(features.get("hw-caller-fanin", 0.0))
        - 0.12 * float(features.get("hw-example-likelihood", 0.0))
        - 0.08 * float(features.get("hw-os-adapter-likelihood", 0.0))
        - 0.14 * float(features.get("hw-internal-callback-likelihood", 0.0))
        - 0.12 * float(features.get("hw-static-internal", 0.0))
    )
    return score


def hard_constraint_penalty(candidate: dict[str, Any]) -> float:
    features = candidate["features"]
    return min(
        1.0,
        max(
            float(features.get("opposite-action", 0.0)),
            float(features.get("semantic-conflict", 0.0)),
            float(features.get("reverse-os-adapter", 0.0)),
            float(features.get("test-example", 0.0)),
        ),
    )
