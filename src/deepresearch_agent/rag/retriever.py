from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.rag.embedding import Embedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


class ScopeHit(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    section_label: str | None
    text: str
    score: float


class ScopeIndexMismatchError(RuntimeError):
    pass


class ScopeRetriever:
    def __init__(
        self,
        embedder: Embedder,
        vector_store: FaissVectorStore,
        repository: CompanyRepository,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository

    def search(self, query: str, k: int = 10) -> list[ScopeHit]:
        query_vector = self.embedder.embed_query(query)
        matches = self.vector_store.search(query_vector, k)
        records = self.repository.get_scope_chunks([chunk_id for chunk_id, _ in matches])
        hits: list[ScopeHit] = []
        for chunk_id, score in matches:
            record = records.get(chunk_id)
            if record is None:
                continue
            hits.append(
                ScopeHit(
                    unified_social_credit_code=record.unified_social_credit_code,
                    legal_name=record.legal_name,
                    section_label=record.section_label,
                    text=record.text,
                    score=score,
                )
            )
        return hits


def load_scope_retriever(
    database_path: str | Path,
    index_path: str | Path,
    embedder: Embedder,
) -> ScopeRetriever:
    repository = CompanyRepository(database_path)
    metadata = repository.get_scope_index_metadata()
    if metadata is None:
        raise ScopeIndexMismatchError(
            "scope index metadata missing; run scripts/build_scope_index.py to rebuild"
        )
    if (
        metadata.embedding_model != embedder.model_name
        or metadata.embedding_dim != embedder.dimension
    ):
        raise ScopeIndexMismatchError(
            f"index built with {metadata.embedding_model}/{metadata.embedding_dim}, "
            f"query uses {embedder.model_name}/{embedder.dimension}; rebuild the index"
        )
    if not Path(index_path).exists():
        raise ScopeIndexMismatchError(
            f"FAISS index not found: {index_path}; run scripts/build_scope_index.py"
        )
    store = FaissVectorStore.load(Path(index_path), metadata.embedding_dim)
    return ScopeRetriever(embedder, store, repository)
