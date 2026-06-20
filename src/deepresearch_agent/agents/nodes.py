from __future__ import annotations

from deepresearch_agent.domain import DomainPack
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import (
    Citation,
    Evidence,
    ResearchPlanItem,
    ResearchState,
    SupplierReport,
    ToolTrace,
)
from deepresearch_agent.tools.base import ToolRegistry


_DIMENSION_QUESTIONS = {
    "supplier_profile": "What is {supplier_name}'s business profile?",
    "product_capability": "What product capability evidence exists for {supplier_name}?",
    "delivery_capability": "What delivery capacity evidence exists for {supplier_name}?",
    "compliance": "What certifications or restrictions apply to {supplier_name}?",
    "financial_stability": "What financial stability evidence exists for {supplier_name}?",
    "negative_news": "What negative news or risk signals exist for {supplier_name}?",
    "geopolitical_or_sanctions_risk": "What sanctions or geopolitical risks apply to {supplier_name}?",
}

_HIGH_PRIORITY_DIMENSIONS = {
    "supplier_profile",
    "compliance",
    "geopolitical_or_sanctions_risk",
}


def planner_node(state: ResearchState, domain_pack: DomainPack) -> ResearchState:
    supplier_name = _extract_supplier_name(state.question)
    state.supplier_name = supplier_name
    state.plan = [
        ResearchPlanItem(
            dimension=dimension,
            question=_question_for_dimension(dimension, supplier_name),
            priority=1 if dimension in _HIGH_PRIORITY_DIMENSIONS else 2,
        )
        for dimension in domain_pack.research_dimensions
    ]
    return state


def researcher_node(
    state: ResearchState,
    retriever: LocalDocumentRetriever,
    tools: ToolRegistry,
    domain_pack: DomainPack,
) -> ResearchState:
    if state.supplier_name is None:
        raise ValueError("planner_node must set supplier_name before researcher_node")

    if "extract_supplier_profile" in domain_pack.allowed_tools:
        profile_result = tools.run("extract_supplier_profile", {"supplier_name": state.supplier_name})
        state.trace.append(
            ToolTrace(
                tool_name=profile_result.name,
                args={"supplier_name": state.supplier_name},
                status=profile_result.status,
                latency_ms=profile_result.latency_ms,
                permission_tier=profile_result.permission_tier,
            )
        )
        if profile_result.status == "ok":
            data = profile_result.data
            state.evidence.append(
                Evidence(
                    claim=f"{state.supplier_name} supplies {', '.join(data['products'])}.",
                    dimension="supplier_profile",
                    confidence=0.8,
                    citation=Citation(
                        source_id=f"supplier_profile:{state.supplier_name.lower().replace(' ', '-')}",
                        title=f"{state.supplier_name} local supplier profile",
                        url=f"local://suppliers/{state.supplier_name.lower().replace(' ', '-')}",
                        snippet=data["risk_summary"],
                    ),
                ),
            )
            if data["certifications"]:
                state.evidence.append(
                    Evidence(
                        claim=f"{state.supplier_name} lists certifications: {', '.join(data['certifications'])}.",
                        dimension="compliance",
                        confidence=0.78,
                        citation=Citation(
                            source_id=f"supplier_profile:{state.supplier_name.lower().replace(' ', '-')}",
                            title=f"{state.supplier_name} local supplier profile",
                            url=f"local://suppliers/{state.supplier_name.lower().replace(' ', '-')}",
                            snippet=", ".join(data["certifications"]),
                        ),
                    ),
                )

    if "check_sanctions_or_blacklist" in domain_pack.allowed_tools:
        sanctions_result = tools.run("check_sanctions_or_blacklist", {"company_name": state.supplier_name})
        state.trace.append(
            ToolTrace(
                tool_name=sanctions_result.name,
                args={"company_name": state.supplier_name},
                status=sanctions_result.status,
                latency_ms=sanctions_result.latency_ms,
                permission_tier=sanctions_result.permission_tier,
            )
        )
        if sanctions_result.status == "ok":
            state.evidence.append(
                Evidence(
                    claim=f"Sanctions fixture listed={sanctions_result.data['listed']} for {state.supplier_name}.",
                    dimension="geopolitical_or_sanctions_risk",
                    confidence=0.9,
                    citation=Citation(
                        source_id=f"sanctions:{state.supplier_name.lower().replace(' ', '-')}",
                        title="Local sanctions fixture",
                        url="local://procurement/sanctions",
                        snippet=sanctions_result.data["reason"],
                    ),
                )
            )

    if "search_supplier_docs" in domain_pack.allowed_tools:
        for item in state.plan:
            for result in retriever.search(
                f"{state.supplier_name} {item.question}",
                limit=1,
                supplier_name=state.supplier_name,
            ):
                state.evidence.append(
                    Evidence(
                        claim=result.snippet,
                        dimension=item.dimension,
                        confidence=min(0.95, 0.55 + result.score),
                        citation=Citation(
                            source_id=result.source_id,
                            title=result.title,
                            url=result.url,
                            snippet=result.snippet,
                        ),
                    )
                )

    state.iteration += 1
    return state


