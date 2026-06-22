import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.retriever import load_scope_retriever
from deepresearch_agent.rag.tools import build_scope_tool_registry


def test_scope_tool_returns_structured_hits(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())
    registry = build_scope_tool_registry(retriever)

    result = registry.run("search_company_scope", {"query": "工业设备制造", "k": 3})

    assert result.status == "ok"
    assert result.permission_tier == "read_private"
    assert result.data["hits"][0]["text"] == "工业设备制造"
    assert result.data["hits"][0]["legal_name"] == "示例科技股份有限公司"
