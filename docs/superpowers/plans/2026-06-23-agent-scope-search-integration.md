# Agent 跨企业经营范围筛选集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把跨企业语义经营范围检索接入 Agent 主流程——planner 对“未解析出企业”的能力类问题路由到 scope 检索，输出候选供应商清单，与现有“核验指定企业”流程并存。

**Architecture:** planner 后路由按 `resolve_supplier` 结果分流：`resolved`→核验（不变），`not_found` 且注入了 scope 节点→新 `scope_search` 节点。新报告 `ScopeSearchReport` 复用现有 `Evidence`/`Citation`。`run_research` 加 `enable_scope` 开关，CLI 启用、API 不动；`rag` 懒加载，缺 `.[rag]`/索引时降级为“不可用”报告。

**Tech Stack:** Python 3.11、LangGraph、Pydantic、SQLite、FAISS（`.[rag]`）、pytest。

## Global Constraints

- 解释器固定 `.\.conda-env\python.exe`，不新建 venv。
- 默认测试不加载真模型、不触网；重依赖测试用 `pytest.mark.slow` 默认排除。
- 不引入 LLM；路由用确定性 `resolve_supplier` 结果。
- `/research` API 响应形状不变（`response_model=SupplierReport`）；scope 仅经 CLI 暴露。
- scope 命中复用 `Evidence`/`Citation`，不另造引用系统。
- `recommendation` 在 scope 报告中固定 `"insufficient_evidence"`（按经营范围找到 ≠ 采购背书）。
- 主 graph 的 import 不依赖 faiss/torch（`rag` 懒加载于 `run_research` 的 `enable_scope` 分支）。
- 每个 Task 末尾提交一次，提交信息用中文。

---

## File Structure

修改：
- `src/deepresearch_agent/state.py` — 新增 `ScopeCandidate`、`ScopeSearchReport`；`ResearchState` 加 `scope_report`。
- `src/deepresearch_agent/agents/nodes.py` — 新增 `scope_search_node` 及分组/常量。
- `src/deepresearch_agent/agents/graph.py` — `build_graph` 加 `scope_node` 参数与路由闭包；`run_research` 加 `enable_scope`/`index_path`；`_build_scope_node`；`DEFAULT_INDEX_PATH`。
- `src/deepresearch_agent/cli.py` — `--index` 参数、`enable_scope=True`、scope/supplier 渲染分流。
- 测试：`tests/test_nodes.py`（加 scope_search_node 测试）、`tests/test_graph.py`（加路由/集成测试）、`tests/test_cli.py`（加 scope 渲染测试）。

---

## Task 1: state 新增 scope 报告模型

