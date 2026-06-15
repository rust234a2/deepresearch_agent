from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class HitlPolicy(BaseModel):
    high_risk_recommendation: bool
    missing_compliance_evidence: bool
    conflicting_claims: bool


class DomainPack(BaseModel):
    name: str
    description: str
    research_dimensions: list[str]
    allowed_tools: list[str]
    report_sections: list[str]
    source_priority: list[str]
    hitl_policy: HitlPolicy


def load_domain_pack(path: Path) -> DomainPack:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DomainPack.model_validate(data)
