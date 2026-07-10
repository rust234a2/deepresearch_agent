# N2 Neo4j 股权图后端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Cypher 实现 `Neo4jBackend`（`OwnershipGraphBackend` 四方法），替换内存图成为生产图引擎，并用真 Neo4j 对拍验证与内存实现逐条相等。

**Architecture:** SQLite 仍是事实源；灌图脚本把 `graph_nodes`/边 MERGE 进 Neo4j（可重建产物）；`Neo4jBackend` 把 `ultimate_controllers`/邻居下推为 Cypher；`_build_graph_searcher` 改建 `Neo4jBackend.from_env()`，连不上 → C4 降级。内存实现退居测试替身。

**Tech Stack:** Python、Neo4j 5（本地 Docker）、`neo4j` 驱动、pytest。复用 `OwnershipGraphBackend`/`ControllerResult`/`NeighborEdge`、`hybrid_search`、C4 降级链。

## Global Constraints

- **Neo4j 仅本地自建（Docker），绝不用云**（数据本地化红线）。
- SQLite 是事实源；Neo4j 图是可重建产物。报告/researcher/writer/CLI/API 形状不变；关联/共享控制人线索级（"须人工复核"）。
- `via_person` 语义：内存版取"BFS 首达路径"，Cypher 版取"任一有效路径"——在 `ownership_links` fixture 上逐条相等；差异写进代码注释。
- 依赖版本：`neo4j>=5.0`（可选 extra `.[neo4j]`）。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`。`neo4j` 标记测试默认排除，跑对拍加 `-m neo4j`。
- 每个任务结束提交一次；中文提交信息。

## 文件结构

- 改 `pyproject.toml` — `.[neo4j]` extra + `neo4j` marker + `addopts` 排除（Task 1）。
- 新 `.env.example` 追加 `NEO4J_*`（Task 1）；新 `docker-compose.yml`（Task 1）。
- 新 `scripts/build_ownership_neo4j.py` — SQLite→Neo4j 灌图（Task 2）。
- 新 `src/deepresearch_agent/neo4j_backend.py` — `Neo4jBackend`（Task 3）。
- 新 `tests/test_neo4j_backend.py` — 灌图 + 对拍（Task 2、3）。
- 改 `src/deepresearch_agent/agents/graph.py` — `_build_graph_searcher` 建 `Neo4jBackend`（Task 4）。

---

### Task 1：依赖 · 配置 · docker-compose · 测试标记

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`（追加）、`docker-compose.yml`

**Interfaces:**
- Produces: 可选依赖 `.[neo4j]`；pytest `neo4j` marker（默认排除）；本地 Neo4j 服务定义；`NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` 约定。

- [ ] **Step 1: 加 `.[neo4j]` extra**

`pyproject.toml` 的 `[project.optional-dependencies]` 里 `llm = [...]` 之后加：

```toml
neo4j = [
  "neo4j>=5.0",
]
```

- [ ] **Step 2: 注册 `neo4j` marker 并默认排除**

`pyproject.toml` 的 `[tool.pytest.ini_options]`：把

```toml
addopts = "-q -m 'not slow'"
markers = [
  "slow: 需要重型 ML 依赖或模型下载，默认排除",
]
```

改为

```toml
addopts = "-q -m 'not slow and not neo4j'"
markers = [
  "slow: 需要重型 ML 依赖或模型下载，默认排除",
  "neo4j: 需要本地 Neo4j（docker compose up）的对拍测试，默认排除",
]
```

- [ ] **Step 3: `.env.example` 追加 Neo4j 连接**

在 `.env.example` 末尾追加：

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=devpassword
```

- [ ] **Step 4: 新建 `docker-compose.yml`**

仓库根创建 `docker-compose.yml`：

```yaml
services:
  neo4j:
    image: neo4j:5
    container_name: deepresearch-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: "${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-devpassword}"
    volumes:
      - neo4j-data:/data

volumes:
  neo4j-data:
