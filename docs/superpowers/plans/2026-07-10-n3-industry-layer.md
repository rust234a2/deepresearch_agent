# N3 业务/行业层进图 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把登记的国标行业四级名称确定性建成 Neo4j 的 `(:Industry)` 树 + 公司归属边，与股权层共图（数据层进图，不碰 Agent 检索）。

**Architecture:** 新增 `CompanyRepository.iter_company_industries()` 读四级行业名；灌图脚本加 `build_industry_neo4j` 幂等 MERGE 行业节点 + `SUBCLASS_OF` 层级链 + `IN_INDUSTRY` 归属边（MATCH 已有 Entity，不造孤儿）；只清行业子图、不碰股权。全确定性、无 LLM。

**Tech Stack:** Python、Neo4j 5（本地 Docker）、`neo4j` 驱动、pytest。复用 N2 的 driver/灌图模式、`docker-compose`、`.[neo4j]`、`@pytest.mark.neo4j`、主 procurement fixture。

## Global Constraints

- 全**确定性**（登记字段直接建节点），**无 LLM**、**不结构化 `business_scope`**。SQLite 是事实源，Neo4j 是可重建产物；Neo4j 仅本地。
- 报告/researcher/writer/CLI/API/`Neo4jBackend`/SQLite schema 一律不改。
- **关系类型用英文**：`IN_INDUSTRY`（公司→最深行业级）、`SUBCLASS_OF`（深→浅层级）——与 `SHAREHOLDING`/`INVESTMENT` 一致（refine spec 的中文 `属于行业`/`隶属`，收尾同步回 spec）。节点 `name`/`level` 属性保持中文。
- 行业节点 `node_id = "ind:{level}:{name}"`，`level` ∈ `门类/大类/中类/小类`；`(:Industry)` 与 `(:Entity)` 不同标签、不相撞。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`。`neo4j` 标记测试加 `-m neo4j`。
- 每个任务结束提交一次；中文提交信息。

## 文件结构

- 改 `src/deepresearch_agent/company_models.py` — 新增 `CompanyIndustry` 模型（Task 1）。
- 改 `src/deepresearch_agent/company_repository.py` — 新增 `iter_company_industries()`（Task 1）。
- 改 `scripts/build_ownership_neo4j.py` — 新增 `build_industry_neo4j` + `_industry_chain`/`_ind_id` 辅助（Task 2）。
- 改 `tests/test_company_repository.py` — 读方法测试（Task 1）；新 `tests/test_industry_layer_neo4j.py` — 灌图验证（Task 2）。

---

### Task 1：读层 —— `CompanyIndustry` 模型 + `iter_company_industries`

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`
- Modify: `src/deepresearch_agent/company_repository.py`
- Test: `tests/test_company_repository.py`

**Interfaces:**
- Consumes: `none_if_blank`、`field_validator`（`company_models.py` 已有）；`CompanyRepository._connect`。
- Produces: `CompanyIndustry`（字段 `unified_social_credit_code` + `gb_industry_section/division/group/class`，空串→None）；`CompanyRepository.iter_company_industries() -> list[CompanyIndustry]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾追加：

```python
def test_iter_company_industries_returns_four_level_names(company_database_path):
    repo = CompanyRepository(company_database_path)

    rows = repo.iter_company_industries()

    assert len(rows) == len(repo.get_all_company_names())
    with_class = [r for r in rows if r.gb_industry_class]
    assert with_class, "fixture 应至少有一家带小类行业"
    sample = with_class[0]
    assert sample.gb_industry_section and sample.gb_industry_division
    assert sample.gb_industry_group and sample.gb_industry_class
    assert sample.unified_social_credit_code
