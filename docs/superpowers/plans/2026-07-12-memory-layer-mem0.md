# 记忆层（mem0 + 会话多轮指代）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Agent 加两层记忆——确定性会话缓冲（多轮指代）+ mem0 语义记忆（跨会话、云端 DeepSeek 抽取 + 本地 bge 嵌入 + 本地 Chroma），并经 `run_research` 与交互式 `cli chat` 接入。

**Architecture:** 新 `memory/` 子系统（session/service/config 三文件，职责单一）。图层包装编排记忆（planner 仅加一处 preresolved 回退），nodes 内部尽量不动。默认关，API/CI 形状不变。CI 零网络零 key（FakeMemoryBackend + 确定性会话测试），真云端链路标 `@pytest.mark.llm` 手验。

**Tech Stack:** Python 3.11、pydantic、mem0ai、chromadb、sentence-transformers(bge，`.[rag]` 已有)、openai(DeepSeek，`.[llm]` 已有)、argparse、pytest。环境 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **红线已由用户明确豁免（走云端 DeepSeek），但保留本地接口**：LLM provider 可插拔，`MemoryConfig.deepseek`（默认）/`MemoryConfig.ollama`（本地）。`CLAUDE.md` 红线文本不删。
- **独立真值/事实不变**：记忆层不改企业事实来源（SQLite/Neo4j），只加会话上下文与语义记忆。
- 降级语义照搬 `retrieval_available`：缺 `.[memory]`/缺 key/运行时异常 → `memory_available=False` 或 no-op，绝不抛出、不污染报告。
- 默认关：`run_research(enable_memory=False)` 时行为与当前完全一致；`/research` API 本轮不动。
- CI 零网络零 key：确定性会话与降级用 FakeMemoryBackend/None 测；真 mem0+DeepSeek 标 `@pytest.mark.llm`，默认排除。
- 测试隔离缓存跑：`.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`。
- 归一化/实体类型复用现有：`CompanyResolution.match_type` 只有 `legal_name|alias`，**指代不新增类型**，直接复用存下的 resolved 实体对象。

---

### Task 1: `.[memory]` extra + `memory/session.py`（确定性会话与指代）

**Files:**
- Modify: `pyproject.toml`（加 `memory` extra、`llm` marker、addopts 排除 llm）
- Create: `src/deepresearch_agent/memory/__init__.py`（空）
- Create: `src/deepresearch_agent/memory/session.py`
- Test: `tests/test_memory_session.py`

**Interfaces:**
- Produces:
  - `ANAPHORA_MARKERS: tuple[str, ...]`
  - `contains_anaphora(query: str) -> bool`
  - `Session`（dataclass）：`user_id: str`、`session_id: str`、`recent_entities: deque`；`note_entity(resolution: CompanyResolution) -> None`、`resolve_anaphora(query: str) -> CompanyResolution | None`

- [ ] **Step 1: 改 pyproject（extra + marker + addopts）**

在 `[project.optional-dependencies]` 末尾（`trace` 段后）加：

```toml
memory = [
  "mem0ai>=0.1",
  "chromadb>=0.5",
]
```

把 `addopts` 改为（加 `and not llm`）：

```toml
addopts = "-q -m 'not slow and not neo4j and not llm'"
```

在 `markers` 列表加一行：

```toml
  "llm: 需要外部 LLM（DeepSeek）与 mem0/chromadb 的真链路测试，默认排除",
```

- [ ] **Step 2: 写失败测试**

新建 `tests/test_memory_session.py`：

