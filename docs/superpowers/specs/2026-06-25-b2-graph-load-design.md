# 模块 B2：图谱构建/加载设计

日期：2026-06-25

本文件是路线图阶段 B 第二块 **B2** 的设计 spec。B1（实体解析 → `graph_nodes` 节点表）已完成并合并。B2 在节点表之上，把两份股权边映射到 `node_id` 空间，形成可遍历的有向图（owner → owned），供 B3 多跳遍历。

## 背景与定位

A2 的 `company_shareholders` / `company_investments` 两表以"公司信用代码 + 对手方（名 + 可选解析码）"存边；B1 把实体去重成带稳定 `node_id` 的 `graph_nodes`。B2 把每条边的两个端点都映射到 `node_id`，形成统一的有向图结构（外部实体也成为一等节点），让 B3 能按 `node_id` 做 ego-graph、最短路径、共同控制人等遍历。

**关键决策（已确认）：内存图加载器，不持久化、不改 schema。** 边已存在于两张边表，再建 `graph_edges` 表只是按 `node_id` 重存一遍（重复）；B1 的去重节点表才是真正的新增价值。B2 现算出内存 `OwnershipGraph`，B3 在其上跑遍历。**不引入 NetworkX**（纯 dict 邻接，零新依赖；NetworkX 留给 B3 按需评估）。

## 全局约束（红线）

- **纯确定性、零 LLM、零新依赖、无 schema 变更**。
- **node_id 一致性**：B2 边端点的 `node_id` 必须与 B1 `graph_nodes` 的 `node_id` 完全一致（同一套推导规则）。为此把 B1 `_insert_graph_nodes` 里的外部实体 `node_id` 推导抽成**共享函数** `external_node_id`，B1 建库与 B2 加载共用，杜绝漂移。
- **方向语义**：边表示 `source 持有/投资 target`（所有者 → 被持有）。
- **名称连接**沿用 `normalize_company_name`（边表已存 `normalized_*`）。

## node_id 推导（共享）

在 `company_models.py` 新增（复用已有 `FUND_NOISE_KEYWORDS`）：

```python
def external_node_id(normalized_name: str, is_person: bool) -> tuple[str, str]:
    """返回 (node_id, node_type)，用于无库内信用代码的外部实体。"""
    if is_person:
        return f"person:{normalized_name}", "person"
    if any(keyword in normalized_name for keyword in FUND_NOISE_KEYWORDS):
        return f"fund:{normalized_name}", "fund"
    return f"ext:{normalized_name}", "company"
```

某端点的 `node_id`：有库内信用代码 → 该代码；否则 → `external_node_id(normalized_name, is_person)[0]`。

`company_database._insert_graph_nodes` 的 `bump_external` 改为调用 `external_node_id`（行为不变，去重）。

## 边方向与属性

| 边类型 | source | target | holding_pct | status |
|---|---|---|---|---|
| `shareholding`（股东持有公司） | 股东节点 | 锚点公司节点 | 股东行的 `indirect_holding_pct`（原文） | None |
| `investment`（公司投资被投资方） | 锚点公司节点 | 被投资方节点 | 投资行的 `holding_pct`（原文） | 投资行的 `status`（原文） |

`holding_pct` / `status` 原文透传（与 A2/A3 一致，不解析）。详细字段（份额、认缴、行业等）不进图边，需要时仍由 A3 的 `get_shareholders`/`get_investments` 回查。

## 数据模型（`company_models.py`）

```python
class GraphEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_type: Literal["shareholding", "investment"]
    holding_pct: str | None = None
    status: str | None = None
```

## Repository（`company_repository.py`）

新增 `iter_graph_edges() -> list[GraphEdge]`：

