# 模块 B7：GraphRAG Agent 接入设计

日期：2026-07-01

本文件是路线图阶段 B 第七块 **B7** 的设计 spec。B1–B3、B5 已完成并合并（B4 跳过、B6 缓做）。B7 把 B5 的混合检索接进 LangGraph Agent 的**能力检索路径**，让"按能力找供应商"的查询额外返回候选的最终控制人与**跨候选共享控制人（围标线索）**。

## 背景与定位

现状：planner 解析不到具名公司（`not_found`）且开启 scope 时，路由到 `scope_search_node`，用经营范围语义检索返回候选名单。B7 在同一条岔路上加一个**图增强**版本：用 B5 `hybrid_search`（语义种子 + 图扩展）返回候选 + 每家最终控制人 + **跨候选共享控制人**。

**范围（已确认 = 实现一）**：只做能力检索路径的围标线索；**不**给具名公司报告加多跳控制人维度（那是后续可选项）。

## 全局约束（红线）

- **纯确定性、零 LLM、零新依赖、无 schema 变更**。
- **recommendation 固定 `insufficient_evidence`**；围标是**线索**不是结论；`via_person` 的共享控制人标低置信 + "须人工复核"。
- **降级**：节点内懒加载 rag + 图，缺 `.[rag]`/索引/图则降级为"不可用"报告（同 `scope_search_node`），不崩。
- **API 形状不变**：`enable_graph` 仅 CLI 开；`/research` 接口不变（与 `enable_scope` 一致）。

## 数据模型（`state.py`）

```python
class GraphSearchCandidate(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    top_score: float
    ultimate_controllers: list[str]   # 控制人显示名；自然人控制人后缀 "（疑·须人工复核）"

class SharedControllerFinding(BaseModel):
    controller_name: str
    controlled_companies: list[str]   # 该控制人控制的候选公司法定名
    via_person: bool
    note: str                         # via_person → "经同名自然人推断，须人工复核"；否则 "经企业股权链推断"

class GraphSearchReport(BaseModel):
    query: str
    recommendation: Recommendation = "insufficient_evidence"
    summary: str
    candidates: list[GraphSearchCandidate]
    shared_controllers: list[SharedControllerFinding]
    open_questions: list[str]
```

`ResearchState` 增字段 `graph_report: GraphSearchReport | None = None`。

## 节点（`agents/nodes.py`）

```python
def graph_search_node(state: ResearchState, searcher) -> ResearchState
```

- `searcher` 是 `callable(query) -> HybridContext` 或 `None`。
- `searcher is None` → 不可用报告（summary 提示装 `.[rag]` 并构建图/索引；`candidates`/`shared_controllers` 空；recommendation 仍 `insufficient_evidence`）。
- 否则 `try: ctx = searcher(state.question)`，异常 → 不可用报告（同 scope 兜底）。
- 由 `HybridContext` 组装 `GraphSearchReport`：
  - `candidates`：每个 `seed` → `GraphSearchCandidate`（code、name、score、`ultimate_controllers` = 控制人显示名列表，`via_person` 的加 "（疑·须人工复核）" 后缀）。
  - `shared_controllers`：每个 `HybridContext.shared_controllers` → `SharedControllerFinding`（控制人名、被控候选的**法定名**[由 controlled_seeds 代码经 seeds 映射]、via_person、note）。
  - `summary`：有候选时 "按经营范围语义检索到 N 家候选；其中 M 组疑似共享控制人（围标/集中度线索，须人工复核）；现有数据不足以作采购批准或风险结论。"；无候选时 "未检索到经营范围匹配的企业。"；无共享控制人时 summary 里 M=0 措辞为 "未发现候选间共享控制人"。
  - `open_questions`：沿用 scope 的免责清单 + 一条 "共享控制人为线索级推断（尤其同名自然人），须人工复核，不构成围标认定。"

## 编排（`agents/graph.py`）

- `build_graph(domain_pack, repository, scope_node=None, graph_node=None)`：新增 `graph_node` 参数（与 `scope_node` 对称）。
- 路由 `route_after_planner`：`not_found` 时——`graph_node` 存在 → `"graph_search"`；否则 `scope_node` 存在 → `"scope_search"`；否则 `"writer"`。（图增强优先，因其含 scope 语义 + 图扩展。）
- `run_research(..., enable_scope=False, enable_graph=False)`：`enable_graph` 时构建 `graph_node`。
- `_build_graph_node(database_path, index_path)`：懒加载 `BgeEmbedder` + `load_scope_retriever` + `load_ownership_graph(repository)`；任一失败 → `searcher=None`。`searcher = lambda q: hybrid_search(q, retriever, graph)`。返回 `lambda state: graph_search_node(state, searcher)`。

## CLI（`cli.py`）

- 加 `--graph`（store_true，默认关）→ `run_research(..., enable_graph=True)`。
- `main` 优先打印 `state.graph_report`（候选表 + 共享控制人表），否则 scope/supplier 报告。
- 新增 `_print_graph_report`：候选表（公司/控制人/分数）+ 共享控制人表（控制人/被控候选/是否自然人疑似）。

## 测试

**节点（`tests/test_nodes.py` 套件内，无 bge）**：用 `ownership_links` fixture 建图，`searcher = lambda q: assemble_subgraph_context(graph, [A,B,C])`：
- `graph_search_node` 产 `GraphSearchReport`：candidates 含甲/乙/丙；`shared_controllers` 含 `共同控股集团`（控制全部三家，via_person F）与 `张三`（via_person T、note 含"须人工复核"）；recommendation `insufficient_evidence`。
- `searcher=None` → 不可用报告（summary 含"不可用"、空候选）。
- searcher 抛异常 → 不可用报告。

**编排（`tests/test_graph.py` 套件内）**：
- 注入 stub `graph_node`（返回固定 `GraphSearchReport`），能力查询路由到 `graph_search`（`state.graph_report` 非空、`state.report` 为空）；具名公司仍走核验（`report` 非空、`graph_report` 空）。
- `run_research(enable_graph=True, index_path=不存在)` → 降级不可用报告（不崩）。

## 改动面

- `state.py`：3 个模型 + `ResearchState.graph_report`。
- `agents/nodes.py`：`graph_search_node` + 组装助手。
- `agents/graph.py`：`graph_node` 参数 + 路由 + `run_research(enable_graph)` + `_build_graph_node`。
- `cli.py`：`--graph` flag + `_print_graph_report`。
- 测试：`test_nodes.py`、`test_graph.py` 增用例。
- **无 schema 变更、无新依赖、无需重建真库**。复用 B5 `hybrid_search`/`assemble_subgraph_context`、`rag/` 的 `ScopeRetriever`、B2 `load_ownership_graph`。
