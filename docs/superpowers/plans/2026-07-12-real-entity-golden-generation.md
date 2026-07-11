# 真实企业识别 Golden 生成 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一个读真库、派生四类企业识别 golden 题（法定名/曾用名/歧义/not_found）的起草脚本，真值取自数据库原始事实、与 `resolve_text` 语义可证明一致。

**Architecture:** 纯生成逻辑放 `eval/golden_gen.py`（对合成 fixture 做 TDD、进 CI）；`scripts/generate_entity_golden.py` 是薄 CLI 壳；给 `CompanyRepository` 加 `iter_aliases()`。真名只写进 gitignored 的 `.local.yaml`，脚本只回聚合条数。

**Tech Stack:** Python 3.11、pydantic（`GoldenEntityCase`）、PyYAML、sqlite3、pytest。环境用 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **独立真值**：golden 答案只来自 DB 原始事实（法定名、alias、代码），绝不从 `resolve_text` 输出反推。
- **红线**：脚本 stdout 只打印各类题条数，绝不打印真企业名；真名只进 `evals/procurement/*.local.yaml`（`.gitignore` 已含）。
- 归一化统一用 `deepresearch_agent.company_database.normalize_company_name`；含名判断统一复用 `deepresearch_agent.company_repository._contains_name`，保证与 `resolve_text` 语义一致。
- 测试用现场构建的合成 sqlite，零真数据；隔离缓存跑：`.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`。
- 不改 `entity_resolution_metrics`；不做 scope；不做全量属性测试。

---

### Task 1: `CompanyRepository.iter_aliases()`

**Files:**
- Modify: `src/deepresearch_agent/company_repository.py`（在 `get_all_company_names` 附近加方法）
- Test: `tests/test_company_repository.py`

**Interfaces:**
- Produces: `CompanyRepository.iter_aliases(self) -> list[tuple[str, str]]` —— 返回全部 `(unified_social_credit_code, alias)`，按 `(code, alias)` 排序保证确定性。

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾追加（复用 conftest 的 `company_database_path`，该 fixture 企业 `91330000123456789X` 的 aliases 为 `示例设备有限公司|示例机械有限公司`）：

```python
def test_iter_aliases_returns_all_code_alias_pairs(company_database_path):
    repo = CompanyRepository(company_database_path)
    pairs = repo.iter_aliases()
    assert ("91330000123456789X", "示例机械有限公司") in pairs
    assert ("91330000123456789X", "示例设备有限公司") in pairs
    # 确定性：按 (code, alias) 升序
    assert pairs == sorted(pairs)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_aliases_returns_all_code_alias_pairs -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: FAIL（`AttributeError: 'CompanyRepository' object has no attribute 'iter_aliases'`）

- [ ] **Step 3: 实现 `iter_aliases`**

在 `company_repository.py` 的 `get_all_company_names` 方法之后插入：

```python
    def iter_aliases(self) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, alias FROM company_aliases "
                "ORDER BY unified_social_credit_code, alias"
            ).fetchall()
        return [(row["unified_social_credit_code"], row["alias"]) for row in rows]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_aliases_returns_all_code_alias_pairs -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：CompanyRepository.iter_aliases 取全部 (代码, 曾用名) 对"
```

---

### Task 2: `golden_gen.py` 纯生成逻辑

**Files:**
- Create: `src/deepresearch_agent/eval/golden_gen.py`
- Test: `tests/test_golden_gen.py`

**Interfaces:**
- Consumes: `GoldenEntityCase`（`eval/models.py`）、`normalize_company_name`、`_contains_name`。
- Produces:
  - `generate_entity_golden(company_names: dict[str, str], aliases: list[tuple[str, str]], *, seed: int = 20260712, n_legal: int = 25, n_alias: int = 15, n_not_found: int = 10, ambiguous_cap: int = 25) -> list[GoldenEntityCase]`
  - `category_counts(cases: list[GoldenEntityCase]) -> dict[str, int]` —— 键 `resolved_legal / resolved_alias / ambiguous / not_found`，按 `case_id` 前缀计数。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_golden_gen.py`：

