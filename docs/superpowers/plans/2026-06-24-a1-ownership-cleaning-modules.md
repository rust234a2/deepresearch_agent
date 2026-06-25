# 模块 A1：股权数据清洗模块化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把两段股权数据清洗逻辑从 `scripts/` 提升为 `src/` 下带 TDD 测试的正式模块，脚本退化为薄命令行包装。

**Architecture:** 新增共享单元格清洗 `vendor_export.py`，两个清洗模块 `shareholder_data_cleaning.py`（utf-8-sig）/ `investment_data_cleaning.py`（gb18030，复用 `parse_capital`/`normalize_date`）；纯函数 `clean_*_rows` 与文件 IO `run_cleaning` 分离，合成 fixture 测试。

**Tech Stack:** Python 3.11、csv、pytest。

## Global Constraints

- 解释器固定 `.\.conda-env\python.exe`，不新建 venv。
- 测试用合成 fixture，不依赖真实数据、不触网。
- 输出列与现脚本一致（股东 9 列、投资 14 列）；行为不变。
- `processed/` Git 忽略，受限数据不入库。
- 每个 Task 末尾提交一次，提交信息用中文。

---

## File Structure

新建：
- `src/deepresearch_agent/vendor_export.py` — `unquote` / `clean_cell`。
- `src/deepresearch_agent/shareholder_data_cleaning.py` — `OUTPUT_COLUMNS` / `clean_shareholder_rows` / `run_cleaning`。
- `src/deepresearch_agent/investment_data_cleaning.py` — `OUTPUT_COLUMNS` / `clean_investment_rows` / `run_cleaning`。
- 测试：`tests/test_vendor_export.py`、`tests/test_shareholder_data_cleaning.py`、`tests/test_investment_data_cleaning.py`。

改写：
- `scripts/clean_qcc_shareholder_data.py` — 薄包装。
- `scripts/clean_tyc_investment_data.py` — 薄包装。

---

## Task 1: vendor_export 共享单元格清洗

**Files:**
- Create: `src/deepresearch_agent/vendor_export.py`
- Test: `tests/test_vendor_export.py`

**Interfaces:**
- Produces: `unquote(value: str) -> str`、`clean_cell(value: str) -> str`

- [ ] **Step 1: 写失败测试 `tests/test_vendor_export.py`**

```python
from deepresearch_agent.vendor_export import clean_cell, unquote


def test_unquote_strips_excel_text_wrapper():
    assert unquote('="泰尔股份"') == "泰尔股份"
    assert unquote("  普通值  ") == "普通值"
    assert unquote('=""') == ""


def test_clean_cell_treats_dash_and_stars_as_missing():
    assert clean_cell('="-"') == ""
    assert clean_cell("-") == ""
    assert clean_cell('="***"') == ""
    assert clean_cell('="工业设备制造"') == "工业设备制造"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_vendor_export.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t1`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.vendor_export`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/vendor_export.py`**

```python
from __future__ import annotations

import re


_EXCEL_QUOTE = re.compile(r'^="(.*)"$', re.DOTALL)


def unquote(value: str) -> str:
    value = value.strip()
    match = _EXCEL_QUOTE.fullmatch(value)
    if match:
        value = match.group(1)
    return value.strip()


def clean_cell(value: str) -> str:
    value = unquote(value)
    if value == "-" or (value and set(value) == {"*"}):
        return ""
    return value
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_vendor_export.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t1b`
Expected: PASS（2 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/vendor_export.py tests/test_vendor_export.py
git commit -m "功能：增加企查查/天眼查导出单元格清洗 vendor_export"
```

---

## Task 2: 股东清洗模块 + 薄脚本

**Files:**
- Create: `src/deepresearch_agent/shareholder_data_cleaning.py`
- Modify: `scripts/clean_qcc_shareholder_data.py`（改为薄包装）
- Test: `tests/test_shareholder_data_cleaning.py`

**Interfaces:**
- Consumes: `vendor_export.unquote` / `clean_cell`（Task 1）；`company_database.normalize_company_name`。
- Produces:
  - `OUTPUT_COLUMNS`（9 列，见下）
  - `clean_shareholder_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]`
  - `run_cleaning(input_path, output_path) -> dict[str, int]`（读 utf-8-sig）

- [ ] **Step 1: 写失败测试 `tests/test_shareholder_data_cleaning.py`**

```python
import csv

from deepresearch_agent.shareholder_data_cleaning import (
    OUTPUT_COLUMNS,
    clean_shareholder_rows,
    run_cleaning,
)


