from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.memory.session import Session


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SessionOwnershipError(Exception):
    """请求 user_id 与会话 owner 不符——非泄露式，API 映射 404。"""


class InvalidSessionIdError(Exception):
    """session_id 非法（防路径穿越）——API 映射 400。"""


def _require_valid_id(session_id: str) -> None:
    if not SESSION_ID_PATTERN.match(session_id):
        raise InvalidSessionIdError(f"非法 session_id：{session_id!r}")


@dataclass(frozen=True)
class SessionSummary:
    """供对话侧边栏使用的最小元数据，不包含会话实体或研究报告。"""

    session_id: str
    title: str
    updated_at: str


class JsonSessionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def load(self, session_id: str, user_id: str) -> Session | None:
        _require_valid_id(session_id)
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("user_id") != user_id:
            raise SessionOwnershipError(session_id)
        entities = deque(
            (CompanyResolution.model_validate(item) for item in data.get("recent_entities", [])),
            maxlen=5,
        )
        return Session(
            user_id=user_id,
            session_id=session_id,
            title=data.get("title"),
            recent_entities=entities,
        )

    def save(self, session: Session) -> None:
        _require_valid_id(session.session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(session.session_id)
        previous: dict = {}
        if target.exists():
            previous = json.loads(target.read_text(encoding="utf-8"))
        now = datetime.now(UTC).isoformat()
        payload = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "title": session.title,
            "created_at": previous.get("created_at", now),
            "updated_at": now,
            "recent_entities": [r.model_dump(mode="json") for r in session.recent_entities],
        }
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)

    def list_for_user(self, user_id: str) -> list[SessionSummary]:
        """列出属于当前用户的会话，按最近活动时间倒序。

        旧格式会话没有标题和时间字段时保持可见，并以文件修改时间作为排序依据。
        """
        if not self.root.exists():
            return []

        summaries: list[SessionSummary] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("user_id") != user_id:
                continue
            session_id = data.get("session_id")
            if not isinstance(session_id, str) or not SESSION_ID_PATTERN.match(session_id):
                continue
            updated_at = data.get("updated_at")
            if not isinstance(updated_at, str) or not updated_at:
                updated_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            title = data.get("title")
            summaries.append(
                SessionSummary(
                    session_id=session_id,
                    title=title.strip() if isinstance(title, str) and title.strip() else "未命名对话",
                    updated_at=updated_at,
                )
            )
        return sorted(summaries, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str, user_id: str) -> bool:
        """删除属于当前用户的会话；不存在时返回 False。"""
        _require_valid_id(session_id)
        path = self._path(session_id)
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("user_id") != user_id:
            raise SessionOwnershipError(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
