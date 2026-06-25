# 模块 B2：图谱构建/加载实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 B1 节点表之上，把两份股权边映射到 `node_id` 空间，提供内存有向图 `OwnershipGraph`（含出/入邻接），供 B3 多跳遍历。无 schema 变更、无新依赖。

**Architecture:** 抽出共享的 `external_node_id` 让 B1 建库与 B2 加载用同一套 `node_id` 规则；Repository 新增 `iter_graph_edges()` 把边表两端映射到 `node_id`；新模块 `ownership_graph.py` 的 `load_ownership_graph` 从 `graph_nodes` + 边构出内存图。

**Tech Stack:** Python 3.11、Pydantic v2、SQLite、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM、零新依赖、无 schema 变更**（`SCHEMA_VERSION` 保持 4）。
- **node_id 一致**：边端点 `node_id` 必须等于 B1 `graph_nodes` 的 `node_id` —— 共享 `external_node_id`。
- **方向**：边 = `source 持有/投资 target`。持股边 `source=股东、target=公司`；投资边 `source=公司、target=被投资`。
- `holding_pct`/`status` 原文透传，空串归 `None`。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`。每个 Task 一提交，中文提交信息。

---

### Task 1: 共享 `external_node_id` + `GraphEdge` + `iter_graph_edges`

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`（`external_node_id` 函数、`GraphEdge` 模型）
- Modify: `src/deepresearch_agent/company_database.py`（`_insert_graph_nodes` 改用 `external_node_id`）
- Modify: `src/deepresearch_agent/company_repository.py`（导入 + `iter_graph_edges`）
- Modify: `tests/test_company_repository.py`（`iter_graph_edges` 用例 + ownership_links 建库 helper）

**Interfaces:**
- Consumes：B1 的 `graph_nodes`、`FUND_NOISE_KEYWORDS`、`none_if_blank`；A2 边表列。
- Produces：
  - `company_models.external_node_id(normalized_name: str, is_person: bool) -> tuple[str, str]`（返回 `(node_id, node_type)`）。
  - `company_models.GraphEdge`（`source_node_id`, `target_node_id`, `edge_type`, `holding_pct`, `status`）。
  - `CompanyRepository.iter_graph_edges() -> list[GraphEdge]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾新增（`FIXTURES` 已是 `.../procurement`）：

```python
_LINKS = FIXTURES / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _build_ownership_links_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        _LINKS / "companies.csv",
        _LINKS / "contacts.csv",
        database_path,
        shareholders_csv=_LINKS / "shareholders.csv",
        investments_csv=_LINKS / "investments.csv",
    )
    return database_path


def test_iter_graph_edges_maps_endpoints_to_node_ids(tmp_path):
    repository = CompanyRepository(_build_ownership_links_database(tmp_path))

    edges = repository.iter_graph_edges()

    triples = {(e.source_node_id, e.target_node_id, e.edge_type) for e in edges}
    assert ("ext:共同控股集团有限公司", A_CODE, "shareholding") in triples
    assert (B_CODE, A_CODE, "shareholding") in triples
    assert (A_CODE, C_CODE, "investment") in triples
    assert (A_CODE, "ext:共同投资标的有限公司", "investment") in triples
    fund_edge = next(
        e for e in edges if e.source_node_id.startswith("fund:") and e.target_node_id == A_CODE
    )
    assert fund_edge.edge_type == "shareholding"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_graph_edges_maps_endpoints_to_node_ids -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`
Expected: FAIL —`AttributeError: 'CompanyRepository' object has no attribute 'iter_graph_edges'`。

- [ ] **Step 3: 加 `external_node_id` + `GraphEdge`，并让 B1 复用**

在 `src/deepresearch_agent/company_models.py` 中，`FUND_NOISE_KEYWORDS` 常量之后、`RelatedPartyConfig` 之前新增函数：

```python
def external_node_id(normalized_name: str, is_person: bool) -> tuple[str, str]:
    if is_person:
        return f"person:{normalized_name}", "person"
    if any(keyword in normalized_name for keyword in FUND_NOISE_KEYWORDS):
        return f"fund:{normalized_name}", "fund"
    return f"ext:{normalized_name}", "company"
