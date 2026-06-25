# 模块 B1：实体解析 → 节点表实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `build_company_database` 同一事务内，把两份股权边里的实体去重成规范节点，落持久化 `graph_nodes` 表（schema 升 v4），并加 Repository 读层。

**Architecture:** 沿用 A2 的原子构建：`_create_schema` 加 `graph_nodes` 表 + 2 索引；边插完后 `_insert_graph_nodes` 从已插入的边表聚合实体（库内公司按信用代码、外部按 `ext:/person:/fund:`+规范名去重）；`SCHEMA_VERSION` 3→4；Repository 加 `get_graph_node` / `iter_graph_nodes`。

**Tech Stack:** Python 3.11、SQLite（标准库）、Pydantic v2、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM**；同名自然人合并为一节点（仅有名字），标 `is_person`、暴露 `mention_count`，绝不认定控制关系。
- **节点 = 边里出现过的实体**（锚点 + 对手方）；库内公司无边者不入节点。
- **node_id**：库内公司=信用代码；外部企业=`ext:`+规范名；自然人=`person:`+规范名；基金/托管=`fund:`+规范名。
- **基金判定**：规范名命中 `FUND_NOISE_KEYWORDS`（复用 A4 噪声关键词）。
- **原子 + 版本同步**：`SCHEMA_VERSION=4`，`PRAGMA user_version` 同步；Repository 版本不匹配报错。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`。每个 Task 一提交，中文提交信息。

---

### Task 1: schema v4 + `graph_nodes` 表 + 节点构建 + 模型

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`（`FUND_NOISE_KEYWORDS` 常量、`GraphNode` 模型、`RelatedPartyConfig` 默认引用常量）
- Modify: `src/deepresearch_agent/company_database.py`（`SCHEMA_VERSION=4`、import 常量、`_create_schema` 加表/索引、`_insert_graph_nodes`、摘要加 `nodes`）
- Modify: `tests/test_company_database.py`（v4 + 摘要 +nodes + 节点用例）
- Modify: `tests/test_company_database_cli.py`（摘要打印 +nodes）

**Interfaces:**
- Consumes：A2 的 `company_shareholders`/`company_investments` 表列、`normalize_company_name`、`_CompanySourceRow`。
- Produces：
  - `company_models.FUND_NOISE_KEYWORDS: tuple[str, ...]`、`GraphNode` 模型。
  - `graph_nodes` 表（列见下）。
  - `build_company_database(...)` 摘要追加 `"nodes": int`。

- [ ] **Step 1: 写失败测试（构建产出节点）**

把 `tests/test_company_database.py` 的 `test_build_company_database_creates_schema_indexes_and_metadata` 里的 `user_version` 断言与摘要断言更新，并新增节点用例。具体改动：

把该测试中

```python
    assert summary == {
        "companies": 1,
        "contacts": 1,
        "shareholders": 0,
        "investments": 0,
        "unresolved_shareholders": 0,
        "unresolved_investments": 0,
    }
```

改为（加 `"nodes": 0`）：

```python
    assert summary == {
        "companies": 1,
        "contacts": 1,
        "shareholders": 0,
        "investments": 0,
        "unresolved_shareholders": 0,
        "unresolved_investments": 0,
        "nodes": 0,
    }
```

把同测试里 `assert connection.execute("PRAGMA user_version").fetchone()[0] == 3` 改为 `== 4`，并在该测试的索引集合断言（`{ ... } <= indexes`）里追加两项：

```python
        "idx_graph_nodes_normalized",
        "idx_graph_nodes_type",
```

在 `tests/test_company_database.py` 末尾新增节点用例：

