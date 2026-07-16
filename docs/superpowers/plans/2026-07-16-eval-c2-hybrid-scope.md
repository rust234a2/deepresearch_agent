# Eval C2 混合 scope 评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 scope 语义检索加混合评测——确定性词面层（CI 下界）+ DeepSeek 判官层（补语义命中），两个数字一起给，诚实标注召回是词面下界。

**Architecture:** 长在现有 `eval/` 包上。词面层纯确定性、零 LLM、CI 安全；判官层复用 `llm/deepseek.py` 的 OpenAI 兼容 client 模式、无 key 降级只出词面。retriever 返回 chunk 命中，按企业代码去重后用**全量经营范围**做词面/判官判定。独立 CLI 子命令 `eval scope-quality`，v1 `eval scope` recall@k 不动。

**Tech Stack:** Python 3.11（`.conda-env/python.exe`）、pydantic、pyyaml、pytest、rich、openai（判官层，`.[llm]` 已装）、bge+FAISS（仅真库/slow）。

## Global Constraints

- **复用同源组件**：走 `ScopeRetriever`（= `run_research` 的 scope 组件），不建第二条检索路径。
- **真名不出库**：查询集是通用能力词、可提交；企业代码/判官结果只在本地聚合，CLI 只打印聚合指标、无企业名。
- **判官数据外发**：DeepSeek 判官把经营范围原文发云端，属用户已授权的云端豁免（与记忆线、网页呈现层同级）；**CLAUDE.md 核心红线文本不删、仅本线豁免**。CI 零网络（fake judge / fake client），真链路标 `@pytest.mark.llm`/`slow`。
- **降级**：无 `DEEPSEEK_API_KEY` 或缺 openai → `build_deepseek_scope_judge()` 返回 None → 跳过判官层、只出词面、不报错。
- **不撞 v1**：新子命令 `eval scope-quality`（`ScopeQueryCase` 无期望码）；v1 `eval scope`（`GoldenScopeCase` 带 `expected_codes`）一字不动。
- **测试命令**：`.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`。
- **提交粒度**：每 Task 结束提交一次，中文提交信息，结尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。**不碰用户未提交的 `llm/deepseek.py`**。

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/deepresearch_agent/company_repository.py` | `iter_business_scopes()` 只读全量经营范围 | Modify |
| `src/deepresearch_agent/eval/models.py` | `ScopeQueryCase` + `ScopeLexicalMetrics` + `ScopeJudgedMetrics` | Modify |
| `src/deepresearch_agent/eval/metrics.py` | `scope_lexical_metrics` + `scope_judged_metrics` 纯函数 | Modify |
| `src/deepresearch_agent/eval/scope_judge.py` | `build_deepseek_scope_judge`（判官，可降级）| Create |
| `src/deepresearch_agent/eval/runner.py` | `load_scope_query_cases` + `run_scope_lexical` + `run_scope_judged` | Modify |
| `src/deepresearch_agent/cli.py` | `eval scope-quality` 子命令（`--judge`）| Modify |
| `evals/procurement/scope_queries.synthetic.yaml` | CI 合成查询集（提交）| Create |
| `evals/procurement/scope_queries.yaml` | 真实通用能力词查询集（提交，无企业数据）| Create |
| `tests/test_company_repository.py` | `iter_business_scopes` 测试 | Modify |
| `tests/test_eval_metrics.py` | 词面/判官指标纯测试 | Modify |
| `tests/test_scope_judge.py` | 判官解析 + 无 key 降级 | Create |
| `tests/test_eval_scope_quality_runner.py` | fake retriever + fixture 库跑 runner（CI）| Create |

---

### Task 1: `CompanyRepository.iter_business_scopes()`

**Files:**
- Modify: `src/deepresearch_agent/company_repository.py`（`iter_aliases` 之后）
- Test: `tests/test_company_repository.py`

**Interfaces:**
- Produces: `iter_business_scopes(self) -> list[tuple[str, str]]`（`(信用代码, 经营范围原文)`，NULL→`""`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_company_repository.py` 末尾追加：

