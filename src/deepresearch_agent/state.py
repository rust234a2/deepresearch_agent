from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.query_complexity import ComplexityResult


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
    error: str | None = None


class SupplierReport(BaseModel):
    supplier_name: str
    recommendation: Recommendation
    summary: str
    risks: list[str]
    evidence_table: list[Evidence]
    open_questions: list[str]


class ScopeCandidate(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    matched_clauses: list[Evidence]
    top_score: float


class ScopeSearchReport(BaseModel):
    query: str
    recommendation: Recommendation = "insufficient_evidence"
    summary: str
    candidates: list[ScopeCandidate]
    open_questions: list[str]


class GraphSearchCandidate(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    top_score: float
    ultimate_controllers: list[str]


class SharedControllerFinding(BaseModel):
    controller_name: str
    controlled_companies: list[str]
    via_person: bool
    note: str
    concentrated_industries: list[str] = []


class GraphSearchReport(BaseModel):
    query: str
    recommendation: Recommendation = "insufficient_evidence"
    summary: str
    candidates: list[GraphSearchCandidate]
    shared_controllers: list[SharedControllerFinding]
    open_questions: list[str]


class ResearchState(BaseModel):
    question: str
    domain: str
    supplier_name: str | None = None
    company_credit_code: str | None = None
    supplier_resolution: CompanyResolution | None = None
    preresolved: CompanyResolution | None = None
    iteration: int = 0
    max_iterations: int = 3
    plan: list[ResearchPlanItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    report: SupplierReport | None = None
    scope_report: ScopeSearchReport | None = None
    graph_report: GraphSearchReport | None = None
    trace: list[ToolTrace] = Field(default_factory=list)
    complexity: ComplexityResult | None = None
    retrieval_mode: Literal["named", "scope", "graph", "unresolved"] | None = None
    retrieval_available: bool = True
    scope_candidates: list[ScopeCandidate] = Field(default_factory=list)
    graph_candidates: list[GraphSearchCandidate] = Field(default_factory=list)
    shared_controllers: list[SharedControllerFinding] = Field(default_factory=list)
    degradations: list[str] = Field(default_factory=list)
