# 模块 A3：Repository 股权读层实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `CompanyRepository` 上加 `get_shareholders(code)` / `get_investments(code)` 两个只读方法，把 A2 入库的两张股权边表按公司信用代码读出为 Pydantic 记录。

**Architecture:** 与现有 `get_scope_chunks` / `ScopeChunkRecord` 同构——新增两个 Pydantic 记录模型，两个仓库方法走现有只读 `_connect()`，按 `unified_social_credit_code` 过滤、`ORDER BY id` 取行、`model_validate` 成列表。纯读层，不接图、不接 Agent。

**Tech Stack:** Python 3.11、Pydantic v2、SQLite（标准库 `sqlite3`）、pytest。仓库内 conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **原文透传**：除 `shareholder_is_person`（TEXT `"true"/"false"` → `bool`）外，所有股权字段 `str | None`，不解析百分比/日期/金额。
- **空串转 None**：A2 把空单元格存为 `""`（非 NULL），所有可空 `str | None` 字段用 `none_if_blank`（已在 `company_models.py` 定义）转 `None`。
- **确定性**：读取 `ORDER BY id`（= 入库顺序 = 源 CSV 顺序）。
- **不暴露内部列**：返回记录不含 `id`、`normalized_shareholder_name`、`normalized_investee_name`；SELECT 显式列出要暴露的列。
- **复用 `_connect()`**：库不存在 / schema 不匹配由它抛 `FileNotFoundError` / `RuntimeError`；A3 不新增错误路径。
- **未知/无边 code → `[]`**：不区分"公司不在库"与"公司无该类边"。
- 测试解释器：`.\.conda-env\python.exe -m pytest`。每个 Task 完成后提交，提交信息用中文。

---

### Task 1: 股东读路径（`ShareholderRecord` + `get_shareholders`）

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`（新增 `ShareholderRecord`）
- Modify: `src/deepresearch_agent/company_repository.py`（导入 `ShareholderRecord`；新增 `get_shareholders`）
- Test: `tests/test_company_repository.py`（新增 `_build_database_with_ownership` helper + 2 个测试）

**Interfaces:**
- Consumes:
  - `build_company_database(companies_csv, contacts_csv, output_path, shareholders_csv=None, investments_csv=None)`（A2 已实现）。
  - fixture：`tests/fixtures/procurement/shareholders.csv`（3 行：张三=自然人、示例科技=企业法人、不存在公司=锚点不可解析被跳过 → 示例科技得 2 条边）。
  - `none_if_blank`（`company_models.py` 顶部已定义）。
- Produces:
  - `ShareholderRecord`：字段 `unified_social_credit_code: str`、`shareholder_name: str`、`shareholder_credit_code: str | None`、`shareholder_type: str | None`、`shareholder_is_person: bool`、`share_class: str | None`、`shares_held: str | None`、`indirect_holding_pct: str | None`、`associated_product: str | None`。
  - `CompanyRepository.get_shareholders(self, code: str) -> list[ShareholderRecord]`。
  - `_build_database_with_ownership(tmp_path: Path) -> Path`（测试 helper，Task 2 复用）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 顶部 import 处加入 `ShareholderRecord`（与现有 import 同段）：

```python
from deepresearch_agent.company_repository import CompanyRepository
```

保持不变，在文件中新增 helper 与测试（放在现有 `_build_database` 之后）：

```python
def _build_database_with_ownership(tmp_path: Path) -> Path:
    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )
    return database_path