- 读 `company_shareholders`（`unified_social_credit_code`, `normalized_shareholder_name`, `shareholder_credit_code`, `shareholder_is_person`, `indirect_holding_pct`）：`target=锚点码`，`source=shareholder_credit_code or external_node_id(normalized_shareholder_name, is_person)[0]`，`edge_type="shareholding"`，`holding_pct=indirect_holding_pct`，`status=None`。
- 读 `company_investments`（`unified_social_credit_code`, `normalized_investee_name`, `investee_credit_code`, `holding_pct`, `status`）：`source=锚点码`，`target=investee_credit_code or external_node_id(normalized_investee_name, False)[0]`，`edge_type="investment"`，`holding_pct`、`status` 原文。
- 空串经 `none_if_blank` 归 None（`holding_pct`/`status`）。

## 内存图（新模块 `ownership_graph.py`）

```python
@dataclass
class OwnershipGraph:
    nodes: dict[str, GraphNode]            # node_id -> 节点
    edges: list[GraphEdge]
    out_edges: dict[str, list[GraphEdge]]  # 按 source 分组
    in_edges: dict[str, list[GraphEdge]]   # 按 target 分组

    def get_node(self, node_id: str) -> GraphNode | None
    def successors(self, node_id: str) -> list[GraphEdge]    # 出边（该节点持有/投资谁）
    def predecessors(self, node_id: str) -> list[GraphEdge]  # 入边（谁持有/投资该节点）


def load_ownership_graph(repository: CompanyRepository) -> OwnershipGraph:
    nodes = {node.node_id: node for node in repository.iter_graph_nodes()}
    edges = repository.iter_graph_edges()
    out_edges, in_edges = {}, {}
    for edge in edges:
        out_edges.setdefault(edge.source_node_id, []).append(edge)
        in_edges.setdefault(edge.target_node_id, []).append(edge)
    return OwnershipGraph(nodes, edges, out_edges, in_edges)
```

- 每条边的两个端点都应是 `nodes` 里的已知节点（B1 节点与 B2 边由同一批边、同一套 `node_id` 规则派生，天然一致）。
- 加载是只读、确定性的；按 Agent 单次研究加载一次（与 A4/B 内存方案一致）。

## 错误处理

- 库不存在 / schema 不匹配由 `_connect()` 抛出（`FileNotFoundError` / `RuntimeError`）。
- `successors`/`predecessors`/`get_node` 对未知 `node_id` 返回 `[]` / `None`。

## 测试

**Repository（`tests/test_company_repository.py`）**：`iter_graph_edges` 用 `ownership_links` fixture，断言：
- 持股边 `共同控股集团 → 甲`（`source=ext:共同控股集团有限公司`、`target=甲码`、`shareholding`）。
- 直接持股边 `乙 → 甲`（`source=乙码`、`target=甲码`）。
- 投资边 `甲 → 丙`（`source=甲码`、`target=丙码`、`investment`）。
- 投资边 `甲 → 共同投资标的`（`target=ext:...`、`investment`）。

**内存图（`tests/test_ownership_graph.py`，新）**：
- `load_ownership_graph` 后 `nodes` 含全部 B1 节点；`edges` 数 = 边表行数。
- `successors("甲码")` 含投资甲所投的边；`predecessors("甲码")` 含持有甲的边（乙、共同控股集团、张三、嘉实基金）。
- `get_node("甲码").node_type == "company"`；未知 id → `successors` 空、`get_node` 为 None。
- `external_node_id` 单元：person/fund/company 三分支。

## 改动面

- `company_models.py`：`external_node_id` 函数、`GraphEdge` 模型。
- `company_database.py`：`_insert_graph_nodes` 改用 `external_node_id`（DRY，行为不变）。
- `company_repository.py`：`iter_graph_edges`。
- `ownership_graph.py`（新）：`OwnershipGraph` + `load_ownership_graph`。
- 测试：`test_ownership_graph.py`（新）、`test_company_repository.py`（+`iter_graph_edges`）。
- **无 schema 变更、无 `SCHEMA_VERSION` 改动、无新依赖、无需重建真库**。
