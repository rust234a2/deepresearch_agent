# Eval v1 确定性评测机制 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Agent 一套确定性、可 CI、可复现的硬指标：企业识别 P/R（零下载核心）+ scope recall@k（slow），复用 `run_research` 同源组件、不建第二条执行路径。

**Architecture:** 新 `eval/` 包：`models.py`（golden case + 指标 Pydantic 模型）、`metrics.py`（纯函数集合运算）、`runner.py`（调 `resolve_supplier`/`ScopeRetriever` 产出结果交给 metrics + 读 YAML）。CLI 加 `eval entity`/`eval scope` 子命令（手动分派保持向后兼容）。双轨 golden：合成提交、真实本地 gitignore。

**Tech Stack:** Python、Pydantic、pyyaml、pytest。复用 `supplier_resolution.resolve_supplier`、`rag.retriever.ScopeRetriever`、`company_database_path` fixture。

## Global Constraints

- **无 LLM、无网络、无 LLM-as-judge**；纯集合运算。不引入 RAGAS/LlamaIndex/Phoenix/Qdrant。
- 复用 `run_research` 同源组件（`resolve_supplier`、`ScopeRetriever`），不建第二条执行路径。
- 推荐准确率/风险命中率 = N/A（Agent 固定 `insufficient_evidence`）；GraphRAG 精准率后置。
- 真实 golden 不出库（`.gitignore` 加 `evals/procurement/*.local.yaml`）；合成 golden 提交。
- scope recall 测试标 `@pytest.mark.slow`（需 bge 模型 + FAISS 索引）；企业识别为零下载 CI 核心。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`。
- 现有单问题 CLI 路径必须保持向后兼容。每任务提交一次；中文提交信息。

## 文件结构

- 新 `src/deepresearch_agent/eval/__init__.py`、`models.py`、`metrics.py`、`runner.py`。
- 新 `evals/procurement/entity_resolution.synthetic.yaml`、`scope_recall.synthetic.yaml`。
- 新 `tests/test_eval_models.py`、`test_eval_metrics.py`、`test_eval_runner.py`、`test_eval_scope_runner.py`。
- 改 `src/deepresearch_agent/cli.py`、`tests/test_cli.py`、`.gitignore`。

---

### Task 1：models + metrics（纯函数，CI 核心）

**Files:**
- Create: `src/deepresearch_agent/eval/__init__.py`、`src/deepresearch_agent/eval/models.py`、`src/deepresearch_agent/eval/metrics.py`
- Test: `tests/test_eval_models.py`、`tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: `CompanyResolution`（`company_models`，字段 `status`/`unified_social_credit_code`）。
- Produces: `GoldenEntityCase`、`GoldenScopeCase`、`EntityResolutionMetrics`、`ScopeRecallMetrics`（models.py）；`entity_resolution_metrics(cases, resolutions) -> EntityResolutionMetrics`、`scope_recall_metrics(cases, retrieved_per_case) -> ScopeRecallMetrics`（metrics.py）。

- [ ] **Step 1: 写失败测试（models）**

创建 `tests/test_eval_models.py`：

```python
import pytest
from pydantic import ValidationError

from deepresearch_agent.eval.models import GoldenEntityCase, GoldenScopeCase


def test_entity_case_resolved_requires_code():
    case = GoldenEntityCase(
        case_id="c1", question="核验甲", expected_status="resolved", expected_code="X"
    )
    assert case.expected_code == "X"


def test_entity_case_not_found_needs_no_code():
    case = GoldenEntityCase(case_id="c2", question="核验无", expected_status="not_found")
    assert case.expected_code is None


def test_scope_case_holds_expected_codes():
    case = GoldenScopeCase(case_id="s1", query="注塑", expected_codes=["X", "Y"], k=5)
    assert case.expected_codes == ["X", "Y"] and case.k == 5


def test_entity_case_rejects_bad_status():
    with pytest.raises(ValidationError):
        GoldenEntityCase(case_id="c3", question="q", expected_status="weird")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_models.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.eval`）

- [ ] **Step 3: 建包 + models**

创建 `src/deepresearch_agent/eval/__init__.py`（空文件）。

