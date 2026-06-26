# 模块 B3：图遍历/多跳查询层实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 B2 的 `OwnershipGraph` 上实现四个纯确定性多跳算法（ego_graph、ultimate_controllers、common_controllers、shortest_path），基金节点不扩展、自然人路径标 `via_person`、置信交上层。

**Architecture:** 新模块 `graph_traversal.py`：Pydantic 结果模型 + 共享的"向上可达"BFS 助手 + 四个算法函数。纯 dict 遍历，无新依赖、无 schema 变更。

**Tech Stack:** Python 3.11、Pydantic v2、`collections.deque`、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM、零新依赖、无 schema 变更**。
- **基金**：不从 `fund` 节点扩展；`fund` 不作控制人结果。`DEFAULT_BLOCK_EXPAND_TYPES = ("fund",)`。
- **自然人**：正常穿，但路径/结果标 `via_person=True`；B3 不算置信、不写免责。
- **防环**：visited/seen 集合；**确定性**：扩展邻居按 `node_id` 排序，结果按稳定键排序。
- 方向：入边=向上（控制人），出边=向下（持有/投资）。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-b3`。每个 Task 一提交，中文提交信息。

---

### Task 1: 结果模型 + 助手 + `ego_graph` + `ultimate_controllers`

**Files:**
- Create: `src/deepresearch_agent/graph_traversal.py`
- Create: `tests/test_graph_traversal.py`

**Interfaces:**
- Consumes：B2 `OwnershipGraph`（`nodes`/`edges`/`successors`/`predecessors`）、`GraphNode`、`GraphEdge`、`external_node_id`（建库间接产生 node_id）。
- Produces：
  - 模型 `EgoResult`、`ControllerResult`（+ Task 2 用的 `CommonController`、`GraphPath`）。
  - `ego_graph(graph, node_id, radius=2, block_expand_types=DEFAULT_BLOCK_EXPAND_TYPES) -> EgoResult`。
  - `ultimate_controllers(graph, node_id, max_depth=5, block_expand_types=...) -> list[ControllerResult]`。
  - 内部助手 `_upward_reachable`（Task 2 复用）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_traversal.py`：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import GraphEdge, GraphNode
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.ownership_graph import OwnershipGraph, load_ownership_graph
from deepresearch_agent.graph_traversal import (
    ego_graph,
    ultimate_controllers,
)


LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _graph(tmp_path: Path) -> OwnershipGraph:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def _manual_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> OwnershipGraph:
    out_edges: dict[str, list[GraphEdge]] = {}
    in_edges: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        out_edges.setdefault(edge.source_node_id, []).append(edge)
        in_edges.setdefault(edge.target_node_id, []).append(edge)
    return OwnershipGraph(
        nodes={n.node_id: n for n in nodes},
        edges=edges,
        out_edges=out_edges,
        in_edges=in_edges,
    )


def test_ego_graph_includes_in_and_out_neighbors(tmp_path):
    graph = _graph(tmp_path)

    ego = ego_graph(graph, A_CODE, radius=1)

    assert ego.center == A_CODE
    assert A_CODE in ego.node_ids
    assert B_CODE in ego.node_ids                      # 乙 持有 甲（入边）
    assert "person:张三" in ego.node_ids                # 张三 持有 甲（入边）
    assert C_CODE in ego.node_ids                      # 甲 投资 丙（出边）
    assert "ext:共同投资标的有限公司" in ego.node_ids