```python
def test_iter_business_scopes_returns_code_scope_pairs(company_database_path):
    repo = CompanyRepository(company_database_path)
    scopes = dict(repo.iter_business_scopes())
    assert len(scopes) == len(repo.get_all_company_names())
    assert "工业设备制造" in scopes["91330000123456789X"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_iter_business_scopes_returns_code_scope_pairs -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`AttributeError: 'CompanyRepository' object has no attribute 'iter_business_scopes'`）

- [ ] **Step 3: 写实现**

在 `src/deepresearch_agent/company_repository.py` 的 `iter_aliases` 方法之后插入：

```python
    def iter_business_scopes(self) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unified_social_credit_code, business_scope FROM companies"
            ).fetchall()
        return [
            (row["unified_social_credit_code"], row["business_scope"] or "")
            for row in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "C2：CompanyRepository.iter_business_scopes 只读全量经营范围

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 模型 + 词面/判官指标

**Files:**
- Modify: `src/deepresearch_agent/eval/models.py`
- Modify: `src/deepresearch_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

**Interfaces:**
- Produces:
  - `ScopeQueryCase(case_id: str, query: str, k: int = 10)`
  - `ScopeLexicalMetrics(total, mean_lexical_precision_at_k, mean_lexical_recall_at_k, mean_lexical_tp_count)`
  - `ScopeJudgedMetrics(total, mean_judged_precision_at_k, mean_noise_at_k, mean_semantic_gain_at_k)`
  - `scope_lexical_metrics(retrieved_per_case: list[set[str]], lexical_tp_per_case: list[set[str]]) -> ScopeLexicalMetrics`
  - `scope_judged_metrics(retrieved_per_case: list[set[str]], judged_cover_per_case: list[set[str]], lexical_tp_per_case: list[set[str]]) -> ScopeJudgedMetrics`

- [ ] **Step 1: 写失败测试**

在 `tests/test_eval_metrics.py` 末尾追加：

```python
def test_scope_lexical_metrics_precision_recall_and_tp_count():
    from deepresearch_agent.eval.metrics import scope_lexical_metrics

    # q1: 召回 {A,Z}，词面 TP {A,B} → precision .5、recall .5、tp 2
    # q2: 召回 {C}，词面 TP {C}     → precision 1、recall 1、tp 1
    m = scope_lexical_metrics([{"A", "Z"}, {"C"}], [{"A", "B"}, {"C"}])
    assert m.total == 2
    assert m.mean_lexical_precision_at_k == 0.75      # (.5 + 1) / 2
    assert m.mean_lexical_recall_at_k == 0.75         # (.5 + 1) / 2
    assert m.mean_lexical_tp_count == 1.5             # (2 + 1) / 2


def test_scope_judged_metrics_gain_over_lexical():
    from deepresearch_agent.eval.metrics import scope_judged_metrics

    # 召回 {A,B}；词面 TP {A}（只 A 字面命中）；判官覆盖 {A,B}（B 是语义命中）
    m = scope_judged_metrics([{"A", "B"}], [{"A", "B"}], [{"A"}])
    assert m.mean_judged_precision_at_k == 1.0        # 2/2
    assert m.mean_noise_at_k == 0.0                   # 1 - 1
    assert m.mean_semantic_gain_at_k == 0.5           # judged 1.0 - lexical .5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py -k scope_lexical -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ImportError: cannot import name 'scope_lexical_metrics'`）

- [ ] **Step 3a: 加模型**

在 `src/deepresearch_agent/eval/models.py` 文件末尾追加：

```python
class ScopeQueryCase(BaseModel):
    case_id: str
    query: str
    k: int = 10


class ScopeLexicalMetrics(BaseModel):
    total: int
    mean_lexical_precision_at_k: float
    mean_lexical_recall_at_k: float
    mean_lexical_tp_count: float


class ScopeJudgedMetrics(BaseModel):
    total: int
    mean_judged_precision_at_k: float
    mean_noise_at_k: float
    mean_semantic_gain_at_k: float
```

- [ ] **Step 3b: 加指标函数**

在 `src/deepresearch_agent/eval/metrics.py` import 段加 `ScopeJudgedMetrics, ScopeLexicalMetrics`，文件末尾追加：

```python
def scope_lexical_metrics(
    retrieved_per_case: list[set[str]], lexical_tp_per_case: list[set[str]]
) -> ScopeLexicalMetrics:
    precisions: list[float] = []
    recalls: list[float] = []
    tp_counts: list[float] = []
    for retrieved, tp in zip(retrieved_per_case, lexical_tp_per_case):
        hit = retrieved & tp
        precisions.append(len(hit) / len(retrieved) if retrieved else 0.0)
        recalls.append(len(hit) / len(tp) if tp else 1.0)
        tp_counts.append(float(len(tp)))
    total = len(retrieved_per_case)
    return ScopeLexicalMetrics(
        total=total,
        mean_lexical_precision_at_k=sum(precisions) / total if total else 0.0,
        mean_lexical_recall_at_k=sum(recalls) / total if total else 1.0,
        mean_lexical_tp_count=sum(tp_counts) / total if total else 0.0,
    )


def scope_judged_metrics(
    retrieved_per_case: list[set[str]],
    judged_cover_per_case: list[set[str]],
    lexical_tp_per_case: list[set[str]],
) -> ScopeJudgedMetrics:
    jprecs: list[float] = []
    noises: list[float] = []
    gains: list[float] = []
    for retrieved, judged, tp in zip(
        retrieved_per_case, judged_cover_per_case, lexical_tp_per_case
    ):
        n = len(retrieved)
        jp = len(judged) / n if n else 0.0
        lp = len(retrieved & tp) / n if n else 0.0
        jprecs.append(jp)
        noises.append(1.0 - jp)
        gains.append(jp - lp)
    total = len(retrieved_per_case)
    return ScopeJudgedMetrics(
        total=total,
        mean_judged_precision_at_k=sum(jprecs) / total if total else 0.0,
        mean_noise_at_k=sum(noises) / total if total else 0.0,
        mean_semantic_gain_at_k=sum(gains) / total if total else 0.0,
    )
```

`metrics.py` 的 import 块加两个名字：

```python
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    PerturbationRobustnessMetrics,
    PerturbationTypeMetrics,
    ScopeJudgedMetrics,
    ScopeLexicalMetrics,
    ScopeRecallMetrics,
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（原有 + 新增 2）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/eval/models.py src/deepresearch_agent/eval/metrics.py tests/test_eval_metrics.py
git commit -m "C2：ScopeQueryCase + 词面/判官指标模型与纯函数

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: DeepSeek 判官 `eval/scope_judge.py`

**Files:**
- Create: `src/deepresearch_agent/eval/scope_judge.py`
- Test: `tests/test_scope_judge.py`

**Interfaces:**
- Produces: `build_deepseek_scope_judge(api_key=None, model="deepseek-chat", base_url="https://api.deepseek.com", client=None) -> Callable[[str, str], bool] | None`（`judge(query, scope) -> bool`）

- [ ] **Step 1: 写失败测试**

`tests/test_scope_judge.py`：

```python
from deepresearch_agent.eval.scope_judge import build_deepseek_scope_judge


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class _FakeCompletions:
    def __init__(self, content): self._content = content
    def create(self, **kw): return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def test_judge_parses_yes():
    judge = build_deepseek_scope_judge(client=_FakeClient("是"))
    assert judge("注塑成型", "从事塑料制品注塑加工") is True


def test_judge_parses_no():
    judge = build_deepseek_scope_judge(client=_FakeClient("否"))
    assert judge("注塑成型", "餐饮服务；住宿服务") is False


def test_judge_false_on_garbage():
    judge = build_deepseek_scope_judge(client=_FakeClient(""))
    assert judge("注塑成型", "任意文本") is False


def test_judge_none_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_scope_judge() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_scope_judge.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.eval.scope_judge`）

- [ ] **Step 3: 写实现**

`src/deepresearch_agent/eval/scope_judge.py`：

```python
from __future__ import annotations

import os
from collections.abc import Callable

_JUDGE_SYSTEM_PROMPT = (
    "你是经营范围覆盖判定器。给定一个能力关键词和一家企业的经营范围原文，"
    "判断该经营范围是否实际覆盖该能力。只输出 是 或 否，不要任何多余文字。"
)


def _parse_bool(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("是"):
        return True
    if stripped.startswith("否"):
        return False
    return ("是" in stripped) and ("否" not in stripped)


def build_deepseek_scope_judge(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> Callable[[str, str], bool] | None:
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0, max_retries=2)

    def judge(query: str, scope: str) -> bool:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"能力：{query}\n经营范围：{scope}"},
                ],
            )
            return _parse_bool(response.choices[0].message.content)
        except Exception:
            return False

    return judge
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_scope_judge.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/eval/scope_judge.py tests/test_scope_judge.py
git commit -m "C2：DeepSeek 经营范围覆盖判官（约束式是/否，无 key 降级 None）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Runner + 合成查询集 + CI runner 测试

