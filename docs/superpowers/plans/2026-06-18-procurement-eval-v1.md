# Procurement Eval v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic evaluation harness for the procurement DeepResearch Agent so supplier recommendations, risk detection, citation coverage, missing-data handling, and retrieval recall can be measured before adding heavier retrieval and database features.

**Architecture:** Add a small `deepresearch_agent.eval` package with typed golden-case models, metric functions, and a runner that calls the existing `run_research()` graph. Golden cases live outside `src` under `evals/procurement/golden_cases.yaml` so domain data can evolve without changing code. The CLI gains an `eval procurement` subcommand while preserving the current single-question research command.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, pytest, existing LangGraph runner.

---

## File Structure

- Create: `evals/procurement/golden_cases.yaml`
  - Stores deterministic procurement evaluation cases.
- Create: `src/deepresearch_agent/eval/__init__.py`
  - Exposes the public eval API.
- Create: `src/deepresearch_agent/eval/models.py`
  - Defines `GoldenCase`, `ExpectedOutcome`, `EvalCaseResult`, and `EvalSummary`.
- Create: `src/deepresearch_agent/eval/metrics.py`
  - Implements pure metric functions with no graph dependency.
- Create: `src/deepresearch_agent/eval/runner.py`
  - Loads golden cases, runs the existing graph, computes metrics.
- Modify: `src/deepresearch_agent/cli.py`
  - Adds `deepresearch eval procurement` while keeping direct question execution.
- Create: `tests/test_eval_models.py`
  - Validates golden-case loading.
- Create: `tests/test_eval_metrics.py`
  - Tests metric behavior without running LangGraph.
- Create: `tests/test_eval_runner.py`
  - Tests end-to-end eval against existing fixtures.
- Modify: `README.md`
  - Documents the eval command and metrics.

---

### Task 1: Add Golden Cases

**Files:**
- Create: `evals/procurement/golden_cases.yaml`
- Test: `tests/test_eval_models.py`

- [ ] **Step 1: Create a failing test for golden-case loading**

Create `tests/test_eval_models.py`:

```python
from pathlib import Path

from deepresearch_agent.eval.runner import load_golden_cases


def test_load_procurement_golden_cases():
    cases = load_golden_cases(Path("evals/procurement/golden_cases.yaml"))

    assert len(cases) == 2
    assert cases[0].case_id == "acme_low_risk_supplier"
    assert cases[0].expected.recommendation == "approve"
    assert "supplier_profile" in cases[0].expected.required_dimensions
    assert cases[1].case_id == "northstar_restricted_supplier"
    assert cases[1].expected.recommendation == "reject"
    assert "sanctions_or_blacklist" in cases[1].expected.expected_risks
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'deepresearch_agent.eval'`.

- [ ] **Step 3: Add the golden cases**

Create `evals/procurement/golden_cases.yaml`:

```yaml
cases:
  - case_id: acme_low_risk_supplier
    question: Assess ACME Sensors for industrial sensor procurement
    expected:
      recommendation: approve
      expected_risks: []
      required_dimensions:
        - supplier_profile
        - compliance
        - delivery_capability
        - negative_news
      required_source_ids:
        - supplier_profile:acme-sensors
        - sanctions:acme-sensors
        - doc:acme-sensors
      allow_missing_data: false

  - case_id: northstar_restricted_supplier
    question: Assess Northstar Components for control module procurement
    expected:
      recommendation: reject
      expected_risks:
        - sanctions_or_blacklist
        - export_restriction
      required_dimensions:
        - supplier_profile
        - compliance
        - delivery_capability
        - negative_news
        - geopolitical_or_sanctions_risk
      required_source_ids:
        - supplier_profile:northstar-components
        - sanctions:northstar-components
        - doc:northstar-components
      allow_missing_data: false
```

- [ ] **Step 4: Add eval models and loader**

Create `src/deepresearch_agent/eval/__init__.py`:

