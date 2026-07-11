# 模块 N4：graph 报告"同行业+同控制人"围标线索设计

日期：2026-07-11

N3 把行业层灌进了 Neo4j（`(:Entity)-[:IN_INDUSTRY]->(:Industry)`）。**N4 把行业层变成 Agent 的尽调信号**：在 graph 模式的共享控制人之上，检测"同一控制人控制的候选里 ≥2 家落在**同一行业**"，作为**围标/集中度线索**写进 `GraphSearchReport`。仍线索级、须人工复核、**绝不认定围标**。

## 为什么（业务）

采购收到甲乙丙三份"竞争"报价，若三家**同行业**且**背后同一控制人** → 不是三家竞争，是一只手演三家（虚假竞争 / 围标 / 集中度风险）。单看"同控制人"或"同行业"都是噪声，**两者叠加**才是尖锐信号。股权层给"同控制人"、N3 行业层给"同行业"，N4 把两维一叠。

## 红线

- **线索级**：`via_person` 低置信、标"须人工复核"；**绝不认定围标**（同名自然人可能非同一人；同控制人 ≠ 实际串通）。
- 报告对已解析企业固定 `insufficient_evidence`（graph 模式本就不下采购结论）。
- 无 LLM；不结构化 `business_scope`（行业来自 N3 的登记 `IN_INDUSTRY` 边）。

## 架构：绕过"行业只在 Neo4j"

行业数据只在 Neo4j（N3），内存后端（CI 测试替身）没有行业。给后端协议加一个方法：

```python
def company_industry(self, node_id: str) -> str | None: ...
```

- **`Neo4jBackend`**：`MATCH (c:Entity {node_id:$id})-[:IN_INDUSTRY]->(i:Industry) RETURN i.name`；无边返回 `None`。
- **`InMemoryOwnershipBackend`**：直接返回 `None`（无行业数据）→ 集中度检测自然为空，**不误报、优雅降级**。

这样协议统一、内存后端不破；检测逻辑本身可用**假后端**（返回行业）在 CI 单测，Neo4j 端到端另测。N2 对拍不受影响（不灌行业 → `company_industry` 全 None → 两后端仍一致）。

## 数据流

```
assemble_subgraph_context(backend, seeds):
  现有：算出 shared_controllers（每个含 controlled_seeds）
  N4：对每个共享控制人，把它控制的 seeds 按 backend.company_industry(code) 分组，
      收集"≥2 家落在同一行业"的行业名 → concentrated_industries: list[str]
SharedController.concentrated_industries（graph_retrieval 模型加字段，默认 []）
  → _build_graph_findings → SharedControllerFinding.concentrated_industries（state 模型加字段，默认 []）
  → writer：非空 → note 升级为"同行业（<名>）+同控制人，疑似围标/集中度线索，须人工复核"；
    summary 追加"其中 N 组同行业+同控制人（围标线索）"；open_questions 保持免责。
```

### 检测细节（`assemble_subgraph_context`）

对每个 `nid → codes`（`len(codes) >= 2` 的共享控制人）：
- `industry_by_code = {c: backend.company_industry(c) for c in codes}`（None 跳过）。
- 按行业名分桶，`concentrated = sorted(名 for 名, 桶 in 分桶 if len(桶) >= 2)`。
- 写入 `SharedController.concentrated_industries`。内存后端全 None → `concentrated == []`。

## 模型变更

- `graph_retrieval.SharedController`：加 `concentrated_industries: list[str] = []`。
- `state.SharedControllerFinding`：加 `concentrated_industries: list[str] = []`。
- 两者默认空列表，向后兼容；`HybridContext`/`GraphSearchReport` 结构不变（字段挂在子模型上）。

## writer 变更（`_build_graph_findings` + `_write_graph_report`）

`_build_graph_findings`：把 `item.concentrated_industries` 透传给 `SharedControllerFinding`；若非空，`note` 用：

```
f"同行业（{'、'.join(concentrated)}）+同控制人，疑似围标/集中度线索，须人工复核"
```

否则保持现有 note（`经同名自然人推断…` / `经企业股权链推断`）。

`_write_graph_report` 的 summary：在现有"其中 N 组疑似共享控制人"后，若有任一 finding `concentrated_industries` 非空，追加"（其中 M 组同行业+同控制人）"。`_GRAPH_OPEN_QUESTIONS` 已含围标免责句，不改。

## 测试

**单元（CI，无 Neo4j，`tests/test_graph_retrieval.py` / `test_nodes.py`）**：
- 假后端实现 `company_industry`：让 A、C 返回同一行业、B 不同 → `assemble_subgraph_context` 后，控制 {A,C} 的共享控制人 `concentrated_industries == [该行业]`；控制 {A,B,C} 但仅 A、C 同行业的 → 也含该行业。
- 内存后端（真实 `ownership_links` 图，无行业）→ 所有 `concentrated_industries == []`（不误报）。
- `_build_graph_findings`：`concentrated_industries` 非空 → `SharedControllerFinding.note` 含"同行业"和"围标"；为空 → 保持旧 note。
- writer：state 里放一条带 `concentrated_industries` 的 finding → `graph_report` summary 含"同行业+同控制人"。

**Neo4j（`@pytest.mark.neo4j`，`tests/test_industry_layer_neo4j.py` 或新文件）**：
- 用 `ownership_links`（甲乙丙同四级行业 + 共享控制人"共同控股集团"）灌股权 + 行业 → `Neo4jBackend.company_industry(甲)` == 小类名；`assemble_subgraph_context(Neo4jBackend, [甲,乙,丙])` 的共享控制人 `concentrated_industries` 含该小类。

**N2 对拍不受影响**：不灌行业 → `company_industry` 全 None → `Neo4jBackend` 与 `InMemoryOwnershipBackend` 的 `assemble_subgraph_context` 仍逐条相等（`concentrated_industries` 两边都 []）。

## 改动面

- 改：`ownership_backend.py`（协议 + `InMemoryOwnershipBackend.company_industry` 返 None）、`neo4j_backend.py`（`company_industry` Cypher）、`graph_retrieval.py`（`SharedController` 加字段 + `assemble_subgraph_context` 算集中度）、`state.py`（`SharedControllerFinding` 加字段）、`agents/nodes.py`（`_build_graph_findings` 透传 + note 升级、`_write_graph_report` summary）、`tests/test_graph_retrieval.py`/`test_nodes.py`/`test_neo4j_backend.py`（或新 neo4j 测试）。
- 不改：`graph_traversal.py`、`ownership_graph.py`、`cli.py`、`api.py`、SQLite schema、灌图脚本（N3 已灌行业）、依赖。
- 复用：N3 的 `IN_INDUSTRY` 边、N2 driver/对拍模式、C4 降级链、`@pytest.mark.neo4j`。