```python
import csv
from pathlib import Path

import pytest

from deepresearch_agent.company_database import build_company_database, normalize_company_name
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import category_counts, generate_entity_golden
from deepresearch_agent.eval.runner import run_entity_resolution

FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def _code(i: int) -> str:
    return f"91330000{i:010d}"  # 8 + 10 = 18 位，唯一


# C1 变成歧义源（被 C5 的 alias 撞名），故 C1 不进 resolved_legal。
# 干净法定名源：C2 C3 C4 C5；唯一 alias 源：C3 的 "伽马材料有限公司"。
_COMPANIES = [
    {"code": _code(1), "legal_name": "阿尔法精密机械有限公司", "aliases": ""},
    {"code": _code(2), "legal_name": "贝塔电子科技有限公司", "aliases": ""},
    {"code": _code(3), "legal_name": "伽马新材料有限公司", "aliases": "伽马材料有限公司"},
    {"code": _code(4), "legal_name": "德尔塔自动化设备有限公司", "aliases": ""},
    {"code": _code(5), "legal_name": "艾普西隆机床有限公司", "aliases": "阿尔法精密机械有限公司"},
]


@pytest.fixture
def golden_repo(tmp_path) -> CompanyRepository:
    src_lines = (FIXTURES / "companies.csv").read_text(encoding="utf-8").splitlines()
    header = src_lines[0].split(",")
    template = next(csv.DictReader(src_lines))
    comp_path = tmp_path / "companies.csv"
    with comp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for company in _COMPANIES:
            row = dict(template)
            row["source_name"] = company["legal_name"]
            row["legal_name"] = company["legal_name"]
            row["unified_social_credit_code"] = company["code"]
            row["aliases"] = company["aliases"]
            writer.writerow(row)
    cont_path = tmp_path / "contacts.csv"
    with cont_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["unified_social_credit_code", "legal_name", "phones", "emails", "mailing_address"],
        )
        writer.writeheader()
        for company in _COMPANIES:
            writer.writerow(
                {
                    "unified_social_credit_code": company["code"],
                    "legal_name": company["legal_name"],
                    "phones": "",
                    "emails": "",
                    "mailing_address": "",
                }
            )
    db_path = tmp_path / "companies.sqlite3"
    build_company_database(comp_path, cont_path, db_path)
    return CompanyRepository(db_path)


def _generate(repo: CompanyRepository):
    return generate_entity_golden(
        repo.get_all_company_names(),
        repo.iter_aliases(),
        seed=1,
        n_legal=3,
        n_alias=1,
        n_not_found=2,
        ambiguous_cap=25,
    )


def test_category_counts_match_requested(golden_repo):
    cases = _generate(golden_repo)
    assert category_counts(cases) == {
        "resolved_legal": 3,
        "resolved_alias": 1,
        "ambiguous": 1,
        "not_found": 2,
    }


def test_resolved_legal_excludes_homonym(golden_repo):
    cases = _generate(golden_repo)
    legal = [c for c in cases if c.case_id.startswith("resolved_legal")]
    # C1 的法定名撞了 C5 的 alias，绝不能作为 resolved 题
    assert all(c.question != "阿尔法精密机械有限公司" for c in legal)
    # 每条 resolved 题的 expected_code 唯一且正确
    names = golden_repo.get_all_company_names()
    for c in legal:
        assert c.expected_status == "resolved"
        assert names[c.expected_code] == c.question


def test_resolved_alias_case(golden_repo):
    cases = _generate(golden_repo)
    alias = [c for c in cases if c.case_id.startswith("resolved_alias")]
    assert len(alias) == 1
    assert alias[0].question == "伽马材料有限公司"
    assert alias[0].expected_status == "resolved"
    assert alias[0].expected_code == _code(3)


def test_ambiguous_case_has_both_codes(golden_repo):
    cases = _generate(golden_repo)
    amb = [c for c in cases if c.case_id.startswith("ambiguous")]
    assert len(amb) == 1
    assert amb[0].question == "阿尔法精密机械有限公司"
    assert amb[0].expected_status == "ambiguous"
    assert amb[0].expected_candidate_codes == sorted([_code(1), _code(5)])


def test_not_found_questions_contain_no_db_name(golden_repo):
    cases = _generate(golden_repo)
    nf = [c for c in cases if c.case_id.startswith("not_found")]
    assert len(nf) == 2
    db_names = {normalize_company_name(n) for n in golden_repo.get_all_company_names().values()}
    for c in nf:
        assert c.expected_status == "not_found"
        nq = normalize_company_name(c.question)
        assert all(name not in nq for name in db_names)


def test_closed_loop_accuracy_is_one(golden_repo):
    # 生成器与 resolve_text 语义一致的端到端证明
    cases = _generate(golden_repo)
    metrics = run_entity_resolution(golden_repo, cases)
    assert metrics.accuracy == 1.0


def test_deterministic_same_seed(golden_repo):
    a = _generate(golden_repo)
    b = _generate(golden_repo)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: FAIL（`ModuleNotFoundError: No module named 'deepresearch_agent.eval.golden_gen'`）

- [ ] **Step 3: 实现 `golden_gen.py`**

新建 `src/deepresearch_agent/eval/golden_gen.py`：

```python
from __future__ import annotations