**Files:**
- Modify: `src/deepresearch_agent/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `ScopeCandidate(unified_social_credit_code: str, legal_name: str, matched_clauses: list[Evidence], top_score: float)`
  - `ScopeSearchReport(query: str, recommendation: Recommendation = "insufficient_evidence", summary: str, candidates: list[ScopeCandidate], open_questions: list[str])`
  - `ResearchState.scope_report: ScopeSearchReport | None = None`

- [ ] **Step 1: 写失败测试，追加到 `tests/test_state.py` 末尾**

```python
def test_scope_search_report_defaults_to_insufficient_evidence():
    from deepresearch_agent.state import (
        Citation,
        Evidence,
        ScopeCandidate,
        ScopeSearchReport,
    )

    evidence = Evidence(
        claim="工业设备制造",
        dimension="business_scope_match",
        confidence=0.9,
        citation=Citation(
            source_id="company:X",
            title="示例 经营范围",
            url="local://companies/X",
            snippet="工业设备制造",
        ),
    )
    candidate = ScopeCandidate(
        unified_social_credit_code="X",
        legal_name="示例科技股份有限公司",
        matched_clauses=[evidence],
        top_score=0.9,
    )
    report = ScopeSearchReport(
        query="工业设备制造",
        summary="一家候选",
        candidates=[candidate],
        open_questions=[],
    )

    assert report.recommendation == "insufficient_evidence"
    assert report.candidates[0].legal_name == "示例科技股份有限公司"
    assert report.candidates[0].matched_clauses[0].dimension == "business_scope_match"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_state.py::test_scope_search_report_defaults_to_insufficient_evidence -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t1`
Expected: FAIL（`ImportError: cannot import name 'ScopeSearchReport'`）。

- [ ] **Step 3: 在 `src/deepresearch_agent/state.py` 增加模型**

在 `class SupplierReport(BaseModel):` 定义之后、`class ResearchState(BaseModel):` 之前插入：

```python
class ScopeCandidate(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    matched_clauses: list[Evidence]
    top_score: float


class ScopeSearchReport(BaseModel):
    query: str
    recommendation: Recommendation = "insufficient_evidence"
    summary: str
    candidates: list[ScopeCandidate]
    open_questions: list[str]
```

在 `class ResearchState(BaseModel):` 中，`report: SupplierReport | None = None` 这一行之后插入：

```python
    scope_report: ScopeSearchReport | None = None
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_state.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t1b`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/state.py tests/test_state.py
git commit -m "功能：新增 ScopeSearchReport 与 ScopeCandidate 状态模型"
```

---

## Task 2: scope_search_node

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `ScopeCandidate`、`ScopeSearchReport`（Task 1）；`Evidence`/`Citation`（现有）；任意带 `search(query, k) -> list[ScopeHit]` 的 retriever（duck-typed，不在 nodes 内 import rag）。
- Produces: `scope_search_node(state: ResearchState, retriever) -> ResearchState`（写 `state.scope_report`）。`retriever` 可为 `None`。

- [ ] **Step 1: 写失败测试，追加到 `tests/test_nodes.py` 末尾**

```python
def test_scope_search_node_returns_unavailable_when_retriever_missing():
    from deepresearch_agent.agents.nodes import scope_search_node

    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    updated = scope_search_node(state, None)

    assert updated.scope_report is not None
    assert updated.scope_report.recommendation == "insufficient_evidence"
    assert updated.scope_report.candidates == []
    assert "不可用" in updated.scope_report.summary


def test_scope_search_node_groups_hits_into_candidates():
    from deepresearch_agent.agents.nodes import scope_search_node
    from deepresearch_agent.state import Citation, Evidence  # noqa: F401

    class _Hit:
        def __init__(self, code, name, text, score):
            self.unified_social_credit_code = code
            self.legal_name = name
            self.section_label = None
            self.text = text
            self.score = score

    class _Retriever:
        def search(self, query, k):
            return [
                _Hit("X", "示例科技股份有限公司", "工业设备制造", 0.95),
                _Hit("X", "示例科技股份有限公司", "工业设备销售", 0.80),
            ]

    state = ResearchState(question="工业设备制造", domain="procurement")
    updated = scope_search_node(state, _Retriever())

    report = updated.scope_report
    assert report is not None
    assert report.recommendation == "insufficient_evidence"
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.unified_social_credit_code == "X"
    assert candidate.top_score == 0.95
    assert [ev.claim for ev in candidate.matched_clauses] == ["工业设备制造", "工业设备销售"]
    assert candidate.matched_clauses[0].dimension == "business_scope_match"
    assert candidate.matched_clauses[0].citation.url == "local://companies/X"


def test_scope_search_node_reports_no_matches_when_empty():
    from deepresearch_agent.agents.nodes import scope_search_node

    class _Empty:
        def search(self, query, k):
            return []

    state = ResearchState(question="完全不相关的查询", domain="procurement")
    updated = scope_search_node(state, _Empty())

    assert updated.scope_report.candidates == []
    assert "未检索到" in updated.scope_report.summary
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k scope_search -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t2`
Expected: FAIL（`ImportError: cannot import name 'scope_search_node'`）。

- [ ] **Step 3: 在 `src/deepresearch_agent/agents/nodes.py` 实现**

把顶部 `from deepresearch_agent.state import (...)` 的导入列表中追加 `ScopeCandidate` 与 `ScopeSearchReport`（与现有 `Citation`、`Evidence` 等并列）。

在 `writer_node` 定义之后插入：

```python
SCOPE_SEARCH_K = 10

_SCOPE_OPEN_QUESTIONS = [
    "经营范围匹配仅为登记信息，不代表实际产能、交期或质量。",
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]


def scope_search_node(state: ResearchState, retriever) -> ResearchState:
    if retriever is None:
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary="经营范围语义检索不可用：请安装 .[rag] 可选依赖并运行 "
            "scripts/build_scope_index.py 构建索引。",
            candidates=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"],
        )
        return state

    try:
        hits = retriever.search(state.question, SCOPE_SEARCH_K)
    except Exception as exc:  # 检索期异常兜底为不可用报告
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary=f"经营范围语义检索失败：{exc}",
            candidates=[],
            open_questions=["检查 .[rag] 依赖与 FAISS 索引后重试。"],
        )
        return state

    candidates = _group_scope_hits(hits)
    if candidates:
        summary = (
            f"按经营范围语义检索到 {len(candidates)} 家候选企业；"
            "现有数据仅工商经营范围，不足以作出采购批准或风险结论。"
        )
    else:
        summary = "未检索到经营范围匹配的企业。"
    state.scope_report = ScopeSearchReport(
        query=state.question,
        summary=summary,
        candidates=candidates,
        open_questions=list(_SCOPE_OPEN_QUESTIONS),
    )
    return state


def _group_scope_hits(hits) -> list[ScopeCandidate]:
    grouped: dict[str, ScopeCandidate] = {}
    for hit in hits:
        evidence = Evidence(
            claim=hit.text,
            dimension="business_scope_match",
            confidence=min(max(hit.score, 0.0), 1.0),
            citation=Citation(
                source_id=f"company:{hit.unified_social_credit_code}",
                title=f"{hit.legal_name} 经营范围",
                url=f"local://companies/{hit.unified_social_credit_code}",
                snippet=hit.text,
            ),
        )
        candidate = grouped.get(hit.unified_social_credit_code)
        if candidate is None:
            grouped[hit.unified_social_credit_code] = ScopeCandidate(
                unified_social_credit_code=hit.unified_social_credit_code,
                legal_name=hit.legal_name,
                matched_clauses=[evidence],
                top_score=hit.score,
            )
        else:
            candidate.matched_clauses.append(evidence)
            candidate.top_score = max(candidate.top_score, hit.score)
    return list(grouped.values())
```

说明：`hits` 已按评分降序（FAISS 返回），按首次出现分组后 `candidates` 即按 `top_score` 降序，无需再排序。

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k scope_search -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t2b`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：增加 scope_search_node 与命中分组"
```

---

## Task 3: graph 路由与 run_research 开关

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `scope_search_node`（Task 2）；`build_scope_index`、`FakeEmbedder`、`load_scope_retriever`（已有 rag）。
- Produces:
  - `build_graph(domain_pack, repository, scope_node=None)`
  - `run_research(question, domain="procurement", database_path=DEFAULT_DATABASE_PATH, index_path=DEFAULT_INDEX_PATH, enable_scope=False)`
  - `DEFAULT_INDEX_PATH: Path`

- [ ] **Step 1: 写失败测试，追加到 `tests/test_graph.py` 末尾**

```python
def _stub_scope_node(state):
    from deepresearch_agent.state import ScopeSearchReport

    state.scope_report = ScopeSearchReport(
        query=state.question,
        summary="stub",
        candidates=[],
        open_questions=[],
    )
    return state


def test_capability_question_routes_to_scope_when_node_injected(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository
    from deepresearch_agent.domain import load_domain_pack

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, scope_node=_stub_scope_node)

    state = run_compiled(app, "哪些企业能做注塑成型", "procurement")

    assert state.scope_report is not None
    assert state.scope_report.summary == "stub"
    assert state.report is None


def test_named_company_still_routes_to_verify_with_scope_node(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository
    from deepresearch_agent.domain import load_domain_pack

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, scope_node=_stub_scope_node)

    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")

    assert state.report is not None
    assert state.report.supplier_name == "示例科技股份有限公司"
    assert state.scope_report is None


def test_run_research_without_scope_keeps_supplier_report(company_database_path):
    state = run_research("哪些企业能做注塑成型", database_path=company_database_path)

    assert state.scope_report is None
    assert state.report is not None
    assert state.report.recommendation == "insufficient_evidence"


def test_run_research_enable_scope_without_index_returns_unavailable(company_database_path, tmp_path):
    missing_index = tmp_path / "does_not_exist.faiss"

    state = run_research(
        "哪些企业能做注塑成型",
        database_path=company_database_path,
        index_path=missing_index,
        enable_scope=True,
    )

    assert state.scope_report is not None
    assert "不可用" in state.scope_report.summary
    assert state.report is None
```

注意：`test_run_research_without_scope_keeps_supplier_report` 证明 API 路径（`enable_scope=False`）对能力类问题仍返回 `SupplierReport`，响应形状不变。

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py -k "scope or capability or named_company" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t3`
Expected: FAIL（`build_graph() got an unexpected keyword argument 'scope_node'` 或 `run_research() got an unexpected keyword argument 'enable_scope'`）。

- [ ] **Step 3: 改 `src/deepresearch_agent/agents/graph.py`**

顶部 import 增加 `scope_search_node`：

```python
from deepresearch_agent.agents.nodes import (
    critique_node,
    planner_node,
    researcher_node,
    scope_search_node,
    writer_node,
)
```

在 `DEFAULT_DATABASE_PATH = ...` 之后增加：

```python
DEFAULT_INDEX_PATH = Path("data/procurement/derived/scope_index.faiss")
```

把 `build_graph` 整个函数替换为：

```python
def build_graph(domain_pack: DomainPack, repository: CompanyRepository, scope_node=None):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)
    graph.add_node(
        "planner",
        lambda state: planner_node(state, domain_pack, repository),
    )
    graph.add_node(
        "researcher",
        lambda state: researcher_node(state, tools, domain_pack),
    )
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack))
    graph.set_entry_point("planner")

    planner_routes = {"researcher": "researcher", "writer": "writer"}
    if scope_node is not None:
        graph.add_node("scope_search", scope_node)
        graph.add_edge("scope_search", END)
        planner_routes["scope_search"] = "scope_search"

    def route_after_planner(state: ResearchState) -> str:
        resolution = state.supplier_resolution
        status = resolution.status if resolution is not None else "not_found"
        if status == "resolved":
            return "researcher"
        if status == "not_found" and scope_node is not None:
            return "scope_search"
        return "writer"

    graph.add_conditional_edges("planner", route_after_planner, planner_routes)
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic",
        _should_continue,
        {"researcher": "researcher", "writer": "writer"},
    )
    graph.add_edge("writer", END)
    return graph.compile()