def test_ego_graph_does_not_expand_from_fund():
    nodes = [
        GraphNode(node_id="X", display_name="X", normalized_name="x",
                  node_type="company", in_database=True, mention_count=1),
        GraphNode(node_id="Y", display_name="Y", normalized_name="y",
                  node_type="company", in_database=True, mention_count=1),
        GraphNode(node_id="fund:F", display_name="F基金", normalized_name="f基金",
                  node_type="fund", in_database=False, mention_count=2),
    ]
    edges = [
        GraphEdge(source_node_id="fund:F", target_node_id="X", edge_type="shareholding"),
        GraphEdge(source_node_id="fund:F", target_node_id="Y", edge_type="shareholding"),
    ]
    graph = _manual_graph(nodes, edges)

    ego = ego_graph(graph, "X", radius=2)

    assert "fund:F" in ego.node_ids   # 基金作为端点可见
    assert "Y" not in ego.node_ids    # 但不从基金扩展到它的其它持仓


def test_ultimate_controllers(tmp_path):
    graph = _graph(tmp_path)

    controllers = ultimate_controllers(graph, A_CODE)

    by_id = {c.node_id: c for c in controllers}
    assert "ext:共同控股集团有限公司" in by_id     # 根（无上层）
    assert by_id["ext:共同控股集团有限公司"].via_person is False
    assert "person:张三" in by_id                  # 自然人终点
    assert by_id["person:张三"].via_person is True
    assert B_CODE not in by_id                      # 乙 有上层（共同控股集团），非最终
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_traversal.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b3`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.graph_traversal'`。

- [ ] **Step 3: 写 `graph_traversal.py`（模型 + 助手 + 两算法）**

创建 `src/deepresearch_agent/graph_traversal.py`：

```python
from __future__ import annotations

from collections import deque

from pydantic import BaseModel

from deepresearch_agent.company_models import GraphEdge
from deepresearch_agent.ownership_graph import OwnershipGraph


DEFAULT_BLOCK_EXPAND_TYPES = ("fund",)


class EgoResult(BaseModel):
    center: str
    node_ids: list[str]
    edges: list[GraphEdge]


class ControllerResult(BaseModel):
    node_id: str
    display_name: str
    depth: int
    via_person: bool


class CommonController(BaseModel):
    node_id: str
    display_name: str
    depth_from_a: int
    depth_from_b: int
    via_person: bool


class GraphPath(BaseModel):
    node_ids: list[str]
    length: int
    via_person: bool


def _node_type(graph: OwnershipGraph, node_id: str) -> str | None:
    node = graph.nodes.get(node_id)
    return node.node_type if node is not None else None


def _is_person(graph: OwnershipGraph, node_id: str) -> bool:
    node = graph.nodes.get(node_id)
    return bool(node is not None and node.is_person)


def _display(graph: OwnershipGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    return node.display_name if node is not None else node_id


def _upward_reachable(
    graph: OwnershipGraph,
    node_id: str,
    max_depth: int,
    block_expand_types: tuple[str, ...],
) -> dict[str, tuple[int, bool]]:
    """向上（入边/股东方向）可达的非 fund 节点 -> (最短深度, 路径是否经过自然人)。"""
    reached: dict[str, tuple[int, bool]] = {}
    seen = {node_id}
    queue: deque[tuple[str, int, bool]] = deque([(node_id, 0, False)])
    while queue:
        current, depth, via_person = queue.popleft()
        if depth >= max_depth:
            continue
        if current != node_id and _node_type(graph, current) in block_expand_types:
            continue
        for edge in graph.predecessors(current):
            parent = edge.source_node_id
            if parent in seen or _node_type(graph, parent) in block_expand_types:
                continue
            seen.add(parent)
            parent_via = via_person or _is_person(graph, parent)
            reached[parent] = (depth + 1, parent_via)
            queue.append((parent, depth + 1, parent_via))
    return reached


def ego_graph(
    graph: OwnershipGraph,
    node_id: str,
    radius: int = 2,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> EgoResult:
    visited = {node_id}
    frontier = [node_id]
    for _ in range(radius):
        next_frontier: list[str] = []
        for current in frontier:
            if current != node_id and _node_type(graph, current) in block_expand_types:
                continue
            neighbors = {edge.target_node_id for edge in graph.successors(current)}
            neighbors |= {edge.source_node_id for edge in graph.predecessors(current)}
            for neighbor in sorted(neighbors):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
    edges = [
        edge
        for edge in graph.edges
        if edge.source_node_id in visited and edge.target_node_id in visited
    ]
    return EgoResult(center=node_id, node_ids=sorted(visited), edges=edges)


def ultimate_controllers(
    graph: OwnershipGraph,
    node_id: str,
    max_depth: int = 5,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> list[ControllerResult]:
    reached = _upward_reachable(graph, node_id, max_depth, block_expand_types)
    results: list[ControllerResult] = []
    for nid, (depth, via_person) in reached.items():
        has_parent = any(
            _node_type(graph, edge.source_node_id) not in block_expand_types
            for edge in graph.predecessors(nid)
        )
        if (not has_parent) or _is_person(graph, nid):
            results.append(
                ControllerResult(
                    node_id=nid,
                    display_name=_display(graph, nid),
                    depth=depth,
                    via_person=via_person,
                )
            )
    results.sort(key=lambda c: (c.depth, c.node_id))
    return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_traversal.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b3`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/graph_traversal.py tests/test_graph_traversal.py
