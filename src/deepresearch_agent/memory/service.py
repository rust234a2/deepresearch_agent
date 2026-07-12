from __future__ import annotations

from typing import Protocol


class MemoryBackend(Protocol):
    def search(self, user_id: str, query: str, limit: int) -> list[str]: ...

    def add(self, user_id: str, messages: list[dict]) -> None: ...


class FakeMemoryBackend:
    """内存实现，测试用：最近的记忆在前。"""

    def __init__(self) -> None:
        self.store: dict[str, list[str]] = {}

    def search(self, user_id: str, query: str, limit: int) -> list[str]:
        return self.store.get(user_id, [])[:limit]

    def add(self, user_id: str, messages: list[dict]) -> None:
        text = " ".join(m.get("content", "") for m in messages)
        self.store.setdefault(user_id, []).insert(0, text)


class Mem0Backend:
    """包装 mem0.Memory；真链路用（云端 DeepSeek 抽取）。CI 不测，见 @pytest.mark.llm。"""

    def __init__(self, memory) -> None:
        self._memory = memory

    def search(self, user_id: str, query: str, limit: int) -> list[str]:
        res = self._memory.search(query=query, user_id=user_id, limit=limit)
        results = res.get("results", []) if isinstance(res, dict) else res
        return [r.get("memory", "") for r in results if isinstance(r, dict)]

    def add(self, user_id: str, messages: list[dict]) -> None:
        self._memory.add(messages, user_id=user_id)


class MemoryService:
    def __init__(self, backend=None) -> None:
        self._backend = backend

    @property
    def memory_available(self) -> bool:
        return self._backend is not None

    def recall(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        if self._backend is None:
            return []
        try:
            return self._backend.search(user_id, query, limit)
        except Exception:
            return []

    def remember(self, user_id: str, messages: list[dict]) -> None:
        if self._backend is None:
            return
        try:
            self._backend.add(user_id, messages)
        except Exception:
            return