```python
from collections import deque

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.memory.session import (
    ANAPHORA_MARKERS,
    Session,
    contains_anaphora,
)


def _resolved(name: str, code: str) -> CompanyResolution:
    return CompanyResolution(
        status="resolved", legal_name=name, unified_social_credit_code=code, match_type="legal_name"
    )


def test_contains_anaphora_detects_markers():
    assert contains_anaphora("它的联系方式呢")
    assert contains_anaphora("该公司的股东")
    assert contains_anaphora("上述企业的经营范围")
    assert not contains_anaphora("核验万马科技股份有限公司")


def test_note_entity_only_keeps_resolved():
    s = Session(user_id="u", session_id="s")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(CompanyResolution(status="not_found"))
    s.note_entity(CompanyResolution(status="ambiguous"))
    assert [r.unified_social_credit_code for r in s.recent_entities] == ["C1"]


def test_resolve_anaphora_returns_most_recent():
    s = Session(user_id="u", session_id="s")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(_resolved("乙公司", "C2"))
    hit = s.resolve_anaphora("它的联系方式呢")
    assert hit is not None and hit.unified_social_credit_code == "C2"


def test_resolve_anaphora_none_without_marker_or_buffer():
    s = Session(user_id="u", session_id="s")
    assert s.resolve_anaphora("它的股东") is None  # 空缓冲
    s.note_entity(_resolved("甲公司", "C1"))
    assert s.resolve_anaphora("核验乙公司") is None  # 无指代标记


def test_recent_entities_capped_at_five():
    s = Session(user_id="u", session_id="s")
    for i in range(7):
        s.note_entity(_resolved(f"公司{i}", f"C{i}"))
    assert isinstance(s.recent_entities, deque)
    assert len(s.recent_entities) == 5
    assert s.recent_entities[-1].unified_social_credit_code == "C6"


def test_markers_include_common_forms():
    for m in ("它", "该公司", "上述"):
        assert m in ANAPHORA_MARKERS
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_session.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: FAIL（`ModuleNotFoundError: No module named 'deepresearch_agent.memory'`）

- [ ] **Step 4: 实现**

新建空 `src/deepresearch_agent/memory/__init__.py`。

新建 `src/deepresearch_agent/memory/session.py`：

```python
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
    recent_entities: deque = field(default_factory=lambda: deque(maxlen=5))

    def note_entity(self, resolution: CompanyResolution) -> None:
        if resolution.status == "resolved" and resolution.unified_social_credit_code:
            self.recent_entities.append(resolution)

    def resolve_anaphora(self, query: str) -> CompanyResolution | None:
        if contains_anaphora(query) and self.recent_entities:
            return self.recent_entities[-1]
        return None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_session.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: PASS（6 项）

- [ ] **Step 6: 提交**

```powershell
git add pyproject.toml src/deepresearch_agent/memory/__init__.py src/deepresearch_agent/memory/session.py tests/test_memory_session.py
git commit -m "功能：memory 会话缓冲与确定性多轮指代解析(.[memory] extra)"
```

---

### Task 2: `memory/service.py`（记忆读写门面 + Fake 后端）

**Files:**
- Create: `src/deepresearch_agent/memory/service.py`
- Test: `tests/test_memory_service.py`

**Interfaces:**
- Consumes: 无（纯门面）。
- Produces:
  - `MemoryBackend`（Protocol）：`search(user_id, query, limit) -> list[str]`、`add(user_id, messages) -> None`
  - `FakeMemoryBackend`（测试用内存实现）
  - `Mem0Backend`（包 `mem0.Memory`；真链路用，CI 不测）
  - `MemoryService(backend=None)`：`recall(user_id, query, limit=5) -> list[str]`、`remember(user_id, messages) -> None`、属性 `memory_available: bool`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_memory_service.py`：

```python
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService


def test_service_none_backend_degrades_to_noop():
    svc = MemoryService(None)
    assert svc.memory_available is False
    assert svc.recall("u", "任何") == []
    svc.remember("u", [{"role": "user", "content": "hi"}])  # 不抛


def test_service_recall_and_remember_with_fake_backend():
    svc = MemoryService(FakeMemoryBackend())
    assert svc.memory_available is True
    svc.remember(
        "u",
        [{"role": "user", "content": "查甲公司"}, {"role": "assistant", "content": "甲公司摘要"}],
    )
    got = svc.recall("u", "甲")
    assert any("甲公司" in line for line in got)


def test_recall_isolated_per_user():
    backend = FakeMemoryBackend()
    svc = MemoryService(backend)
    svc.remember("u1", [{"role": "user", "content": "u1记忆"}])
    assert svc.recall("u2", "任何") == []


