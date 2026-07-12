# 网页端接入 scope/GraphRAG 自动路由设计

> 状态：设计已确认（三节经用户逐节 approve）。下一步 writing-plans 出实现计划。

## 目标

让网页端 `POST /session/turn` 复用 CLI（`run_research`）的完整检索逻辑：启用 scope + graph，由 **LLM 复杂度分类（无 LLM 则关系关键词启发式）自动决定是否调用 GraphRAG**，而非当前恒命名核验。复杂查询在网页也能出候选/控制人/围标线索，并在 graph 命中围标线索时于报告一侧给出「候选⇔控制人」节点可视化。

## 背景：当前三层差异（为何不是一个开关）

- **CLI**（`run_research`，graph.py:205）：懒加载 `scope_retriever`+`graph_searcher`，`build_graph(..., llm=_build_llm(), scope_enabled=True, graph_enabled=args.graph)`。输出按 `retrieval_mode` 为 `SupplierReport`/`ScopeSearchReport`/`GraphSearchReport` 之一。
- **网页**（`create_app`→`graph_for`，api.py）：`build_graph(domain_pack, repository)`——无检索器、无 llm、scope/graph 全关，恒 `SupplierReport`。
- **前端**（app.js `renderReport`）：只识别 `SupplierReport`（`evidence_table/risks/open_questions`）。scope/graph 报告字段是 `candidates/shared_controllers`，直接渲染会空白。
- **响应模型**：`SessionTurnResponse.report` 强类型 `SupplierReport`，返回图报告会校验失败。

故「移过去」牵动后端注入 + 响应模型 + 前端渲染三层。

## 架构

### 后端：`create_app` 注入检索器（照搬 run_research）

在 `create_app` 内、建缓存图时注入（沿用 `compiled_graphs` 缓存机制，启动建一次）：

```python
scope_retriever = _build_scope_retriever(database_path, index_path)      # 缺 .[rag]/索引 → None
graph_searcher  = _build_graph_searcher(database_path, scope_retriever)  # 连不上 Neo4j → None
graph_module.build_graph(
    domain_pack, repository,
    scope_retriever=scope_retriever, graph_searcher=graph_searcher,
    llm=graph_module._build_llm(),           # 有 DEEPSEEK_API_KEY 用 LLM，否则回退启发式
    scope_enabled=True, graph_enabled=True,
)
```

- `_build_scope_retriever`/`_build_graph_searcher`/`_build_llm` 复用 `agents/graph.py` 已有函数。
- `create_app` 新增可选参数 `index_path`（默认 `DEFAULT_INDEX_PATH`）、`enable_scope=True`、`enable_graph=True`，便于测试注入 fake 检索器与关闭。
- **短超时**：`Neo4jBackend.from_env()` 的 `verify_connectivity` 连不上会等超时，拖慢启动。`_build_graph_searcher` 已 try/except→None；在 `from_env` 侧或驱动配置加短连接超时（如 3s），Neo4j 没起时快速降级。

### 后端：响应模型放宽

```python
class SessionTurnResponse(BaseModel):
    session_id: str
    report_type: Literal["named", "scope", "graph", "unresolved"]
    report: dict     # 三种报告之一的 model_dump(mode="json")，前端按 report_type 解释
```

`session_turn` 从 `state` 按 `retrieval_mode` 取报告：`named`/`unresolved`→`state.report`；`scope`→`state.scope_report`；`graph`→`state.graph_report`。`report_type = state.retrieval_mode`。`report = <取到的报告>.model_dump(mode="json")`。

`/research` 端点**保持不变**（无状态入口，不在「网页」范围）。

### 前端：按 report_type 分派

```
named / unresolved → renderReport(report)      // 复用现有报告卡，零改动
scope              → renderScopeText(report)    // bubble-assistant 文本气泡：摘要 + 候选名单
graph              → renderGraphText(report)    // 文本气泡：摘要 + 候选 + 最终控制人
                   + renderGraphViz(report)     // 侧边 SVG 节点图（仅围标线索子图）
```

- **scope/graph 主体走文本气泡**（最小改动）：复用 app.js 现有 `bubble-assistant` 样式，把 `summary` + 候选（`legal_name · top_score · ultimate_controllers`）排成可读文本。
- **`renderScopeText`/`renderGraphText`/`renderGraphViz` 为纯函数**（report → DOM），可单独喂样例数据肉眼验。

### 前端：graph 侧边节点可视化（围标线索子图）