```

- [ ] **Step 5: 验证配置**

Run: `docker compose config`
Expected: 打印规范化后的 compose 配置，无错误。

Run: `.\.conda-env\python.exe -m pytest --markers -p no:cacheprovider --basetemp=.conda-cache/pytest-n2 2>&1 | Select-String neo4j`
Expected: 列出 `@pytest.mark.neo4j: ...`（marker 已注册）。

- [ ] **Step 6: 全量回归（marker 排除改动不破坏现有）**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: 全绿（`neo4j` 测试尚不存在；`addopts` 排除项不影响现有用例）。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml .env.example docker-compose.yml
git commit -m "功能：N2-1 加 .[neo4j] extra、neo4j 测试标记与本地 docker-compose"
```

---

### Task 2：SQLite→Neo4j 灌图脚本

**Files:**
- Create: `scripts/build_ownership_neo4j.py`
- Test: `tests/test_neo4j_backend.py`

**Interfaces:**
- Consumes: `CompanyRepository.iter_graph_nodes() -> list[GraphNode]`（`node_id`/`display_name`/`node_type`/`is_person`）、`iter_graph_edges() -> list[GraphEdge]`（`source_node_id`/`target_node_id`/`edge_type`/`holding_pct`）。
- Produces: `build_ownership_neo4j(repository, driver) -> None` —— 幂等清空 + 建唯一约束 + 批量 MERGE 节点/边。

- [ ] **Step 0: 起 Neo4j + 装驱动（本会话前置，仅执行一次）**

```powershell
.\.conda-env\python.exe -m pip install "neo4j>=5.0"
$env:NEO4J_URI = "bolt://localhost:7687"; $env:NEO4J_USER = "neo4j"; $env:NEO4J_PASSWORD = "devpassword"
docker compose up -d neo4j
```
等 ~15s 让 Neo4j 就绪（`verify_connectivity` 会兜底；不就绪则对拍测试 skip）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_neo4j_backend.py`：

```python
import os
from pathlib import Path

import pytest

pytest.importorskip("neo4j")

from deepresearch_agent.company_repository import CompanyRepository

LINKS = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _repository(tmp_path: Path) -> CompanyRepository:
    from deepresearch_agent.company_database import build_company_database

    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        LINKS / "companies.csv",
        LINKS / "contacts.csv",
        database_path,
        shareholders_csv=LINKS / "shareholders.csv",
        investments_csv=LINKS / "investments.csv",
    )
    return CompanyRepository(database_path)


def _driver_or_skip():
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "devpassword")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        pytest.skip("Neo4j 不可达（先 docker compose up -d neo4j）")
    return driver


