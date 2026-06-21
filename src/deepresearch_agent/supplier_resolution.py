from __future__ import annotations

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.company_repository import CompanyRepository


def resolve_supplier(
    question: str,
    repository: CompanyRepository,
) -> CompanyResolution:
    return repository.resolve_text(question)
