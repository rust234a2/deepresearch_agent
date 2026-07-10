# N1 股权图后端接口抽象 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抽出 `OwnershipGraphBackend` 协议、让内存图实现它、把 `hybrid_search`/`assemble_subgraph_context` 改成吃 backend，为 N2 引入 Neo4j 留出可插拔边界。

**Architecture:** 纯重构、零行为变化、零 Neo4j 依赖。第一步建 `ownership_backend.py`（协议 + `InMemoryOwnershipBackend` + 迁入的 `NeighborEdge`），旧路径不动、全绿；第二步把消费方翻转到 backend、删除 `graph_retrieval` 里被 backend 收编的私有函数、迁移调用点测试。

**Tech Stack:** Python 3、Pydantic、pytest。复用 `graph_traversal.ultimate_controllers`、现有 `OwnershipGraph`。

## Global Constraints

- SQLite 是股权边事实源；图是可重建查询产物。关联方/共享控制人为线索级（`via_person` 低置信、"须人工复核"）。
- N1 不引入外部服务/新依赖；`researcher`/`writer`/报告/CLI/API/schema 一行不改。
- 行为零变化：迁移后既有断言全部原样保留并通过。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`。
- 每个任务结束提交一次；中文提交信息。

## 文件结构

- 新 `src/deepresearch_agent/ownership_backend.py` — `NeighborEdge` + `OwnershipGraphBackend` 协议 + `InMemoryOwnershipBackend`（Task 1）。
- 新 `tests/test_ownership_backend.py` — backend 行为测试，兼作 N2 对拍参考（Task 1）。
- 改 `src/deepresearch_agent/graph_retrieval.py` — Task 1 迁 `NeighborEdge` 导入；Task 2 消费方吃 backend、删私有函数。
- 改 `src/deepresearch_agent/agents/graph.py` — Task 2 `_build_graph_searcher` 包 backend。
- 改 `tests/test_graph_retrieval.py`、`tests/test_nodes.py` — Task 2 调用点包 backend。

---

### Task 1：新建 `ownership_backend.py` + 内存后端

**Files:**
- Create: `src/deepresearch_agent/ownership_backend.py`
- Create: `tests/test_ownership_backend.py`
- Modify: `src/deepresearch_agent/graph_retrieval.py`（`NeighborEdge` 改为从新模块导入）

**Interfaces:**
- Consumes: `graph_traversal.ControllerResult` / `graph_traversal.ultimate_controllers`、`ownership_graph.OwnershipGraph`。
- Produces: `NeighborEdge`（迁到此）、`OwnershipGraphBackend`（Protocol：`has_node`/`display_name`/`ultimate_controllers`/`direct_neighbors`）、`InMemoryOwnershipBackend(graph: OwnershipGraph)`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_ownership_backend.py`：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.graph_traversal import ultimate_controllers
from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
from deepresearch_agent.ownership_graph import load_ownership_graph


LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _graph(tmp_path: Path):
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def test_backend_has_node_and_display_name(tmp_path):
    backend = InMemoryOwnershipBackend(_graph(tmp_path))
    assert backend.has_node(A_CODE) is True
    assert backend.has_node("no-such") is False
    assert backend.display_name(A_CODE) == "甲公司"
    assert backend.display_name("no-such") == "no-such"


def test_backend_ultimate_controllers_matches_traversal(tmp_path):
    graph = _graph(tmp_path)
    backend = InMemoryOwnershipBackend(graph)
    assert backend.ultimate_controllers(A_CODE) == ultimate_controllers(graph, A_CODE)


def test_backend_direct_neighbors_shape_and_sort(tmp_path):
    backend = InMemoryOwnershipBackend(_graph(tmp_path))
    neighbors = backend.direct_neighbors(A_CODE)
    assert neighbors == sorted(neighbors, key=lambda n: (n.direction, n.node_id))
    # 甲 对外投资 丙（out / investment）
    assert any(
        n.node_id == C_CODE and n.direction == "out" and n.edge_type == "investment"
        for n in neighbors
    )
    # 乙 持股 甲（in / shareholding）
    assert any(
        n.node_id == B_CODE and n.direction == "in" and n.edge_type == "shareholding"
        for n in neighbors
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_backend.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.ownership_backend`）

- [ ] **Step 3: 建 `ownership_backend.py`**

创建 `src/deepresearch_agent/ownership_backend.py`：

```python
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult, ultimate_controllers
from deepresearch_agent.ownership_graph import OwnershipGraph


class NeighborEdge(BaseModel):
    node_id: str
    name: str
    node_type: str
    edge_type: Literal["shareholding", "investment"]
    direction: Literal["in", "out"]
    holding_pct: str | None = None


class OwnershipGraphBackend(Protocol):
    def has_node(self, node_id: str) -> bool: ...
    def display_name(self, node_id: str) -> str: ...
    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]: ...
    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]: ...