创建 `src/deepresearch_agent/eval/models.py`：

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GoldenEntityCase(BaseModel):
    case_id: str
    question: str
    expected_status: Literal["resolved", "ambiguous", "not_found"]
    expected_code: str | None = None
    expected_candidate_codes: list[str] = Field(default_factory=list)


class GoldenScopeCase(BaseModel):
    case_id: str
    query: str
    expected_codes: list[str]
    k: int = 10


class EntityResolutionMetrics(BaseModel):
    total: int
    accuracy: float
    resolved_precision: float
    resolved_recall: float


class ScopeRecallMetrics(BaseModel):
    total: int
    mean_recall_at_k: float
    mean_precision_at_k: float
```

- [ ] **Step 4: 跑 models 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_models.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: PASS（4 项）

- [ ] **Step 5: 写失败测试（metrics）**

创建 `tests/test_eval_metrics.py`：

```python
from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.eval.metrics import entity_resolution_metrics, scope_recall_metrics
from deepresearch_agent.eval.models import GoldenEntityCase, GoldenScopeCase


def _case(cid, status, code=None):
    return GoldenEntityCase(case_id=cid, question="q", expected_status=status, expected_code=code)


def test_entity_metrics_all_correct():
    cases = [_case("a", "resolved", "X"), _case("b", "not_found")]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="X"),
        CompanyResolution(status="not_found"),
    ]
    m = entity_resolution_metrics(cases, resolutions)
    assert m.total == 2 and m.accuracy == 1.0
    assert m.resolved_precision == 1.0 and m.resolved_recall == 1.0


def test_entity_metrics_wrong_code_and_false_resolve():
    cases = [_case("a", "resolved", "X"), _case("b", "not_found")]
    resolutions = [
        CompanyResolution(status="resolved", unified_social_credit_code="Y"),  # 错 code
        CompanyResolution(status="resolved", unified_social_credit_code="Z"),  # 假阳性 resolve
    ]
    m = entity_resolution_metrics(cases, resolutions)
    assert m.accuracy == 0.0
    assert m.resolved_precision == 0.0            # 预测 2 个 resolved，0 个对
    assert m.resolved_recall == 0.0               # 期望 1 个 resolved，0 个对


def test_scope_metrics_partial_and_zero():
    cases = [
        GoldenScopeCase(case_id="s1", query="q", expected_codes=["A", "B"]),
        GoldenScopeCase(case_id="s2", query="q", expected_codes=["C"]),
    ]
    retrieved = [{"A", "Z"}, set()]  # s1 命中 A（recall .5, precision .5）；s2 全丢
    m = scope_recall_metrics(cases, retrieved)
    assert m.total == 2
    assert m.mean_recall_at_k == 0.25             # (0.5 + 0.0) / 2
    assert m.mean_precision_at_k == 0.25          # (0.5 + 0.0) / 2
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: FAIL（`ModuleNotFoundError` / 函数不存在）

- [ ] **Step 7: 实现 metrics**

创建 `src/deepresearch_agent/eval/metrics.py`：

```python
from __future__ import annotations

from deepresearch_agent.company_models import CompanyResolution
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    ScopeRecallMetrics,
)


def entity_resolution_metrics(
    cases: list[GoldenEntityCase], resolutions: list[CompanyResolution]
) -> EntityResolutionMetrics:
    total = len(cases)
    correct = pred_resolved = exp_resolved = correct_resolved = 0
    for case, res in zip(cases, resolutions):
        status_match = res.status == case.expected_status
        if case.expected_status == "resolved":
            exp_resolved += 1
            case_correct = status_match and res.unified_social_credit_code == case.expected_code
        else:
            case_correct = status_match
        if res.status == "resolved":
            pred_resolved += 1
            if case.expected_status == "resolved" and res.unified_social_credit_code == case.expected_code:
                correct_resolved += 1
        if case_correct:
            correct += 1
    return EntityResolutionMetrics(
        total=total,
        accuracy=correct / total if total else 1.0,
        resolved_precision=correct_resolved / pred_resolved if pred_resolved else 1.0,
        resolved_recall=correct_resolved / exp_resolved if exp_resolved else 1.0,
    )


def scope_recall_metrics(
    cases: list[GoldenScopeCase], retrieved_per_case: list[set[str]]
) -> ScopeRecallMetrics:
    recalls: list[float] = []
    precisions: list[float] = []
    for case, retrieved in zip(cases, retrieved_per_case):
        expected = set(case.expected_codes)
        hit = expected & retrieved
        recalls.append(len(hit) / len(expected) if expected else 1.0)
        precisions.append(len(hit) / len(retrieved) if retrieved else 0.0)
    total = len(cases)
    return ScopeRecallMetrics(
        total=total,
        mean_recall_at_k=sum(recalls) / total if total else 1.0,
        mean_precision_at_k=sum(precisions) / total if total else 0.0,
    )
```

