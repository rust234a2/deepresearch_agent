# /research API 接记忆（会话存储 + ownership）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `POST /session/turn` 有状态多轮端点，会话缓冲 JSON 文件跨进程持久化，ownership 授权（防 IDOR）+ session_id 格式校验（防路径穿越），复用 `execute_turn` 记忆编排。

**Architecture:** `memory/store.py` 存会话（原子写、owner 绑定、格式校验）；`agents/graph.py` 抽 `execute_turn`（`run_research` 与 API 共用）；`api.py` 加端点 + 可注入 memory/store。默认零网络零 key（Fake + tmp）。

**Tech Stack:** Python 3.11、FastAPI、pydantic、uuid、pytest（TestClient）。环境 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **ownership 授权**：`load` 时 `存储 owner != 请求 user_id` → 抛 `SessionOwnershipError`（API 404），任何 save 之前，绝不覆写他人会话。
- **路径穿越防护**：session_id 必须匹配 `^[A-Za-z0-9_-]{1,64}$` 才作文件名，否则抛 `InvalidSessionIdError`（API 400）。
- **原子写**：写临时文件 → `os.replace`。
- `/research` 旧端点行为/形状**不变**；`/session/turn` 恒 `enable_memory=True`、`enable_scope=False`（→ SupplierReport）。
- `execute_turn` 重构后 `run_research` 行为**不变**（现有记忆/追踪测试仍绿）。
- CI 零网络零 key：store 用 tmp_path、API 注入 FakeMemoryBackend；真 mem0+DeepSeek 标 `@pytest.mark.llm`。
- 测试隔离缓存：`.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`。
- `CompanyResolution` 序列化用 `model_dump(mode="json")` / `model_validate`；`Session.recent_entities` 是 `deque(maxlen=5)`。

---

### Task 1: `memory/store.py`（JSON 会话存储 + ownership + 格式校验）

**Files:**
- Create: `src/deepresearch_agent/memory/store.py`
- Test: `tests/test_memory_store.py`

**Interfaces:**
- Consumes: `Session`（`memory/session.py`）、`CompanyResolution`（`company_models`）。
- Produces:
  - `SESSION_ID_PATTERN`（re.Pattern）、`SessionOwnershipError`、`InvalidSessionIdError`
  - `JsonSessionStore(root)`：`load(session_id: str, user_id: str) -> Session | None`、`save(session: Session) -> None`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_memory_store.py`：

```python
import pytest

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.memory.session import Session
from deepresearch_agent.memory.store import (
    InvalidSessionIdError,
    JsonSessionStore,
    SessionOwnershipError,
)


def _resolved(name: str, code: str) -> CompanyResolution:
    return CompanyResolution(
        status="resolved", legal_name=name, unified_social_credit_code=code, match_type="legal_name"
    )


def test_save_load_round_trip_preserves_recent_entities(tmp_path):
    store = JsonSessionStore(tmp_path)
    s = Session(user_id="alice", session_id="sess-1")
    s.note_entity(_resolved("甲公司", "C1"))
    s.note_entity(_resolved("乙公司", "C2"))
    store.save(s)

    loaded = store.load("sess-1", "alice")
    assert loaded is not None
    assert loaded.user_id == "alice"
    assert loaded.session_id == "sess-1"
    assert [r.unified_social_credit_code for r in loaded.recent_entities] == ["C1", "C2"]
    # 载入后仍是最近实体在末尾，指代可用
    assert loaded.resolve_anaphora("它的联系方式呢").unified_social_credit_code == "C2"


def test_load_missing_returns_none(tmp_path):
    assert JsonSessionStore(tmp_path).load("nope", "alice") is None


def test_load_wrong_owner_raises_and_does_not_overwrite(tmp_path):
    store = JsonSessionStore(tmp_path)
    a = Session(user_id="alice", session_id="sess-1")
    a.note_entity(_resolved("甲公司", "C1"))
    store.save(a)
    with pytest.raises(SessionOwnershipError):
        store.load("sess-1", "bob")
    # alice 的会话未被动过
    still = store.load("sess-1", "alice")
    assert [r.unified_social_credit_code for r in still.recent_entities] == ["C1"]