def critique_node(state: ResearchState) -> ResearchState:
    covered = {item.dimension for item in state.evidence}
    required = {item.dimension for item in state.plan}
    state.missing_dimensions = sorted(required - covered)
    return state


def writer_node(state: ResearchState, domain_pack: DomainPack) -> ResearchState:
    if state.supplier_name is None:
        raise ValueError("supplier_name is required to write a report")

    has_sanctions_risk = any(
        item.dimension == "geopolitical_or_sanctions_risk" and "listed=True" in item.claim
        for item in state.evidence
    )
    if has_sanctions_risk:
        recommendation = "reject"
        summary = "Supplier should be rejected or escalated because a sanctions or blacklist risk was found."
    elif state.missing_dimensions:
        recommendation = "conditional"
        summary = "Supplier may be suitable, but some evidence dimensions require human follow-up."
    else:
        recommendation = "approve"
        summary = "Supplier appears suitable based on the local v1 evidence set."

    open_questions = [f"Collect more evidence for {dimension}." for dimension in state.missing_dimensions]
    if has_sanctions_risk and domain_pack.hitl_policy.high_risk_recommendation:
        open_questions.append("Human review required for high-risk recommendation.")
    if "compliance" in state.missing_dimensions and domain_pack.hitl_policy.missing_compliance_evidence:
        open_questions.append("Human review required because compliance evidence is missing.")

    state.report = SupplierReport(
        supplier_name=state.supplier_name,
        recommendation=recommendation,
        summary=summary,
        risks=_risk_lines(state),
        evidence_table=state.evidence,
        open_questions=open_questions,
    )
    return state


def _question_for_dimension(dimension: str, supplier_name: str) -> str:
    template = _DIMENSION_QUESTIONS.get(
        dimension,
        "What evidence exists for {supplier_name}'s " + dimension.replace("_", " ") + "?",
    )
    return template.format(supplier_name=supplier_name)


def _extract_supplier_name(question: str) -> str:
    known = ["ACME Sensors", "Northstar Components"]
    for supplier in known:
        if supplier.lower() in question.lower():
            return supplier
    return question.split(" for ")[0].replace("Assess ", "").strip()


def _risk_lines(state: ResearchState) -> list[str]:
    risks: list[str] = []
    for item in state.evidence:
        text = f"{item.claim} Source: {item.citation.title}."
        if "listed=True" in item.claim or "restriction" in item.citation.snippet.lower():
            risks.append(text)
    if state.missing_dimensions:
        risks.append(f"Missing evidence dimensions: {', '.join(state.missing_dimensions)}.")
    return risks or ["No high-risk signal found in the local v1 fixture set."]
