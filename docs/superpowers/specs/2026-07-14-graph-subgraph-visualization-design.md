# 网页图谱子图可视化设计（GraphRAG 检索节点/边侧栏展示）

- 日期：2026-07-14
- 状态：已与用户确认
- 前置：C2 检索/生成分层、N2 Neo4j 图后端、2026-07-12 网页聊天界面、2026-07-13 流式呈现层

## 目标

网页聊天界面在一轮对话走 **graph 模式**（GraphRAG 混合检索）时，在页面右侧的固定面板中把本次检索实际触及的节点和边画出来，让"语义检索命中了哪些种子企业、它们的股东/对外投资/最终控制人是谁、哪些控制人横跨多家企业（围标线索）"一眼可见。

非目标：

- 不改报告文本、不改 `/research` 与 `/session/turn` 非流式响应形状。
- 不做历史子图持久化（localStorage 不存子图，恢复历史会话时面板为空状态）。
- 不引入任何前端第三方库或构建工具，维持零依赖 vanilla 页面。
- 不新增图查询——只可视化 `hybrid_search` 已经取回的 `HybridContext`，不为画图多查 Neo4j。

## 已确认的产品决策

| 决策点 | 结论 |
| --- | --- |
| 展示范围 | 全量层：种子企业 + 最终控制人/共享控制人 + 每个种子的直接股东与对外投资（含持股比例） |
| 交互程度 | 基础交互：滚轮缩放、拖拽平移、悬停 tooltip、点击高亮相邻边 |
| 呈现方式 | 右侧固定面板，随本页面会话最新一次图检索更新，可收起；窄屏变抽屉 |
| 渲染方案 | 手写 SVG + 确定性分层布局，零依赖 |

## 一、数据模型（`graph_retrieval.py` 新增）

三个 Pydantic 模型 + 一个纯函数投影：

- **`SubgraphNode`**：`id`（企业信用代码或图节点 id）、`name`、`kind`（`seed` / `shareholder` / `investment` / `controller`）、`node_type`（`company` / `person` / 空）、`score: float`（仅种子非零）、`is_shared_controller: bool`、`concentrated_industries: list[str]`（非空即围标线索红色高亮）。
- **`SubgraphEdge`**：`source`、`target`（方向统一为资金/控制流向：股东→企业、企业→被投企业、控制人→种子）、`kind`（`shareholding` / `investment` / `control_clue`）、`holding_pct: str | None`、`via_person: bool`（仅 `control_clue` 有意义）。
- **`GraphSubgraph`**：`nodes: list[SubgraphNode]`、`edges: list[SubgraphEdge]`、`truncated: bool`。
- **`project_subgraph(context: HybridContext) -> GraphSubgraph`**：纯函数投影，规则：
  - `context.seeds` → `kind="seed"` 节点，带 `score`。
  - 每个种子的 `neighbors`：`direction="in"` → 邻居节点 `kind="shareholder"`、边 邻居→种子；`direction="out"` → 邻居节点 `kind="investment"`、边 种子→邻居；边 `kind` 取 `NeighborEdge.edge_type`，携带 `holding_pct`。
  - 每个种子的 `controllers` → 节点 `kind="controller"`、边 控制人→种子 `kind="control_clue"`（最终控制人是多跳推导结果，不冒充直接持股，前端画虚线）、`via_person` 透传。
  - 节点按 `id` 去重，`kind` 冲突时优先级 `seed > controller > shareholder > investment`（同一主体既是直接股东又是最终控制人时：一个节点、两条边）。
  - `context.shared_controllers` 里的节点置 `is_shared_controller=True` 并带 `concentrated_industries`。
  - 邻居上限：每种子每方向最多 15 条（`holding_pct` 字符串提取数值降序排序，解析失败或为空的排最后，同值按 `node_id` 保证确定性），超出丢弃并置 `truncated=True`。

## 二、状态与编排（`state.py` + `agents/nodes.py`）

- `ResearchState` 新增字段 `graph_subgraph: GraphSubgraph | None = None`。
- `_retrieve_graph` 检索成功时同时写 `state.graph_candidates`、`state.shared_controllers` 与 `state.graph_subgraph = project_subgraph(context)`；运行时失败或降级 scope 的路径上保持 `None`。
- writer 不读该字段，报告结构与文案零改动。