def test_get_shareholders_returns_ordered_records_with_person_flag(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    records = repository.get_shareholders("91330000123456789X")

    assert len(records) == 2
    person = records[0]
    assert person.shareholder_name == "张三"
    assert person.shareholder_is_person is True
    assert person.shareholder_credit_code is None
    assert person.share_class == "流通A股"
    assert person.shares_held == "1000"
    assert person.indirect_holding_pct is None
    entity = records[1]
    assert entity.shareholder_type == "企业法人"
    assert entity.shareholder_is_person is False
    assert entity.shareholder_credit_code == "91330000123456789X"


def test_get_shareholders_returns_empty_for_unknown_and_edgeless(tmp_path):
    owned_dir = tmp_path / "owned"
    owned_dir.mkdir()
    with_ownership = CompanyRepository(_build_database_with_ownership(owned_dir))
    assert with_ownership.get_shareholders("missing-code") == []

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    without_ownership = CompanyRepository(_build_database(plain_dir))
    assert without_ownership.get_shareholders("91330000123456789X") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_get_shareholders_returns_ordered_records_with_person_flag -q`
Expected: FAIL —`AttributeError: 'CompanyRepository' object has no attribute 'get_shareholders'`（以及 `ImportError`/`NameError` 若模型未定义）。

- [ ] **Step 3: 加 `ShareholderRecord` 模型**

在 `src/deepresearch_agent/company_models.py` 末尾（`ScopeIndexMetadata` 之后）追加：

```python
class ShareholderRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    unified_social_credit_code: str
    shareholder_name: str
    shareholder_credit_code: str | None = None
    shareholder_type: str | None = None
    shareholder_is_person: bool
    share_class: str | None = None
    shares_held: str | None = None
    indirect_holding_pct: str | None = None
    associated_product: str | None = None

    @field_validator("shareholder_is_person", mode="before")
    @classmethod
    def parse_is_person(cls, value: object) -> bool:
        return value is True or value == "true"

    @field_validator(
        "shareholder_credit_code",
        "shareholder_type",
        "share_class",
        "shares_held",
        "indirect_holding_pct",
        "associated_product",
        mode="before",
    )
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)
```

（`BaseModel`、`ConfigDict`、`field_validator`、`none_if_blank` 均已在文件顶部 import/定义，无需新增 import。）

- [ ] **Step 4: 加 `get_shareholders` 方法**

在 `src/deepresearch_agent/company_repository.py` 的 import 块里，把 `ShareholderRecord` 加进从 `company_models` 的导入列表（按字母/就近插入，与现有多行 import 同段）：

```python
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
    ScopeChunkRecord,
    ScopeIndexMetadata,
    ShareholderRecord,
)
```

在 `get_scope_index_metadata` 方法之后、`class` 内新增方法：

```python
    def get_shareholders(self, code: str) -> list[ShareholderRecord]:
        normalized_code = code.strip()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, shareholder_name, "
                "shareholder_credit_code, shareholder_type, shareholder_is_person, "
                "share_class, shares_held, indirect_holding_pct, associated_product "
                "FROM company_shareholders "
                "WHERE unified_social_credit_code = ? ORDER BY id",
                (normalized_code,),
            ).fetchall()
        return [ShareholderRecord.model_validate(dict(row)) for row in rows]
```

- [ ] **Step 5: 跑两个测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_get_shareholders_returns_ordered_records_with_person_flag tests/test_company_repository.py::test_get_shareholders_returns_empty_for_unknown_and_edgeless -q`
Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：Repository 加 get_shareholders 读股东边"
```

---

### Task 2: 对外投资读路径（`InvestmentRecord` + `get_investments`）

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`（新增 `InvestmentRecord`）
- Modify: `src/deepresearch_agent/company_repository.py`（导入 `InvestmentRecord`；新增 `get_investments`）
- Test: `tests/test_company_repository.py`（新增 2 个测试，复用 Task 1 的 `_build_database_with_ownership`）

**Interfaces:**
- Consumes:
  - `_build_database_with_ownership`（Task 1 新增）。
  - fixture：`tests/fixtures/procurement/investments.csv`（3 行：示例科技=可解析、某外部子公司=未解析、不存在公司=锚点被跳过 → 示例科技得 2 条边）。
- Produces:
  - `InvestmentRecord`：字段 `unified_social_credit_code: str`、`investee_name: str`、`investee_credit_code: str | None`、`status: str | None`、`investee_established_date: str | None`、`holding_pct: str | None`、`subscribed_capital_amount: str | None`、`subscribed_capital_currency: str | None`、`subscribed_capital_original: str | None`、`final_beneficiary_pct: str | None`、`region: str | None`、`industry: str | None`、`associated_product: str | None`。
  - `CompanyRepository.get_investments(self, code: str) -> list[InvestmentRecord]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾追加：

```python
def test_get_investments_returns_records_with_resolution(tmp_path):
    repository = CompanyRepository(_build_database_with_ownership(tmp_path))

    records = repository.get_investments("91330000123456789X")

    assert len(records) == 2
    resolved = records[0]
    assert resolved.investee_name == "示例科技股份有限公司"
    assert resolved.investee_credit_code == "91330000123456789X"
    assert resolved.status == "存续"
    assert resolved.holding_pct == "100%"
    external = records[1]
    assert external.investee_name == "某外部子公司有限公司"
    assert external.investee_credit_code is None
    assert external.status == "注销"
    assert external.subscribed_capital_original == "500万元"


