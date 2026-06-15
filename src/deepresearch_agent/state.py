from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Recommendation = Literal["approve", "conditional", "reject", "insufficient_evidence"]


class Citation(BaseModel):
    source_id: str
    title: str
    url: str | HttpUrl
    snippet: str


class Evidence(BaseModel):
    claim: str
    dimension: str
    confidence: float = Field(ge=0.0, le=1.0)
    citation: Citation


class ResearchPlanItem(BaseModel):
    dimension: str
    question: str
    priority: int = Field(ge=1, le=5)


class ToolTrace(BaseModel):
    tool_name: str
    args: dict
    status: Literal["ok", "error"]
    latency_ms: int
    permission_tier: str


class SupplierReport(BaseModel):
    supplier_name: str
    recommendation: Recommendation
    summary: str
    risks: list[str]
    evidence_table: list[Evidence]
    open_questions: list[str]


class ResearchState(BaseModel):
    question: str
    domain: str
    supplier_name: str | None = None
    iteration: int = 0
    max_iterations: int = 3
    plan: list[ResearchPlanItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    report: SupplierReport | None = None
    trace: list[ToolTrace] = Field(default_factory=list)
