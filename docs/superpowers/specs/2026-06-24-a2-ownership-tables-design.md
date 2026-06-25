# 模块 A2：股权边表入库设计

日期：2026-06-24

本 spec 属于"股权关系层 + GraphRAG 路线图"的**模块 A2**。只覆盖建表与入库，不含 Repository 读方法（A3）、关联计算（A4）、Agent 接入（A5）。

## 目标

把 A1 清洗出的 `shareholders.csv` / `investments.csv` 接进 SQLite：新增 `company_shareholders`、`company_investments` 两张边表，按规范化名称把"我方企业"锚点解析为统一社会信用代码，对手方在我方库内时也解析（可空）。集成进 `build_company_database` 的**单次原子构建**（方案 a），schema 升 v3。

## 范围

### 包含
- `SCHEMA_VERSION` 升 v3；新增两张边表 + 索引；`import_metadata` 扩展股权计数与哈希。
- `build_company_database` 增加可选入参 `shareholders_csv` / `investments_csv`，在同一原子事务内入库。
- 名称解析：锚点（我方企业）必须解析、否则跳过并计数；对手方解析为可空信用代码。
- 入库列全部 TEXT（与 companies 表一致）。
- 脚本 `scripts/build_company_database.py` 增加 `--shareholders` / `--investments`（存在才传）。
- 适配现有受 schema 版本影响的测试。

### 不包含
- 不加 `CompanyRepository.get_shareholders/get_investments`（A3）。
- 不做关联供应商计算（A4）、不接 Agent（A5）。
- 不改 A1 清洗模块的输出列。

## Schema v3

`SCHEMA_VERSION = 3`。`_create_schema` 在现有表之后新增：

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

`import_metadata` 表改为：

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

`shareholders_sha256`/`investments_sha256` 在未提供对应 CSV 时为 NULL；计数为 0。

## 名称解析

在内存中从 `companies` 列表构建索引（不查 DB）：

```python
def _build_name_index(companies) -> tuple[dict[str, str], dict[str, set[str]]]:
    # legal: 规范化法定名 -> 信用代码（schema 保证法定名唯一）
    # alias: 规范化曾用名 -> {信用代码...}
```

```python
def _resolve(normalized_name, legal_map, alias_map) -> str | None:
    # 优先法定名精确命中；否则曾用名唯一命中；其余 None
```

规则：
- **锚点**（边的 `normalized_company_name`，即我方企业）：`_resolve` 得 `unified_social_credit_code`；**为 None 则跳过该边并计数**（即那 3~4 家名称不匹配的）。
- **股东对手方**：仅当 `shareholder_is_person == "false"` 时尝试 `_resolve(normalize_company_name(shareholder_name))` → `shareholder_credit_code`（可空）；自然人一律 None，避免人名误撞公司名。
- **被投企业对手方**：`_resolve(normalized_investee_name)` → `investee_credit_code`（可空）。

## 构建流程

`build_company_database` 签名扩展：

```python
def build_company_database(
    companies_csv, contacts_csv, output_path,
    shareholders_csv=None, investments_csv=None,
) -> dict[str, int]
```

- 读 companies、contacts（不变）。
- `shareholders_csv` 非空 → `_read_shareholders(path)`：用 `shareholder_data_cleaning.OUTPUT_COLUMNS` 校验表头，返回 `(line_number, dict)` 列表；为空则 `[]`。`investments` 同理用 `investment_data_cleaning.OUTPUT_COLUMNS`。
- `_build_atomic_database` 内、`_insert_companies` 之后：`legal_map, alias_map = _build_name_index(companies)`，再 `_insert_shareholders` / `_insert_investments`（逐行解析锚点，跳过未解析并计数；写对手方可空代码）。
- `import_metadata` INSERT 改为 11 个值（含两个哈希、两个计数）。
- 返回 `{companies, contacts, shareholders, investments, unresolved_shareholders, unresolved_investments}`（后两者为锚点未解析而跳过的边数）。

整个过程仍在单个事务内、写临时文件后原子替换——保持"一次构建、可从 CSV 完全复现"。

## 脚本

`scripts/build_company_database.py` 增加：

```python
parser.add_argument("--shareholders", default="data/procurement/processed/shareholders.csv")
parser.add_argument("--investments", default="data/procurement/processed/investments.csv")
```

仅当文件存在才传入对应路径（否则传 None，建空表）——这样没有股权导出时仍可正常建库。

## 错误处理
- 提供的 CSV 路径不存在或表头不符 → `build_company_database` 抛 `ValueError`（含路径），整次构建失败、不覆盖旧库（沿用现有原子失败语义）。
- 锚点未解析 → 跳过该边并计入 `unresolved_*`，不报错。
- 对手方未解析 → 代码列存 NULL，不报错。
- schema 版本不为 3 → `CompanyRepository` 拒绝并提示重建（沿用现有校验）。

## 测试策略（合成 fixture）

新增可提交 fixture：`tests/fixtures/procurement/shareholders.csv`、`investments.csv`（A1 输出列结构），引用现有 fixture 企业 `示例科技股份有限公司`（`91330000123456789X`），并含一条锚点无法解析的边（验证跳过+计数）、一条对手方在库内的边（验证对手方代码解析）。

- `test_company_database`：
  - 把现有 `user_version == 2` 断言改为 `== 3`。
  - 把现有 `summary == {"companies": 1, "contacts": 1}` 断言改为含新键：`{"companies": 1, "contacts": 1, "shareholders": 0, "investments": 0, "unresolved_shareholders": 0, "unresolved_investments": 0}`（该用例不传股权 CSV）。
  - 新增用例：`build_company_database(..., shareholders_csv=fixture, investments_csv=fixture)` → 断言两表行数、`import_metadata` 的 `shareholder_count`/`investment_count`、对手方代码解析（库内→非空、自然人/库外→NULL）、锚点未解析边被跳过且计入返回值、两表索引存在。
  - 新增用例：不传股权 CSV → 两表为空、计数 0、哈希为 NULL。
- `test_company_repository::test_repository_rejects_unsupported_schema_version`：`PRAGMA user_version = 99`，`match="expected 3"`。
- 默认套件其余测试经 conftest 建 v3 库（含空股权表）照常通过；本模块不改 conftest。

## 验收条件
- 全套测试通过。
- 用真实 processed CSV 构建：`company_shareholders` ≈ 38,331 行、`company_investments` ≈ 55,701 行（以解析后实际为准）；锚点未解析边数与返回的 `unresolved_*` 一致；`import_metadata` 记录两计数与哈希。
- 不提供股权 CSV 时建库成功、两表为空，现有工商/检索路径不受影响。
- schema 为 v3；旧 v2 库被拒绝并提示重建。