def test_recall_respects_limit():
    svc = MemoryService(FakeMemoryBackend())
    for i in range(10):
        svc.remember("u", [{"role": "user", "content": f"记忆{i}"}])
    assert len(svc.recall("u", "记忆", limit=3)) == 3


def test_service_swallows_backend_errors():
    class Boom:
        def search(self, user_id, query, limit):
            raise RuntimeError("boom")

        def add(self, user_id, messages):
            raise RuntimeError("boom")

    svc = MemoryService(Boom())
    assert svc.recall("u", "x") == []  # 异常吞掉→空
    svc.remember("u", [{"role": "user", "content": "x"}])  # 不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_service.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

新建 `src/deepresearch_agent/memory/service.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_service.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: PASS（5 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/memory/service.py tests/test_memory_service.py
git commit -m "功能：MemoryService 门面 + Fake/Mem0 后端(降级 no-op、吞异常)"
```

---

### Task 3: `memory/config.py`（provider 抽象 + mem0 配置构建）

**Files:**
- Create: `src/deepresearch_agent/memory/config.py`
- Test: `tests/test_memory_config.py`

**Interfaces:**
- Consumes: `Mem0Backend`（`memory/service.py`）。
- Produces:
  - `MemoryConfig`（dataclass，字段见实现）；`MemoryConfig.deepseek(**kw)`、`MemoryConfig.ollama(model=, base_url=, **kw)`
  - `to_mem0_config(self) -> dict`（`{llm, embedder, vector_store}`）
  - `build_memory_backend(config: MemoryConfig | None = None) -> Mem0Backend | None`（懒加载 mem0；缺 key/缺依赖 → None）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_memory_config.py`：

```python
from deepresearch_agent.memory.config import MemoryConfig, build_memory_backend


def test_deepseek_config_shape():
    cfg = MemoryConfig.deepseek()
    m = cfg.to_mem0_config()
    assert m["llm"]["provider"] == "openai"  # DeepSeek 走 openai 兼容
    assert m["llm"]["config"]["model"] == "deepseek-chat"
    assert "deepseek.com" in m["llm"]["config"]["openai_base_url"]
    assert m["embedder"]["provider"] == "huggingface"
    assert m["embedder"]["config"]["model"] == "BAAI/bge-small-zh-v1.5"
    assert m["vector_store"]["provider"] == "chroma"
    assert m["vector_store"]["config"]["collection_name"] == "procurement_memory"


def test_ollama_config_preserves_local_interface():
    cfg = MemoryConfig.ollama()
    m = cfg.to_mem0_config()
    assert m["llm"]["provider"] == "ollama"
    assert m["llm"]["config"]["model"] == "qwen2.5:3b"
    assert "localhost" in m["llm"]["config"]["ollama_base_url"]
    # 嵌入器/向量库仍本地
    assert m["embedder"]["provider"] == "huggingface"
    assert m["vector_store"]["provider"] == "chroma"


def test_build_backend_none_when_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_memory_backend(MemoryConfig.deepseek()) is None


def test_build_backend_none_when_mem0_absent(monkeypatch):
    # 有 key 但 mem0 未安装（CI 环境）→ import 失败被吞 → None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")
    assert build_memory_backend(MemoryConfig.deepseek()) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_config.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

新建 `src/deepresearch_agent/memory/config.py`：

