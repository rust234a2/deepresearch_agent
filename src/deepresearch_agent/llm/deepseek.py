from __future__ import annotations

import os
from typing import Callable


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
