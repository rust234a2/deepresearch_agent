from __future__ import annotations

import re
from dataclasses import dataclass

_SECTION_SEPARATOR = "***"
_ITEM_SEPARATORS = re.compile(r"[、；;，,。]")
_LABEL_PATTERN = re.compile(r"^([^：:]{1,12})[：:]")
_DISCLAIMER_PATTERN = re.compile(r"（依法须经[^）]*）")


@dataclass(frozen=True)
class ScopeChunk:
    section_label: str | None
    ordinal: int
    text: str


def _normalize(value: str) -> str:
    return " ".join(value.split())


def chunk_business_scope(text: str | None) -> list[ScopeChunk]:
    if text is None or not text.strip():
        return []
    chunks: list[ScopeChunk] = []
    ordinal = 0
    for raw_section in text.split(_SECTION_SEPARATOR):
        section = raw_section.strip()
        if not section:
            continue
        label: str | None = None
        match = _LABEL_PATTERN.match(section)
        if match:
            label = match.group(1).strip()
            section = section[match.end():]
        section = _DISCLAIMER_PATTERN.sub("", section)
        seen: set[str] = set()
        for raw_item in _ITEM_SEPARATORS.split(section):
            item = _normalize(raw_item)
            if not item:
                continue
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            chunks.append(ScopeChunk(section_label=label, ordinal=ordinal, text=item))
            ordinal += 1
    return chunks