import random

from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.company_repository import _contains_name
from deepresearch_agent.eval.models import GoldenEntityCase


def _build_name_index(
    company_names: dict[str, str], aliases: list[tuple[str, str]]
) -> dict[str, set[str]]:
    """归一化名 → 代码集，over 法定名 ∪ 曾用名。真值的唯一来源。"""
    index: dict[str, set[str]] = {}
    for code, legal in company_names.items():
        index.setdefault(normalize_company_name(legal), set()).add(code)
    for code, alias in aliases:
        index.setdefault(normalize_company_name(alias), set()).add(code)
    return index


def generate_entity_golden(
    company_names: dict[str, str],
    aliases: list[tuple[str, str]],
    *,
    seed: int = 20260712,
    n_legal: int = 25,
    n_alias: int = 15,
    n_not_found: int = 10,
    ambiguous_cap: int = 25,
) -> list[GoldenEntityCase]:
    rng = random.Random(seed)
    name_to_codes = _build_name_index(company_names, aliases)
    cases: list[GoldenEntityCase] = []

    # 1) resolved 法定名：归一化法定名唯一映射到本代码（排除同名/被 alias 撞名的）
    legal_pool = sorted(
        code
        for code, legal in company_names.items()
        if name_to_codes[normalize_company_name(legal)] == {code}
    )
    rng.shuffle(legal_pool)
    for i, code in enumerate(legal_pool[:n_legal]):
        cases.append(
            GoldenEntityCase(
                case_id=f"resolved_legal_{i}",
                question=company_names[code],
                expected_status="resolved",
                expected_code=code,
            )
        )

    # 2) resolved 曾用名：该 alias 归一化后唯一映射到本代码
    alias_pool = sorted(
        (code, alias)
        for code, alias in aliases
        if name_to_codes[normalize_company_name(alias)] == {code}
    )
    rng.shuffle(alias_pool)
    for i, (code, alias) in enumerate(alias_pool[:n_alias]):
        cases.append(
            GoldenEntityCase(
                case_id=f"resolved_alias_{i}",
                question=alias,
                expected_status="resolved",
                expected_code=code,
            )
        )

    # 3) ambiguous：归一化名映射到 ≥2 代码；查询用一个原始拼写
    original_by_norm: dict[str, str] = {}
    for code, legal in company_names.items():
        original_by_norm.setdefault(normalize_company_name(legal), legal)
    for code, alias in aliases:
        original_by_norm.setdefault(normalize_company_name(alias), alias)
    ambiguous_norms = sorted(norm for norm, codes in name_to_codes.items() if len(codes) >= 2)
    dropped = max(0, len(ambiguous_norms) - ambiguous_cap)
    for i, norm in enumerate(ambiguous_norms[:ambiguous_cap]):
        cases.append(
            GoldenEntityCase(
                case_id=f"ambiguous_{i}",
                question=original_by_norm[norm],
                expected_status="ambiguous",
                expected_candidate_codes=sorted(name_to_codes[norm]),
            )
        )
    if dropped:
        print(f"[golden_gen] ambiguous 候选超 cap，丢弃 {dropped} 条")

    # 4) not_found：合成名，校验库中无任何名被其包含
    made = 0
    attempt = 0
    while made < n_not_found:
        question = f"核验{seed}号不存在测试企业{attempt}有限公司"
        attempt += 1
        nq = normalize_company_name(question)
        if any(_contains_name(nq, name) for name in name_to_codes):
            continue
        cases.append(
            GoldenEntityCase(
                case_id=f"not_found_{made}",
                question=question,
                expected_status="not_found",
            )
        )
        made += 1

    return cases


