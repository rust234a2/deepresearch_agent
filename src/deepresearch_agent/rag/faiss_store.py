from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


class FaissVectorStore:
    def __init__(self, dimension: int, index: faiss.Index | None = None) -> None:
        self.dimension = dimension
        self._index = (
            index
            if index is not None
            else faiss.IndexIDMap(faiss.IndexFlatIP(dimension))
        )

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        self._index.add_with_ids(
            np.ascontiguousarray(vectors, dtype=np.float32),
            np.asarray(ids, dtype=np.int64),
        )

    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]:
        query2d = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
        scores, ids = self._index.search(query2d, k)
        return [
            (int(chunk_id), float(score))
            for chunk_id, score in zip(ids[0], scores[0])
            if chunk_id != -1
        ]

    def save(self, path: Path) -> None:
        faiss.write_index(self._index, str(path))

    @classmethod
    def load(cls, path: Path, dimension: int) -> FaissVectorStore:
        return cls(dimension=dimension, index=faiss.read_index(str(path)))
