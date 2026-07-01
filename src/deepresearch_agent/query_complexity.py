from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel

from deepresearch_agent.company_repository import CompanyRepository


RELATIONSHIP_KEYWORDS = (
    "控制人",
    "实控人",
    "实际控制",
    "控股",
    "母公司",
    "子公司",
    "股东",
    "持股",
    "持有",
    "投资",
    "关联",
    "关系",
    "围标",
    "串标",
    "穿透",
    "背后",
    "一伙",
    "同一控制",
    "共同控制",
    "最终受益",
    "谁控制",
    "谁持有",
    "路径",
)

_VALID_LEVELS = {"simple", "medium", "complex"}


class ComplexityResult(BaseModel):
    level: Literal["simple", "medium", "complex"]
    method: Literal["heuristic", "llm"]
    reasoning: str


def classify_heuristic(query: str, repository: CompanyRepository) -> ComplexityResult:
    matched = [keyword for keyword in RELATIONSHIP_KEYWORDS if keyword in query]
    has_relationship = bool(matched)
    has_entity = repository.resolve_text(query).status in {"resolved", "ambiguous"}
    if has_relationship and has_entity:
        return ComplexityResult(
            level="complex",
            method="heuristic",
            reasoning=f"含关系关键词『{matched[0]}』且指名企业，需多跳图检索",
        )
    if has_relationship:
        return ComplexityResult(
            level="medium",
            method="heuristic",
            reasoning=f"含关系关键词『{matched[0]}』但未指名企业，需能力检索+图融合",
        )
    return ComplexityResult(
        level="simple",
        method="heuristic",
        reasoning="无关系信号，纯核验或能力检索",
    )


def classify_complexity(
    query: str,
    repository: CompanyRepository,
    llm: Callable[[str], str | None] | None = None,
) -> ComplexityResult:
    if llm is not None:
        try:
            level = llm(query)
        except Exception:
            level = None
        if level in _VALID_LEVELS:
            return ComplexityResult(level=level, method="llm", reasoning="LLM 分类")
    return classify_heuristic(query, repository)