```python
from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_CHROMA_PATH = "data/procurement/derived/mem0_chroma"
DEFAULT_EMBEDDER_MODEL = "BAAI/bge-small-zh-v1.5"


@dataclass
class MemoryConfig:
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    embedder_model: str = DEFAULT_EMBEDDER_MODEL
    vector_store_path: str = DEFAULT_CHROMA_PATH
    collection_name: str = "procurement_memory"

    @classmethod
    def deepseek(cls, **kwargs) -> "MemoryConfig":
        return cls(**kwargs)

    @classmethod
    def ollama(
        cls,
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        **kwargs,
    ) -> "MemoryConfig":
        return cls(
            llm_provider="ollama",
            llm_model=model,
            llm_base_url=base_url,
            api_key_env="",
            **kwargs,
        )

    def to_mem0_config(self) -> dict:
        if self.llm_provider == "ollama":
            llm = {
                "provider": "ollama",
                "config": {"model": self.llm_model, "ollama_base_url": self.llm_base_url},
            }
        else:
            llm = {
                "provider": "openai",
                "config": {
                    "model": self.llm_model,
                    "openai_base_url": self.llm_base_url,
                    "api_key": os.environ.get(self.api_key_env, ""),
                },
            }
        return {
            "llm": llm,
            "embedder": {"provider": "huggingface", "config": {"model": self.embedder_model}},
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": self.collection_name,
                    "path": self.vector_store_path,
                },
            },
        }


def build_memory_backend(config: MemoryConfig | None = None):
    config = config or MemoryConfig()
    if config.llm_provider == "deepseek" and not os.environ.get(config.api_key_env):
        return None
    try:
        from mem0 import Memory

        from deepresearch_agent.memory.service import Mem0Backend

        memory = Memory.from_config(config.to_mem0_config())
        return Mem0Backend(memory)
    except Exception:
        return None
```

> 注：`to_mem0_config` 的 exact 键名（`openai_base_url`/`ollama_base_url`/chroma `path`）随 mem0 版本可能微调；本任务测试只断言我们的 provider 选择与取值形状，真 mem0 接受性由 Task 6 后的手验（`@pytest.mark.llm` 或本地跑）确认，实现者装 mem0 后如键名不符按installed 版本对齐并在报告说明。

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_config.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: PASS（4 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/memory/config.py tests/test_memory_config.py
git commit -m "功能：MemoryConfig provider 抽象(云端 DeepSeek 默认/本地 Ollama 接口)+ 懒加载后端"
```

---

### Task 4: 接入 Agent（state.preresolved + planner 回退 + run_research 编排）

**Files:**
- Modify: `src/deepresearch_agent/state.py`（加 `preresolved` 字段）
- Modify: `src/deepresearch_agent/agents/nodes.py`（planner 回退）
- Modify: `src/deepresearch_agent/agents/graph.py`（`run_compiled` 传 preresolved、`run_research` 编排记忆）
- Test: `tests/test_memory_integration.py`

**Interfaces:**
- Consumes: `Session`、`MemoryService`、`FakeMemoryBackend`。
- Produces:
  - `ResearchState.preresolved: CompanyResolution | None = None`
  - `run_compiled(compiled_graph, question, domain, preresolved=None)`
  - `run_research(..., session: Session | None = None, memory: MemoryService | None = None, enable_memory: bool = False)`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_memory_integration.py`（用 conftest 的 `company_database_path`，其企业法定名 `示例科技股份有限公司`、code `91330000123456789X`）：

```python
from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def test_memory_off_behaves_as_before(company_database_path):
    state = run_research(ENTITY, database_path=company_database_path)
    assert state.report is not None
    assert state.supplier_resolution.unified_social_credit_code == CODE
    assert state.preresolved is None


def test_coreference_resolves_pronoun_to_prior_entity(company_database_path):
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())
    # 第一轮：解析到实体
    s1 = run_research(
        ENTITY, database_path=company_database_path, session=session, memory=memory, enable_memory=True
    )
    assert s1.supplier_resolution.unified_social_credit_code == CODE
    # 第二轮：指代 → 回退到上一轮实体
    s2 = run_research(
        "它的联系方式呢",
        database_path=company_database_path,
        session=session,
        memory=memory,
        enable_memory=True,
    )
    assert s2.supplier_resolution is not None
    assert s2.supplier_resolution.unified_social_credit_code == CODE
    assert s2.supplier_name == ENTITY


def test_remember_called_with_question_and_summary(company_database_path):
    backend = FakeMemoryBackend()
    session = Session(user_id="u", session_id="s")
    run_research(
        ENTITY,
        database_path=company_database_path,
        session=session,
        memory=MemoryService(backend),
        enable_memory=True,
    )
    stored = backend.store.get("u", [])
    assert stored and ENTITY in stored[0]  # 问题进了记忆


def test_recall_surfaced_in_report_open_questions(company_database_path):
    backend = FakeMemoryBackend()
    backend.store["u"] = ["你此前研究过示例科技股份有限公司"]
    session = Session(user_id="u", session_id="s")
    state = run_research(
        ENTITY,
        database_path=company_database_path,
        session=session,
        memory=MemoryService(backend),
        enable_memory=True,
    )
    assert any("历史记忆" in q for q in state.report.open_questions)


def test_no_coreference_without_prior_entity(company_database_path):
    session = Session(user_id="u", session_id="s")
    state = run_research(
        "它的联系方式呢",
        database_path=company_database_path,
        session=session,
        memory=MemoryService(FakeMemoryBackend()),
        enable_memory=True,
    )
    # 无历史实体 → 指代无回退 → not_found → 未解析报告
    assert state.supplier_resolution.status == "not_found"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_integration.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: FAIL（`TypeError: run_research() got an unexpected keyword argument 'session'`）

- [ ] **Step 3a: 加 state 字段**

在 `src/deepresearch_agent/state.py` 的 `ResearchState` 中，`supplier_resolution` 字段之后加：

```python
    preresolved: CompanyResolution | None = None
