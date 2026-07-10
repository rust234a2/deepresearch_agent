# 模块 N1：股权图后端接口抽象设计

日期：2026-07-10

引入 Neo4j 替换内存图，分两步走。**N1 是纯重构**：抽出 `OwnershipGraphBackend` 协议，让现有内存图实现它，把 `hybrid_search`/`assemble_subgraph_context` 从吃 `OwnershipGraph` 改成吃 backend。**零行为变化、不引入任何 Neo4j 依赖、全部测试保持绿。** N2（Neo4j 后端 + Cypher + 对拍）在 N1 落地后单独开。

## 背景与定位

用户决定引入 Neo4j 替换内存图（角色 = 图查询引擎，SQLite 仍是事实源），测试策略选 **A：抽象接口 + 双实现**（Neo4j 生产实现 + 内存实现当 CI 测试替身）。为避免"每问一个节点邻居就发一次 Cypher"的慢查询反模式，遍历将整体下推到 Cypher（N2）；因此接口边界画在**遍历操作层**，不是访问器层。

N1 先把这个可插拔边界做出来，且不碰 Neo4j——先去风险、随时可停。

## 红线（不变）

- SQLite 是股权边事实源；图是可重建的查询产物。
- 关联方/共享控制人为线索级（`via_person` 低置信、标"须人工复核"）。
- N1 不引入外部服务/新依赖；`researcher`/`writer`/报告/CLI/API 一行不改。

## 接口

生产路径（`_build_graph_searcher → hybrid_search → assemble_subgraph_context`）只用到 `ultimate_controllers` + 直接邻居 + 节点元数据。据此定义**四方法协议**（新文件 `src/deepresearch_agent/ownership_backend.py`）：

```python
class OwnershipGraphBackend(Protocol):
    def has_node(self, node_id: str) -> bool: ...
    def display_name(self, node_id: str) -> str: ...
    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]: ...
    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]: ...
```

- `ControllerResult` 复用 `graph_traversal`（不动）。
- `NeighborEdge` 从 `graph_retrieval.py` **迁到** `ownership_backend.py`（它是"边视图"，属于 backend 层）；`graph_retrieval` 再 `from deepresearch_agent.ownership_backend import NeighborEdge` 保持兼容。
- `ego_graph`/`common_controllers`/`shortest_path`（B3）**不在协议里**——它们不在 Agent 热路径，仍作 `graph_traversal` 里吃 `OwnershipGraph` 的模块函数保留，N1 不动。

### `InMemoryOwnershipBackend`

包住现有 `OwnershipGraph`，四方法全**委托现有已测代码**：

```python
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
        # 迁移现 graph_retrieval._direct_neighbors 逻辑：出边 direction="out"、入边 "in"，
        # name/type 用本 backend 的 display_name/_node_type，末尾按 (direction, node_id) 排序。
        ...
```

`direct_neighbors` 的排序与字段必须**逐字复刻**现 `_direct_neighbors`（`(direction, node_id)` 排序、`edge_type`、`holding_pct`），保证零行为变化。

## 消费方改动

`graph_retrieval.py`：

- 删除本地 `NeighborEdge` 定义（改为从 `ownership_backend` 导入并 re-export）、删除 `_name`/`_type`/`_direct_neighbors`（收进 backend）。
- `assemble_subgraph_context(backend: OwnershipGraphBackend, seed_codes, max_depth=5, query=None, scores=None)`：
  - `code not in graph.nodes` → `not backend.has_node(code)`
  - `ultimate_controllers(graph, code, max_depth=...)` → `backend.ultimate_controllers(code, max_depth=...)`
  - `_name(graph, code)` → `backend.display_name(code)`
  - `_direct_neighbors(graph, code)` → `backend.direct_neighbors(code)`
  - 共享控制人组装用 `controller.display_name`（`ControllerResult` 自带），不变。
- `hybrid_search(query, scope_retriever, backend: OwnershipGraphBackend, k=10, max_depth=5)`：`graph` 形参改名 `backend`，转发给 `assemble_subgraph_context(backend, ...)`。scope 检索部分不变。

`agents/graph.py` 的 `_build_graph_searcher`：

```python
from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
...
backend = InMemoryOwnershipBackend(load_ownership_graph(CompanyRepository(database_path)))
return lambda query: hybrid_search(query, scope_retriever, backend)
```

## 测试

沿用 Windows 约定：`--basetemp=.conda-cache/pytest-n1`。

**新增 `tests/test_ownership_backend.py`**（这也是 N2 对拍的"参考行为"基准）：用 `ownership_links` fixture 构图 → `InMemoryOwnershipBackend(graph)`：
- `has_node("91110000000000111A")` True、`has_node("no-such")` False。
- `display_name` 对已知 code 返回登记名、未知 code 原样返回。
- `ultimate_controllers(code)` 结果与直接调 `graph_traversal.ultimate_controllers(graph, code)` **逐条相等**。
- `direct_neighbors(code)` 结果与现 `graph_retrieval._direct_neighbors(graph, code)` 迁移前行为一致（字段 + `(direction, node_id)` 排序）。

**迁移既有调用点**（改为传 backend，断言不变——证明零行为变化）：
- `tests/test_graph_retrieval.py`：4 处 `assemble_subgraph_context(graph, ...)` / `hybrid_search(..., graph)` 改为先 `backend = InMemoryOwnershipBackend(graph)` 再传 `backend`；所有断言原样保留。
- `tests/test_nodes.py` 第 307 行 researcher 图测试：`searcher = lambda query: assemble_subgraph_context(InMemoryOwnershipBackend(graph), seeds, query=query)`；断言不变。

**不受影响**（无需改）：`tests/test_ownership_graph.py`、`tests/test_graph_traversal.py`（仍直接测 `OwnershipGraph` 与 `graph_traversal`）、`tests/test_graph.py`（图 searcher 用桩，不经 `assemble_subgraph_context`）。

**验收**：全量 `pytest` 绿（迁移后既有断言全过 + 新 backend 测试通过）。

## 改动面

- 新文件：`src/deepresearch_agent/ownership_backend.py`（协议 + `InMemoryOwnershipBackend` + `NeighborEdge`）、`tests/test_ownership_backend.py`。
- 改：`src/deepresearch_agent/graph_retrieval.py`（NeighborEdge 迁移/re-export、删 `_name`/`_type`/`_direct_neighbors`、`assemble_subgraph_context`/`hybrid_search` 吃 backend）、`src/deepresearch_agent/agents/graph.py`（`_build_graph_searcher` 包 backend）、`tests/test_graph_retrieval.py`、`tests/test_nodes.py`。
- 不改：`ownership_graph.py`、`graph_traversal.py`、`state.py`、`agents/nodes.py`、`cli.py`、`api.py`、SQLite schema、依赖。
- **零行为变化、零新依赖。** N2（Neo4j driver `.[neo4j]` extra、Docker、SQLite→Neo4j 灌图、`Neo4jBackend` Cypher、对拍测试、CI 跳过真 Neo4j）单独开。
