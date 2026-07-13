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
    "shared_person_shareholder": "共同自然人",
    "shared_investee": "共同对外投资",
}

_DIMENSION_KEYWORDS = {
    "company_identity": ("工商", "基本信息", "主体信息", "统一社会信用代码", "信用代码", "曾用名"),
    "registration": ("工商", "登记", "注册状态", "法定代表人", "法人", "成立日期", "登记机关"),
    "capital": ("注册资本", "实缴资本", "注册资金", "实收资本"),
    "industry_and_business_scope": ("经营范围", "业务范围", "行业", "主营", "经营业务"),
    "enterprise_scale": ("企业规模", "规模", "员工", "参保人数"),
    "contact": ("联系方式", "电话", "邮箱", "地址", "联系"),
    "ownership_structure": ("股东", "股权", "持股", "控股", "对外投资", "投资关系"),
    "related_parties": ("关联方", "关联企业", "关联公司", "关联关系"),
}

_DIMENSION_LABELS = {
    "company_identity": "主体身份",
    "registration": "工商登记",
    "capital": "注册资本",
    "industry_and_business_scope": "行业与经营范围",
    "enterprise_scale": "企业规模",
    "contact": "联系方式",
    "ownership_structure": "股权结构",
    "related_parties": "关联方线索",
}

_FULL_RESEARCH_KEYWORDS = ("全面核验", "完整核验", "全方位", "尽调", "所有信息", "全部信息")


def planner_node(
    state: ResearchState,
    domain_pack: DomainPack,
    repository: CompanyRepository,
    llm=None,
) -> ResearchState:
    resolution = resolve_supplier(state.question, repository)
    if resolution.status == "not_found" and state.preresolved is not None:
        resolution = state.preresolved
    state.supplier_resolution = resolution
    state.supplier_name = resolution.legal_name
    state.company_credit_code = resolution.unified_social_credit_code
    state.complexity = classify_complexity(state.question, repository, llm)
    if resolution.status != "resolved" or resolution.legal_name is None:
        state.plan = []
        return state

    requested_dimensions = _select_plan_dimensions(state.question, domain_pack.research_dimensions)
    state.plan = [
        ResearchPlanItem(
            dimension=dimension,
            question=_DIMENSION_QUESTIONS[dimension].format(
                supplier_name=resolution.legal_name
            ),
            priority=1 if dimension in {"company_identity", "registration"} else 2,
        )
        for dimension in requested_dimensions
    ]
    return state


def _select_plan_dimensions(question: str, available_dimensions: list[str]) -> list[str]:
    """Select only the research dimensions explicitly requested by the user."""
    if any(keyword in question for keyword in _FULL_RESEARCH_KEYWORDS):
        return list(available_dimensions)

    requested = {
        dimension
        for dimension, keywords in _DIMENSION_KEYWORDS.items()
        if dimension in available_dimensions and any(keyword in question for keyword in keywords)
    }
    if not requested:
        return list(available_dimensions)
    return [dimension for dimension in available_dimensions if dimension in requested]


def researcher_node(
    state: ResearchState,
    tools: ToolRegistry,
    domain_pack: DomainPack,
    scope_retriever=None,
    graph_searcher=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
) -> ResearchState:
    mode = _decide_retrieval_mode(
        state, scope_retriever, graph_searcher, scope_enabled, graph_enabled
    )
    state.retrieval_mode = mode
    if mode == "named":
        _research_named(state, tools, domain_pack)
    elif mode == "scope":
        _retrieve_scope(state, scope_retriever)
    elif mode == "graph":
        graph_error = _retrieve_graph(state, graph_searcher)
        if graph_error:
            if scope_retriever is not None:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，已降级为经营范围检索。"
                )
                state.retrieval_mode = "scope"
                state.retrieval_available = True
                _retrieve_scope(state, scope_retriever)
            else:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，无可用降级路径。"
                )
    return state