```

删除现有模块级 `_route_after_planner` 函数（已被 `build_graph` 内的闭包取代）。

把 `run_research` 替换为：

```python
def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    enable_scope: bool = False,
) -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    repository = CompanyRepository(database_path)
    scope_node = _build_scope_node(database_path, index_path) if enable_scope else None
    app = build_graph(domain_pack, repository, scope_node=scope_node)
    return run_compiled(app, question, domain)


def _build_scope_node(database_path: str | Path, index_path: str | Path):
    retriever = None
    try:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            retriever = load_scope_retriever(database_path, index_path, BgeEmbedder())
    except Exception:
        retriever = None
    return lambda state: scope_search_node(state, retriever)
```

说明：`BgeEmbedder()` 只在索引文件存在时才构造（构造才会加载真模型）；索引缺失或 `.[rag]` 未装时 `retriever=None`，节点产出“不可用”报告。`rag` 仅在此分支内 import，核心 import 不依赖 faiss/torch。

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t3b`
Expected: PASS（含既有 graph 测试）。

- [ ] **Step 5: 跑全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t3c`
Expected: PASS。

- [ ] **Step 6: 加一个慢速端到端测试（真模型），追加到 `tests/test_graph.py` 末尾**

```python
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.mark.slow
def test_run_research_scope_search_end_to_end(company_database_path, tmp_path):
    import pytest  # noqa: F811

    from build_scope_index import build_scope_index
    from deepresearch_agent.rag.embedding import BgeEmbedder

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, BgeEmbedder())

    state = run_research(
        "哪些企业能做工业设备制造",
        database_path=company_database_path,
        index_path=index_path,
        enable_scope=True,
    )

    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert state.scope_report.recommendation == "insufficient_evidence"
    assert state.report is None