```python
def test_build_company_database_builds_graph_nodes(tmp_path):
    database_path = tmp_path / "companies.sqlite3"

    summary = build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )

    assert summary["nodes"] == 3
    with sqlite3.connect(database_path) as connection:
        company = connection.execute(
            "SELECT node_type, in_database, unified_social_credit_code, is_person, mention_count "
            "FROM graph_nodes WHERE node_id = '91330000123456789X'"
        ).fetchone()
        assert company == ("company", 1, "91330000123456789X", 0, 6)
        person = connection.execute(
            "SELECT node_type, in_database, is_person FROM graph_nodes WHERE node_id = 'person:张三'"
        ).fetchone()
        assert person == ("person", 0, 1)
        external = connection.execute(
            "SELECT node_type, in_database FROM graph_nodes "
            "WHERE display_name = '某外部子公司有限公司'"
        ).fetchone()
        assert external == ("company", 0)


def test_build_company_database_classifies_fund_nodes(tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"
    database_path = tmp_path / "companies.sqlite3"

    build_company_database(
        fixtures / "companies.csv",
        fixtures / "contacts.csv",
        database_path,
        shareholders_csv=fixtures / "shareholders.csv",
        investments_csv=fixtures / "investments.csv",
    )

    with sqlite3.connect(database_path) as connection:
        fund = connection.execute(
            "SELECT node_type FROM graph_nodes WHERE display_name = '嘉实沪深300指数证券投资基金'"
        ).fetchone()
        assert fund == ("fund",)
        node_id = connection.execute(
            "SELECT node_id FROM graph_nodes WHERE display_name = '嘉实沪深300指数证券投资基金'"
        ).fetchone()[0]
        assert node_id.startswith("fund:")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py::test_build_company_database_builds_graph_nodes -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`
Expected: FAIL —`sqlite3.OperationalError: no such table: graph_nodes`（或摘要 KeyError 'nodes'）。

- [ ] **Step 3: 加 `FUND_NOISE_KEYWORDS` 常量 + `GraphNode` 模型，并让 `RelatedPartyConfig` 引用常量**

在 `src/deepresearch_agent/company_models.py` 中，把现有 `RelatedPartyConfig` 的 `noise_keywords` 默认值提取为模块级常量。先在 `RelatedPartyConfig` 定义之前新增：

```python
FUND_NOISE_KEYWORDS = (
    "证券投资基金",
    "指数",
    "etf",
    "登记结算",
    "中央结算",
    "nominees",
    "ubs",
    "barclays",
    "morgan",
    "goldman",
    "qfii",
)
```

把 `RelatedPartyConfig.noise_keywords` 的默认值改为引用该常量：

```python
class RelatedPartyConfig(BaseModel):
    corporate_degree_cap: int = 10
    investee_degree_cap: int = 10
    noise_keywords: tuple[str, ...] = FUND_NOISE_KEYWORDS
```

在 `company_models.py` 末尾追加 `GraphNode` 模型：

```python
class GraphNode(BaseModel):
    node_id: str
    display_name: str
    normalized_name: str
    node_type: Literal["company", "person", "fund"]
    in_database: bool
    unified_social_credit_code: str | None = None
    is_person: bool = False
    mention_count: int
```

- [ ] **Step 4: schema v4 + `graph_nodes` 表 + 索引**

在 `src/deepresearch_agent/company_database.py`：

把 `SCHEMA_VERSION = 3` 改为 `SCHEMA_VERSION = 4`。

把顶部导入 `from deepresearch_agent.company_models import CompanyContact, CompanyProfile` 改为：

```python
from deepresearch_agent.company_models import CompanyContact, CompanyProfile, FUND_NOISE_KEYWORDS
```

在 `_create_schema` 的多语句 schema 块里、`idx_investments_investee_code` 索引之后（schema 字符串闭合 `"""` 之前）追加：

```sql
        CREATE TABLE graph_nodes (
            node_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            node_type TEXT NOT NULL,
            in_database INTEGER NOT NULL,
            unified_social_credit_code TEXT,
            is_person INTEGER NOT NULL,
            mention_count INTEGER NOT NULL
        );
        CREATE INDEX idx_graph_nodes_normalized ON graph_nodes(normalized_name);
        CREATE INDEX idx_graph_nodes_type ON graph_nodes(node_type);
```

- [ ] **Step 5: 加 `_insert_graph_nodes` 并接入构建与摘要**

在 `src/deepresearch_agent/company_database.py` 新增函数（置于 `_insert_investments` 之后）：

