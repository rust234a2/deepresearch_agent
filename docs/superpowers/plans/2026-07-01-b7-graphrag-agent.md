# 模块 B7：GraphRAG Agent 接入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 B5 混合检索接进 Agent 的能力检索路径：新增 `graph_search_node` + `GraphSearchReport`，能力查询额外返回候选最终控制人与跨候选共享控制人（围标线索），`enable_graph` 经 CLI `--graph` 开，缺依赖降级。

**Architecture:** 与 `scope_search_node` 对称：`state.py` 加报告模型 + `graph_report` 字段；`graph_search_node` 由 B5 `HybridContext` 组装报告；`graph.py` 加 `graph_node` 路由 + `run_research(enable_graph)` + 懒加载；CLI 加 `--graph` + 打印。

**Tech Stack:** Python 3.11、Pydantic v2、LangGraph、rich、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **纯确定性、零 LLM、零新依赖、无 schema 变更**。
- recommendation 固定 `insufficient_evidence`；共享控制人是线索，`via_person` 标低置信 + "须人工复核"。
- 缺 `.[rag]`/索引/图 → 降级"不可用"报告，不崩。
- `enable_graph` 仅 CLI；API 形状不变。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-b7`。每 Task 一提交，中文提交信息。

---

### Task 1: 报告模型 + `graph_search_node`

**Files:**
- Modify: `src/deepresearch_agent/state.py`（3 模型 + `ResearchState.graph_report`）
- Modify: `src/deepresearch_agent/agents/nodes.py`（`graph_search_node` + 助手）
- Modify: `tests/test_nodes.py`（节点用例）

**Interfaces:**
- Consumes：B5 `assemble_subgraph_context`/`HybridContext`（`seeds`/`shared_controllers`）、B2 `load_ownership_graph`。
- Produces：
  - `state.GraphSearchCandidate`/`SharedControllerFinding`/`GraphSearchReport`、`ResearchState.graph_report`。
  - `nodes.graph_search_node(state, searcher) -> ResearchState`（`searcher: callable(query)->HybridContext | None`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 顶部 import 区追加：

```python
from deepresearch_agent.graph_retrieval import assemble_subgraph_context
from deepresearch_agent.ownership_graph import load_ownership_graph
```

在文件末尾新增：

```python
_LINKS = Path("tests/fixtures/procurement/ownership_links")


def _ownership_graph(tmp_path):
    from deepresearch_agent.company_database import build_company_database

    database_path = tmp_path / "companies.sqlite3"
    build_company_database(
        _LINKS / "companies.csv",
        _LINKS / "contacts.csv",
        database_path,
        shareholders_csv=_LINKS / "shareholders.csv",
        investments_csv=_LINKS / "investments.csv",
    )
    return load_ownership_graph(CompanyRepository(database_path))


def test_graph_search_node_reports_candidates_and_shared_controllers(tmp_path):
    from deepresearch_agent.agents.nodes import graph_search_node

    graph = _ownership_graph(tmp_path)
    seeds = ["91110000000000111A", "91110000000000222B", "91110000000000333C"]
    searcher = lambda query: assemble_subgraph_context(graph, seeds, query=query)

    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    updated = graph_search_node(state, searcher)

    report = updated.graph_report
    assert report is not None
    assert report.recommendation == "insufficient_evidence"
    candidate_names = {c.legal_name for c in report.candidates}
    assert {"甲公司", "乙公司", "丙公司"} <= candidate_names
    shared = {s.controller_name: s for s in report.shared_controllers}
    assert "共同控股集团有限公司" in shared
    assert shared["共同控股集团有限公司"].via_person is False
    assert "张三" in shared
    assert shared["张三"].via_person is True
    assert "须人工复核" in shared["张三"].note


def test_graph_search_node_unavailable_when_searcher_missing():
    from deepresearch_agent.agents.nodes import graph_search_node

    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    updated = graph_search_node(state, None)

    assert updated.graph_report is not None
    assert updated.graph_report.recommendation == "insufficient_evidence"
    assert updated.graph_report.candidates == []
    assert "不可用" in updated.graph_report.summary
