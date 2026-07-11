import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

GOLDEN = Path("evals/procurement/scope_recall.synthetic.yaml")


@pytest.mark.slow
def test_scope_runner_on_synthetic_golden(company_database_path, tmp_path):
    from build_scope_index import build_scope_index
    from deepresearch_agent.eval.runner import load_scope_cases, run_scope_recall
    from deepresearch_agent.rag.embedding import BgeEmbedder
    from deepresearch_agent.rag.retriever import load_scope_retriever

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, BgeEmbedder())
    retriever = load_scope_retriever(company_database_path, index_path, BgeEmbedder())

    cases = load_scope_cases(GOLDEN)
    metrics = run_scope_recall(retriever, cases)

    assert metrics.total == 1
    assert metrics.mean_recall_at_k == 1.0  # 期望企业应被召回进 top-10