def _decide_retrieval_mode(
    state: ResearchState,
    scope_retriever,
    graph_searcher,
    scope_enabled: bool,
    graph_enabled: bool,
) -> str:
    resolution = state.supplier_resolution
    status = resolution.status if resolution is not None else "not_found"
    if status == "resolved":
        return "named"
    if status == "ambiguous":
        return "unresolved"
    level = state.complexity.level if state.complexity is not None else "simple"
    want_graph = graph_enabled and level in {"medium", "complex"}
    if want_graph and graph_searcher is not None:
        return "graph"
    if want_graph and scope_retriever is not None:
        return "scope"  # 想用图但 searcher 缺失且 scope 可用 → 退到 scope
    if scope_enabled:
        return "scope"
    if want_graph:
        return "graph"  # 图已启用但检索器均未加载 → 交给 writer 出"不可用"图报告
    return "unresolved"


def _research_named(state: ResearchState, tools: ToolRegistry, domain_pack: DomainPack) -> None:
    if state.supplier_name is None or state.company_credit_code is None:
        raise ValueError("planner_node must resolve a company before researcher_node")

    requested_dimensions = {item.dimension for item in state.plan}
    profile_dimensions = {
        "company_identity",
        "registration",
        "capital",
        "industry_and_business_scope",
        "enterprise_scale",
    }

    if requested_dimensions & profile_dimensions and "get_company_profile" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_company_profile", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_profile_evidence(state, result.data)

    if "contact" in requested_dimensions and "get_company_contact" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_company_contact", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_contact_evidence(state, result.data)

    if "ownership_structure" in requested_dimensions and "get_ownership_neighborhood" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_ownership_neighborhood", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_ownership_evidence(state, result.data)

    if "related_parties" in requested_dimensions and "get_related_parties" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_related_parties", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_related_parties_evidence(state, result.data)

    state.evidence = [
        evidence for evidence in state.evidence if evidence.dimension in requested_dimensions
    ]
    state.iteration += 1


def _retrieve_scope(state: ResearchState, retriever) -> None:
    if retriever is None:
        state.retrieval_available = False
        return
    try:
        hits = retriever.search(state.question, SCOPE_SEARCH_K)
    except Exception as exc:
        state.retrieval_available = False
        state.degradations.append(f"经营范围检索运行时失败：{exc}。")
        return
    state.scope_candidates = _group_scope_hits(hits)


def _retrieve_graph(state: ResearchState, searcher) -> str | None:
    if searcher is None:
        state.retrieval_available = False
        return None
    try:
        context = searcher(state.question)
    except Exception as exc:
        state.retrieval_available = False
        return str(exc)
    candidates, shared = _build_graph_findings(context)
    state.graph_candidates = candidates
    state.shared_controllers = shared
    return None


def _build_graph_findings(context):
    name_by_code = {seed.code: seed.name for seed in context.seeds}
    candidates = [
        GraphSearchCandidate(
            unified_social_credit_code=seed.code,
            legal_name=seed.name,
            top_score=seed.score,
            ultimate_controllers=[controller.display_name for controller in seed.controllers],
        )
        for seed in context.seeds
    ]
    shared = []
    for item in context.shared_controllers:
        if item.concentrated_industries:
            note = f"同行业（{'、'.join(item.concentrated_industries)}）+同控制人"
        elif item.via_person:
            note = "经自然人节点关联"
        else:
            note = "经企业股权链关联"
        shared.append(
            SharedControllerFinding(
                controller_name=item.name,
                controlled_companies=[name_by_code.get(code, code) for code in item.controlled_seeds],
                via_person=item.via_person,
                note=note,
                concentrated_industries=item.concentrated_industries,
            )
        )
    return candidates, shared


def critique_node(state: ResearchState) -> ResearchState:
    covered = {item.dimension for item in state.evidence}
    required = {item.dimension for item in state.plan}
    state.missing_dimensions = sorted(required - covered)
    return state


def writer_node(state: ResearchState, domain_pack: DomainPack) -> ResearchState:
    if state.retrieval_mode == "scope":
        return _write_scope_report(state)
    if state.retrieval_mode == "graph":
        return _write_graph_report(state)
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
    state.report = SupplierReport(
        supplier_name=state.supplier_name,
        recommendation="insufficient_evidence",
        summary=_requested_dimension_summary(state),
        risks=[
            "当前数据源不包含制裁、司法、负面新闻、财务和采购履约数据，"
            "不能据此作出采购批准或风险结论。"
        ],
        evidence_table=state.evidence,
        open_questions=open_questions,
    )
    return state


