from pathlib import Path

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.runner import load_entity_cases, run_entity_resolution

GOLDEN = Path("evals/procurement/entity_resolution.synthetic.yaml")


def test_entity_runner_on_synthetic_golden(company_database_path):
    repository = CompanyRepository(company_database_path)
    cases = load_entity_cases(GOLDEN)

    metrics = run_entity_resolution(repository, cases)

    assert metrics.total == 3
    assert metrics.accuracy == 1.0
    assert metrics.resolved_precision == 1.0
    assert metrics.resolved_recall == 1.0
