from __future__ import annotations

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import DomainPack
from deepresearch_agent.query_complexity import classify_complexity
from deepresearch_agent.state import (
    Citation,
    Evidence,
    GraphSearchCandidate,
    GraphSearchReport,
    ResearchPlanItem,
    ResearchState,
    ScopeCandidate,
    ScopeSearchReport,
    SharedControllerFinding,
    SupplierReport,
    ToolTrace,
)
from deepresearch_agent.supplier_resolution import resolve_supplier
from deepresearch_agent.tools.base import ToolRegistry


_DIMENSION_QUESTIONS = {
    "company_identity": "What is {supplier_name}'s registered identity?",
    "registration": "What is {supplier_name}'s registration status and history?",
    "capital": "What registered and paid-in capital data exists for {supplier_name}?",
    "industry_and_business_scope": "What industry and business scope is registered for {supplier_name}?",
    "enterprise_scale": "What enterprise scale and employee data exists for {supplier_name}?",
    "contact": "What source-backed contact data exists for {supplier_name}?",
    "ownership_structure": "What registered shareholders and outbound investments exist for {supplier_name}?",
    "related_parties": "What related parties can be inferred for {supplier_name} from shared ownership?",
}

_RELATION_LABELS = {
    "direct_shareholder": "直接股东",
    "direct_investee": "直接被投资",
    "shared_corporate_shareholder": "共同企业股东",
    "shared_person_shareholder": "共同自然人(疑似)",
    "shared_investee": "共同对外投资",
}


def planner_node(
    state: ResearchState,
    domain_pack: DomainPack,
    repository: CompanyRepository,
    llm=None,
) -> ResearchState:
    resolution = resolve_supplier(state.question, repository)
    state.supplier_resolution = resolution
    state.supplier_name = resolution.legal_name
    state.company_credit_code = resolution.unified_social_credit_code
    state.complexity = classify_complexity(state.question, repository, llm)
    if resolution.status != "resolved" or resolution.legal_name is None:
        state.plan = []
        return state

    state.plan = [
        ResearchPlanItem(
            dimension=dimension,
            question=_DIMENSION_QUESTIONS[dimension].format(
                supplier_name=resolution.legal_name
            ),
            priority=1 if dimension in {"company_identity", "registration"} else 2,
        )
        for dimension in domain_pack.research_dimensions
    ]
    return state


def researcher_node(
    state: ResearchState,
    tools: ToolRegistry,
    domain_pack: DomainPack,
) -> ResearchState:
    if state.supplier_name is None or state.company_credit_code is None:
        raise ValueError("planner_node must resolve a company before researcher_node")

    if "get_company_profile" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_company_profile",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_profile_evidence(state, result.data)

    if "get_company_contact" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_company_contact",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_contact_evidence(state, result.data)

    if "get_ownership_neighborhood" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_ownership_neighborhood",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_ownership_evidence(state, result.data)

    if "get_related_parties" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_related_parties",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_related_parties_evidence(state, result.data)

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

    open_questions = [
        f"补充当前数据源缺失的研究维度：{dimension}。"
        for dimension in state.missing_dimensions
    ]
    open_questions.extend(
        [
            "接入制裁和监管名单数据。",
            "接入司法案件与负面新闻数据。",
            "接入财务数据。",
            "接入产能、交期与质量认证数据。",
            "接入内部采购履约数据。",
        ]
    )
    open_questions.append(
        "股权关联方为线索级推断（尤其同名自然人），须人工复核，不构成控制关系或采购结论。"
    )
    state.report = SupplierReport(
        supplier_name=state.supplier_name,
        recommendation="insufficient_evidence",
        summary="已完成本地工商和联系方式核验；现有数据不足以作出采购批准或风险结论。",
        risks=[
            "当前数据源不包含制裁、司法、负面新闻、财务和采购履约数据，"
            "不能据此作出采购批准或风险结论。"
        ],
        evidence_table=state.evidence,
        open_questions=open_questions,
    )
    return state


SCOPE_SEARCH_K = 10

_SCOPE_OPEN_QUESTIONS = [
    "经营范围匹配仅为登记信息，不代表实际产能、交期或质量。",
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]


def scope_search_node(state: ResearchState, retriever) -> ResearchState:
    if retriever is None:
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary="经营范围语义检索不可用：请安装 .[rag] 可选依赖并运行 "
            "scripts/build_scope_index.py 构建索引。",
            candidates=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"],
        )
        return state

    try:
        hits = retriever.search(state.question, SCOPE_SEARCH_K)
    except Exception as exc:  # 检索期异常兜底为不可用报告
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary=f"经营范围语义检索失败：{exc}",
            candidates=[],
            open_questions=["检查 .[rag] 依赖与 FAISS 索引后重试。"],
        )
        return state

    candidates = _group_scope_hits(hits)
    if candidates:
        summary = (
            f"按经营范围语义检索到 {len(candidates)} 家候选企业；"
            "现有数据仅工商经营范围，不足以作出采购批准或风险结论。"
        )
    else:
        summary = "未检索到经营范围匹配的企业。"
    state.scope_report = ScopeSearchReport(
        query=state.question,
        summary=summary,
        candidates=candidates,
        open_questions=list(_SCOPE_OPEN_QUESTIONS),
    )
    return state


