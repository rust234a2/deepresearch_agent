from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np


class VectorStore(Protocol):
    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]: ...

    def save(self, path: Path) -> None: ...
