# 网页端接入 scope/GraphRAG 自动路由设计（流式对齐版）

> 状态：设计已确认（三节经用户逐节 approve；写计划前发现网页已流式化，方案对齐到 SSE 流式架构，用户确认「对齐到流式」）。下一步 writing-plans。

## 目标

让网页端复用 CLI（`run_research`）的检索逻辑：启用 scope + graph，由 **LLM 复杂度分类（无 LLM 则关系关键词启发式）自动决定是否调用 GraphRAG**。网页当前已是**流式（SSE）纯文本**架构，故 graph/scope 结果对齐到流式：报告转文本流逐字显示，graph 命中围标线索时额外发 `graph_viz` 事件在一侧画「候选⇔控制人」节点图。

## 现状（写计划前核对，与初版 spec 的差异）

网页已从「一次性 JSON + 结构化报告卡」演进为**流式纯文本**：

- 后端 `/session/turn/stream`（api.py:120）：SSE 端点，`iter_execute_turn`（graph.py:157，yield `(node_name, state)`，末尾 `("complete", final_state)`）逐节点推 `progress`，complete 时发 `report_start` + `message_delta`（`_report_message_chunks` 逐字）+ `complete`。
- 前端 app.js `streamSessionTurn`（app.js:244）：消费 SSE，把报告当纯文本流显示在 `bubble-assistant` 气泡（不再渲染结构化卡片）。
- `graph_for`（api.py:80）仍 `build_graph(domain_pack, repository)`——无检索器，故流式路径也恒命名核验。
- **崩溃隐患**：`session_turn_stream` complete 分支 `if state.report is None: raise`（api.py:153）。一旦注入 graph、复杂查询走 scope/graph，`state.report` 为 None（值在 `scope_report`/`graph_report`），会 500。`_report_message_chunks` 也只认 `SupplierReport` 字段。同理 JSON `/session/turn`（api.py:116）。

故本设计的接入点是 **SSE 事件流 + `_report_message_chunks`**，非初版的「JSON 响应模型」。

## 架构

### 后端 1：`create_app` 注入检索器（照搬 run_research）

`graph_for` 建图时注入（沿用 `compiled_graphs` 缓存，启动建一次）：

```python
scope_retriever = graph_module._build_scope_retriever(database_path, index_path)   # 缺 .[rag]/索引 → None
graph_searcher  = graph_module._build_graph_searcher(database_path, scope_retriever) # 连不上 Neo4j → None
graph_module.build_graph(
    domain_pack, repository,
    scope_retriever=scope_retriever, graph_searcher=graph_searcher,
    llm=graph_module._build_llm(),          # 有 DEEPSEEK_API_KEY 用 LLM，否则回退关系关键词启发式
    scope_enabled=True, graph_enabled=True,
)
```

- `create_app` 新增可选参数 `index_path`（默认 `graph_module.DEFAULT_INDEX_PATH`）、`enable_scope=True`、`enable_graph=True`，便于测试注入 fake 检索器或关闭。
- **短超时**：`Neo4jBackend.from_env` 的 `verify_connectivity` 连不上会等超时，拖慢启动。`_build_graph_searcher` 已 try/except→None；在驱动/`from_env` 侧加短连接超时（如 3s），Neo4j 没起时快速降级。

### 后端 2：两个端点按 `retrieval_mode` 取报告（修 None 崩溃）

抽一个纯函数 `_report_of(state) -> tuple[str, dict]`：按 `state.retrieval_mode` 返回 `(report_type, report_dict)`——`named`/`unresolved`→`state.report`；`scope`→`state.scope_report`；`graph`→`state.graph_report`；`model_dump(mode="json")`。

- 流式端点 complete 分支：改用 `_report_of`，不再 `raise if state.report is None`。`report_start` payload 宽松：`{"report_type": ..., "title": <supplier_name 或 query>, "recommendation": ...}`。
- JSON `/session/turn`：响应模型放宽为 `SessionTurnResponse{session_id, report_type: str, report: dict}`（保证注入 graph 后不崩；网页不靠它，测试与其他消费者用）。`report["supplier_name"]` 在 named 下仍可取。

### 后端 3：`_report_message_chunks` 支持三种报告 → 文本流

按 `report_type` 生成文本段（`_text_chunks` 逐字复用）：

- `named`/`unresolved`：现有逻辑（supplier_name + 结论 + summary）。
- `scope`：`query` + 结论 + summary + 候选列表（`legal_name · top_score`，逐条）。
- `graph`：`query` + 结论 + summary + 候选（`legal_name · 最终控制人`）+ 围标线索（`shared_controllers` 逐条 `controller_name → controlled_companies`，标「线索级·须人工复核」）。

### 后端 4：graph 围标线索 → `graph_viz` SSE 事件

`graph` 模式且 `shared_controllers` 非空时，complete 前发一个事件：

```
event: graph_viz
data: {
  "controllers": [{"name": "...", "collusion": true}],   # collusion = concentrated_industries 非空
  "edges": [{"controller": "...", "company": "..."}]      # 控制人 → 被控候选（controlled_companies）
}
```