def test_invalid_session_id_rejected_on_load_and_save(tmp_path):
    store = JsonSessionStore(tmp_path)
    with pytest.raises(InvalidSessionIdError):
        store.load("../../etc/passwd", "alice")
    with pytest.raises(InvalidSessionIdError):
        store.save(Session(user_id="alice", session_id="a/b"))


def test_save_is_atomic_and_file_readable(tmp_path):
    store = JsonSessionStore(tmp_path)
    store.save(Session(user_id="alice", session_id="sess-1"))
    # 目标文件存在、无残留临时文件
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "sess-1.json" in files
    assert all(not f.endswith(".tmp") for f in files)


def test_cross_process_persistence_new_store_instance(tmp_path):
    JsonSessionStore(tmp_path).save(
        _session_with("alice", "sess-1", _resolved("甲公司", "C1"))
    )
    # 另一个 store 实例（模拟另一进程）能读回
    loaded = JsonSessionStore(tmp_path).load("sess-1", "alice")
    assert [r.unified_social_credit_code for r in loaded.recent_entities] == ["C1"]


def _session_with(user_id, session_id, *entities):
    s = Session(user_id=user_id, session_id=session_id)
    for e in entities:
        s.note_entity(e)
    return s
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_store.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: FAIL（`ModuleNotFoundError: No module named 'deepresearch_agent.memory.store'`）

- [ ] **Step 3: 实现**

新建 `src/deepresearch_agent/memory/store.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_memory_store.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: PASS（6 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/memory/store.py tests/test_memory_store.py
git commit -m "功能：JsonSessionStore 跨进程会话存储(ownership 校验+格式防穿越+原子写)"
```

---

### Task 2: `execute_turn` 重构

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`
- Test: `tests/test_execute_turn.py`

**Interfaces:**
- Produces: `execute_turn(app, question, domain, session=None, memory=None, enable_memory=False, tracer=None) -> ResearchState`
- `run_research` 内部改为委托 `execute_turn`（签名/行为不变）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_execute_turn.py`：

```python
from deepresearch_agent.agents.graph import build_graph, execute_turn
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.session import Session
from pathlib import Path

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def _app(db_path):
    domain_pack = load_domain_pack(Path("domains") / "procurement" / "domain.yaml")
    return build_graph(domain_pack, CompanyRepository(db_path))


def test_execute_turn_coreference(company_database_path):
    app = _app(company_database_path)
    session = Session(user_id="u", session_id="s")
    memory = MemoryService(FakeMemoryBackend())

    s1 = execute_turn(app, ENTITY, "procurement", session=session, memory=memory, enable_memory=True)
    assert s1.supplier_resolution.unified_social_credit_code == CODE

    s2 = execute_turn(
        app, "它的联系方式呢", "procurement", session=session, memory=memory, enable_memory=True
    )
    assert s2.supplier_resolution.unified_social_credit_code == CODE


def test_execute_turn_memory_off_is_plain(company_database_path):
    app = _app(company_database_path)
    state = execute_turn(app, ENTITY, "procurement")
    assert state.report is not None
    assert state.preresolved is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_execute_turn.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: FAIL（`ImportError: cannot import name 'execute_turn'`）

- [ ] **Step 3: 重构 graph.py**

在 `src/deepresearch_agent/agents/graph.py`，`run_compiled` 之后加 `execute_turn`：

```python
def execute_turn(
    app,
    question: str,
    domain: str,
    session=None,
    memory=None,
    enable_memory: bool = False,
    tracer=None,
) -> ResearchState:
    preresolved = None
    memory_lines: list[str] = []
    if enable_memory and session is not None:
        preresolved = session.resolve_anaphora(question)
        if memory is not None:
            memory_lines = memory.recall(session.user_id, question)

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

把 `run_research` 尾部（从 `preresolved = None` 到最后 `return state` 之间的编排块）替换为委托调用。即把：