```python
from deepresearch_agent.eval.models import EvalCaseResult, EvalSummary, GoldenCase
from deepresearch_agent.eval.runner import evaluate_cases, load_golden_cases

__all__ = [
    "EvalCaseResult",
    "EvalSummary",
    "GoldenCase",
    "evaluate_cases",
    "load_golden_cases",
]
```

Create `src/deepresearch_agent/eval/models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from deepresearch_agent.state import Recommendation


class ExpectedOutcome(BaseModel):
    recommendation: Recommendation
    expected_risks: list[str] = Field(default_factory=list)
    required_dimensions: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)
    allow_missing_data: bool = False


class GoldenCase(BaseModel):
    case_id: str
    question: str
    expected: ExpectedOutcome


class EvalCaseResult(BaseModel):
    case_id: str
    recommendation_match: bool
    risk_hit_rate: float
    citation_coverage: float
    missing_data_handling: bool
    retrieval_recall_at_k: float
    passed: bool


class EvalSummary(BaseModel):
    total_cases: int
    passed_cases: int
    recommendation_accuracy: float
    average_risk_hit_rate: float
    average_citation_coverage: float
    missing_data_handling_rate: float
    average_retrieval_recall_at_k: float
    case_results: list[EvalCaseResult]
```

Create `src/deepresearch_agent/eval/runner.py` with loader only:

```python
from __future__ import annotations

from pathlib import Path

import yaml

from deepresearch_agent.eval.models import GoldenCase


def load_golden_cases(path: str | Path) -> list[GoldenCase]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(item) for item in payload["cases"]]
```

- [ ] **Step 5: Run the model test**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add evals/procurement/golden_cases.yaml src/deepresearch_agent/eval tests/test_eval_models.py
git commit -m "feat: add procurement eval golden cases"
```

---

### Task 2: Add Pure Metric Functions

**Files:**
- Create: `src/deepresearch_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

- [ ] **Step 1: Write failing metric tests**

Create `tests/test_eval_metrics.py`:

```python
from deepresearch_agent.eval.metrics import (
    citation_coverage,
    missing_data_handling,
    recommendation_match,
    retrieval_recall_at_k,
    risk_hit_rate,
)
from deepresearch_agent.eval.models import ExpectedOutcome
from deepresearch_agent.state import Citation, Evidence, SupplierReport


def _report(
    recommendation: str = "reject",
    risks: list[str] | None = None,
    open_questions: list[str] | None = None,
) -> SupplierReport:
    evidence = [
        Evidence(
            claim="Northstar Components has an export restriction signal.",
            dimension="geopolitical_or_sanctions_risk",
            confidence=0.9,
            citation=Citation(
                source_id="sanctions:northstar-components",
                title="Local sanctions fixture",
                url="local://procurement/sanctions",
                snippet="Export restriction applies.",
            ),
        ),
        Evidence(
            claim="Northstar supplier note mentions control module delivery uncertainty.",
            dimension="delivery_capability",
            confidence=0.8,
            citation=Citation(
                source_id="doc:northstar-components",
                title="Northstar Components Supplier Note",
                url="local://procurement/documents/northstar-components.md",
                snippet="Delivery capacity is not confirmed.",
            ),
        ),
    ]
    return SupplierReport(
        supplier_name="Northstar Components",
        recommendation=recommendation,  # type: ignore[arg-type]
        summary="Supplier should be rejected.",
        risks=risks or ["sanctions_or_blacklist risk found.", "export_restriction risk found."],
        evidence_table=evidence,
        open_questions=open_questions or [],
    )


def test_recommendation_match():
    expected = ExpectedOutcome(recommendation="reject")
    assert recommendation_match(_report(), expected) is True
    assert recommendation_match(_report(recommendation="approve"), expected) is False


def test_risk_hit_rate():
    expected = ExpectedOutcome(
        recommendation="reject",
        expected_risks=["sanctions_or_blacklist", "export_restriction"],
    )
    assert risk_hit_rate(_report(), expected) == 1.0


def test_citation_coverage():
    expected = ExpectedOutcome(
        recommendation="reject",
        required_dimensions=["geopolitical_or_sanctions_risk", "delivery_capability"],
    )
    assert citation_coverage(_report(), expected) == 1.0


def test_missing_data_handling():
    expected = ExpectedOutcome(recommendation="conditional", allow_missing_data=True)
    report = _report(recommendation="conditional", open_questions=["Collect more financial evidence."])
    assert missing_data_handling(report, expected) is True


def test_retrieval_recall_at_k():
    expected = ExpectedOutcome(
        recommendation="reject",
        required_source_ids=["sanctions:northstar-components", "doc:northstar-components"],
    )
    assert retrieval_recall_at_k(_report(), expected) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_metrics.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'deepresearch_agent.eval.metrics'`.

