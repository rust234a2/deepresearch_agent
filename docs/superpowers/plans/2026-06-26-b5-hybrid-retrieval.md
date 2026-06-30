# 模块 B5（精简）：混合检索/子图上下文组装实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 B5 混合检索：核心 `assemble_subgraph_context`（种子公司 → B3 控制人 + 1 跳邻域 + 跨种子共享控制人）+ 薄包装 `hybrid_search`（复用 `ScopeRetriever` 语义种子，鸭子类型，不 import rag）。

**Architecture:** 新模块 `graph_retrieval.py`：Pydantic 结果模型 + `assemble_subgraph_context`（无 bge 可测）+ `hybrid_search`（语义种子薄包装）。复用 B3 `ultimate_controllers`、B2 `OwnershipGraph`。

**Tech Stack:** Python 3.11、Pydantic v2、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM、零新依赖、无 schema 变更**。
- **核心无 bge**：`assemble_subgraph_context` 只吃 graph + 种子码；`hybrid_search` 对 retriever 鸭子类型（调 `.search`、读 `.unified_social_credit_code`/`.score`），`graph_retrieval` 不 import `rag/`。
- **置信交上层**：只组装结构 + 传 B3 `via_person`，不算置信。
- **确定性排序**：邻居 `(direction, node_id)`；共享控制人 `(-len, node_id)`；种子 `(-score, code)`。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-b5`。每个 Task 一提交，中文提交信息。

---

### Task 1: 模型 + `assemble_subgraph_context`

**Files:**
- Create: `src/deepresearch_agent/graph_retrieval.py`
- Create: `tests/test_graph_retrieval.py`

**Interfaces:**
- Consumes：B3 `ultimate_controllers`/`ControllerResult`、B2 `OwnershipGraph`/`load_ownership_graph`。
- Produces：
  - 模型 `NeighborEdge`、`SeedContext`、`SharedController`、`HybridContext`。
  - `assemble_subgraph_context(graph, seed_codes, max_depth=5, query=None, scores=None) -> HybridContext`。
  - 内部 `_direct_neighbors`（+ Task 2 复用 `_name`/`_type`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_retrieval.py`：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.graph_retrieval import assemble_subgraph_context
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


