# 模块 C2：查询编排（检索/生成分层）设计

日期：2026-07-01

本文件是路线图阶段 C 第二块 **C2** 的设计 spec。C1 已交付查询复杂度分类器（`classify_complexity` + DeepSeek 适配器），但**未接入编排**。C2 做两件事：

1. 把 C1 分类器接进 planner，按复杂度把查询分流到三种检索策略。
2. 按用户确认的架构收敛，做一次**检索/生成分层**重构：`researcher` 收归全部检索，`writer` 收归全部生成，撤销 `scope_search` / `graph_search` 两个独立节点。

**本模块合并 C3**（结构化生成 = writer 单独生成）。C2 之后路线图只剩 **C4（降级/重试）**。

## 红线（不变）

- 报告对已解析企业**固定** `recommendation="insufficient_evidence"`；绝不写"未发现风险"或采购批准/拒绝结论。
- 股权关联方、共享控制人 = **线索级推断**（尤其同名自然人），带"须人工复核"，不构成控制关系或围标认定。
- LLM（C1 已保证）**只发查询文本**、只做查询分类；不接触企业数据、不做采购结论。
- 不接实时 API、爬虫、Qdrant、MCP。检索器全是本地既有能力（具名工具 / FAISS scope / 内存图）。

## 分层架构

现状是 `planner → researcher → critic → writer`，外加 planner 后的条件路由把 `not_found` 甩到独立的 `scope_search` / `graph_search` 节点（各自既检索又生成报告，然后直接 END）。C2 把它改成**纯线性**图，检索与生成各归其位。

### planner（解析 + 分类，不检索）

- `resolve_supplier(question, repository)`（现状不变）→ `state.supplier_resolution` / `supplier_name` / `company_credit_code`。
- **新增**：`classify_complexity(question, repository, llm)` → `state.complexity`（`ComplexityResult`）。`llm` 为注入的可选分类器（`build_deepseek_classifier()` 的返回值，无 key/无依赖时为 `None`，走确定性启发式）。
- 解析成功（`resolved`）才建 `plan`（现状不变）；否则 `plan=[]`。

### researcher = 检索层（按 解析状态 × 复杂度 分派）

researcher 从 `resolution.status` + `complexity.level` 推导**检索模式**，只做检索，把结果落到 state 的中间字段，**不产出任何报告叙述**（summary / open_questions / recommendation 全部交给 writer）。

派发矩阵：

| `resolution.status` | `complexity.level` | 检索模式 `retrieval_mode` | 实际检索 |
|---|---|---|---|
| `resolved` | 任意 | `named` | 4 个具名工具 → `state.evidence` |
| `not_found` | `medium` / `complex` | `graph`（无 searcher 则回退 `scope`） | `hybrid_search` → `graph_candidates` + `shared_controllers` |
| `not_found` | `simple` | `scope` | `retriever.search` → `scope_candidates` |
| `ambiguous` | 任意 | `unresolved` | 不检索 |

各模式检索行为：

- **named**：沿用现状——按 `domain_pack.allowed_tools` 依次调 `get_company_profile` / `get_company_contact` / `get_ownership_neighborhood` / `get_related_parties`，拆成六+两个维度的 `Evidence` 追加到 `state.evidence`。`iteration += 1`（保留 critic 回环）。
- **scope**：`retriever.search(question, k=10)` → 复用 `_group_scope_hits` 逻辑分组为 `list[ScopeCandidate]` → `state.scope_candidates`。
- **graph**：`searcher(question)`（`hybrid_search` 封装）→ 由 `HybridContext` 组装 `list[GraphSearchCandidate]`（含 `ultimate_controllers`，`via_person` 标"疑·须人工复核"）与 `list[SharedControllerFinding]` → `state.graph_candidates` / `state.shared_controllers`。
- **unresolved**：不检索，留空。
- **检索器缺失/异常**（retriever/searcher 为 `None` 或 `search`/`searcher` 抛异常）：置 `state.retrieval_available=False`，不抛出；生成"不可用"叙述由 writer 负责。

回退细节：desired=`graph` 但注入的 `graph_searcher` 为 `None` → 退到 `scope`（若 `scope_retriever` 存在）；desired=`scope` 但 `scope_retriever` 为 `None` → `retrieval_available=False`。

> 说明：researcher 里针对 `named` 路径仍要求 `supplier_name`/`credit_code` 已解析；对 `scope`/`graph`/`unresolved` 模式**不再抛 `ValueError`**（现状会抛），改为按模式走对应分支或直接跳过检索。