def _group_scope_hits(hits) -> list[ScopeCandidate]:
    grouped: dict[str, ScopeCandidate] = {}
    for hit in hits:
        evidence = Evidence(
            claim=hit.text,
            dimension="business_scope_match",
            confidence=min(max(hit.score, 0.0), 1.0),
            citation=Citation(
                source_id=f"company:{hit.unified_social_credit_code}",
                title=f"{hit.legal_name} 经营范围",
                url=f"local://companies/{hit.unified_social_credit_code}",
                snippet=hit.text,
            ),
        )
        candidate = grouped.get(hit.unified_social_credit_code)
        if candidate is None:
            grouped[hit.unified_social_credit_code] = ScopeCandidate(
                unified_social_credit_code=hit.unified_social_credit_code,
                legal_name=hit.legal_name,
                matched_clauses=[evidence],
                top_score=hit.score,
            )
        else:
            candidate.matched_clauses.append(evidence)
            candidate.top_score = max(candidate.top_score, hit.score)
    return list(grouped.values())


_GRAPH_OPEN_QUESTIONS = [
    "经营范围匹配仅为登记信息，不代表实际产能、交期或质量。",
    "共享控制人为线索级推断（尤其同名自然人），须人工复核，不构成围标认定。",
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]


def graph_search_node(state: ResearchState, searcher) -> ResearchState:
    if searcher is None:
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary="图谱关系检索不可用：请安装 .[rag] 可选依赖并构建 FAISS 经营范围索引与公司图谱。",
            candidates=[],
            shared_controllers=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 索引。"],
        )
        return state

    try:
        context = searcher(state.question)
    except Exception as exc:  # 检索期异常兜底为不可用报告
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary=f"图谱关系检索失败：{exc}",
            candidates=[],
            shared_controllers=[],
            open_questions=["检查 .[rag] 依赖、FAISS 索引与公司图谱后重试。"],
        )
        return state

    name_by_code = {seed.code: seed.name for seed in context.seeds}
    candidates = [
        GraphSearchCandidate(
            unified_social_credit_code=seed.code,
            legal_name=seed.name,
            top_score=seed.score,
            ultimate_controllers=[
                f"{controller.display_name}（疑·须人工复核）"
                if controller.via_person
                else controller.display_name
                for controller in seed.controllers
            ],
        )
        for seed in context.seeds
    ]
    shared = [
        SharedControllerFinding(
            controller_name=item.name,
            controlled_companies=[name_by_code.get(code, code) for code in item.controlled_seeds],
            via_person=item.via_person,
            note="经同名自然人推断，须人工复核" if item.via_person else "经企业股权链推断",
        )
        for item in context.shared_controllers
    ]
    if candidates:
        if shared:
            middle = f"其中 {len(shared)} 组疑似共享控制人（围标/集中度线索，须人工复核）；"
        else:
            middle = "未发现候选间共享控制人；"
        summary = (
            f"按经营范围语义检索到 {len(candidates)} 家候选；"
            + middle
            + "现有数据不足以作出采购批准或风险结论。"
        )
    else:
        summary = "未检索到经营范围匹配的企业。"
    state.graph_report = GraphSearchReport(
        query=state.question,
        summary=summary,
        candidates=candidates,
        shared_controllers=shared,
        open_questions=list(_GRAPH_OPEN_QUESTIONS),
    )
    return state


def _append_profile_evidence(state: ResearchState, data: dict) -> None:
    identity_parts = [
        f"法定名称：{data['legal_name']}",
        f"统一社会信用代码：{data['unified_social_credit_code']}",
    ]
    if data.get("aliases"):
        identity_parts.append(f"曾用名：{'、'.join(data['aliases'])}")
    _append_fact(state, "company_identity", "；".join(identity_parts), "；".join(identity_parts))

    registration_parts = _labeled_values(
        data,
        (
            ("registration_status", "登记状态"),
            ("legal_representative", "法定代表人"),
            ("company_type", "企业类型"),
            ("established_date", "成立日期"),
            ("registration_authority", "登记机关"),
        ),
    )
    if registration_parts:
        text = "；".join(registration_parts)
        _append_fact(state, "registration", text, text)

    capital_parts = _labeled_values(
        data,
        (
            ("registered_capital_original", "注册资本"),
            ("paid_in_capital_original", "实缴资本"),
        ),
    )
    if capital_parts:
        text = "；".join(capital_parts)
        _append_fact(state, "capital", text, text)

    industry_parts = _labeled_values(
        data,
        (
            ("gb_industry_section", "行业门类"),
            ("gb_industry_division", "行业大类"),
            ("gb_industry_group", "行业中类"),
            ("gb_industry_class", "行业小类"),
            ("business_scope", "经营范围"),
        ),
    )
    if industry_parts:
        text = "；".join(industry_parts)
        _append_fact(state, "industry_and_business_scope", text, data.get("business_scope") or text)

    scale_parts = _labeled_values(
        data,
        (
            ("enterprise_size", "企业规模"),
            ("employee_count", "参保人数"),
            ("employee_count_report_year", "参保人数年报年份"),
        ),
    )
    if scale_parts:
        text = "；".join(scale_parts)
        _append_fact(state, "enterprise_scale", text, text)