- **画什么**：`shared_controllers`（控制 ≥2 家候选的控制人）+ 其 `controlled_companies`。信息密度最高、节点最少。
- **数据源**：`GraphSearchReport` 现有字段，**不改后端契约**。
- **画法**：内联 SVG 手绘、无 CDN、无物理引擎。分层布局——共享控制人节点（★，`--bad` 红）在上，被控候选（○）在下，控制边连接；`concentrated_industries` 非空（同行业+同控制人）的边加粗并标「围标线索」。
- **无 `shared_controllers` 时**：侧边显示「未发现候选间共享控制人」一行字，**不强画散图**。
- **响应式**：宽屏放报告右侧，窄屏堆下方。

## 数据流（一轮，网页）

```
用户问题 → POST /session/turn {question,user_id,session_id?}
  → execute_turn 跑缓存图（planner 用 LLM/启发式判复杂度 → researcher 按 retrieval_mode 分派）
  → 返回 {session_id, report_type, report}
  → 前端按 report_type 分派渲染（named 卡片 / scope 文本 / graph 文本+侧边图）
```

## 降级链（照搬图层已有，API 不额外写）

| 缺什么 | 降级到 | 结果 |
|---|---|---|
| Neo4j 没起 | graph_searcher=None → 回退 scope | 复杂查询走 scope，不崩 |
| `.[rag]`/索引也没有 | scope_retriever=None → 命名核验 | 退回当前行为 |
| 全没有 | 等于没开 | 与当前网页一致 |

运行时异常走已有 `state.degradations` 链，writer 插到 `open_questions` 最前。开此功能不使网页更脆。

## LLM 复杂度分类

照搬 CLI：`_build_llm()` 有 `DEEPSEEK_API_KEY` + `.[llm]` 就用 DeepSeek 分类，否则 `classify_complexity` 回退关系关键词启发式（`query_complexity.py` 的 22 个关系词）。两者都能触发「复杂→GraphRAG」，LLM 更准。**只发查询文本、不发数据**（守唯一 LLM 环节红线）。

## 测试策略

- **后端** `tests/test_api_session_retrieval.py`（TestClient + 注入 fake `scope_retriever`/`graph_searcher`）：
  - 关系词查询（如「找股东有关联的供应商」）→ `report_type == "graph"`，`report` 含 `candidates`。
  - 能力查询（如「哪些企业能做注塑成型」）→ `report_type == "scope"`。
  - 命名核验（如示例企业名）→ `report_type == "named"`，`report["supplier_name"]` 正确。
  - 缺 graph_searcher（None）+ 复杂查询 → 降级 `scope`（有 scope）或 `named/unresolved`。
  - 响应形状：含 `report_type` 与 `report`(dict)。
- **现有 `tests/test_api_session.py` 更新**：响应从 `report` 变 `report_type`+`report`；`report["supplier_name"]` 仍可取，断言相应调整。
- **前端**：`renderScopeText/renderGraphText/renderGraphViz` 纯函数，浏览器手验（起 uvicorn + setup.ps1 已就绪的 Neo4j，走命名/能力/关系三类查询）+ 代码审查（无 JS 框架）。
- 全套 `pytest` 保持绿。

## 明确不做（后续）

- 流式/SSE（app.js 现有 `createStreamingMessage` 实验代码不依赖、不删；本设计基于一次性返回）。
- 完整股权穿透图（多跳中间节点，需后端新增 node-link 边接口）。
- `/research` 端点开 scope/graph。
- 真鉴权、会话 TTL。

## Self-Review

- **占位符**：无 TBD；注入代码、响应模型、三分派、可视化数据源、降级表、测试项均具体。
- **一致性**：`report_type`/`report` 跨后端与前端一致；报告字段与 `state.py`（`SupplierReport`/`ScopeSearchReport`/`GraphSearchReport`）、`graph.py`（`_build_scope_retriever`/`_build_graph_searcher`/`_build_llm`/`build_graph` 签名）、`query_complexity.py` 对齐。`create_app` 新增参数与现有 `memory=/session_store=` 注入并存。
- **核心数据原则**：三种报告均由 writer 生成、前端逐字渲染；graph 围标线索仍标「线索级·须人工复核」；LLM 只发查询文本。
- **范围**：单一实现计划可覆盖（后端注入+响应模型 / 前端三分派+SVG图 / 测试）。流式/穿透图/`/research`/鉴权切出。
- **歧义**：可视化限定「围标线索子图」；无共享控制人不强画；Neo4j 短超时降级；`report_type` 四值枚举明确。
