from __future__ import annotations

from typing import Protocol

import numpy as np

BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class FakeEmbedder:
    """Deterministic, dependency-free embedder for tests."""

    model_name = "fake-embedder"
    dimension = 8

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = np.array([self._vector(text) for text in texts], dtype=np.float32)
        return _l2_normalize(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for index, char in enumerate(text):
            vector[index % self.dimension] += (ord(char) % 17) + 1.0
        return vector


class BgeEmbedder:
    """Local bge-small-zh-v1.5 embedder via sentence-transformers."""

    model_name = "bge-small-zh-v1.5"
    dimension = 512

    def __init__(self, model_path: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_path)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vectors = self._model.encode(
            [BGE_QUERY_INSTRUCTION + text], normalize_embeddings=True
        )
        return np.asarray(vectors, dtype=np.float32)[0]