```python
def _insert_graph_nodes(
    connection: sqlite3.Connection,
    companies: list[_CompanySourceRow],
) -> int:
    legal_map = {
        item.profile.unified_social_credit_code: item.profile.legal_name for item in companies
    }
    nodes: dict[str, dict] = {}

    def bump_company(code: str) -> None:
        node = nodes.get(code)
        if node is None:
            legal_name = legal_map[code]
            nodes[code] = {
                "node_id": code,
                "display_name": legal_name,
                "normalized_name": normalize_company_name(legal_name),
                "node_type": "company",
                "in_database": 1,
                "unified_social_credit_code": code,
                "is_person": 0,
                "mention_count": 1,
            }
        else:
            node["mention_count"] += 1

    def bump_external(display_name: str, normalized_name: str, is_person: bool) -> None:
        if is_person:
            node_id = f"person:{normalized_name}"
            node_type = "person"
        elif any(keyword in normalized_name for keyword in FUND_NOISE_KEYWORDS):
            node_id = f"fund:{normalized_name}"
            node_type = "fund"
        else:
            node_id = f"ext:{normalized_name}"
            node_type = "company"
        node = nodes.get(node_id)
        if node is None:
            nodes[node_id] = {
                "node_id": node_id,
                "display_name": display_name,
                "normalized_name": normalized_name,
                "node_type": node_type,
                "in_database": 0,
                "unified_social_credit_code": None,
                "is_person": 1 if is_person else 0,
                "mention_count": 1,
            }
        else:
            node["mention_count"] += 1

    for anchor, name, normalized, code, is_person in connection.execute(
        "SELECT unified_social_credit_code, shareholder_name, normalized_shareholder_name, "
        "shareholder_credit_code, shareholder_is_person FROM company_shareholders"
    ).fetchall():
        bump_company(anchor)
        if code is not None:
            bump_company(code)
        else:
            bump_external(name, normalized, is_person == "true")

    for anchor, name, normalized, code in connection.execute(
        "SELECT unified_social_credit_code, investee_name, normalized_investee_name, "
        "investee_credit_code FROM company_investments"
    ).fetchall():
        bump_company(anchor)
        if code is not None:
            bump_company(code)
        else:
            bump_external(name, normalized, False)

    for node in nodes.values():
        connection.execute(
            "INSERT INTO graph_nodes (node_id, display_name, normalized_name, node_type, "
            "in_database, unified_social_credit_code, is_person, mention_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node["node_id"],
                node["display_name"],
                node["normalized_name"],
                node["node_type"],
                node["in_database"],
                node["unified_social_credit_code"],
                node["is_person"],
                node["mention_count"],
            ),
        )
    return len(nodes)
```

在 `_build_atomic_database` 里，`_insert_investments(...)` 之后、写 `import_metadata` 之前插入：

```python
            node_count = _insert_graph_nodes(connection, companies)
```

把 `_build_atomic_database` 末尾 `return {...}` 改为追加 `nodes`：

```python
    return {
        "shareholders": sh_inserted,
        "investments": inv_inserted,
        "unresolved_shareholders": sh_unresolved,
        "unresolved_investments": inv_unresolved,
        "nodes": node_count,
    }
```

- [ ] **Step 6: 跑构建测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`
Expected: PASS（含两个新节点用例 + 更新后的 v4/摘要用例）。

- [ ] **Step 7: 更新 CLI 摘要打印断言**

把 `tests/test_company_database_cli.py` 两处断言

```python
        "companies=1 contacts=1 shareholders=0 investments=0 "
        "unresolved_shareholders=0 unresolved_investments=0"
```

改为（追加 ` nodes=0`）：

```python
        "companies=1 contacts=1 shareholders=0 investments=0 "
        "unresolved_shareholders=0 unresolved_investments=0 nodes=0"
```

- [ ] **Step 8: 跑 CLI 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`
Expected: PASS（2 passed）。若 CLI 实际打印顺序/格式不符，检查 `scripts/build_company_database.py` 的打印行确为按摘要字典顺序 `key=value` 空格连接。

- [ ] **Step 9: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_database.py tests/test_company_database.py tests/test_company_database_cli.py
git commit -m "功能：B1 建库生成 graph_nodes 实体节点表并升 schema v4"
```

---

### Task 2: Repository 节点读层

**Files:**
- Modify: `src/deepresearch_agent/company_repository.py`（导入 `GraphNode`；新增 `get_graph_node`、`iter_graph_nodes`；版本断言随常量自动变 4）
- Modify: `tests/test_company_repository.py`（`expected 3`→`expected 4`；新增节点读用例）

**Interfaces:**
- Consumes：Task 1 的 `graph_nodes` 表、`GraphNode` 模型、`_build_database_with_ownership`（已在 A3 加）。
- Produces：
  - `CompanyRepository.get_graph_node(node_id: str) -> GraphNode | None`。
  - `CompanyRepository.iter_graph_nodes() -> list[GraphNode]`。

- [ ] **Step 1: 写失败测试**

把 `tests/test_company_repository.py` 中 `with pytest.raises(RuntimeError, match="expected 3"):` 改为 `match="expected 4"`。

在文件末尾新增：

```python
def test_get_graph_node_returns_typed_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    company = repository.get_graph_node("91330000123456789X")
    assert company is not None
    assert company.node_type == "company"
    assert company.in_database is True
    assert company.unified_social_credit_code == "91330000123456789X"

    person = repository.get_graph_node("person:张三")
    assert person is not None
    assert person.node_type == "person"
    assert person.is_person is True

    assert repository.get_graph_node("no-such-node") is None


