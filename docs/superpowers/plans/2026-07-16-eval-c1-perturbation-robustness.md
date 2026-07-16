# Eval C1 扰动鲁棒性评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给企业识别加一套"真实输入变形"的评测，按扰动类型量化 `resolve_supplier` 的鲁棒性（去后缀/相邻字对调/全半角/整句包裹），产出真库的身份回收率表。

**Architecture:** 全部长在现有 `eval/` 包上，复用 `models / metrics / runner / golden_gen` 四件套。纯确定性、零 LLM、零网络。扰动真值用"来源法"（每条扰动从已知企业 X 生成、理想答案恒为解析到 X），种子唯一性用独立粗粒度子串扫描保证非循环。

**Tech Stack:** Python 3.11（工作区 conda env `.conda-env/python.exe`）、pydantic、pyyaml、pytest、rich（CLI 输出）。

## Global Constraints

- **复用同源组件**：走 `resolve_supplier`（= `run_research` 依赖的同一组件），不建第二条执行路径。
- **真名不出库**：真实 golden 写 `evals/procurement/perturbation.local.yaml`（`.gitignore` 的 `evals/procurement/*.local.yaml` 已覆盖）；脚本 stdout 与 CLI 指标**只有聚合数、无企业名**。
- **非循环真值**：扰动期望 = 来源企业 X，**绝不用 `resolve_text` 反推**；种子唯一性用独立子串扫描（非 resolver 两段式逻辑）。
- **测试命令**：`.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`（隔离缓存目录，避免 Windows 临时目录残留）。
- **提交粒度**：每个 Task 结束提交一次，中文提交信息，结尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/deepresearch_agent/eval/perturb.py` | 4 个纯扰动函数 + `_stem` | Create |
| `src/deepresearch_agent/eval/models.py` | `GoldenEntityCase` 加 `perturbation_type`；两个指标模型 | Modify |
| `src/deepresearch_agent/eval/metrics.py` | `perturbation_metrics` 纯函数 | Modify |
| `src/deepresearch_agent/eval/golden_gen.py` | `generate_perturbation_golden` + counts + write + 扩展 `_case_to_dict` | Modify |
| `src/deepresearch_agent/eval/runner.py` | `run_perturbation_robustness` | Modify |
| `src/deepresearch_agent/cli.py` | `eval perturb` 子命令 | Modify |
| `scripts/generate_perturbation_golden.py` | 薄 CLI，只回条数 | Create |
| `evals/procurement/perturbation.synthetic.yaml` | 提交的合成 golden | Create |
| `tests/test_eval_perturb.py` | 扰动函数单测 | Create |
| `tests/test_eval_metrics.py` | 加 `perturbation_metrics` 单测 | Modify |
| `tests/test_golden_gen.py` | 加扰动生成器测试 | Modify |
| `tests/test_eval_runner.py` | 加合成 golden 端到端测试 | Modify |
| `tests/test_cli.py` | 加 `eval perturb` 解析/输出测试 | Modify |

---

### Task 1: 扰动函数 `eval/perturb.py`

**Files:**
- Create: `src/deepresearch_agent/eval/perturb.py`
- Test: `tests/test_eval_perturb.py`

**Interfaces:**
- Consumes: `deepresearch_agent.company_repository._COMPANY_SUFFIXES`（后缀常量，golden_gen 已有导入 `_contains_name` 的先例）。
- Produces:
  - `drop_suffix(name: str) -> str | None`
  - `transpose(name: str, rng: random.Random) -> str | None`
  - `width_variant(name: str) -> str | None`
  - `noise_wrap(name: str) -> str | None`
  - `_stem(name: str) -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_eval_perturb.py`：

```python
import random

from deepresearch_agent.eval.perturb import (
    drop_suffix,
    noise_wrap,
    transpose,
    width_variant,
)


def test_drop_suffix_removes_trailing_designator():
    assert drop_suffix("示例科技股份有限公司") == "示例科技"
    assert drop_suffix("阿尔法精密机械有限公司") == "阿尔法精密机械"


def test_drop_suffix_none_when_no_suffix():
    assert drop_suffix("示例科技") is None