def test_get_investments_returns_empty_for_unknown_and_edgeless(tmp_path):
    owned_dir = tmp_path / "owned"
    owned_dir.mkdir()
    with_ownership = CompanyRepository(_build_database_with_ownership(owned_dir))
    assert with_ownership.get_investments("missing-code") == []

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    without_ownership = CompanyRepository(_build_database(plain_dir))
    assert without_ownership.get_investments("91330000123456789X") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_get_investments_returns_records_with_resolution -q`
Expected: FAIL —`AttributeError: 'CompanyRepository' object has no attribute 'get_investments'`。

- [ ] **Step 3: 加 `InvestmentRecord` 模型**

在 `src/deepresearch_agent/company_models.py` 末尾（`ShareholderRecord` 之后）追加：

```python
class InvestmentRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    unified_social_credit_code: str
    investee_name: str
    investee_credit_code: str | None = None
    status: str | None = None
    investee_established_date: str | None = None
    holding_pct: str | None = None
    subscribed_capital_amount: str | None = None
    subscribed_capital_currency: str | None = None
    subscribed_capital_original: str | None = None
    final_beneficiary_pct: str | None = None
    region: str | None = None
    industry: str | None = None
    associated_product: str | None = None

    @field_validator(
        "investee_credit_code",
        "status",
        "investee_established_date",
        "holding_pct",
        "subscribed_capital_amount",
        "subscribed_capital_currency",
        "subscribed_capital_original",
        "final_beneficiary_pct",
        "region",
        "industry",
        "associated_product",
        mode="before",
    )
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)
```

- [ ] **Step 4: 加 `get_investments` 方法**

在 `src/deepresearch_agent/company_repository.py` 的 `company_models` 导入列表里加 `InvestmentRecord`（与 Task 1 加的 `ShareholderRecord` 同段）：

```python
from deepresearch_agent.company_models import (
    CompanyContact,
    CompanyProfile,
    CompanyRecord,
    CompanyResolution,
    CompanyResolutionCandidate,
    InvestmentRecord,
    ScopeChunkRecord,
    ScopeIndexMetadata,
    ShareholderRecord,
)
```

在 `get_shareholders` 方法之后新增：

```python
    def get_investments(self, code: str) -> list[InvestmentRecord]:
        normalized_code = code.strip()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, investee_name, investee_credit_code, "
                "status, investee_established_date, holding_pct, subscribed_capital_amount, "
                "subscribed_capital_currency, subscribed_capital_original, "
                "final_beneficiary_pct, region, industry, associated_product "
                "FROM company_investments "
                "WHERE unified_social_credit_code = ? ORDER BY id",
                (normalized_code,),
            ).fetchall()
        return [InvestmentRecord.model_validate(dict(row)) for row in rows]
```

- [ ] **Step 5: 跑两个测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_get_investments_returns_records_with_resolution tests/test_company_repository.py::test_get_investments_returns_empty_for_unknown_and_edgeless -q`
Expected: PASS（2 passed）。

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q`
Expected: PASS（在原 100 passed 基础上 +4 = 104 passed, 2 deselected）。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：Repository 加 get_investments 读对外投资边"
```

---

## 自检

**Spec 覆盖**：
- `ShareholderRecord` / `InvestmentRecord` 模型 → Task 1 Step 3 / Task 2 Step 3。
- `get_shareholders` / `get_investments` 方法（`ORDER BY id`、显式列、`_connect`）→ Task 1 Step 4 / Task 2 Step 4。
- 原文透传 + `shareholder_is_person` → bool → 两个模型的 validator。
- 空串经 `none_if_blank` 转 None → 两个模型的 `parse_blanks` validator。
- 不暴露 `id`/`normalized_*` → 两个 SELECT 的显式列清单（未含这些列）。
- 未知/无边 → `[]`：spec 测试 3 → 拆成 Task 1 Step 1 与 Task 2 Step 1 的两个 `_empty_` 测试，分别覆盖两方法的"未知 code"与"无股权数据建库的公司"两种情形。
- 复用现有 fixture + `build_company_database(..., shareholders_csv=, investments_csv=)` → `_build_database_with_ownership` helper。

**Placeholder 扫描**：无 TBD/TODO；每个改代码步骤都给了完整代码与确切命令/预期。

**类型一致性**：`get_shareholders -> list[ShareholderRecord]`、`get_investments -> list[InvestmentRecord]` 在 Interfaces 与实现步骤中一致；模型字段名与 A2 表列名（`company_database.py` 的 `_insert_shareholders` / `_insert_investments`）逐一对应；`shareholder_is_person` 在表中为 TEXT、模型中为 `bool`，由 validator 桥接。
