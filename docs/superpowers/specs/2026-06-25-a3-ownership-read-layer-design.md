# 模块 A3：Repository 股权读层设计

日期：2026-06-25

本文件是路线图模块 **A3** 的设计 spec。上游 A1（清洗模块化）、A2（边表入库）已完成并合并。A3 在 `CompanyRepository` 上加两个只读方法，把 A2 入库的两张股权边表按公司信用代码读出为 Pydantic 记录。

## 背景与定位

A2 建库时已把股东、对外投资两份边数据入库为：

- `company_shareholders`：谁持有某库内公司（股东边）。
- `company_investments`：某库内公司对外投资了谁（投资边）。

两表的锚点列 `unified_social_credit_code` 是库内公司的信用代码（NOT NULL 外键），对手方信用代码（`shareholder_credit_code` / `investee_credit_code`）仅在按规范化名解析到库内公司时才有值，否则为 NULL。所有股权字段在 A2 一律按原文存为 TEXT。

A3 只做**读层**：把这些边读出来。不接图、不做关联计算（A4）、不接 Agent/工具（A5）。是 A4/A5 与后续 B 阶段的取数基础。

## 全局约束

- **原文透传**：除把存为 TEXT 的布尔列 `shareholder_is_person` 反序列化为 `bool` 外，所有股权字段保持 `str | None`，忠实呈现数据源原文，不解析百分比/日期/金额。理由：与 A2 存储一致，守"按原文作证据、不推断"的数据纪律，且 A3 当前无需要数值类型的消费者（YAGNI）。
- **确定性**：读取结果按 `id`（= 入库顺序 = 源 CSV 顺序）排序，保证可复现。
- **不暴露内部列**：返回记录不含自增主键 `id` 与派生列 `normalized_shareholder_name` / `normalized_investee_name`（连接/匹配用的辅助列，非源数据）。与现有 `get_by_credit_code` 丢弃 `normalized_legal_name` 一致。
- **复用现有连接**：方法走现有 `_connect()`，它已处理库不存在（`FileNotFoundError`）与 schema 版本不匹配（`RuntimeError`）。A3 不新增错误路径。

## 数据模型（`company_models.py`）

新增两个 Pydantic 模型，与现有 `ScopeChunkRecord` 同构（`model_config` 沿用本模块约定，空串经 `none_if_blank` 转 `None`）。

### `ShareholderRecord`

| 字段 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| `unified_social_credit_code` | `str` | 同名列 | 锚点：被持有的库内公司 |
| `shareholder_name` | `str` | `shareholder_name` | 股东名（源原文） |
| `shareholder_credit_code` | `str \| None` | `shareholder_credit_code` | 解析到库内公司才有，否则 None |
| `shareholder_type` | `str \| None` | `shareholder_type` | 如"自然人股东""企业法人" |
| `shareholder_is_person` | `bool` | `shareholder_is_person` | TEXT `"true"/"false"` → bool |
| `share_class` | `str \| None` | `share_class` | 股份类别 |
| `shares_held` | `str \| None` | `shares_held` | 持股数（原文） |
| `indirect_holding_pct` | `str \| None` | `indirect_holding_pct` | 间接持股比例（原文） |
| `associated_product` | `str \| None` | `associated_product` | 关联产品（原文） |

`shareholder_is_person` 用一个 `field_validator(mode="before")` 显式映射：值等于 `"true"` → `True`，否则 `False`（与本仓库显式校验器风格一致，避免依赖 Pydantic 隐式强转）。

### `InvestmentRecord`