```

- [ ] **Step 3b: planner 回退**

在 `src/deepresearch_agent/agents/nodes.py` 的 `planner_node` 中，把：

```python
    resolution = resolve_supplier(state.question, repository)
    state.supplier_resolution = resolution
```

改为（直接解析优先，仅 not_found 时回退指代实体）：

```python
    resolution = resolve_supplier(state.question, repository)
    if resolution.status == "not_found" and state.preresolved is not None:
        resolution = state.preresolved
    state.supplier_resolution = resolution
```

- [ ] **Step 3c: graph.py 的 run_compiled + run_research**

在 `src/deepresearch_agent/agents/graph.py`，把 `run_compiled` 改为接受 `preresolved`：

```python
def run_compiled(compiled_graph, question: str, domain: str, preresolved=None) -> ResearchState:
    result = compiled_graph.invoke(
        ResearchState(question=question, domain=domain, preresolved=preresolved)
    )
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)
```

在文件末尾（`_build_llm` 之后）加三个 helper：

```python
def _report_of(state: ResearchState):
    for report in (state.report, state.scope_report, state.graph_report):
        if report is not None:
            return report
    return None


def _report_summary(state: ResearchState) -> str:
    report = _report_of(state)
    return report.summary if report is not None else ""


def _surface_memory(state: ResearchState, lines: list[str]) -> None:
    report = _report_of(state)
    if report is None or not lines:
        return
    note = [f"结合历史记忆（供参考，非本轮新事实）：{line}" for line in lines]
    report.open_questions = note + list(report.open_questions)
```

把 `run_research` 的签名与主体改为（加 `session`/`memory`/`enable_memory`，编排记忆；保留既有 tracing 行为）：

```python
def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    enable_scope: bool = False,
    enable_graph: bool = False,
    enable_tracing: bool = False,
    session=None,
    memory=None,
    enable_memory: bool = False,
) -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    repository = CompanyRepository(database_path)
    scope_retriever = (
        _build_scope_retriever(database_path, index_path)
        if (enable_scope or enable_graph)
        else None
    )
    graph_searcher = (
        _build_graph_searcher(database_path, scope_retriever) if enable_graph else None
    )
    if enable_tracing:
        configure_tracing()
    app = build_graph(
        domain_pack,
        repository,
        scope_retriever=scope_retriever,
        graph_searcher=graph_searcher,
        llm=_build_llm(),
        scope_enabled=enable_scope,
        graph_enabled=enable_graph,
        enable_tracing=enable_tracing,
    )

    preresolved = None
    memory_lines: list[str] = []
    if enable_memory and session is not None:
        preresolved = session.resolve_anaphora(question)
        if memory is not None:
            memory_lines = memory.recall(session.user_id, question)

    tracer = get_tracer() if enable_tracing else None
    if tracer is not None:
        with tracer.start_as_current_span("research") as span:
            span.set_attribute("question", question)
            span.set_attribute("domain", domain)
            state = run_compiled(app, question, domain, preresolved=preresolved)
    else:
        state = run_compiled(app, question, domain, preresolved=preresolved)

    if enable_memory and session is not None:
        if state.supplier_resolution is not None:
            session.note_entity(state.supplier_resolution)
        if memory is not None:
            memory.remember(
                session.user_id,
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": _report_summary(state)},
                ],
            )
    if memory_lines:
        _surface_memory(state, memory_lines)
    return state
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_integration.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: PASS（5 项）

