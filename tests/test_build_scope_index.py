import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


def test_build_scope_index_writes_embeddings_metadata_and_faiss(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"

    summary = build_scope_index(
        company_database_path,
        index_path,
        FakeEmbedder(),
        now="2026-06-22T00:00:00+00:00",
    )

    assert summary == {"chunks": 2}
    assert index_path.exists()
    with sqlite3.connect(company_database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM business_scope_chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0] == 2
        meta = connection.execute(
            "SELECT embedding_model, embedding_dim, normalized, chunk_count, built_at "
            "FROM scope_index_metadata"
        ).fetchone()
        assert meta == ("fake-embedder", 8, 1, 2, "2026-06-22T00:00:00+00:00")
        ids = [row[0] for row in connection.execute(
            "SELECT chunk_id FROM business_scope_chunks ORDER BY chunk_id"
        )]

    store = FaissVectorStore.load(index_path, dimension=8)
    query = FakeEmbedder().embed_query("工业设备制造")
    assert store.search(query, k=1)[0][0] in ids