数据由 `GraphSearchReport.shared_controllers` 现有字段构造，**不改后端报告契约**。`shared_controllers` 为空则不发 `graph_viz`。

### 前端：流式文本通用 + 新增 `graph_viz` 事件画侧边 SVG

- **scope/graph 主体零改动**：报告已由后端转文本流，前端 `message_delta` 逐字显示照常（流式纯文本对三种报告天然通用）。
- **唯一前端新增**：`submit` 的 SSE 事件循环加 `else if (event === "graph_viz") renderGraphViz(data, streamed.node)`。
- **`renderGraphViz(data, anchor)`（纯函数）**：内联 SVG 手绘、无 CDN、无物理引擎。分层布局——共享控制人节点（★，`--bad` 红）在上，被控候选（○）在下，控制边连接；`collusion:true` 的边加粗标「围标线索」。挂在报告气泡一侧（宽屏右、窄屏下）。
- 加载态、错误兜底、多轮 session、命名核验体验：全部不变。

## 数据流（一轮，网页流式）

```
用户问题 → POST /session/turn/stream (SSE)
  → session / progress×N（planner 用 LLM/启发式判复杂度 → researcher 按 retrieval_mode 分派）
  → report_start{report_type,title,recommendation}
  → message_delta×N（三种报告均转文本流）
  → [graph 且有围标线索] graph_viz{controllers,edges} → 前端画侧边 SVG
  → complete
```

## 降级链（照搬图层已有，端点不额外写）

| 缺什么 | 降级到 | 结果 |
|---|---|---|
| Neo4j 没起 | graph_searcher=None → 回退 scope | 复杂查询走 scope，流式不崩 |
| `.[rag]`/索引也没有 | scope_retriever=None → 命名核验 | 退回当前行为 |
| 全没有 | 等于没开 | 与当前网页一致 |

运行时异常走已有 `state.degradations` 链，writer 插到报告 `open_questions` 最前（经文本流体现）。

## LLM 复杂度分类

照搬 CLI：`_build_llm()` 有 `DEEPSEEK_API_KEY` + `.[llm]` 用 DeepSeek，否则 `classify_complexity` 回退关系关键词启发式（`query_complexity.py` 22 词）。二者都能触发「复杂→GraphRAG」。**只发查询文本、不发数据**（守唯一 LLM 环节红线）。

## 测试策略

- **后端** `tests/test_api_stream_retrieval.py`（TestClient `.stream()` + 注入 fake `scope_retriever`/`graph_searcher`）：
  - 关系词查询（如「找股东有关联的供应商」）→ body 含 `event: graph_viz`（fake 造出 `shared_controllers`）与候选文本。
  - 能力查询（如「哪些企业能做注塑成型」）→ 走 scope，body 含候选文本、无 `graph_viz`。
  - 命名核验 → 现有 `report_start`/`message_delta`，行为不变。
  - 缺 graph_searcher（None）+ 复杂查询 → 降级 scope，流式不崩、无 `graph_viz`。
- **`tests/test_api_session.py` 更新**：JSON 端点响应加 `report_type`；`report["supplier_name"]` 仍可取，断言相应调整。
- **现有 `tests/test_api_stream.py`**：命名核验路径断言应保持通过（回归）。
- **前端** `renderGraphViz` 纯函数：浏览器手验（起 uvicorn + setup.ps1 就绪的 Neo4j，走命名/能力/关系三类查询）+ 代码审查（无 JS 框架）。
- 全套 `pytest` 保持绿。

## 明确不做（后续）

- 完整股权穿透图（多跳中间节点，需后端新增 node-link 边接口）。
- `/research` 端点开 scope/graph。
- 真鉴权、会话 TTL。
- 把 scope/graph 也做成结构化卡片（本设计走流式纯文本，与现网页方向一致）。

## Self-Review

- **占位符**：无 TBD；注入代码、`_report_of`、`graph_viz` 契约、文本流分支、降级表、测试项均具体。
- **一致性**：`report_type`/`graph_viz` 契约跨后端与前端一致；字段与 `state.py`（`SupplierReport`/`ScopeSearchReport`/`GraphSearchReport`：candidates/shared_controllers/ultimate_controllers/concentrated_industries）、`graph.py`（`iter_execute_turn`/`_build_scope_retriever`/`_build_graph_searcher`/`_build_llm`/`_report_of` 拟新增）、`query_complexity.py` 对齐。`create_app` 新增参数与现有 `memory=/session_store=` 并存。
- **核心数据原则**：三种报告均 writer 生成、经文本流逐字呈现；围标线索标「线索级·须人工复核」；LLM 只发查询文本。
- **范围**：单一计划可覆盖（注入+修崩溃 / `_report_message_chunks` 三报告 / `graph_viz` 事件 / 前端 SVG / 测试）。穿透图/`/research`/鉴权/结构化卡片切出。
- **歧义**：可视化限「围标线索子图」；无共享控制人不发 `graph_viz`；Neo4j 短超时降级；`report_type` 四值枚举明确。
