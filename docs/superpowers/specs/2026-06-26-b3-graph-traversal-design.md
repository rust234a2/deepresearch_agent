# 模块 B3：图遍历/多跳查询层设计

日期：2026-06-26

本文件是路线图阶段 B 第三块 **B3** 的设计 spec。B2（`OwnershipGraph` 内存图）已完成并合并。B3 在该图上提供纯确定性多跳查询算法，供 B5 混合检索 / Agent 接入使用。

## 背景与定位

B2 的 `load_ownership_graph(repository)` 给出 owner→owned 的有向图（节点 = B1 去重实体，边 = 持股/投资，带出/入邻接）。B3 在其上实现四个图算法：ego-graph、最终控制人穿透、共同控制人、最短路径。这是"孤岛星型"数据里 1–2 跳能挖出的核心价值（共同实控人、围标线索、主体穿透），是 A4 单跳关联的多跳推广。

## 全局约束（红线）

- **纯确定性、零 LLM、零新依赖、无 schema 变更**（不引入 NetworkX，纯 dict BFS/DFS）。
- **基金穿透策略（已确认 = A）**：遍历**不从 `fund` 类节点继续扩展**（fund 可作 ego-graph 的端点，但不从它走到它的其它持仓，防多跳爆炸）；`fund` 节点**不作为控制人结果**（被动持有/托管，非实控人）。
- **自然人穿透 + 置信交上层**：`person` 节点正常穿（自然人是实控人候选），但**任何经过 person 节点的路径/结果标 `via_person=True`**；B3 **不**自己算置信度、不写免责，只输出"结构 + `via_person` 标记"，由上层（B5/Agent）据此贴低置信与"须人工复核"（与 A5 关联方证据同一处逻辑）。
- **防环**：所有遍历带 visited 集合。
- **确定性顺序**：扩展邻居按 `node_id` 排序，结果按稳定键排序。

## 模块（新文件 `graph_traversal.py`）

函数都吃一个 `OwnershipGraph`。方向约定：**入边（`in_edges`/`predecessors`）= 向上（找控制人/股东）**；**出边（`out_edges`/`successors`）= 向下（持有/投资谁）**。

```python
DEFAULT_BLOCK_EXPAND_TYPES = ("fund",)   # 不从这些类型的节点继续扩展
```

### 结果模型（`graph_traversal.py`，Pydantic）

```python
class EgoResult(BaseModel):
    center: str
    node_ids: list[str]        # 排序，含 center
    edges: list[GraphEdge]     # 邻域内部边

class ControllerResult(BaseModel):
    node_id: str
    display_name: str
    depth: int                 # 距查询节点的跳数
    via_person: bool           # 路径是否经过自然人

class CommonController(BaseModel):
    node_id: str
    display_name: str
    depth_from_a: int
    depth_from_b: int
    via_person: bool

class GraphPath(BaseModel):
    node_ids: list[str]        # 从 a 到 b 有序
    length: int
    via_person: bool
```

### 算法

1. **`ego_graph(graph, node_id, radius=2, block_expand_types=DEFAULT_BLOCK_EXPAND_TYPES) -> EgoResult`**
   双向 BFS（in + out）至 `radius` 跳。到达 `fund` 类节点时**加入节点集但不从它继续扩展**。返回到达的 `node_ids`（排序、含 center）+ 这些节点之间的边。未知/孤立节点 → 只含 center、空边。

2. **`ultimate_controllers(graph, node_id, max_depth=5, block_expand_types=DEFAULT_BLOCK_EXPAND_TYPES) -> list[ControllerResult]`**
   沿入边向上 DFS/BFS，跳过 `fund` 节点（不计入、不扩展）。某非 fund 节点是**最终控制人**当：它无非 fund 的上层入边（根），**或**它是 `person`（自然人为控制链终点），**或**触达 `max_depth`。每个最终控制人返回 `depth` 与 `via_person`（路径上是否含 person）。按 `(depth, node_id)` 排序。

3. **`common_controllers(graph, node_a, node_b, max_depth=5, block_expand_types=...) -> list[CommonController]`**
   分别求 a、b 的"向上可达非 fund 节点集合"（带各自最短 depth 与 via_person），求交，排除 a、b 自身。每个共同控制人返回 `depth_from_a`/`depth_from_b` 与 `via_person`（任一侧路径经过 person 即 True）。按 `(depth_from_a + depth_from_b, node_id)` 排序。

4. **`shortest_path(graph, node_a, node_b, max_depth=6, block_expand_types=...) -> GraphPath | None`**
   把图当**无向**做 BFS（同时看出入边），**不经过 fund 节点**（fund 只能作端点，但 a/b 是公司故路径不含 fund）。返回最短路径节点序列、长度、`via_person`；不连通或超 `max_depth` → `None`。

## 数据流验证（现有 `ownership_links` fixture，无需改 fixture）

fixture 含 2 跳链：`甲←乙`（乙是甲股东）且 `乙←共同控股集团`，故 `甲←乙←共同控股集团`。

- `ultimate_controllers(甲)` → `共同控股集团`（根，via_person=False）、`张三`（person 终点，via_person=True）；`乙` 是中间节点不算最终。
- `common_controllers(甲, 丙)` → `张三`（甲、丙 都被张三持有，via_person=True）。
- `common_controllers(甲, 乙)` → `共同控股集团`（via_person=False；排除 a/b 自身）。
- `shortest_path(甲, 丙)` → `[甲, 丙]`，length=1，via_person=False（甲直接投资丙，无向图里 1 跳直连）。`shortest_path(乙, 丙)` → `[乙, 甲, 丙]`，length=2。
- `ego_graph(甲, radius=1)` → 含 `甲`、入边来源（共同控股集团、张三、嘉实基金[fund 不扩展]、乙）、出边目标（丙、共同投资标的）。

## 错误处理

- 未知 `node_id`：`ego_graph` 返回只含 center 的结果；`ultimate_controllers`/`common_controllers` 返回 `[]`；`shortest_path` 返回 `None`。
- 同节点 `shortest_path(x, x)` → 长度 0 路径 `[x]`。

## 测试（`tests/test_graph_traversal.py`，新）

按上面"数据流验证"逐项断言；外加：
- `ego_graph` 不从 fund 扩展（fund 在节点集但其它持仓不进来）。
- `via_person` 正确（经张三的路径为 True，经共同控股集团的为 False）。
- 防环：构造/利用互持不死循环（fixture 无互持，用 max_depth 小值确保有界即可）。
- 未知节点/同节点边界。

## 改动面

- 新文件：`src/deepresearch_agent/graph_traversal.py`、`tests/test_graph_traversal.py`。
- 复用：B2 `OwnershipGraph`、B1 `GraphNode`/`node_type`、B2 `GraphEdge`。
- **无 schema 变更、无新依赖、无需重建真库**。不接 Agent（B7）、不做向量（B4）、不做混合检索（B5）。