- [ ] **Step 3: Implement metric functions**

Create `src/deepresearch_agent/eval/metrics.py`:

```python
from __future__ import annotations

from deepresearch_agent.eval.models import ExpectedOutcome
from deepresearch_agent.state import SupplierReport


def recommendation_match(report: SupplierReport, expected: ExpectedOutcome) -> bool:
    return report.recommendation == expected.recommendation


def risk_hit_rate(report: SupplierReport, expected: ExpectedOutcome) -> float:
    if not expected.expected_risks:
        return 1.0
    risk_text = " ".join(report.risks).lower()
    hits = sum(1 for risk in expected.expected_risks if risk.lower() in risk_text)
    return hits / len(expected.expected_risks)


def citation_coverage(report: SupplierReport, expected: ExpectedOutcome) -> float:
    if not expected.required_dimensions:
        return 1.0
    covered = {
        item.dimension
        for item in report.evidence_table
        if item.citation.source_id and item.citation.snippet
    }
    hits = sum(1 for dimension in expected.required_dimensions if dimension in covered)
    return hits / len(expected.required_dimensions)


def missing_data_handling(report: SupplierReport, expected: ExpectedOutcome) -> bool:
    if not expected.allow_missing_data:
        return True
    return bool(report.open_questions) or report.recommendation in {"conditional", "insufficient_evidence"}


def retrieval_recall_at_k(report: SupplierReport, expected: ExpectedOutcome) -> float:
    if not expected.required_source_ids:
        return 1.0
    source_ids = {item.citation.source_id for item in report.evidence_table}
    hits = sum(1 for source_id in expected.required_source_ids if source_id in source_ids)
    return hits / len(expected.required_source_ids)
```

- [ ] **Step 4: Run metric tests**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_metrics.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/deepresearch_agent/eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat: add procurement eval metrics"
```

---

### Task 3: Add Eval Runner

**Files:**
- Modify: `src/deepresearch_agent/eval/runner.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_eval_runner.py`:

```python
from pathlib import Path

from deepresearch_agent.eval.runner import evaluate_cases, load_golden_cases


def test_evaluate_procurement_cases():
    cases = load_golden_cases(Path("evals/procurement/golden_cases.yaml"))

    summary = evaluate_cases(cases)

    assert summary.total_cases == 2
    assert summary.passed_cases == 2
    assert summary.recommendation_accuracy == 1.0
    assert summary.average_citation_coverage >= 0.75
    assert summary.average_retrieval_recall_at_k >= 0.75
    assert {case.case_id for case in summary.case_results} == {
        "acme_low_risk_supplier",
        "northstar_restricted_supplier",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_runner.py -v
```

Expected: FAIL with `ImportError` for missing `evaluate_cases`.

- [ ] **Step 3: Implement runner**

Replace `src/deepresearch_agent/eval/runner.py` with:

```python
from __future__ import annotations

from pathlib import Path

import yaml

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.eval.metrics import (
    citation_coverage,
    missing_data_handling,
    recommendation_match,
    retrieval_recall_at_k,
    risk_hit_rate,
)
from deepresearch_agent.eval.models import EvalCaseResult, EvalSummary, GoldenCase


def load_golden_cases(path: str | Path) -> list[GoldenCase]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(item) for item in payload["cases"]]