@pytest.mark.neo4j
def test_loader_populates_neo4j_matching_sqlite(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_ownership_neo4j import build_ownership_neo4j

    repository = _repository(tmp_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)
        with driver.session() as s:
            n = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            e = s.run(
                "MATCH ()-[r:SHAREHOLDING|INVESTMENT]->() RETURN count(r) AS c"
            ).single()["c"]
        assert n == len(repository.iter_graph_nodes())
        assert e == len(repository.iter_graph_edges())
    finally:
        driver.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: FAIL（`ModuleNotFoundError: build_ownership_neo4j`）。若显示 SKIP，说明 Neo4j 未就绪 —— 回 Step 0 起库。

- [ ] **Step 3: 实现灌图脚本**

创建 `scripts/build_ownership_neo4j.py`：

```python
from __future__ import annotations


def build_ownership_neo4j(repository, driver) -> None:
    """从 SQLite 读 graph_nodes/边，幂等灌进 Neo4j。SQLite 是事实源，此为可重建产物。"""
    nodes = repository.iter_graph_nodes()
    edges = repository.iter_graph_edges()
    node_rows = [
        {
            "node_id": n.node_id,
            "display_name": n.display_name,
            "node_type": n.node_type,
            "is_person": n.is_person,
        }
        for n in nodes
    ]
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT entity_node_id IF NOT EXISTS "
            "FOR (n:Entity) REQUIRE n.node_id IS UNIQUE"
        )
        session.run("MATCH (n:Entity) DETACH DELETE n")
        session.run(
            "UNWIND $rows AS row MERGE (n:Entity {node_id: row.node_id}) "
            "SET n.display_name = row.display_name, n.node_type = row.node_type, "
            "n.is_person = row.is_person",
            rows=node_rows,
        )
        for rel, kind in (("SHAREHOLDING", "shareholding"), ("INVESTMENT", "investment")):
            rows = [
                {"src": e.source_node_id, "tgt": e.target_node_id, "pct": e.holding_pct}
                for e in edges
                if e.edge_type == kind
            ]
            session.run(
                f"UNWIND $rows AS row "
                f"MATCH (s:Entity {{node_id: row.src}}), (t:Entity {{node_id: row.tgt}}) "
                f"MERGE (s)-[r:{rel}]->(t) SET r.holding_pct = row.pct",
                rows=rows,
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: PASS（1 项；Neo4j 节点/边数与 SQLite 一致）。

- [ ] **Step 5: 提交**

```bash
git add scripts/build_ownership_neo4j.py tests/test_neo4j_backend.py
git commit -m "功能：N2-2 SQLite→Neo4j 灌图脚本（幂等，节点/边数与源一致）"
```

---

### Task 3：`Neo4jBackend` + 双实现对拍

**Files:**
- Create: `src/deepresearch_agent/neo4j_backend.py`
- Test: `tests/test_neo4j_backend.py`（追加对拍）

**Interfaces:**
- Consumes: `neo4j.GraphDatabase`、`OwnershipGraphBackend` 四方法契约、`ControllerResult`（`graph_traversal`）、`NeighborEdge`（`ownership_backend`）、`build_ownership_neo4j`、`InMemoryOwnershipBackend`。
- Produces: `Neo4jBackend(driver)`；`Neo4jBackend.from_env() -> Neo4jBackend`（读 `NEO4J_*` + `verify_connectivity`，连不上抛异常）；实现 `has_node`/`display_name`/`ultimate_controllers`/`direct_neighbors`。

- [ ] **Step 1: 写失败对拍测试**

在 `tests/test_neo4j_backend.py` 末尾追加：

```python
def _graph(tmp_path: Path):
    from deepresearch_agent.company_database import build_company_database
    from deepresearch_agent.ownership_graph import load_ownership_graph

    database_path = tmp_path / "companies.sqlite3"
    if not database_path.exists():
        build_company_database(
            LINKS / "companies.csv",
            LINKS / "contacts.csv",
            database_path,
            shareholders_csv=LINKS / "shareholders.csv",
            investments_csv=LINKS / "investments.csv",
        )
    return load_ownership_graph(CompanyRepository(database_path))


@pytest.mark.neo4j
def test_neo4j_backend_matches_inmemory(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_ownership_neo4j import build_ownership_neo4j

    from deepresearch_agent.graph_retrieval import assemble_subgraph_context
    from deepresearch_agent.neo4j_backend import Neo4jBackend
    from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend

    repository = _repository(tmp_path)
    graph = _graph(tmp_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)
        neo = Neo4jBackend(driver)
        mem = InMemoryOwnershipBackend(graph)

        assert neo.has_node("no-such") is False
        assert neo.display_name("no-such") == "no-such"
        for code in (A_CODE, B_CODE, C_CODE):
            assert neo.has_node(code) == mem.has_node(code)
            assert neo.display_name(code) == mem.display_name(code)
            assert neo.ultimate_controllers(code) == mem.ultimate_controllers(code)
            assert neo.direct_neighbors(code) == mem.direct_neighbors(code)

        seeds = [A_CODE, B_CODE, C_CODE]
        assert assemble_subgraph_context(neo, seeds) == assemble_subgraph_context(mem, seeds)
    finally:
        driver.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py::test_neo4j_backend_matches_inmemory -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.neo4j_backend`）。

- [ ] **Step 3: 实现 `Neo4jBackend`**

创建 `src/deepresearch_agent/neo4j_backend.py`：

```python
from __future__ import annotations

import os

from deepresearch_agent.graph_traversal import ControllerResult
from deepresearch_agent.ownership_backend import NeighborEdge


class Neo4jBackend:
    """OwnershipGraphBackend 的 Neo4j 实现：遍历下推为 Cypher。

    via_person 语义说明：内存实现取"BFS 首达路径"的值；此处取"任一有效路径是否
    经自然人"（定义更确定）。二者在 ownership_links fixture 上逐条相等。
    """

    def __init__(self, driver) -> None:
        self._driver = driver

    @classmethod
    def from_env(cls) -> "Neo4jBackend":
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return cls(driver)

    def has_node(self, node_id: str) -> bool:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {node_id: $id}) RETURN count(n) > 0 AS exists", id=node_id
            ).single()
        return bool(rec["exists"])

    def display_name(self, node_id: str) -> str:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {node_id: $id}) RETURN n.display_name AS name", id=node_id
            ).single()
        return rec["name"] if rec is not None else node_id

    def ultimate_controllers(self, node_id: str, max_depth: int = 5) -> list[ControllerResult]:
        query = (
            f"MATCH path = (start:Entity {{node_id: $id}})"
            f"<-[:SHAREHOLDING|INVESTMENT*1..{int(max_depth)}]-(ctrl:Entity) "
            "WHERE none(n IN nodes(path)[1..] WHERE n.node_type = 'fund') "
            "AND (ctrl.is_person OR NOT EXISTS { "
            "MATCH (ctrl)<-[:SHAREHOLDING|INVESTMENT]-(p:Entity) WHERE p.node_type <> 'fund' }) "
            "WITH ctrl, min(length(path)) AS depth, "
            "max(CASE WHEN any(n IN nodes(path)[1..] WHERE n.is_person) THEN 1 ELSE 0 END) AS via "
            "RETURN ctrl.node_id AS node_id, ctrl.display_name AS display_name, "
            "depth, via = 1 AS via_person ORDER BY depth, node_id"
        )
        with self._driver.session() as s:
            return [
                ControllerResult(
                    node_id=r["node_id"],
                    display_name=r["display_name"],
                    depth=r["depth"],
                    via_person=r["via_person"],
                )
                for r in s.run(query, id=node_id)
            ]

    def direct_neighbors(self, node_id: str) -> list[NeighborEdge]:
        query = (
            "MATCH (x:Entity {node_id: $id})-[r:SHAREHOLDING|INVESTMENT]-(nb:Entity) "
            "RETURN nb.node_id AS node_id, nb.display_name AS name, nb.node_type AS node_type, "
            "type(r) AS rel_type, r.holding_pct AS holding_pct, "
            "CASE WHEN startNode(r).node_id = $id THEN 'out' ELSE 'in' END AS direction"
        )
        with self._driver.session() as s:
            neighbors = [
                NeighborEdge(
                    node_id=r["node_id"],
                    name=r["name"],
                    node_type=r["node_type"],
                    edge_type=r["rel_type"].lower(),
                    direction=r["direction"],
                    holding_pct=r["holding_pct"],
                )
                for r in s.run(query, id=node_id)
            ]
        neighbors.sort(key=lambda n: (n.direction, n.node_id))
        return neighbors
