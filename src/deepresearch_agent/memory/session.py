from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from deepresearch_agent.company_models import CompanyResolution


ANAPHORA_MARKERS: tuple[str, ...] = (
    "它",
    "该公司",
    "该企业",
    "该供应商",
    "该厂商",
    "这家",
    "那家",
    "这家公司",
    "那家公司",
    "上述",
    "此公司",
)


def contains_anaphora(query: str) -> bool:
    return any(marker in query for marker in ANAPHORA_MARKERS)


@dataclass
class Session:
    user_id: str
    session_id: str
    # 会话标题只用于对话管理界面；实体缓冲仍是 Agent 多轮指代的唯一上下文。
    title: str | None = None
    recent_entities: deque = field(default_factory=lambda: deque(maxlen=5))

    def note_entity(self, resolution: CompanyResolution) -> None:
        if resolution.status == "resolved" and resolution.unified_social_credit_code:
            self.recent_entities.append(resolution)

    def resolve_anaphora(self, query: str) -> CompanyResolution | None:
        if contains_anaphora(query) and self.recent_entities:
            return self.recent_entities[-1]
        return None