def evaluate_cases(cases: list[GoldenCase]) -> EvalSummary:
    results: list[EvalCaseResult] = []
    for case in cases:
        state = run_research(case.question)
        if state.report is None:
            raise RuntimeError(f"Case {case.case_id} finished without a report")

        rec_match = recommendation_match(state.report, case.expected)
        risk_rate = risk_hit_rate(state.report, case.expected)
        cite_coverage = citation_coverage(state.report, case.expected)
        missing_ok = missing_data_handling(state.report, case.expected)
        recall = retrieval_recall_at_k(state.report, case.expected)
        passed = (
            rec_match
            and risk_rate == 1.0
            and cite_coverage >= 0.75
            and missing_ok
            and recall >= 0.75
        )
        results.append(
            EvalCaseResult(
                case_id=case.case_id,
                recommendation_match=rec_match,
                risk_hit_rate=risk_rate,
                citation_coverage=cite_coverage,
                missing_data_handling=missing_ok,
                retrieval_recall_at_k=recall,
                passed=passed,
            )
        )

    total = len(results)
    passed_count = sum(1 for result in results if result.passed)
    return EvalSummary(
        total_cases=total,
        passed_cases=passed_count,
        recommendation_accuracy=_avg([1.0 if item.recommendation_match else 0.0 for item in results]),
        average_risk_hit_rate=_avg([item.risk_hit_rate for item in results]),
        average_citation_coverage=_avg([item.citation_coverage for item in results]),
        missing_data_handling_rate=_avg([1.0 if item.missing_data_handling else 0.0 for item in results]),
        average_retrieval_recall_at_k=_avg([item.retrieval_recall_at_k for item in results]),
        case_results=results,
    )


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
```

- [ ] **Step 4: Run runner test**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_eval_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/deepresearch_agent/eval/runner.py tests/test_eval_runner.py
git commit -m "feat: add procurement eval runner"
```

---

### Task 4: Add CLI Eval Command

**Files:**
- Modify: `src/deepresearch_agent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
import pytest

from deepresearch_agent.cli import build_parser


def test_parser_supports_eval_procurement_command():
    parser = build_parser()

    args = parser.parse_args(["eval", "procurement"])

    assert args.command == "eval"
    assert args.domain == "procurement"


def test_parser_supports_research_command():
    parser = build_parser()

    args = parser.parse_args(["research", "Assess ACME Sensors for industrial sensor procurement"])

    assert args.command == "research"
    assert args.question == "Assess ACME Sensors for industrial sensor procurement"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_cli.py -v
```

Expected: FAIL with `ImportError: cannot import name 'build_parser'`.

- [ ] **Step 3: Refactor CLI to support subcommands**