def _requested_dimension_summary(state: ResearchState) -> str:
    requested = [item.dimension for item in state.plan]
    labels = "、".join(_DIMENSION_LABELS.get(item, item) for item in requested)
    paragraphs = [f"已按你的问题核验{labels}。"]
    for dimension in requested:
        claims = [item.claim for item in state.evidence if item.dimension == dimension]
        if claims:
            paragraphs.append(_natural_dimension_paragraph(dimension, claims))
    paragraphs.append(
        "以上仅依据当前本地工商登记与联系方式数据；未接入制裁、司法、负面新闻、财务、产能、交期、认证或采购履约数据，不能据此作出采购批准或风险结论。"
    )
    return "\n\n".join(paragraphs)


def _natural_dimension_paragraph(dimension: str, claims: list[str]) -> str:
    claim = "；".join(claims)
    replacements = {
        "法定名称：": "法定名称为",
        "；统一社会信用代码：": "，统一社会信用代码为",
        "；曾用名：": "；曾用名包括",
        "登记状态：": "登记状态为",
        "；法定代表人：": "，法定代表人为",
        "；企业类型：": "，企业类型为",
        "；成立日期：": "，成立于",
        "；登记机关：": "，登记机关为",
        "注册资本：": "注册资本为",
        "；实缴资本：": "，实缴资本为",
        "行业门类：": "所在行业门类为",
        "；行业大类：": "，行业大类为",
        "；行业中类：": "，行业中类为",
        "；行业小类：": "，行业小类为",
        "；经营范围：": "。登记经营范围包括：",
    }
    for source, target in replacements.items():
        claim = claim.replace(source, target)

    prefixes = {
        "company_identity": "该企业的",
        "registration": "工商登记显示，该企业",
        "capital": "资本信息显示，该企业",
        "industry_and_business_scope": "按登记信息，该企业",
        "enterprise_scale": "企业规模信息显示，",
        "contact": "可查到的联系方式为：",
        "ownership_structure": "登记股权信息显示，",
        "related_parties": "关联方线索显示，",
    }
    return prefixes.get(dimension, "核验结果显示，") + claim + "。"


def _write_scope_report(state: ResearchState) -> ResearchState:
    if not state.retrieval_available:
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary="经营范围语义检索不可用：请安装 .[rag] 可选依赖并运行 "
            "scripts/build_scope_index.py 构建索引。",
            candidates=[],
            open_questions=list(state.degradations)
            + ["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"],
        )
        return state
    candidates = state.scope_candidates
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
        open_questions=list(state.degradations) + list(_SCOPE_OPEN_QUESTIONS),
    )
    return state


def _write_graph_report(state: ResearchState) -> ResearchState:
    if not state.retrieval_available:
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary="图谱关系检索不可用：请安装 .[rag] 可选依赖并构建 FAISS 经营范围索引与公司图谱。",
            candidates=[],
            shared_controllers=[],
            open_questions=list(state.degradations) + ["安装 .[rag] 可选依赖并构建 FAISS 索引。"],
        )
        return state
    candidates = state.graph_candidates
    shared = state.shared_controllers
    if candidates:
        if shared:
            collusion = sum(1 for s in shared if s.concentrated_industries)
            middle = f"其中 {len(shared)} 组共享关联；"
            if collusion:
                middle += f"其中 {collusion} 组同行业+同控制人关联；"
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
        open_questions=list(state.degradations) + list(_GRAPH_OPEN_QUESTIONS),
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
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]


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
        summary = f"根据当前名称线索匹配到多家企业：{candidates}。请指定其中一家后再继续核验。"
        question = f"请从以下企业中指定一家：{candidates}。"
    else:
        summary = "未能从本地企业数据库识别供应商。"
        question = "请提供数据库中存在的企业法定名称或曾用名。"
    state.report = SupplierReport(
        supplier_name="待确认企业" if resolution is not None and resolution.status == "ambiguous" else "未识别企业",
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