def category_counts(cases: list[GoldenEntityCase]) -> dict[str, int]:
    counts = {"resolved_legal": 0, "resolved_alias": 0, "ambiguous": 0, "not_found": 0}
    for case in cases:
        for prefix in counts:
            if case.case_id.startswith(prefix):
                counts[prefix] += 1
                break
    return counts
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: PASS（7 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/eval/golden_gen.py tests/test_golden_gen.py
git commit -m "功能：golden_gen 派生四类企业识别 golden 题(独立真值+闭环校验)"
```

---

### Task 3: `write_golden` + `scripts/generate_entity_golden.py`

**Files:**
- Modify: `src/deepresearch_agent/eval/golden_gen.py`（加 `write_golden`）
- Create: `scripts/generate_entity_golden.py`
- Test: `tests/test_golden_gen.py`（追加 `write_golden` 用例）

**Interfaces:**
- Consumes: `CompanyRepository.get_all_company_names` / `iter_aliases`、`generate_entity_golden`、`category_counts`、`load_entity_cases`。
- Produces: `write_golden(repository, output_path, *, seed=20260712, n_legal=25, n_alias=15, n_not_found=10, ambiguous_cap=25) -> dict[str, int]` —— 写 yaml、返回各类条数（不含任何名字）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_golden_gen.py` 追加：

```python
def test_write_golden_writes_loadable_yaml_and_returns_counts_only(golden_repo, tmp_path):
    from deepresearch_agent.eval.golden_gen import write_golden
    from deepresearch_agent.eval.runner import load_entity_cases

    out = tmp_path / "entity_resolution.local.yaml"
    counts = write_golden(
        golden_repo, out, seed=1, n_legal=3, n_alias=1, n_not_found=2, ambiguous_cap=25
    )
    # 返回值只有整数条数，无企业名（红线：结构上保证只回数字）
    assert counts == {"resolved_legal": 3, "resolved_alias": 1, "ambiguous": 1, "not_found": 2}
    assert all(isinstance(v, int) for v in counts.values())
    # 产出的 yaml 能被评测 loader 正常读回
    cases = load_entity_cases(out)
    assert len(cases) == 7
    assert {c.expected_status for c in cases} == {"resolved", "ambiguous", "not_found"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py::test_write_golden_writes_loadable_yaml_and_returns_counts_only -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: FAIL（`ImportError: cannot import name 'write_golden'`）

- [ ] **Step 3: 实现 `write_golden`**

在 `golden_gen.py` 顶部加 `from pathlib import Path` 与 `import yaml`，并在文件末尾追加：

```python
def _case_to_dict(case: GoldenEntityCase) -> dict:
    data = {
        "case_id": case.case_id,
        "question": case.question,
        "expected_status": case.expected_status,
    }
    if case.expected_code is not None:
        data["expected_code"] = case.expected_code
    if case.expected_candidate_codes:
        data["expected_candidate_codes"] = case.expected_candidate_codes
    return data


