from __future__ import annotations

import os
from collections.abc import Callable

_JUDGE_SYSTEM_PROMPT = (
    "你是经营范围覆盖判定器。给定一个能力关键词和一家企业的经营范围原文，"
    "判断该经营范围是否实际覆盖该能力。只输出 是 或 否，不要任何多余文字。"
)


def _parse_bool(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("是"):
        return True
    if stripped.startswith("否"):
        return False
    return ("是" in stripped) and ("否" not in stripped)


def build_deepseek_scope_judge(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> Callable[[str, str], bool] | None:
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0, max_retries=2)

    def judge(query: str, scope: str) -> bool:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"能力：{query}\n经营范围：{scope}"},
                ],
            )
            return _parse_bool(response.choices[0].message.content)
        except Exception:
            return False

    return judge
