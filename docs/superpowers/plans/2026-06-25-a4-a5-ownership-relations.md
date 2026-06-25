# 模块 A4 + A5：股权关联计算与 Agent 接入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 A4 股权关联计算（`find_related_parties`：直接边 + 共享外部企业股东/自然人/对外投资 + 噪声过滤）并通过 A5 把"股权邻域 + 关联方"接进 LangGraph Agent（两工具、两研究维度），recommendation 仍固定 `insufficient_evidence`。

**Architecture:** A4 在内存里扫一遍全部边表建反向索引（节点→公司集合），无 schema 变更；A5 沿用现有"工具白名单 → researcher 调工具 → 按维度产 Evidence → critic → writer"模式，新增两工具两维度，空结果显式产"数据源未提供"证据守红线。

**Tech Stack:** Python 3.11、Pydantic v2、SQLite、LangGraph、pytest。仓库内 conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM**；关联方是线索不是结论，绝不做控制关系认定或采购批准/拒绝；writer 仍 `recommendation="insufficient_evidence"`。
- **数据缺失 ≠ 无风险**：空结果也显式写"数据源未提供"证据，不静默跳过。
- **名称匹配 ≠ 身份认定**：自然人关联一律低置信（0.2）+ 须人工复核，**不按度过滤**（全展示 + 警示）。
- **噪声过滤只作用于企业/投资侧**：度 > cap（默认 10）**或** 名称命中关键词（证券投资基金/指数/etf/登记结算/中央结算/nominees/ubs/barclays/morgan/goldman/qfii）→ 剔除；PE/产业基金保留。
- **名称连接**用 `normalize_company_name`（A2 入库时已规范化，A4 直接比较存库的 `normalized_*`）。
- 置信度：direct 0.9 / shared_corporate 0.5 / shared_investee 0.25 / shared_person 0.2。
- 测试解释器：`.\.conda-env\python.exe -m pytest`，Windows 下加 `-p no:cacheprovider --basetemp=.conda-cache/pytest-a45`。每个 Task 完成后提交，中文提交信息。

---

### Task 1: Repository 批量读 + `OwnershipEdge` 模型（A4 取数地基）

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`（新增 `OwnershipEdge`）
- Modify: `src/deepresearch_agent/company_repository.py`（导入 `OwnershipEdge`；新增 `get_all_company_names`、`iter_shareholder_edges`、`iter_investment_edges`）
- Test: `tests/test_company_repository.py`（复用 Task 已有的 `_build_database_with_ownership`）

**Interfaces:**
- Consumes：`_build_database_with_ownership(tmp_path)`（A3 已加）、fixtures `shareholders.csv`/`investments.csv`。
- Produces：
  - `OwnershipEdge(company_code: str, node_name: str, node_code: str | None = None, is_person: bool = False)`。
  - `CompanyRepository.get_all_company_names() -> dict[str, str]`（code → legal_name）。
  - `CompanyRepository.iter_shareholder_edges() -> list[OwnershipEdge]`。
  - `CompanyRepository.iter_investment_edges() -> list[OwnershipEdge]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾追加：

```python
def test_iter_shareholder_edges_returns_normalized_nodes(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    edges = repository.iter_shareholder_edges()

    assert len(edges) == 2
    person = next(e for e in edges if e.node_name == "张三")
    assert person.company_code == "91330000123456789X"
    assert person.is_person is True
    assert person.node_code is None
    entity = next(e for e in edges if e.is_person is False)
    assert entity.node_code == "91330000123456789X"


def test_iter_investment_edges_and_company_names(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    edges = repository.iter_investment_edges()
    names = repository.get_all_company_names()

    assert len(edges) == 2
    resolved = next(e for e in edges if e.node_code is not None)
    assert resolved.node_code == "91330000123456789X"
    assert all(e.is_person is False for e in edges)
    assert names["91330000123456789X"] == "示例科技股份有限公司"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_shareholder_edges_returns_normalized_nodes -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: FAIL —`AttributeError: 'CompanyRepository' object has no attribute 'iter_shareholder_edges'`。

- [ ] **Step 3: 加 `OwnershipEdge` 模型**

在 `src/deepresearch_agent/company_models.py` 末尾追加：

```python
class OwnershipEdge(BaseModel):
    company_code: str
    node_name: str
    node_code: str | None = None
    is_person: bool = False
