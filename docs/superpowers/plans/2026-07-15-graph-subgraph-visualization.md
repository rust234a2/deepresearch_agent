# 网页图谱子图可视化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 网页聊天在 graph 模式轮次时，把 `hybrid_search` 已取回的股权子图（种子企业/直接股东/对外投资/控制人）通过新 SSE 事件推给前端，在右侧固定面板用手写 SVG 分层布局渲染。

**Architecture:** 后端在 `graph_retrieval.py` 新增纯函数 `project_subgraph` 把 `HybridContext` 投影为 `GraphSubgraph`（节点/边），`_retrieve_graph` 写入 `ResearchState.graph_subgraph`，流式端点在 `report_start` 前发 `graph_subgraph` 事件；前端新增零依赖 `graph.js`（确定性分层布局 + SVG + 缩放/平移/悬停/点击高亮）和右侧可收起面板。

**Tech Stack:** Python 3.11 + Pydantic + FastAPI SSE（后端）；vanilla JS + SVG + CSS 变量（前端，无构建、无第三方库）。

**Spec:** `docs/superpowers/specs/2026-07-14-graph-subgraph-visualization-design.md`

## Global Constraints

- 全程中文沟通，Git 提交信息用中文；每个任务完成即提交一次。
- 数据红线：面板与所有新文案只陈述 payload 字段，线索级证据（"线索级证据 · 须人工复核"），不出现"认定 / 无风险 / 实际控制"表述；`via_person` 标"经自然人关联 · 低置信"。
- 前端零依赖：不引入任何第三方库、CDN、npm 或构建工具。
- 报告文本、`/research` 与 `/session/turn` 非流式响应形状零改动。
- 测试解释器：`.\.conda-env\python.exe -m pytest`（PowerShell；bash 下等价 `./.conda-env/python.exe -m pytest`）。不新建 venv。
- 每种子每方向邻居上限 15 条（常量 `MAX_NEIGHBORS_PER_DIRECTION = 15`）。
- 节点 id 约定沿用仓库现状：企业=信用代码、外部企业=`ext:名称`、自然人=`person:姓名`。

---

### Task 1: `project_subgraph` 投影函数与子图数据模型

**Files:**
- Modify: `src/deepresearch_agent/graph_retrieval.py`
- Test: `tests/test_graph_retrieval.py`

**Interfaces:**
- Consumes: 现有 `HybridContext` / `SeedContext` / `SharedController`（本文件）、`NeighborEdge`（`ownership_backend.py`）、`ControllerResult`（`graph_traversal.py`）。
- Produces（后续任务依赖的确切签名）:
  - `class SubgraphNode(BaseModel)`: `id: str`, `name: str`, `kind: Literal["seed","shareholder","investment","controller"]`, `node_type: str = ""`, `score: float = 0.0`, `is_shared_controller: bool = False`, `concentrated_industries: list[str] = []`
  - `class SubgraphEdge(BaseModel)`: `source: str`, `target: str`, `kind: Literal["shareholding","investment","control_clue"]`, `holding_pct: str | None = None`, `via_person: bool = False`
  - `class GraphSubgraph(BaseModel)`: `nodes: list[SubgraphNode]`, `edges: list[SubgraphEdge]`, `truncated: bool = False`
  - `def project_subgraph(context: HybridContext) -> GraphSubgraph`
  - `MAX_NEIGHBORS_PER_DIRECTION = 15`

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_retrieval.py` 末尾追加（文件已有 `assemble_subgraph_context`/`hybrid_search` 的测试与 fixture，不动）：

```python
# ---------- project_subgraph：HybridContext → 可视化子图 ----------

from deepresearch_agent.graph_retrieval import (  # noqa: E402
    HybridContext,
    SeedContext,
    SharedController,
    project_subgraph,
)
from deepresearch_agent.graph_traversal import ControllerResult  # noqa: E402
from deepresearch_agent.ownership_backend import NeighborEdge  # noqa: E402


def _neighbor(node_id, name, node_type, edge_type, direction, pct=None):
    return NeighborEdge(node_id=node_id, name=name, node_type=node_type,
                        edge_type=edge_type, direction=direction, holding_pct=pct)


def _controller(node_id, name, via_person=False):
    return ControllerResult(node_id=node_id, display_name=name, depth=1, via_person=via_person)


def _seed(code, name, score=0.0, controllers=(), neighbors=()):
    return SeedContext(code=code, name=name, score=score,
                       controllers=list(controllers), neighbors=list(neighbors))


def test_project_subgraph_maps_nodes_and_edges():
    ctx = HybridContext(seeds=[_seed(
        "91A", "甲公司", score=0.9,
        controllers=[_controller("person:张三", "张三", via_person=True)],
        neighbors=[
            _neighbor("ext:基金X", "基金X", "company", "shareholding", "in", "60%"),
            _neighbor("91C", "丙公司", "company", "investment", "out", "30%"),
        ],
    )], shared_controllers=[])

    sub = project_subgraph(ctx)

    kinds = {n.id: n.kind for n in sub.nodes}
    assert kinds == {"91A": "seed", "ext:基金X": "shareholder",
                     "91C": "investment", "person:张三": "controller"}
    types = {n.id: n.node_type for n in sub.nodes}
    assert types["person:张三"] == "person" and types["91A"] == "company"
    seed_node = next(n for n in sub.nodes if n.id == "91A")
    assert seed_node.score == 0.9
    edges = {(e.source, e.target): e for e in sub.edges}
    assert edges[("ext:基金X", "91A")].kind == "shareholding"
    assert edges[("ext:基金X", "91A")].holding_pct == "60%"
    assert edges[("91A", "91C")].kind == "investment"
    clue = edges[("person:张三", "91A")]
    assert clue.kind == "control_clue" and clue.via_person is True
    assert sub.truncated is False