```

（`Path`、`ResearchState`、`CompanyRepository` 已在 `test_nodes.py` import；若 `CompanyRepository` 未 import 则在顶部加 `from deepresearch_agent.company_repository import CompanyRepository`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_graph_search_node_unavailable_when_searcher_missing -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b7`
Expected: FAIL —`ImportError: cannot import name 'graph_search_node'` 或 `GraphSearchReport` 未定义。

- [ ] **Step 3: 加 `state.py` 模型**

在 `src/deepresearch_agent/state.py` 的 `ScopeSearchReport` 之后追加：

```python
class GraphSearchCandidate(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    top_score: float
    ultimate_controllers: list[str]


class SharedControllerFinding(BaseModel):
    controller_name: str
    controlled_companies: list[str]
    via_person: bool
    note: str


class GraphSearchReport(BaseModel):
    query: str
    recommendation: Recommendation = "insufficient_evidence"
    summary: str
    candidates: list[GraphSearchCandidate]
    shared_controllers: list[SharedControllerFinding]
    open_questions: list[str]
```

在 `ResearchState` 里 `scope_report` 字段之后加：

```python
    graph_report: GraphSearchReport | None = None
```

- [ ] **Step 4: 加 `graph_search_node`**

在 `src/deepresearch_agent/agents/nodes.py` 顶部 `from deepresearch_agent.state import (...)` 列表里加入 `GraphSearchCandidate`、`GraphSearchReport`、`SharedControllerFinding`。

在 `scope_search_node` 相关代码之后（`_group_scope_hits` 之前或之后均可）新增：

```python
_GRAPH_OPEN_QUESTIONS = [
    "经营范围匹配仅为登记信息，不代表实际产能、交期或质量。",
    "共享控制人为线索级推断（尤其同名自然人），须人工复核，不构成围标认定。",
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]


def graph_search_node(state: ResearchState, searcher) -> ResearchState:
    if searcher is None:
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary="图谱关系检索不可用：请安装 .[rag] 可选依赖并构建 FAISS 经营范围索引与公司图谱。",
            candidates=[],
            shared_controllers=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 索引。"],
        )
        return state

    try:
        context = searcher(state.question)
    except Exception as exc:  # 检索期异常兜底为不可用报告
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary=f"图谱关系检索失败：{exc}",
            candidates=[],
            shared_controllers=[],
            open_questions=["检查 .[rag] 依赖、FAISS 索引与公司图谱后重试。"],
        )
        return state

    name_by_code = {seed.code: seed.name for seed in context.seeds}
    candidates = [
        GraphSearchCandidate(
            unified_social_credit_code=seed.code,
            legal_name=seed.name,
            top_score=seed.score,
            ultimate_controllers=[
                f"{controller.display_name}（疑·须人工复核）"
                if controller.via_person
                else controller.display_name
                for controller in seed.controllers
            ],
        )
        for seed in context.seeds
    ]
    shared = [
        SharedControllerFinding(
            controller_name=item.name,
            controlled_companies=[name_by_code.get(code, code) for code in item.controlled_seeds],
            via_person=item.via_person,
            note="经同名自然人推断，须人工复核" if item.via_person else "经企业股权链推断",
        )
        for item in context.shared_controllers
    ]
    if candidates:
        if shared:
            middle = f"其中 {len(shared)} 组疑似共享控制人（围标/集中度线索，须人工复核）；"
        else:
            middle = "未发现候选间共享控制人；"
        summary = (
            f"按经营范围语义检索到 {len(candidates)} 家候选；"
            + middle
            + "现有数据不足以作出采购批准或风险结论。"
        )
    else:
        summary = "未检索到经营范围匹配的企业。"
    state.graph_report = GraphSearchReport(
        query=state.question,
        summary=summary,
        candidates=candidates,
        shared_controllers=shared,
        open_questions=list(_GRAPH_OPEN_QUESTIONS),
    )
    return state
```

- [ ] **Step 5: 跑节点测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b7`
Expected: PASS（含两个新用例 + 既有不回归）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：B7 graph_search_node 与 GraphSearchReport"
```

---

