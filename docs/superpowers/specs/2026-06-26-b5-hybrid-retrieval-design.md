# 模块 B5（精简）：混合检索 / 子图上下文组装设计

日期：2026-06-26

本文件是路线图阶段 B 第五块 **B5** 的设计 spec（精简版）。B1–B3 已完成并合并。**B4（独立 83k 节点向量索引）经评估为冗余、本轮跳过**：节点文本≈名称、语义弱，且 `rag/` 的经营范围语义索引已覆盖库内公司，其输出（信用代码）即图节点 `node_id`，语义→图之间无需新索引。B5 复用 `rag/` 的 `ScopeRetriever` 作语义种子 + B3 图扩展，组装结构化子图上下文。

## 背景与定位

GraphRAG 的"local search"：查询 → 语义找种子公司 → 沿图扩展邻域 → 组装上下文供上层（B7/Agent）产证据。B5 = 这个检索+组装层。**扩展粒度（已确认 = ②）**：每个种子取 `ultimate_controllers`（B3）+ 1 跳直接邻域（直接股东 + 对外投资）+ **跨种子共享控制人**（≥2 个种子同属一个控制人 → 围标/集中度线索）。

## 全局约束（红线）

- **纯确定性、零 LLM、无 schema 变更**。
- **核心无 bge 依赖**：`assemble_subgraph_context` 只吃 `OwnershipGraph` + 种子代码，可用合成 fixture 测；语义检索在薄包装 `hybrid_search` 里，且 `hybrid_search` 对 retriever **鸭子类型**（只调 `.search(query,k)`、读 `.unified_social_credit_code`/`.score`），`graph_retrieval` **不 import `rag/`**，`.[rag]` 依赖只在真正构造 `ScopeRetriever` 处（B7 接入）。
- **置信/免责交上层**：B5 只组装结构 + 传递 B3 的 `via_person`，**不**算置信、不写免责。
- **确定性顺序**：邻居、控制人、共享控制人均按稳定键排序。

## 模块（新文件 `graph_retrieval.py`）

复用 `graph_traversal.ultimate_controllers` / `ControllerResult`；节点名/类型经 `graph.get_node(node_id)` 读取，**不**引入 `graph_traversal` 的私有助手。

### 结果模型（Pydantic）

```python
class NeighborEdge(BaseModel):
    node_id: str
    name: str
    node_type: str
    edge_type: Literal["shareholding", "investment"]
    direction: Literal["in", "out"]      # in=持有/投资种子；out=种子持有/投资它
    holding_pct: str | None = None

class SeedContext(BaseModel):
    code: str
    name: str
    score: float                          # 语义分；直接给种子时默认 0.0
    controllers: list[ControllerResult]   # B3 ultimate_controllers
    neighbors: list[NeighborEdge]         # 1 跳入+出

class SharedController(BaseModel):
    node_id: str
    name: str
    controlled_seeds: list[str]           # ≥2 个种子代码（排序）
    via_person: bool

class HybridContext(BaseModel):
    query: str | None
    seeds: list[SeedContext]
    shared_controllers: list[SharedController]
```

### 核心：`assemble_subgraph_context`

```python
def assemble_subgraph_context(
    graph: OwnershipGraph,
    seed_codes: list[str],
    max_depth: int = 5,
    query: str | None = None,
    scores: dict[str, float] | None = None,
) -> HybridContext
```

逻辑：
1. 对每个 `code`（跳过不在 `graph.nodes` 的）：
   - `controllers = ultimate_controllers(graph, code, max_depth=max_depth)`。
   - `neighbors = _direct_neighbors(graph, code)`：`graph.successors(code)` → `direction="out"`；`graph.predecessors(code)` → `direction="in"`；各带 `edge_type`/`holding_pct`/对手方名与类型；按 `(direction, node_id)` 排序。
   - `score = (scores or {}).get(code, 0.0)`。
   - 累加 `controller_id -> {控制的种子集合}` 与 `controller_id -> (name, via_person 取或)`。
2. `shared_controllers` = 控制 ≥2 个种子的控制人，按 `(-len(controlled_seeds), node_id)` 排序。
3. `seeds` 按 `(-score, code)` 排序。
4. 返回 `HybridContext`。

### 薄包装：`hybrid_search`

```python
def hybrid_search(query, scope_retriever, graph, k=10, max_depth=5) -> HybridContext:
    hits = scope_retriever.search(query, k)
    scores: dict[str, float] = {}
    for hit in hits:
        code = hit.unified_social_credit_code
        scores[code] = max(scores.get(code, 0.0), hit.score)   # 同公司多 chunk 取最高分
    seed_codes = sorted(scores, key=lambda c: (-scores[c], c))
    return assemble_subgraph_context(graph, seed_codes, max_depth=max_depth, query=query, scores=scores)
```

## 错误处理

- 种子代码不在图中 → 跳过；全不在 → `seeds=[]`、`shared_controllers=[]`。
- `hybrid_search` 不自己 catch retriever 异常（由上层 B7 像 `scope_search_node` 那样降级为不可用报告）。

## 测试（`tests/test_graph_retrieval.py`，新）

复用 `ownership_links` fixture + `load_ownership_graph`（无 bge）。

- **`test_assemble_shared_controllers`**：种子 `[甲, 乙, 丙]` → `shared_controllers` 含 `共同控股集团`（控制 {甲,乙}，via_person F）与 `张三`（控制 {甲,丙}，via_person T）。
- **`test_assemble_seed_context`**：种子 `[甲]` → 该 seed 的 `controllers` 含 共同控股集团/张三；`neighbors` 含 `丙`（out/investment）与 `共同控股集团`（in/shareholding）。
- **`test_assemble_skips_unknown_seed`**：`["no-such-code"]` → 空 seeds/shared。
- **`test_hybrid_search_uses_scope_seeds`**：stub retriever（鸭子类型，返回带 `unified_social_credit_code`/`score` 的对象）→ 种子取自 hits、按分排序、`shared_controllers` 正确。

## 改动面

- 新文件：`src/deepresearch_agent/graph_retrieval.py`、`tests/test_graph_retrieval.py`。
- 复用：B3 `ultimate_controllers`/`ControllerResult`、B2 `OwnershipGraph`、`rag/` 的 `ScopeRetriever`（鸭子类型，不 import）。
- **无 schema 变更、无新依赖、无需重建真库**。不接 Agent（B7）、B4 跳过、B6 缓做。
- 在路线图备注 B4 跳过的理由（spec 已记录）。