def test_transpose_swaps_one_adjacent_pair_in_stem():
    # rng 固定 → 取第 0 对相邻字对调，后缀保留
    result = transpose("示例科技股份有限公司", random.Random(0))
    assert result is not None
    assert result != "示例科技股份有限公司"
    assert result.endswith("股份有限公司")
    # 词干长度不变、仍是 4 字 + 原后缀
    assert len(result) == len("示例科技股份有限公司")


def test_transpose_none_when_stem_too_short():
    assert transpose("A公司", random.Random(0)) is None  # 词干 "a" 折叠前 1 字


def test_width_variant_converts_ascii_to_fullwidth():
    # ASCII 字母数字转全角；纯中文名无 ASCII → None
    assert width_variant("ABC智能装备有限公司") == "ＡＢＣ智能装备有限公司"
    assert width_variant("示例科技股份有限公司") is None


def test_noise_wrap_wraps_into_sentence():
    assert noise_wrap("示例科技股份有限公司") == "核验示例科技股份有限公司的工商信息"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_perturb.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.eval.perturb`）

- [ ] **Step 3: 写实现**

`src/deepresearch_agent/eval/perturb.py`：

```python
from __future__ import annotations

import random

from deepresearch_agent.company_repository import _COMPANY_SUFFIXES


def _stem(name: str) -> str:
    """去掉尾部一个公司后缀取词干（后缀表复用 resolver 常量；独立性在匹配逻辑不在此表）。"""
    for suffix in _COMPANY_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def drop_suffix(name: str) -> str | None:
    """去掉尾部一个公司后缀；无已知后缀或去后为空 → None。"""
    for suffix in _COMPANY_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return None


def transpose(name: str, rng: random.Random) -> str | None:
    """词干内随机取一对相邻字符对调（错字的确定性代理）；词干 < 2 字 → None。"""
    stem = _stem(name)
    if len(stem) < 2:
        return None
    i = rng.randrange(len(stem) - 1)
    swapped = stem[:i] + stem[i + 1] + stem[i] + stem[i + 2 :]
    return swapped + name[len(stem) :]


def width_variant(name: str) -> str | None:
    """把 ASCII 字母数字转全角（NFKC 应折回）；无 ASCII 字母数字 → None。"""
    out: list[str] = []
    changed = False
    for ch in name:
        if ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            out.append(chr(ord(ch) + 0xFEE0))
            changed = True
        else:
            out.append(ch)
    return "".join(out) if changed else None


def noise_wrap(name: str) -> str | None:
    """包成整句（测试全名子串段是否被句子干扰）；恒可用。"""
    return f"核验{name}的工商信息"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_perturb.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/eval/perturb.py tests/test_eval_perturb.py
git commit -m "C1：扰动函数（去后缀/对调/全半角/整句包裹）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 指标模型 + `perturbation_metrics`

