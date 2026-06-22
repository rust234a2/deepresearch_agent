import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402


@pytest.mark.slow
def test_bge_semantic_recall_end_to_end(company_database_path, tmp_path):
    from deepresearch_agent.rag.embedding import BgeEmbedder
    from deepresearch_agent.rag.retriever import load_scope_retriever

    embedder = BgeEmbedder()
    assert embedder.dimension == 512

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, embedder)
    retriever = load_scope_retriever(company_database_path, index_path, embedder)

    hits = retriever.search("机械设备生产", k=2)

    assert hits
    assert hits[0].legal_name == "示例科技股份有限公司"
    assert 0.0 <= hits[0].score <= 1.0001