```

- [ ] **Step 4: 加三个批量读方法**

在 `src/deepresearch_agent/company_repository.py` 的 `company_models` 导入列表加入 `OwnershipEdge`（保持字母序，置于 `InvestmentRecord` 之后、`ScopeChunkRecord` 之前）：

```python
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
    InvestmentRecord,
    OwnershipEdge,
    ScopeChunkRecord,
    ScopeIndexMetadata,
    ShareholderRecord,
)
```

在 `get_investments` 方法之后新增三个方法：

```python
    def get_all_company_names(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, legal_name FROM companies"
            ).fetchall()
        return {row["unified_social_credit_code"]: row["legal_name"] for row in rows}

    def iter_shareholder_edges(self) -> list[OwnershipEdge]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, normalized_shareholder_name, "
                "shareholder_credit_code, shareholder_is_person FROM company_shareholders"
            ).fetchall()
        return [
            OwnershipEdge(
                company_code=row["unified_social_credit_code"],
                node_name=row["normalized_shareholder_name"],
                node_code=row["shareholder_credit_code"],
                is_person=row["shareholder_is_person"] == "true",
            )
            for row in rows
        ]

    def iter_investment_edges(self) -> list[OwnershipEdge]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, normalized_investee_name, "
                "investee_credit_code FROM company_investments"
            ).fetchall()
        return [
            OwnershipEdge(
                company_code=row["unified_social_credit_code"],
                node_name=row["normalized_investee_name"],
                node_code=row["investee_credit_code"],
                is_person=False,
            )
            for row in rows
        ]
```

- [ ] **Step 5: 跑两个测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_shareholder_edges_returns_normalized_nodes tests/test_company_repository.py::test_iter_investment_edges_and_company_names -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：Repository 加股权边批量读与公司名映射"
```

---

### Task 2: `find_related_parties` 关联计算（A4 核心）

**Files:**
- Create: `src/deepresearch_agent/ownership_links.py`
- Modify: `src/deepresearch_agent/company_models.py`（新增 `RelationType`、`RelatedParty`、`RelatedPartyConfig`）
- Create: `tests/test_ownership_links.py`
- Create fixtures: `tests/fixtures/procurement/ownership_links/{companies,contacts,shareholders,investments}.csv`

**Interfaces:**
- Consumes：Task 1 的 `OwnershipEdge` 与三个批量读方法；`normalize_company_name` 已在 A2 入库时作用于存库的 `normalized_*`。
- Produces：
  - `RelatedParty`（字段见下）、`RelatedPartyConfig`、`RelationType`。
  - `find_related_parties(repository, code: str, config: RelatedPartyConfig = DEFAULT_CONFIG) -> list[RelatedParty]`。

- [ ] **Step 1: 建 A4 fixture（3 家库内公司 + 共享/噪声/直接/自然人节点）**

创建 `tests/fixtures/procurement/ownership_links/companies.csv`（表头与 `tests/fixtures/procurement/companies.csv` 完全一致，3 行只填前 4 列，其余 30 列留空）：

```
source_name,legal_name,registration_status,unified_social_credit_code,legal_representative,company_type,registered_capital_amount,registered_capital_currency,registered_capital_original,paid_in_capital_amount,paid_in_capital_currency,paid_in_capital_original,established_date,business_term_start,business_term_end,business_term_indefinite,registered_address,province,city,district,registration_authority,gb_industry_section,gb_industry_division,gb_industry_group,gb_industry_class,enterprise_size,business_scope,aliases,english_name,website,employee_count,employee_count_report_year,latest_annual_report_year,taxpayer_qualification
甲公司,甲公司,存续,91110000000000111A,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
乙公司,乙公司,存续,91110000000000222B,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
丙公司,丙公司,存续,91110000000000333C,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
```

创建 `tests/fixtures/procurement/ownership_links/contacts.csv`（仅表头）：

```
unified_social_credit_code,legal_name,phones,emails,mailing_address
```

创建 `tests/fixtures/procurement/ownership_links/shareholders.csv`：