**Files:**
- Modify: `src/deepresearch_agent/eval/models.py`
- Modify: `src/deepresearch_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: `GoldenEntityCase`（现有）、`CompanyResolution`（`deepresearch_agent.company_models`，字段 `status` / `unified_social_credit_code`）。
- Produces:
  - `GoldenEntityCase.perturbation_type: str | None = None`（新字段）
  - `PerturbationTypeMetrics(perturbation_type, n, recovery, wrong, miss)`
  - `PerturbationRobustnessMetrics(total, overall_recovery, per_type: list[PerturbationTypeMetrics])`
  - `perturbation_metrics(cases: list[GoldenEntityCase], resolutions: list[CompanyResolution]) -> PerturbationRobustnessMetrics`

- [ ] **Step 1: 写失败测试**

在 `tests/test_eval_metrics.py` 末尾追加：

```python
def test_perturbation_metrics_groups_by_type():
    from deepresearch_agent.eval.metrics import perturbation_metrics

    def _p(cid, ptype, code="X"):
        return GoldenEntityCase(
            case_id=cid,
            question="q",
            expected_status="resolved",
            expected_code=code,
            perturbation_type=ptype,
        )

    cases = [
        _p("drop_suffix_0", "drop_suffix"),
        _p("drop_suffix_1", "drop_suffix"),
        _p("transpose_0", "transpose"),
    ]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="X"),  # recovery
        CompanyResolution(status="resolved", unified_social_credit_code="Y"),  # wrong
        CompanyResolution(status="not_found"),                                  # miss
    ]
    m = perturbation_metrics(cases, resolutions)

    assert m.total == 3
    assert m.overall_recovery == 1 / 3
    by_type = {t.perturbation_type: t for t in m.per_type}
    assert by_type["drop_suffix"].n == 2
    assert by_type["drop_suffix"].recovery == 0.5
    assert by_type["drop_suffix"].wrong == 0.5
    assert by_type["drop_suffix"].miss == 0.0
    assert by_type["transpose"].n == 1
    assert by_type["transpose"].miss == 1.0
    # per_type 按扰动类型名排序，稳定输出
    assert [t.perturbation_type for t in m.per_type] == ["drop_suffix", "transpose"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py::test_perturbation_metrics_groups_by_type -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ImportError: cannot import name 'perturbation_metrics'`）

- [ ] **Step 3a: 加模型**

在 `src/deepresearch_agent/eval/models.py`：`GoldenEntityCase` 加字段（放在 `expected_candidate_codes` 之后）：

```python
    perturbation_type: str | None = None
```

文件末尾追加两个模型：

```python
class PerturbationTypeMetrics(BaseModel):
    perturbation_type: str
    n: int
    recovery: float
    wrong: float
    miss: float


class PerturbationRobustnessMetrics(BaseModel):
    total: int
    overall_recovery: float
    per_type: list[PerturbationTypeMetrics]
```

- [ ] **Step 3b: 加指标函数**

在 `src/deepresearch_agent/eval/metrics.py`：import 段加 `PerturbationRobustnessMetrics, PerturbationTypeMetrics`，文件末尾追加：

```python
def perturbation_metrics(
    cases: list[GoldenEntityCase], resolutions: list[CompanyResolution]
) -> PerturbationRobustnessMetrics:
    grouped: dict[str, list[tuple[GoldenEntityCase, CompanyResolution]]] = {}
    for case, res in zip(cases, resolutions):
        grouped.setdefault(case.perturbation_type or "", []).append((case, res))

    per_type: list[PerturbationTypeMetrics] = []
    total = 0
    total_recovered = 0
    for ptype in sorted(grouped):
        pairs = grouped[ptype]
        n = len(pairs)
        recovery = wrong = miss = 0
        for case, res in pairs:
            if res.status == "resolved" and res.unified_social_credit_code == case.expected_code:
                recovery += 1
            elif res.status == "resolved":
                wrong += 1
            else:
                miss += 1
        per_type.append(
            PerturbationTypeMetrics(
                perturbation_type=ptype,
                n=n,
                recovery=recovery / n,
                wrong=wrong / n,
                miss=miss / n,
            )
        )
        total += n
        total_recovered += recovery

    return PerturbationRobustnessMetrics(
        total=total,
        overall_recovery=total_recovered / total if total else 1.0,
        per_type=per_type,
    )
```

`metrics.py` 顶部现有 import 块改为（加两个名字）：

```python
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    PerturbationRobustnessMetrics,
    PerturbationTypeMetrics,
    ScopeRecallMetrics,
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（原有 3 + 新增 1 = 4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/eval/models.py src/deepresearch_agent/eval/metrics.py tests/test_eval_metrics.py
git commit -m "C1：扰动鲁棒性指标模型 + perturbation_metrics（按类型算回收/误解析/漏解析）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 扰动 golden 生成器 `eval/golden_gen.py`

**Files:**
- Modify: `src/deepresearch_agent/eval/golden_gen.py`
- Test: `tests/test_golden_gen.py`

**Interfaces:**
- Consumes: `perturb.drop_suffix/transpose/width_variant/noise_wrap/_stem`；`normalize_company_name`；`GoldenEntityCase`；`repository.get_all_company_names()`（`dict[code, legal]`）、`repository.iter_aliases()`（`list[(code, alias)]`）。
- Produces:
  - `generate_perturbation_golden(company_names, aliases, *, seed=20260716, per_type_n=25) -> list[GoldenEntityCase]`
  - `perturbation_category_counts(cases) -> dict[str, int]`
  - `write_perturbation_golden(repository, output_path, *, seed=20260716, per_type_n=25) -> dict[str, int]`
  - `_PERTURBERS: tuple[str, ...]`

- [ ] **Step 1: 写失败测试**

在 `tests/test_golden_gen.py` 复用 `golden_repo` fixture 前，加一个含 ASCII 企业的独立 fixture 与测试（追加到文件末尾）：

```python
# --- C1 扰动 golden ---

_PERTURB_COMPANIES = [
    {"code": _code(11), "legal_name": "泽塔精密仪器有限公司", "aliases": ""},
    {"code": _code(12), "legal_name": "ABC智能装备有限公司", "aliases": ""},
    # 词干 "西格玛" 是下一家 "西格玛" 的子串 → 词干不唯一 → 不选作种子
    {"code": _code(13), "legal_name": "西格玛有限公司", "aliases": ""},
    {"code": _code(14), "legal_name": "西格玛传感器有限公司", "aliases": ""},
]


@pytest.fixture
def perturb_repo(tmp_path) -> CompanyRepository:
    src_lines = (FIXTURES / "companies.csv").read_text(encoding="utf-8-sig").splitlines()
    header = src_lines[0].split(",")
    template = next(csv.DictReader(src_lines))
    comp_path = tmp_path / "companies.csv"
    with comp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for company in _PERTURB_COMPANIES:
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
        for company in _PERTURB_COMPANIES:
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


def test_perturbation_golden_only_unique_stem_seeds(perturb_repo):
    from deepresearch_agent.eval.golden_gen import generate_perturbation_golden

    cases = generate_perturbation_golden(
        perturb_repo.get_all_company_names(), perturb_repo.iter_aliases(), seed=1
    )
    # 西格玛（词干被 "西格玛传感器" 撞、且它本身是别家子串）不作种子 → 不出现在任何扰动题的来源
    seed_codes = {c.expected_code for c in cases}
    assert _code(13) not in seed_codes
    # 泽塔、ABC 词干唯一 → 是种子
    assert _code(11) in seed_codes
    assert _code(12) in seed_codes


def test_perturbation_golden_all_expected_resolved_with_type(perturb_repo):
    from deepresearch_agent.eval.golden_gen import generate_perturbation_golden

    cases = generate_perturbation_golden(
        perturb_repo.get_all_company_names(), perturb_repo.iter_aliases(), seed=1
    )
    assert cases  # 非空
    for c in cases:
        assert c.expected_status == "resolved"
        assert c.expected_code is not None
        assert c.perturbation_type in {"drop_suffix", "transpose", "width_variant", "noise_wrap"}


def test_perturbation_golden_width_variant_only_from_ascii_company(perturb_repo):
    from deepresearch_agent.eval.golden_gen import generate_perturbation_golden

    cases = generate_perturbation_golden(
        perturb_repo.get_all_company_names(), perturb_repo.iter_aliases(), seed=1
    )
    width_cases = [c for c in cases if c.perturbation_type == "width_variant"]
    # 只有 ABC 那家有 ASCII，能产出全半角扰动
    assert width_cases
    assert all(c.expected_code == _code(12) for c in width_cases)


def test_perturbation_golden_deterministic(perturb_repo):
    from deepresearch_agent.eval.golden_gen import generate_perturbation_golden

    a = generate_perturbation_golden(
        perturb_repo.get_all_company_names(), perturb_repo.iter_aliases(), seed=1
    )
    b = generate_perturbation_golden(
        perturb_repo.get_all_company_names(), perturb_repo.iter_aliases(), seed=1
    )
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_write_perturbation_golden_returns_counts_only(perturb_repo, tmp_path):
    from deepresearch_agent.eval.golden_gen import write_perturbation_golden
    from deepresearch_agent.eval.runner import load_entity_cases

    out = tmp_path / "perturbation.local.yaml"
    counts = write_perturbation_golden(perturb_repo, out, seed=1)
    assert all(isinstance(v, int) for v in counts.values())
    assert set(counts) == {"drop_suffix", "transpose", "width_variant", "noise_wrap"}
    # 产出 yaml 能被评测 loader 读回，且带 perturbation_type
    cases = load_entity_cases(out)
    assert cases
    assert all(c.perturbation_type is not None for c in cases)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final -k perturbation`
Expected: FAIL（`ImportError: cannot import name 'generate_perturbation_golden'`）

- [ ] **Step 3: 写实现**

在 `src/deepresearch_agent/eval/golden_gen.py`：

顶部 import 加：

```python
from deepresearch_agent.eval.perturb import (
    _stem,
    drop_suffix,
    noise_wrap,
    transpose,
    width_variant,
)
```

扩展现有 `_case_to_dict`，在 `return data` 前加：

```python
    if case.perturbation_type is not None:
        data["perturbation_type"] = case.perturbation_type
```

文件末尾追加：

```python
_PERTURBERS: tuple[str, ...] = ("drop_suffix", "transpose", "width_variant", "noise_wrap")


def _apply_perturber(ptype: str, name: str, rng: random.Random) -> str | None:
    if ptype == "drop_suffix":
        return drop_suffix(name)
    if ptype == "transpose":
        return transpose(name, rng)
    if ptype == "width_variant":
        return width_variant(name)
    if ptype == "noise_wrap":
        return noise_wrap(name)
    return None


def _unique_stem_seeds(
    company_names: dict[str, str], aliases: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """选词干（去后缀、≥4 字）在全库唯一的企业作种子。独立粗粒度子串扫描，非 resolver 逻辑。"""
    corpus = [(code, normalize_company_name(legal)) for code, legal in company_names.items()]
    corpus += [(code, normalize_company_name(alias)) for code, alias in aliases]
    seeds: list[tuple[str, str]] = []
    for code, legal in company_names.items():
        stem = normalize_company_name(_stem(legal))
        if len(stem) < 4:
            continue
        if any(other_code != code and stem in other_norm for other_code, other_norm in corpus):
            continue
        seeds.append((code, legal))
    return sorted(seeds)


def generate_perturbation_golden(
    company_names: dict[str, str],
    aliases: list[tuple[str, str]],
    *,
    seed: int = 20260716,
    per_type_n: int = 25,
) -> list[GoldenEntityCase]:
    rng = random.Random(seed)
    seeds = _unique_stem_seeds(company_names, aliases)
    all_norm_names = [(code, normalize_company_name(n)) for code, n in company_names.items()]
    cases: list[GoldenEntityCase] = []
    for ptype in _PERTURBERS:
        order = list(seeds)
        rng.shuffle(order)
        made = 0
        for code, legal in order:
            if made >= per_type_n:
                break
            perturbed = _apply_perturber(ptype, legal, rng)
            if perturbed is None:
                continue
            nperturbed = normalize_company_name(perturbed)
            # 来源纯净：跳过意外重引别家完整名的扰动
            if any(oc != code and on and on in nperturbed for oc, on in all_norm_names):
                continue
            cases.append(
                GoldenEntityCase(
                    case_id=f"{ptype}_{made}",
                    question=perturbed,
                    expected_status="resolved",
                    expected_code=code,
                    perturbation_type=ptype,
                )
            )
            made += 1
    return cases


def perturbation_category_counts(cases: list[GoldenEntityCase]) -> dict[str, int]:
    counts = {ptype: 0 for ptype in _PERTURBERS}
    for case in cases:
        if case.perturbation_type in counts:
            counts[case.perturbation_type] += 1
    return counts


def write_perturbation_golden(
    repository,
    output_path,
    *,
    seed: int = 20260716,
    per_type_n: int = 25,
) -> dict[str, int]:
    cases = generate_perturbation_golden(
        repository.get_all_company_names(),
        repository.iter_aliases(),
        seed=seed,
        per_type_n=per_type_n,
    )
    payload = {"cases": [_case_to_dict(c) for c in cases]}
    Path(output_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return perturbation_category_counts(cases)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（原有 + 新增 5 全绿）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/eval/golden_gen.py tests/test_golden_gen.py
git commit -m "C1：扰动 golden 生成器（来源法 + 唯一词干种子 + 来源纯净）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Runner + 合成 golden 端到端

**Files:**
- Modify: `src/deepresearch_agent/eval/runner.py`
- Create: `evals/procurement/perturbation.synthetic.yaml`
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `resolve_supplier`（现有 import）、`perturbation_metrics`、`load_entity_cases`（现有，已能读带 `perturbation_type` 的 YAML）。
- Produces: `run_perturbation_robustness(repository, cases) -> PerturbationRobustnessMetrics`

- [ ] **Step 1: 建合成 golden**

`evals/procurement/perturbation.synthetic.yaml`（源自 fixture 唯一企业 `示例科技股份有限公司` / `91330000123456789X`；扰动串手工算好、行为确定）：

```yaml
cases:
  - case_id: drop_suffix_0
    question: 示例科技
    expected_status: resolved
    expected_code: 91330000123456789X
    perturbation_type: drop_suffix
  - case_id: noise_wrap_0
    question: 核验示例科技股份有限公司的工商信息
    expected_status: resolved
    expected_code: 91330000123456789X
    perturbation_type: noise_wrap
  - case_id: transpose_0
    question: 例示科技股份有限公司
    expected_status: resolved
    expected_code: 91330000123456789X
    perturbation_type: transpose
```

> 说明：`示例科技`（去后缀）与整句包裹都应解析回 X（回收）；`例示科技股份有限公司`（词干 4 字对调、破坏唯一 ≥4 字片段）应 not_found（漏解析）。这坐实"resolver 无模糊匹配、短词干对调即崩"。

- [ ] **Step 2: 写失败测试**

在 `tests/test_eval_runner.py` 末尾追加：

```python
def test_perturbation_runner_on_synthetic_golden(company_database_path):
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        run_perturbation_robustness,
    )

    repository = CompanyRepository(company_database_path)
    cases = load_entity_cases("evals/procurement/perturbation.synthetic.yaml")

    m = run_perturbation_robustness(repository, cases)

    assert m.total == 3
    by_type = {t.perturbation_type: t for t in m.per_type}
    assert by_type["drop_suffix"].recovery == 1.0
    assert by_type["noise_wrap"].recovery == 1.0
    assert by_type["transpose"].miss == 1.0     # 短词干对调 → not_found
    assert m.overall_recovery == 2 / 3
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_runner.py::test_perturbation_runner_on_synthetic_golden -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ImportError: cannot import name 'run_perturbation_robustness'`）

- [ ] **Step 4: 写实现**

在 `src/deepresearch_agent/eval/runner.py`：import 段的 `from deepresearch_agent.eval.metrics import ...` 加 `perturbation_metrics`；`from deepresearch_agent.eval.models import ...` 加 `PerturbationRobustnessMetrics`。文件末尾追加：

```python
def run_perturbation_robustness(
    repository: CompanyRepository, cases: list[GoldenEntityCase]
) -> PerturbationRobustnessMetrics:
    resolutions = [resolve_supplier(case.question, repository) for case in cases]
    return perturbation_metrics(cases, resolutions)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_runner.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（原有 1 + 新增 1 = 2 passed）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/eval/runner.py evals/procurement/perturbation.synthetic.yaml tests/test_eval_runner.py
