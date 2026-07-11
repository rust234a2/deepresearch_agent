from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GoldenEntityCase(BaseModel):
    case_id: str
    question: str
    expected_status: Literal["resolved", "ambiguous", "not_found"]
    expected_code: str | None = None
    expected_candidate_codes: list[str] = Field(default_factory=list)


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
