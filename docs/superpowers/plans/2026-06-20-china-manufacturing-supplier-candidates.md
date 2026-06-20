# 中国制造业供应商候选名单实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从公开市场企业基础资料中生成最多 5000 家真实中国制造业企业法人名称，并按 15 个制造行业输出 UTF-8 CSV。

**Architecture:** 新增独立的候选名单生成模块，将网络获取、制造业分类、企业去重、行业均衡抽样和 CSV 写出拆成可测试函数。命令行脚本调用公开分页接口获取当前企业法定名称和行业资料；测试使用内存 fixture，不依赖网络。

**Tech Stack:** Python 3.11 标准库、urllib、csv、pytest、东方财富公开企业基础资料接口。

---

## 文件结构

- `src/deepresearch_agent/candidate_generation.py`：候选记录模型、行业分类、去重、均衡选择和 CSV 写出。
- `scripts/generate_china_manufacturing_candidates.py`：分页获取公开企业资料并生成最终名单。
- `tests/test_candidate_generation.py`：覆盖分类、去重、均衡选择和 CSV 编码。
- `data/procurement/candidates/china_manufacturing_supplier_names.csv`：最终候选名单。

### Task 1: 候选名单分类与选择

**Files:**
- Create: `src/deepresearch_agent/candidate_generation.py`
- Test: `tests/test_candidate_generation.py`

- [ ] **Step 1: 编写失败测试**

测试必须覆盖：

```python
def test_classify_candidate_maps_manufacturing_company():
    record = {"ORG_NAME": "示例传感器股份有限公司", "INDUSTRYCSRC1": "仪器仪表制造业", "MAIN_BUSINESS": "工业传感器研发生产"}
    assert classify_candidate(record) == "仪器仪表与传感器"


def test_build_candidates_deduplicates_legal_names():
    records = [
        {"ORG_NAME": "示例电子股份有限公司", "INDUSTRYCSRC1": "计算机、通信和其他电子设备制造业", "MAIN_BUSINESS": "电子元件"},
        {"ORG_NAME": " 示例电子股份有限公司 ", "INDUSTRYCSRC1": "计算机、通信和其他电子设备制造业", "MAIN_BUSINESS": "电子元件"},
    ]
    assert len(build_candidates(records, limit=5000)) == 1


def test_select_balanced_candidates_respects_limit_and_uses_multiple_industries():
    candidates = [Candidate(f"企业{i}", "机械设备") for i in range(10)]
    candidates += [Candidate(f"电子企业{i}", "电子元器件") for i in range(10)]
    selected = select_balanced_candidates(candidates, limit=6)
    assert len(selected) == 6
    assert {item.industry for item in selected} == {"机械设备", "电子元器件"}
```

- [ ] **Step 2: 验证测试因模块缺失而失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_candidate_generation.py -q`

Expected: FAIL，提示 `deepresearch_agent.candidate_generation` 不存在。

- [ ] **Step 3: 实现最小候选生成模块**

实现：

```python
@dataclass(frozen=True)
class Candidate:
    supplier_name: str
    industry: str


def classify_candidate(record: dict) -> str | None:
    text = " ".join(str(record.get(key) or "") for key in ("INDUSTRYCSRC1", "MAIN_BUSINESS", "BUSINESS_SCOPE"))
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return industry
    return None


def build_candidates(records: Iterable[dict], limit: int = 5000) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for record in records:
        name = " ".join(str(record.get("ORG_NAME") or "").split())
        industry = classify_candidate(record)
        if name and industry:
            unique.setdefault(unicodedata.normalize("NFKC", name).casefold(), Candidate(name, industry))
    return select_balanced_candidates(list(unique.values()), limit)