git commit -m "C1：扰动鲁棒性 runner + 合成 golden 端到端（去后缀/整句回收、短词干对调漏解析）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: CLI `eval perturb`

**Files:**
- Modify: `src/deepresearch_agent/cli.py:124-166`（`_eval_main`）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_perturbation_robustness`、`load_entity_cases`、`CompanyRepository`、`Console`。
- Produces: CLI 路径 `eval perturb --database <db> --cases <yaml>`，输出按类型表、无真名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加：

```python
def test_cli_eval_perturb_prints_type_table(company_database_path, capsys):
    main(
        [
            "eval", "perturb",
            "--database", str(company_database_path),
            "--cases", "evals/procurement/perturbation.synthetic.yaml",
        ]
    )
    out = capsys.readouterr().out
    assert "perturbation robustness" in out
    assert "drop_suffix" in out
    assert "transpose" in out
    assert "overall_recovery=" in out
    # 红线：不泄露企业名
    assert "示例科技" not in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py::test_cli_eval_perturb_prints_type_table -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（argparse `invalid choice: 'perturb'` → SystemExit）

- [ ] **Step 3: 写实现**

在 `src/deepresearch_agent/cli.py` 的 `_eval_main`：

runner import 块加 `run_perturbation_robustness`：

```python
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        load_scope_cases,
        run_entity_resolution,
        run_perturbation_robustness,
        run_scope_recall,
    )
```