- [ ] **Step 8: 跑 metrics 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_metrics.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: PASS（3 项）

- [ ] **Step 9: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: 全绿

- [ ] **Step 10: 提交**

```bash
git add src/deepresearch_agent/eval/__init__.py src/deepresearch_agent/eval/models.py src/deepresearch_agent/eval/metrics.py tests/test_eval_models.py tests/test_eval_metrics.py
git commit -m "功能：Eval-1 golden case 模型与确定性指标（企业识别 P/R、scope recall@k）"
```

---

### Task 2：runner + 合成 golden + gitignore

**Files:**
- Create: `src/deepresearch_agent/eval/runner.py`、`evals/procurement/entity_resolution.synthetic.yaml`、`evals/procurement/scope_recall.synthetic.yaml`
- Modify: `.gitignore`
- Test: `tests/test_eval_runner.py`、`tests/test_eval_scope_runner.py`

**Interfaces:**
- Consumes: `resolve_supplier`（`supplier_resolution`）、`ScopeRetriever.search(query, k) -> list[ScopeHit]`（`hit.unified_social_credit_code`）、Task 1 的 models/metrics。
- Produces: `load_entity_cases(path) -> list[GoldenEntityCase]`、`load_scope_cases(path) -> list[GoldenScopeCase]`、`run_entity_resolution(repository, cases) -> EntityResolutionMetrics`、`run_scope_recall(retriever, cases) -> ScopeRecallMetrics`。

- [ ] **Step 1: 写合成 golden**

创建 `evals/procurement/entity_resolution.synthetic.yaml`：

```yaml
cases:
  - case_id: resolved_legal_name
    question: 核验示例科技股份有限公司
    expected_status: resolved
    expected_code: 91330000123456789X
  - case_id: resolved_via_alias
    question: 核验示例设备有限公司
    expected_status: resolved
    expected_code: 91330000123456789X
  - case_id: not_found
    question: 核验不存在企业
    expected_status: not_found
```

创建 `evals/procurement/scope_recall.synthetic.yaml`：

```yaml
cases:
  - case_id: industrial_equipment
    query: 工业设备制造
    expected_codes:
      - 91330000123456789X
    k: 10
```

- [ ] **Step 2: 写失败测试（entity runner，CI）**

创建 `tests/test_eval_runner.py`：

```python
from pathlib import Path

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.runner import load_entity_cases, run_entity_resolution

GOLDEN = Path("evals/procurement/entity_resolution.synthetic.yaml")


def test_entity_runner_on_synthetic_golden(company_database_path):
    repository = CompanyRepository(company_database_path)
    cases = load_entity_cases(GOLDEN)

    metrics = run_entity_resolution(repository, cases)

    assert metrics.total == 3
    assert metrics.accuracy == 1.0
    assert metrics.resolved_precision == 1.0
    assert metrics.resolved_recall == 1.0
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_runner.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.eval.runner`）

- [ ] **Step 4: 实现 runner**

创建 `src/deepresearch_agent/eval/runner.py`：

