# Procurement DeepResearch Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable open-source DeepResearch Agent v1 for supplier due diligence in procurement and supply-chain scenarios.

**Architecture:** The project is a small FastAPI-ready Python package with a LangGraph research loop: plan, retrieve, critique, optionally retrieve again, then write a cited supplier report. Domain-specific behavior lives in a procurement domain pack; tools are exposed through a registry that can later be backed by MCP servers.

**Tech Stack:** Python 3.11, LangGraph, LangChain Core, Pydantic v2, FastAPI, pytest, PyYAML, Rich, optional LangSmith tracing.

---

## Scope

This plan implements v1 only:

- Supplier due diligence as the first procurement domain.
- Local deterministic fixtures for suppliers, news, sanctions, and documents.
- LangGraph stateful loop with conditional edge from critique back to retrieval.
- Tool schema, permission tier, timeout metadata, and trace events.
- Tests for state models, domain loading, tools, retrieval, graph routing, report generation, and API entrypoint.

This plan does not implement real paid APIs, production Qdrant, PostgresSaver, Redis, or Kubernetes. Those belong to later milestones after v1 is demonstrably working.

## File Structure

- `pyproject.toml`: package metadata, dependencies, pytest config.
- `README.md`: project purpose, quickstart, architecture, example command.
- `.env.example`: optional provider keys and tracing flags.
- `src/deepresearch_agent/__init__.py`: package version.
- `src/deepresearch_agent/state.py`: Pydantic state, evidence, citations, plans, reports.
- `src/deepresearch_agent/domain.py`: domain pack loader and validation.
- `src/deepresearch_agent/tools/base.py`: tool protocol, registry, permission tiers, trace envelope.
- `src/deepresearch_agent/tools/procurement.py`: deterministic procurement tools for v1.
- `src/deepresearch_agent/retrieval/local.py`: local keyword retriever with citation-ready snippets.
- `src/deepresearch_agent/agents/nodes.py`: planner, researcher, critic, writer node functions.
- `src/deepresearch_agent/agents/graph.py`: LangGraph construction and run helper.
- `src/deepresearch_agent/api.py`: FastAPI app exposing `/research`.
- `src/deepresearch_agent/cli.py`: command-line demo runner.
- `domains/procurement/domain.yaml`: procurement domain pack.
- `data/procurement/suppliers.json`: supplier fixture data.
- `data/procurement/documents/*.md`: local supplier documents.
- `tests/`: focused tests matching each module.

---

### Task 1: Project Scaffold and Core State Models

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.env.example`
- Create: `src/deepresearch_agent/__init__.py`
- Create: `src/deepresearch_agent/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing state model tests**

Create `tests/test_state.py`:

```python
from deepresearch_agent.state import (
    Citation,
    Evidence,
    ResearchState,
    SupplierReport,
)


def test_research_state_defaults():
    state = ResearchState(
        question="Assess ACME Sensors for industrial sensor procurement",
        domain="procurement",
    )

    assert state.question.startswith("Assess ACME")
    assert state.domain == "procurement"
    assert state.iteration == 0
    assert state.max_iterations == 3
    assert state.plan == []
    assert state.evidence == []
    assert state.trace == []


def test_evidence_requires_citation():
    citation = Citation(
        source_id="supplier_profile:acme-sensors",
        title="ACME Sensors profile",
        url="local://suppliers/acme-sensors",
        snippet="ISO 9001 certified supplier with two manufacturing sites.",
    )
    evidence = Evidence(
        claim="ACME Sensors has quality certification.",
        dimension="compliance",
        confidence=0.82,
        citation=citation,
    )

    assert evidence.citation.source_id == "supplier_profile:acme-sensors"
    assert evidence.dimension == "compliance"


def test_supplier_report_contains_recommendation_and_evidence():
    report = SupplierReport(
        supplier_name="ACME Sensors",
        recommendation="conditional",
        summary="Suitable if delivery capacity is confirmed.",
        risks=["Delivery capacity is not independently verified."],
        evidence_table=[
            Evidence(
                claim="ACME Sensors has ISO 9001 certification.",
                dimension="compliance",
                confidence=0.82,
                citation=Citation(
                    source_id="supplier_profile:acme-sensors",
                    title="ACME Sensors profile",
                    url="local://suppliers/acme-sensors",
                    snippet="ISO 9001 certified supplier.",
                ),
            )
        ],
        open_questions=["Confirm current monthly production capacity."],
    )

    assert report.recommendation == "conditional"
    assert report.evidence_table[0].claim.startswith("ACME")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_state.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'deepresearch_agent'`.