def test_project_subgraph_dedups_prefers_stronger_kind_and_keeps_edges():
    # 张三 既是 甲 的直接股东，又是 甲、乙 的最终控制人 → 一个节点、kind=controller、三条边
    zhang_in = _neighbor("person:张三", "张三", "person", "shareholding", "in", "40%")
    ctx = HybridContext(seeds=[
        _seed("91A", "甲公司", 0.9,
              controllers=[_controller("person:张三", "张三", True)], neighbors=[zhang_in]),
        _seed("91B", "乙公司", 0.8, controllers=[_controller("person:张三", "张三", True)]),
    ], shared_controllers=[])

    sub = project_subgraph(ctx)

    zhang = [n for n in sub.nodes if n.id == "person:张三"]
    assert len(zhang) == 1 and zhang[0].kind == "controller"
    triples = sorted((e.source, e.target, e.kind) for e in sub.edges)
    assert triples == [
        ("person:张三", "91A", "control_clue"),
        ("person:张三", "91A", "shareholding"),
        ("person:张三", "91B", "control_clue"),
    ]


def test_project_subgraph_marks_shared_controllers():
    ctx = HybridContext(
        seeds=[
            _seed("91A", "甲公司", 0.9, controllers=[_controller("ext:集团", "集团")]),
            _seed("91B", "乙公司", 0.8, controllers=[_controller("ext:集团", "集团")]),
        ],
        shared_controllers=[SharedController(
            node_id="ext:集团", name="集团", controlled_seeds=["91A", "91B"],
            via_person=False, concentrated_industries=["机床制造"],
        )],
    )

    sub = project_subgraph(ctx)

    node = next(n for n in sub.nodes if n.id == "ext:集团")
    assert node.is_shared_controller is True
    assert node.concentrated_industries == ["机床制造"]
    assert node.node_type == "company"


def test_project_subgraph_truncates_neighbors_by_pct():
    neighbors = [
        _neighbor(f"ext:股东{i:02d}", f"股东{i:02d}", "company", "shareholding", "in", f"{i}%")
        for i in range(1, 18)  # 17 个直接股东，比例 1%..17%
    ]
    ctx = HybridContext(seeds=[_seed("91A", "甲公司", 0.9, neighbors=neighbors)],
                        shared_controllers=[])

    sub = project_subgraph(ctx)

    holders = {n.id for n in sub.nodes if n.kind == "shareholder"}
    assert len(holders) == 15
    assert "ext:股东17" in holders and "ext:股东03" in holders  # 高比例保留
    assert "ext:股东01" not in holders and "ext:股东02" not in holders  # 最低两个被截断
    assert sub.truncated is True


def test_project_subgraph_empty_context():
    sub = project_subgraph(HybridContext(seeds=[], shared_controllers=[]))
    assert sub.nodes == [] and sub.edges == [] and sub.truncated is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -q`
Expected: FAIL，`ImportError: cannot import name 'project_subgraph'`

- [ ] **Step 3: 实现投影函数**

`src/deepresearch_agent/graph_retrieval.py`：文件顶部 import 区改为：

```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult
from deepresearch_agent.ownership_backend import NeighborEdge, OwnershipGraphBackend
```

文件末尾（`hybrid_search` 之后）追加：

```python
# ---------- 可视化子图投影（供网页图谱面板使用，纯函数、不额外查图） ----------

MAX_NEIGHBORS_PER_DIRECTION = 15

_KIND_PRIORITY = {"seed": 3, "controller": 2, "shareholder": 1, "investment": 0}


class SubgraphNode(BaseModel):
    id: str
    name: str
    kind: Literal["seed", "shareholder", "investment", "controller"]
    node_type: str = ""
    score: float = 0.0
    is_shared_controller: bool = False
    concentrated_industries: list[str] = []


class SubgraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["shareholding", "investment", "control_clue"]
    holding_pct: str | None = None
    via_person: bool = False


class GraphSubgraph(BaseModel):
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]
    truncated: bool = False


def _pct_value(pct: str | None) -> float:
    if not pct:
        return -1.0
    match = re.search(r"\d+(?:\.\d+)?", pct)
    return float(match.group()) if match else -1.0