```
company_name,normalized_company_name,shareholder_name,shareholder_type,shareholder_is_person,share_class,shares_held,indirect_holding_pct,associated_product
甲公司,甲公司,共同控股集团有限公司,企业法人,false,,,,
乙公司,乙公司,共同控股集团有限公司,企业法人,false,,,,
甲公司,甲公司,张三,自然人股东,true,,,,
丙公司,丙公司,张三,自然人股东,true,,,,
甲公司,甲公司,嘉实沪深300指数证券投资基金,投资基金,false,,,,
乙公司,乙公司,嘉实沪深300指数证券投资基金,投资基金,false,,,,
甲公司,甲公司,乙公司,企业法人,false,,,,
```

创建 `tests/fixtures/procurement/ownership_links/investments.csv`：

```
company_name,normalized_company_name,investee_name,normalized_investee_name,status,investee_established_date,holding_pct,subscribed_capital_amount,subscribed_capital_currency,subscribed_capital_original,final_beneficiary_pct,region,industry,associated_product
甲公司,甲公司,共同投资标的有限公司,共同投资标的有限公司,存续,,,,,,,,,
乙公司,乙公司,共同投资标的有限公司,共同投资标的有限公司,存续,,,,,,,,,
甲公司,甲公司,丙公司,丙公司,存续,,,,,,,,,
```

设计意图（甲=A `...111A`，乙=B `...222B`，丙=C `...333C`，字典序 A<B<C）：
- 乙 是 甲 的股东（库内）→ 查 A 得 `direct_shareholder` B。
- 甲 投资 丙（库内）→ 查 A 得 `direct_investee` C。
- 共同控股集团 同为 甲、乙 股东 → `shared_corporate_shareholder` B（度 2）。
- 张三 同为 甲、丙 股东 → `shared_person_shareholder` C（度 2）。
- 嘉实…指数证券投资基金 同为 甲、乙 股东 → 命中关键词，**被过滤**。
- 共同投资标的 同被 甲、乙 投资 → `shared_investee` B（度 2）。

- [ ] **Step 2: 写失败测试**

创建 `tests/test_ownership_links.py`：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_models import RelatedPartyConfig
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.ownership_links import find_related_parties


FIXTURES = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"

A_CODE = "91110000000000111A"
B_CODE = "91110000000000222B"
C_CODE = "91110000000000333C"


def _repository(tmp_path: Path) -> CompanyRepository:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )
    return CompanyRepository(database_path)


def test_find_related_parties_covers_all_relation_types_and_filters_noise(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE)

    pairs = {(p.related_code, p.relation_type) for p in parties}
    assert pairs == {
        (B_CODE, "direct_shareholder"),
        (C_CODE, "direct_investee"),
        (B_CODE, "shared_corporate_shareholder"),
        (B_CODE, "shared_investee"),
        (C_CODE, "shared_person_shareholder"),
    }
    # 嘉实…证券投资基金 是噪声，不得制造任何关联
    assert all("证券投资基金" not in (p.via_node_name or "") for p in parties)

    person = next(p for p in parties if p.relation_type == "shared_person_shareholder")
    assert person.confidence == 0.2
    assert person.via_is_person is True
    assert person.shared_degree == 2
    assert "须人工复核" in person.reliability_note

    corporate = next(p for p in parties if p.relation_type == "shared_corporate_shareholder")
    assert corporate.confidence == 0.5
    assert corporate.via_node_name == "共同控股集团有限公司"


def test_find_related_parties_sorted_by_confidence_then_code(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE)

    keys = [(p.confidence, p.related_code) for p in parties]
    assert keys == sorted(keys, key=lambda k: (-k[0], k[1]))
    assert parties[0].confidence == 0.9


def test_find_related_parties_degree_cap_filters_corporate_links(tmp_path):
    repository = _repository(tmp_path)

    parties = find_related_parties(repository, A_CODE, RelatedPartyConfig(corporate_degree_cap=1))

    # 度 2 的共同控股集团被 cap=1 过滤；自然人不受企业 cap 影响仍在
    assert not any(p.relation_type == "shared_corporate_shareholder" for p in parties)
    assert any(p.relation_type == "shared_person_shareholder" for p in parties)