git commit -m "功能：B3 图遍历 ego_graph 与 ultimate_controllers"
```

---

### Task 2: `common_controllers` + `shortest_path`

**Files:**
- Modify: `src/deepresearch_agent/graph_traversal.py`（两函数）
- Modify: `tests/test_graph_traversal.py`（用例）

**Interfaces:**
- Consumes：Task 1 的 `_upward_reachable`、`_node_type`/`_is_person`/`_display`、`CommonController`、`GraphPath`。
- Produces：
  - `common_controllers(graph, node_a, node_b, max_depth=5, block_expand_types=...) -> list[CommonController]`。
  - `shortest_path(graph, node_a, node_b, max_depth=6, block_expand_types=...) -> GraphPath | None`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_traversal.py` 顶部 import 追加 `common_controllers, shortest_path`：

```python
from deepresearch_agent.graph_traversal import (
    common_controllers,
    ego_graph,
    shortest_path,
    ultimate_controllers,
)
```

在文件末尾新增：

```python
def test_common_controllers_company_via_non_person(tmp_path):
    graph = _graph(tmp_path)

    common = common_controllers(graph, A_CODE, B_CODE)

    by_id = {c.node_id: c for c in common}
    assert "ext:共同控股集团有限公司" in by_id
    assert by_id["ext:共同控股集团有限公司"].via_person is False
    assert A_CODE not in by_id and B_CODE not in by_id


def test_common_controllers_person_low_confidence(tmp_path):
    graph = _graph(tmp_path)

    common = common_controllers(graph, A_CODE, C_CODE)

    by_id = {c.node_id: c for c in common}
    assert "person:张三" in by_id
    assert by_id["person:张三"].via_person is True


def test_shortest_path_direct_and_two_hop(tmp_path):
    graph = _graph(tmp_path)

    direct = shortest_path(graph, A_CODE, C_CODE)
    assert direct is not None
    assert direct.node_ids == [A_CODE, C_CODE]
    assert direct.length == 1

    two_hop = shortest_path(graph, B_CODE, C_CODE)
    assert two_hop is not None
    assert two_hop.node_ids[0] == B_CODE and two_hop.node_ids[-1] == C_CODE
    assert two_hop.length == 2


def test_shortest_path_edges_unknown_and_same(tmp_path):
    graph = _graph(tmp_path)

    same = shortest_path(graph, A_CODE, A_CODE)
    assert same is not None and same.node_ids == [A_CODE] and same.length == 0
    assert shortest_path(graph, A_CODE, "no-such-node") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_traversal.py::test_common_controllers_company_via_non_person -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b3`
Expected: FAIL —`ImportError: cannot import name 'common_controllers'`。

- [ ] **Step 3: 加 `common_controllers` + `shortest_path`**