在 `p_entity` 三行之后、`p_scope` 之前插入子解析器：

```python
    p_perturb = sub.add_parser("perturb", help="扰动鲁棒性（按类型回收率）")
    p_perturb.add_argument("--database", required=True)
    p_perturb.add_argument("--cases", required=True)
```

把分派 `if args.kind == "entity": ... else: ...` 改为 `elif` 链，在 entity 分支后、scope（`else`→改成 `elif args.kind == "scope"`... 保持 scope 逻辑不变）之间加 perturb 分支。最终分派结构：

```python
    if args.kind == "entity":
        repository = CompanyRepository(args.database)
        m = run_entity_resolution(repository, load_entity_cases(args.cases))
        console.print("[bold]Eval: entity resolution (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  accuracy={m.accuracy:.2f}  "
            f"resolved_precision={m.resolved_precision:.2f}  resolved_recall={m.resolved_recall:.2f}"
        )
    elif args.kind == "perturb":
        repository = CompanyRepository(args.database)
        m = run_perturbation_robustness(repository, load_entity_cases(args.cases))
        console.print("[bold]Eval: perturbation robustness (procurement)[/bold]")
        console.print(f"  total={m.total}  overall_recovery={m.overall_recovery:.2f}")
        for t in m.per_type:
            console.print(
                f"  {t.perturbation_type:14} n={t.n}  recovery={t.recovery:.2f}  "
                f"wrong={t.wrong:.2f}  miss={t.miss:.2f}"
            )
    else:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        retriever = load_scope_retriever(args.database, args.index, BgeEmbedder())
        m = run_scope_recall(retriever, load_scope_cases(args.cases))
        console.print("[bold]Eval: scope recall@k (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  mean_recall_at_k={m.mean_recall_at_k:.2f}  "
            f"mean_precision_at_k={m.mean_precision_at_k:.2f}"
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（含新增 1，其余回归绿）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/cli.py tests/test_cli.py
git commit -m "C1：CLI eval perturb 子命令（按类型回收率表、无真名）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 起草脚本 `scripts/generate_perturbation_golden.py`

**Files:**
- Create: `scripts/generate_perturbation_golden.py`
- Test: `tests/test_golden_gen.py`（加脚本 stdout 测试）

**Interfaces:**
- Consumes: `write_perturbation_golden`、`CompanyRepository`。
- Produces: `main(argv=None)`，stdout 只打印各扰动类型条数。

- [ ] **Step 1: 写失败测试**

在 `tests/test_golden_gen.py` 末尾追加：

```python
def test_generate_perturbation_script_prints_counts_only(perturb_repo, tmp_path, capsys, monkeypatch):
    # perturb_repo fixture 已在 tmp_path 下建好 companies.sqlite3，脚本直接读该库
    db = tmp_path / "companies.sqlite3"
    out = tmp_path / "perturbation.local.yaml"

    scripts_dir = Path(__file__).parent.parent / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import generate_perturbation_golden as script

    script.main(["--database", str(db), "--output", str(out), "--seed", "1"])
    printed = capsys.readouterr().out
    # 只回条数与文件名，绝不出现企业名
    assert "泽塔精密仪器有限公司" not in printed
    assert "ABC智能装备有限公司" not in printed
    assert "drop_suffix=" in printed
    assert out.exists()