### Task 2: 编排路由 + CLI

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`（`graph_node` 参数 + 路由 + `run_research(enable_graph)` + `_build_graph_node`）
- Modify: `src/deepresearch_agent/cli.py`（`--graph` + `_print_graph_report`）
- Modify: `tests/test_graph.py`（路由 + 降级用例）

**Interfaces:**
- Consumes：Task 1 的 `graph_search_node`；B5 `hybrid_search`；`rag/` `load_scope_retriever`/`BgeEmbedder`；B2 `load_ownership_graph`。
- Produces：`build_graph(..., graph_node=None)`、`run_research(..., enable_graph=False)`、CLI `--graph`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph.py` 末尾新增：

```python
def _stub_graph_node(state):
    from deepresearch_agent.state import GraphSearchReport

    state.graph_report = GraphSearchReport(
        query=state.question,
        summary="stub-graph",
        candidates=[],
        shared_controllers=[],
        open_questions=[],
    )
    return state


def test_capability_routes_to_graph_when_node_injected(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, graph_node=_stub_graph_node)

    state = run_compiled(app, "哪些企业能做注塑成型", "procurement")

    assert state.graph_report is not None
    assert state.graph_report.summary == "stub-graph"
    assert state.report is None


def test_named_company_still_verifies_with_graph_node(company_database_path):
    from deepresearch_agent.agents.graph import build_graph, run_compiled
    from deepresearch_agent.company_repository import CompanyRepository

    domain_pack = load_domain_pack(Path("domains/procurement/domain.yaml"))
    repository = CompanyRepository(company_database_path)
    app = build_graph(domain_pack, repository, graph_node=_stub_graph_node)

    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")

    assert state.report is not None
    assert state.graph_report is None


def test_run_research_enable_graph_without_index_degrades(company_database_path, tmp_path):
    missing_index = tmp_path / "does_not_exist.faiss"

    state = run_research(
        "哪些企业能做注塑成型",
        database_path=company_database_path,
        index_path=missing_index,
        enable_graph=True,
    )

    assert state.graph_report is not None
    assert "不可用" in state.graph_report.summary
    assert state.report is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py::test_capability_routes_to_graph_when_node_injected -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b7`
Expected: FAIL —`build_graph() got an unexpected keyword argument 'graph_node'`。

- [ ] **Step 3: `graph.py` 加 graph_node 路由 + run_research + 懒加载**

在 `src/deepresearch_agent/agents/graph.py` 顶部 `from deepresearch_agent.agents.nodes import (...)` 列表里加入 `graph_search_node`。

把 `build_graph` 改为：

```python
def build_graph(domain_pack: DomainPack, repository: CompanyRepository, scope_node=None, graph_node=None):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)
    graph.add_node("planner", lambda state: planner_node(state, domain_pack, repository))
    graph.add_node("researcher", lambda state: researcher_node(state, tools, domain_pack))
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack))
    graph.set_entry_point("planner")

    planner_routes = {"researcher": "researcher", "writer": "writer"}
    if scope_node is not None:
        graph.add_node("scope_search", scope_node)
        graph.add_edge("scope_search", END)
        planner_routes["scope_search"] = "scope_search"
    if graph_node is not None:
        graph.add_node("graph_search", graph_node)
        graph.add_edge("graph_search", END)
        planner_routes["graph_search"] = "graph_search"

    def route_after_planner(state: ResearchState) -> str:
        resolution = state.supplier_resolution
        status = resolution.status if resolution is not None else "not_found"
        if status == "resolved":
            return "researcher"
        if status == "not_found":
            if graph_node is not None:
                return "graph_search"
            if scope_node is not None:
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

把 `run_research` 改为：

```python
def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    enable_scope: bool = False,
    enable_graph: bool = False,
) -> ResearchState:
    domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
    repository = CompanyRepository(database_path)
    scope_node = (
        _build_scope_node(database_path, index_path)
        if enable_scope and not enable_graph
        else None
    )
    graph_node = _build_graph_node(database_path, index_path) if enable_graph else None
    app = build_graph(domain_pack, repository, scope_node=scope_node, graph_node=graph_node)
    return run_compiled(app, question, domain)