在 `src/deepresearch_agent/graph_traversal.py` 末尾追加：

```python
def common_controllers(
    graph: OwnershipGraph,
    node_a: str,
    node_b: str,
    max_depth: int = 5,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> list[CommonController]:
    up_a = _upward_reachable(graph, node_a, max_depth, block_expand_types)
    up_b = _upward_reachable(graph, node_b, max_depth, block_expand_types)
    shared = (set(up_a) & set(up_b)) - {node_a, node_b}
    results: list[CommonController] = []
    for nid in shared:
        depth_a, via_a = up_a[nid]
        depth_b, via_b = up_b[nid]
        results.append(
            CommonController(
                node_id=nid,
                display_name=_display(graph, nid),
                depth_from_a=depth_a,
                depth_from_b=depth_b,
                via_person=via_a or via_b,
            )
        )
    results.sort(key=lambda c: (c.depth_from_a + c.depth_from_b, c.node_id))
    return results


def shortest_path(
    graph: OwnershipGraph,
    node_a: str,
    node_b: str,
    max_depth: int = 6,
    block_expand_types: tuple[str, ...] = DEFAULT_BLOCK_EXPAND_TYPES,
) -> GraphPath | None:
    if node_a == node_b:
        if node_a not in graph.nodes:
            return None
        return GraphPath(node_ids=[node_a], length=0, via_person=_is_person(graph, node_a))
    parents: dict[str, str | None] = {node_a: None}
    queue: deque[tuple[str, int]] = deque([(node_a, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        if current != node_a and _node_type(graph, current) in block_expand_types:
            continue
        neighbors = {edge.target_node_id for edge in graph.successors(current)}
        neighbors |= {edge.source_node_id for edge in graph.predecessors(current)}
        for neighbor in sorted(neighbors):
            if neighbor in parents:
                continue
            parents[neighbor] = current
            if neighbor == node_b:
                path = [node_b]
                cursor: str | None = current
                while cursor is not None:
                    path.append(cursor)
                    cursor = parents[cursor]
                path.reverse()
                via = any(_is_person(graph, n) for n in path)
                return GraphPath(node_ids=path, length=len(path) - 1, via_person=via)
            queue.append((neighbor, depth + 1))
    return None
```

- [ ] **Step 4: 跑遍历测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_traversal.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b3`
Expected: PASS（7 passed）。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-b3-full`
Expected: PASS（122 + 本次新增，2 deselected）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/graph_traversal.py tests/test_graph_traversal.py
git commit -m "功能：B3 图遍历 common_controllers 与 shortest_path"
```

---

## 自检

**Spec 覆盖**：
- `ego_graph`（双向、radius、不从 fund 扩展、含 center+内部边）→ Task 1 Step 3 + 测试。
- `ultimate_controllers`（向上、跳 fund、根/person 为终点、via_person、排序）→ Task 1 Step 3 + 测试。
- `common_controllers`（交集、排除 a/b、双侧 depth、via_person）→ Task 2 Step 3 + 测试。
- `shortest_path`（无向 BFS、不穿 fund、同节点/未知/直连/两跳）→ Task 2 Step 3 + 测试。
- 基金 A 策略、via_person 交上层、防环、确定性排序 → 各算法实现 + `_upward_reachable`/排序键。
- 四个结果模型 → Task 1 定义（CommonController/GraphPath 在 Task 1 定义、Task 2 用）。

**Placeholder 扫描**：无 TBD/TODO；每步给完整代码与命令/预期。

**类型一致性**：`_upward_reachable -> dict[node_id,(depth,via_person)]` 被 `ultimate_controllers`/`common_controllers` 共用；结果模型字段在定义、构造、测试断言一致；`block_expand_types` 默认 `("fund",)` 贯穿四函数；方向（入边=上、出边=下）在 `_upward_reachable`/`ego_graph`/`shortest_path` 一致。