```

- [ ] **Step 4: 跑对拍确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: PASS（2 项：灌图 + 对拍逐条相等）。

> 若对拍某条不等：多半是 Cypher 语义与内存版有细微差（fund 过滤 / via_person / 排序 / holding_pct 的 null）。逐条对比 `neo.<方法>(code)` 与 `mem.<方法>(code)` 定位，修 Cypher，勿改内存实现（它是基准）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/neo4j_backend.py tests/test_neo4j_backend.py
git commit -m "功能：N2-3 Neo4jBackend（Cypher 遍历）+ 与内存实现双向对拍"
```

---

### Task 4：接线 —— 生产改用 Neo4jBackend

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`（`_build_graph_searcher`）
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `Neo4jBackend.from_env()`。
- Produces: `_build_graph_searcher(database_path, scope_retriever)` 改建 `Neo4jBackend`；连不上（`from_env` 抛异常）返回 `None`（决策期回退 scope）。内存实现不再进生产。

- [ ] **Step 1: 写失败测试（接线降级，CI 安全）**

在 `tests/test_graph.py` 末尾追加：

```python
def test_build_graph_searcher_none_when_neo4j_unavailable(company_database_path, monkeypatch):
    from deepresearch_agent.agents import graph as graph_module
    import deepresearch_agent.neo4j_backend as nb

    def boom(cls):
        raise RuntimeError("neo4j 不可达")

    monkeypatch.setattr(nb.Neo4jBackend, "from_env", classmethod(boom))
    searcher = graph_module._build_graph_searcher(company_database_path, object())
    assert searcher is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py::test_build_graph_searcher_none_when_neo4j_unavailable -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: FAIL —— 现 `_build_graph_searcher` 建 `InMemoryOwnershipBackend`（`load_ownership_graph`），不碰 `Neo4jBackend.from_env`，猴补丁不生效、返回一个 callable 而非 None。