```python
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

替换为：

```python
    tracer = get_tracer() if enable_tracing else None
    return execute_turn(
        app,
        question,
        domain,
        session=session,
        memory=memory,
        enable_memory=enable_memory,
        tracer=tracer,
    )
```

（`_report_summary`/`_surface_memory` 已在文件中，`execute_turn` 直接用。）

- [ ] **Step 4: 跑测试确认通过 + 现有记忆/追踪回归**

Run: `.\.conda-env\python.exe -m pytest tests/test_execute_turn.py tests/test_memory_integration.py tests/test_observability.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: PASS（新 2 + 记忆 5 + 追踪若干，全绿）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/agents/graph.py tests/test_execute_turn.py
git commit -m "重构：抽 execute_turn 复用记忆编排(run_research 委托，行为不变)"
```

---

### Task 3: API `POST /session/turn`

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_api_session.py`

**Interfaces:**
- Consumes: `execute_turn`、`JsonSessionStore`/错误类、`MemoryService`/`build_memory_backend`、`Session`。
- Produces:
  - `create_app(database_path=DEFAULT_DATABASE_PATH, memory=None, session_store=None)`
  - `SessionTurnRequest{question, domain="procurement", session_id: str | None = None, user_id}`
  - `SessionTurnResponse{session_id: str, report: SupplierReport}`
  - `POST /session/turn`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api_session.py`：

```python
from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore

ENTITY = "示例科技股份有限公司"
CODE = "91330000123456789X"


def _client(company_database_path, tmp_path):
    app = create_app(
        database_path=company_database_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp_path),
    )
    return TestClient(app)


def test_first_turn_returns_session_id(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]  # 服务端生成并回传
    assert body["report"]["supplier_name"] == ENTITY


