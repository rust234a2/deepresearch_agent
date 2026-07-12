from __future__ import annotations

import json
import os
import re
from collections import deque
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
        return Session(user_id=user_id, session_id=session_id, recent_entities=entities)

    def save(self, session: Session) -> None:
        _require_valid_id(session.session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "recent_entities": [r.model_dump(mode="json") for r in session.recent_entities],
        }
        target = self._path(session.session_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