def test_find_related_parties_empty_for_unknown_code(tmp_path):
    repository = _repository(tmp_path)

    assert find_related_parties(repository, "no-such-code") == []
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_links.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.ownership_links'` 或 `ImportError: cannot import name 'RelatedPartyConfig'`。

- [ ] **Step 4: 加 `RelationType` / `RelatedParty` / `RelatedPartyConfig` 模型**

在 `src/deepresearch_agent/company_models.py` 末尾追加（`Literal` 已在顶部 import）：

```python
RelationType = Literal[
    "direct_shareholder",
    "direct_investee",
    "shared_corporate_shareholder",
    "shared_person_shareholder",
    "shared_investee",
]


class RelatedParty(BaseModel):
    unified_social_credit_code: str
    related_code: str
    related_name: str
    relation_type: RelationType
    via_node_name: str | None = None
    via_is_person: bool = False
    shared_degree: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reliability_note: str


class RelatedPartyConfig(BaseModel):
    corporate_degree_cap: int = 10
    investee_degree_cap: int = 10
    noise_keywords: tuple[str, ...] = (
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

- [ ] **Step 5: 写 `ownership_links.py`**

创建 `src/deepresearch_agent/ownership_links.py`：

```python
from __future__ import annotations

from deepresearch_agent.company_models import (
    RelatedParty,
    RelatedPartyConfig,
    RelationType,
)
from deepresearch_agent.company_repository import CompanyRepository


DEFAULT_CONFIG = RelatedPartyConfig()

_RELATION_CONFIDENCE: dict[RelationType, float] = {
    "direct_shareholder": 0.9,
    "direct_investee": 0.9,
    "shared_corporate_shareholder": 0.5,
    "shared_person_shareholder": 0.2,
    "shared_investee": 0.25,
}


def _is_noise(node_name: str, degree: int, cap: int, keywords: tuple[str, ...]) -> bool:
    if degree > cap:
        return True
    return any(keyword in node_name for keyword in keywords)


def _reliability_note(
    relation_type: RelationType,
    anchor_name: str,
    related_name: str,
    via_node: str | None,
    degree: int | None,
) -> str:
    if relation_type == "direct_shareholder":
        return f"登记直接持股关系：{related_name} 持有 {anchor_name}。"
    if relation_type == "direct_investee":
        return f"登记直接投资关系：{anchor_name} 投资 {related_name}。"
    if relation_type == "shared_corporate_shareholder":
        return f"经由共同企业股东「{via_node}」推断的关联，需人工核实是否构成共同控制。"
    if relation_type == "shared_person_shareholder":
        return (
            f"经由同名自然人「{via_node}」关联（该姓名共连接 {degree} 家库内公司），"
            "疑似重名，信息不可靠，须人工复核确认是否同一人。"
        )
    return f"经由共同对外投资「{via_node}」推断的弱关联，合资不等于同一控制。"