```python
from __future__ import annotations

from pathlib import Path

import yaml

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.metrics import entity_resolution_metrics, scope_recall_metrics
from deepresearch_agent.eval.models import (
    EntityResolutionMetrics,
    GoldenEntityCase,
    GoldenScopeCase,
    ScopeRecallMetrics,
)
from deepresearch_agent.supplier_resolution import resolve_supplier


def load_entity_cases(path: str | Path) -> list[GoldenEntityCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenEntityCase.model_validate(item) for item in data["cases"]]


def load_scope_cases(path: str | Path) -> list[GoldenScopeCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenScopeCase.model_validate(item) for item in data["cases"]]


def run_entity_resolution(
    repository: CompanyRepository, cases: list[GoldenEntityCase]
) -> EntityResolutionMetrics:
    resolutions = [resolve_supplier(case.question, repository) for case in cases]
    return entity_resolution_metrics(cases, resolutions)


def run_scope_recall(retriever, cases: list[GoldenScopeCase]) -> ScopeRecallMetrics:
    retrieved_per_case = [
        {hit.unified_social_credit_code for hit in retriever.search(case.query, case.k)}
        for case in cases
    ]
    return scope_recall_metrics(cases, retrieved_per_case)
```

- [ ] **Step 5: 跑 entity runner 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_runner.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: PASS（accuracy=1.0，合成 golden 全对）

- [ ] **Step 6: 写 scope runner 测试（slow）**

创建 `tests/test_eval_scope_runner.py`：

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

GOLDEN = Path("evals/procurement/scope_recall.synthetic.yaml")


@pytest.mark.slow
def test_scope_runner_on_synthetic_golden(company_database_path, tmp_path):
    from build_scope_index import build_scope_index
    from deepresearch_agent.eval.runner import load_scope_cases, run_scope_recall
    from deepresearch_agent.rag.embedding import BgeEmbedder
    from deepresearch_agent.rag.retriever import load_scope_retriever

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, BgeEmbedder())
    retriever = load_scope_retriever(company_database_path, index_path, BgeEmbedder())

    cases = load_scope_cases(GOLDEN)
    metrics = run_scope_recall(retriever, cases)

    assert metrics.total == 1
    assert metrics.mean_recall_at_k == 1.0  # 期望企业应被召回进 top-10