### writer = 生成层（唯一报告生成者）

writer 按检索模式产出对应报告，**所有叙述性文字（summary / open_questions / recommendation / 人工复核提示）都在此生成**：

| 模式 | 产出 | 落到 state |
|---|---|---|
| `named` | `SupplierReport`（现状逻辑不变，固定 `insufficient_evidence`） | `state.report` |
| `unresolved`（含 `ambiguous`） | 未解析 `SupplierReport`（现状 `_write_unresolved_supplier_report`） | `state.report` |
| `scope` | `ScopeSearchReport`（此处生成 summary + `_SCOPE_OPEN_QUESTIONS`） | `state.scope_report` |
| `graph` | `GraphSearchReport`（此处生成 summary + 每条 shared 的 note + `_GRAPH_OPEN_QUESTIONS`） | `state.graph_report` |
| 检索器不可用 | 对应的不可用报告（提示装 `.[rag]` 并构建索引/图谱） | `scope_report` / `graph_report` |

`scope_report` / `graph_report` / `report` 字段保留在 state，CLI 打印逻辑不变。

### 图简化（`agents/graph.py`）

- 图变为纯线性：`planner → researcher → critic → writer → END`。
- **删除**：`route_after_planner` 条件路由、`scope_search` / `graph_search` 两个节点、`_build_scope_node` / `_build_graph_node` 里的"节点工厂"包装（检索器构建逻辑保留，但改为直接注入 researcher）。
- **critic 保留**：`missing_dimensions` 非空且 `iteration < max_iterations(3)` 回 researcher，否则进 writer（`_should_continue` 不变）。实际只有 `named` 路径会累积维度、可能回环；其余模式 `plan=[]` → 无缺口 → 直通 writer。
- `ambiguous` 不再需要专门的 planner→writer 短路：researcher 对 `unresolved` 模式跳过检索，critic 无缺口，writer 出未解析报告。

### 检索器 / LLM 注入

`build_graph(domain_pack, repository, scope_retriever=None, graph_searcher=None, llm=None)`：

- planner 闭包用 `llm`；researcher 闭包用 `scope_retriever` + `graph_searcher`。
- `run_research(question, domain, database_path, index_path, enable_scope=False, enable_graph=False)`：
  - `llm = build_deepseek_classifier()`（无 key/无 `.[llm]` → `None`，自动走启发式）。
  - `enable_scope` → 尝试构建 `scope_retriever`（复用现 `_build_scope_node` 内的懒加载，改为返回 retriever 本体）。
  - `enable_graph` → 尝试构建 `graph_searcher`（复用现 `_build_graph_node` 内的 `hybrid_search` 闭包）。
  - 缺 `.[rag]`/索引 → 对应检索器为 `None`，researcher 走"不可用"分支。
- API `/research`（`enable_scope=enable_graph=False`）形状不变：`not_found` → researcher `unresolved`（无检索器）→ writer 未解析报告。

## state 变更（`state.py`）

新增字段（均带默认值，保持向后兼容）：

```python
complexity: ComplexityResult | None = None
retrieval_mode: Literal["named", "scope", "graph", "unresolved"] | None = None
retrieval_available: bool = True
scope_candidates: list[ScopeCandidate] = Field(default_factory=list)
graph_candidates: list[GraphSearchCandidate] = Field(default_factory=list)
shared_controllers: list[SharedControllerFinding] = Field(default_factory=list)
```

- `ComplexityResult` 从 `query_complexity` 导入（已是 Pydantic 模型）。
- `ScopeCandidate` / `GraphSearchCandidate` / `SharedControllerFinding` 已存在，复用。
- 保留 `scope_report` / `graph_report` / `report`（writer 产出，供 CLI）。
- **无 SQLite schema 变更**（`SCHEMA_VERSION` 不动）。

## CLI / API

- `cli.py`：`--graph` / scope 默认行为等价保留；`_print_scope_report` / `_print_graph_report` 不变（读 `state.scope_report`/`graph_report`）。可选：多打印一行 `state.complexity`（级别 + method）便于观察分流，非必需。
- **行为变化点**：同一入口现在**按复杂度自动选 scope 还是 graph**——`not_found` 不再"只要 enable_graph 就一律 graph"，而是 `simple→scope`、`medium/complex→graph`（graph 不可用时退 scope）。这是 C2 的核心价值。
- API `/research` 请求/响应形状不变。