def find_related_parties(
    repository: CompanyRepository,
    code: str,
    config: RelatedPartyConfig = DEFAULT_CONFIG,
) -> list[RelatedParty]:
    anchor = code.strip()
    names = repository.get_all_company_names()
    if anchor not in names:
        return []

    shareholder_edges = repository.iter_shareholder_edges()
    investment_edges = repository.iter_investment_edges()

    corp_index: dict[str, set[str]] = {}
    person_index: dict[str, set[str]] = {}
    investee_index: dict[str, set[str]] = {}
    for edge in shareholder_edges:
        if edge.is_person:
            person_index.setdefault(edge.node_name, set()).add(edge.company_code)
        elif edge.node_code is None:
            corp_index.setdefault(edge.node_name, set()).add(edge.company_code)
    for edge in investment_edges:
        if edge.node_code is None:
            investee_index.setdefault(edge.node_name, set()).add(edge.company_code)

    results: list[RelatedParty] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(
        related_code: str,
        relation_type: RelationType,
        via_node: str | None,
        via_is_person: bool,
        degree: int | None,
    ) -> None:
        if related_code == anchor or related_code not in names:
            return
        key = (related_code, relation_type, via_node)
        if key in seen:
            return
        seen.add(key)
        results.append(
            RelatedParty(
                unified_social_credit_code=anchor,
                related_code=related_code,
                related_name=names[related_code],
                relation_type=relation_type,
                via_node_name=via_node,
                via_is_person=via_is_person,
                shared_degree=degree,
                confidence=_RELATION_CONFIDENCE[relation_type],
                reliability_note=_reliability_note(
                    relation_type, names[anchor], names[related_code], via_node, degree
                ),
            )
        )

    # 直接边
    for edge in shareholder_edges:
        if edge.company_code == anchor and edge.node_code is not None:
            add(edge.node_code, "direct_shareholder", None, False, None)
    for edge in investment_edges:
        if edge.company_code == anchor and edge.node_code is not None:
            add(edge.node_code, "direct_investee", None, False, None)

    # 共享企业股东
    anchor_corp_nodes = {
        edge.node_name
        for edge in shareholder_edges
        if edge.company_code == anchor and not edge.is_person and edge.node_code is None
    }
    for node in anchor_corp_nodes:
        companies = corp_index.get(node, set())
        if _is_noise(node, len(companies), config.corporate_degree_cap, config.noise_keywords):
            continue
        for other in companies:
            add(other, "shared_corporate_shareholder", node, False, len(companies))

    # 共享自然人（不过滤）
    anchor_person_nodes = {
        edge.node_name
        for edge in shareholder_edges
        if edge.company_code == anchor and edge.is_person
    }
    for node in anchor_person_nodes:
        companies = person_index.get(node, set())
        for other in companies:
            add(other, "shared_person_shareholder", node, True, len(companies))

    # 共同对外投资
    anchor_investee_nodes = {
        edge.node_name
        for edge in investment_edges
        if edge.company_code == anchor and edge.node_code is None
    }
    for node in anchor_investee_nodes:
        companies = investee_index.get(node, set())
        if _is_noise(node, len(companies), config.investee_degree_cap, config.noise_keywords):
            continue
        for other in companies:
            add(other, "shared_investee", node, False, len(companies))

    results.sort(key=lambda party: (-party.confidence, party.related_code))
    return results
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_ownership_links.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: PASS（4 passed）。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/ownership_links.py tests/test_ownership_links.py tests/fixtures/procurement/ownership_links
git commit -m "功能：A4 股权关联计算 find_related_parties 与噪声过滤"
```

---

### Task 3: 两个工具 + Domain Pack 维度/工具/章节（A5 接线）

**Files:**
- Modify: `src/deepresearch_agent/tools/procurement.py`（新增两工具）
- Modify: `domains/procurement/domain.yaml`（维度/工具/章节）
- Modify: `tests/test_domain.py`（维度与工具列表）
- Test: `tests/test_tools.py`（若不存在则在本 Task 创建；下方给出新增测试）

**Interfaces:**
- Consumes：Task 1 的 `get_shareholders`/`get_investments`、Task 2 的 `find_related_parties`。
- Produces：工具 `get_ownership_neighborhood`、`get_related_parties`（`read_private`），返回 `{"shareholders":[...],"investments":[...]}` 与 `{"related_parties":[...]}`。

- [ ] **Step 1: 写失败测试（工具）**

在 `tests/test_company_repository.py` 同目录新建/追加到 `tests/test_tools.py`（若文件不存在则创建，含以下内容；若已存在则只追加两个测试函数与必要 import）：

```python
from pathlib import Path

from deepresearch_agent.company_database import build_company_database
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


FIXTURES = Path(__file__).parent / "fixtures" / "procurement" / "ownership_links"

A_CODE = "91110000000000111A"


def _ownership_registry(tmp_path: Path):
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )
    return build_procurement_tool_registry(CompanyRepository(database_path))


def test_get_ownership_neighborhood_tool_returns_shareholders_and_investments(tmp_path):
    registry = _ownership_registry(tmp_path)

    result = registry.run("get_ownership_neighborhood", {"credit_code": A_CODE})

    assert result.status == "ok"
    assert result.permission_tier == "read_private"
    assert [s["shareholder_name"] for s in result.data["shareholders"]]
    assert [i["investee_name"] for i in result.data["investments"]]