| 字段 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| `unified_social_credit_code` | `str` | 同名列 | 锚点：投资方（库内公司） |
| `investee_name` | `str` | `investee_name` | 被投资方名（源原文） |
| `investee_credit_code` | `str \| None` | `investee_credit_code` | 解析到库内公司才有，否则 None |
| `status` | `str \| None` | `status` | 如"存续""注销" |
| `investee_established_date` | `str \| None` | `investee_established_date` | 成立日期（原文，不转 date） |
| `holding_pct` | `str \| None` | `holding_pct` | 持股比例（原文，如"100%"） |
| `subscribed_capital_amount` | `str \| None` | `subscribed_capital_amount` | 认缴金额（原文） |
| `subscribed_capital_currency` | `str \| None` | `subscribed_capital_currency` | 认缴币种 |
| `subscribed_capital_original` | `str \| None` | `subscribed_capital_original` | 认缴原文（如"500万元"） |
| `final_beneficiary_pct` | `str \| None` | `final_beneficiary_pct` | 最终受益比例（原文） |
| `region` | `str \| None` | `region` | 地区 |
| `industry` | `str \| None` | `industry` | 行业 |
| `associated_product` | `str \| None` | `associated_product` | 关联产品（原文） |

投资记录无 `is_person`（被投资方均为实体）。所有非锚点字段 `str | None` 原文透传。

## 仓库方法（`company_repository.py`）

```python
def get_shareholders(self, code: str) -> list[ShareholderRecord]
def get_investments(self, code: str) -> list[InvestmentRecord]
```

行为：

1. `normalized_code = code.strip()`。
2. 经 `_connect()` 开只读连接。
3. `SELECT <显式列> FROM <表> WHERE unified_social_credit_code = ? ORDER BY id`，显式列出要暴露的列（不含 `id`、`normalized_*`）。
4. 逐行 `model_validate` 成记录，返回列表。
5. **无匹配行（公司不在库 或 公司无该类边）→ 返回 `[]`**。不区分两种情形（YAGNI；外键保证只有真实公司才有边行）。无需 `JOIN`——股东名即源名，投资记录自带被投资方名。

## 错误处理

无新增错误路径。库不存在 / schema 不匹配由 `_connect()` 抛出（`FileNotFoundError` / `RuntimeError`）。未知或无边的 code 返回空列表，不抛错。

## 测试（`tests/test_company_repository.py`）

复用现有 fixture `tests/fixtures/procurement/shareholders.csv`、`investments.csv`，用 `build_company_database(..., shareholders_csv=..., investments_csv=...)` 现场建库（fixture 中"不存在公司"锚点行在建库时被跳过，故示例科技各得 2 条边）。

1. **`test_get_shareholders_returns_ordered_records_with_person_flag`**
   - `get_shareholders("91330000123456789X")` 返回 2 条，按 id 序（张三在前）。
   - 自然人行：`shareholder_name="张三"`、`shareholder_is_person is True`、`shareholder_credit_code is None`。
   - 企业法人行：`shareholder_type="企业法人"`、`shareholder_is_person is False`、`shareholder_credit_code="91330000123456789X"`。

2. **`test_get_investments_returns_records_with_resolution`**
   - `get_investments("91330000123456789X")` 返回 2 条。
   - 已解析行：`investee_name="示例科技股份有限公司"`、`investee_credit_code="91330000123456789X"`、`holding_pct="100%"`。
   - 外部行：`investee_name="某外部子公司有限公司"`、`investee_credit_code is None`、`status="注销"`、`subscribed_capital_original="500万元"`。

3. **`test_get_shareholders_and_investments_empty_for_unknown_and_edgeless`**
   - 未知 code：`get_shareholders("missing-code") == []`、`get_investments("missing-code") == []`。
   - 不带股权 CSV 建库的真实公司（用现有 `_build_database` helper）：两方法对其信用代码都返回 `[]`。

## 改动面

- `src/deepresearch_agent/company_models.py`：新增 `ShareholderRecord`、`InvestmentRecord`。
- `src/deepresearch_agent/company_repository.py`：导入两个新模型；新增 `get_shareholders`、`get_investments`。
- `tests/test_company_repository.py`：新增 3 个测试与一个"带股权建库"的小 helper。

无新文件、无 schema 改动、无 `SCHEMA_VERSION` 变更。与既有 `get_scope_chunks` / `ScopeChunkRecord` 模式同构。