```

在 `_build_scope_node` 之后新增：

```python
def _build_graph_node(database_path: str | Path, index_path: str | Path):
    searcher = None
    try:
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_graph import load_ownership_graph
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            retriever = load_scope_retriever(database_path, index_path, BgeEmbedder())
            graph = load_ownership_graph(CompanyRepository(database_path))
            searcher = lambda query: hybrid_search(query, retriever, graph)
    except Exception:
        searcher = None
    return lambda state: graph_search_node(state, searcher)
```

- [ ] **Step 4: CLI 加 `--graph` + 打印**

在 `src/deepresearch_agent/cli.py`：

import 行改为 `from deepresearch_agent.state import GraphSearchReport, ScopeSearchReport, SupplierReport`。

`--index` 参数之后加：

```python
    parser.add_argument(
        "--graph",
        action="store_true",
        help="启用 GraphRAG 能力检索：候选 + 最终控制人 + 共享控制人（围标线索）。",
    )
```

把 `run_research(...)` 调用改为传 `enable_graph=args.graph`：

```python
    state = run_research(
        args.question,
        database_path=args.database,
        index_path=args.index,
        enable_scope=True,
        enable_graph=args.graph,
    )
```

把报告分发改为优先 graph：

```python
    console = Console()
    if state.graph_report is not None:
        _print_graph_report(console, state.graph_report)
    elif state.scope_report is not None:
        _print_scope_report(console, state.scope_report)
    elif state.report is not None:
        _print_supplier_report(console, state.report)
    else:
        raise SystemExit("Research finished without a report.")
```

在 `_print_scope_report` 之后新增：

```python
def _print_graph_report(console: Console, report: GraphSearchReport) -> None:
    console.print(f"[bold]Query:[/bold] {report.query}")
    console.print(f"[bold]Recommendation:[/bold] {report.recommendation}")
    console.print(report.summary)

    candidates = Table(title="Candidates")
    candidates.add_column("Company")
    candidates.add_column("Ultimate controllers")
    candidates.add_column("Score")
    for candidate in report.candidates:
        controllers = "；".join(candidate.ultimate_controllers)
        candidates.add_row(candidate.legal_name, controllers, f"{candidate.top_score:.3f}")
    console.print(candidates)

    shared = Table(title="Shared controllers (bid-rigging clues)")
    shared.add_column("Controller")
    shared.add_column("Controlled candidates")
    shared.add_column("Note")
    for finding in report.shared_controllers:
        shared.add_row(
            finding.controller_name,
            "、".join(finding.controlled_companies),
            finding.note,
        )
    console.print(shared)
```

- [ ] **Step 5: 跑编排测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-b7`
Expected: PASS（含 3 个新用例 + 既有 scope/路由不回归）。

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-b7-full`
Expected: PASS（133 + 本次新增，2 deselected）。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/agents/graph.py src/deepresearch_agent/cli.py tests/test_graph.py
git commit -m "功能：B7 能力检索路由到 graph_search 并加 CLI --graph"
```

---

## 自检

**Spec 覆盖**：
- 3 报告模型 + `graph_report` → Task 1 Step 3。
- `graph_search_node`（候选 + 共享控制人 + via_person 后缀/note + summary + 不可用/异常降级）→ Task 1 Step 4 + 测试。
- `graph_node` 路由（not_found 优先 graph，再 scope，再 writer）→ Task 2 Step 3 + 测试。
- `run_research(enable_graph)` + 懒加载降级 → Task 2 Step 3 + `test_run_research_enable_graph_without_index_degrades`。
- CLI `--graph` + 打印 → Task 2 Step 4。
- recommendation 固定 `insufficient_evidence` → 模型默认 + 不可用分支。

**Placeholder 扫描**：无 TBD/TODO；每步给完整代码与命令/预期。

**类型一致性**：`graph_search_node(state, searcher)` 中 `searcher(query)->HybridContext`，读 `context.seeds[*].code/name/score/controllers` 与 `context.shared_controllers[*].name/controlled_seeds/via_person`，与 B5 `HybridContext`/`SeedContext`/`SharedController` 字段一致；`ControllerResult.display_name/via_person` 与 B3 一致；`GraphSearchReport` 字段在 state 定义、节点构造、CLI 打印、测试断言一致；`build_graph(..., graph_node=)`/`run_research(..., enable_graph=)` 签名在实现/测试/CLI 一致。
```