- [ ] **Step 5: 全套回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-memory-full`
Expected: 全绿（原 202 + 本模块新增；0 失败）

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py src/deepresearch_agent/agents/graph.py tests/test_memory_integration.py
git commit -m "功能：记忆接入 run_research(会话指代回退+跨会话召回注入+remember)"
```

---

### Task 5: `cli chat` 交互式多轮

**Files:**
- Modify: `src/deepresearch_agent/cli.py`（加 `chat` 分派 + `run_chat_loop` + `_chat_main`）
- Test: `tests/test_cli_chat.py`

**Interfaces:**
- Consumes: `run_research`、`Session`、`MemoryService`、`build_memory_backend`。
- Produces:
  - `run_chat_loop(session, memory, read_line, emit, run_turn) -> None`（可测核心：`read_line() -> str | None`，`emit(state) -> None`，`run_turn(line, session, memory) -> state`）
  - `_chat_main(argv)`（CLI 包装，`input`/`Console` 注入 `run_chat_loop`）
  - `main` 支持 `chat` 子命令

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cli_chat.py`（复用 `company_database_path`；用脚本化 `read_line` 与真 `run_research` 绑定 fixture 库，端到端验多轮指代，零网络）：

```python
from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.cli import run_chat_loop
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def test_chat_loop_multi_turn_coreference(company_database_path):
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())
    lines = iter([ENTITY, "它的联系方式呢", "exit"])
    states = []

    def read_line():
        return next(lines, None)

    def run_turn(line, s, m):
        return run_research(
            line,
            database_path=company_database_path,
            session=s,
            memory=m,
            enable_memory=True,
        )

    run_chat_loop(session, memory, read_line, states.append, run_turn)

    assert len(states) == 2  # exit 不产出
    assert states[0].supplier_resolution.unified_social_credit_code == CODE
    # 第二轮靠会话指代解析到同一实体
    assert states[1].supplier_resolution.unified_social_credit_code == CODE


def test_chat_loop_stops_on_exit_and_none():
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(None)
    emitted = []
    for stopper in (["exit"], [None]):
        it = iter(stopper)
        run_chat_loop(
            session,
            memory,
            lambda: next(it, None),
            emitted.append,
            lambda line, s, m: emitted.append("RAN"),
        )
    assert emitted == []  # exit / None 立即停，未跑任何轮
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli_chat.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: FAIL（`ImportError: cannot import name 'run_chat_loop'`）

- [ ] **Step 3: 实现**

在 `src/deepresearch_agent/cli.py`，`main` 开头的 eval 分派之后加 chat 分派：

```python
    if raw and raw[0] == "chat":
        _chat_main(raw[1:])
        return
```

在文件末尾加：

