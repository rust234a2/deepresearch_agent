from __future__ import annotations

from pathlib import Path

import yaml

from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.metrics import (
    entity_resolution_metrics,
    perturbation_metrics,
    scope_judged_metrics,
    scope_lexical_metrics,
    scope_recall_metrics,
)
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    PerturbationRobustnessMetrics,
    ScopeJudgedMetrics,
    ScopeLexicalMetrics,
    ScopeQueryCase,
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


def load_scope_query_cases(path: str | Path) -> list[ScopeQueryCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [ScopeQueryCase.model_validate(item) for item in data["cases"]]


def _lexical_tp(scopes: dict[str, str], query: str) -> set[str]:
    q = normalize_company_name(query)
    return {code for code, scope in scopes.items() if q in normalize_company_name(scope)}


def run_scope_lexical(
    retriever, repository: CompanyRepository, cases: list[ScopeQueryCase]
) -> ScopeLexicalMetrics:
    scopes = dict(repository.iter_business_scopes())
    retrieved_per_case: list[set[str]] = []
    lexical_tp_per_case: list[set[str]] = []
    for case in cases:
        retrieved = {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        retrieved_per_case.append(retrieved)
        lexical_tp_per_case.append(_lexical_tp(scopes, case.query))
    return scope_lexical_metrics(retrieved_per_case, lexical_tp_per_case)


def run_scope_judged(
    retriever, repository: CompanyRepository, judge, cases: list[ScopeQueryCase]
) -> ScopeJudgedMetrics:
    scopes = dict(repository.iter_business_scopes())
    retrieved_per_case: list[set[str]] = []
    judged_cover_per_case: list[set[str]] = []
    lexical_tp_per_case: list[set[str]] = []
    for case in cases:
        retrieved = {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        retrieved_per_case.append(retrieved)
        judged_cover_per_case.append(
            {code for code in retrieved if judge(case.query, scopes.get(code, ""))}
        )
        lexical_tp_per_case.append(_lexical_tp(scopes, case.query))
    return scope_judged_metrics(retrieved_per_case, judged_cover_per_case, lexical_tp_per_case)
