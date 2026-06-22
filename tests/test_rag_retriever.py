import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.retriever import (
    ScopeIndexMismatchError,
    load_scope_retriever,
)


def _prepare(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")
    return index_path


def test_retriever_returns_ranked_hits(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())

    hits = retriever.search("工业设备制造", k=5)

    assert hits[0].text == "工业设备制造"
    assert hits[0].legal_name == "示例科技股份有限公司"
    assert hits[0].score > 0.99
    assert len(hits) <= 5


def test_retriever_respects_k_limit(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())

    assert len(retriever.search("工业设备", k=1)) == 1


class _OtherEmbedder(FakeEmbedder):
    model_name = "other-model"


def test_retriever_rejects_model_mismatch(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)

    with pytest.raises(ScopeIndexMismatchError, match="rebuild"):
        load_scope_retriever(company_database_path, index_path, _OtherEmbedder())