def test_get_related_parties_tool_returns_related_parties(tmp_path):
    registry = _ownership_registry(tmp_path)

    result = registry.run("get_related_parties", {"credit_code": A_CODE})

    assert result.status == "ok"
    assert result.permission_tier == "read_private"
    relation_types = {p["relation_type"] for p in result.data["related_parties"]}
    assert "direct_shareholder" in relation_types
    assert "shared_person_shareholder" in relation_types
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_tools.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: FAIL —`KeyError: 'Tool not registered: get_ownership_neighborhood'`。

- [ ] **Step 3: 注册两个工具**

在 `src/deepresearch_agent/tools/procurement.py` 顶部 import 区追加：

```python
from deepresearch_agent.ownership_links import find_related_parties
```

在 `build_procurement_tool_registry` 内、`registry.register(...)` 两段之后追加（`return registry` 之前）：

```python
    def get_ownership_neighborhood(args: dict) -> dict:
        code = args["credit_code"]
        return {
            "shareholders": [r.model_dump(mode="json") for r in repository.get_shareholders(code)],
            "investments": [r.model_dump(mode="json") for r in repository.get_investments(code)],
        }

    def get_related_parties(args: dict) -> dict:
        code = args["credit_code"]
        return {
            "related_parties": [
                r.model_dump(mode="json") for r in find_related_parties(repository, code)
            ]
        }

    registry.register(
        RegisteredTool(
            name="get_ownership_neighborhood",
            description="Return source-backed direct shareholders and outbound investments.",
            permission_tier="read_private",
            handler=get_ownership_neighborhood,
        )
    )
    registry.register(
        RegisteredTool(
            name="get_related_parties",
            description="Return inferred related parties via shared ownership (clues, not conclusions).",
            permission_tier="read_private",
            handler=get_related_parties,
        )
    )
```

- [ ] **Step 4: 更新 Domain Pack**

把 `domains/procurement/domain.yaml` 的三段改为：

```yaml
research_dimensions:
  - company_identity
  - registration
  - capital
  - industry_and_business_scope
  - enterprise_scale
  - contact
  - ownership_structure
  - related_parties
allowed_tools:
  - get_company_profile
  - get_company_contact
  - get_ownership_neighborhood
  - get_related_parties
report_sections:
  - Executive Summary
  - Company Identity
  - Registration
  - Capital
  - Industry and Business Scope
  - Enterprise Scale
  - Contact
  - Ownership Structure
  - Related Parties
  - Evidence Table
  - Open Questions
```

- [ ] **Step 5: 更新 `test_domain.py`**

把 `tests/test_domain.py` 的两处断言改为：

```python
    assert pack.research_dimensions == [
        "company_identity",
        "registration",
        "capital",
        "industry_and_business_scope",
        "enterprise_scale",
        "contact",
        "ownership_structure",
        "related_parties",
    ]
    assert pack.allowed_tools == [
        "get_company_profile",
        "get_company_contact",
        "get_ownership_neighborhood",
        "get_related_parties",
    ]
```