**Files:**
- Modify: `src/deepresearch_agent/eval/runner.py`
- Create: `evals/procurement/scope_queries.synthetic.yaml`
- Test: `tests/test_eval_scope_quality_runner.py`

**Interfaces:**
- Consumes: `ScopeRetriever.search(query, k) -> list[ScopeHit]`（`.unified_social_credit_code`）、`repository.iter_business_scopes()`、`scope_lexical_metrics`/`scope_judged_metrics`、`normalize_company_name`。
- Produces:
  - `load_scope_query_cases(path) -> list[ScopeQueryCase]`
  - `run_scope_lexical(retriever, repository, cases) -> ScopeLexicalMetrics`
  - `run_scope_judged(retriever, repository, judge, cases) -> ScopeJudgedMetrics`

- [ ] **Step 1: 建合成查询集**

`evals/procurement/scope_queries.synthetic.yaml`（基于 fixture 经营范围 `工业设备制造；工业设备销售。`）：

```yaml
cases:
  - {case_id: q_equipment, query: 工业设备, k: 10}
```

- [ ] **Step 2: 写失败测试**

`tests/test_eval_scope_quality_runner.py`：

```python
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.models import ScopeQueryCase
from deepresearch_agent.eval.runner import (
    load_scope_query_cases,
    run_scope_judged,
    run_scope_lexical,
)

_CODE = "91330000123456789X"


class _FakeHit:
    def __init__(self, code):
        self.unified_social_credit_code = code


class _FakeRetriever:
    def __init__(self, by_query):
        self._by_query = by_query

    def search(self, query, k):
        return [_FakeHit(c) for c in self._by_query.get(query, [])][:k]


def test_load_scope_query_cases_reads_yaml():
    cases = load_scope_query_cases("evals/procurement/scope_queries.synthetic.yaml")
    assert cases and cases[0].query == "工业设备"
    assert cases[0].k == 10


def test_run_scope_lexical_hits_fixture_scope(company_database_path):
    repo = CompanyRepository(company_database_path)
    cases = [ScopeQueryCase(case_id="q1", query="工业设备", k=10)]
    retriever = _FakeRetriever({"工业设备": [_CODE]})

    m = run_scope_lexical(retriever, repo, cases)

    assert m.total == 1
    assert m.mean_lexical_precision_at_k == 1.0
    assert m.mean_lexical_recall_at_k == 1.0
    assert m.mean_lexical_tp_count == 1.0


def test_run_scope_judged_semantic_gain_over_non_lexical(company_database_path):
    repo = CompanyRepository(company_database_path)
    # "注塑成型" 不在 fixture 经营范围原文里（词面不命中），但假判官说覆盖 → 语义增益
    cases = [ScopeQueryCase(case_id="q1", query="注塑成型", k=10)]
    retriever = _FakeRetriever({"注塑成型": [_CODE]})

    m = run_scope_judged(retriever, repo, lambda q, scope: True, cases)

    assert m.mean_judged_precision_at_k == 1.0
    assert m.mean_noise_at_k == 0.0
    assert m.mean_semantic_gain_at_k == 1.0    # judged 1.0 − lexical 0.0
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_scope_quality_runner.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: FAIL（`ImportError: cannot import name 'run_scope_lexical'`）

- [ ] **Step 4: 写实现**

在 `src/deepresearch_agent/eval/runner.py`：

顶部 import 加：

```python
from deepresearch_agent.company_database import normalize_company_name
```

`from deepresearch_agent.eval.metrics import (...)` 加 `scope_judged_metrics, scope_lexical_metrics`；`from deepresearch_agent.eval.models import (...)` 加 `ScopeJudgedMetrics, ScopeLexicalMetrics, ScopeQueryCase`。

文件末尾追加：

```python
def load_scope_query_cases(path: str | Path) -> list[ScopeQueryCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [ScopeQueryCase.model_validate(item) for item in data["cases"]]


def _lexical_tp(scopes: dict[str, str], query: str) -> set[str]:
    q = normalize_company_name(query)
    return {code for code, scope in scopes.items() if q in normalize_company_name(scope)}


def run_scope_lexical(retriever, repository, cases: list[ScopeQueryCase]) -> ScopeLexicalMetrics:
    scopes = dict(repository.iter_business_scopes())
    retrieved_per_case: list[set[str]] = []
    lexical_tp_per_case: list[set[str]] = []
    for case in cases:
        retrieved = {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        retrieved_per_case.append(retrieved)
        lexical_tp_per_case.append(_lexical_tp(scopes, case.query))
    return scope_lexical_metrics(retrieved_per_case, lexical_tp_per_case)


def run_scope_judged(
    retriever, repository, judge, cases: list[ScopeQueryCase]
) -> ScopeJudgedMetrics:
    scopes = dict(repository.iter_business_scopes())
    retrieved_per_case: list[set[str]] = []
    judged_cover_per_case: list[set[str]] = []
    lexical_tp_per_case: list[set[str]] = []
    for case in cases:
        retrieved = {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        retrieved_per_case.append(retrieved)
        judged_cover_per_case.append(
            {code for code in retrieved if judge(case.query, scopes.get(code, ""))}
        )
        lexical_tp_per_case.append(_lexical_tp(scopes, case.query))
    return scope_judged_metrics(retrieved_per_case, judged_cover_per_case, lexical_tp_per_case)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_scope_quality_runner.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/eval/runner.py evals/procurement/scope_queries.synthetic.yaml tests/test_eval_scope_quality_runner.py
git commit -m "C2：scope 混合 runner（词面 + 判官）+ 合成查询集 + CI fake-retriever 测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: CLI `eval scope-quality`

**Files:**
- Modify: `src/deepresearch_agent/cli.py:124-180`（`_eval_main`）

**Interfaces:**
- Consumes: `load_scope_query_cases`、`run_scope_lexical`、`run_scope_judged`、`build_deepseek_scope_judge`、`load_scope_retriever`、`BgeEmbedder`。
- Produces: CLI 路径 `eval scope-quality --database <db> --index <faiss> --cases <yaml> [--judge]`。

> 注：无 CLI 单测——`scope-quality` 需真 bge + FAISS 索引（与 v1 `eval scope` 一致、v1 也无 cli 单测）；由 Task 6 真库端到端验证。

- [ ] **Step 1: 加 runner import**

在 `_eval_main` 的 `from deepresearch_agent.eval.runner import (...)` 块加三个名字：

```python
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        load_scope_cases,
        load_scope_query_cases,
        run_entity_resolution,
        run_perturbation_robustness,
        run_scope_judged,
        run_scope_lexical,
        run_scope_recall,
    )
```

- [ ] **Step 2: 加子解析器**

在 `p_scope`（`scope` 子解析器，三个 add_argument）之后插入：

```python
    p_scope_quality = sub.add_parser("scope-quality", help="scope 混合评测（词面 + DeepSeek 判官）")
    p_scope_quality.add_argument("--database", required=True)
    p_scope_quality.add_argument("--index", required=True)
    p_scope_quality.add_argument("--cases", required=True)
    p_scope_quality.add_argument("--judge", action="store_true")
```

- [ ] **Step 3: 加分派分支**

把当前 scope 分派的 `else:` 改为 `elif args.kind == "scope":`（内容不变），再追加 `scope-quality` 分支。即分派尾部结构为：

```python
    elif args.kind == "scope":
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        retriever = load_scope_retriever(args.database, args.index, BgeEmbedder())
        m = run_scope_recall(retriever, load_scope_cases(args.cases))
        console.print("[bold]Eval: scope recall@k (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  mean_recall_at_k={m.mean_recall_at_k:.2f}  "
            f"mean_precision_at_k={m.mean_precision_at_k:.2f}"
        )
    else:  # scope-quality
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        repository = CompanyRepository(args.database)
        retriever = load_scope_retriever(args.database, args.index, BgeEmbedder())
        cases = load_scope_query_cases(args.cases)
        lex = run_scope_lexical(retriever, repository, cases)
        console.print("[bold]Eval: scope quality — lexical (procurement)[/bold]")
        console.print(
            f"  cases={lex.total}  lexical_precision@k={lex.mean_lexical_precision_at_k:.2f}  "
            f"lexical_recall@k(下界)={lex.mean_lexical_recall_at_k:.2f}  "
            f"lexical_tp(均)={lex.mean_lexical_tp_count:.1f}"
        )
        if args.judge:
            from deepresearch_agent.eval.scope_judge import build_deepseek_scope_judge

            judge = build_deepseek_scope_judge()
            if judge is None:
                console.print("  [judge] 无 DEEPSEEK_API_KEY 或缺 openai，跳过判官层")
            else:
                jm = run_scope_judged(retriever, repository, judge, cases)
                console.print("[bold]Eval: scope quality — DeepSeek judge[/bold]")
                console.print(
                    f"  cases={jm.total}  judged_precision@k={jm.mean_judged_precision_at_k:.2f}  "
                    f"noise@k={jm.mean_noise_at_k:.2f}  semantic_gain@k={jm.mean_semantic_gain_at_k:.2f}"
                )
```

> 注意：现有代码里 scope 分派是 `if args.kind == "entity": ... elif args.kind == "perturb": ... else:`（else 即 scope）。本步把那个 `else:` 显式改成 `elif args.kind == "scope":` 并新增 `else:  # scope-quality`。

- [ ] **Step 4: 全套测试回归绿**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: PASS（现有 CLI 测试不受影响；scope-quality 无单测）

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/cli.py
git commit -m "C2：CLI eval scope-quality 子命令（词面默认、--judge 加判官、无 key 降级）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 真实查询集 + 真库跑双指标 + 文档 + 合并推送

**Files:**
- Create: `evals/procurement/scope_queries.yaml`（提交，通用能力词、无企业数据）
- Modify: `docs/project-memory.md`（加第 34 条）

- [ ] **Step 1: 全套测试绿**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final`
Expected: 全绿（slow/neo4j/llm 默认排除）

- [ ] **Step 2: 建真实查询集**

`evals/procurement/scope_queries.yaml`（通用制造业能力词，约 15 条；先给一版，Step 3 按词面 TP 数微调）：

```yaml
cases:
  - {case_id: q_injection, query: 注塑, k: 10}
  - {case_id: q_mould, query: 模具, k: 10}
  - {case_id: q_machining, query: 机械加工, k: 10}
  - {case_id: q_hardware, query: 五金, k: 10}
  - {case_id: q_electronic, query: 电子元器件, k: 10}
  - {case_id: q_autoparts, query: 汽车零部件, k: 10}
  - {case_id: q_plastic, query: 塑料制品, k: 10}
  - {case_id: q_sheetmetal, query: 钣金, k: 10}
  - {case_id: q_welding, query: 焊接, k: 10}
  - {case_id: q_surface, query: 表面处理, k: 10}
  - {case_id: q_package, query: 包装材料, k: 10}
  - {case_id: q_rubber, query: 橡胶制品, k: 10}
  - {case_id: q_casting, query: 铸造, k: 10}
  - {case_id: q_automation, query: 自动化设备, k: 10}
  - {case_id: q_cnc, query: 数控, k: 10}
```

- [ ] **Step 3: 建真库 FAISS 索引（若无）并跑词面层（payoff 之一）**

先确认 scope 索引存在；无则构建（需 `.[rag]` + `OPENBLAS_NUM_THREADS=1`）：

```powershell
$env:PYTHONIOENCODING = "utf-8"; $env:OPENBLAS_NUM_THREADS = "1"
# 若 derived/scope_index.faiss 不存在再构建：
# .\.conda-env\python.exe scripts/build_scope_index.py
.\.conda-env\python.exe -m deepresearch_agent.cli eval scope-quality `
  --database data/procurement/derived/companies.sqlite3 `
  --index data/procurement/derived/scope_index.faiss `
  --cases evals/procurement/scope_queries.yaml
```
Expected: 打印词面 `lexical_precision@k / lexical_recall@k(下界) / lexical_tp(均)`。**若某些 query 的 lexical_tp≈0**（词在库里几乎不出现），把该 query 换成库里更常见的能力词后重跑，保证查询集有意义。**把词面表贴给用户。**

- [ ] **Step 4: 跑判官层（有 key 时，payoff 之二）**

```powershell
$env:PYTHONIOENCODING = "utf-8"; $env:OPENBLAS_NUM_THREADS = "1"
.\.conda-env\python.exe -m deepresearch_agent.cli eval scope-quality `
  --database data/procurement/derived/companies.sqlite3 `
  --index data/procurement/derived/scope_index.faiss `
  --cases evals/procurement/scope_queries.yaml --judge
```
Expected: 追加 `judged_precision@k / noise@k / semantic_gain@k`。无 key 则打印跳过提示——如实告诉用户判官层需 `DEEPSEEK_API_KEY`。**把判官表（或跳过说明）贴给用户。**

- [ ] **Step 5: 更新项目记忆**

在 `docs/project-memory.md` 的“最新更新”与“已完成模块”追加第 34 条，概述 C2：混合 scope 评测（词面确定性下界 + DeepSeek 判官补语义命中、`semantic_gain` 量化语义检索净价值、判官数据外发豁免、无 key 降级、独立 `eval scope-quality` 子命令、真库词面/判官数字）。**只记聚合数、无企业名。**

- [ ] **Step 6: 提交并合并推送**

```bash
git add evals/procurement/scope_queries.yaml docs/project-memory.md
git commit -m "C2：真实查询集 + 真库词面/判官双指标 + 项目记忆

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

然后按 finishing-a-development-branch：验证全测试绿 → fast-forward 合并 master → `git push origin master` → 删分支（按 [[push-policy]]，只发代码不发数据；`*.local.yaml`/真库/索引均 gitignore 不进推送）。

---

## Self-Review

**1. Spec coverage（对 spec 第 2 节逐条核）**：
- 查询集可提交（ScopeQueryCase）→ Task 4 合成 + Task 6 真实。✅
- 词面层 `lexical_precision@k`/`lexical_recall@k(下界)`/`lexical_tp_count`（`iter_business_scopes`）→ Task 1、2、4。✅
- 判官层 `judged_precision@k`/`noise@k`/`semantic_gain@k`（DeepSeek，可降级）→ Task 3、4、5。✅
- 独立 `eval scope-quality`、v1 `eval scope` 不动 → Task 5（显式 `elif args.kind == "scope"` 保留原逻辑）。✅
- 红线：查询可提交、判官外发豁免留档、CI 零网络（fake）、真链路 slow/llm → Global Constraints + 各 Task。✅

**2. Placeholder scan**：无 TBD/TODO；每个改码步骤给完整代码。Task 6 的查询集标注“按 TP 微调”是可执行的验证步骤、非占位。✅

**3. Type consistency**：
- `ScopeQueryCase(case_id, query, k)` 在 Task 2 定义，Task 4/5 消费一致。✅
- `scope_lexical_metrics(retrieved_per_case, lexical_tp_per_case)` / `scope_judged_metrics(retrieved_per_case, judged_cover_per_case, lexical_tp_per_case)` 在 Task 2 定义，Task 4 runner 调用一致。✅
- `build_deepseek_scope_judge(...) -> judge(query, scope)->bool` 在 Task 3 定义，Task 4/5 用法一致。✅
- `run_scope_lexical(retriever, repository, cases)` / `run_scope_judged(retriever, repository, judge, cases)` 在 Task 4 定义，Task 5 CLI 调用一致。✅
- `iter_business_scopes() -> list[tuple[str,str]]` 在 Task 1 定义，Task 4 `dict(...)` 消费一致。✅

**已知取舍（非缺陷）**：retriever 返回 chunk、去重到企业级后用**全量经营范围**判定（非仅命中 chunk），故 precision 分母是 top-k 去重后的**企业数**（可能 < k）；与 v1 recall 的“代码集合”口径一致。判官层默认关、无 key 只出词面，CI 全程零网络。
