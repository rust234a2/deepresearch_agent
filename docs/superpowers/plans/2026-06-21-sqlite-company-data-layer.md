# SQLite 企业数据层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以企查查清洗 CSV 为事实标准生成 SQLite 企业库，并让供应商识别、工具和 Agent 只返回数据库中真实存在的工商与联系方式。

**Architecture:** `processed/*.csv` 经构建器校验后原子生成 `derived/companies.sqlite3`；运行时只通过只读 `CompanyRepository` 查询。正式模型严格覆盖数据源，旧能力、合规、财务和采购历史模型及两家演示数据全部移除。

**Tech Stack:** Python 3.11、Pydantic v2、标准库 `csv/sqlite3/hashlib/pathlib`、LangGraph、FastAPI、pytest

---

## 文件结构

- 新建 `company_models.py`：数据源强类型模型。
- 新建 `company_database.py`：CSV 校验、SQLite schema 和原子构建。
- 新建 `company_repository.py`：只读查询、名称解析和模型映射。
- 新建 `scripts/build_company_database.py`：显式构建命令。
- 修改 `state.py`、`supplier_resolution.py`、采购工具、节点和图，删除旧数据结构和运行路径。
- 修改 API、CLI、Domain Pack、测试和文档。

## Task 1：建立数据源强类型模型

**Files:**
- Create: `src/deepresearch_agent/company_models.py`
- Modify: `src/deepresearch_agent/state.py`
- Create: `tests/test_company_models.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import date
from decimal import Decimal

from deepresearch_agent.company_models import CompanyContact, CompanyProfile


def test_company_profile_parses_cleaned_csv_values():
    profile = CompanyProfile.model_validate({
        "source_name": "示例科技",
        "legal_name": "示例科技股份有限公司",
        "registration_status": "存续",
        "unified_social_credit_code": "91330000123456789X",
        "registered_capital_amount": "1000000",
        "registered_capital_currency": "CNY",
        "registered_capital_original": "100万元",
        "paid_in_capital_amount": "",
        "established_date": "2020-01-02",
        "business_term_start": "2020-01-02",
        "business_term_end": "",
        "business_term_indefinite": "true",
        "aliases": "示例设备有限公司|示例机械有限公司",
        "employee_count": "120",
        "business_scope": "工业设备制造；工业设备销售。",
    })
    assert profile.registered_capital_amount == Decimal("1000000")
    assert profile.paid_in_capital_amount is None
    assert profile.established_date == date(2020, 1, 2)
    assert profile.business_term_indefinite is True
    assert profile.aliases == ["示例设备有限公司", "示例机械有限公司"]
    assert profile.employee_count == 120


def test_company_contact_parses_pipe_separated_values():
    contact = CompanyContact.model_validate({
        "unified_social_credit_code": "91330000123456789X",
        "legal_name": "示例科技股份有限公司",
        "phones": "0571-12345678|400-123-4567",
        "emails": "info@example.cn|sales@example.cn",
        "mailing_address": "",
    })
    assert contact.phones == ["0571-12345678", "400-123-4567"]
    assert contact.emails == ["info@example.cn", "sales@example.cn"]
    assert contact.mailing_address is None
```

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_models.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-models-red`

Expected: FAIL，包含 `ModuleNotFoundError: deepresearch_agent.company_models`。

- [ ] **Step 3: 实现模型**

`CompanyProfile` 必须包含设计规格列出的全部 34 个清洗字段。金额为 `Decimal | None`，日期为 `date | None`，人数和年份为 `int | None`，无固定期限为 `bool`，别名为 `list[str]`。实现以下公共模型和转换器：

```python
def none_if_blank(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def split_pipe(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split("|") if item.strip()]


class CompanyProfile(BaseModel):
    source_name: str
    legal_name: str
    registration_status: str | None = None
    unified_social_credit_code: str
    legal_representative: str | None = None
    company_type: str | None = None
    registered_capital_amount: Decimal | None = None
    registered_capital_currency: str | None = None
    registered_capital_original: str | None = None
    paid_in_capital_amount: Decimal | None = None
    paid_in_capital_currency: str | None = None
    paid_in_capital_original: str | None = None
    established_date: date | None = None
    business_term_start: date | None = None
    business_term_end: date | None = None
    business_term_indefinite: bool = False
    registered_address: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    registration_authority: str | None = None
    gb_industry_section: str | None = None
    gb_industry_division: str | None = None
    gb_industry_group: str | None = None
    gb_industry_class: str | None = None
    enterprise_size: str | None = None
    business_scope: str | None = None
    aliases: list[str] = Field(default_factory=list)
    english_name: str | None = None
    website: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    employee_count_report_year: int | None = Field(default=None, ge=1900)
    latest_annual_report_year: int | None = Field(default=None, ge=1900)
    taxpayer_qualification: str | None = None

    @field_validator("aliases", mode="before")
    @classmethod
    def parse_aliases(cls, value: object) -> list[str]:
        return split_pipe(value)

    @field_validator(
        "registration_status", "legal_representative", "company_type",
        "registered_capital_amount", "registered_capital_currency",
        "registered_capital_original", "paid_in_capital_amount",
        "paid_in_capital_currency", "paid_in_capital_original",
        "established_date", "business_term_start", "business_term_end",
        "registered_address", "province", "city", "district",
        "registration_authority", "gb_industry_section", "gb_industry_division",
        "gb_industry_group", "gb_industry_class", "enterprise_size",
        "business_scope", "english_name", "website", "employee_count",
        "employee_count_report_year", "latest_annual_report_year",
        "taxpayer_qualification", mode="before",
    )
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)