```

在 `tests/test_graph.py` 顶部增加 `import pytest`（若尚无）。

- [ ] **Step 7: 运行慢速测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py::test_run_research_scope_search_end_to_end -m slow -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t3d`
Expected: PASS（1 passed，加载真 bge 模型）。

- [ ] **Step 8: 提交**

```bash
git add src/deepresearch_agent/agents/graph.py tests/test_graph.py
git commit -m "功能：graph 路由 not_found 到 scope 检索并加 enable_scope 开关"
```

---

## Task 4: CLI 渲染候选清单

**Files:**
- Modify: `src/deepresearch_agent/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_research(..., index_path=..., enable_scope=True)`（Task 3）；`ScopeSearchReport`（Task 1）。
- Produces: CLI 对 `state.scope_report` 渲染候选清单；否则按现有 `state.report` 渲染。

- [ ] **Step 1: 写失败测试，追加到 `tests/test_cli.py` 末尾**

```python
def test_cli_renders_supplier_report_for_named_company(company_database_path, tmp_path, capsys):
    from deepresearch_agent import cli

    cli.main(
        [
            "核验示例科技股份有限公司",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )

    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "insufficient_evidence" in out


def test_cli_renders_scope_unavailable_for_capability_question(company_database_path, tmp_path, capsys):
    from deepresearch_agent import cli

    cli.main(
        [
            "哪些企业能做注塑成型",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )

    out = capsys.readouterr().out
    assert "不可用" in out
    assert "insufficient_evidence" in out
```

