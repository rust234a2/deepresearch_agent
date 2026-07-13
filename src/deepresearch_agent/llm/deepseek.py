from __future__ import annotations

import os
from typing import Callable, Iterator


_VALID_LEVELS = ("simple", "medium", "complex")

_SYSTEM_PROMPT = (
    "你是查询复杂度分类器。只输出 simple、medium、complex 三者之一，不要任何多余文字。\n"
    "simple = 核验单个具名企业，或纯能力检索；\n"
    "medium = 按能力找企业并涉及它们之间的关系；\n"
    "complex = 某个具体企业的深层股权/控制关系（多跳穿透）。"
)


def _parse_level(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.strip().lower()
    for level in _VALID_LEVELS:
        if level in lowered:
            return level
    return None


def build_deepseek_classifier(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> Callable[[str], str | None] | None:
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url)

    def classify(query: str) -> str | None:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
            )
            return _parse_level(response.choices[0].message.content)
        except Exception:
            return None

    return classify


_PRESENTER_SYSTEM_PROMPT = (
    "你是工商研究报告的呈现器，把给定的结构化报告改写成通顺中文，用于展示。严格规则：\n"
    "1. 只复述报告中出现的事实，绝不添加任何未在报告中的信息。\n"
    "2. 绝不推断产能、交期、质量认证或风险；经营范围按原文，不结构化为产品。\n"
    "3. 保留所有企业名、统一社会信用代码、控制人姓名的原文，不改写。\n"
    "4. 围标/共享控制人线索必须标注「线索级·须人工复核」，绝不作控制关系或围标认定。\n"
    "5. 只输出正文，不加额外建议、不加评论。\n"
    "6. 换行请直接输出真实换行，绝不要输出字面的反斜杠加 n。"
)


def _render_report_for_llm(report_type: str, report: dict) -> str:
    # 刻意不传 summary 与 risks：它们可能含固定结论式表述；数据缺口由 open_questions 承载。
    lines: list[str] = []
    if report_type in ("named", "unresolved"):
        lines.append(f"企业：{report.get('supplier_name', '')}")
        for ev in report.get("evidence_table", []):
            lines.append(f"证据[{ev.get('dimension', '')}]：{ev.get('claim', '')}")
    elif report_type == "scope":
        lines.append(f"能力检索：{report.get('query', '')}")
        for c in report.get("candidates", []):
            lines.append(f"候选：{c.get('legal_name', '')}（相关度 {c.get('top_score', 0):.2f}）")
    else:  # graph
        lines.append(f"股权关系检索：{report.get('query', '')}")
        for c in report.get("candidates", []):
            ctrl = "、".join(c.get("ultimate_controllers") or []) or "—"
            lines.append(f"候选：{c.get('legal_name', '')}｜最终控制人：{ctrl}")
        for s in report.get("shared_controllers", []):
            comp = "、".join(s.get("controlled_companies") or [])
            lines.append(f"共享控制人线索：{s.get('controller_name', '')} → {comp}（{s.get('note', '')}）")
    for q in report.get("open_questions", []):
        lines.append(f"待解问题：{q}")
    return "\n".join(lines)


def build_deepseek_polisher(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> "Callable[[str, dict], Iterator[str]] | None":
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url)

    def stream_presentation(report_type: str, report: dict) -> Iterator[str]:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            stream=True,
            messages=[
                {"role": "system", "content": _PRESENTER_SYSTEM_PROMPT},
                {"role": "user", "content": _render_report_for_llm(report_type, report)},
            ],
        )
        # DeepSeek 偶尔吐字面反斜杠n。反斜杠可能被拆在两个 token 里（\ 在前、n 在后），
        # 故缓冲一个末尾孤立反斜杠到下一 token 再一起替换，避免漏清。
        pending = ""
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if not delta:
                continue
            text = pending + delta
            pending = ""
            if text.endswith("\\"):
                pending = "\\"
                text = text[:-1]
            yield text.replace("\\n", "\n")
        if pending:
            yield pending

    return stream_presentation