def _header():
    return [
        '="企业名称"', '="股东名称"', '="股东类型"', '="股份类型"', '="持股数（股）"',
        '="认缴出资额"', '="认缴出资日期"', '="间接持股比例"', '="首次持股日期"',
        '="关联产品/机构"', "",
    ]


def test_clean_shareholder_rows_parses_dedupes_and_drops_blank_names():
    raw = [
        ["查企业  上企查查 ", " 联系电话", " 声明..."],
        [],
        ['="股东信息"', ""],
        _header(),
        ['="万马科技股份有限公司"', '="张德生"', '="自然人股东"', '="流通A股"', "28,843,500",
         '="-"', '="-"', '="1.4726%"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', '="某私募基金"', '="其他投资者"', '="流通A股"', "6,700,000",
         '="-"', '="-"', '="-"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', '="张德生"', '="自然人股东"', '="流通A股"', "28,843,500",
         '="-"', '="-"', '="1.4726%"', '="-"', '="-"', ""],
        ['="万马科技股份有限公司"', "", '="自然人股东"', "", "", "", "", "", "", "", ""],
    ]

    rows = clean_shareholder_rows(raw)

    assert [r["shareholder_name"] for r in rows] == ["张德生", "某私募基金"]
    first = rows[0]
    assert first["company_name"] == "万马科技股份有限公司"
    assert first["normalized_company_name"] == "万马科技股份有限公司"
    assert first["shareholder_is_person"] == "true"
    assert first["shares_held"] == "28843500"
    assert first["indirect_holding_pct"] == "1.4726%"
    assert rows[1]["shareholder_is_person"] == "false"


def test_shareholder_run_cleaning_writes_csv_roundtrip(tmp_path):
    src = tmp_path / "raw.csv"
    with src.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["声明..."])
        writer.writerow([c for c in _header() if c])
        writer.writerow(['="示例公司"', '="李四"', '="自然人股东"', '="流通A股"', "1,000",
                         '="-"', '="-"', '="-"', '="-"', '="-"'])
    out = tmp_path / "shareholders.csv"

    summary = run_cleaning(src, out)

    assert summary == {
        "edges": 1, "companies": 1, "shareholders": 1,
        "person_edges": 1, "entity_edges": 0,
    }
    with out.open(encoding="utf-8-sig", newline="") as handle:
        got = list(csv.DictReader(handle))
    assert list(got[0].keys()) == OUTPUT_COLUMNS
    assert got[0]["shareholder_name"] == "李四"
    assert got[0]["shares_held"] == "1000"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_shareholder_data_cleaning.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t2`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.shareholder_data_cleaning`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/shareholder_data_cleaning.py`**

```python
from __future__ import annotations

import csv
from pathlib import Path

from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.vendor_export import clean_cell, unquote


OUTPUT_COLUMNS = [
    "company_name",
    "normalized_company_name",
    "shareholder_name",
    "shareholder_type",
    "shareholder_is_person",
    "share_class",
    "shares_held",
    "indirect_holding_pct",
    "associated_product",
]


def _shares(value: str) -> str:
    cleaned = clean_cell(value).replace(",", "")
    return cleaned if cleaned.isdigit() else ""


def clean_shareholder_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header_seen = False
    seen_keys: set[tuple[str, ...]] = set()
    for raw in raw_rows:
        cells = [unquote(cell) for cell in raw]
        if not header_seen:
            if cells and cells[0] == "企业名称":
                header_seen = True
            continue
        if len(cells) < 5:
            continue
        company_name = clean_cell(raw[0])
        shareholder_name = clean_cell(raw[1])
        shareholder_type = clean_cell(raw[2])
        if not company_name or not shareholder_name:
            continue
        record = {
            "company_name": company_name,
            "normalized_company_name": normalize_company_name(company_name),
            "shareholder_name": shareholder_name,
            "shareholder_type": shareholder_type,
            "shareholder_is_person": "true" if shareholder_type == "自然人股东" else "false",
            "share_class": clean_cell(raw[3]) if len(raw) > 3 else "",
            "shares_held": _shares(raw[4]) if len(raw) > 4 else "",
            "indirect_holding_pct": clean_cell(raw[7]) if len(raw) > 7 else "",
            "associated_product": clean_cell(raw[9]) if len(raw) > 9 else "",
        }
        key = tuple(record[column] for column in OUTPUT_COLUMNS)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(record)
    return rows