```python
def run_chat_loop(session, memory, read_line, emit, run_turn) -> None:
    while True:
        line = read_line()
        if line is None:
            break
        line = line.strip()
        if line in ("exit", "quit", ""):
            break
        emit(run_turn(line, session, memory))


def _print_any_report(console: Console, state) -> None:
    if state.graph_report is not None:
        _print_graph_report(console, state.graph_report)
    elif state.scope_report is not None:
        _print_scope_report(console, state.scope_report)
    elif state.report is not None:
        _print_supplier_report(console, state.report)


def _chat_main(argv: list[str]) -> None:
    from deepresearch_agent.memory.config import build_memory_backend
    from deepresearch_agent.memory.service import MemoryService
    from deepresearch_agent.memory.session import Session

    parser = argparse.ArgumentParser(prog="cli chat", description="交互式多轮供应商核验对话。")
    parser.add_argument("--user", default="default")
    parser.add_argument("--session", default="cli")
    parser.add_argument("--database", default="data/procurement/derived/companies.sqlite3")
    parser.add_argument("--index", default="data/procurement/derived/scope_index.faiss")
    args = parser.parse_args(argv)

    session = Session(user_id=args.user, session_id=args.session)
    memory = MemoryService(build_memory_backend())
    console = Console()
    console.print(f"[bold]对话开始[/bold]（输入 exit 退出）。记忆可用：{memory.memory_available}")

    def run_turn(line, s, m):
        return run_research(
            line,
            database_path=args.database,
            index_path=args.index,
            enable_scope=True,
            session=s,
            memory=m,
            enable_memory=True,
        )

    run_chat_loop(session, memory, lambda: _read_input(console), lambda st: _print_any_report(console, st), run_turn)


def _read_input(console: Console) -> str | None:
    try:
        return input("> ")
    except EOFError:
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli_chat.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-memory`
Expected: PASS（2 项）

- [ ] **Step 5: 全套回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-memory-full2`
Expected: 全绿

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/cli.py tests/test_cli_chat.py
git commit -m "功能：cli chat 交互式多轮对话(run_chat_loop 可测核心)"
```

---

### Task 6: 文档同步

**Files:**
- Modify: `CLAUDE.md`（常用命令加 `cli chat`；注意点加记忆层一句 + 红线豁免说明）
- Modify: `docs/architecture.md`（新增记忆层小节 + 数据流）
- Modify: `docs/project-memory.md`（追加条目 26）
- Modify: `.gitignore`（忽略 `data/procurement/derived/mem0_chroma/`）

- [ ] **Step 1: .gitignore**

在 `.gitignore` 末尾加：

```
data/procurement/derived/mem0_chroma/
```

- [ ] **Step 2: CLAUDE.md**

在「运行 Agent」代码块内（`--trace` 那段之后）加：

````markdown
# 交互式多轮对话（会话指代 + mem0 跨会话记忆；记忆走云端 DeepSeek，需 DEEPSEEK_API_KEY + .[memory]）
.\.conda-env\python.exe -m deepresearch_agent.cli chat --user me `
  --database data/procurement/derived/companies.sqlite3
````

在「注意点」列表加一条：

```markdown
- `memory/` 是记忆层（`session.py` 确定性会话缓冲+多轮指代 / `service.py` MemoryService 门面+Fake 后端 / `config.py` provider 抽象）。两层：会话最近实体缓冲（指代，零 LLM）+ mem0 语义记忆（跨会话，云端 DeepSeek 抽取+本地 bge 嵌入+本地 Chroma）。经 `run_research(session=, enable_memory=)` 与 `cli chat` 接入，默认关、API 不动。**红线豁免**：本线经用户明确决定走云端 DeepSeek（`MemoryConfig.deepseek`），本地 Ollama 接口保留（`MemoryConfig.ollama`）；CLAUDE.md 核心红线文本仍在、仅本线豁免，见 spec。CI 零网络（FakeMemoryBackend），真链路标 `@pytest.mark.llm`。
```

- [ ] **Step 3: docs/architecture.md**

在「经营范围语义检索」小节之后插入新小节：

```markdown
## 记忆层（`memory/`）

两层记忆，经 `run_research(session=, memory=, enable_memory=)` 与 `cli chat` 接入，默认关、`/research` API 不动。