```

> 注：`perturb_repo` fixture 在 `tmp_path` 下建了 `companies.sqlite3`，脚本直接读该库。`Path` 已在 `test_golden_gen.py` 顶部导入。

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py::test_generate_perturbation_script_prints_counts_only -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ModuleNotFoundError: generate_perturbation_golden`）

- [ ] **Step 3: 写实现**

`scripts/generate_perturbation_golden.py`：

```python
"""起草真实扰动鲁棒性 golden（读真库 → 写 .local.yaml → 只打印各扰动类型条数）。

真企业名只写进 --output 指向的 .local.yaml（Git 忽略）；stdout 绝不打印企业名。
"""

from __future__ import annotations

import argparse

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import write_perturbation_golden


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="起草真实扰动鲁棒性 golden（仅本地、不出库）。")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", default="evals/procurement/perturbation.local.yaml")
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--per-type-n", type=int, default=25)
    args = parser.parse_args(argv)

    counts = write_perturbation_golden(
        CompanyRepository(args.database),
        args.output,
        seed=args.seed,
        per_type_n=args.per_type_n,
    )
    total = sum(counts.values())
    print(f"已写入 {args.output}（{total} 条，真名不出库）")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_golden_gen.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/generate_perturbation_golden.py tests/test_golden_gen.py
git commit -m "C1：真实扰动 golden 起草脚本（stdout 只回条数、真名不出库）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: 真库跑出鲁棒性表 + 全测试 + 文档 + 推送

**Files:**
- Modify: `docs/project-memory.md`（加第 33 条）

- [ ] **Step 1: 全套测试绿**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: 全绿（原有 + C1 新增，slow/neo4j/llm 默认排除）

- [ ] **Step 2: 真库生成扰动 golden（真名不出库）**

Run（PowerShell，先设 UTF-8 避免中文乱码）：

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.conda-env\python.exe scripts/generate_perturbation_golden.py `
  --database data/procurement/derived/companies.sqlite3
