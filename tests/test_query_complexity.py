from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.query_complexity import classify_complexity, classify_heuristic


def _repo(company_database_path):
    return CompanyRepository(company_database_path)


def test_heuristic_named_verify_is_simple(company_database_path):
    result = classify_heuristic("核验示例科技股份有限公司", _repo(company_database_path))
    assert result.level == "simple"
    assert result.method == "heuristic"


def test_heuristic_capability_is_simple(company_database_path):
    result = classify_heuristic("哪些企业能做注塑成型", _repo(company_database_path))
    assert result.level == "simple"


def test_heuristic_capability_with_relationship_is_medium(company_database_path):
    result = classify_heuristic("哪些做注塑的供应商互相关联", _repo(company_database_path))
    assert result.level == "medium"


def test_heuristic_named_with_relationship_is_complex(company_database_path):
    result = classify_heuristic(
        "示例科技股份有限公司的最终实控人是谁", _repo(company_database_path)
    )
    assert result.level == "complex"


def test_classify_complexity_uses_llm_when_valid(company_database_path):
    result = classify_complexity("随便", _repo(company_database_path), llm=lambda q: "complex")
    assert result.level == "complex"
    assert result.method == "llm"


def test_classify_complexity_falls_back_on_llm_none_invalid_or_error(company_database_path):
    repo = _repo(company_database_path)
    query = "核验示例科技股份有限公司"
    assert classify_complexity(query, repo, llm=lambda q: None).method == "heuristic"
    assert classify_complexity(query, repo, llm=lambda q: "weird").method == "heuristic"

    def boom(q):
        raise RuntimeError("llm down")

    assert classify_complexity(query, repo, llm=boom).method == "heuristic"