- [ ] **Step 3: Add project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "deepresearch-agent"
version = "0.1.0"
description = "A pluggable LangGraph DeepResearch Agent for cited supplier due diligence reports."
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111.0",
  "langchain-core>=0.3.0",
  "langgraph>=0.2.0",
  "pydantic>=2.7.0",
  "pyyaml>=6.0.1",
  "rich>=13.7.0",
  "uvicorn>=0.30.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2.0",
  "pytest-cov>=5.0.0",
]

[project.scripts]
deepresearch = "deepresearch_agent.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Add package version**

Create `src/deepresearch_agent/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Add state models**

Create `src/deepresearch_agent/state.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Recommendation = Literal["approve", "conditional", "reject", "insufficient_evidence"]


class Citation(BaseModel):
    source_id: str
    title: str
    url: str | HttpUrl
    snippet: str


class Evidence(BaseModel):
    claim: str
    dimension: str
    confidence: float = Field(ge=0.0, le=1.0)
    citation: Citation


class ResearchPlanItem(BaseModel):
    dimension: str
    question: str
    priority: int = Field(ge=1, le=5)


class ToolTrace(BaseModel):
    tool_name: str
    args: dict
    status: Literal["ok", "error"]
    latency_ms: int
    permission_tier: str


class SupplierReport(BaseModel):
    supplier_name: str
    recommendation: Recommendation
    summary: str
    risks: list[str]
    evidence_table: list[Evidence]
    open_questions: list[str]


