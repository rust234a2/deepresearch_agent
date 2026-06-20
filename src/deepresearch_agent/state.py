from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Recommendation = Literal["approve", "conditional", "reject", "insufficient_evidence"]


class SupplierResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    supplier_name: str | None = None
    matched_text: str | None = None
    match_type: Literal["legal_name", "alias"] | None = None
    candidates: list[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    legal_name: str
    country: str
    registration_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    registered_address: str | None = None
    operating_address: str | None = None
    website: str | HttpUrl | None = None
    status: str | None = None


class SupplierCapability(BaseModel):
    products: list[str] = Field(default_factory=list)
    delivery_capacity: str | None = None
    production_sites: int | None = Field(default=None, ge=0)
    monthly_capacity_units: int | None = Field(default=None, ge=0)
    minimum_order_quantity: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    supports_customization: bool | None = None


class ComplianceProfile(BaseModel):
    certifications: list[str] = Field(default_factory=list)
    sanctions_listed: bool = False
    blacklist_listed: bool = False
    listing_reason: str | None = None
    risk_summary: str | None = None
    administrative_penalties: list[str] = Field(default_factory=list)
    legal_cases: list[str] = Field(default_factory=list)
    negative_news: list[str] = Field(default_factory=list)


class FinancialProfile(BaseModel):
    revenue: float | None = Field(default=None, ge=0.0)
    currency: str | None = None
    fiscal_year: int | None = None
    credit_rating: str | None = None
    risk_summary: str | None = None


class ProcurementHistory(BaseModel):
    approved_supplier: bool | None = None
    historical_order_count: int | None = Field(default=None, ge=0)
    on_time_delivery_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_issue_count: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)


class SupplierDueDiligenceProfile(BaseModel):
    company: CompanyProfile
    capability: SupplierCapability
    compliance: ComplianceProfile
    financial: FinancialProfile = Field(default_factory=FinancialProfile)
    procurement_history: ProcurementHistory = Field(default_factory=ProcurementHistory)


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
    supplier_resolution: SupplierResolution | None = None
    iteration: int = 0
    max_iterations: int = 3
    plan: list[ResearchPlanItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    report: SupplierReport | None = None
    trace: list[ToolTrace] = Field(default_factory=list)