- **会话最近实体缓冲**（`session.py`，确定性、零 LLM）：`Session.recent_entities` 存最近 resolved 实体；`resolve_anaphora` 在句含 `它/该公司/上述` 等标记时返回最近实体。planner 仅在直接解析 `not_found` 时回退该实体（`state.preresolved`）。
- **mem0 语义记忆**（`service.py`/`config.py`，跨会话）：`MemoryService.recall/remember` 包 mem0；抽取走云端 DeepSeek（`MemoryConfig.deepseek`，OpenAI 兼容），嵌入用本地 bge，向量库本地 Chroma。缺依赖/缺 key/异常 → `memory_available=False` 或 no-op 降级。
- **数据流（一轮）**：指代解析→`preresolved`；`recall`→注入报告 `open_questions`（标注「历史记忆」）；跑图；`note_entity`；`remember(问题+报告摘要)`。
- **红线**：本线经用户决定豁免数据本地化、抽取走云端；本地 Ollama 接口保留（一段 config 可切回）。CI 零网络用 FakeMemoryBackend，真链路 `@pytest.mark.llm` 手验。
```

- [ ] **Step 4: docs/project-memory.md**

在最后一条编号条目之后、`## 本地数据状态` 之前加条目 26：

```markdown
26. **记忆层（mem0 语义记忆 + 会话多轮指代）**：新 `memory/`（session/service/config）。**两层**：①会话最近实体缓冲（`Session.recent_entities` deque(maxlen=5) + `resolve_anaphora` 识别 `它/该公司/上述` 等标记→最近 resolved 实体，确定性零 LLM）；②mem0 语义记忆（`MemoryService.recall/remember`，云端 DeepSeek 抽取+本地 bge 嵌入+本地 Chroma）。接入：`state.preresolved` + planner「直接解析 not_found 才回退指代实体」；`run_research(session=,memory=,enable_memory=)` 图层编排（指代→recall 注入 open_questions→跑图→note_entity→remember 问题+摘要），默认关、API 不动；`cli chat` REPL（`run_chat_loop` 可测核心）承载多轮。**红线：用户明确决定本线豁免数据本地化、走云端 DeepSeek**（两次告知不可逆风险后决定），`MemoryConfig` 留本地 Ollama 接口一段 config 可切回，CLAUDE.md 红线文本不删仅本线豁免。降级照搬 retrieval_available（缺 .[memory]/key/异常→no-op）。CI 零网络零 key（FakeMemoryBackend + 确定性会话测试），真 mem0+DeepSeek 标 `@pytest.mark.llm` 手验。`.[memory]` extra=mem0ai+chromadb。前端聊天页/API 接记忆留后续。
```

- [ ] **Step 5: 提交**

```powershell
git add CLAUDE.md docs/architecture.md docs/project-memory.md .gitignore
git commit -m "文档：同步记忆层(两层记忆+云端豁免+cli chat)到架构/记忆/CLAUDE"
```

---

## 收尾

六个 Task 完成后用 **superpowers:finishing-a-development-branch**：跑全套测试 → present 合并选项。

**真链路手验（收尾后，用户本地，可选）**：`pip install .[memory]`（mem0ai+chromadb，注意 Phoenix 教训——若与 numpy/torch 冲突先隔离验证不破坏测试）→ 设 `DEEPSEEK_API_KEY` → `cli chat` 跑真多轮 → 确认 mem0 config 键名对installed 版本无误、跨会话 recall 生效。

## Self-Review

- **Spec 覆盖**：两层记忆（Task1 会话缓冲 + Task2/3 mem0）、接入 run_research（Task4）、cli chat 多轮（Task5）、默认关/API 不动（Task4 test `test_memory_off_behaves_as_before`）、CI 零网络（FakeMemoryBackend 贯穿）、红线豁免留档（Task6 文档 + spec）、本地 Ollama 接口（Task3 `MemoryConfig.ollama` + test）均有任务。前端/API 接记忆按 spec 明确不做。
- **占位符**：无 TBD；每步含完整代码与命令。config 键名「实现时对版本对齐」是诚实延迟（真接受性手验），非缺口。
- **类型一致**：`Session.resolve_anaphora -> CompanyResolution | None`、`MemoryService.recall -> list[str]`、`run_research(..., session, memory, enable_memory)`、`run_compiled(..., preresolved=None)`、`run_chat_loop(session, memory, read_line, emit, run_turn)` 跨 Task 引用一致。planner 回退用 `state.preresolved`（Task4 定义、Task5 经 run_research 间接用）。`FakeMemoryBackend.store: dict[str,list[str]]` 在 Task2 定义、Task4/5 test 直接读一致。