def project_subgraph(context: HybridContext) -> GraphSubgraph:
    nodes: dict[str, SubgraphNode] = {}
    edges: list[SubgraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    truncated = False

    def upsert(node: SubgraphNode) -> None:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
            return
        keep, other = (node, existing) if (
            _KIND_PRIORITY[node.kind] > _KIND_PRIORITY[existing.kind]
        ) else (existing, node)
        keep.is_shared_controller = keep.is_shared_controller or other.is_shared_controller
        keep.concentrated_industries = keep.concentrated_industries or other.concentrated_industries
        keep.score = max(keep.score, other.score)
        keep.node_type = keep.node_type or other.node_type
        nodes[node.id] = keep

    def add_edge(edge: SubgraphEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append(edge)

    for seed in context.seeds:
        upsert(SubgraphNode(id=seed.code, name=seed.name, kind="seed",
                            node_type="company", score=seed.score))

    shared_meta = {item.node_id: item for item in context.shared_controllers}
    for seed in context.seeds:
        for direction, kind in (("in", "shareholder"), ("out", "investment")):
            picked = sorted(
                (n for n in seed.neighbors if n.direction == direction),
                key=lambda n: (-_pct_value(n.holding_pct), n.node_id),
            )
            if len(picked) > MAX_NEIGHBORS_PER_DIRECTION:
                truncated = True
                picked = picked[:MAX_NEIGHBORS_PER_DIRECTION]
            for neighbor in picked:
                upsert(SubgraphNode(id=neighbor.node_id, name=neighbor.name,
                                    kind=kind, node_type=neighbor.node_type))
                if direction == "in":
                    add_edge(SubgraphEdge(source=neighbor.node_id, target=seed.code,
                                          kind=neighbor.edge_type, holding_pct=neighbor.holding_pct))
                else:
                    add_edge(SubgraphEdge(source=seed.code, target=neighbor.node_id,
                                          kind=neighbor.edge_type, holding_pct=neighbor.holding_pct))
        for controller in seed.controllers:
            shared = shared_meta.get(controller.node_id)
            upsert(SubgraphNode(
                id=controller.node_id,
                name=controller.display_name,
                kind="controller",
                node_type="person" if controller.node_id.startswith("person:") else "company",
                is_shared_controller=shared is not None,
                concentrated_industries=list(shared.concentrated_industries) if shared else [],
            ))
            add_edge(SubgraphEdge(source=controller.node_id, target=seed.code,
                                  kind="control_clue", via_person=controller.via_person))

    return GraphSubgraph(nodes=list(nodes.values()), edges=edges, truncated=truncated)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -q`
Expected: 全部 PASS（原有 6 项 + 新增 5 项）

- [ ] **Step 5: 静态门禁 + 提交**

Run: `.\.conda-env\python.exe -m ruff check src/deepresearch_agent/graph_retrieval.py tests/test_graph_retrieval.py; .\.conda-env\python.exe -m mypy src/deepresearch_agent/graph_retrieval.py`
Expected: 无报错（若 black 有格式意见按其输出修正）

```powershell
git add src/deepresearch_agent/graph_retrieval.py tests/test_graph_retrieval.py
git commit -m "图谱可视化：HybridContext 到子图节点/边的纯函数投影"
```

---

### Task 2: `ResearchState.graph_subgraph` 字段与 researcher 填充

**Files:**
- Modify: `src/deepresearch_agent/state.py`（字段 + import）
- Modify: `src/deepresearch_agent/agents/nodes.py:232-244`（`_retrieve_graph`）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: Task 1 的 `GraphSubgraph`、`project_subgraph`。
- Produces: `ResearchState.graph_subgraph: GraphSubgraph | None = None`（Task 3 读取）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加（`_repository`、`_ScopeRetriever`、`planner_node`、`researcher_node`、`ToolRegistry`、`DOMAIN_PACK`、`ResearchState` 均已在该文件 import/定义）：

```python
def test_retrieve_graph_populates_subgraph():
    from deepresearch_agent.agents.nodes import _retrieve_graph
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext
    from deepresearch_agent.graph_traversal import ControllerResult
    from deepresearch_agent.ownership_backend import NeighborEdge

    def searcher(query):
        return HybridContext(query=query, seeds=[SeedContext(
            code="X", name="示例", score=0.9,
            controllers=[ControllerResult(node_id="person:张三", display_name="张三",
                                          depth=1, via_person=True)],
            neighbors=[NeighborEdge(node_id="ext:基金", name="基金", node_type="company",
                                    edge_type="shareholding", direction="in",
                                    holding_pct="60%")],
        )], shared_controllers=[])

    state = ResearchState(question="q", domain="procurement")
    assert _retrieve_graph(state, searcher) is None
    assert state.graph_subgraph is not None
    assert {n.id for n in state.graph_subgraph.nodes} == {"X", "person:张三", "ext:基金"}
    assert len(state.graph_subgraph.edges) == 2


def test_graph_runtime_failure_leaves_subgraph_none(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    def boom(query):
        raise RuntimeError("graph down")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), graph_searcher=boom,
        scope_enabled=True, graph_enabled=True,
    )
    assert updated.retrieval_mode == "scope"  # 降级路径
    assert updated.graph_subgraph is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_retrieve_graph_populates_subgraph -q`
Expected: FAIL，`AttributeError`/pydantic 报 `graph_subgraph` 字段不存在

- [ ] **Step 3: 实现**

`src/deepresearch_agent/state.py`：import 区加一行（放在 `company_models` import 之后）：

```python
from deepresearch_agent.graph_retrieval import GraphSubgraph
```

`ResearchState` 里 `shared_controllers` 字段之后加：

```python
    graph_subgraph: GraphSubgraph | None = None
```

`src/deepresearch_agent/agents/nodes.py`：import 区加：

```python
from deepresearch_agent.graph_retrieval import project_subgraph
```

`_retrieve_graph` 成功分支（`state.shared_controllers = shared` 之后、`return None` 之前）加一行：

```python
    state.graph_subgraph = project_subgraph(context)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py tests/test_state.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 静态门禁 + 提交**

Run: `.\.conda-env\python.exe -m ruff check src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py; .\.conda-env\python.exe -m mypy src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py`
Expected: 无报错

```powershell
git add src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "图谱可视化：研究状态携带检索子图，降级路径保持为空"
```

---

### Task 3: 流式端点新增 `graph_subgraph` SSE 事件

**Files:**
- Modify: `src/deepresearch_agent/api.py:199-204`（`events()` 的 complete 分支）
- Test: `tests/test_api_stream_retrieval.py`

**Interfaces:**
- Consumes: Task 2 的 `state.graph_subgraph`；现有 `_sse(event, data)`、`state.retrieval_mode`。
- Produces: SSE 事件 `graph_subgraph`，data 为 `GraphSubgraph.model_dump()`（`{"nodes": [...], "edges": [...], "truncated": bool}`），位于 `report_start` 之前。前端（Task 5）按此事件名订阅。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_stream_retrieval.py` 末尾追加（`_client`、`_ScopeRetriever` 已在该文件定义）：

```python
def _event_payload(body: str, event: str):
    import json
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"event: {event}":
            return json.loads(lines[i + 1].removeprefix("data:").strip())
    return None


def test_stream_emits_graph_subgraph_before_report(company_database_path, tmp_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext
    from deepresearch_agent.graph_traversal import ControllerResult
    from deepresearch_agent.ownership_backend import NeighborEdge

    def build_scope(database_path, index_path):
        return _ScopeRetriever()

    def build_graph(database_path, scope_retriever):
        def search(query):
            return HybridContext(query=query, seeds=[SeedContext(
                code="91330000123456789X", name="示例科技股份有限公司", score=0.95,
                controllers=[ControllerResult(node_id="person:张三", display_name="张三",
                                              depth=1, via_person=True)],
                neighbors=[NeighborEdge(node_id="person:张三", name="张三", node_type="person",
                                        edge_type="shareholding", direction="in",
                                        holding_pct="60%")],
            )], shared_controllers=[])
        return search

    monkeypatch.setattr(graph_module, "_build_scope_retriever", build_scope)
    monkeypatch.setattr(graph_module, "_build_graph_searcher", build_graph)
    client = _client(company_database_path, tmp_path, polisher=None,
                     enable_scope=True, enable_graph=True)

    with client.stream("POST", "/session/turn/stream",
                       json={"question": "哪些做注塑的供应商互相关联", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())

    assert "event: graph_subgraph" in body
    assert body.index("event: graph_subgraph") < body.index("event: report_start")
    payload = _event_payload(body, "graph_subgraph")
    assert {n["id"] for n in payload["nodes"]} == {"91330000123456789X", "person:张三"}
    assert payload["truncated"] is False


def test_stream_named_mode_has_no_graph_subgraph_event(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "graph_subgraph" not in body


def test_stream_scope_mode_has_no_graph_subgraph_event(company_database_path, tmp_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "_build_scope_retriever",
                        lambda database_path, index_path: _ScopeRetriever())
    client = _client(company_database_path, tmp_path, polisher=None,
                     enable_scope=True, enable_graph=False)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "哪些企业能做注塑成型", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "graph_subgraph" not in body
    assert "event: report_start" in body
```

说明：`哪些做注塑的供应商互相关联` 在无 LLM 时启发式分类为 `medium`（见 `tests/test_nodes.py::test_planner_complexity_falls_back_to_heuristic`），且不含库内企业名 → 走 graph 模式。

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py::test_stream_emits_graph_subgraph_before_report -q`
Expected: FAIL，`assert "event: graph_subgraph" in body` 断言失败

- [ ] **Step 3: 实现**

`src/deepresearch_agent/api.py`，`events()` 内 complete 分支，`report_type, report = _resolve_report(state)` 之后、`yield _sse("report_start", ...)` 之前插入：

```python
                if (
                    state.retrieval_mode == "graph"
                    and state.graph_subgraph is not None
                    and state.graph_subgraph.nodes
                ):
                    yield _sse("graph_subgraph", state.graph_subgraph.model_dump())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py tests/test_api_stream.py tests/test_api.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 静态门禁 + 提交**

Run: `.\.conda-env\python.exe -m ruff check src/deepresearch_agent/api.py tests/test_api_stream_retrieval.py; .\.conda-env\python.exe -m mypy src/deepresearch_agent/api.py`
Expected: 无报错

```powershell
git add src/deepresearch_agent/api.py tests/test_api_stream_retrieval.py
git commit -m "图谱可视化：流式端点在报告前推送 graph_subgraph 事件"
```

---

### Task 4: 前端面板——DOM、样式与 SVG 渲染/交互（graph.js）

**Files:**
- Modify: `src/deepresearch_agent/web/index.html`
- Modify: `src/deepresearch_agent/web/style.css`
- Create: `src/deepresearch_agent/web/graph.js`
- Test: `tests/test_api_web.py`

**Interfaces:**
- Consumes: Task 3 的 SSE `graph_subgraph` payload 形状（`nodes[].{id,name,kind,node_type,score,is_shared_controller,concentrated_industries}`、`edges[].{source,target,kind,holding_pct,via_person}`、`truncated`）。
- Produces: 全局 `window.GraphPanel = { render(payload), clear() }`（Task 5 的 app.js 调用）；DOM id：`graph-panel`、`graph-svg`、`graph-empty`、`graph-legend`、`graph-foot`、`graph-tooltip`、`graph-collapse`、`graph-toggle`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_web.py` 末尾追加：

```python
def test_web_includes_graph_panel(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/")
    assert 'id="graph-panel"' in r.text
    assert "线索级证据 · 须人工复核" in r.text
    assert 'id="graph-toggle"' in r.text
    assert "/static/graph.js" in r.text


def test_static_graph_js_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/graph.js")
    assert r.status_code == 200
    assert "window.GraphPanel" in r.text
    assert "认定" not in r.text  # 数据红线：面板代码不含认定式文案
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q`
Expected: 新增 2 项 FAIL（404 / 断言失败），原有项 PASS

- [ ] **Step 3: index.html 加面板与入口**

`src/deepresearch_agent/web/index.html` 两处修改。

其一：顶栏主题按钮 `id="theme"` 的 `<button>` 之前插入（窄屏抽屉开关，默认隐藏，graph.js 在有数据时显示）：

```html
        <button class="iconbtn graph-toggle" id="graph-toggle" title="查看股权图谱" aria-label="查看股权图谱" hidden>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="6" cy="6" r="2.6"/><circle cx="18" cy="7" r="2.6"/><circle cx="12" cy="18" r="2.6"/><path d="M7.8 7.4L10.5 16M16.4 8.8l-3 7.4M8.6 6.3l6.8.5"/></svg>
        </button>
```

其二：`.app` 的收尾 `</div>`（`</footer>` 之后那个）与 `</div><!-- app-shell 收尾 -->` 之间插入面板（即 `.app-shell` 的第三个子元素）：

```html
    <aside class="graph-panel" id="graph-panel" aria-label="股权图谱线索">
      <div class="graph-head">
        <div>
          <div class="graph-title">股权图谱线索</div>
          <div class="graph-sub">线索级证据 · 须人工复核</div>
        </div>
        <button class="iconbtn graph-collapse" id="graph-collapse" title="收起图谱面板" aria-label="收起图谱面板">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>
        </button>
      </div>
      <div class="graph-legend" id="graph-legend" hidden>
        <span class="lg pill">企业</span>
        <span class="lg square">自然人</span>
        <span class="lg solid">持股 / 投资</span>
        <span class="lg dashed">控制线索</span>
        <span class="lg shared">同行业+同控制人</span>
      </div>
      <div class="graph-canvas-wrap">
        <svg id="graph-svg" role="img" aria-label="股权图谱子图"></svg>
        <div class="graph-tooltip" id="graph-tooltip" hidden></div>
        <p class="graph-empty" id="graph-empty">发起“哪些供应商互相关联”这类图谱检索后，这里会展示本次检索涉及的节点和边。</p>
      </div>
      <p class="graph-foot" id="graph-foot" hidden>部分直接股东/投资未展示。</p>
    </aside>
```

并把脚本引入改为（graph.js 在 app.js 之前）：

```html
  <script src="/static/graph.js" defer></script>
  <script src="/static/app.js" defer></script>
```

- [ ] **Step 4: style.css 加面板样式与窄屏抽屉**

`src/deepresearch_agent/web/style.css` 末尾（`@media (max-width: 560px)` 规则之前）追加：

```css
/* 股权图谱面板 */
.graph-panel { display: flex; flex: 0 0 380px; flex-direction: column; min-width: 0; border-left: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 88%, var(--bg)); transition: flex-basis .22s ease; }
/* 宽屏收起（窄屏走抽屉，不用 collapsed） */
@media (min-width: 1101px) {
  .graph-panel.collapsed { flex-basis: 46px; }
  .graph-panel.collapsed .graph-legend, .graph-panel.collapsed .graph-canvas-wrap,
  .graph-panel.collapsed .graph-foot, .graph-panel.collapsed .graph-head > div { display: none; }
  .graph-panel.collapsed .graph-collapse svg { transform: rotate(180deg); }
}
.graph-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; padding: 18px 14px 10px; }
.graph-title { font-size: 14px; font-weight: 700; letter-spacing: .01em; }
.graph-sub { margin-top: 2px; color: var(--warn); font-family: var(--mono); font-size: 10.5px; letter-spacing: .05em; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 6px 10px; padding: 0 14px 10px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 11px; }
.graph-legend .lg { display: inline-flex; align-items: center; gap: 5px; }
.graph-legend .lg::before { content: ""; width: 14px; height: 9px; border: 1.5px solid var(--line-strong); background: var(--surface); }
.graph-legend .pill::before { border-radius: 999px; }
.graph-legend .square::before { border-radius: 2px; }
.graph-legend .solid::before { height: 0; border: 0; border-top: 2px solid var(--line-strong); }
.graph-legend .dashed::before { height: 0; border: 0; border-top: 2px dashed var(--line-strong); }
.graph-legend .shared::before { border-color: var(--bad); background: color-mix(in srgb, var(--bad) 14%, var(--surface)); }
.graph-canvas-wrap { position: relative; flex: 1 1 auto; min-height: 0; }
#graph-svg { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
#graph-svg:active { cursor: grabbing; }
.graph-empty { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; padding: 0 22px; color: var(--muted); font-size: 12.5px; line-height: 1.7; text-align: center; }
.graph-tooltip { position: absolute; z-index: 5; max-width: 200px; padding: 8px 10px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); box-shadow: var(--shadow); color: var(--fg-soft); font-size: 12px; line-height: 1.6; white-space: pre-line; pointer-events: none; }
.graph-foot { margin: 0; padding: 8px 14px 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; }

/* 图谱 SVG 元素（颜色全部走主题变量） */
.gnode { cursor: pointer; }
.gnode rect { fill: var(--surface); stroke: var(--line-strong); stroke-width: 1.4; }
.gnode text { fill: var(--fg-soft); font: 600 12px var(--sans); }
.gnode.seed rect { fill: var(--accent-soft); stroke: var(--accent); }
.gnode.seed text { fill: var(--accent-ink); }
.gnode.controller rect { fill: var(--warn-soft); stroke: var(--warn-line); }
.gnode.shared rect { fill: color-mix(in srgb, var(--bad) 10%, var(--surface)); stroke: var(--bad); }
.gnode.shared text { fill: var(--bad); }
.gedge path { stroke: var(--line-strong); stroke-width: 1.4; }
.gedge.control_clue path { stroke-dasharray: 5 4; }
.gedge.shared path { stroke: var(--bad); }
.gedge .pct { fill: var(--muted); font: 10.5px var(--mono); text-anchor: middle; }
#graph-svg.has-sel .gedge:not(.hl) { opacity: .18; }
#graph-svg.has-sel .gnode:not(.sel) { opacity: .3; }
.gedge.hl path { stroke: var(--accent); stroke-width: 2; }
.gedge.shared.hl path { stroke: var(--bad); }

/* 窄屏：面板变覆盖式抽屉，顶栏出现开关 */
.graph-toggle { display: none; }
@media (max-width: 1100px) {
  .graph-panel { position: fixed; inset: 0 0 0 auto; z-index: 40; width: min(88vw, 400px); transform: translateX(104%); border-left: 1px solid var(--line); background: var(--surface); box-shadow: -18px 0 44px rgba(0,0,0,.18); transition: transform .22s ease; }
  .graph-panel.open { transform: translateX(0); }
  .graph-toggle { display: inline-grid; }
  .graph-toggle[hidden] { display: none; }
}
```

- [ ] **Step 5: 新建 graph.js（完整文件）**

`src/deepresearch_agent/web/graph.js`：

```js
/* 股权图谱线索面板：确定性分层布局 + 手写 SVG，零依赖。
   只陈述 graph_subgraph 载荷里的字段；线索级证据，须人工复核。 */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const NODE_W = 150, NODE_H = 34, GAP_X = 24, ROW_GAP = 112, PAD = 48;
  const KIND_LABEL = {
    seed: "候选企业",
    shareholder: "直接股东",
    investment: "对外投资",
    controller: "最终控制人 · 线索",
  };
  const EDGE_LABEL = { shareholding: "持股", investment: "投资", control_clue: "控制线索" };

  const panel = document.getElementById("graph-panel");
  const svg = document.getElementById("graph-svg");
  const emptyEl = document.getElementById("graph-empty");
  const legendEl = document.getElementById("graph-legend");
  const footEl = document.getElementById("graph-foot");
  const tooltip = document.getElementById("graph-tooltip");
  const collapseBtn = document.getElementById("graph-collapse");
  const toggleBtn = document.getElementById("graph-toggle");

  let view = null;      // 当前 viewBox {x,y,w,h}
  let selected = null;  // 选中节点 id

  function svgEl(tag, attrs, text) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  const short = (s, max) => (s && s.length > max ? s.slice(0, max - 1) + "…" : s || "");

  // ---- 布局：kind 定行（共享控制人 / 控制人+股东 / 种子 / 对外投资），列按相连种子聚簇 ----
  function layout(payload) {
    const rowOf = (n) => {
      if (n.kind === "seed") return 2;
      if (n.kind === "investment") return 3;
      return n.is_shared_controller ? 0 : 1;
    };
    const rows = [[], [], [], []];
    payload.nodes.forEach((n) => rows[rowOf(n)].push(n));
    rows[2].sort((a, b) => (b.score - a.score) || (a.id < b.id ? -1 : 1));
    const seedCol = new Map(rows[2].map((n, i) => [n.id, i]));
    const anchors = new Map();
    payload.edges.forEach((e) => {
      const seed = seedCol.has(e.source) ? e.source : (seedCol.has(e.target) ? e.target : null);
      const other = seed === e.source ? e.target : e.source;
      if (seed == null || seedCol.has(other)) return;
      if (!anchors.has(other)) anchors.set(other, []);
      anchors.get(other).push(seedCol.get(seed));
    });
    const anchorOf = (id) => {
      const a = anchors.get(id);
      return a && a.length ? a.reduce((x, y) => x + y, 0) / a.length : Number.MAX_SAFE_INTEGER;
    };
    [0, 1, 3].forEach((r) =>
      rows[r].sort((a, b) => (anchorOf(a.id) - anchorOf(b.id)) || (a.id < b.id ? -1 : 1)));

    const liveRows = [0, 1, 2, 3].filter((r) => rows[r].length);
    const rowY = new Map(liveRows.map((r, i) => [r, PAD + i * ROW_GAP]));
    const cols = Math.max(...liveRows.map((r) => rows[r].length));
    const width = PAD * 2 + cols * NODE_W + (cols - 1) * GAP_X;
    const xy = new Map();
    liveRows.forEach((r) => {
      const rowW = rows[r].length * NODE_W + (rows[r].length - 1) * GAP_X;
      rows[r].forEach((n, i) => xy.set(n.id, {
        x: (width - rowW) / 2 + i * (NODE_W + GAP_X),
        y: rowY.get(r),
      }));
    });
    return { xy, width, height: PAD * 2 + (liveRows.length - 1) * ROW_GAP + NODE_H };
  }

  function edgePath(a, b) {
    const sx = a.x + NODE_W / 2, tx = b.x + NODE_W / 2;
    if (a.y === b.y) {  // 同行相连（如种子间投资）：上方绕行
      return `M ${sx} ${a.y} C ${sx} ${a.y - 56}, ${tx} ${b.y - 56}, ${tx} ${b.y}`;
    }
    const down = a.y < b.y;
    const sy = down ? a.y + NODE_H : a.y;
    const ty = down ? b.y : b.y + NODE_H;
    const my = (sy + ty) / 2;
    return `M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`;
  }

  // ---- tooltip ----
  function showTooltip(n, ev) {
    const lines = [n.name, (KIND_LABEL[n.kind] || n.kind) + " · " + (n.node_type === "person" ? "自然人" : "企业")];
    if (n.kind === "seed" && n.score) lines.push("检索得分 " + Number(n.score).toFixed(2));
    if (n.is_shared_controller) {
      lines.push(n.concentrated_industries && n.concentrated_industries.length
        ? "同行业+同控制人线索：" + n.concentrated_industries.join("、") + " · 须人工复核"
        : "控制多家候选企业 · 须人工复核");
    }
    tooltip.textContent = lines.join("\n");
    tooltip.hidden = false;
    moveTooltip(ev);
  }
  function moveTooltip(ev) {
    const box = svg.parentElement.getBoundingClientRect();
    tooltip.style.left = Math.max(0, Math.min(ev.clientX - box.left + 12, box.width - 180)) + "px";
    tooltip.style.top = (ev.clientY - box.top + 12) + "px";
  }
  function hideTooltip() { tooltip.hidden = true; }

  // ---- 点击高亮相邻边 ----
  function toggleSelect(id, incident) {
    if (selected === id) { clearSelect(); return; }
    selected = id;
    svg.classList.add("has-sel");
    svg.querySelectorAll(".hl, .sel").forEach((el) => el.classList.remove("hl", "sel"));
    const hit = new Set([id]);
    (incident.get(id) || []).forEach((g) => {
      g.classList.add("hl");
      hit.add(g.dataset.source); hit.add(g.dataset.target);
    });
    svg.querySelectorAll(".gnode").forEach((el) => {
      if (hit.has(el.dataset.id)) el.classList.add("sel");
    });
  }
  function clearSelect() {
    selected = null;
    svg.classList.remove("has-sel");
    svg.querySelectorAll(".hl, .sel").forEach((el) => el.classList.remove("hl", "sel"));
  }

  // ---- 渲染 ----
  function render(payload) {
    if (!payload || !Array.isArray(payload.nodes) || !payload.nodes.length) return;
    clearSelect();
    svg.replaceChildren();
    const { xy, width, height } = layout(payload);
    const root = svgEl("g", { class: "graph-root" });
    svg.appendChild(root);

    const sharedIds = new Set(
      payload.nodes.filter((n) => n.is_shared_controller).map((n) => n.id));
    const incident = new Map(); // 节点 id → 关联边 <g> 列表
    (payload.edges || []).forEach((e) => {
      const a = xy.get(e.source), b = xy.get(e.target);
      if (!a || !b) return;
      const shared = e.kind === "control_clue" && sharedIds.has(e.source);
      const g = svgEl("g", { class: "gedge " + e.kind + (shared ? " shared" : "") });
      g.dataset.source = e.source; g.dataset.target = e.target;
      const path = svgEl("path", { d: edgePath(a, b), fill: "none" });
      path.appendChild(svgEl("title", {}, e.kind === "control_clue"
        ? EDGE_LABEL[e.kind] + (e.via_person ? " · 经自然人关联 · 低置信" : "") + " · 须人工复核"
        : EDGE_LABEL[e.kind] + (e.holding_pct ? " " + e.holding_pct : "")));
      g.appendChild(path);
      if (e.holding_pct) {
        g.appendChild(svgEl("text", {
          x: (a.x + b.x) / 2 + NODE_W / 2,
          y: (Math.min(a.y, b.y) + Math.max(a.y, b.y) + NODE_H) / 2 - 4,
          class: "pct",
        }, e.holding_pct));
      }
      root.appendChild(g);
      [e.source, e.target].forEach((id) => {
        if (!incident.has(id)) incident.set(id, []);
        incident.get(id).push(g);
      });
    });

    payload.nodes.forEach((n) => {
      const p = xy.get(n.id);
      const cls = ["gnode", n.kind, n.node_type === "person" ? "person" : "company"];
      if (n.is_shared_controller) cls.push("shared");
      const g = svgEl("g", { class: cls.join(" "), transform: `translate(${p.x} ${p.y})` });
      g.dataset.id = n.id;
      g.appendChild(svgEl("rect", {
        width: NODE_W, height: NODE_H,
        rx: n.node_type === "person" ? 4 : NODE_H / 2,  // 图例：○ 企业 / □ 自然人
      }));
      g.appendChild(svgEl("text", {
        x: NODE_W / 2, y: NODE_H / 2 + 4, "text-anchor": "middle",
      }, short(n.name, 10)));
      g.addEventListener("mouseenter", (ev) => showTooltip(n, ev));
      g.addEventListener("mousemove", moveTooltip);
      g.addEventListener("mouseleave", hideTooltip);
      g.addEventListener("click", (ev) => { ev.stopPropagation(); toggleSelect(n.id, incident); });
      root.appendChild(g);
    });

    view = { x: 0, y: 0, w: width, h: height };
    applyView();
    panel.classList.add("has-data");
    legendEl.hidden = false;
    emptyEl.hidden = true;
    footEl.hidden = !payload.truncated;
    toggleBtn.hidden = false;
  }

  function clear() {
    svg.replaceChildren();
    view = null;
    clearSelect();
    hideTooltip();
    panel.classList.remove("has-data", "open");
    legendEl.hidden = true;
    emptyEl.hidden = false;
    footEl.hidden = true;
    toggleBtn.hidden = true;
  }

  // ---- 缩放 / 平移（操作 viewBox） ----
  function applyView() {
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  }
  svg.addEventListener("wheel", (ev) => {
    if (!view) return;
    ev.preventDefault();
    const factor = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
    const box = svg.getBoundingClientRect();
    const px = view.x + ((ev.clientX - box.left) / box.width) * view.w;
    const py = view.y + ((ev.clientY - box.top) / box.height) * view.h;
    const w = Math.max(120, Math.min(view.w * factor, 20000));
    const h = w * (view.h / view.w);
    view = { x: px - (px - view.x) * (w / view.w), y: py - (py - view.y) * (h / view.h), w, h };
    applyView();
  }, { passive: false });
  /* 不用 setPointerCapture：捕获会把拖后 click 重定向到 svg，破坏节点点击。
     以 3px 阈值区分点击与拖拽，拖出画布即结束拖拽。 */
  let drag = null, dragMoved = false;
  svg.addEventListener("pointerdown", (ev) => {
    if (!view) return;
    drag = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y };
    dragMoved = false;
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag || !view) return;
    if (!dragMoved && Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) <= 3) return;
    dragMoved = true;
    const box = svg.getBoundingClientRect();
    view.x = drag.vx - (ev.clientX - drag.x) * (view.w / box.width);
    view.y = drag.vy - (ev.clientY - drag.y) * (view.h / box.height);
    applyView();
  });
  svg.addEventListener("pointerup", () => { drag = null; });
  svg.addEventListener("pointerleave", () => { drag = null; });
  svg.addEventListener("click", () => {
    if (dragMoved) { dragMoved = false; return; }  // 拖拽结束的 click 不清除选中
    clearSelect();
  });

  // ---- 面板收起 / 窄屏抽屉 ----
  collapseBtn.addEventListener("click", () => {
    if (matchMedia("(max-width: 1100px)").matches) panel.classList.remove("open");
    else panel.classList.toggle("collapsed");
  });
  toggleBtn.addEventListener("click", () => panel.classList.toggle("open"));

  window.GraphPanel = { render, clear };
})();
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q`
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```powershell
git add src/deepresearch_agent/web/index.html src/deepresearch_agent/web/style.css src/deepresearch_agent/web/graph.js tests/test_api_web.py
git commit -m "图谱可视化：右侧面板与零依赖 SVG 分层渲染（缩放/平移/悬停/高亮）"
```

---

### Task 5: app.js 接线——订阅事件、会话切换清空

**Files:**
- Modify: `src/deepresearch_agent/web/app.js`
- Test: `tests/test_api_web.py`

**Interfaces:**
- Consumes: Task 4 的 `window.GraphPanel.render(payload)` / `window.GraphPanel.clear()`；Task 3 的 SSE 事件名 `graph_subgraph`。
- Produces: 无（终端消费者）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_web.py` 末尾追加：

```python
def test_web_script_wires_graph_subgraph_event(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/app.js")
    assert 'event === "graph_subgraph"' in r.text
    assert "GraphPanel.render" in r.text
    assert "GraphPanel.clear" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py::test_web_script_wires_graph_subgraph_event -q`
Expected: FAIL，断言失败

- [ ] **Step 3: 实现（app.js 四处小改）**

其一，`submit()` 的 `onEvent` 链里，`else if (event === "progress") ...` 与 `else if (event === "report_start") {` 之间插入：

```js
        else if (event === "graph_subgraph") {
          if (window.GraphPanel) GraphPanel.render(data);
        }
```

其二，`startNewConversation()` 里 `entries = [];` 之后加：

```js
    if (window.GraphPanel) GraphPanel.clear();
```

其三，`openSession(id)` 里 `entries = ...;` 之后加：

```js
    if (window.GraphPanel) GraphPanel.clear();
```

其四，身份切换 handler（`$("#identity").addEventListener` 内）`transcripts = loadTranscripts();` 之后加：

```js
      if (window.GraphPanel) GraphPanel.clear();
```

另外 `deleteSession(item)` 中删除的是当前会话的分支（`sessionId = null; entries = [];` 处）也加：

```js
        if (window.GraphPanel) GraphPanel.clear();
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/web/app.js tests/test_api_web.py
git commit -m "图谱可视化：网页订阅 graph_subgraph 事件并在会话切换时清空面板"
```

---

### Task 6: 全量回归、端到端手动验证与文档更新

**Files:**
- Modify: `CLAUDE.md`（运行 Agent 一节的网页说明）
- Modify: `docs/architecture.md`（流式端点/前端一节）

**Interfaces:**
- Consumes: Task 1–5 全部产物。
- Produces: 无（验证与文档）。

- [ ] **Step 1: 全量测试**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: 全部 PASS（原 67 项 + 本计划新增约 12 项），0 failed

- [ ] **Step 2: 静态门禁全量**

Run: `.\.conda-env\python.exe -m ruff check src tests; .\.conda-env\python.exe -m black --check src tests; .\.conda-env\python.exe -m mypy src`
Expected: 无报错（black 报格式就 `-m black src tests` 格式化后重跑测试）

- [ ] **Step 3: 端到端手动验证（真实栈：Neo4j + FAISS 索引 + 本地 SQLite）**

```powershell
# 前置：docker compose up -d（Neo4j），已构建 companies.sqlite3 与 scope_index.faiss
.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload
```

浏览器打开 `http://127.0.0.1:8000/`，逐项核对：

1. 初始状态：右侧面板显示空状态文案，顶栏无图谱开关（宽屏下本就隐藏）。
2. 输入关系类问题（如「哪些做精密结构件的供应商互相关联」）：报告开始流式输出**之前**面板亮出图谱；种子在中行、股东/控制人在上、对外投资在下；持股比例标在边上；控制线索为虚线。
3. 若命中共享控制人：节点/边红色高亮，悬停显示"须人工复核"提示。
4. 交互：滚轮缩放、拖拽平移、悬停 tooltip、点击节点高亮相邻边、点空白取消。
5. 收起按钮可收起/展开面板；把窗口缩到 <1100px，面板变抽屉、顶栏出现开关按钮。
6. 输入具名核验问题（如「核验万马科技股份有限公司」）：面板保持上一张图不变。
7. 新建对话：面板回到空状态。
8. 深浅主题切换：图谱颜色跟随主题。

任何一步不符即回到对应 Task 修复后重验。

- [ ] **Step 4: 文档更新**

`CLAUDE.md` 运行 Agent 一节，网页流式端点那行注释末尾补一句（保持原行内容不动，另起一行注释）：

```
# graph 模式轮次会先推 SSE 事件 graph_subgraph（检索子图节点/边），网页右侧面板据此渲染股权图谱线索（线索级、须人工复核）
```

`docs/architecture.md` 两处：

其一，「接口」一节 **Web 聊天界面** 条目里把托管文件清单 `web/{index.html,style.css,app.js}` 改为 `web/{index.html,style.css,app.js,graph.js}`。

其二，在 **网页流式呈现（DeepSeek）** 条目之后插入新条目：

```markdown
- **网页图谱子图可视化**：graph 模式轮次在 `report_start` 前推送 SSE 事件 `graph_subgraph`（`project_subgraph` 把 `HybridContext` 纯函数投影为 `GraphSubgraph`：种子/直接股东/对外投资/最终控制人节点 + 持股/投资/控制线索边，每种子每方向邻居上限 15 条，超限置 `truncated`）；前端 `web/graph.js` 在右侧可收起面板用确定性分层布局渲染（手写 SVG、零第三方依赖），支持缩放/平移/悬停/点击高亮，共享控制人红色高亮并注明围标线索，全程「线索级证据 · 须人工复核」口径。named/scope/降级轮次不发事件，面板保持原状；子图不持久化，仅反映本页面会话最新一次图检索。
```

- [ ] **Step 5: 提交并推送**

```powershell
git add CLAUDE.md docs/architecture.md
git commit -m "图谱可视化：文档同步（SSE 事件与前端面板说明）"
git push origin master
```

（推送依据用户已授权的推送习惯：模块完成+测试绿后自动推 master。）