def write_golden(
    repository,
    output_path,
    *,
    seed: int = 20260712,
    n_legal: int = 25,
    n_alias: int = 15,
    n_not_found: int = 10,
    ambiguous_cap: int = 25,
) -> dict[str, int]:
    cases = generate_entity_golden(
        repository.get_all_company_names(),
        repository.iter_aliases(),
        seed=seed,
        n_legal=n_legal,
        n_alias=n_alias,
        n_not_found=n_not_found,
        ambiguous_cap=ambiguous_cap,
    )
    payload = {"cases": [_case_to_dict(c) for c in cases]}
    Path(output_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return category_counts(cases)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-golden`
Expected: PASS（8 项）

- [ ] **Step 5: 写脚本 `scripts/generate_entity_golden.py`**

```python
"""起草真实企业识别 golden（读真库 → 写 .local.yaml → 只打印各类条数）。

真企业名只写进 --output 指向的 .local.yaml（Git 忽略）；stdout 绝不打印企业名。
"""

from __future__ import annotations

import argparse

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import write_golden


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="起草真实企业识别 golden（仅本地、不出库）。")
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--output", default="evals/procurement/entity_resolution.local.yaml"
    )
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--n-legal", type=int, default=25)
    parser.add_argument("--n-alias", type=int, default=15)
    parser.add_argument("--n-not-found", type=int, default=10)
    parser.add_argument("--ambiguous-cap", type=int, default=25)
    args = parser.parse_args(argv)

    counts = write_golden(
        CompanyRepository(args.database),
        args.output,
        seed=args.seed,
        n_legal=args.n_legal,
        n_alias=args.n_alias,
        n_not_found=args.n_not_found,
        ambiguous_cap=args.ambiguous_cap,
    )
    total = sum(counts.values())
    print(f"已写入 {args.output}（{total} 条，真名不出库）")
    print(
        f"  法定名={counts['resolved_legal']}  曾用名={counts['resolved_alias']}  "
        f"歧义={counts['ambiguous']}  not_found={counts['not_found']}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 冒烟——脚本对合成 fixture 能跑通、只回数字**

Run（用现成合成 fixture 库，确认脚本端到端不崩、stdout 无企业名）：
```powershell
.\.conda-env\python.exe scripts/generate_entity_golden.py --database tests/fixtures/procurement/does-not-exist.sqlite3 --output .conda-cache/smoke.local.yaml 2>&1 | Select-String "usage|Error"
```
说明：真库不在版本库内，冒烟仅验证脚本参数解析与导入正常（会因库不存在报 `FileNotFoundError`，属预期；真实产出由用户本地对真库运行）。逻辑正确性已由 Task 2/3 的单测覆盖。

- [ ] **Step 7: 全套测试回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-golden-full`
Expected: 全绿（原 193 + 本模块新增用例；0 失败）

- [ ] **Step 8: 提交**

```powershell
git add src/deepresearch_agent/eval/golden_gen.py scripts/generate_entity_golden.py tests/test_golden_gen.py
git commit -m "功能：generate_entity_golden 脚本(写 .local.yaml、只回条数)"
```

---

## 收尾

三个 Task 完成后用 **superpowers:finishing-a-development-branch**：跑全套测试 → present 合并选项。文档同步（`docs/architecture.md`「后续能力」的 eval 扩展条目、`docs/project-memory.md`、CLAUDE.md 常用命令加起草脚本、`docs/eval-plan.md` 标注真实 golden 起草已落地）随收尾一并处理。

## Self-Review

- **Spec 覆盖**：四类题生成（Task 2）、独立真值/闭环校验（Task 2 test）、红线只回数字（Task 3 test + 脚本）、`iter_aliases`（Task 1）、运行方式（脚本）均有对应任务。scope/metrics 改动/全量属性测试按 spec 明确不做。
- **占位符**：无 TBD/TODO，每步含真实代码与命令。
- **类型一致**：`iter_aliases -> list[tuple[str,str]]`、`generate_entity_golden(...)->list[GoldenEntityCase]`、`write_golden(...)->dict[str,int]` 在 Task 间引用一致；`case_id` 前缀 `resolved_legal/resolved_alias/ambiguous/not_found` 与 `category_counts` 解析一致。