```

- [ ] **Step 7: 跑 scope runner 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_eval_scope_runner.py -m slow -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: PASS（若 `.[rag]`/bge 就绪）。

> 注：默认套件用 `-m 'not slow and not neo4j'` 排除；本步显式 `-m slow` 单跑。若 bge 未装/下载会失败或耗时——这是预期的"下载部分"，本地就绪时验证。

- [ ] **Step 8: `.gitignore` 加真实 golden**

在 `.gitignore` 末尾追加：

```
evals/procurement/*.local.yaml
```

- [ ] **Step 9: 全量回归（默认排除 slow）**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: 全绿（entity runner 通过；scope runner 因 slow 被排除）

- [ ] **Step 10: 提交**

```bash
git add src/deepresearch_agent/eval/runner.py evals/procurement/entity_resolution.synthetic.yaml evals/procurement/scope_recall.synthetic.yaml tests/test_eval_runner.py tests/test_eval_scope_runner.py .gitignore
git commit -m "功能：Eval-2 runner 复用 resolve_supplier/ScopeRetriever + 合成 golden（真实 golden gitignore）"
```

---

### Task 3：CLI `eval` 子命令

**Files:**
- Modify: `src/deepresearch_agent/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_entity_cases`/`run_entity_resolution`/`load_scope_cases`/`run_scope_recall`（Task 2）、`CompanyRepository`。
- Produces: `main(["eval", "entity", "--database", db, "--cases", yaml])` 打印企业识别指标；`main(["eval", "scope", ...])` 打印 scope 指标；现有 `main(["<question>", ...])` 不变。

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加：

```python
def test_cli_eval_entity_prints_metrics(company_database_path, capsys):
    main(
        [
            "eval", "entity",
            "--database", str(company_database_path),
            "--cases", "evals/procurement/entity_resolution.synthetic.yaml",
        ]
    )
    out = capsys.readouterr().out
    assert "entity resolution" in out
    assert "accuracy=1.00" in out


def test_cli_question_path_still_works(company_database_path, tmp_path, capsys):
    main(
        [
            "核验示例科技股份有限公司",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )
    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py::test_cli_eval_entity_prints_metrics -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: FAIL（`eval` 被当成 question 传给 `run_research`，无 "entity resolution" 输出）

- [ ] **Step 3: cli.py 加手动分派 + eval 子命令**

在 `src/deepresearch_agent/cli.py` 顶部 `import argparse` 之后加 `import sys`。

把 `def main(argv: list[str] | None = None) -> None:` 函数体最前面加入分派（现有 parser 逻辑保持在 else 分支/其后不变）：

```python
def main(argv: list[str] | None = None) -> None:
    raw = sys.argv[1:] if argv is None else argv
    if raw and raw[0] == "eval":
        _eval_main(raw[1:])
        return
    parser = argparse.ArgumentParser(description="Run a procurement DeepResearch supplier assessment.")
    # ...（现有 add_argument / parse_args / run_research / 打印逻辑保持不变）
```

在文件末尾（`if __name__ == "__main__":` 之前）新增：

```python
def _eval_main(argv: list[str]) -> None:
    from deepresearch_agent.company_repository import CompanyRepository
    from deepresearch_agent.eval.runner import (
        load_entity_cases,
        load_scope_cases,
        run_entity_resolution,
        run_scope_recall,
    )

    parser = argparse.ArgumentParser(prog="cli eval", description="确定性评测（企业识别 / scope 召回）。")
    sub = parser.add_subparsers(dest="kind", required=True)

    p_entity = sub.add_parser("entity", help="企业识别 P/R")
    p_entity.add_argument("--database", required=True)
    p_entity.add_argument("--cases", required=True)

    p_scope = sub.add_parser("scope", help="scope 检索 recall@k")
    p_scope.add_argument("--database", required=True)
    p_scope.add_argument("--index", required=True)
    p_scope.add_argument("--cases", required=True)

    args = parser.parse_args(argv)
    console = Console()

    if args.kind == "entity":
        repository = CompanyRepository(args.database)
        m = run_entity_resolution(repository, load_entity_cases(args.cases))
        console.print("[bold]Eval: entity resolution (procurement)[/bold]")
        console.print(
            f"  cases={m.total}  accuracy={m.accuracy:.2f}  "
            f"resolved_precision={m.resolved_precision:.2f}  resolved_recall={m.resolved_recall:.2f}"
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

（`Console` 已在 cli.py 顶部从 `rich.console` 导入。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: PASS（新 2 项 + 既有 3 项全绿，向后兼容）

- [ ] **Step 5: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-eval`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/cli.py tests/test_cli.py
git commit -m "功能：Eval-3 CLI eval entity/scope 子命令（手动分派保持单问题路径兼容）"
```

---

## 收尾

三任务完成、全量绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。收尾前文档同步：`docs/architecture.md` 后续能力更新（eval v1 已交付确定性基线）、`project-memory.md`/`CLAUDE.md` 记 eval 包与 CLI；`docs/eval-plan.md` 标注第 1–2 步（golden + 确定性指标）已落地、RAGAS/Phoenix/LLM-judge 仍后置。

## Self-Review

- **Spec 覆盖**：models（golden + 指标）=Task 1；纯函数指标（企业识别 P/R、scope recall@k）=Task 1；runner 复用 `resolve_supplier`/`ScopeRetriever`=Task 2；双轨 golden + gitignore=Task 2；scope 标 slow=Task 2 Step 6-7；CLI 子命令 + 向后兼容=Task 3；N/A 指标与 GraphRAG 后置、不引入 RAGAS/Phoenix=Global Constraints。
- **占位符**：无 TBD/TODO；每步含完整代码。
- **类型一致**：`entity_resolution_metrics(cases, resolutions)` / `scope_recall_metrics(cases, retrieved_per_case)`（Task 1）被 runner（Task 2）以 `resolutions=[resolve_supplier(...)]`、`retrieved_per_case=[{hit.unified_social_credit_code ...}]` 精确喂入；`load_entity_cases`/`run_entity_resolution` 等（Task 2）被 CLI（Task 3）消费；golden YAML 顶层 `cases:` 与 `load_*` 的 `data["cases"]` 一致；`expected_code` 值 `91330000123456789X` 与 fixture 一致。
