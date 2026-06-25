# 模块 A2：股权边表入库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 A1 清洗的 shareholders/investments 接进 SQLite——新增两张边表，按规范化名称解析锚点与对手方，集成进 `build_company_database` 单次原子构建，schema 升 v3。

**Architecture:** 先做 schema v3 迁移（空的两张边表 + `import_metadata` 扩展），再加可选 CSV 入参、内存名称索引解析、逐边入库。锚点解析不到则跳过并计数；对手方解析为可空信用代码，自然人不解析。

**Tech Stack:** Python 3.11、SQLite、pytest。

## Global Constraints

- 解释器固定 `.\.conda-env\python.exe`，不新建 venv。
- 入库列全部 TEXT（与 companies 表一致）。
- 测试用合成 fixture，不依赖真实数据。
- `SCHEMA_VERSION` 升 3；改 schema 必须同步 `SCHEMA_VERSION` 与 `_create_schema`。
- `processed/` Git 忽略；fixture 可提交。
- 每个 Task 末尾提交一次，提交信息用中文。

---

## File Structure

修改：
- `src/deepresearch_agent/company_database.py` — `SCHEMA_VERSION=3`、新表与索引、`import_metadata` 扩展、`build_company_database` 入参、名称解析与入库。
- `scripts/build_company_database.py` — 加 `--shareholders` / `--investments`。
- `tests/test_company_database.py` — 适配 v3、新增入库用例。
- `tests/test_company_repository.py` — schema 拒绝用例改 v3。

新建：
- `tests/fixtures/procurement/shareholders.csv`、`tests/fixtures/procurement/investments.csv`。

---

## Task 1: schema v3 迁移（空边表）

**Files:**
- Modify: `src/deepresearch_agent/company_database.py`
- Modify: `tests/test_company_database.py`
- Modify: `tests/test_company_repository.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION == 3`；表 `company_shareholders` / `company_investments`（空）+ 索引；`import_metadata` 含 `shareholders_sha256`/`investments_sha256`/`shareholder_count`/`investment_count`。

- [ ] **Step 1: 改测试 `tests/test_company_database.py`**

把 `test_build_company_database_creates_schema_indexes_and_metadata` 中 `assert connection.execute("PRAGMA user_version").fetchone()[0] == 2` 改为 `== 3`，并在该 `with` 块内 `indexes = {...}` 之前追加：

```python
        assert connection.execute("SELECT COUNT(*) FROM company_shareholders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM company_investments").fetchone()[0] == 0
        ownership_meta = connection.execute(
            "SELECT shareholder_count, investment_count, shareholders_sha256, investments_sha256 "
            "FROM import_metadata"
        ).fetchone()
        assert ownership_meta == (0, 0, None, None)
```

把该用例末尾的索引断言集合扩展为（追加 4 个）：

```python
    assert {
        "idx_companies_registration_status",
        "idx_companies_province_city",
        "idx_companies_industry_division",
        "idx_companies_enterprise_size",
        "idx_company_aliases_normalized",
        "idx_shareholders_company",
        "idx_shareholders_holder_code",
        "idx_investments_company",
        "idx_investments_investee_code",
    } <= indexes
```

- [ ] **Step 2: 改测试 `tests/test_company_repository.py`**

把 `test_repository_rejects_unsupported_schema_version` 中 `connection.execute("PRAGMA user_version = 99")` 保持 `99`，把 `match="expected 2"` 改为 `match="expected 3"`。

- [ ] **Step 3: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py::test_build_company_database_creates_schema_indexes_and_metadata -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t1`
Expected: FAIL（user_version 仍为 2 且无 `company_shareholders` 表）。

- [ ] **Step 4: 改 `src/deepresearch_agent/company_database.py`**

把 `SCHEMA_VERSION = 2` 改为 `SCHEMA_VERSION = 3`。

在 `_create_schema` 的 `connection.executescript(""" ... """)` 内，把 `CREATE TABLE import_metadata (...)` 整段替换为：

```sql
        CREATE TABLE import_metadata (
            schema_version INTEGER NOT NULL,
            companies_sha256 TEXT NOT NULL,
            contacts_sha256 TEXT NOT NULL,
            shareholders_sha256 TEXT,
            investments_sha256 TEXT,
            input_company_count INTEGER NOT NULL,
            company_count INTEGER NOT NULL,
            contact_count INTEGER NOT NULL,
            shareholder_count INTEGER NOT NULL,
            investment_count INTEGER NOT NULL,
            generated_at TEXT NOT NULL
        );