## 三、SSE 推送（`api.py`）

- 流式端点 `/session/turn/stream` 的 complete 分支，在 `report_start` 事件**之前**：若 `state.retrieval_mode == "graph"` 且 `state.graph_subgraph` 非空且 `nodes` 非空，则 `yield _sse("graph_subgraph", state.graph_subgraph.model_dump())`。图先亮出来，正文随后逐 token 流出。
- named / scope / unresolved 模式、以及 graph 失败降级后的轮次不发该事件。
- 非流式 `/session/turn` 与 `/research` 响应模型不变。

## 四、前端（`web/index.html` + 新文件 `web/graph.js` + `app.js` + `style.css`）

### index.html

`.app` 右侧新增 `<aside class="graph-panel">`，包含：

- 标题"股权图谱线索" + 固定副标"线索级证据 · 须人工复核"；
- 收起/展开按钮；
- 图例：○ 企业 / □ 自然人 / 实线 持股·投资（标比例）/ 虚线 控制线索 / 红色 同行业+同控制人；
- SVG 画布；
- 空状态文案（尚无图检索轮次时展示）；
- 截断脚注（`truncated=true` 时显示"部分直接股东/投资未展示"）。

### graph.js（新文件，约 250–300 行）

- 暴露 `window.GraphPanel = { render(payload), clear() }`，不引模块系统，`index.html` 以 `<script src="/static/graph.js" defer>` 引入（先于 app.js）。
- **确定性分层布局**四行：
  1. 共享控制人（`is_shared_controller`）；
  2. 其余控制人 + 直接股东（按所属种子聚簇）；
  3. 种子企业（按 `score` 降序从左到右定列）；
  4. 对外投资。
- 边为贝塞尔曲线，中点标持股比例；`control_clue` 虚线；共享控制人节点与其边红色高亮，`concentrated_industries` 非空时 tooltip 注明围标线索。
- 交互：滚轮缩放、拖拽平移（均操作 `viewBox`）；悬停 tooltip（名称/类型/比例，`via_person` 标"经自然人关联 · 低置信"）；点击节点高亮其相邻边，再点或点空白取消。
- 颜色全部走现有 CSS 变量，自动适配深浅主题。

### app.js

- `streamSessionTurn` 的 `onEvent` 增加 `graph_subgraph` 分支 → `GraphPanel.render(data)`。
- 新建会话、切换会话、切换身份时 `GraphPanel.clear()`。
- 不持久化子图（面板只反映本页面会话最新一次图检索）。

### style.css

- 外层布局三栏：侧边栏 | 聊天 | 图谱面板（面板宽约 380px，可收起为窄条）。
- 窄屏 `<1100px`：面板变覆盖式抽屉，顶栏出现切换按钮（仅当当前有图数据时显示）。

## 五、错误处理与数据红线

- 图检索运行时失败/降级 scope → 不发事件，面板维持原状（上一张图或空状态）。
- 投影结果节点为空 → 不发事件。
- 面板所有文案不出现"认定 / 无风险 / 实际控制"表述；副标常驻"线索级证据 · 须人工复核"；`via_person` 与围标高亮均带低置信提示，与 writer 的线索级口径一致。
- 前端渲染只陈述 payload 里的字段，不推断、不补全。

## 六、测试

沿用现有 pytest 模式（前端无 JS 测试框架，维持现状，改完用本地服务手动验证）：

- `tests/test_graph_retrieval.py` 增补 `project_subgraph`：节点去重与 kind 优先级、边方向与 kind、共享控制人标记与 `concentrated_industries` 透传、每方向 15 条截断与 `truncated` 标记、`via_person` 透传、空 seeds 返回空子图。
- `tests/test_nodes.py` 增补：fake searcher 返回固定 `HybridContext` 时 `state.graph_subgraph` 被填充；graph 运行时失败降级 scope 时为 `None`。
- `tests/test_api_stream_retrieval.py` 增补：graph 模式 SSE 事件流包含 `graph_subgraph` 且位于 `report_start` 之前；scope / named 模式不包含该事件。
