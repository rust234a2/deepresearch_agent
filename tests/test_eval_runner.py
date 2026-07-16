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


def test_perturbation_runner_on_synthetic_golden(company_database_path):
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        run_perturbation_robustness,
    )

    repository = CompanyRepository(company_database_path)
    cases = load_entity_cases("evals/procurement/perturbation.synthetic.yaml")

    m = run_perturbation_robustness(repository, cases)

    assert m.total == 3
    by_type = {t.perturbation_type: t for t in m.per_type}
    assert by_type["drop_suffix"].recovery == 1.0
    assert by_type["noise_wrap"].recovery == 1.0
    assert by_type["transpose"].miss == 1.0     # 短词干对调 → not_found
    assert m.overall_recovery == 2 / 3
