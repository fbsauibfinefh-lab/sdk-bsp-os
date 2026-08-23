from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class OSBackend(ABC):
    @abstractmethod
    def generate(
        self,
        rtthread_root: Path,
        board: str,
        output: Path,
        ir: dict[str, Any],
        resolution: dict[str, Any],
        closure: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build(self, project: Path, toolchain_bin: Path, jobs: int = 1) -> tuple[int, str]:
        raise NotImplementedError
