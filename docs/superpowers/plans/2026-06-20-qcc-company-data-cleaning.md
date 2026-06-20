# 企业工商数据清洗实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将企查查工商信息 Excel 可重复地清洗为核心企业、联系方式和拒绝记录三张本地 CSV。

**Architecture:** 使用 `openpyxl` 只读解析工作簿，将纯字段规范化函数与文件 I/O 分离。核心清洗函数返回三组结构化记录，命令行脚本负责选择输入文件和写出 UTF-8 BOM CSV。

**Tech Stack:** Python 3.11、openpyxl、csv、pytest。

---

### Task 1: 字段规范化与工作簿清洗

**Files:**
- Create: `src/deepresearch_agent/company_data_cleaning.py`
- Create: `tests/test_company_data_cleaning.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 编写失败测试**

测试以下行为：

```python
def test_parse_capital_converts_ten_thousand_yuan():
    assert parse_capital("13400万元") == ("134000000", "CNY", "13400万元")

def test_parse_business_term_handles_indefinite_end():
    assert parse_business_term("1997-01-28 至 无固定期限") == ("1997-01-28", "", True)

def test_split_values_removes_placeholders_and_duplicates():
    assert split_values("a@example.com;a@example.com;-;b@example.com") == ["a@example.com", "b@example.com"]

def test_clean_rows_separates_matched_and_rejected_records():
    companies, contacts, rejected = clean_rows([...])
    assert len(companies) == 1
    assert len(contacts) == 1
    assert rejected == [{"source_name": "未匹配公司", "matched_name": "未匹配到相关企业", "reason": "unmatched"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_data_cleaning.py -q --basetemp=.pytest-tmp`

Expected: FAIL，提示模块不存在。

- [ ] **Step 3: 添加依赖并实现最小清洗模块**

在 `pyproject.toml` 添加：

```toml
"openpyxl>=3.1.5",
```

实现 `normalize_missing`、`parse_capital`、`parse_business_term`、`split_values`、`clean_rows`、`read_workbook_rows` 和 `write_csv`。读取时固定跳过第 1 行声明，以第 2 行作为表头。

- [ ] **Step 4: 运行目标测试和全量测试**

```powershell
.\.conda-env\python.exe -m pytest tests/test_company_data_cleaning.py -q --basetemp=.pytest-tmp
.\.conda-env\python.exe -m pytest -q --basetemp=.pytest-tmp
```

Expected: 全部通过。

- [ ] **Step 5: 提交**

```powershell
git add pyproject.toml src/deepresearch_agent/company_data_cleaning.py tests/test_company_data_cleaning.py
git commit -m "功能：增加企业工商数据清洗器"
```

### Task 2: 清洗命令与本地数据产物

**Files:**
- Create: `scripts/clean_qcc_company_data.py`
- Modify: `.gitignore`
- Create locally, ignored: `data/procurement/cleaned/companies.csv`
- Create locally, ignored: `data/procurement/cleaned/contacts.csv`
- Create locally, ignored: `data/procurement/cleaned/rejected.csv`

- [ ] **Step 1: 编写命令层失败测试**

使用临时工作簿调用 `run_cleaning(input_path, output_dir)`，断言三张 CSV 均生成且记录数正确。

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_data_cleaning.py::test_run_cleaning_writes_three_csv_files -q --basetemp=.pytest-tmp`

Expected: FAIL，提示 `run_cleaning` 不存在。

- [ ] **Step 3: 实现命令并添加忽略规则**

命令：

```powershell
.\.conda-env\python.exe scripts/clean_qcc_company_data.py --input <xlsx> --output-dir data/procurement/cleaned
```

`.gitignore` 添加：

```text
data/procurement/candidates/*.xlsx
data/procurement/cleaned/
```

- [ ] **Step 4: 执行真实清洗**

Expected:

```text
input_rows=3509
companies=3506
contacts=3506
rejected=3
```

- [ ] **Step 5: 验证输出**

验证核心表名称和统一社会信用代码非空、三张表数量正确、资本字段可解析、拒绝表包含 3 条未匹配记录。

- [ ] **Step 6: 运行全量测试并提交脚本**

```powershell
.\.conda-env\python.exe -m pytest -q --basetemp=.pytest-tmp
git diff --check
git add .gitignore scripts/clean_qcc_company_data.py tests/test_company_data_cleaning.py
git commit -m "功能：增加企查查数据清洗命令"
```

清洗生成的 CSV 不执行 `git add`。