def test_iter_graph_nodes_returns_all_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    nodes = repository.iter_graph_nodes()

    assert {n.node_id for n in nodes} == {
        "91330000123456789X",
        "person:张三",
        n_id_for_external(nodes),
    }


def n_id_for_external(nodes):
    return next(n.node_id for n in nodes if n.display_name == "某外部子公司有限公司")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_get_graph_node_returns_typed_nodes -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`
Expected: FAIL —`AttributeError: 'CompanyRepository' object has no attribute 'get_graph_node'`。

- [ ] **Step 3: 加节点读方法**

在 `src/deepresearch_agent/company_repository.py` 的 `company_models` 导入列表加入 `GraphNode`（保持字母序，置于 `CompanyResolutionCandidate` 之后、`InvestmentRecord` 之前）。

在 `iter_investment_edges` 之后新增：

```python
    def get_graph_node(self, node_id: str) -> GraphNode | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_id, display_name, normalized_name, node_type, in_database, "
                "unified_social_credit_code, is_person, mention_count "
                "FROM graph_nodes WHERE node_id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return _graph_node_from_row(row)

    def iter_graph_nodes(self) -> list[GraphNode]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT node_id, display_name, normalized_name, node_type, in_database, "
                "unified_social_credit_code, is_person, mention_count FROM graph_nodes"
            ).fetchall()
        return [_graph_node_from_row(row) for row in rows]
```

在 `company_repository.py` 模块底部（类外，与其他 `_` 辅助函数同区）新增构造辅助：

```python
def _graph_node_from_row(row: sqlite3.Row) -> GraphNode:
    return GraphNode(
        node_id=row["node_id"],
        display_name=row["display_name"],
        normalized_name=row["normalized_name"],
        node_type=row["node_type"],
        in_database=bool(row["in_database"]),
        unified_social_credit_code=row["unified_social_credit_code"],
        is_person=bool(row["is_person"]),
        mention_count=row["mention_count"],
    )
```

- [ ] **Step 4: 跑节点读测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b1`
Expected: PASS。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-b1-full`
Expected: PASS（114 + 本次新增，2 deselected）。注意：所有经 `_connect()` 的测试现在要求 v4；fixture 经 `build_company_database` 现场重建即得 v4，无需手动迁移。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：B1 Repository 加 graph_nodes 节点读层"
```

---

## 自检

**Spec 覆盖**：
- schema v4 + `graph_nodes` 表 + 2 索引 → Task 1 Step 4。
- `FUND_NOISE_KEYWORDS` 常量 + `RelatedPartyConfig` 引用 + `GraphNode` 模型 → Task 1 Step 3。
- `_insert_graph_nodes`（库内/外部/person/fund 分类、去重、mention_count、摘要 nodes）→ Task 1 Step 5 + 测试 Step 1。
- 基金归类 → Task 1 的 `test_build_company_database_classifies_fund_nodes`。
- CLI 摘要 +nodes → Task 1 Step 7。
- Repository `get_graph_node`/`iter_graph_nodes` + `expected 4` → Task 2。

**Placeholder 扫描**：无 TBD/TODO；每个改代码步骤给完整代码与命令/预期。

**类型一致性**：`GraphNode` 字段（`node_id`/`display_name`/`normalized_name`/`node_type`/`in_database`/`unified_social_credit_code`/`is_person`/`mention_count`）在模型、`graph_nodes` 表列、`_insert_graph_nodes` 写入、`_graph_node_from_row` 读取、测试断言五处一致；`node_id` 方案（信用代码 / `ext:`/`person:`/`fund:`+规范名）在 spec、构建、测试一致；`SCHEMA_VERSION=4` 在 `company_database` 定义、Repository 校验、两处测试断言一致。