class ResearchState(BaseModel):
    question: str
    domain: str
    supplier_name: str | None = None
    iteration: int = 0
    max_iterations: int = 3
    plan: list[ResearchPlanItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    report: SupplierReport | None = None
    trace: list[ToolTrace] = Field(default_factory=list)
```

- [ ] **Step 6: Add starter docs**

Create `.env.example`:

```bash
OPENAI_API_KEY=
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
DEEPRESEARCH_DOMAIN=procurement
```

Create `README.md`:

```markdown
# DeepResearch Agent

A pluggable LangGraph DeepResearch Agent for supplier due diligence in procurement and supply-chain workflows.

## v1 Scope

The first domain pack is `procurement`. It researches a supplier, gathers cited evidence, critiques evidence coverage, loops when evidence is insufficient, and writes a supplier due diligence report.

## Quickstart

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
pytest
deepresearch "Assess ACME Sensors for industrial sensor procurement"
```

## Architecture

```text
Planner -> Researcher -> Critic -> Researcher when evidence is missing -> Writer
```
```

- [ ] **Step 7: Run the tests and verify they pass**

Run:

```bash
pip install -e ".[dev]"
pytest tests/test_state.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pyproject.toml README.md .env.example src/deepresearch_agent/__init__.py src/deepresearch_agent/state.py tests/test_state.py
git commit -m "feat: add project scaffold and research state models"
```

Expected: commit succeeds. If the workspace is not a git repository, run `git init` first only if the project owner agrees.

---

### Task 2: Procurement Domain Pack Loader

**Files:**
- Create: `src/deepresearch_agent/domain.py`
- Create: `domains/procurement/domain.yaml`
- Test: `tests/test_domain.py`

- [ ] **Step 1: Write the failing domain loader tests**

Create `tests/test_domain.py`:

```python
from pathlib import Path

from deepresearch_agent.domain import load_domain_pack


def test_load_procurement_domain_pack():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.name == "procurement"
    assert "supplier_profile" in pack.research_dimensions
    assert "search_supplier_docs" in pack.allowed_tools
    assert pack.report_sections[0] == "Executive Summary"


def test_domain_pack_defines_hitl_policy():
    pack = load_domain_pack(Path("domains/procurement/domain.yaml"))

    assert pack.hitl_policy.high_risk_recommendation is True
    assert pack.hitl_policy.missing_compliance_evidence is True
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_domain.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `deepresearch_agent.domain`.

- [ ] **Step 3: Add the domain pack model and loader**

Create `src/deepresearch_agent/domain.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class HitlPolicy(BaseModel):
    high_risk_recommendation: bool
    missing_compliance_evidence: bool
    conflicting_claims: bool


class DomainPack(BaseModel):
    name: str
    description: str
    research_dimensions: list[str]
    allowed_tools: list[str]
    report_sections: list[str]
    source_priority: list[str]
    hitl_policy: HitlPolicy


def load_domain_pack(path: Path) -> DomainPack:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DomainPack.model_validate(data)
```

- [ ] **Step 4: Add the procurement domain pack**

Create `domains/procurement/domain.yaml`:

```yaml
name: procurement
description: Supplier due diligence for procurement and supply-chain decisions.
research_dimensions:
  - supplier_profile
  - product_capability
  - delivery_capability
  - compliance
  - financial_stability
  - negative_news
  - geopolitical_or_sanctions_risk
allowed_tools:
  - search_supplier_docs
  - search_public_news
  - check_sanctions_or_blacklist
  - extract_supplier_profile
  - generate_risk_matrix
report_sections:
  - Executive Summary
  - Supplier Profile
  - Product Capability
  - Delivery Capability
  - Compliance and Certifications
  - Risk Signals
  - Evidence Table
  - Recommendation
  - Open Questions
source_priority:
  - official_supplier_documents
  - government_or_regulatory_lists
  - credible_news
  - internal_procurement_records
hitl_policy:
  high_risk_recommendation: true
  missing_compliance_evidence: true
  conflicting_claims: true
```

- [ ] **Step 5: Run the tests and verify they pass**

Run:

```bash
pytest tests/test_domain.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/deepresearch_agent/domain.py domains/procurement/domain.yaml tests/test_domain.py
git commit -m "feat: add procurement domain pack loader"
```

Expected: commit succeeds.

---

### Task 3: Tool Registry and Procurement Fixture Tools

**Files:**
- Create: `src/deepresearch_agent/tools/base.py`
- Create: `src/deepresearch_agent/tools/procurement.py`
- Create: `data/procurement/suppliers.json`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/test_tools.py`:

```python
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def test_supplier_profile_tool_returns_structured_result():
    registry = build_procurement_tool_registry()

    result = registry.run("extract_supplier_profile", {"supplier_name": "ACME Sensors"})

    assert result.name == "extract_supplier_profile"
    assert result.status == "ok"
    assert result.data["supplier_name"] == "ACME Sensors"
    assert result.permission_tier == "read_public"


def test_sanctions_tool_flags_known_risk_supplier():
    registry = build_procurement_tool_registry()

    result = registry.run("check_sanctions_or_blacklist", {"company_name": "Northstar Components"})

    assert result.status == "ok"
    assert result.data["listed"] is True
    assert "export restriction" in result.data["reason"].lower()


def test_unknown_tool_raises_key_error():
    registry = build_procurement_tool_registry()

    try:
        registry.run("missing_tool", {})
    except KeyError as exc:
        assert "missing_tool" in str(exc)
    else:
        raise AssertionError("missing tool should raise KeyError")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_tools.py -v
```

Expected: FAIL because `deepresearch_agent.tools` does not exist.

- [ ] **Step 3: Add tool base classes**

Create `src/deepresearch_agent/tools/base.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field


PermissionTier = Literal["read_public", "read_private", "write", "human_approval"]


class ToolResult(BaseModel):
    name: str
    status: Literal["ok", "error"]
    data: dict
    latency_ms: int
    permission_tier: PermissionTier


class RegisteredTool(BaseModel):
    name: str
    description: str
    permission_tier: PermissionTier
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    handler: Callable[[dict], dict]

    class Config:
        arbitrary_types_allowed = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, args: dict) -> ToolResult:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")

        tool = self._tools[name]
        started = perf_counter()
        try:
            data = tool.handler(args)
            status = "ok"
        except Exception as exc:  # pragma: no cover - error path is integration-tested later
            data = {"error": str(exc)}
            status = "error"
        latency_ms = int((perf_counter() - started) * 1000)

        return ToolResult(
            name=name,
            status=status,
            data=data,
            latency_ms=latency_ms,
            permission_tier=tool.permission_tier,
        )
```

- [ ] **Step 4: Add supplier fixture data**

Create `data/procurement/suppliers.json`:

```json
[
  {
    "supplier_name": "ACME Sensors",
    "country": "Malaysia",
    "products": ["industrial temperature sensor", "pressure sensor"],
    "certifications": ["ISO 9001", "RoHS"],
    "delivery_capacity": "Two manufacturing sites; stated monthly capacity of 120000 sensor units.",
    "risk_summary": "No sanctions match in local fixture. Delivery capacity requires customer reference confirmation.",
    "listed": false,
    "listing_reason": ""
  },
  {
    "supplier_name": "Northstar Components",
    "country": "Unknown",
    "products": ["control module"],
    "certifications": [],
    "delivery_capacity": "Capacity not disclosed.",
    "risk_summary": "Local fixture marks the company as restricted for export-control concerns.",
    "listed": true,
    "listing_reason": "Matched local export restriction fixture."
  }
]
```

- [ ] **Step 5: Add procurement tools**

Create `src/deepresearch_agent/tools/procurement.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


DATA_PATH = Path("data/procurement/suppliers.json")


def _load_suppliers() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _find_supplier(name: str) -> dict:
    normalized = name.lower()
    for supplier in _load_suppliers():
        if supplier["supplier_name"].lower() == normalized:
            return supplier
    raise ValueError(f"Unknown supplier: {name}")


def _extract_supplier_profile(args: dict) -> dict:
    supplier = _find_supplier(args["supplier_name"])
    return {
        "supplier_name": supplier["supplier_name"],
        "country": supplier["country"],
        "products": supplier["products"],
        "certifications": supplier["certifications"],
        "delivery_capacity": supplier["delivery_capacity"],
        "risk_summary": supplier["risk_summary"],
    }


def _check_sanctions_or_blacklist(args: dict) -> dict:
    supplier = _find_supplier(args["company_name"])
    return {
        "company_name": supplier["supplier_name"],
        "listed": supplier["listed"],
        "reason": supplier["listing_reason"] or "No match in local sanctions fixture.",
    }


def build_procurement_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            name="extract_supplier_profile",
            description="Return a structured profile for a supplier from local fixture data.",
            permission_tier="read_public",
            handler=_extract_supplier_profile,
        )
    )
    registry.register(
        RegisteredTool(
            name="check_sanctions_or_blacklist",
            description="Check whether a supplier appears in the local sanctions fixture.",
            permission_tier="read_public",
            handler=_check_sanctions_or_blacklist,
        )
    )
    return registry
```

- [ ] **Step 6: Run the tests and verify they pass**

Run:

```bash
pytest tests/test_tools.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/deepresearch_agent/tools/base.py src/deepresearch_agent/tools/procurement.py data/procurement/suppliers.json tests/test_tools.py
git commit -m "feat: add procurement tool registry"
```

Expected: commit succeeds.

---

### Task 4: Local Retrieval With Citation-Ready Evidence

**Files:**
- Create: `src/deepresearch_agent/retrieval/local.py`
- Create: `data/procurement/documents/acme-sensors.md`
- Create: `data/procurement/documents/northstar-components.md`
- Test: `tests/test_retrieval.py`

- [ ] **Step 1: Write failing retrieval tests**

Create `tests/test_retrieval.py`:

```python
from deepresearch_agent.retrieval.local import LocalDocumentRetriever


def test_retriever_returns_citation_ready_results():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search("ACME Sensors ISO 9001 delivery capacity", limit=2)

    assert results
    assert results[0].source_id.startswith("doc:")
    assert "ACME" in results[0].title
    assert results[0].snippet


def test_retriever_ranks_matching_supplier_above_other_docs():
    retriever = LocalDocumentRetriever("data/procurement/documents")

    results = retriever.search("Northstar export restriction", limit=2)

    assert results[0].title == "Northstar Components Supplier Note"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_retrieval.py -v
```

Expected: FAIL because `deepresearch_agent.retrieval` does not exist.

- [ ] **Step 3: Add local procurement documents**

Create `data/procurement/documents/acme-sensors.md`:

```markdown
# ACME Sensors Supplier Brief

ACME Sensors manufactures industrial temperature sensors and pressure sensors.
The supplier states that it operates two manufacturing sites in Malaysia.
Its profile lists ISO 9001 and RoHS certifications.
The stated monthly capacity is 120000 sensor units.
No local sanctions fixture match is present.
Procurement should confirm recent on-time delivery performance before approving long-term contracts.
```

Create `data/procurement/documents/northstar-components.md`:

```markdown
# Northstar Components Supplier Note

Northstar Components sells control modules for industrial equipment.
The supplier does not disclose current production capacity.
The local risk fixture marks Northstar Components with an export restriction concern.
No current ISO 9001 certificate is available in the local supplier packet.
Procurement should reject or escalate this supplier until compliance evidence is reviewed.
```

- [ ] **Step 4: Add local retriever**

Create `src/deepresearch_agent/retrieval/local.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetrievalResult:
    source_id: str
    title: str
    url: str
    snippet: str
    score: float


class LocalDocumentRetriever:
    def __init__(self, document_dir: str | Path) -> None:
        self.document_dir = Path(document_dir)
        self.documents = self._load_documents()

    def _load_documents(self) -> list[tuple[Path, str, str]]:
        docs: list[tuple[Path, str, str]] = []
        for path in sorted(self.document_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            docs.append((path, title, text))
        return docs

    def search(self, query: str, limit: int = 5) -> list[RetrievalResult]:
        query_terms = self._terms(query)
        scored: list[RetrievalResult] = []
        for path, title, text in self.documents:
            text_terms = self._terms(text)
            overlap = query_terms.intersection(text_terms)
            if not overlap:
                continue
            score = len(overlap) / max(len(query_terms), 1)
            scored.append(
                RetrievalResult(
                    source_id=f"doc:{path.stem}",
                    title=title,
                    url=f"local://procurement/documents/{path.name}",
                    snippet=self._snippet(text, overlap),
                    score=score,
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {term.lower() for term in re.findall(r"[A-Za-z0-9]+", text)}

    @staticmethod
    def _snippet(text: str, overlap: set[str]) -> str:
        for sentence in re.split(r"(?<=[.])\s+", text.replace("\n", " ")):
            sentence_terms = LocalDocumentRetriever._terms(sentence)
            if sentence_terms.intersection(overlap):
                return sentence[:280]
        return text.replace("\n", " ")[:280]
```

- [ ] **Step 5: Run the tests and verify they pass**

Run:

```bash
pytest tests/test_retrieval.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/deepresearch_agent/retrieval/local.py data/procurement/documents tests/test_retrieval.py
git commit -m "feat: add local citation retriever"
```

Expected: commit succeeds.

---

### Task 5: Agent Nodes

**Files:**
- Create: `src/deepresearch_agent/agents/nodes.py`
- Test: `tests/test_nodes.py`

- [ ] **Step 1: Write failing node tests**

Create `tests/test_nodes.py`:

```python
from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def test_planner_extracts_supplier_and_dimensions():
    state = ResearchState(
        question="Assess ACME Sensors for industrial sensor procurement",
        domain="procurement",
    )

    updated = planner_node(state)

    assert updated.supplier_name == "ACME Sensors"
    assert [item.dimension for item in updated.plan] == [
        "supplier_profile",
        "compliance",
        "delivery_capability",
        "negative_news",
    ]


def test_researcher_collects_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )

    updated = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
    )

    assert updated.evidence
    assert any(item.dimension == "compliance" for item in updated.evidence)
    assert updated.trace


def test_critic_identifies_missing_dimensions_when_evidence_is_empty():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )

    updated = critique_node(state)

    assert "supplier_profile" in updated.missing_dimensions


def test_writer_creates_report_from_evidence():
    state = planner_node(
        ResearchState(
            question="Assess ACME Sensors for industrial sensor procurement",
            domain="procurement",
        )
    )
    state = researcher_node(
        state,
        retriever=LocalDocumentRetriever("data/procurement/documents"),
        tools=build_procurement_tool_registry(),
    )
    state = critique_node(state)

    updated = writer_node(state)

    assert updated.report is not None
    assert updated.report.supplier_name == "ACME Sensors"
    assert updated.report.recommendation in {"approve", "conditional"}
    assert updated.report.evidence_table
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_nodes.py -v
```

Expected: FAIL because `deepresearch_agent.agents.nodes` does not exist.

- [ ] **Step 3: Add deterministic agent nodes**

Create `src/deepresearch_agent/agents/nodes.py`:

```python
from __future__ import annotations

from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import Citation, Evidence, ResearchPlanItem, ResearchState, SupplierReport, ToolTrace
from deepresearch_agent.tools.base import ToolRegistry


def planner_node(state: ResearchState) -> ResearchState:
    supplier_name = _extract_supplier_name(state.question)
    state.supplier_name = supplier_name
    state.plan = [
        ResearchPlanItem(dimension="supplier_profile", question=f"What is {supplier_name}'s business profile?", priority=1),
        ResearchPlanItem(dimension="compliance", question=f"What certifications or restrictions apply to {supplier_name}?", priority=1),
        ResearchPlanItem(dimension="delivery_capability", question=f"What delivery capacity evidence exists for {supplier_name}?", priority=2),
        ResearchPlanItem(dimension="negative_news", question=f"What risk signals exist for {supplier_name}?", priority=3),
    ]
    return state


def researcher_node(
    state: ResearchState,
    retriever: LocalDocumentRetriever,
    tools: ToolRegistry,
) -> ResearchState:
    if state.supplier_name is None:
        raise ValueError("planner_node must set supplier_name before researcher_node")

    profile_result = tools.run("extract_supplier_profile", {"supplier_name": state.supplier_name})
    state.trace.append(
        ToolTrace(
            tool_name=profile_result.name,
            args={"supplier_name": state.supplier_name},
            status=profile_result.status,
            latency_ms=profile_result.latency_ms,
            permission_tier=profile_result.permission_tier,
        )
    )
    if profile_result.status == "ok":
        data = profile_result.data
        state.evidence.append(
            Evidence(
                claim=f"{state.supplier_name} supplies {', '.join(data['products'])}.",
                dimension="supplier_profile",
                confidence=0.8,
                citation=Citation(
                    source_id=f"supplier_profile:{state.supplier_name.lower().replace(' ', '-')}",
                    title=f"{state.supplier_name} local supplier profile",
                    url=f"local://suppliers/{state.supplier_name.lower().replace(' ', '-')}",
                    snippet=data["risk_summary"],
                ),
            )
        )
        if data["certifications"]:
            state.evidence.append(
                Evidence(
                    claim=f"{state.supplier_name} lists certifications: {', '.join(data['certifications'])}.",
                    dimension="compliance",
                    confidence=0.78,
                    citation=Citation(
                        source_id=f"supplier_profile:{state.supplier_name.lower().replace(' ', '-')}",
                        title=f"{state.supplier_name} local supplier profile",
                        url=f"local://suppliers/{state.supplier_name.lower().replace(' ', '-')}",
                        snippet=", ".join(data["certifications"]),
                    ),
                )
            )

    sanctions_result = tools.run("check_sanctions_or_blacklist", {"company_name": state.supplier_name})
    state.trace.append(
        ToolTrace(
            tool_name=sanctions_result.name,
            args={"company_name": state.supplier_name},
            status=sanctions_result.status,
            latency_ms=sanctions_result.latency_ms,
            permission_tier=sanctions_result.permission_tier,
        )
    )
    if sanctions_result.status == "ok":
        risk_dimension = "geopolitical_or_sanctions_risk"
        state.evidence.append(
            Evidence(
                claim=f"Sanctions fixture listed={sanctions_result.data['listed']} for {state.supplier_name}.",
                dimension=risk_dimension,
                confidence=0.9,
                citation=Citation(
                    source_id=f"sanctions:{state.supplier_name.lower().replace(' ', '-')}",
                    title="Local sanctions fixture",
                    url="local://procurement/sanctions",
                    snippet=sanctions_result.data["reason"],
                ),
            )
        )

    for item in state.plan:
        for result in retriever.search(f"{state.supplier_name} {item.question}", limit=1):
            state.evidence.append(
                Evidence(
                    claim=result.snippet,
                    dimension=item.dimension,
                    confidence=min(0.95, 0.55 + result.score),
                    citation=Citation(
                        source_id=result.source_id,
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                    ),
                )
            )

    state.iteration += 1
    return state


def critique_node(state: ResearchState) -> ResearchState:
    covered = {item.dimension for item in state.evidence}
    required = {item.dimension for item in state.plan}
    state.missing_dimensions = sorted(required - covered)
    return state


def writer_node(state: ResearchState) -> ResearchState:
    if state.supplier_name is None:
        raise ValueError("supplier_name is required to write a report")

    has_sanctions_risk = any(
        item.dimension == "geopolitical_or_sanctions_risk" and "listed=True" in item.claim
        for item in state.evidence
    )
    if has_sanctions_risk:
        recommendation = "reject"
        summary = "Supplier should be rejected or escalated because a sanctions or blacklist risk was found."
    elif state.missing_dimensions:
        recommendation = "conditional"
        summary = "Supplier may be suitable, but some evidence dimensions require human follow-up."
    else:
        recommendation = "approve"
        summary = "Supplier appears suitable based on the local v1 evidence set."

    state.report = SupplierReport(
        supplier_name=state.supplier_name,
        recommendation=recommendation,
        summary=summary,
        risks=_risk_lines(state),
        evidence_table=state.evidence,
        open_questions=[f"Collect more evidence for {dimension}." for dimension in state.missing_dimensions],
    )
    return state


def _extract_supplier_name(question: str) -> str:
    known = ["ACME Sensors", "Northstar Components"]
    for supplier in known:
        if supplier.lower() in question.lower():
            return supplier
    return question.split(" for ")[0].replace("Assess ", "").strip()


def _risk_lines(state: ResearchState) -> list[str]:
    risks: list[str] = []
    for item in state.evidence:
        text = f"{item.claim} Source: {item.citation.title}."
        if "listed=True" in item.claim or "restriction" in item.citation.snippet.lower():
            risks.append(text)
    if state.missing_dimensions:
        risks.append(f"Missing evidence dimensions: {', '.join(state.missing_dimensions)}.")
    return risks or ["No high-risk signal found in the local v1 fixture set."]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```bash
pytest tests/test_nodes.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "feat: add deterministic supplier research nodes"
```

Expected: commit succeeds.

---

### Task 6: LangGraph Workflow

**Files:**
- Create: `src/deepresearch_agent/agents/graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write failing graph tests**

Create `tests/test_graph.py`:

```python
from deepresearch_agent.agents.graph import run_research


def test_graph_generates_report_for_approved_supplier():
    final_state = run_research("Assess ACME Sensors for industrial sensor procurement")

    assert final_state.report is not None
    assert final_state.report.supplier_name == "ACME Sensors"
    assert final_state.report.evidence_table
    assert final_state.iteration >= 1


def test_graph_rejects_known_restricted_supplier():
    final_state = run_research("Assess Northstar Components for control module procurement")

    assert final_state.report is not None
    assert final_state.report.recommendation == "reject"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_graph.py -v
```

Expected: FAIL because `deepresearch_agent.agents.graph` does not exist.

- [ ] **Step 3: Add LangGraph workflow**

Create `src/deepresearch_agent/agents/graph.py`:

```python
from __future__ import annotations

from langgraph.graph import END, StateGraph

from deepresearch_agent.agents.nodes import critique_node, planner_node, researcher_node, writer_node
from deepresearch_agent.retrieval.local import LocalDocumentRetriever
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


def _should_continue(state: ResearchState) -> str:
    if state.missing_dimensions and state.iteration < state.max_iterations:
        return "researcher"
    return "writer"


def build_graph():
    retriever = LocalDocumentRetriever("data/procurement/documents")
    tools = build_procurement_tool_registry()

    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", lambda state: researcher_node(state, retriever=retriever, tools=tools))
    graph.add_node("critic", critique_node)
    graph.add_node("writer", writer_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic",
        _should_continue,
        {
            "researcher": "researcher",
            "writer": "writer",
        },
    )
    graph.add_edge("writer", END)
    return graph.compile()


def run_research(question: str, domain: str = "procurement") -> ResearchState:
    app = build_graph()
    initial_state = ResearchState(question=question, domain=domain)
    result = app.invoke(initial_state)
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)
```

- [ ] **Step 4: Run the graph tests**

Run:

```bash
pytest tests/test_graph.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/deepresearch_agent/agents/graph.py tests/test_graph.py
git commit -m "feat: add langgraph supplier research loop"
```

Expected: commit succeeds.

---

### Task 7: CLI and FastAPI Entrypoints

**Files:**
- Create: `src/deepresearch_agent/cli.py`
- Create: `src/deepresearch_agent/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from deepresearch_agent.api import app


def test_research_api_returns_report():
    client = TestClient(app)

    response = client.post(
        "/research",
        json={"question": "Assess ACME Sensors for industrial sensor procurement"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["supplier_name"] == "ACME Sensors"
    assert data["evidence_table"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_api.py -v
```

Expected: FAIL because `deepresearch_agent.api` does not exist.

- [ ] **Step 3: Add FastAPI app**

Create `src/deepresearch_agent/api.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.state import SupplierReport


class ResearchRequest(BaseModel):
    question: str
    domain: str = "procurement"


app = FastAPI(title="DeepResearch Agent", version="0.1.0")


@app.post("/research", response_model=SupplierReport)
def research(request: ResearchRequest) -> SupplierReport:
    state = run_research(request.question, domain=request.domain)
    if state.report is None:
        raise RuntimeError("research graph completed without a report")
    return state.report
```

- [ ] **Step 4: Add CLI runner**

Create `src/deepresearch_agent/cli.py`:

```python
from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a procurement DeepResearch supplier assessment.")
    parser.add_argument("question", help="Research question, including a known supplier name.")
    args = parser.parse_args()

    state = run_research(args.question)
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
```

- [ ] **Step 5: Run API tests**

Run:

```bash
pytest tests/test_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run CLI smoke test**

Run:

```bash
deepresearch "Assess ACME Sensors for industrial sensor procurement"
```

Expected: terminal prints supplier, recommendation, summary, and evidence table.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/deepresearch_agent/api.py src/deepresearch_agent/cli.py tests/test_api.py
git commit -m "feat: add api and cli entrypoints"
```

Expected: commit succeeds.

---

### Task 8: Documentation and v1 Verification

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/eval-plan.md`

- [ ] **Step 1: Update README with exact commands**

Replace `README.md` with:

```markdown
# DeepResearch Agent

An open-source, pluggable DeepResearch Agent framework built on LangGraph. The v1 domain is supplier due diligence for procurement and supply-chain decisions.

## When To Use This

Use DeepResearch when an answer requires gathering evidence from many sources, deciding what to search next, resolving missing evidence, and producing a cited report. Do not use it for single-fact lookup, one-authority-source questions, or latency-sensitive chat.

## v1 Demo

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
pytest
deepresearch "Assess ACME Sensors for industrial sensor procurement"
```

## API

```bash
uvicorn deepresearch_agent.api:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Assess ACME Sensors for industrial sensor procurement\"}"
```

## Architecture

```text
Planner -> Researcher -> Critic -> Researcher when evidence is missing -> Writer
```

The procurement domain pack defines research dimensions, allowed tools, report sections, source priority, and HITL policy. The core graph is domain-independent enough to support later investment or academic research packs.

## Roadmap

- Add BM25 + vector hybrid retrieval with alpha tuning.
- Add Qdrant and reranker support.
- Extract procurement tools into an MCP server.
- Add LangSmith trace and local trace export.
- Add golden supplier cases and trajectory evaluation.
```

- [ ] **Step 2: Add architecture doc**

Create `docs/architecture.md`:

```markdown
# Architecture

## Core Loop

The v1 graph uses LangGraph because supplier due diligence is not a linear chain. The agent must plan dimensions, gather evidence, critique coverage, and loop back to retrieval when evidence is missing.

## Nodes

- `planner`: extracts supplier and creates dimension-specific research questions.
- `researcher`: calls deterministic procurement tools and local retrieval.
- `critic`: checks evidence coverage against the plan.
- `writer`: creates a cited supplier due diligence report.

## Domain Pack Boundary

The procurement domain pack lives in `domains/procurement/domain.yaml`. Later domains should define their own dimensions, allowed tools, report sections, source priority, and HITL rules without rewriting the graph.

## Tool Boundary

The v1 tool registry records name, description, permission tier, timeout, latency, and structured results. This is intentionally close to MCP tool metadata so the tools can be moved behind an MCP server in a later milestone.
```

- [ ] **Step 3: Add eval plan doc**

Create `docs/eval-plan.md`:

```markdown
# Evaluation Plan

## Component Evaluation

- Retrieval recall@k: whether supplier documents containing required evidence are returned.
- Citation hit rate: whether report claims include source snippets that support them.
- Tool success rate: whether tool calls return structured data and trace metadata.

## Trajectory Evaluation

- Planner includes supplier profile, compliance, delivery capability, and negative news.
- Critic detects missing dimensions.
- Graph loops to retrieval when evidence is missing and iteration budget remains.
- Writer rejects suppliers with sanctions or blacklist evidence.

## End-to-End Evaluation

Golden cases should include:

- Low-risk supplier with certifications and delivery evidence.
- Restricted supplier that must be rejected.
- Supplier with missing compliance evidence that requires conditional recommendation.
```

- [ ] **Step 4: Run full verification**

Run:

```bash
pytest -v
deepresearch "Assess ACME Sensors for industrial sensor procurement"
deepresearch "Assess Northstar Components for control module procurement"
```

Expected:

- `pytest -v` passes.
- ACME Sensors report returns `approve` or `conditional`.
- Northstar Components report returns `reject`.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md docs/architecture.md docs/eval-plan.md
git commit -m "docs: document procurement deepresearch v1"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: The plan covers scaffold, domain pack, tools, retrieval, LangGraph loop, API, CLI, docs, and verification for supplier due diligence v1.
- Placeholder scan: No placeholder markers or unspecified implementation steps remain.
- Type consistency: `ResearchState`, `Evidence`, `Citation`, `SupplierReport`, `ToolRegistry`, and graph functions are consistently named across tasks.
- Scope check: This is one independently testable subsystem: a deterministic procurement supplier due diligence v1. MCP extraction, vector database, reranker, LangSmith, and multi-domain expansion are intentionally deferred to later plans.