- [ ] **Step 6: 跑工具与 domain 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_tools.py tests/test_domain.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/tools/procurement.py domains/procurement/domain.yaml tests/test_domain.py tests/test_tools.py
git commit -m "功能：A5 注册股权邻域与关联方工具并扩 Domain Pack"
```

---

### Task 4: researcher/writer 接两维度（A5 编排）

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`_DIMENSION_QUESTIONS`、researcher 两段、两个 evidence 构造、writer open_question）
- Modify: `tests/test_nodes.py`（更新"全维度"测试，新增两维度证据测试）

**Interfaces:**
- Consumes：Task 3 的两工具与扩后的 `domain_pack.allowed_tools`/`research_dimensions`；Task 2 的 `RelatedParty` 字段（`related_name`/`relation_type`/`reliability_note`/`confidence`）。
- Produces：researcher 对已解析公司追加 `ownership_structure` 与 `related_parties` 证据（空则各产一条"数据源未提供/未发现"证据）；writer 追加关联方人工复核免责 open_question。

- [ ] **Step 1: 改"全维度"测试 + 加两维度证据测试**

在 `tests/test_nodes.py` 把 `test_researcher_collects_six_source_backed_dimensions` 整体替换为下面的"全维度"版本（更新 trace 断言含四工具），并在其后新增两个测试：

```python
def test_researcher_collects_all_source_backed_dimensions(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(
        state,
        build_procurement_tool_registry(repository),
        DOMAIN_PACK,
    )

    assert {item.dimension for item in updated.evidence} == set(DOMAIN_PACK.research_dimensions)
    assert any("工业设备制造" in item.claim for item in updated.evidence)
    assert all(item.citation.source_id == "company:91330000123456789X" for item in updated.evidence)
    assert {item.tool_name for item in updated.trace} == {
        "get_company_profile",
        "get_company_contact",
        "get_ownership_neighborhood",
        "get_related_parties",
    }


def test_researcher_emits_ownership_fallback_when_no_ownership_data(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="核验示例科技股份有限公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)

    ownership = [e for e in updated.evidence if e.dimension == "ownership_structure"]
    related = [e for e in updated.evidence if e.dimension == "related_parties"]
    assert len(ownership) == 1 and "数据源未提供" in ownership[0].claim
    assert len(related) == 1 and "数据源未发现" in related[0].claim


def test_researcher_emits_related_parties_with_low_confidence_clues(tmp_path):
    from deepresearch_agent.company_database import build_company_database

    fixtures = Path("tests/fixtures/procurement/ownership_links")
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        fixtures / "companies.csv",
        fixtures / "contacts.csv",
        database_path,
        shareholders_csv=fixtures / "shareholders.csv",
        investments_csv=fixtures / "investments.csv",
    )
    repository = _repository(database_path)
    state = planner_node(
        ResearchState(question="核验甲公司", domain="procurement"),
        DOMAIN_PACK,
        repository,
    )

    updated = researcher_node(state, build_procurement_tool_registry(repository), DOMAIN_PACK)

    related = [e for e in updated.evidence if e.dimension == "related_parties"]
    assert related
    person = next(e for e in related if "共同自然人" in e.claim)
    assert person.confidence == 0.2
    assert "须人工复核" in person.claim
    ownership = [e for e in updated.evidence if e.dimension == "ownership_structure"]
    assert any("股东" in e.claim or "对外投资" in e.claim for e in ownership)
```

注：`tests/fixtures/procurement/ownership_links/companies.csv` 含「甲公司」，`planner_node` 用 `resolve_text` 能按名解析（子串匹配）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_researcher_collects_all_source_backed_dimensions -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: FAIL —trace 只含两旧工具（`get_ownership_neighborhood`/`get_related_parties` 未被调用），断言不等。

- [ ] **Step 3: 加 `_DIMENSION_QUESTIONS` 两条 + 关系标签**

在 `src/deepresearch_agent/agents/nodes.py` 的 `_DIMENSION_QUESTIONS` 字典末尾加两条：

```python
    "ownership_structure": "What registered shareholders and outbound investments exist for {supplier_name}?",
    "related_parties": "What related parties can be inferred for {supplier_name} from shared ownership?",
```

在该字典之后新增关系中文标签常量：

```python
_RELATION_LABELS = {
    "direct_shareholder": "直接股东",
    "direct_investee": "直接被投资",
    "shared_corporate_shareholder": "共同企业股东",
    "shared_person_shareholder": "共同自然人(疑似)",
    "shared_investee": "共同对外投资",
}
```

- [ ] **Step 4: researcher 调两工具 + 两个 evidence 构造**

在 `researcher_node` 内 `get_company_contact` 那段之后、`state.iteration += 1` 之前插入：

```python
    if "get_ownership_neighborhood" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_ownership_neighborhood",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_ownership_evidence(state, result.data)

    if "get_related_parties" in domain_pack.allowed_tools:
        result = _run_tool(
            state,
            tools,
            "get_related_parties",
            {"credit_code": state.company_credit_code},
        )
        if result is not None and result.status == "ok":
            _append_related_parties_evidence(state, result.data)
```

在 `_append_contact_evidence` 之后新增两个构造函数：

```python
def _append_ownership_evidence(state: ResearchState, data: dict) -> None:
    appended = False
    for shareholder in data.get("shareholders", []):
        parts = [f"股东：{shareholder['shareholder_name']}"]
        if shareholder.get("shareholder_type"):
            parts.append(f"类型：{shareholder['shareholder_type']}")
        if shareholder.get("shares_held"):
            parts.append(f"持股数：{shareholder['shares_held']}")
        text = "；".join(parts)
        _append_fact(state, "ownership_structure", text, text)
        appended = True
    for investment in data.get("investments", []):
        parts = [f"对外投资：{investment['investee_name']}"]
        if investment.get("status"):
            parts.append(f"状态：{investment['status']}")
        if investment.get("holding_pct"):
            parts.append(f"持股比例：{investment['holding_pct']}")
        text = "；".join(parts)
        _append_fact(state, "ownership_structure", text, text)
        appended = True
    if not appended:
        text = f"数据源未提供 {state.supplier_name} 的股东或对外投资数据。"
        _append_fact(state, "ownership_structure", text, text)


def _append_related_parties_evidence(state: ResearchState, data: dict) -> None:
    parties = data.get("related_parties", [])
    if not parties:
        text = f"数据源未发现 {state.supplier_name} 的可推断关联方。"
        _append_fact(state, "related_parties", text, text)
        return
    for party in parties:
        label = _RELATION_LABELS.get(party["relation_type"], party["relation_type"])
        claim = f"关联方：{party['related_name']}（{label}）。{party['reliability_note']}"
        _append_evidence(
            state,
            Evidence(
                claim=claim,
                dimension="related_parties",
                confidence=party["confidence"],
                citation=Citation(
                    source_id=f"company:{state.company_credit_code}",
                    title=f"{state.supplier_name} 股权关联",
                    url=f"local://companies/{state.company_credit_code}",
                    snippet=party["reliability_note"],
                ),
            ),
        )
```

- [ ] **Step 5: writer 追加关联方免责 open_question**

在 `writer_node` 内，`open_questions.extend([...])` 那段之后、构造 `SupplierReport` 之前插入：

```python
    open_questions.append(
        "股权关联方为线索级推断（尤其同名自然人），须人工复核，不构成控制关系或采购结论。"
    )
```

- [ ] **Step 6: 跑相关测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a45`
Expected: PASS。

- [ ] **Step 7: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-a45-full`
Expected: PASS（在 A3 的 104 passed 基础上净增本次新测试，2 deselected 不变；若有既有用例因维度增加而失败，按本 Task 已列出的更新点排查 `test_graph.py` 的维度集合断言——它断言 `== set(research_dimensions)`，researcher 对空数据产兜底证据后仍覆盖全维度，应通过）。

- [ ] **Step 8: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：A5 researcher 接股权结构与关联方两维度"
```

---

## 自检

**Spec 覆盖**：
- `OwnershipEdge` + 三批量读 → Task 1。
- `RelatedParty`/`RelatedPartyConfig`/`find_related_parties`（四类关系 + 噪声过滤 + 自然人不过滤 + 排序 + 未知码空）→ Task 2。
- 置信度 0.9/0.5/0.25/0.2 与 reliability_note 模板 → Task 2 的 `_RELATION_CONFIDENCE` 与 `_reliability_note`。
- 两工具 + domain.yaml 维度/工具/章节 + test_domain 更新 → Task 3。
- researcher 两段 + 空兜底证据 + `_DIMENSION_QUESTIONS` + writer 免责 + writer 仍 `insufficient_evidence`（未改 writer 的 recommendation）→ Task 4。
- 数据缺失显式产证据（守红线）→ Task 4 的 `_append_ownership_evidence`/`_append_related_parties_evidence` 兜底分支 + 对应测试。

**Placeholder 扫描**：无 TBD/TODO；每个改代码步骤均给完整代码与确切命令/预期。

**类型一致性**：`find_related_parties(repository, code, config) -> list[RelatedParty]` 在 Interfaces/实现/测试一致；`RelatedParty` 字段名（`related_code`/`related_name`/`relation_type`/`via_node_name`/`via_is_person`/`shared_degree`/`confidence`/`reliability_note`）在模型、算法、工具 `model_dump`、researcher 读取（`party["related_name"]` 等）四处一致；`OwnershipEdge`（`company_code`/`node_name`/`node_code`/`is_person`）在 repository 构造与 `find_related_parties` 消费一致；新维度名 `ownership_structure`/`related_parties` 在 domain.yaml、`_DIMENSION_QUESTIONS`、researcher、测试一致。
```
