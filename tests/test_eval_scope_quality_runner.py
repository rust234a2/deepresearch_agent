from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.models import ScopeQueryCase
from deepresearch_agent.eval.runner import (
    load_scope_query_cases,
    run_scope_judged,
    run_scope_lexical,
)

_CODE = "91330000123456789X"


class _FakeHit:
    def __init__(self, code):
        self.unified_social_credit_code = code


class _FakeRetriever:
    def __init__(self, by_query):
        self._by_query = by_query

    def search(self, query, k):
        return [_FakeHit(c) for c in self._by_query.get(query, [])][:k]


def test_load_scope_query_cases_reads_yaml():
    cases = load_scope_query_cases("evals/procurement/scope_queries.synthetic.yaml")
    assert cases and cases[0].query == "工业设备"
    assert cases[0].k == 10


def test_run_scope_lexical_hits_fixture_scope(company_database_path):
    repo = CompanyRepository(company_database_path)
    cases = [ScopeQueryCase(case_id="q1", query="工业设备", k=10)]
    retriever = _FakeRetriever({"工业设备": [_CODE]})

    m = run_scope_lexical(retriever, repo, cases)

    assert m.total == 1
    assert m.mean_lexical_precision_at_k == 1.0
    assert m.mean_lexical_recall_at_k == 1.0
    assert m.mean_lexical_tp_count == 1.0


def test_run_scope_judged_semantic_gain_over_non_lexical(company_database_path):
    repo = CompanyRepository(company_database_path)
    # "注塑成型" 不在 fixture 经营范围原文里（词面不命中），但假判官说覆盖 → 语义增益
    cases = [ScopeQueryCase(case_id="q1", query="注塑成型", k=10)]
    retriever = _FakeRetriever({"注塑成型": [_CODE]})

    m = run_scope_judged(retriever, repo, lambda q, scope: True, cases)

    assert m.mean_judged_precision_at_k == 1.0
    assert m.mean_noise_at_k == 0.0
    assert m.mean_semantic_gain_at_k == 1.0  # judged 1.0 − lexical 0.0