```

`INDUSTRY_KEYWORDS` 必须覆盖设计规格中的 15 个行业，匹配顺序从具体行业到宽泛行业，防止“半导体设备”先被机械设备吸收。

- [ ] **Step 4: 运行目标测试**

Run: `.\.conda-env\python.exe -m pytest tests/test_candidate_generation.py -q`

Expected: PASS。

- [ ] **Step 5: 提交分类模块**

```powershell
git add src/deepresearch_agent/candidate_generation.py tests/test_candidate_generation.py
git commit -m "功能：增加制造业候选企业分类器"
```

### Task 2: 公开企业资料分页获取器

**Files:**
- Create: `scripts/generate_china_manufacturing_candidates.py`
- Modify: `tests/test_candidate_generation.py`

- [ ] **Step 1: 编写分页解析失败测试**

```python
def test_parse_source_page_keeps_active_china_company():
    payload = {
        "result": {
            "pages": 1,
            "data": [{
                "ORG_NAME": "示例设备股份有限公司",
                "LISTING_STATE": "0",
                "COUNTRY": "China 中国",
                "SECUCODE": "000001.SZ",
                "INDUSTRYCSRC1": "专用设备制造业",
                "MAIN_BUSINESS": "工业设备制造",
            }],
        }
    }
    assert parse_source_page(payload)[0]["ORG_NAME"] == "示例设备股份有限公司"
```

- [ ] **Step 2: 验证新测试失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_candidate_generation.py::test_parse_source_page_keeps_active_china_company -q`

Expected: FAIL，提示 `parse_source_page` 不存在。

- [ ] **Step 3: 实现分页获取和来源过滤**

接口固定为：

```text
https://datacenter-web.eastmoney.com/api/data/v1/get
```

请求参数固定为：

```python
{
    "sortColumns": "SECURITY_CODE",
    "sortTypes": "1",
    "pageSize": "500",
    "pageNumber": str(page_number),
    "reportName": "RPT_HSF9_BASIC_ORGINFO",
    "columns": "ALL",
    "source": "WEB",
    "client": "WEB",
}
```

`parse_source_page()` 只保留：

- `LISTING_STATE == "0"`
- `COUNTRY` 包含 `中国` 或 `China`
- `SECUCODE` 以 `.SH`、`.SZ` 或 `.BJ` 结尾
- `ORG_NAME` 非空

使用 `urllib.request.urlopen`，每页最多重试 3 次，超时 30 秒；任何页面最终失败时退出并报告页码，不写出半成品 CSV。

- [ ] **Step 4: 运行分页解析测试和全量测试**

Run: `.\.conda-env\python.exe -m pytest tests/test_candidate_generation.py -q`

Expected: PASS。

- [ ] **Step 5: 提交生成脚本**

```powershell
git add scripts/generate_china_manufacturing_candidates.py tests/test_candidate_generation.py
git commit -m "功能：增加候选企业名单生成脚本"
```

### Task 3: 生成并验收候选名单

**Files:**
- Create: `data/procurement/candidates/china_manufacturing_supplier_names.csv`

- [ ] **Step 1: 运行真实名单生成**

Run:

```powershell
.\.conda-env\python.exe scripts/generate_china_manufacturing_candidates.py --limit 5000 --output data/procurement/candidates/china_manufacturing_supplier_names.csv
```

Expected: 输出获取记录数、制造业候选数、去重后数量和最终写入数量；命令退出码为 0。

- [ ] **Step 2: 验证 CSV**

```powershell
.\.conda-env\python.exe -c "import csv; from collections import Counter; p='data/procurement/candidates/china_manufacturing_supplier_names.csv'; rows=list(csv.DictReader(open(p, encoding='utf-8-sig'))); names=[r['supplier_name'] for r in rows]; industries=Counter(r['industry'] for r in rows); assert 0 < len(rows) <= 5000; assert len(names)==len(set(names)); assert len(industries)==15; assert all(names); print(len(rows), industries)"
```

Expected: 断言全部通过并打印记录数和 15 个行业分布。

- [ ] **Step 3: 运行全量测试和差异检查**

```powershell
.\.conda-env\python.exe -m pytest -q
git diff --check
```

Expected: 测试全部通过，`git diff --check` 无错误。

- [ ] **Step 4: 提交候选名单**

```powershell
git add data/procurement/candidates/china_manufacturing_supplier_names.csv
git commit -m "数据：增加中国制造业供应商候选名单"
```

## 自查

- 规格覆盖：数量上限、15 行业、企业法人名称、去重、UTF-8 CSV 和不虚构名称均有对应任务。
- 边界：候选名单不写入 `suppliers.json`，不改变当前 Agent 识别范围。
- 测试边界：单元测试不调用网络，真实网络仅用于显式生成步骤。