注意：两个测试都把 `--index` 指向不存在的文件，因此 `enable_scope=True` 时 `retriever=None`，不加载真模型；能力问题走“不可用”scope 报告，指名企业走核验报告。

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -k "scope or named_company" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t4`
Expected: FAIL（`--index` 不是已知参数 / 能力问题当前返回 unresolved supplier 报告，无“不可用”字样）。

- [ ] **Step 3: 把 `src/deepresearch_agent/cli.py` 替换为**

```python
from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from deepresearch_agent.agents.graph import run_research
from deepresearch_agent.state import ScopeSearchReport, SupplierReport


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a procurement DeepResearch supplier assessment.")
    parser.add_argument("question", help="Research question: a known supplier name, or a capability to search for.")
    parser.add_argument(
        "--database",
        default="data/procurement/derived/companies.sqlite3",
        help="Path to the generated SQLite company database.",
    )
    parser.add_argument(
        "--index",
        default="data/procurement/derived/scope_index.faiss",
        help="Path to the FAISS business-scope index (for capability searches).",
    )
    args = parser.parse_args(argv)

    state = run_research(
        args.question,
        database_path=args.database,
        index_path=args.index,
        enable_scope=True,
    )

    console = Console()
    if state.scope_report is not None:
        _print_scope_report(console, state.scope_report)
    elif state.report is not None:
        _print_supplier_report(console, state.report)
    else:
        raise SystemExit("Research finished without a report.")


