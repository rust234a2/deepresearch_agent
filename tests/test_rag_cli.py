import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag import cli
from deepresearch_agent.rag.embedding import FakeEmbedder


def test_cli_prints_ranked_company_and_clause(company_database_path, tmp_path, capsys):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")

    cli.main(
        [
            "工业设备制造",
            "--k", "3",
            "--database", str(company_database_path),
            "--index", str(index_path),
        ],
        embedder=FakeEmbedder(),
    )

    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "工业设备制造" in out