def test_assemble_shared_controllers_across_seeds(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(graph, [A_CODE, B_CODE, C_CODE])

    shared = {s.node_id: s for s in ctx.shared_controllers}
    assert "ext:共同控股集团有限公司" in shared
    assert set(shared["ext:共同控股集团有限公司"].controlled_seeds) == {A_CODE, B_CODE}
    assert shared["ext:共同控股集团有限公司"].via_person is False
    assert "person:张三" in shared
    assert set(shared["person:张三"].controlled_seeds) == {A_CODE, C_CODE}
    assert shared["person:张三"].via_person is True


def test_assemble_seed_context_controllers_and_neighbors(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(graph, [A_CODE], scores={A_CODE: 0.9})

    seed = ctx.seeds[0]
    assert seed.code == A_CODE
    assert seed.score == 0.9
    controller_ids = {c.node_id for c in seed.controllers}
    assert "ext:共同控股集团有限公司" in controller_ids
    assert "person:张三" in controller_ids
    neighbor_ids = {n.node_id for n in seed.neighbors}
    assert C_CODE in neighbor_ids
    assert "ext:共同控股集团有限公司" in neighbor_ids
    invest = next(n for n in seed.neighbors if n.node_id == C_CODE)
    assert invest.direction == "out" and invest.edge_type == "investment"
    held_by = next(n for n in seed.neighbors if n.node_id == "ext:共同控股集团有限公司")
    assert held_by.direction == "in" and held_by.edge_type == "shareholding"


def test_assemble_skips_unknown_seed(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(graph, ["no-such-code"])

    assert ctx.seeds == []
    assert ctx.shared_controllers == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b5`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.graph_retrieval'`。

- [ ] **Step 3: 写 `graph_retrieval.py`（模型 + 核心）**

创建 `src/deepresearch_agent/graph_retrieval.py`：

```python
from __future__ import annotations

from typing import Literal

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


class SeedContext(BaseModel):
    code: str
    name: str
    score: float
    controllers: list[ControllerResult]
    neighbors: list[NeighborEdge]


class SharedController(BaseModel):
    node_id: str
    name: str
    controlled_seeds: list[str]
    via_person: bool


class HybridContext(BaseModel):
    query: str | None = None
    seeds: list[SeedContext]
    shared_controllers: list[SharedController]


def _name(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.display_name if node is not None else node_id


def _type(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.node_type if node is not None else ""


def _direct_neighbors(graph: OwnershipGraph, code: str) -> list[NeighborEdge]:
    neighbors: list[NeighborEdge] = []
    for edge in graph.successors(code):
        neighbors.append(
            NeighborEdge(
                node_id=edge.target_node_id,
                name=_name(graph, edge.target_node_id),
                node_type=_type(graph, edge.target_node_id),
                edge_type=edge.edge_type,
                direction="out",
                holding_pct=edge.holding_pct,
            )
        )
    for edge in graph.predecessors(code):
        neighbors.append(
            NeighborEdge(
                node_id=edge.source_node_id,
                name=_name(graph, edge.source_node_id),
                node_type=_type(graph, edge.source_node_id),
                edge_type=edge.edge_type,
                direction="in",
                holding_pct=edge.holding_pct,
            )
        )
    neighbors.sort(key=lambda n: (n.direction, n.node_id))
    return neighbors


def assemble_subgraph_context(
    graph: OwnershipGraph,
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
        if code not in graph.nodes:
            continue
        controllers = ultimate_controllers(graph, code, max_depth=max_depth)
        seeds.append(
            SeedContext(
                code=code,
                name=_name(graph, code),
                score=scores.get(code, 0.0),
                controllers=controllers,
                neighbors=_direct_neighbors(graph, code),
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b5`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/graph_retrieval.py tests/test_graph_retrieval.py
git commit -m "功能：B5 子图上下文组装 assemble_subgraph_context"
```

---

### Task 2: `hybrid_search` 薄包装

**Files:**
- Modify: `src/deepresearch_agent/graph_retrieval.py`（`hybrid_search`）
- Modify: `tests/test_graph_retrieval.py`（stub retriever 用例）

**Interfaces:**
- Consumes：Task 1 的 `assemble_subgraph_context`；任意带 `.search(query,k)`（返回带 `.unified_social_credit_code`/`.score` 的对象）的 retriever。
- Produces：`hybrid_search(query, scope_retriever, graph, k=10, max_depth=5) -> HybridContext`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_retrieval.py` 顶部 import 追加 `hybrid_search`：

```python
from deepresearch_agent.graph_retrieval import assemble_subgraph_context, hybrid_search
```

在文件末尾新增：

```python
class _Hit:
    def __init__(self, code: str, score: float):
        self.unified_social_credit_code = code
        self.score = score


class _StubRetriever:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, k):
        return self._hits


def test_hybrid_search_uses_scope_seeds_sorted_by_score(tmp_path):
    graph = _graph(tmp_path)
    retriever = _StubRetriever([_Hit(B_CODE, 0.7), _Hit(A_CODE, 0.95), _Hit(A_CODE, 0.4)])

    ctx = hybrid_search("注塑成型", retriever, graph)

    assert ctx.query == "注塑成型"
    assert [s.code for s in ctx.seeds] == [A_CODE, B_CODE]   # 按分降序；甲取最高 0.95
    assert ctx.seeds[0].score == 0.95
    shared_ids = {s.node_id for s in ctx.shared_controllers}
    assert "ext:共同控股集团有限公司" in shared_ids           # 甲、乙 共享
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py::test_hybrid_search_uses_scope_seeds_sorted_by_score -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b5`
Expected: FAIL —`ImportError: cannot import name 'hybrid_search'`。

- [ ] **Step 3: 加 `hybrid_search`**

在 `src/deepresearch_agent/graph_retrieval.py` 末尾追加：

```python
def hybrid_search(
    query: str,
    scope_retriever,
    graph: OwnershipGraph,
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
        graph, seed_codes, max_depth=max_depth, query=query, scores=scores
    )
```

- [ ] **Step 4: 跑检索测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b5`
Expected: PASS（4 passed）。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-b5-full`
Expected: PASS（129 + 本次新增，2 deselected）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/graph_retrieval.py tests/test_graph_retrieval.py
git commit -m "功能：B5 hybrid_search 语义种子薄包装"
```

---

## 自检

**Spec 覆盖**：
- 四个结果模型 → Task 1 Step 3。
- `assemble_subgraph_context`（控制人 + 1 跳邻域 + 跨种子共享控制人、score、排序、跳未知）→ Task 1 Step 3 + 测试。
- `hybrid_search`（鸭子类型 retriever、同公司多 chunk 取最高分、按分排序）→ Task 2 Step 3 + 测试。
- 置信交上层（只传 `via_person`，不算置信）→ 模型只含 `via_person`。
- `graph_retrieval` 不 import `rag/` → import 仅 graph_traversal/ownership_graph + pydantic。

**Placeholder 扫描**：无 TBD/TODO；每步给完整代码与命令/预期。

**类型一致性**：`assemble_subgraph_context(graph, seed_codes, max_depth, query, scores) -> HybridContext` 在 Interfaces/实现/测试一致；模型字段（`SeedContext.controllers: list[ControllerResult]`、`NeighborEdge.direction in {in,out}`、`SharedController.controlled_seeds`）在定义、构造、断言一致；`hybrid_search` 读 `hit.unified_social_credit_code`/`hit.score` 与 stub `_Hit` 属性一致。
```
