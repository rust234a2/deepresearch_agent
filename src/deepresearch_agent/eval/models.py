from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GoldenEntityCase(BaseModel):
    case_id: str
    question: str
    expected_status: Literal["resolved", "ambiguous", "not_found"]
    expected_code: str | None = None
    expected_candidate_codes: list[str] = Field(default_factory=list)
    perturbation_type: str | None = None


class GoldenScopeCase(BaseModel):
    case_id: str
    query: str
    expected_codes: list[str]
    k: int = 10


class EntityResolutionMetrics(BaseModel):
    total: int
    accuracy: float
    resolved_precision: float
    resolved_recall: float


class ScopeRecallMetrics(BaseModel):
    total: int
    mean_recall_at_k: float
    mean_precision_at_k: float


class PerturbationTypeMetrics(BaseModel):
    perturbation_type: str
    n: int
    recovery: float
    wrong: float
    miss: float


class PerturbationRobustnessMetrics(BaseModel):
    total: int
    overall_recovery: float
    per_type: list[PerturbationTypeMetrics]


class ScopeQueryCase(BaseModel):
    case_id: str
    query: str
    k: int = 10


class ScopeLexicalMetrics(BaseModel):
    total: int
    mean_lexical_precision_at_k: float
    mean_lexical_recall_at_k: float
    mean_lexical_tp_count: float


class ScopeJudgedMetrics(BaseModel):
    total: int
    mean_judged_precision_at_k: float
    mean_noise_at_k: float
    mean_semantic_gain_at_k: float