```

在 `company_models.py` 末尾（`GraphNode` 之后）新增模型：

```python
class GraphEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_type: Literal["shareholding", "investment"]
    holding_pct: str | None = None
    status: str | None = None

    @field_validator("holding_pct", "status", mode="before")
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)
```

在 `src/deepresearch_agent/company_database.py` 把导入

```python
from deepresearch_agent.company_models import FUND_NOISE_KEYWORDS, CompanyContact, CompanyProfile
```

改为（不再直接用 `FUND_NOISE_KEYWORDS`，改用 `external_node_id`）：

```python
from deepresearch_agent.company_models import CompanyContact, CompanyProfile, external_node_id
```

把 `_insert_graph_nodes` 内的 `bump_external` 函数体开头

```python
    def bump_external(display_name: str, normalized_name: str, is_person: bool) -> None:
        if is_person:
            node_id = f"person:{normalized_name}"
            node_type = "person"
        elif any(keyword in normalized_name for keyword in FUND_NOISE_KEYWORDS):
            node_id = f"fund:{normalized_name}"
            node_type = "fund"
        else:
            node_id = f"ext:{normalized_name}"
            node_type = "company"
        node = nodes.get(node_id)
```

改为：

```python
    def bump_external(display_name: str, normalized_name: str, is_person: bool) -> None:
        node_id, node_type = external_node_id(normalized_name, is_person)
        node = nodes.get(node_id)
```

- [ ] **Step 4: 加 `iter_graph_edges`**

在 `src/deepresearch_agent/company_repository.py` 的 `company_models` 导入列表加入 `GraphEdge`、`external_node_id`（`GraphEdge` 置于 `CompanyResolutionCandidate` 之后、`GraphNode` 之前；`external_node_id` 是函数，加在末尾一行）：

```python
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
    GraphEdge,
    GraphNode,
    InvestmentRecord,
    OwnershipEdge,
    ScopeChunkRecord,
    ScopeIndexMetadata,
    ShareholderRecord,
    external_node_id,
)
```

在 `iter_graph_nodes` 之后新增：

```python
    def iter_graph_edges(self) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        with self._connect() as connection:
            for anchor, normalized, code, is_person, pct in connection.execute(
                "SELECT unified_social_credit_code, normalized_shareholder_name, "
                "shareholder_credit_code, shareholder_is_person, indirect_holding_pct "
                "FROM company_shareholders"
            ).fetchall():
                source = code if code is not None else external_node_id(normalized, is_person == "true")[0]
                edges.append(
                    GraphEdge(
                        source_node_id=source,
                        target_node_id=anchor,
                        edge_type="shareholding",
                        holding_pct=pct,
                        status=None,
                    )
                )
            for anchor, normalized, code, pct, status in connection.execute(
                "SELECT unified_social_credit_code, normalized_investee_name, "
                "investee_credit_code, holding_pct, status FROM company_investments"
            ).fetchall():
                target = code if code is not None else external_node_id(normalized, False)[0]
                edges.append(
                    GraphEdge(
                        source_node_id=anchor,
                        target_node_id=target,
                        edge_type="investment",
                        holding_pct=pct,
                        status=status,
                    )
                )
        return edges
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`
Expected: PASS（含新 `iter_graph_edges` 用例 + 既有节点/边读用例不回归）。

- [ ] **Step 6: 跑 B1 建库测试确认重构无回归**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`
Expected: PASS（`_insert_graph_nodes` 改用 `external_node_id` 后行为不变）。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_database.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：B2 共享 external_node_id 并加 GraphEdge 与 iter_graph_edges"
```

---

### Task 2: 内存图 `OwnershipGraph` + `load_ownership_graph`

**Files:**
- Create: `src/deepresearch_agent/ownership_graph.py`
- Create: `tests/test_ownership_graph.py`

**Interfaces:**
- Consumes：Task 1 的 `iter_graph_edges`、B1 的 `iter_graph_nodes`、`GraphNode`/`GraphEdge`、`external_node_id`。
- Produces：
  - `OwnershipGraph`（`nodes`/`edges`/`out_edges`/`in_edges` + `get_node`/`successors`/`predecessors`）。
  - `load_ownership_graph(repository: CompanyRepository) -> OwnershipGraph`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_ownership_graph.py`：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import external_node_id
from deepresearch_agent.company_repository import CompanyRepository
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


