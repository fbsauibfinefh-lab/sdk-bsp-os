from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(value).hexdigest()[:16]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def copytree_filtered(source: Path, destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {".git", "__pycache__", ".sconsign.dblite"}.intersection(names)
        current = Path(directory)
        if current.name == "build":
            ignored.update(names)
        for name in names:
            if name.endswith((".o", ".elf", ".bin", ".map", ".pyc")):
                ignored.add(name)
        return ignored

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore, symlinks=False)


def relative_files(root: Path, suffixes: Iterable[str]) -> list[Path]:
    wanted = {item.lower() for item in suffixes}
    excluded = {".git", "build", "__pycache__", ".cache"}
    output: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(item for item in dirnames if item not in excluded)
        base = Path(directory)
        for filename in sorted(filenames):
            path = base / filename
            if path.suffix.lower() in wanted or filename in {
                "CMakeLists.txt", "Makefile", "SConstruct", "SConscript"
            }:
                output.append(path)
    return output