class CompanyContact(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    mailing_address: str | None = None

    @field_validator("phones", "emails", mode="before")
    @classmethod
    def parse_multi_values(cls, value: object) -> list[str]:
        return split_pipe(value)

    @field_validator("mailing_address", mode="before")
    @classmethod
    def parse_mailing_address(cls, value: object) -> object:
        return none_if_blank(value)


class CompanyRecord(BaseModel):
    profile: CompanyProfile
    contact: CompanyContact | None = None


class CompanyResolutionCandidate(BaseModel):
    legal_name: str
    unified_social_credit_code: str


class CompanyResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    legal_name: str | None = None
    unified_social_credit_code: str | None = None
    matched_text: str | None = None
    match_type: Literal["legal_name", "alias"] | None = None
    candidates: list[CompanyResolutionCandidate] = Field(default_factory=list)
```

从 `state.py` 删除旧 `CompanyProfile`、`SupplierCapability`、`ComplianceProfile`、`FinancialProfile`、`ProcurementHistory`、`SupplierDueDiligenceProfile`，并把 `ResearchState.supplier_resolution` 类型改为 `CompanyResolution | None`。

- [ ] **Step 4: 更新状态测试并验证绿灯**

删除 `tests/test_state.py` 中旧模型导入和旧尽调组合模型测试。

Run: `.\.conda-env\python.exe -m pytest tests/test_company_models.py tests/test_state.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-models-green`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/state.py tests/test_company_models.py tests/test_state.py
git commit -m "重构：以工商数据源重建企业模型"
```

## Task 2：实现可原子重建的 SQLite 构建器

**Files:**
- Create: `src/deepresearch_agent/company_database.py`
- Create: `tests/test_company_database.py`
- Create: `tests/fixtures/procurement/companies.csv`
- Create: `tests/fixtures/procurement/contacts.csv`

- [ ] **Step 1: 写失败测试**

创建两份 UTF-8-SIG 合成 fixture，表头分别严格等于 `CORE_COLUMNS` 和 `CONTACT_COLUMNS`，内容使用 Task 1 的示例科技数据。成功路径直接读取 fixture；失败路径复制后只改变一个变量。调用 `build_company_database()` 后断言：

```python
connection = sqlite3.connect(database_path)
assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
assert connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
assert connection.execute("SELECT COUNT(*) FROM company_aliases").fetchone()[0] == 2
assert connection.execute("SELECT COUNT(*) FROM company_contacts").fetchone()[0] == 1
assert connection.execute("SELECT company_count FROM import_metadata").fetchone()[0] == 1
```

另外覆盖空企业集、重复信用代码、孤立联系方式、联系方式法定名称不一致和错误表头，全部断言错误包含源文件及 CSV 行号。预先写入一个可查询的旧目标数据库，再触发失败构建，断言旧目标 SHA-256 不变，证明原子替换有效。

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-db-red`

Expected: FAIL，包含构建模块或函数不存在。

- [ ] **Step 3: 实现 schema 和构建流程**

公开接口：

```python
SCHEMA_VERSION = 1

def normalize_company_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def build_company_database(
    companies_csv: str | Path,
    contacts_csv: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    companies = read_and_validate_companies(Path(companies_csv))
    contacts = read_and_validate_contacts(Path(contacts_csv), companies)
    build_atomic_database(companies, contacts, Path(output_path))
    return {"companies": len(companies), "contacts": len(contacts)}
```

SQLite 固定创建 `companies`、`company_aliases`、`company_contacts`、`import_metadata`。`companies` 除 aliases 外覆盖 `CORE_COLUMNS`，信用代码为主键，法定名称和规范化名称非空，规范化法定名称唯一。别名表外键到企业并设置企业内唯一约束。联系方式以信用代码为主键和外键。

固定索引：登记状态、省市、国标行业大类、企业规模、规范化别名。设置 `PRAGMA foreign_keys = ON` 和 `PRAGMA user_version = 1`。元数据写入两个 SHA-256、输入/导入计数和 UTC 生成时间。

每行先通过 `CompanyProfile.model_validate()` 或 `CompanyContact.model_validate()`；异常包装为 `ValueError(f"{path}:{line_number}: {error}")`。临时路径为 `output.with_suffix(output.suffix + ".tmp")`；只删除旧临时文件，事务成功并关闭连接后用 `temp.replace(output)`，失败时删除临时文件但保留旧目标。

- [ ] **Step 4: 验证绿灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-db-green`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/company_database.py tests/test_company_database.py tests/fixtures/procurement/companies.csv tests/fixtures/procurement/contacts.csv
git commit -m "功能：增加SQLite企业数据库构建器"
```

## Task 3：实现只读 CompanyRepository

**Files:**
- Create: `src/deepresearch_agent/company_repository.py`
- Create: `tests/test_company_repository.py`

- [ ] **Step 1: 写失败测试**

```python
record = repository.get_by_credit_code("91330000123456789X")
assert record.profile.legal_name == "示例科技股份有限公司"
assert record.profile.business_scope == "工业设备制造；工业设备销售。"
assert record.contact.phones == ["0571-12345678", "400-123-4567"]

resolved = repository.resolve_text("请核验示例设备有限公司的工商信息")
assert resolved.status == "resolved"
assert resolved.match_type == "alias"
assert resolved.unified_social_credit_code == "91330000123456789X"

unknown = repository.resolve_text("请核验不存在公司")
assert unknown.status == "not_found"
```

增加共享别名歧义、数据库不存在和 schema version 不支持测试。

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-repo-red`

Expected: FAIL，包含 Repository 模块不存在。

- [ ] **Step 3: 实现只读 Repository**

```python
class CompanyRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(
                f"Company database not found: {self.database_path}. "
                "Run scripts/build_company_database.py first."
            )
        connection = sqlite3.connect(
            f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            connection.close()
            raise RuntimeError(
                f"Unsupported company database schema {version}; expected {SCHEMA_VERSION}. Rebuild it."
            )
        return connection
```

实现 `get_by_credit_code()`：查询企业、别名和可选联系方式，移除内部 `normalized_legal_name` 后构造 `CompanyRecord`。实现 `get_contact()`：复用信用代码查询。实现 `resolve_text()`：一次读取全部法定名称和别名；英文名称使用字母数字边界，中文使用子串；同企业命中多个名称时保留最长名称，同长度优先法定名称；零/一/多企业分别返回 `not_found/resolved/ambiguous`。

- [ ] **Step 4: 验证绿灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-repo-green`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：增加只读企业Repository"
```

## Task 4：增加构建命令并迁移数据目录

**Files:**
- Create: `scripts/build_company_database.py`
- Create: `tests/test_company_database_cli.py`
- Modify: `.gitignore`
- Move locally: `data/procurement/cleaned/*` -> `data/procurement/processed/*`
- Move locally: `data/procurement/candidates/*.xlsx` -> `data/procurement/raw/*`

- [ ] **Step 1: 写失败测试**

调用 `main(["--companies", companies, "--contacts", contacts, "--output", database])`，断言数据库存在且输出等于 `companies=1 contacts=1`。

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-db-cli-red`

Expected: FAIL，包含构建脚本模块不存在。

- [ ] **Step 3: 实现 CLI**

```python
from __future__ import annotations

import argparse

from deepresearch_agent.company_database import build_company_database


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the local SQLite company database.")
    parser.add_argument("--companies", default="data/procurement/processed/companies.csv")
    parser.add_argument("--contacts", default="data/procurement/processed/contacts.csv")
    parser.add_argument("--output", default="data/procurement/derived/companies.sqlite3")
    args = parser.parse_args(argv)
    summary = build_company_database(args.companies, args.contacts, args.output)
    print(f"companies={summary['companies']} contacts={summary['contacts']}")


if __name__ == "__main__":
    main()
```

`.gitignore` 增加 `data/procurement/raw/`、`data/procurement/processed/`、`data/procurement/derived/`，移除旧 `cleaned/` 规则。

- [ ] **Step 4: 验证绿灯并迁移真实数据**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-db-cli-green`

Expected: PASS。

迁移前逐个确认目标不存在；若目标存在则比较 SHA-256，内容不同就停止，禁止覆盖。

```powershell
New-Item -ItemType Directory -Force data/procurement/processed
New-Item -ItemType Directory -Force data/procurement/raw
Move-Item data/procurement/cleaned/companies.csv data/procurement/processed/companies.csv
Move-Item data/procurement/cleaned/contacts.csv data/procurement/processed/contacts.csv
Move-Item data/procurement/cleaned/rejected.csv data/procurement/processed/rejected.csv
Get-ChildItem data/procurement/candidates -Filter *.xlsx | Move-Item -Destination data/procurement/raw
```

- [ ] **Step 5: 提交**

```powershell
git add scripts/build_company_database.py tests/test_company_database_cli.py .gitignore
git commit -m "功能：增加企业数据库构建命令"
```

## Task 5：把识别和采购工具迁移到 Repository

**Files:**
- Modify: `src/deepresearch_agent/supplier_resolution.py`
- Modify: `src/deepresearch_agent/tools/procurement.py`
- Modify: `tests/test_supplier_resolution.py`
- Modify: `tests/test_tools.py`
- Delete: `src/deepresearch_agent/data_loader.py`
- Delete: `tests/test_data_loader.py`

- [ ] **Step 1: 重写失败测试**

供应商识别测试注入临时 Repository，覆盖法定名称、曾用名、未知和共享别名歧义。工具测试使用：

```python
registry = build_procurement_tool_registry(repository)
profile = registry.run("get_company_profile", {"credit_code": "91330000123456789X"})
assert profile.status == "ok"
assert profile.data["legal_name"] == "示例科技股份有限公司"
assert profile.data["business_scope"] == "工业设备制造；工业设备销售。"
assert "products" not in profile.data
assert "certifications" not in profile.data

contact = registry.run("get_company_contact", {"credit_code": "91330000123456789X"})
assert contact.data["phones"] == ["0571-12345678", "400-123-4567"]
```

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_supplier_resolution.py tests/test_tools.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-tools-red`

Expected: FAIL，包含新参数或新工具名不存在。

- [ ] **Step 3: 实现 Repository 注入**

```python
def resolve_supplier(question: str, repository: CompanyRepository) -> CompanyResolution:
    return repository.resolve_text(question)
```

```python
def build_procurement_tool_registry(repository: CompanyRepository) -> ToolRegistry:
    registry = ToolRegistry()

    def get_profile(args: dict) -> dict:
        record = repository.get_by_credit_code(args["credit_code"])
        if record is None:
            raise ValueError(f"Unknown company credit code: {args['credit_code']}")
        return record.profile.model_dump(mode="json")

    def get_contact(args: dict) -> dict:
        contact = repository.get_contact(args["credit_code"])
        if contact is None:
            raise ValueError(f"No contact data for company: {args['credit_code']}")
        return contact.model_dump(mode="json")

    registry.register(RegisteredTool(
        name="get_company_profile",
        description="Return source-backed Chinese company registration data.",
        permission_tier="read_local",
        handler=get_profile,
    ))
    registry.register(RegisteredTool(
        name="get_company_contact",
        description="Return source-backed company contact data.",
        permission_tier="read_local",
        handler=get_contact,
    ))
    return registry
```

删除旧 loader 和所有旧工具引用。

- [ ] **Step 4: 验证绿灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_supplier_resolution.py tests/test_tools.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-tools-green`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/supplier_resolution.py src/deepresearch_agent/tools/procurement.py tests/test_supplier_resolution.py tests/test_tools.py
git rm src/deepresearch_agent/data_loader.py tests/test_data_loader.py
git commit -m "重构：让企业识别和工具使用SQLite"
```

## Task 6：迁移 Domain Pack、节点和 LangGraph

**Files:**
- Modify: `domains/procurement/domain.yaml`
- Modify: `src/deepresearch_agent/agents/nodes.py`
- Modify: `src/deepresearch_agent/agents/graph.py`
- Modify: `src/deepresearch_agent/state.py`
- Modify: `tests/test_domain.py`
- Modify: `tests/test_nodes.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: 写 SQLite 端到端失败测试**

```python
final_state = run_research(
    "核验示例科技股份有限公司的工商和经营范围",
    database_path=database_path,
)
assert final_state.report.supplier_name == "示例科技股份有限公司"
assert final_state.report.recommendation == "insufficient_evidence"
assert {item.dimension for item in final_state.evidence} == {
    "company_identity", "registration", "capital",
    "industry_and_business_scope", "enterprise_scale", "contact",
}
assert "工业设备制造" in " ".join(item.claim for item in final_state.evidence)
assert not any("未发现风险" in line for line in final_state.report.risks)
```

保留未知和歧义测试，但改用合成中文企业和临时数据库。

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_domain.py tests/test_nodes.py tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-graph-red`

Expected: FAIL，显示旧维度、旧工具或 `database_path` 参数不匹配。

- [ ] **Step 3: 更新 Domain Pack**

```yaml
name: procurement
description: Source-backed Chinese company registration research for procurement.
research_dimensions:
  - company_identity
  - registration
  - capital
  - industry_and_business_scope
  - enterprise_scale
  - contact
allowed_tools:
  - get_company_profile
  - get_company_contact
report_sections:
  - Executive Summary
  - Company Identity
  - Registration
  - Capital
  - Industry and Business Scope
  - Enterprise Scale
  - Contact
  - Evidence Table
  - Open Questions
source_priority:
  - local_company_registration_data
hitl_policy:
  high_risk_recommendation: false
  missing_compliance_evidence: false
  conflicting_claims: true
```

- [ ] **Step 4: 重写节点行为**

给 `ResearchState` 增加 `company_credit_code: str | None`。`planner_node` 注入 Repository，通过 `resolve_supplier` 设置法定名称和信用代码。`researcher_node` 删除 `LocalDocumentRetriever` 参数，只调用两个新工具；按字段组生成身份、登记、资本、行业与经营范围、企业规模和联系方式证据。字段缺失时不生成对应证据，经营范围 claim 使用原文。

所有 citation 使用：

```python
Citation(
    source_id=f"company:{state.company_credit_code}",
    title=f"{state.supplier_name} 工商数据",
    url=f"local://companies/{state.company_credit_code}",
    snippet=source_text,
)
```

已解析企业的 writer 固定返回 `insufficient_evidence`，风险说明固定为：

```text
当前数据源不包含制裁、司法、负面新闻、财务和采购履约数据，不能据此作出采购批准或风险结论。
```

开放问题先列当前研究维度中实际缺失的字段组，再固定列出制裁、司法与负面新闻、财务、产能交期和采购履约五类未接入数据；不得写“未发现风险”。

- [ ] **Step 5: 修改 graph 注入数据库**

```python
DEFAULT_DATABASE_PATH = Path("data/procurement/derived/companies.sqlite3")

def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    repository = CompanyRepository(database_path)
    app = build_graph(domain_pack, repository)
    result = app.invoke(ResearchState(question=question, domain=domain))
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)
```

`build_graph(domain_pack, repository)` 用 Repository 构建工具并注入 planner；保留现有入口点、条件边、循环和 `END` 边。

- [ ] **Step 6: 验证绿灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_domain.py tests/test_nodes.py tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-graph-green`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add domains/procurement/domain.yaml src/deepresearch_agent/agents/nodes.py src/deepresearch_agent/agents/graph.py src/deepresearch_agent/state.py tests/test_domain.py tests/test_nodes.py tests/test_graph.py
git commit -m "重构：让研究图基于工商数据生成证据"
```

## Task 7：更新 API、CLI、演示数据和文档

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Modify: `src/deepresearch_agent/cli.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_retrieval.py`
- Delete: `data/procurement/suppliers.json`
- Delete: `data/procurement/documents/acme-sensors.md`
- Delete: `data/procurement/documents/northstar-components.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: 写入口失败测试**

```python
client = TestClient(create_app(database_path))
response = client.post(
    "/research",
    json={"question": "核验示例科技股份有限公司"},
)
assert response.status_code == 200
assert response.json()["supplier_name"] == "示例科技股份有限公司"
assert response.json()["recommendation"] == "insufficient_evidence"
```

CLI 测试调用 `main(["核验示例科技股份有限公司", "--database", str(database_path)])`，断言输出包含企业名、`insufficient_evidence` 和 Evidence。

- [ ] **Step 2: 验证红灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_api.py tests/test_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-entry-red`

Expected: FAIL，包含 `create_app` 或 `--database` 不存在。

- [ ] **Step 3: 实现 API app factory 和 CLI 参数**

```python
def create_app(database_path: str | Path = DEFAULT_DATABASE_PATH) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")

    @application.post("/research", response_model=SupplierReport)
    def research(request: ResearchRequest) -> SupplierReport:
        state = run_research(
            request.question,
            domain=request.domain,
            database_path=database_path,
        )
        if state.report is None:
            raise RuntimeError("research graph completed without a report")
        return state.report

    return application


app = create_app()
```

CLI 增加：

```python
parser.add_argument(
    "--database",
    default="data/procurement/derived/companies.sqlite3",
    help="Path to the generated SQLite company database.",
)
state = run_research(args.question, database_path=args.database)
```

- [ ] **Step 4: 删除演示数据并更新文档**

README 写明 CSV 是事实源、SQLite 是派生产物、构建命令、当前支持字段和明确不支持的数据。架构图删除 `suppliers.json`、英文文档、旧工具和 sanctions 流程，增加 processed CSV、SQLite、Repository 和两个新工具。`tests/test_retrieval.py` 改为只使用 `tmp_path` 合成 Markdown，不依赖被删文件。

- [ ] **Step 5: 验证绿灯**

Run: `.\.conda-env\python.exe -m pytest tests/test_api.py tests/test_cli.py tests/test_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-entry-green`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/api.py src/deepresearch_agent/cli.py tests/test_api.py tests/test_cli.py tests/test_retrieval.py README.md docs/architecture.md
git rm data/procurement/suppliers.json data/procurement/documents/acme-sensors.md data/procurement/documents/northstar-components.md
git commit -m "文档：切换到SQLite企业数据运行路径"
```

## Task 8：真实数据构建、全量验收和项目记忆

**Files:**
- Modify: `docs/project-memory.md`

- [ ] **Step 1: 用真实 processed CSV 构建数据库**

Run: `.\.conda-env\python.exe scripts/build_company_database.py`

Expected: `companies=3506 contacts=3506`，退出码 0。

- [ ] **Step 2: 验证万马科技法定名称、曾用名和经营范围**

Run:

```powershell
.\.conda-env\python.exe -c "from deepresearch_agent.company_repository import CompanyRepository; r=CompanyRepository('data/procurement/derived/companies.sqlite3'); x=r.resolve_text('核验万马电子医疗有限公司'); assert x.status=='resolved'; rec=r.get_by_credit_code(x.unified_social_credit_code); assert rec.profile.legal_name=='万马科技股份有限公司'; assert rec.profile.business_scope and '通信设备制造' in rec.profile.business_scope; print(rec.profile.legal_name, len(rec.profile.business_scope))"
```

Expected: 输出 `万马科技股份有限公司` 和大于 0 的经营范围长度。

- [ ] **Step 3: 运行完整验证**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-sqlite-final`

Expected: 全部测试 PASS。

Run: `git diff --check`

Expected: 退出码 0。

- [ ] **Step 4: 更新项目记忆**

记录正式模型已切换为企查查字段、SQLite schema version 1、真实库计数、旧模型和演示数据已删除、经营范围保留原文、分块和中文 FTS5 未实施，以及构建和测试命令。

- [ ] **Step 5: 提交验收文档**

```powershell
git add docs/project-memory.md
git commit -m "文档：记录SQLite企业数据层状态"
```

- [ ] **Step 6: 检查最终工作树**

Run: `git status --short --ignored`

Expected: 无未提交的跟踪文件；`processed/`、`derived/companies.sqlite3` 和测试临时目录均为 ignored。
