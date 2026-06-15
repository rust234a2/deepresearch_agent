from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PermissionTier = Literal["read_public", "read_private", "write", "human_approval"]


class ToolResult(BaseModel):
    name: str
    status: Literal["ok", "error"]
    data: dict
    latency_ms: int
    permission_tier: PermissionTier


class RegisteredTool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    permission_tier: PermissionTier
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    handler: Callable[[dict], dict]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, args: dict) -> ToolResult:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")

        tool = self._tools[name]
        started = perf_counter()
        try:
            data = tool.handler(args)
            status = "ok"
        except Exception as exc:  # pragma: no cover - error path is integration-tested later
            data = {"error": str(exc)}
            status = "error"
        latency_ms = int((perf_counter() - started) * 1000)

        return ToolResult(
            name=name,
            status=status,
            data=data,
            latency_ms=latency_ms,
            permission_tier=tool.permission_tier,
        )