def test_external_node_id_branches():
    assert external_node_id("张三", True) == ("person:张三", "person")
    assert external_node_id("某证券投资基金", False) == ("fund:某证券投资基金", "fund")
    assert external_node_id("某公司", False) == ("ext:某公司", "company")


def test_load_ownership_graph_builds_nodes_and_adjacency(tmp_path):
    graph = _graph(tmp_path)

    assert graph.get_node(A_CODE) is not None
    assert graph.get_node(A_CODE).node_type == "company"
    # 甲 的入边（持有甲者）：乙、共同控股集团、张三、嘉实基金 至少含直接持股的乙
    predecessor_sources = {e.source_node_id for e in graph.predecessors(A_CODE)}
    assert B_CODE in predecessor_sources
    assert "ext:共同控股集团有限公司" in predecessor_sources
    assert "person:张三" in predecessor_sources
    # 甲 的出边（甲投资谁）：丙、共同投资标的
    successor_targets = {e.target_node_id for e in graph.successors(A_CODE)}
    assert C_CODE in successor_targets
    assert "ext:共同投资标的有限公司" in successor_targets


def test_load_ownership_graph_edge_count_and_unknown(tmp_path):
    graph = _graph(tmp_path)

    # 边数 = 入库边表行数（甲乙各 1 条共享股东 + 张三/嘉实/乙持甲 + 投资 4 条…）
    assert len(graph.edges) > 0
    assert all(e.source_node_id in graph.nodes and e.target_node_id in graph.nodes for e in graph.edges)
    assert graph.get_node("no-such-node") is None
    assert graph.successors("no-such-node") == []
    assert graph.predecessors("no-such-node") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.ownership_graph'`。

- [ ] **Step 3: 写 `ownership_graph.py`**

创建 `src/deepresearch_agent/ownership_graph.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field

from deepresearch_agent.company_models import GraphEdge, GraphNode
from deepresearch_agent.company_repository import CompanyRepository


@dataclass
class OwnershipGraph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    out_edges: dict[str, list[GraphEdge]] = field(default_factory=dict)
    in_edges: dict[str, list[GraphEdge]] = field(default_factory=dict)

    def get_node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def successors(self, node_id: str) -> list[GraphEdge]:
        return self.out_edges.get(node_id, [])

    def predecessors(self, node_id: str) -> list[GraphEdge]:
        return self.in_edges.get(node_id, [])


def load_ownership_graph(repository: CompanyRepository) -> OwnershipGraph:
    nodes = {node.node_id: node for node in repository.iter_graph_nodes()}
    edges = repository.iter_graph_edges()
    out_edges: dict[str, list[GraphEdge]] = {}
    in_edges: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        out_edges.setdefault(edge.source_node_id, []).append(edge)
        in_edges.setdefault(edge.target_node_id, []).append(edge)
    return OwnershipGraph(nodes=nodes, edges=edges, out_edges=out_edges, in_edges=in_edges)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b2`
Expected: PASS（3 passed）。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-b2-full`
Expected: PASS（118 + 本次新增，2 deselected）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/ownership_graph.py tests/test_ownership_graph.py
git commit -m "功能：B2 内存有向图 OwnershipGraph 与 load_ownership_graph"
```

---

## 自检

**Spec 覆盖**：
- `external_node_id` 共享 + B1 复用 → Task 1 Step 3。
- `GraphEdge` 模型 → Task 1 Step 3。
- `iter_graph_edges`（持股/投资两类、端点映射 node_id、属性原文）→ Task 1 Step 4 + 测试 Step 1。
- `OwnershipGraph` + `load_ownership_graph`（节点 dict、出/入邻接、get_node/successors/predecessors）→ Task 2。
- 边端点都在节点集内 → Task 2 的 `all(... in graph.nodes ...)` 断言。
- 无 schema 变更 → 不动 `SCHEMA_VERSION`/`_create_schema`。

**Placeholder 扫描**：无 TBD/TODO；每个改代码步骤给完整代码与命令/预期。

**类型一致性**：`external_node_id(normalized_name, is_person) -> (node_id, node_type)` 在 company_models 定义、company_database 复用、company_repository 复用、测试三处一致；`GraphEdge` 字段（`source_node_id`/`target_node_id`/`edge_type`/`holding_pct`/`status`）在模型、`iter_graph_edges`、`OwnershipGraph` 邻接、测试一致；node_id 方案与 B1 完全相同（共享函数保证）。
```
