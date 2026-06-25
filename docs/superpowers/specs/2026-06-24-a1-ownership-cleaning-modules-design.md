# 模块 A1：股权数据清洗模块化设计

日期：2026-06-24

本 spec 属于"股权关系层 + GraphRAG 路线图"的**模块 A1**。只覆盖清洗模块化，不含 SQLite 表、Repository、Agent 接入（那是 A2/A3/A5）。

## 目标

把当前散在 `scripts/` 里的两段股权数据清洗逻辑，提升为 `src/` 下**带 TDD 测试的正式模块**，与现有 `company_data_cleaning` 同一范式；脚本退化为薄命令行包装。行为与现脚本一致（已用真实数据验证：股东 38,331 条、对外投资 55,701 条）。

## 范围

### 包含
- 新模块 `shareholder_data_cleaning.py`（企查查股东，utf-8-sig）。
- 新模块 `investment_data_cleaning.py`（天眼查对外投资，gb18030，复用 `parse_capital` / `normalize_date`）。
- 共享小模块 `vendor_export.py`：`="..."` 文本剥除 + `-`/全星号→空，两清洗器共用。
- 两个脚本改为薄包装（`import ... run_cleaning` + argparse）。
- 合成 fixture 的单元测试，不依赖真实数据。

### 不包含
- 不建 SQLite 表、不改 schema（A2）。
- 不加 Repository 方法（A3）、不接 Agent（A5）。
- 不改输出列定义（沿用现脚本已验证的列）。
- 不解析股东/被投企业到信用代码（无信用代码；名称连接是 A2/B1 的事）。

## 文件结构

```
src/deepresearch_agent/
  vendor_export.py                 # unquote() / clean_cell()，企查查/天眼查导出通用
  shareholder_data_cleaning.py     # OUTPUT_COLUMNS / clean_shareholder_rows / run_cleaning
  investment_data_cleaning.py      # OUTPUT_COLUMNS / clean_investment_rows / run_cleaning
scripts/
  clean_qcc_shareholder_data.py    # 薄包装 → shareholder_data_cleaning.run_cleaning
  clean_tyc_investment_data.py     # 薄包装 → investment_data_cleaning.run_cleaning
tests/
  test_vendor_export.py
  test_shareholder_data_cleaning.py
  test_investment_data_cleaning.py
```

## 接口

### `vendor_export.py`
```python
def unquote(value: str) -> str          # 去掉 Excel 文本包裹 ="..."，再 strip
def clean_cell(value: str) -> str        # unquote 后，"-" 或全 "*" → ""，否则原值
```

### `shareholder_data_cleaning.py`
```python
OUTPUT_COLUMNS: list[str]   # company_name, normalized_company_name, shareholder_name,
                            # shareholder_type, shareholder_is_person, share_class,
                            # shares_held, indirect_holding_pct, associated_product
def clean_shareholder_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]
def run_cleaning(input_path, output_path) -> dict[str, int]   # 读 utf-8-sig，写 utf-8-sig CSV
```
- 定位表头：首格 `unquote` 后等于 `企业名称` 的行。
- 跳过缺 `企业名称` 或 `股东名称` 的行；精确去重（整行）。
- `shares_held` 去逗号、仅保留纯数字否则空；`shareholder_is_person` = (股东类型 == `自然人股东`)。
- `normalized_company_name` 用 `company_database.normalize_company_name`。
- `run_cleaning` 返回 `{edges, companies, shareholders, person_edges, entity_edges}`。

### `investment_data_cleaning.py`
```python
OUTPUT_COLUMNS: list[str]   # company_name, normalized_company_name, investee_name,
                            # normalized_investee_name, status, investee_established_date,
                            # holding_pct, subscribed_capital_amount,
                            # subscribed_capital_currency, subscribed_capital_original,
                            # final_beneficiary_pct, region, industry, associated_product
def clean_investment_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]
def run_cleaning(input_path, output_path) -> dict[str, int]   # 读 gb18030，写 utf-8-sig CSV
```
- 定位表头：首格 `unquote` 后等于 `企业名称` 的行。
- 跳过缺 `企业名称` 或 `被投资企业名称` 的行；精确去重。
- `认缴出资额` 经 `company_data_cleaning.parse_capital` → amount/currency/original 三列；`成立日期` 经 `normalize_date` → ISO；`normalized_*_name` 用 `normalize_company_name`。
- `run_cleaning` 返回 `{edges, investors, investees, active_edges}`（`active_edges` = 状态为 `存续`）。

### 脚本（薄包装）
各自 `argparse`（`--input` 必填、`--output` 默认 `data/procurement/processed/<name>.csv`），校验输入存在，调对应 `run_cleaning`，打印 summary。

## 数据流

```
candidates/<企查查>股东信息.csv (utf-8-sig)  -> shareholder_data_cleaning -> processed/shareholders.csv
candidates/<天眼查>对外投资.csv  (gb18030)    -> investment_data_cleaning  -> processed/investments.csv
```
`processed/` Git 忽略；受限数据不入库。清洗器纯函数 + 文件 IO 分离，便于测试。

## 错误处理
- 输入文件不存在：脚本层 `argparse.error` 明确报错。
- 找不到表头行（无 `企业名称` 列）：`clean_*_rows` 返回空列表（不抛异常），summary 计数为 0——调用方据此判断导出异常。
- 单元格解析失败（如持股数非数字）：对应字段置空，不丢整行。

## 测试策略（合成 fixture，不用真实数据）

- `test_vendor_export`：`unquote('="x"')=='x'`、`clean_cell('="-"')==''`、`clean_cell('="***"')==''`、普通值原样。
- `test_shareholder_data_cleaning`：
  - 给含 banner/声明/段标题 + 表头 + 数据的合成 `raw_rows`，断言跳过非数据行、`="..."` 剥除、持股数去逗号、`shareholder_is_person` 正确、缺名称行丢弃、整行去重。
  - `run_cleaning`：写一个 utf-8-sig 临时 CSV → 读出断言列与计数。
- `test_investment_data_cleaning`：
  - 合成 `raw_rows` 断言 `认缴出资额`"6500万元人民币"→amount 65000000/CNY、`成立日期`→ISO、`normalized_investee_name`、去重。
  - `run_cleaning`：写一个 **gb18030** 临时 CSV → 断言能正确读出（验证编码处理）。
- 默认测试套件不触真实数据、不触网、无重依赖。

## 验收条件
- 三个测试文件全绿，默认套件整体通过。
- 两个脚本仍可命令行运行，对真实导出产出与现状一致的 `shareholders.csv`（9 列）/ `investments.csv`（14 列）。
- 清洗逻辑全部在 `src/` 模块内，脚本仅为薄包装。
