# 模块 N2：Neo4j 股权图后端设计

日期：2026-07-10

N1 抽出了 `OwnershipGraphBackend` 协议、内存实现。**N2 加 Cypher 实现的 `Neo4jBackend`，替换内存图成为生产图引擎**（用户决定：完全替换，内存实现退居测试替身）。完成后 Neo4j 成为图查询引擎，SQLite 仍是事实源。

## 红线与硬约束

- **Neo4j 必须本地自建（Docker），绝不用云托管**（受限企业数据本地化红线）。
- SQLite 是股权边事实源；Neo4j 图是可重建查询产物（同 FAISS 索引定位）。
- 报告/researcher/writer/CLI/API 形状不变；关联方/共享控制人仍线索级（"须人工复核"）。
- Neo4j 不可用 → 靠 C4 降级链退 scope（建 searcher 失败 → 决策期回退；查询期异常 → 运行时降级 + 记 `degradations`）。

## Neo4j 数据模型

- 节点：`(:Entity {node_id, display_name, node_type, is_person})`；`node_id` 唯一约束。属性来自 `GraphNode`（`node_type` ∈ company/person/fund）。
- 边：`(source)-[:SHAREHOLDING {holding_pct}]->(target)`、`(source)-[:INVESTMENT {holding_pct}]->(target)`，方向 = `GraphEdge.source_node_id → target_node_id`。
- "谁控制 X" = 沿 X 的**入边**上溯（target=X 回到 source）。

## `Neo4jBackend`（实现 `OwnershipGraphBackend` 四方法）

新文件 `src/deepresearch_agent/neo4j_backend.py`。`Neo4jBackend(driver)`；`Neo4jBackend.from_env()` 读 `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` 建 driver 并 `verify_connectivity()`（连不上抛异常）。

**`has_node`**
```cypher
MATCH (n:Entity {node_id: $id}) RETURN count(n) > 0 AS exists
```

**`display_name`**（无行返回时 Python 侧回退 `node_id`，与内存实现一致）
```cypher
MATCH (n:Entity {node_id: $id}) RETURN n.display_name AS name
```

**`direct_neighbors`**（Python 侧把 `rel_type` 小写映射 `edge_type`，按 `(direction, node_id)` 排序，构造 `NeighborEdge`）
```cypher
MATCH (x:Entity {node_id: $id})-[r:SHAREHOLDING|INVESTMENT]-(nb:Entity)
RETURN nb.node_id AS node_id, nb.display_name AS name, nb.node_type AS node_type,
       type(r) AS rel_type, r.holding_pct AS holding_pct,
       CASE WHEN startNode(r).node_id = $id THEN 'out' ELSE 'in' END AS direction
```

**`ultimate_controllers`**（核心；纯 Cypher 变长路径 + 路径谓词，不依赖 APOC）。`max_depth` 为我方 int，格式化为字面量（Cypher 变长上界不接受参数）：
```cypher
MATCH path = (start:Entity {node_id: $id})<-[:SHAREHOLDING|INVESTMENT*1..{max_depth}]-(ctrl:Entity)
WHERE none(n IN nodes(path)[1..] WHERE n.node_type = 'fund')
  AND ( ctrl.is_person
        OR NOT EXISTS {
             MATCH (ctrl)<-[:SHAREHOLDING|INVESTMENT]-(p:Entity) WHERE p.node_type <> 'fund'
        } )
WITH ctrl,
     min(length(path)) AS depth,
     max(CASE WHEN any(n IN nodes(path)[1..] WHERE n.is_person) THEN 1 ELSE 0 END) AS via
RETURN ctrl.node_id AS node_id, ctrl.display_name AS display_name, depth, via = 1 AS via_person
ORDER BY depth, node_id
```

复刻内存版语义：
- 路径谓词 `none(... fund)` = "基金不外扩、不计入"（fund 不在路径任何位置，起点除外）。
- 终点判定 `is_person OR 无非 fund 父节点` = 内存版 `(not has_parent) or is_person`。
- `depth = min(length)`；排序 `(depth, node_id)`。

**via_person 语义差异（诚实说明，写进代码注释）**：内存版 `via_person` 取"BFS 首达路径"的值（与遍历顺序相关）；Cypher 版取"任一有效路径是否经自然人"（定义更确定）。二者在 `ownership_links` fixture 上**逐条相等**（该 fixture 无"同一节点既经自然人又不经自然人到达"的歧义），对拍通过。

## 灌图脚本