def _append_contact_evidence(state: ResearchState, data: dict) -> None:
    parts: list[str] = []
    if data.get("phones"):
        parts.append(f"电话：{'、'.join(data['phones'])}")
    if data.get("emails"):
        parts.append(f"邮箱：{'、'.join(data['emails'])}")
    if data.get("mailing_address"):
        parts.append(f"通信地址：{data['mailing_address']}")
    if parts:
        text = "；".join(parts)
        _append_fact(state, "contact", text, text)


def _append_ownership_evidence(state: ResearchState, data: dict) -> None:
    appended = False
    for shareholder in data.get("shareholders", []):
        parts = [f"股东：{shareholder['shareholder_name']}"]
        if shareholder.get("shareholder_type"):
            parts.append(f"类型：{shareholder['shareholder_type']}")
        if shareholder.get("shares_held"):
            parts.append(f"持股数：{shareholder['shares_held']}")
        text = "；".join(parts)
        _append_fact(state, "ownership_structure", text, text)
        appended = True
    for investment in data.get("investments", []):
        parts = [f"对外投资：{investment['investee_name']}"]
        if investment.get("status"):
            parts.append(f"状态：{investment['status']}")
        if investment.get("holding_pct"):
            parts.append(f"持股比例：{investment['holding_pct']}")
        text = "；".join(parts)
        _append_fact(state, "ownership_structure", text, text)
        appended = True
    if not appended:
        text = f"数据源未提供 {state.supplier_name} 的股东或对外投资数据。"
        _append_fact(state, "ownership_structure", text, text)


def _append_related_parties_evidence(state: ResearchState, data: dict) -> None:
    parties = data.get("related_parties", [])
    if not parties:
        text = f"数据源未发现 {state.supplier_name} 的可推断关联方。"
        _append_fact(state, "related_parties", text, text)
        return
    for party in parties:
        label = _RELATION_LABELS.get(party["relation_type"], party["relation_type"])
        claim = f"关联方：{party['related_name']}（{label}）。{party['reliability_note']}"
        _append_evidence(
            state,
            Evidence(
                claim=claim,
                dimension="related_parties",
                confidence=party["confidence"],
                citation=Citation(
                    source_id=f"company:{state.company_credit_code}",
                    title=f"{state.supplier_name} 股权关联",
                    url=f"local://companies/{state.company_credit_code}",
                    snippet=party["reliability_note"],
                ),
            ),
        )


def _append_fact(state: ResearchState, dimension: str, claim: str, snippet: str) -> None:
    _append_evidence(
        state,
        Evidence(
            claim=claim,
            dimension=dimension,
            confidence=0.95,
            citation=Citation(
                source_id=f"company:{state.company_credit_code}",
                title=f"{state.supplier_name} 工商数据",
                url=f"local://companies/{state.company_credit_code}",
                snippet=snippet,
            ),
        ),
    )


def _labeled_values(data: dict, fields: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"{label}：{data[key]}" for key, label in fields if data.get(key) not in (None, "", [])]


def _write_unresolved_supplier_report(state: ResearchState) -> ResearchState:
    resolution = state.supplier_resolution
    if resolution is not None and resolution.status == "ambiguous":
        candidates = "、".join(item.legal_name for item in resolution.candidates)
        summary = f"匹配到多家企业：{candidates}。必须指定单一企业。"
        question = f"请从以下企业中指定一家：{candidates}。"
    else:
        summary = "未能从本地企业数据库识别供应商。"
        question = "请提供数据库中存在的企业法定名称或曾用名。"
    state.report = SupplierReport(
        supplier_name="Unknown supplier",
        recommendation="insufficient_evidence",
        summary=summary,
        risks=["企业身份未解析，未启动工商核验。"],
        evidence_table=[],
        open_questions=[question],
    )
    return state


def _run_tool(state: ResearchState, tools: ToolRegistry, name: str, args: dict):
    if any(item.tool_name == name and item.args == args for item in state.trace):
        return None
    try:
        result = tools.run(name, args)
    except Exception as exc:
        state.trace.append(
            ToolTrace(
                tool_name=name,
                args=args,
                status="error",
                latency_ms=0,
                permission_tier="unavailable",
                error=str(exc),
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
            error=result.data.get("error") if result.status == "error" else None,
        )
    )
    return result


def _append_evidence(state: ResearchState, evidence: Evidence) -> None:
    key = (evidence.dimension, evidence.citation.source_id, evidence.claim)
    existing = {
        (item.dimension, item.citation.source_id, item.claim) for item in state.evidence
    }
    if key not in existing:
        state.evidence.append(evidence)