class InMemoryOwnershipBackend:
    def __init__(self, graph: OwnershipGraph) -> None:
        self._graph = graph

    def has_node(self, node_id: str) -> bool:
        return node_id in self._graph.nodes

    def display_name(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.display_name if node is not None else node_id

    def _node_type(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.node_type if node is not None else ""

    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]:
        return ultimate_controllers(self._graph, node_id, max_depth=max_depth)

    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]:
        neighbors: list[NeighborEdge] = []
        for edge in self._graph.successors(node_id):
            neighbors.append(
                NeighborEdge(
                    node_id=edge.target_node_id,
                    name=self.display_name(edge.target_node_id),
                    node_type=self._node_type(edge.target_node_id),
                    edge_type=edge.edge_type,
                    direction="out",
                    holding_pct=edge.holding_pct,
                )
            )
        for edge in self._graph.predecessors(node_id):
            neighbors.append(
                NeighborEdge(
                    node_id=edge.source_node_id,
                    name=self.display_name(edge.source_node_id),
                    node_type=self._node_type(edge.source_node_id),
                    edge_type=edge.edge_type,
                    direction="in",
                    holding_pct=edge.holding_pct,
                )
            )
        neighbors.sort(key=lambda n: (n.direction, n.node_id))
        return neighbors
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_backend.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: PASS（3 项）

- [ ] **Step 5: `graph_retrieval.py` 改用迁移后的 `NeighborEdge`**

在 `src/deepresearch_agent/graph_retrieval.py` 顶部，把：

```python
from typing import Literal

from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult, ultimate_controllers
from deepresearch_agent.ownership_graph import OwnershipGraph
```

改为：

```python
from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult, ultimate_controllers
from deepresearch_agent.ownership_backend import NeighborEdge
from deepresearch_agent.ownership_graph import OwnershipGraph
```

并删除本地的 `NeighborEdge` 类定义（`class NeighborEdge(BaseModel): ... holding_pct: str | None = None` 整块）。其余（`_name`/`_type`/`_direct_neighbors`/`assemble_subgraph_context`/`hybrid_search`）本步**保持不动**。

- [ ] **Step 6: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: 全绿（既有测试不变——`assemble_subgraph_context` 仍吃 graph；`NeighborEdge` 同一个类，`SeedContext.neighbors` 不受影响 + 新 backend 测试通过）

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/ownership_backend.py tests/test_ownership_backend.py src/deepresearch_agent/graph_retrieval.py
git commit -m "功能：N1-1 新增 OwnershipGraphBackend 协议与内存后端，NeighborEdge 迁入"
```

---

### Task 2：消费方翻转到 backend

**Files:**
- Modify: `src/deepresearch_agent/graph_retrieval.py`（`assemble_subgraph_context`/`hybrid_search` 吃 backend，删 `_name`/`_type`/`_direct_neighbors` 与不再使用的导入）
- Modify: `src/deepresearch_agent/agents/graph.py`（`_build_graph_searcher` 包 backend）
- Modify: `tests/test_graph_retrieval.py`、`tests/test_nodes.py`（调用点包 `InMemoryOwnershipBackend`）

**Interfaces:**
- Consumes: `ownership_backend.OwnershipGraphBackend` / `InMemoryOwnershipBackend`。
- Produces: `assemble_subgraph_context(backend, seed_codes, max_depth=5, query=None, scores=None) -> HybridContext`；`hybrid_search(query, scope_retriever, backend, k=10, max_depth=5) -> HybridContext`。`SeedContext`/`SharedController`/`HybridContext` 不变。

- [ ] **Step 1: 先迁移调用点测试（此时应失败/仍绿，见下）**

`tests/test_graph_retrieval.py`：加导入

```python
from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
```

把 4 处调用改为传 backend（断言全不动）：

```python
    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE, B_CODE, C_CODE])
```
```python
    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE], scores={A_CODE: 0.9})
```
```python
    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), ["no-such-code"])
```
```python
    ctx = hybrid_search("注塑成型", retriever, InMemoryOwnershipBackend(graph))
```

`tests/test_nodes.py`：加导入 `from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend`，把第 307 行改为：

```python
    searcher = lambda query: assemble_subgraph_context(InMemoryOwnershipBackend(graph), seeds, query=query)
```

- [ ] **Step 2: 跑受影响测试确认失败（红步）**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py tests/test_nodes.py -k "assemble or hybrid or researcher_graph" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: FAIL —— 调用点已传 `InMemoryOwnershipBackend(graph)`，但 `assemble_subgraph_context` 旧实现仍用 `code not in graph.nodes`，对 backend 对象报 `AttributeError`（backend 无 `.nodes`）。正是 Step 3 要修的。

- [ ] **Step 3: 翻转 `graph_retrieval.py` 消费方**

把 `src/deepresearch_agent/graph_retrieval.py` 顶部导入改为：

```python
from pydantic import BaseModel