def _print_supplier_report(console: Console, report: SupplierReport) -> None:
    console.print(f"[bold]Supplier:[/bold] {report.supplier_name}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    table = Table(title="Evidence")
    table.add_column("Dimension")
    table.add_column("Claim")
    table.add_column("Source")
    for item in report.evidence_table:
        table.add_row(item.dimension, item.claim, item.citation.title)
    console.print(table)


def _print_scope_report(console: Console, report: ScopeSearchReport) -> None:
    console.print(f"[bold]Query:[/bold] {report.query}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    table = Table(title="Candidates")
    table.add_column("Company")
    table.add_column("Matched clauses")
    table.add_column("Score")
    for candidate in report.candidates:
        clauses = "；".join(evidence.claim for evidence in candidate.matched_clauses)
        table.add_row(candidate.legal_name, clauses, f"{candidate.top_score:.3f}")
    console.print(table)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t4b`
Expected: PASS（含既有 CLI 测试）。

- [ ] **Step 5: 跑全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-int-t4c`
Expected: PASS。

- [ ] **Step 6: 更新 `CLAUDE.md` 的 CLI 说明**

把“运行 Agent”代码块中 CLI 注释行改为（指明也支持能力检索）：

```powershell
# CLI（核验指定企业，或按能力检索供应商：问题不含已知企业名时走经营范围语义检索）
.\.conda-env\python.exe -m deepresearch_agent.cli `
  "核验万马科技股份有限公司的工商和经营范围" `
  --database data/procurement/derived/companies.sqlite3
```

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/cli.py tests/test_cli.py CLAUDE.md
git commit -m "功能：CLI 支持渲染经营范围候选清单"
```

---

## Self-Review

**1. Spec coverage:**
- planner 路由扩展（not_found→scope）→ Task 3 ✅
- scope_search_node（注入式，retriever=None 兜底）→ Task 2 ✅
- ScopeSearchReport / ScopeCandidate（复用 Evidence/Citation）→ Task 1 + Task 2 ✅
- ResearchState.scope_report → Task 1 ✅
- run_research enable_scope 开关；CLI 启用、API 不动 → Task 3（开关）+ Task 4（CLI）✅
- 依赖/索引缺失优雅降级 + 懒加载 → Task 3（`_build_scope_node`）+ Task 2（不可用报告）✅
- 检索器单次构建注入 → Task 3 ✅
- 主 CLI 渲染候选清单 → Task 4 ✅
- API 响应形状不变 → Task 3 的 `test_run_research_without_scope_keeps_supplier_report` 守护 ✅
- recommendation 固定 insufficient_evidence → Task 1 默认值 + Task 2 ✅
- 测试默认不加载真模型 → Task 2/3/4 用 stub/假 retriever/缺索引；真模型仅 Task 3 slow ✅

**2. Placeholder scan:** 无 TBD/TODO/“适当处理”；每个代码步骤含完整代码。✅

**3. Type consistency:**
- `ScopeSearchReport(query, recommendation, summary, candidates, open_questions)` 与 `ScopeCandidate(unified_social_credit_code, legal_name, matched_clauses, top_score)` 在 Task 1 定义，Task 2/3/4 一致使用。
- `scope_search_node(state, retriever)` 在 Task 2 定义，Task 3 注入一致。
- `build_graph(domain_pack, repository, scope_node=None)` 在 Task 3 定义，测试与 api.py 现有 `build_graph(domain_pack, repository)` 调用兼容（`scope_node` 默认 None）。
- `run_research(..., index_path, enable_scope)` 在 Task 3 定义，Task 4 CLI 调用一致。
- ScopeHit 字段（`unified_social_credit_code`/`legal_name`/`text`/`score`）与 `rag/retriever.py` 的 `ScopeHit` 一致。

无不一致。
```
