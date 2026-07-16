from __future__ import annotations

from pathlib import Path

import yaml

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.metrics import (
    entity_resolution_metrics,
    perturbation_metrics,
    scope_recall_metrics,
)
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    PerturbationRobustnessMetrics,
    ScopeRecallMetrics,
)
from deepresearch_agent.supplier_resolution import resolve_supplier


def load_entity_cases(path: str | Path) -> list[GoldenEntityCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenEntityCase.model_validate(item) for item in data["cases"]]


def load_scope_cases(path: str | Path) -> list[GoldenScopeCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenScopeCase.model_validate(item) for item in data["cases"]]


def run_entity_resolution(
    repository: CompanyRepository, cases: list[GoldenEntityCase]
) -> EntityResolutionMetrics:
    resolutions = [resolve_supplier(case.question, repository) for case in cases]
    return entity_resolution_metrics(cases, resolutions)


def run_scope_recall(retriever, cases: list[GoldenScopeCase]) -> ScopeRecallMetrics:
    retrieved_per_case = [
        {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        for case in cases
    ]
    return scope_recall_metrics(cases, retrieved_per_case)


def run_perturbation_robustness(
    repository: CompanyRepository, cases: list[GoldenEntityCase]
) -> PerturbationRobustnessMetrics:
    resolutions = [resolve_supplier(case.question, repository) for case in cases]
    return perturbation_metrics(cases, resolutions)
