# 图谱面板问题聚焦子图设计（修订 2026-07-14 全量层决策）

- 日期：2026-07-15
- 状态：已与用户确认
- 前置：`2026-07-14-graph-subgraph-visualization-design.md`（首版全量层）；真实数据验证发现单次检索 185 节点，其中约 90% 与提问无关

## 决策变更

用户确认：**后端只发精简子图**（推翻首版"全量层"决策）。图谱面板只回答提问本身：哪些供应商命中了查询、它们之间有没有实际关联证据。单一控制人、直接股东、对外投资不再进入载荷。

## 一、后端投影规则（`project_subgraph` 重写）

输入不变（`HybridContext`），输出改为问题聚焦子图：

- **查询概念节点**：`id="query"`、`kind="query"`、`name=context.query or ""`。种子为空时整个子图为空（不发孤查询节点；API 层"nodes 非空才发事件"守卫不变）。
- **种子节点**：命中候选企业，`kind="seed"`、带 `score`，不变。
- **语义命中边**：`query → 种子`，边类型 `semantic_match`；得分不重复存边上，前端从种子节点 `score` 取。
- **共享控制人**：仅投影 `context.shared_controllers`（控制 ≥2 家种子），`kind="controller"`、`is_shared_controller=True`；`control_clue` 边连到其控制的每家种子（`controlled_seeds` 里存在于种子集合的），`via_person`/`concentrated_industries` 透传。
- **移除**：shareholder/investment 节点与边、非共享控制人、`MAX_NEIGHBORS_PER_DIRECTION`、`truncated` 字段。

模型收窄：`SubgraphNode.kind ∈ {query, seed, controller}`、`SubgraphEdge.kind ∈ {semantic_match, control_clue}`、`GraphSubgraph = {nodes, edges}`。共享控制人的 `via_person` 取 `SharedController.via_person`（整体标记），node_type 按 id 前缀 `person:` 判定。

## 二、前端布局与图例（graph.js 简化）

- 三层布局：查询节点顶层居中（加宽 220px，文本超长截断、悬停全文）→ 种子层（按得分降序，超 10 列换行）→ 共享控制人层。
- `semantic_match` 实线，边中点标种子得分（两位小数）；`control_clue` 虚线。
- 图例：查询 / 企业 / 自然人 / 语义命中（实线）/ 控制线索（虚线）/ 同行业+同控制人（红）。
- 不做全量开关（后端已无全量数据）。
- 窄屏抽屉自动弹出、缩放/平移/悬停/点击高亮、`[hidden]` 修复等既有行为保留。

## 三、红色语义修正

精简视图里共享控制人是常态：默认暖黄（warn）样式；**仅 `concentrated_industries` 非空（同行业+同控制人围标线索）才红色**（节点与其边），与 writer 报告"围标叙述才升级"口径对齐。tooltip 口径不变（须人工复核/低置信）。

## 四、错误处理与数据红线

- 面板文案与 tooltip 口径不变：线索级证据、须人工复核、不出现"认定/无风险/实际控制"。
- 检索失败/降级路径不发事件（不变）。
- 报告文字、`/research`、`_build_graph_findings`（报告候选/关联叙述仍基于全量 context）不动。

## 五、测试

- 重写 `tests/test_graph_retrieval.py` 的 project_subgraph 用例：查询节点生成与命名、语义边方向、仅共享控制人入图（非共享控制人/股东/投资不入）、无共享控制人时只有查询+种子、空种子返回空子图、via_person 与围标字段透传。
- 更新 `tests/test_nodes.py`、`tests/test_api_stream_retrieval.py` 对子图形状的断言（stream fixture 改为两种子共享一控制人）。
- `tests/test_api_web.py` 字符串断言随图例/样式更新。
- 验证：pytest 全量 + Playwright 宽/窄视口截图复验。