`scripts/build_ownership_neo4j.py`：`build_ownership_neo4j(repository, driver)` —— 幂等：
1. `MATCH (n:Entity) DETACH DELETE n`（清空）。
2. `CREATE CONSTRAINT ... IF NOT EXISTS FOR (n:Entity) REQUIRE n.node_id IS UNIQUE`。
3. `UNWIND $rows` 批量 `MERGE (n:Entity {node_id})` + `SET` 属性（读 `repository.iter_graph_nodes()`）。
4. `UNWIND $rows` 批量按 `edge_type` `MATCH` 两端 + `MERGE` `:SHAREHOLDING`/`:INVESTMENT` + `SET holding_pct`（读 `repository.iter_graph_edges()`）。

和 `build_scope_index.py` 一个定位——从 SQLite 重建的派生产物。

## 依赖 / 配置 / 部署

- `pyproject.toml`：新增可选依赖 `neo4j = ["neo4j>=5.0"]`；`[tool.pytest.ini_options]` 注册 `neo4j` marker。
- `.env.example`：加 `NEO4J_URI=bolt://localhost:7687`、`NEO4J_USER=neo4j`、`NEO4J_PASSWORD=`。
- 仓库根加 `docker-compose.yml`：`neo4j:5` 镜像，端口 `7687`(bolt)/`7474`(browser)，`NEO4J_AUTH` 从环境注入，数据卷本地持久化。**仅本地**。
- **可视化开箱即用（零额外代码）**：灌图后 Neo4j Browser（`localhost:7474`）一句 `MATCH (n:Entity)-[r]->(m) RETURN n,r,m` 即渲染可交互股权网（按 `node_type` 着色、按边类型区分）。这是选 Neo4j 的核心收益之一，N2 无需为可视化写任何代码。

## 生产接线（Neo4j 单引擎）

`agents/graph.py` 的 `_build_graph_searcher(database_path, scope_retriever)`：

```python
if scope_retriever is None:
    return None
try:
    from deepresearch_agent.graph_retrieval import hybrid_search
    from deepresearch_agent.neo4j_backend import Neo4jBackend

    backend = Neo4jBackend.from_env()  # 连不上抛异常
    return lambda query: hybrid_search(query, scope_retriever, backend)
except Exception:
    return None
```

- Neo4j 没配/连不上 → 返回 `None` → 决策期回退 scope（已有）。
- 内存实现（`InMemoryOwnershipBackend` / `load_ownership_graph`）**不再进生产**，仅测试用。
- driver 生命周期随 searcher（CLI 每次调用；API `enable_graph=False` 不涉及）。

## 测试

**对拍（`tests/test_neo4j_backend.py`，标 `@pytest.mark.neo4j`）**：
- 模块顶 `pytest.importorskip("neo4j")`（驱动没装则跳过）。
- helper 建 driver + `verify_connectivity()`，**连不上 `pytest.skip("Neo4j 不可达")`**。
- 把 `ownership_links` fixture 灌进 Neo4j（`build_ownership_neo4j`），对 `A_CODE`/`B_CODE`/`C_CODE` 逐一断言 `Neo4jBackend` 与 `InMemoryOwnershipBackend` 四方法结果**逐条相等**（`has_node`/`display_name`/`ultimate_controllers`/`direct_neighbors`）。
- 再断言 `assemble_subgraph_context` 在两后端上产出的 `HybridContext` 相等（端到端对拍）。

**CI/无 Neo4j**：`neo4j` marker + skip-if-unreachable → 自动跳过，现有全绿不受影响。

**本会话真验证**：因本机有 Docker，执行时 `docker compose up -d neo4j` + 装 `.[neo4j]` 驱动，把上述对拍**真跑绿**（非仅跳过）。

## 改动面

- 新文件：`src/deepresearch_agent/neo4j_backend.py`、`scripts/build_ownership_neo4j.py`、`docker-compose.yml`、`tests/test_neo4j_backend.py`。
- 改：`pyproject.toml`（`.[neo4j]` extra + `neo4j` marker）、`.env.example`、`src/deepresearch_agent/agents/graph.py`（`_build_graph_searcher` 建 `Neo4jBackend`）。
- 不改：`ownership_backend.py`（内存实现保留为测试替身）、`graph_traversal.py`、`graph_retrieval.py`、`state.py`、`nodes.py`、`cli.py`、`api.py`、SQLite schema。
- 复用：`OwnershipGraphBackend` 协议、`ControllerResult`/`NeighborEdge`、`hybrid_search`/`assemble_subgraph_context`、C4 降级链。