def run_cleaning(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    input_path = Path(input_path)
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    rows = clean_shareholder_rows(raw_rows)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    persons = sum(1 for row in rows if row["shareholder_is_person"] == "true")
    return {
        "edges": len(rows),
        "companies": len({row["normalized_company_name"] for row in rows}),
        "shareholders": len({row["shareholder_name"] for row in rows}),
        "person_edges": persons,
        "entity_edges": len(rows) - persons,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_shareholder_data_cleaning.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t2b`
Expected: PASS（2 passed）。

- [ ] **Step 5: 把 `scripts/clean_qcc_shareholder_data.py` 整文件替换为薄包装**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from deepresearch_agent.shareholder_data_cleaning import run_cleaning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Clean QCC shareholder export into an edge CSV.")
    parser.add_argument("--input", type=Path, required=True, help="Source QCC shareholder .csv file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/procurement/processed/shareholders.csv"),
    )
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input file does not exist: {args.input}")

    summary = run_cleaning(args.input, args.output)
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t2c`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/shareholder_data_cleaning.py scripts/clean_qcc_shareholder_data.py tests/test_shareholder_data_cleaning.py
git commit -m "功能：股东数据清洗模块化并改薄脚本"
```

---

## Task 3: 对外投资清洗模块 + 薄脚本

**Files:**
- Create: `src/deepresearch_agent/investment_data_cleaning.py`
- Modify: `scripts/clean_tyc_investment_data.py`（改为薄包装）
- Test: `tests/test_investment_data_cleaning.py`

**Interfaces:**
- Consumes: `vendor_export.unquote` / `clean_cell`（Task 1）；`company_database.normalize_company_name`；`company_data_cleaning.parse_capital` / `normalize_date`。
- Produces:
  - `OUTPUT_COLUMNS`（14 列，见下）
  - `clean_investment_rows(raw_rows) -> list[dict[str, str]]`
  - `run_cleaning(input_path, output_path) -> dict[str, int]`（读 gb18030）

- [ ] **Step 1: 写失败测试 `tests/test_investment_data_cleaning.py`**

```python
import csv

from deepresearch_agent.investment_data_cleaning import (
    OUTPUT_COLUMNS,
    clean_investment_rows,
    run_cleaning,
)


def _header():
    return [
        '="企业名称"', '="被投资企业名称"', '="状态"', '="成立日期"', '="持股比例"',
        '="认缴出资额"', '="最终受益股份"', '="所属地区"', '="所属行业"', '="关联产品/机构"',
    ]


def _row():
    return [
        '="泰尔重工股份有限公司"', '="泰尔智慧（上海）激光科技有限公司"', '="存续"', '="2021-11-24"',
        '="100%"', '="6500万元人民币"', '="100%"', '="上海市闵行区"', '="科学研究和技术服务业"',
        '="泰尔股份"',
    ]


def test_clean_investment_rows_parses_capital_date_and_dedupes():
    raw = [
        ["声明..."],
        [],
        _header() + [""],
        _row() + [""],
        _row() + [""],  # exact dup -> removed
        ['="泰尔重工股份有限公司"', "", '="存续"', "", "", "", "", "", "", "", ""],  # blank investee -> dropped
    ]

    rows = clean_investment_rows(raw)

    assert len(rows) == 1
    row = rows[0]
    assert row["investee_name"] == "泰尔智慧（上海）激光科技有限公司"
    assert row["normalized_investee_name"] == "泰尔智慧(上海)激光科技有限公司"
    assert row["status"] == "存续"
    assert row["investee_established_date"] == "2021-11-24"
    assert row["holding_pct"] == "100%"
    assert row["subscribed_capital_amount"] == "65000000"
    assert row["subscribed_capital_currency"] == "CNY"
    assert row["industry"] == "科学研究和技术服务业"


def test_investment_run_cleaning_reads_gb18030_roundtrip(tmp_path):
    src = tmp_path / "raw.csv"
    with src.open("w", encoding="gb18030", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["声明..."])
        writer.writerow(_header())
        writer.writerow(_row())
    out = tmp_path / "investments.csv"

    summary = run_cleaning(src, out)

    assert summary == {"edges": 1, "investors": 1, "investees": 1, "active_edges": 1}
    with out.open(encoding="utf-8-sig", newline="") as handle:
        got = list(csv.DictReader(handle))
    assert list(got[0].keys()) == OUTPUT_COLUMNS
    assert got[0]["investee_name"] == "泰尔智慧（上海）激光科技有限公司"
    assert got[0]["subscribed_capital_amount"] == "65000000"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_investment_data_cleaning.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t3`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.investment_data_cleaning`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/investment_data_cleaning.py`**

```python
from __future__ import annotations

import csv
from pathlib import Path

from deepresearch_agent.company_data_cleaning import normalize_date, parse_capital
from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.vendor_export import clean_cell, unquote


OUTPUT_COLUMNS = [
    "company_name",
    "normalized_company_name",
    "investee_name",
    "normalized_investee_name",
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
]


def _col(raw: list[str], index: int) -> str:
    return clean_cell(raw[index]) if len(raw) > index else ""


def clean_investment_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header_seen = False
    seen_keys: set[tuple[str, ...]] = set()
    for raw in raw_rows:
        cells = [unquote(cell) for cell in raw]
        if not header_seen:
            if cells and cells[0] == "企业名称":
                header_seen = True
            continue
        if len(cells) < 2:
            continue
        company_name = clean_cell(raw[0])
        investee_name = clean_cell(raw[1])
        if not company_name or not investee_name:
            continue
        amount, currency, original = parse_capital(_col(raw, 5))
        record = {
            "company_name": company_name,
            "normalized_company_name": normalize_company_name(company_name),
            "investee_name": investee_name,
            "normalized_investee_name": normalize_company_name(investee_name),
            "status": _col(raw, 2),
            "investee_established_date": normalize_date(_col(raw, 3)),
            "holding_pct": _col(raw, 4),
            "subscribed_capital_amount": amount,
            "subscribed_capital_currency": currency,
            "subscribed_capital_original": original,
            "final_beneficiary_pct": _col(raw, 6),
            "region": _col(raw, 7),
            "industry": _col(raw, 8),
            "associated_product": _col(raw, 9),
        }
        key = tuple(record[column] for column in OUTPUT_COLUMNS)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(record)
    return rows


def run_cleaning(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    input_path = Path(input_path)
    with input_path.open(encoding="gb18030", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    rows = clean_investment_rows(raw_rows)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "edges": len(rows),
        "investors": len({row["normalized_company_name"] for row in rows}),
        "investees": len({row["normalized_investee_name"] for row in rows}),
        "active_edges": sum(1 for row in rows if row["status"] == "存续"),
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_investment_data_cleaning.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t3b`
Expected: PASS（2 passed）。

- [ ] **Step 5: 把 `scripts/clean_tyc_investment_data.py` 整文件替换为薄包装**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from deepresearch_agent.investment_data_cleaning import run_cleaning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Clean Tianyancha outbound-investment export into an edge CSV.")
    parser.add_argument("--input", type=Path, required=True, help="Source Tianyancha 对外投资 .csv file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/procurement/processed/investments.csv"),
    )
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input file does not exist: {args.input}")

    summary = run_cleaning(args.input, args.output)
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-a1-t3c`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/investment_data_cleaning.py scripts/clean_tyc_investment_data.py tests/test_investment_data_cleaning.py
git commit -m "功能：对外投资数据清洗模块化并改薄脚本"
```

---

## Self-Review

**1. Spec coverage:**
- `vendor_export.py`（`unquote`/`clean_cell`）→ Task 1 ✅
- `shareholder_data_cleaning.py`（9 列、`clean_shareholder_rows`、`run_cleaning` utf-8-sig）→ Task 2 ✅
- `investment_data_cleaning.py`（14 列、`clean_investment_rows`、`run_cleaning` gb18030、复用 `parse_capital`/`normalize_date`）→ Task 3 ✅
- 脚本改薄包装 → Task 2 Step 5、Task 3 Step 5 ✅
- 合成 fixture、不依赖真实数据、gb18030 与 utf-8-sig 各自验证 → Task 2/3 测试 ✅
- 表头定位、缺名称丢弃、整行去重、持股数去逗号、自然人派生 → Task 2/3 测试断言覆盖 ✅
- 错误处理（输入不存在 → 脚本 argparse.error；无表头 → 返回空）→ 脚本薄包装保留；无表头由 `clean_*_rows` 返回空（测试未单列，行为由 header_seen 逻辑保证）✅

**2. Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。✅

**3. Type consistency:**
- `unquote`/`clean_cell` 在 Task 1 定义，Task 2/3 一致调用。
- `OUTPUT_COLUMNS` / `clean_*_rows` / `run_cleaning` 返回 dict 键在各自 Task 定义与测试一致。
- `run_cleaning` 返回键：股东 `{edges,companies,shareholders,person_edges,entity_edges}`、投资 `{edges,investors,investees,active_edges}` —— 与脚本打印、测试断言一致。
- 复用的 `parse_capital`（返回 amount/currency/original）、`normalize_date`、`normalize_company_name` 签名与现有模块一致。

无不一致。
```