```

（`CompanyRepository` 已在该测试文件导入。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_company_industries_returns_four_level_names -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: FAIL（`AttributeError: 'CompanyRepository' object has no attribute 'iter_company_industries'`）

- [ ] **Step 3: 加 `CompanyIndustry` 模型**

在 `src/deepresearch_agent/company_models.py` 的 `GraphEdge` 定义之后追加：

```python
class CompanyIndustry(BaseModel):
    unified_social_credit_code: str
    gb_industry_section: str | None = None
    gb_industry_division: str | None = None
    gb_industry_group: str | None = None
    gb_industry_class: str | None = None

    @field_validator(
        "gb_industry_section",
        "gb_industry_division",
        "gb_industry_group",
        "gb_industry_class",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return none_if_blank(value)
```

（`BaseModel`/`field_validator`/`none_if_blank` 均已在文件顶部定义/导入。）

- [ ] **Step 4: 加 `iter_company_industries` 读方法**

在 `src/deepresearch_agent/company_repository.py` 顶部 `from deepresearch_agent.company_models import (` 的导入清单里加入 `CompanyIndustry,`（按字母序放在 `CompanyContact` 附近）。

在 `get_all_company_names` 方法之后追加：

```python
    def iter_company_industries(self) -> list[CompanyIndustry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, gb_industry_section, "
                "gb_industry_division, gb_industry_group, gb_industry_class "
                "FROM companies"
            ).fetchall()
        return [CompanyIndustry.model_validate(dict(row)) for row in rows]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_company_industries_returns_four_level_names -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: PASS

- [ ] **Step 6: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: 全绿（新增 1 项通过，既有不受影响）

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：N3-1 CompanyIndustry 模型与 iter_company_industries 读四级行业名"
```

---

### Task 2：灌图 —— `build_industry_neo4j` + 验证

**Files:**
- Modify: `scripts/build_ownership_neo4j.py`
- Test: `tests/test_industry_layer_neo4j.py`

**Interfaces:**
- Consumes: `CompanyRepository.iter_company_industries()`（Task 1）、`build_ownership_neo4j`（N2，建 `:Entity`）、neo4j driver。
- Produces: `build_industry_neo4j(repository, driver) -> None`；模块级辅助 `_industry_chain(ci) -> list[tuple[str, str]]`（非空 (level, name) 链，浅→深）、`_ind_id(level, name) -> str`。

- [ ] **Step 0: 起 Neo4j（若本会话未起）**

```powershell
$env:NEO4J_URI="bolt://localhost:7687"; $env:NEO4J_USER="neo4j"; $env:NEO4J_PASSWORD="devpassword"
docker compose up -d neo4j
```

- [ ] **Step 1: 写失败测试**

创建 `tests/test_industry_layer_neo4j.py`：

```python
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("neo4j")

from deepresearch_agent.company_repository import CompanyRepository

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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
def test_industry_layer_matches_data(company_database_path):
    from build_ownership_neo4j import (
        _industry_chain,
        build_industry_neo4j,
        build_ownership_neo4j,
    )

    repository = CompanyRepository(company_database_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)  # 先建 :Entity
        entity_before = _count(driver, "MATCH (n:Entity) RETURN count(n) AS c")

        build_industry_neo4j(repository, driver)

        industries = repository.iter_company_industries()
        distinct_nodes = set()
        member_count = 0
        hier_pairs = set()
        for ci in industries:
            chain = _industry_chain(ci)
            if not chain:
                continue
            member_count += 1
            ids = [f"ind:{lv}:{nm}" for lv, nm in chain]
            for lv, nm in chain:
                distinct_nodes.add((lv, nm))
            for shallow, deep in zip(ids, ids[1:]):
                hier_pairs.add((deep, shallow))

        assert _count(driver, "MATCH (i:Industry) RETURN count(i) AS c") == len(distinct_nodes)
        assert (
            _count(driver, "MATCH (:Entity)-[:IN_INDUSTRY]->(:Industry) RETURN count(*) AS c")
            == member_count
        )
        assert (
            _count(driver, "MATCH (:Industry)-[:SUBCLASS_OF]->(:Industry) RETURN count(*) AS c")
            == len(hier_pairs)
        )

        # 幂等：再灌一次，计数不变
        build_industry_neo4j(repository, driver)
        assert _count(driver, "MATCH (i:Industry) RETURN count(i) AS c") == len(distinct_nodes)

        # 不越界：行业灌图不动 :Entity
        assert _count(driver, "MATCH (n:Entity) RETURN count(n) AS c") == entity_before
    finally:
        driver.close()


def _count(driver, query: str) -> int:
    with driver.session() as s:
        return s.run(query).single()["c"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_industry_layer_neo4j.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: FAIL（`ImportError: cannot import name '_industry_chain'` / `build_industry_neo4j`）。若 SKIP，回 Step 0 起库。

- [ ] **Step 3: 实现 `build_industry_neo4j`**

在 `scripts/build_ownership_neo4j.py` 末尾追加：

```python
_INDUSTRY_LEVELS = ("门类", "大类", "中类", "小类")


def _ind_id(level: str, name: str) -> str:
    return f"ind:{level}:{name}"


def _industry_chain(ci) -> list[tuple[str, str]]:
    """公司的非空四级行业链，浅→深（门类→小类）。"""
    names = (
        ci.gb_industry_section,
        ci.gb_industry_division,
        ci.gb_industry_group,
        ci.gb_industry_class,
    )
    return [(level, name) for level, name in zip(_INDUSTRY_LEVELS, names) if name]


def build_industry_neo4j(repository, driver) -> None:
    """从登记的国标四级行业名建 (:Industry) 树 + 公司归属边。幂等，只影响行业子图。"""
    node_rows: dict[str, dict] = {}
    hier_rows: dict[tuple[str, str], dict] = {}
    member_rows: list[dict] = []
    for ci in repository.iter_company_industries():
        chain = _industry_chain(ci)
        if not chain:
            continue
        ids = []
        for level, name in chain:
            nid = _ind_id(level, name)
            node_rows[nid] = {"node_id": nid, "name": name, "level": level}
            ids.append(nid)
        for shallow, deep in zip(ids, ids[1:]):
            hier_rows[(deep, shallow)] = {"deep": deep, "shallow": shallow}
        member_rows.append({"code": ci.unified_social_credit_code, "ind": ids[-1]})

    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT industry_node_id IF NOT EXISTS "
            "FOR (i:Industry) REQUIRE i.node_id IS UNIQUE"
        )
        session.run("MATCH (i:Industry) DETACH DELETE i")
        session.run(
            "UNWIND $rows AS row MERGE (i:Industry {node_id: row.node_id}) "
            "SET i.name = row.name, i.level = row.level",
            rows=list(node_rows.values()),
        )
        session.run(
            "UNWIND $rows AS row "
            "MATCH (d:Industry {node_id: row.deep}), (s:Industry {node_id: row.shallow}) "
            "MERGE (d)-[:SUBCLASS_OF]->(s)",
            rows=list(hier_rows.values()),
        )
        session.run(
            "UNWIND $rows AS row "
            "MATCH (c:Entity {node_id: row.code}), (i:Industry {node_id: row.ind}) "
            "MERGE (c)-[:IN_INDUSTRY]->(i)",
            rows=member_rows,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_industry_layer_neo4j.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: PASS（节点数 = distinct、归属边 = 有行业的公司数、层级链 = distinct 对、幂等、不越界均通过）。

> 若失败：多为期望值算法与灌图链逻辑不一致（浅→深顺序、稀疏跳空、`(deep,shallow)` 去重）。用同一 `_industry_chain` 两边对齐，勿改数据。

- [ ] **Step 5: 全量回归 + 对拍仍绿**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: 全绿（`neo4j` 标记默认排除，含新行业测试）。

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py tests/test_industry_layer_neo4j.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n3`
Expected: PASS（N2 对拍 + N3 行业验证都真跑绿）。

- [ ] **Step 6: 提交**

```bash
git add scripts/build_ownership_neo4j.py tests/test_industry_layer_neo4j.py
git commit -m "功能：N3-2 build_industry_neo4j 灌国标行业树与公司归属边（幂等、不碰股权）"
```

---

## 收尾

两任务完成、全量绿 + 行业验证绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。收尾前文档同步 N3：`docs/architecture.md` 后续能力去掉 N3、`project-memory.md`/`CLAUDE.md` 记行业层已进图；并把 **N3 spec 的关系标签由中文 `属于行业`/`隶属` 更正为英文 `IN_INDUSTRY`/`SUBCLASS_OF`**（与实现一致）。

## Self-Review

- **Spec 覆盖**：`CompanyIndustry` + `iter_company_industries`=Task 1；`build_industry_neo4j`（节点/`SUBCLASS_OF`/`IN_INDUSTRY`、MATCH Entity 不造孤儿、幂等只清行业子图）=Task 2；验证（节点数/归属边/层级链/幂等/不越界，期望值从数据算）=Task 2；不碰 `Neo4jBackend`/Agent/报告=贯穿。关系标签中文→英文的偏差已在 Global Constraints 记录、收尾同步回 spec。
- **占位符**：无 TBD/TODO；每步含完整代码/Cypher。
- **类型一致**：`CompanyIndustry` 字段（Task 1）被 `_industry_chain`（Task 2）按 `gb_industry_section/division/group/class` 消费；`_industry_chain`/`_ind_id`/`build_industry_neo4j` 在 Task 2 定义、测试导入同名；`iter_company_industries` 返回 `list[CompanyIndustry]` 在两任务一致。