```

在同一 `executescript` 字符串内、`CREATE TABLE scope_index_metadata (...);` 之后、闭合 `"""` 之前追加：

```sql
        CREATE TABLE company_shareholders (
            id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            shareholder_name TEXT NOT NULL,
            normalized_shareholder_name TEXT NOT NULL,
            shareholder_credit_code TEXT,
            shareholder_type TEXT,
            shareholder_is_person TEXT NOT NULL,
            share_class TEXT,
            shares_held TEXT,
            indirect_holding_pct TEXT,
            associated_product TEXT
        );
        CREATE INDEX idx_shareholders_company
            ON company_shareholders(unified_social_credit_code);
        CREATE INDEX idx_shareholders_holder_code
            ON company_shareholders(shareholder_credit_code);
        CREATE TABLE company_investments (
            id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            investee_name TEXT NOT NULL,
            normalized_investee_name TEXT NOT NULL,
            investee_credit_code TEXT,
            status TEXT,
            investee_established_date TEXT,
            holding_pct TEXT,
            subscribed_capital_amount TEXT,
            subscribed_capital_currency TEXT,
            subscribed_capital_original TEXT,
            final_beneficiary_pct TEXT,
            region TEXT,
            industry TEXT,
            associated_product TEXT
        );
        CREATE INDEX idx_investments_company
            ON company_investments(unified_social_credit_code);
        CREATE INDEX idx_investments_investee_code
            ON company_investments(investee_credit_code);
```

把 `_build_atomic_database` 内的 `import_metadata` INSERT 整段替换为 11 值版本（本任务股权值先填 NULL/0）：

```python
            connection.execute(
                "INSERT INTO import_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    SCHEMA_VERSION,
                    _sha256(companies_path),
                    _sha256(contacts_path),
                    None,
                    None,
                    len(companies),
                    len(companies),
                    len(contacts),
                    0,
                    0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
```

- [ ] **Step 5: 运行确认通过 + 全套无回归**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t1b`
Expected: PASS。

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t1c`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/company_database.py tests/test_company_database.py tests/test_company_repository.py
git commit -m "功能：schema 升 v3 增加空股权边表与索引"
```

---

## Task 2: 股权边入库（解析 + 入库 + 脚本 + fixture）

**Files:**
- Modify: `src/deepresearch_agent/company_database.py`
- Modify: `scripts/build_company_database.py`
- Modify: `tests/test_company_database.py`
- Create: `tests/fixtures/procurement/shareholders.csv`
- Create: `tests/fixtures/procurement/investments.csv`

**Interfaces:**
- Consumes: `shareholder_data_cleaning.OUTPUT_COLUMNS`、`investment_data_cleaning.OUTPUT_COLUMNS`、`normalize_company_name`。
- Produces:
  - `build_company_database(companies_csv, contacts_csv, output_path, shareholders_csv=None, investments_csv=None) -> dict`
  - 返回键：`{companies, contacts, shareholders, investments, unresolved_shareholders, unresolved_investments}`

- [ ] **Step 1: 创建 fixture `tests/fixtures/procurement/shareholders.csv`**

```text
company_name,normalized_company_name,shareholder_name,shareholder_type,shareholder_is_person,share_class,shares_held,indirect_holding_pct,associated_product
示例科技股份有限公司,示例科技股份有限公司,张三,自然人股东,true,流通A股,1000,,
示例科技股份有限公司,示例科技股份有限公司,示例科技股份有限公司,企业法人,false,,,,
不存在公司,不存在公司,李四,自然人股东,true,,,,
```

- [ ] **Step 2: 创建 fixture `tests/fixtures/procurement/investments.csv`**

```text
company_name,normalized_company_name,investee_name,normalized_investee_name,status,investee_established_date,holding_pct,subscribed_capital_amount,subscribed_capital_currency,subscribed_capital_original,final_beneficiary_pct,region,industry,associated_product
示例科技股份有限公司,示例科技股份有限公司,示例科技股份有限公司,示例科技股份有限公司,存续,2020-01-02,100%,1000000,CNY,100万元,100%,浙江省,制造业,
示例科技股份有限公司,示例科技股份有限公司,某外部子公司有限公司,某外部子公司有限公司,注销,2018-05-05,60%,5000000,CNY,500万元,60%,江苏省,批发业,
不存在公司,不存在公司,无关投资,无关投资,存续,,,,,,,,,
```

- [ ] **Step 3: 写失败测试，追加到 `tests/test_company_database.py` 末尾**

```python
def test_build_company_database_ingests_ownership_resolves_and_skips(tmp_path):
    database_path = tmp_path / "companies.sqlite3"

    summary = build_company_database(
        FIXTURES / "companies.csv",
        FIXTURES / "contacts.csv",
        database_path,
        shareholders_csv=FIXTURES / "shareholders.csv",
        investments_csv=FIXTURES / "investments.csv",
    )

    assert summary == {
        "companies": 1,
        "contacts": 1,
        "shareholders": 2,
        "investments": 2,
        "unresolved_shareholders": 1,
        "unresolved_investments": 1,
    }
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM company_shareholders").fetchone()[0] == 2
        person = connection.execute(
            "SELECT shareholder_credit_code FROM company_shareholders WHERE shareholder_name = '张三'"
        ).fetchone()
        assert person == (None,)
        entity = connection.execute(
            "SELECT shareholder_credit_code, unified_social_credit_code "
            "FROM company_shareholders WHERE shareholder_type = '企业法人'"
        ).fetchone()
        assert entity == ("91330000123456789X", "91330000123456789X")

        assert connection.execute("SELECT COUNT(*) FROM company_investments").fetchone()[0] == 2
        resolved = connection.execute(
            "SELECT investee_credit_code FROM company_investments "
            "WHERE investee_name = '示例科技股份有限公司'"
        ).fetchone()
        assert resolved == ("91330000123456789X",)
        external = connection.execute(
            "SELECT investee_credit_code, status FROM company_investments "
            "WHERE investee_name = '某外部子公司有限公司'"
        ).fetchone()
        assert external == (None, "注销")

        meta = connection.execute(
            "SELECT shareholder_count, investment_count, shareholders_sha256 FROM import_metadata"
        ).fetchone()
        assert meta[0] == 2
        assert meta[1] == 2
        assert len(meta[2]) == 64
```

同时把现有 `test_build_company_database_creates_schema_indexes_and_metadata` 中 `assert summary == {"companies": 1, "contacts": 1}` 改为：

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

- [ ] **Step 4: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py::test_build_company_database_ingests_ownership_resolves_and_skips -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t2`
Expected: FAIL（`build_company_database()` 不接受 `shareholders_csv`）。

- [ ] **Step 5: 改 `src/deepresearch_agent/company_database.py`**

顶部 import 区追加：

```python
from deepresearch_agent.investment_data_cleaning import OUTPUT_COLUMNS as INVESTMENT_COLUMNS
from deepresearch_agent.shareholder_data_cleaning import OUTPUT_COLUMNS as SHAREHOLDER_COLUMNS
```

把 `build_company_database` 整个函数替换为：

```python
def build_company_database(
    companies_csv: str | Path,
    contacts_csv: str | Path,
    output_path: str | Path,
    shareholders_csv: str | Path | None = None,
    investments_csv: str | Path | None = None,
) -> dict[str, int]:
    companies_path = Path(companies_csv)
    contacts_path = Path(contacts_csv)
    companies = _read_companies(companies_path)
    contacts = _read_contacts(contacts_path, companies)
    shareholders_path = Path(shareholders_csv) if shareholders_csv is not None else None
    investments_path = Path(investments_csv) if investments_csv is not None else None
    shareholders = _read_edges(shareholders_path, SHAREHOLDER_COLUMNS) if shareholders_path else []
    investments = _read_edges(investments_path, INVESTMENT_COLUMNS) if investments_path else []
    counts = _build_atomic_database(
        companies,
        contacts,
        shareholders,
        investments,
        companies_path,
        contacts_path,
        shareholders_path,
        investments_path,
        Path(output_path),
    )
    return {"companies": len(companies), "contacts": len(contacts), **counts}


def _read_edges(path: Path, expected_columns: list[str]) -> list[dict[str, str]]:
    return [row for _, row in _read_csv(path, expected_columns)]
```

把 `_build_atomic_database` 整个函数替换为：

```python
def _build_atomic_database(
    companies: list[_CompanySourceRow],
    contacts: list[_ContactSourceRow],
    shareholders: list[dict[str, str]],
    investments: list[dict[str, str]],
    companies_path: Path,
    contacts_path: Path,
    shareholders_path: Path | None,
    investments_path: Path | None,
    output_path: Path,
) -> dict[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.unlink(missing_ok=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            _create_schema(connection)
            _insert_companies(connection, companies)
            _insert_contacts(connection, contacts)
            _insert_scope_chunks(connection, companies)
            legal_map, alias_map = _build_name_index(companies)
            sh_inserted, sh_unresolved = _insert_shareholders(
                connection, shareholders, legal_map, alias_map
            )
            inv_inserted, inv_unresolved = _insert_investments(
                connection, investments, legal_map, alias_map
            )
            connection.execute(
                "INSERT INTO import_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    SCHEMA_VERSION,
                    _sha256(companies_path),
                    _sha256(contacts_path),
                    _sha256(shareholders_path) if shareholders_path is not None else None,
                    _sha256(investments_path) if investments_path is not None else None,
                    len(companies),
                    len(companies),
                    len(contacts),
                    sh_inserted,
                    inv_inserted,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.close()
        connection = None
        temporary_path.replace(output_path)
    except Exception:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "shareholders": sh_inserted,
        "investments": inv_inserted,
        "unresolved_shareholders": sh_unresolved,
        "unresolved_investments": inv_unresolved,
    }
```

在 `_insert_scope_chunks` 函数之后新增解析与入库函数：

```python
def _build_name_index(
    companies: list[_CompanySourceRow],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    legal_map: dict[str, str] = {}
    alias_map: dict[str, set[str]] = {}
    for item in companies:
        code = item.profile.unified_social_credit_code
        legal_map[normalize_company_name(item.profile.legal_name)] = code
        for alias in item.profile.aliases:
            alias_map.setdefault(normalize_company_name(alias), set()).add(code)
    return legal_map, alias_map


def _resolve(
    normalized_name: str,
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> str | None:
    if normalized_name in legal_map:
        return legal_map[normalized_name]
    codes = alias_map.get(normalized_name)
    if codes is not None and len(codes) == 1:
        return next(iter(codes))
    return None


def _insert_shareholders(
    connection: sqlite3.Connection,
    rows: list[dict[str, str]],
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    for row in rows:
        anchor = _resolve(row["normalized_company_name"], legal_map, alias_map)
        if anchor is None:
            unresolved += 1
            continue
        holder_code: str | None = None
        if row["shareholder_is_person"] != "true":
            holder_code = _resolve(
                normalize_company_name(row["shareholder_name"]), legal_map, alias_map
            )
        connection.execute(
            "INSERT INTO company_shareholders "
            "(unified_social_credit_code, shareholder_name, normalized_shareholder_name, "
            "shareholder_credit_code, shareholder_type, shareholder_is_person, share_class, "
            "shares_held, indirect_holding_pct, associated_product) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                anchor,
                row["shareholder_name"],
                normalize_company_name(row["shareholder_name"]),
                holder_code,
                row["shareholder_type"],
                row["shareholder_is_person"],
                row["share_class"],
                row["shares_held"],
                row["indirect_holding_pct"],
                row["associated_product"],
            ),
        )
        inserted += 1
    return inserted, unresolved


def _insert_investments(
    connection: sqlite3.Connection,
    rows: list[dict[str, str]],
    legal_map: dict[str, str],
    alias_map: dict[str, set[str]],
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    for row in rows:
        anchor = _resolve(row["normalized_company_name"], legal_map, alias_map)
        if anchor is None:
            unresolved += 1
            continue
        investee_code = _resolve(row["normalized_investee_name"], legal_map, alias_map)
        connection.execute(
            "INSERT INTO company_investments "
            "(unified_social_credit_code, investee_name, normalized_investee_name, "
            "investee_credit_code, status, investee_established_date, holding_pct, "
            "subscribed_capital_amount, subscribed_capital_currency, subscribed_capital_original, "
            "final_beneficiary_pct, region, industry, associated_product) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                anchor,
                row["investee_name"],
                row["normalized_investee_name"],
                investee_code,
                row["status"],
                row["investee_established_date"],
                row["holding_pct"],
                row["subscribed_capital_amount"],
                row["subscribed_capital_currency"],
                row["subscribed_capital_original"],
                row["final_beneficiary_pct"],
                row["region"],
                row["industry"],
                row["associated_product"],
            ),
        )
        inserted += 1
    return inserted, unresolved
```

- [ ] **Step 6: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t2b`
Expected: PASS（含新用例与改过的既有用例）。

- [ ] **Step 7: 改 `scripts/build_company_database.py` 支持股权入参**

把 `main` 函数整段替换为：

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the local SQLite company database.")
    parser.add_argument("--companies", default="data/procurement/processed/companies.csv")
    parser.add_argument("--contacts", default="data/procurement/processed/contacts.csv")
    parser.add_argument("--shareholders", default="data/procurement/processed/shareholders.csv")
    parser.add_argument("--investments", default="data/procurement/processed/investments.csv")
    parser.add_argument("--output", default="data/procurement/derived/companies.sqlite3")
    args = parser.parse_args(argv)
    shareholders = args.shareholders if Path(args.shareholders).is_file() else None
    investments = args.investments if Path(args.investments).is_file() else None
    summary = build_company_database(
        args.companies, args.contacts, args.output,
        shareholders_csv=shareholders, investments_csv=investments,
    )
    print(" ".join(f"{key}={value}" for key, value in summary.items()))
```

并确认脚本顶部已 `from pathlib import Path`（若无则添加 `from pathlib import Path`）。

- [ ] **Step 8: 运行全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a2-t2c`
Expected: PASS。

- [ ] **Step 9: 提交**

```bash
git add src/deepresearch_agent/company_database.py scripts/build_company_database.py tests/test_company_database.py tests/fixtures/procurement/shareholders.csv tests/fixtures/procurement/investments.csv
git commit -m "功能：建库时解析并入库股东与对外投资边"
```

---

## Self-Review

**1. Spec coverage:**
- schema v3 + 两边表 + 索引 + import_metadata 扩展 → Task 1 ✅
- `build_company_database` 可选入参、原子集成 → Task 2 ✅
- 锚点解析、未解析跳过计数 → Task 2（`_resolve` + `_insert_*`）✅
- 对手方可空解析、自然人不解析 → Task 2（`_insert_shareholders` 的 is_person 分支；`_insert_investments` 直接解析）✅
- 入库列全 TEXT → Task 1 DDL ✅
- 脚本可选入参、存在才传 → Task 2 Step 7 ✅
- 受版本影响的测试适配 → Task 1（v3、拒绝用例）+ Task 2（summary 等值）✅
- 不提供 CSV → 空表 0 计数 → Task 1（空）+ Task 2（既有用例 summary 含 0）✅

**2. Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。✅

**3. Type consistency:**
- `build_company_database(..., shareholders_csv=None, investments_csv=None)` 在 Task 2 定义；返回 6 键与测试断言一致。
- `_read_edges(path, expected_columns)`、`_build_name_index`、`_resolve`、`_insert_shareholders`/`_insert_investments`（返回 `(inserted, unresolved)`）在 Task 2 一致使用。
- `SHAREHOLDER_COLUMNS`/`INVESTMENT_COLUMNS` 来自 A1 模块的 `OUTPUT_COLUMNS`，列名与 fixture 表头一致。
- `import_metadata` 11 列顺序与 Task 1 DDL、Task 2 INSERT 一致。

无不一致。
```