## 测试

沿用 Windows 约定：`-p no:cacheprovider --basetemp=.conda-cache/pytest-c2`。

**planner（`tests/test_nodes.py`）**
- 注入 stub `llm=lambda q: "complex"` → `state.complexity.level=="complex"`、`method=="llm"`。
- 不注入 llm → `state.complexity.method=="heuristic"`（走 C1 启发式）。

**researcher 派发（`tests/test_nodes.py`，重写旧 scope/graph 节点测试）**
- `resolved` → `retrieval_mode=="named"`，`state.evidence` 覆盖六维（沿用现 `test_researcher_collects_all_source_backed_dimensions` 断言）。
- `not_found` + `complexity=simple` + 注入假 retriever → `retrieval_mode=="scope"`，`scope_candidates` 分组正确（迁移现 `test_scope_search_node_groups_hits_into_candidates`）。
- `not_found` + `complexity=medium` + 注入假 searcher → `retrieval_mode=="graph"`，`graph_candidates` + `shared_controllers`（`via_person` 标注，迁移现 `test_graph_search_node_reports_candidates_and_shared_controllers`）。
- `ambiguous` → `retrieval_mode=="unresolved"`，不检索、不抛异常。
- 回退：desired graph 但 `graph_searcher=None`、`scope_retriever` 存在 → 退 `scope`。
- 检索器为 `None` → `retrieval_available==False`，不抛异常。

**writer 生成（`tests/test_nodes.py`）**
- `named` → `SupplierReport.recommendation=="insufficient_evidence"`（现 `test_writer_never_approves_from_registration_data_only` 保留）。
- `unresolved`/`ambiguous` → 未解析报告（现有断言迁移）。
- `scope` → `ScopeSearchReport`，summary 含候选数，`open_questions` 含产能/交期免责句。
- `graph` → `GraphSearchReport`，`shared_controllers` 有"须人工复核"note，`open_questions` 含围标免责句。
- 检索器不可用 → 报告 summary 含"不可用"、`open_questions` 含"安装 .[rag]"。

**端到端（`tests/test_graph.py`，按线性图重写）**
- `build_graph` 新签名（`scope_retriever=` / `graph_searcher=` / `llm=`）。删除 `scope_node=`/`graph_node=` 及 `route_after_planner` 相关旧测试。
- 具名企业 → 源可溯 `SupplierReport`（现 `test_graph_generates_source_backed_company_report` 迁移）。
- 具名去重（现 `test_graph_deduplicates_evidence_and_tool_calls` 迁移）。
- 未知企业无检索器 → 未解析报告（现 `test_graph_returns_insufficient_evidence_for_unknown_company` 迁移）。
- 迭代预算耗尽仍收敛（现 `test_router_stops_when_iteration_budget_is_exhausted` 迁移）。
- `run_research(enable_scope=True)` 无索引 → scope 不可用报告；`enable_graph=True` 无索引 → graph 不可用报告（现有两条迁移）。
- 复杂度分流：`not_found` + 关系词（medium）+ 注入假 searcher → 走 graph；`not_found` 纯能力（simple）+ 假 retriever → 走 scope。

**API（`tests/test_api.py`）**：`/research` 形状与既有断言不变（确认重构不破坏）。

## 改动面

- 改：
  - `src/deepresearch_agent/state.py`（新增 6 字段 + 导入 `ComplexityResult`）。
  - `src/deepresearch_agent/agents/nodes.py`（planner 加分类；researcher 重构为派发器；writer 扩为唯一生成者，吸收 scope/graph 报告生成；删除 `scope_search_node` / `graph_search_node`）。
  - `src/deepresearch_agent/agents/graph.py`（线性图 + 检索器/LLM 注入；删除条件路由与节点工厂）。
  - `src/deepresearch_agent/cli.py`（可选打印 complexity；检索器构建适配新注入签名）。
  - `tests/test_nodes.py`、`tests/test_graph.py`（按新分层重写；`tests/test_api.py` 回归确认）。
- 复用：`query_complexity.classify_complexity`、`llm.deepseek.build_deepseek_classifier`、`rag.retriever.load_scope_retriever`、`graph_retrieval.hybrid_search`、现有 `_group_scope_hits` 与 report 组装逻辑。
- **无 SQLite schema 变更；无新依赖**（`.[rag]` / `.[llm]` 均为已存在的可选 extra）。C3 已并入本模块；C4 为后续。
