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
from deepresearch_agent.supplier_resolution import resolve_supplier
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
    resolution = resolve_supplier(state.question)
    state.supplier_resolution = resolution
    state.supplier_name = resolution.supplier_name
    if resolution.status != "resolved" or resolution.supplier_name is None:
        state.plan = []
        return state

    supplier_name = resolution.supplier_name
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
        profile_result = _run_tool(
            state,
            tools,
            "extract_supplier_profile",
            {"supplier_name": state.supplier_name},
        )
        if profile_result is not None and profile_result.status == "ok":
            data = profile_result.data
            _append_evidence(
                state,
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
                _append_evidence(
                    state,
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
        sanctions_result = _run_tool(
            state,
            tools,
            "check_sanctions_or_blacklist",
            {"company_name": state.supplier_name},
        )
        if sanctions_result is not None and sanctions_result.status == "ok":
            _append_evidence(
                state,
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
        plan_items = state.plan
        if state.iteration > 0:
            plan_items = [item for item in state.plan if item.dimension in state.missing_dimensions]
        for item in plan_items:
            for result in retriever.search(
                f"{state.supplier_name} {item.question}",
                limit=1,
                supplier_name=state.supplier_name,
            ):
                _append_evidence(
                    state,
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
        return _write_unresolved_supplier_report(state)

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


def _write_unresolved_supplier_report(state: ResearchState) -> ResearchState:
    resolution = state.supplier_resolution
    if resolution is not None and resolution.status == "ambiguous":
        candidates = ", ".join(resolution.candidates)
        summary = f"Multiple preset suppliers were found: {candidates}. A single supplier is required."
        question = f"Please specify one supplier from: {candidates}."
    else:
        summary = "No supplier in the preset dataset could be identified from the question."
        question = "Please provide a supplier name available in the preset dataset."

    state.report = SupplierReport(
        supplier_name="Unknown supplier",
        recommendation="insufficient_evidence",
        summary=summary,
        risks=["Supplier identity is unresolved; due diligence was not started."],
        evidence_table=[],
        open_questions=[question],
    )
    return state


def _run_tool(state: ResearchState, tools: ToolRegistry, name: str, args: dict):
    if any(item.tool_name == name and item.args == args for item in state.trace):
        return None

    try:
        result = tools.run(name, args)
    except Exception:
        state.trace.append(
            ToolTrace(
                tool_name=name,
                args=args,
                status="error",
                latency_ms=0,
                permission_tier="unavailable",
            )
        )
        return None

    state.trace.append(
        ToolTrace(
            tool_name=result.name,
            args=args,
            status=result.status,
            latency_ms=result.latency_ms,
            permission_tier=result.permission_tier,
        )
    )
    return result


def _append_evidence(state: ResearchState, evidence: Evidence) -> None:
    key = (evidence.dimension, evidence.citation.source_id, evidence.claim)
    existing_keys = {
        (item.dimension, item.citation.source_id, item.claim)
        for item in state.evidence
    }
    if key not in existing_keys:
        state.evidence.append(evidence)


def _risk_lines(state: ResearchState) -> list[str]:
    risks: list[str] = []
    for item in state.evidence:
        text = f"{item.claim} Source: {item.citation.title}."
        if "listed=True" in item.claim or "restriction" in item.citation.snippet.lower():
            risks.append(text)
    if state.missing_dimensions:
        risks.append(f"Missing evidence dimensions: {', '.join(state.missing_dimensions)}.")
    return risks or ["No high-risk signal found in the local v1 fixture set."]