```
Expected: stdout 只打印 `已写入 ...（N 条，真名不出库）` + 各类型条数。

- [ ] **Step 3: 真库跑鲁棒性表（payoff）**

Run:

```powershell
.\.conda-env\python.exe -m deepresearch_agent.cli eval perturb `
  --database data/procurement/derived/companies.sqlite3 `
  --cases evals/procurement/perturbation.local.yaml
```
Expected: 打印 total / overall_recovery / 四类型 recovery/wrong/miss 表。**把这张表贴给用户**（这是 C1 的产出）。

- [ ] **Step 4: 更新项目记忆**

在 `docs/project-memory.md` 的"最新更新"与"已完成模块"追加第 33 条，概述 C1：扰动鲁棒性评测（来源法 golden、四扰动类型、按类型回收率、真库表数字、真名不出库、非循环真值）。记录真库 overall_recovery 与各类型数字（**只记聚合数、无企业名**）。

- [ ] **Step 5: 提交并推送**

```bash
git add docs/project-memory.md
git commit -m "C1：扰动鲁棒性评测收尾（真库鲁棒性表 + 项目记忆）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin master
```
（按 [[push-policy]]：模块完成 + 全测试绿后自动推 master，只发代码不发数据；`perturbation.local.yaml` 被 gitignore、不会进推送。）

---

## Self-Review

**1. Spec coverage（对 spec 第 1 节逐条核）**：
- 真值来源法 + 独立唯一性扫描 → Task 3 `_unique_stem_seeds`。✅
- 4 扰动类型 → Task 1。✅
- `perturbation_type` 字段 + 两指标模型 → Task 2。✅
- 生成器 + counts + write + 薄 CLI（stdout 只回数）→ Task 3、Task 6。✅
- runner + CLI `eval perturb`（按类型、无真名）→ Task 4、Task 5。✅
- 合成 golden（提交）→ Task 4。✅
- 红线：真名不出库、非循环 → Global Constraints + Task 6/7 断言。✅
- 测试矩阵（perturb/metrics/golden_gen/runner/cli）→ 各 Task。✅

**2. Placeholder scan**：无 TBD/TODO；每个改码步骤都给了完整代码。✅

**3. Type consistency**：
- `PerturbationRobustnessMetrics(total, overall_recovery, per_type)` / `PerturbationTypeMetrics(perturbation_type, n, recovery, wrong, miss)` 在 Task 2 定义，Task 4/5 消费一致。✅
- `run_perturbation_robustness(repository, cases)` 在 Task 4 定义，Task 5/7 用法一致。✅
- `generate_perturbation_golden(company_names, aliases, *, seed, per_type_n)` 在 Task 3 定义，Task 6 `write_perturbation_golden` 调用一致。✅
- `perturbation_metrics(cases, resolutions)` 在 Task 2 定义，Task 4 runner 调用一致。✅

**已知放宽点（非缺陷）**：`width_variant` 对纯中文名返回 None，故纯 CJK 库该类型可能条数少甚至为 0——真库跑时按实际 n 呈现（Task 7 表里如实反映），不补造。