def test_second_turn_coreference(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r1 = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"})
    sid = r1.json()["session_id"]
    r2 = client.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert r2.status_code == 200
    assert r2.json()["report"]["supplier_name"] == ENTITY  # 指代到同实体


def test_ownership_blocks_other_user(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    sid = client.post("/session/turn", json={"question": ENTITY, "user_id": "alice"}).json()[
        "session_id"
    ]
    # bob 拿 alice 的 session_id → 404
    r = client.post(
        "/session/turn", json={"question": "它的股东", "user_id": "bob", "session_id": sid}
    )
    assert r.status_code == 404
    # alice 的会话仍在、未被覆写
    ok = client.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert ok.json()["report"]["supplier_name"] == ENTITY


def test_invalid_session_id_400(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post(
        "/session/turn",
        json={"question": ENTITY, "user_id": "alice", "session_id": "../../etc/passwd"},
    )
    assert r.status_code == 400


def test_cross_request_persistence(company_database_path, tmp_path):
    # 两个独立 client 共享同一磁盘 store（模拟跨进程）
    store_dir = tmp_path
    c1 = _client_with_store(company_database_path, store_dir)
    sid = c1.post("/session/turn", json={"question": ENTITY, "user_id": "alice"}).json()[
        "session_id"
    ]
    c2 = _client_with_store(company_database_path, store_dir)
    r = c2.post(
        "/session/turn",
        json={"question": "它的联系方式呢", "user_id": "alice", "session_id": sid},
    )
    assert r.json()["report"]["supplier_name"] == ENTITY


def _client_with_store(db_path, store_dir):
    app = create_app(
        database_path=db_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(store_dir),
    )
    return TestClient(app)


def test_research_endpoint_unchanged(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post("/research", json={"question": ENTITY})
    assert r.status_code == 200
    assert r.json()["supplier_name"] == ENTITY  # 旧端点形状不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_session.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: FAIL（404/无 /session/turn 路由 或 create_app 不接受 memory/session_store）

- [ ] **Step 3: 实现**

把 `src/deepresearch_agent/api.py` 改为：

```python
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, StringConstraints

from deepresearch_agent.agents import graph as graph_module
from deepresearch_agent.agents.graph import DEFAULT_DATABASE_PATH, execute_turn, run_compiled
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.memory.config import build_memory_backend
from deepresearch_agent.memory.service import MemoryService
from deepresearch_agent.memory.session import Session
from deepresearch_agent.memory.store import (
    InvalidSessionIdError,
    JsonSessionStore,
    SessionOwnershipError,
)
from deepresearch_agent.state import SupplierReport


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DEFAULT_SESSIONS_DIR = Path("data/procurement/sessions")


class ResearchRequest(BaseModel):
    question: Question
    domain: str = "procurement"


class SessionTurnRequest(BaseModel):
    question: Question
    user_id: Question
    domain: str = "procurement"
    session_id: str | None = None


class SessionTurnResponse(BaseModel):
    session_id: str
    report: SupplierReport


def create_app(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    memory: MemoryService | None = None,
    session_store: JsonSessionStore | None = None,
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)

    def graph_for(domain: str) -> object:
        if domain not in compiled_graphs:
            domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
            compiled_graphs[domain] = graph_module.build_graph(domain_pack, repository)
        return compiled_graphs[domain]

    @application.post("/research", response_model=SupplierReport)
    def research(request: ResearchRequest) -> SupplierReport:
        state = run_compiled(graph_for(request.domain), request.question, request.domain)
        if state.report is None:
            raise RuntimeError("research graph completed without a report")
        return state.report

    @application.post("/session/turn", response_model=SessionTurnResponse)
    def session_turn(request: SessionTurnRequest) -> SessionTurnResponse:
        user_id = request.user_id
        if request.session_id is None:
            session = Session(user_id=user_id, session_id=uuid.uuid4().hex)
        else:
            try:
                loaded = store.load(request.session_id, user_id)
            except SessionOwnershipError:
                raise HTTPException(status_code=404, detail="session not found")
            except InvalidSessionIdError:
                raise HTTPException(status_code=400, detail="invalid session_id")
            session = loaded or Session(user_id=user_id, session_id=request.session_id)

        state = execute_turn(
            graph_for(request.domain),
            request.question,
            request.domain,
            session=session,
            memory=memory_service,
            enable_memory=True,
        )
        store.save(session)
        if state.report is None:
            raise RuntimeError("session turn completed without a report")
        return SessionTurnResponse(session_id=session.session_id, report=state.report)

    return application


app = create_app()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_session.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess`
Expected: PASS（6 项）

- [ ] **Step 5: 全套回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-apisess-full`
Expected: 全绿（原 224 + 本模块新增；0 失败）

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/api.py tests/test_api_session.py
git commit -m "功能：POST /session/turn 有状态多轮(ownership 授权+跨进程会话+记忆编排)"
```

---

### Task 4: 文档同步

**Files:**
- Modify: `CLAUDE.md`（API 说明补 `/session/turn`）
- Modify: `docs/architecture.md`（接口小节 + 记忆层小节补 API 接入）
- Modify: `docs/project-memory.md`（追加条目 27）
- Modify: `.gitignore`（忽略 `data/procurement/sessions/`）

- [ ] **Step 1: .gitignore**

在 `.gitignore` 的 `data/procurement/derived/` 行之后加：

```
data/procurement/sessions/
```

- [ ] **Step 2: CLAUDE.md**

把「运行 Agent」的 API 注释行：

```markdown
# API（POST /research，body: {"question": "...", "domain": "procurement"}）
```

改为：

```markdown
# API（无状态：POST /research {"question","domain"}；有状态多轮：POST /session/turn {"question","user_id","session_id"?,"domain"?}→{"session_id","report"}）
```

在「注意点」记忆层那条末尾追加一句：

```markdown
API 接入：`POST /session/turn` 有状态多轮（`create_app` 注入 memory/JsonSessionStore），会话缓冲 JSON 文件跨进程持久（`data/procurement/sessions/`，原子写），ownership 授权（owner≠user_id→404 防 IDOR）+ session_id 严格格式（防路径穿越）；`/research` 无状态不变。
```

- [ ] **Step 3: docs/architecture.md**

在「记忆层（`memory/`）」小节末尾（红线那条之后）加：

```markdown
- **API 接入**：`POST /session/turn`（有状态多轮）经 `create_app` 注入 `MemoryService` 与 `JsonSessionStore`（`store.py`，JSON 文件每会话、原子写、跨进程）。授权靠 ownership（存储 owner≠请求 user_id→404，防 IDOR），session_id 严格 `^[A-Za-z0-9_-]{1,64}$` 防路径穿越，`uuid4` 缺省生成并始终回传。记忆编排由 `execute_turn`（`run_research` 与 API 共用）承担。`/research` 无状态一问一答不变。
```

在「接口」小节的 FastAPI 那条之后加：

```markdown
- `POST /session/turn` 为有状态多轮端点：请求体 `user_id` 作 authenticated user（无鉴权层 stand-in），`session_id` 只寻址不授权；响应 `{session_id, report}`。
```

- [ ] **Step 4: docs/project-memory.md**

在条目 26 之后、`## 本地数据状态` 之前加条目 27：

```markdown
27. **/research API 接记忆（跨进程会话 + ownership 授权）**：新 `POST /session/turn` 有状态多轮端点（`/research` 无状态不变）。`memory/store.py` `JsonSessionStore`：会话缓冲 JSON 文件每会话（`data/procurement/sessions/`）、原子写（临时→os.replace）、跨进程；`load(session_id,user_id)` **ownership 校验**（owner≠user_id→`SessionOwnershipError`→404，非泄露式、绝不覆写，防 IDOR）+ **session_id 严格 `^[A-Za-z0-9_-]{1,64}$`**（→`InvalidSessionIdError`→400，防路径穿越）；recent_entities 用 CompanyResolution model_dump/validate 序列化。`agents/graph.py` 抽 `execute_turn(app,question,domain,session,memory,enable_memory,tracer)`（记忆编排从 run_research 搬出，两者共用；run_research 行为不变）。API `create_app(database_path, memory=, session_store=)` 可注入（测试用 FakeMemoryBackend + tmp store，零网络零 key）；`session_id` 缺省 uuid4 生成、始终回传；`enable_memory=True` 恒开、`enable_scope=False`（→SupplierReport）、用缓存图。**身份：请求体 user_id 作 authenticated user stand-in（无真鉴权，后续接 token 中间件）；ownership 绑定+校验本轮建**。测试 TestClient（首轮回 id/次轮指代/用户 B→404 且不覆写/非法 id→400/跨请求持久/旧端点不变）。前端聊天页/真鉴权/会话 TTL 留后续。
```

- [ ] **Step 5: 提交**

```powershell
git add CLAUDE.md docs/architecture.md docs/project-memory.md .gitignore
git commit -m "文档：同步 /session/turn API 接记忆(跨进程会话+ownership)到架构/记忆/CLAUDE"
```

---

## 收尾

四个 Task 完成后用 **superpowers:finishing-a-development-branch**：跑全套测试 → present 合并选项。

**真链路手验（收尾后，用户本地，可选）**：`uvicorn deepresearch_agent.api:app` → `POST /session/turn` 首轮拿 session_id → 次轮 `它...` 验指代 → 设 `DEEPSEEK_API_KEY` 验 mem0 跨会话 recall。

## Self-Review

- **Spec 覆盖**：会话存储（Task1）、ownership+格式防穿越（Task1 test + Task3 API 映射）、execute_turn 复用（Task2）、`/session/turn`（Task3）、`/research` 不变（Task3 test）、跨进程持久（Task1+Task3 test）、身份 user_id（Task3）均有任务。真鉴权/scope/TTL/前端按 spec 明确不做。
- **占位符**：无 TBD；每步含完整代码与命令。
- **类型一致**：`JsonSessionStore.load(session_id, user_id) -> Session | None` / `save(session)`、`SessionOwnershipError`/`InvalidSessionIdError`、`execute_turn(app, question, domain, session=, memory=, enable_memory=, tracer=)`、`create_app(database_path, memory=, session_store=)`、`SessionTurnRequest`/`SessionTurnResponse` 跨 Task 引用一致。`run_compiled(..., preresolved=)` 已在上一模块加、本轮 execute_turn 复用。`Session(user_id, session_id, recent_entities)` 字段与 store 序列化键一致。