- [ ] **Step 3: 改 `_build_graph_searcher` 建 Neo4jBackend**

`src/deepresearch_agent/agents/graph.py`，把 `_build_graph_searcher` 里 try 块：

```python
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend
        from deepresearch_agent.ownership_graph import load_ownership_graph

        backend = InMemoryOwnershipBackend(load_ownership_graph(CompanyRepository(database_path)))
        return lambda query: hybrid_search(query, scope_retriever, backend)
```

改为：

```python
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend.from_env()
        return lambda query: hybrid_search(query, scope_retriever, backend)
```

（`database_path` 参数保留以维持签名不变；灌图由 `scripts/build_ownership_neo4j.py` 离线完成，运行期只连 Neo4j。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py::test_build_graph_searcher_none_when_neo4j_unavailable -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: PASS（`from_env` 抛异常 → 捕获 → None）。

- [ ] **Step 5: 全量回归 + 对拍**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: 全绿（`neo4j` 标记默认排除；接线降级测试通过；其余不受影响）。

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n2`
Expected: PASS（Neo4j 起着时对拍仍绿）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/graph.py tests/test_graph.py
git commit -m "功能：N2-4 _build_graph_searcher 改建 Neo4jBackend，连不上降级 scope"
```

---

## 收尾

四个任务完成、全量绿 + 对拍绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。文档收尾前同步 N2：`docs/architecture.md`/`project-memory.md`/`CLAUDE.md` 说明生产图后端已切 Neo4j（内存实现退居测试替身）、灌图脚本、docker-compose、Neo4j 仅本地。**停容器**：`docker compose down`（保留卷）。

## Self-Review

- **Spec 覆盖**：数据模型（`:Entity` + `:SHAREHOLDING`/`:INVESTMENT`）=Task 2 灌图；四方法 Cypher + via_person 说明=Task 3；灌图脚本=Task 2；依赖/marker/compose/env=Task 1；生产接线（Neo4j 单引擎 + 连不上降级）=Task 4；对拍（连不上跳过、本会话真跑）=Task 2/3；红线（仅本地、SQLite 事实源、报告不变）=Global Constraints。
- **占位符**：无 TBD/TODO；每个改码步骤含完整代码/Cypher。
- **类型一致**：`Neo4jBackend` 四方法签名与 `OwnershipGraphBackend`（N1）一致；返回 `ControllerResult`/`NeighborEdge` 为既有类；`from_env` 在 Task 3 定义、Task 4 消费；`build_ownership_neo4j(repository, driver)` 在 Task 2 定义、Task 3 对拍复用。