from deepresearch_agent.graph_traversal import ControllerResult
from deepresearch_agent.ownership_backend import NeighborEdge, OwnershipGraphBackend
```

删除 `_name`、`_type`、`_direct_neighbors` 三个函数整块。把 `assemble_subgraph_context` 与 `hybrid_search` 替换为：

```python
def assemble_subgraph_context(
    backend: OwnershipGraphBackend,
    seed_codes: list[str],
    max_depth: int = 5,
    query: str | None = None,
    scores: dict[str, float] | None = None,
) -> HybridContext:
    scores = scores or {}
    seeds: list[SeedContext] = []
    controlled: dict[str, set[str]] = {}
    meta: dict[str, tuple[str, bool]] = {}
    for code in seed_codes:
        if not backend.has_node(code):
            continue
        controllers = backend.ultimate_controllers(code, max_depth=max_depth)
        seeds.append(
            SeedContext(
                code=code,
                name=backend.display_name(code),
                score=scores.get(code, 0.0),
                controllers=controllers,
                neighbors=backend.direct_neighbors(code),
            )
        )
        for controller in controllers:
            controlled.setdefault(controller.node_id, set()).add(code)
            name, via = meta.get(controller.node_id, (controller.display_name, False))
            meta[controller.node_id] = (name, via or controller.via_person)
    shared = [
        SharedController(
            node_id=nid,
            name=meta[nid][0],
            controlled_seeds=sorted(codes),
            via_person=meta[nid][1],
        )
        for nid, codes in controlled.items()
        if len(codes) >= 2
    ]
    shared.sort(key=lambda s: (-len(s.controlled_seeds), s.node_id))
    seeds.sort(key=lambda s: (-s.score, s.code))
    return HybridContext(query=query, seeds=seeds, shared_controllers=shared)


def hybrid_search(
    query: str,
    scope_retriever,
    backend: OwnershipGraphBackend,
    k: int = 10,
    max_depth: int = 5,
) -> HybridContext:
    hits = scope_retriever.search(query, k)
    scores: dict[str, float] = {}
    for hit in hits:
        code = hit.unified_social_credit_code
        scores[code] = max(scores.get(code, 0.0), hit.score)
    seed_codes = sorted(scores, key=lambda code: (-scores[code], code))
    return assemble_subgraph_context(
        backend, seed_codes, max_depth=max_depth, query=query, scores=scores
    )
```

（`SeedContext`/`SharedController`/`HybridContext` 三个模型定义保持不动。）

- [ ] **Step 4: 跑受影响测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py tests/test_nodes.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: PASS

- [ ] **Step 5: 更新 `graph.py` 的 `_build_graph_searcher`**

在 `src/deepresearch_agent/agents/graph.py`，把 `_build_graph_searcher` 里 try 块内的：

```python
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_graph import load_ownership_graph

        graph = load_ownership_graph(CompanyRepository(database_path))
        return lambda query: hybrid_search(query, scope_retriever, graph)
```

改为：

```python
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
        from deepresearch_agent.ownership_graph import load_ownership_graph

        backend = InMemoryOwnershipBackend(load_ownership_graph(CompanyRepository(database_path)))
        return lambda query: hybrid_search(query, scope_retriever, backend)
```

- [ ] **Step 6: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-n1`
Expected: 全绿（行为零变化，所有既有断言原样通过）

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/graph_retrieval.py src/deepresearch_agent/agents/graph.py tests/test_graph_retrieval.py tests/test_nodes.py
git commit -m "功能：N1-2 hybrid_search/assemble_subgraph_context 改吃 OwnershipGraphBackend"
```

---

## 收尾

两个任务完成、全量绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。文档在收尾前同步 N1：`docs/architecture.md` 的图检索段说明 `hybrid_search` 走 `OwnershipGraphBackend`（内存实现，N2 将加 Neo4j 实现）。

## Self-Review

- **Spec 覆盖**：`OwnershipGraphBackend` 协议 + `InMemoryOwnershipBackend` + `NeighborEdge` 迁移=Task 1；消费方吃 backend + 删私有函数 + `graph.py` 包 backend + 调用点测试迁移=Task 2；`ego`/`common_controllers`/`shortest_path` 不动（不在协议）；`ownership_graph.py`/`graph_traversal.py`/schema/依赖不改=贯穿。零行为变化由"迁移后既有断言原样保留"保证。
- **占位符**：无 TBD/TODO；每个改码步骤含完整代码。
- **类型一致**：`OwnershipGraphBackend` 四方法在 Task 1 定义、Task 2 的 `assemble_subgraph_context` 逐一消费（`has_node`/`ultimate_controllers`/`display_name`/`direct_neighbors`）；`NeighborEdge` 在 Task 1 迁入 `ownership_backend`、Task 2 graph_retrieval 从该模块导入并被 `SeedContext` 引用，全程同一个类。