Replace `src/deepresearch_agent/cli.py` with:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.eval.runner import evaluate_cases, load_golden_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DeepResearch supplier assessment and evals.")
    subparsers = parser.add_subparsers(dest="command")

    research_parser = subparsers.add_parser("research", help="Run one research question.")
    research_parser.add_argument("question", help="Research question, including a known supplier name.")

    eval_parser = subparsers.add_parser("eval", help="Run evaluation cases.")
    eval_parser.add_argument("domain", choices=["procurement"], help="Domain eval suite to run.")

    parser.add_argument(
        "legacy_question",
        nargs="?",
        help="Backward-compatible research question. Prefer: deepresearch research <question>.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "eval":
        _run_eval(args.domain)
        return

    question = args.question if args.command == "research" else args.legacy_question
    if not question:
        parser.error("Provide a question or use: deepresearch eval procurement")
    _run_research(question)


def _run_research(question: str) -> None:
    state = run_research(question)
    if state.report is None:
        raise SystemExit("Research finished without a report.")

    console = Console()
    console.print(f"[bold]Supplier:[/bold] {state.report.supplier_name}")
    console.print(f"[bold]Recommendation:[/bold] {state.report.recommendation}")
    console.print(state.report.summary)

    table = Table(title="Evidence")
    table.add_column("Dimension")
    table.add_column("Claim")
    table.add_column("Source")
    for item in state.report.evidence_table:
        table.add_row(item.dimension, item.claim, item.citation.title)
    console.print(table)


def _run_eval(domain: str) -> None:
    path = Path("evals") / domain / "golden_cases.yaml"
    cases = load_golden_cases(path)
    summary = evaluate_cases(cases)

    console = Console()
    console.print(f"[bold]Eval domain:[/bold] {domain}")
    console.print(f"[bold]Passed:[/bold] {summary.passed_cases}/{summary.total_cases}")
    console.print(f"recommendation_accuracy={summary.recommendation_accuracy:.2f}")
    console.print(f"average_risk_hit_rate={summary.average_risk_hit_rate:.2f}")
    console.print(f"average_citation_coverage={summary.average_citation_coverage:.2f}")
    console.print(f"missing_data_handling_rate={summary.missing_data_handling_rate:.2f}")
    console.print(f"average_retrieval_recall_at_k={summary.average_retrieval_recall_at_k:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run CLI parser tests**

Run:

```powershell
.conda-env\python.exe -m pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Verify CLI eval manually**

Run:

```powershell
.conda-env\python.exe -m deepresearch_agent.cli eval procurement
```

Expected output includes:

```text
Eval domain: procurement
Passed: 2/2
recommendation_accuracy=1.00
```

- [ ] **Step 6: Verify backward-compatible research command**

Run:

```powershell
.conda-env\python.exe -m deepresearch_agent.cli "Assess ACME Sensors for industrial sensor procurement"
```

Expected output includes:

```text
Supplier: ACME Sensors
Recommendation: approve
```

- [ ] **Step 7: Commit**

```powershell
git add src/deepresearch_agent/cli.py tests/test_cli.py
git commit -m "feat: add procurement eval cli"
```

---

### Task 5: Document Eval v1

**Files:**
- Modify: `README.md`
- Modify: `docs/eval-plan.md`

- [ ] **Step 1: Update README usage section**

Add this section to `README.md` after the CLI usage section:

```markdown
### Run Procurement Eval

Run the deterministic procurement golden cases:

```powershell
.conda-env\python.exe -m deepresearch_agent.cli eval procurement
```

Eval v1 reports:

- `recommendation_accuracy`: whether the final recommendation matches the golden case.
- `average_risk_hit_rate`: whether expected risk labels appear in the report risks.
- `average_citation_coverage`: whether required research dimensions have citation-backed evidence.
- `missing_data_handling_rate`: whether cases that allow missing public data produce follow-up questions or an insufficient-evidence recommendation.
- `average_retrieval_recall_at_k`: whether required evidence source IDs appear in the evidence table.
```

- [ ] **Step 2: Update eval plan status**

Append this to `docs/eval-plan.md`:

```markdown
## Eval v1 Implementation

Eval v1 uses deterministic golden cases under `evals/procurement/golden_cases.yaml`.
It intentionally avoids an LLM-as-judge so the first eval layer is stable, cheap, and CI-friendly.

The initial metrics are:

- recommendation accuracy
- risk hit rate
- citation coverage
- missing-data handling rate
- retrieval recall at k

LLM-as-judge metrics such as report quality, analytical rigor, and groundedness can be added after the deterministic layer is stable.
```

- [ ] **Step 3: Run full tests**

Run:

```powershell
.conda-env\python.exe -m pytest -v
```

Expected: PASS for all tests.

- [ ] **Step 4: Commit docs**

```powershell
git add README.md docs/eval-plan.md
git commit -m "docs: document procurement eval v1"
```

---

## Self-Review

**Spec coverage:** This plan covers the next concrete project phase: Eval v1. It does not implement database, Qdrant, Redis, MCP, or China public data adapters; those are separate subsystems and should receive separate plans after Eval v1 is merged.

**Placeholder scan:** The plan contains no unresolved placeholders. All new files, commands, and expected outputs are specified.

**Type consistency:** The plan uses existing `Recommendation`, `SupplierReport`, `Evidence`, and `Citation` types from `src/deepresearch_agent/state.py`. New eval models consistently refer to `GoldenCase`, `ExpectedOutcome`, `EvalCaseResult`, and `EvalSummary`.

