from __future__ import annotations

from deepresearch_agent.company_models import (
    RelatedParty,
    RelatedPartyConfig,
    RelationType,
)
from deepresearch_agent.company_repository import CompanyRepository


DEFAULT_CONFIG = RelatedPartyConfig()

_RELATION_CONFIDENCE: dict[RelationType, float] = {
    "direct_shareholder": 0.9,
    "direct_investee": 0.9,
    "shared_corporate_shareholder": 0.5,
    "shared_person_shareholder": 0.2,
    "shared_investee": 0.25,
}


def _is_noise(node_name: str, degree: int, cap: int, keywords: tuple[str, ...]) -> bool:
    if degree > cap:
        return True
    return any(keyword in node_name for keyword in keywords)


def _reliability_note(
    relation_type: RelationType,
    anchor_name: str,
    related_name: str,
    via_node: str | None,
    degree: int | None,
) -> str:
    if relation_type == "direct_shareholder":
        return f"登记直接持股关系：{related_name} 持有 {anchor_name}。"
    if relation_type == "direct_investee":
        return f"登记直接投资关系：{anchor_name} 投资 {related_name}。"
    if relation_type == "shared_corporate_shareholder":
        return f"经由共同企业股东「{via_node}」推断的关联，需人工核实是否构成共同控制。"
    if relation_type == "shared_person_shareholder":
        return (
            f"经由同名自然人「{via_node}」关联（该姓名共连接 {degree} 家库内公司），"
            "疑似重名，信息不可靠，须人工复核确认是否同一人。"
        )
    return f"经由共同对外投资「{via_node}」推断的弱关联，合资不等于同一控制。"


def find_related_parties(
    repository: CompanyRepository,
    code: str,
    config: RelatedPartyConfig = DEFAULT_CONFIG,
) -> list[RelatedParty]:
    anchor = code.strip()
    names = repository.get_all_company_names()
    if anchor not in names:
        return []

    shareholder_edges = repository.iter_shareholder_edges()
    investment_edges = repository.iter_investment_edges()

    corp_index: dict[str, set[str]] = {}
    person_index: dict[str, set[str]] = {}
    investee_index: dict[str, set[str]] = {}
    for edge in shareholder_edges:
        if edge.is_person:
            person_index.setdefault(edge.node_name, set()).add(edge.company_code)
        elif edge.node_code is None:
            corp_index.setdefault(edge.node_name, set()).add(edge.company_code)
    for edge in investment_edges:
        if edge.node_code is None:
            investee_index.setdefault(edge.node_name, set()).add(edge.company_code)

    results: list[RelatedParty] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(
        related_code: str,
        relation_type: RelationType,
        via_node: str | None,
        via_is_person: bool,
        degree: int | None,
    ) -> None:
        if related_code == anchor or related_code not in names:
            return
        key = (related_code, relation_type, via_node)
        if key in seen:
            return
        seen.add(key)
        results.append(
            RelatedParty(
                unified_social_credit_code=anchor,
                related_code=related_code,
                related_name=names[related_code],
                relation_type=relation_type,
                via_node_name=via_node,
                via_is_person=via_is_person,
                shared_degree=degree,
                confidence=_RELATION_CONFIDENCE[relation_type],
                reliability_note=_reliability_note(
                    relation_type, names[anchor], names[related_code], via_node, degree
                ),
            )
        )

    # 直接边
    for edge in shareholder_edges:
        if edge.company_code == anchor and edge.node_code is not None:
            add(edge.node_code, "direct_shareholder", None, False, None)
    for edge in investment_edges:
        if edge.company_code == anchor and edge.node_code is not None:
            add(edge.node_code, "direct_investee", None, False, None)

    # 共享企业股东
    anchor_corp_nodes = {
        edge.node_name
        for edge in shareholder_edges
        if edge.company_code == anchor and not edge.is_person and edge.node_code is None
    }
    for node in anchor_corp_nodes:
        companies = corp_index.get(node, set())
        if _is_noise(node, len(companies), config.corporate_degree_cap, config.noise_keywords):
            continue
        for other in companies:
            add(other, "shared_corporate_shareholder", node, False, len(companies))

    # 共享自然人（不过滤）
    anchor_person_nodes = {
        edge.node_name
        for edge in shareholder_edges
        if edge.company_code == anchor and edge.is_person
    }
    for node in anchor_person_nodes:
        companies = person_index.get(node, set())
        for other in companies:
            add(other, "shared_person_shareholder", node, True, len(companies))

    # 共同对外投资
    anchor_investee_nodes = {
        edge.node_name
        for edge in investment_edges
        if edge.company_code == anchor and edge.node_code is None
    }
    for node in anchor_investee_nodes:
        companies = investee_index.get(node, set())
        if _is_noise(node, len(companies), config.investee_degree_cap, config.noise_keywords):
            continue
        for other in companies:
            add(other, "shared_investee", node, False, len(companies))

    results.sort(key=lambda party: (-party.confidence, party.related_code))
    return results
