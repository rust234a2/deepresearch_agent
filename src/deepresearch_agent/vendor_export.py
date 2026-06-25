from __future__ import annotations

import re


_EXCEL_QUOTE = re.compile(r'^="(.*)"$', re.DOTALL)


def unquote(value: str) -> str:
    value = value.strip()
    match = _EXCEL_QUOTE.fullmatch(value)
    if match:
        value = match.group(1)
    return value.strip()


def clean_cell(value: str) -> str:
    value = unquote(value)
    if value == "-" or (value and set(value) == {"*"}):
        return ""
    return value
