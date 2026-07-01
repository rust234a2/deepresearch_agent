# C2 查询编排（检索/生成分层）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 C1 复杂度分类器接进 planner，将 researcher 重构为按复杂度分派的唯一检索层、writer 重构为唯一生成层，图简化为线性 `planner → researcher → critic → writer`。

**Architecture:** planner 解析企业并调用 `classify_complexity` 写入 `state.complexity`；researcher 依 `解析状态 × 复杂度 × 是否启用检索` 选择 named/scope/graph/unresolved 模式，只检索、把结果落到 state；writer 依 `retrieval_mode` 生成对应报告（所有 summary/open_questions/recommendation 在此）。撤销 `scope_search`/`graph_search` 两个独立节点与 planner 后的条件路由。

**Tech Stack:** Python 3、Pydantic、LangGraph、pytest；复用 `query_complexity`、`llm.deepseek`、`rag.retriever`、`graph_retrieval.hybrid_search`。

## Global Constraints

- 报告对已解析企业**固定** `recommendation="insufficient_evidence"`；绝不写"未发现风险"或采购批准/拒绝结论。
- 股权关联方、共享控制人 = 线索级推断（尤其同名自然人），带"须人工复核"，不构成控制关系或围标认定。
- LLM 只发查询文本、只做查询分类；无 `DEEPSEEK_API_KEY`/未装 `.[llm]` → 分类器为 `None`，自动走确定性启发式，**测试不得触网**。
- 无 SQLite schema 变更（`SCHEMA_VERSION` 不动）；无新第三方依赖。
- Windows 测试命令统一：`.\.conda-env\python.exe -m pytest <target> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`（`slow` 用例默认不选）。
- 每个任务结束**提交一次**；中文提交信息；不回退用户未提交文件。

## 文件结构

- `src/deepresearch_agent/state.py` — 加 6 个中间态字段（Task 1）。
- `src/deepresearch_agent/agents/nodes.py` — planner 加分类（Task 2）；researcher 重构为分派器（Task 3）；writer 扩为唯一生成者（Task 4）；删除 `scope_search_node`/`graph_search_node`（Task 6）。
- `src/deepresearch_agent/agents/graph.py` — 线性图 + 检索器/LLM 注入 + `run_research` 线程化 enable 标志（Task 5）。
- `tests/test_nodes.py` — 追加 C2 单元测试（Task 1-4），删除旧节点测试（Task 6）。
- `tests/test_graph.py` — 按线性图重写（Task 5）。
- `tests/test_api.py` — 回归确认，不改（Task 5 验证）。

---

### Task 1：state 中间态字段

**Files:**
- Modify: `src/deepresearch_agent/state.py`
- Test: `tests/test_nodes.py`

**Interfaces:**
- Produces: `ResearchState` 新增 `complexity: ComplexityResult | None`、`retrieval_mode: Literal["named","scope","graph","unresolved"] | None`、`retrieval_available: bool`、`scope_candidates: list[ScopeCandidate]`、`graph_candidates: list[GraphSearchCandidate]`、`shared_controllers: list[SharedControllerFinding]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_research_state_has_c2_retrieval_fields():
    state = ResearchState(question="q", domain="procurement")
    assert state.complexity is None
    assert state.retrieval_mode is None
    assert state.retrieval_available is True
    assert state.scope_candidates == []
    assert state.graph_candidates == []
    assert state.shared_controllers == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_research_state_has_c2_retrieval_fields -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: FAIL（`retrieval_mode` 等属性不存在 / AttributeError）

- [ ] **Step 3: 实现字段**

在 `src/deepresearch_agent/state.py`，顶部导入区加：

```python
from deepresearch_agent.query_complexity import ComplexityResult
```

（`query_complexity` 只依赖 `company_repository`，不导入 `state`，无循环导入。）

在 `ResearchState` 里，`trace` 字段之后加 6 个字段：

```python
    complexity: ComplexityResult | None = None
    retrieval_mode: Literal["named", "scope", "graph", "unresolved"] | None = None
    retrieval_available: bool = True
    scope_candidates: list[ScopeCandidate] = Field(default_factory=list)
    graph_candidates: list[GraphSearchCandidate] = Field(default_factory=list)
    shared_controllers: list[SharedControllerFinding] = Field(default_factory=list)
```

（`ScopeCandidate`/`GraphSearchCandidate`/`SharedControllerFinding` 已在本文件 `ResearchState` 之前定义，直接引用。`Literal` 已从 typing 导入。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_research_state_has_c2_retrieval_fields -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS

- [ ] **Step 5: 全量回归（确保未破坏既有）**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 全绿（新增 1 项通过）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/state.py tests/test_nodes.py
git commit -m "功能：C2-1 ResearchState 加检索/生成分层中间态字段"
```

---

### Task 2：planner 写入复杂度分类

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`planner_node`）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `classify_complexity(query, repository, llm) -> ComplexityResult`（from `deepresearch_agent.query_complexity`）。
- Produces: `planner_node(state, domain_pack, repository, llm=None)` —— 新增可选 `llm` 参数；设 `state.complexity`。既有 3 参调用（`planner_node(state, pack, repo)`）因默认值仍有效。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_planner_sets_complexity_from_llm(company_database_path):
    state = ResearchState(question="随便问问", domain="procurement")
    updated = planner_node(
        state, DOMAIN_PACK, _repository(company_database_path), llm=lambda q: "complex"
    )
    assert updated.complexity is not None
    assert updated.complexity.level == "complex"
    assert updated.complexity.method == "llm"


def test_planner_complexity_falls_back_to_heuristic(company_database_path):
    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    updated = planner_node(state, DOMAIN_PACK, _repository(company_database_path))
    assert updated.complexity is not None
    assert updated.complexity.method == "heuristic"
    assert updated.complexity.level == "medium"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_planner_sets_complexity_from_llm tests/test_nodes.py::test_planner_complexity_falls_back_to_heuristic -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: FAIL（`planner_node` 不接受 `llm` / `complexity` 为 None）

- [ ] **Step 3: 实现**

在 `src/deepresearch_agent/agents/nodes.py` 顶部导入区加：

```python
from deepresearch_agent.query_complexity import classify_complexity
```

把 `planner_node` 改成（新增 `llm` 参数 + 在解析后写 `complexity`）：

```python
def planner_node(
    state: ResearchState,
    domain_pack: DomainPack,
    repository: CompanyRepository,
    llm=None,
) -> ResearchState:
    resolution = resolve_supplier(state.question, repository)
    state.supplier_resolution = resolution
    state.supplier_name = resolution.legal_name
    state.company_credit_code = resolution.unified_social_credit_code
    state.complexity = classify_complexity(state.question, repository, llm)
    if resolution.status != "resolved" or resolution.legal_name is None:
        state.plan = []
        return state

    state.plan = [
        ResearchPlanItem(
            dimension=dimension,
            question=_DIMENSION_QUESTIONS[dimension].format(
                supplier_name=resolution.legal_name
            ),
            priority=1 if dimension in {"company_identity", "registration"} else 2,
        )
        for dimension in domain_pack.research_dimensions
    ]
    return state
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_planner_sets_complexity_from_llm tests/test_nodes.py::test_planner_complexity_falls_back_to_heuristic -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS

- [ ] **Step 5: 回归既有 planner 测试**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k planner -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 全绿（既有 3 个 planner 测试 + 新 2 个）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C2-2 planner 调用 classify_complexity 写入 state.complexity"
```

---

### Task 3：researcher 重构为检索分派器

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`researcher_node` + 新增私有辅助）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `HybridContext`（`context.seeds[i].code/name/score/controllers[j].display_name/via_person`、`context.shared_controllers[k].name/controlled_seeds/via_person`），来自注入的 `graph_searcher(query) -> HybridContext`；注入的 `scope_retriever.search(query, k) -> list[hit]`（`hit.unified_social_credit_code/legal_name/text/score`）。复用本文件已有的 `_group_scope_hits`、常量 `SCOPE_SEARCH_K`。
- Produces: `researcher_node(state, tools, domain_pack, scope_retriever=None, graph_searcher=None, scope_enabled=False, graph_enabled=False)`；设 `state.retrieval_mode`、按模式填 `state.evidence` / `state.scope_candidates` / (`state.graph_candidates` + `state.shared_controllers`) / `state.retrieval_available`。新增私有函数 `_decide_retrieval_mode`、`_research_named`、`_retrieve_scope`、`_retrieve_graph`、`_build_graph_findings`。既有 3 参调用（resolved 场景）走 `named`，行为不变。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加（这些是新的 researcher 级检索测试，取代后续将删除的旧节点测试）：

```python
class _ScopeHit:
    def __init__(self, code, name, text, score):
        self.unified_social_credit_code = code
        self.legal_name = name
        self.section_label = None
        self.text = text
        self.score = score


class _ScopeRetriever:
    def search(self, query, k):
        return [
            _ScopeHit("X", "示例科技股份有限公司", "工业设备制造", 0.95),
            _ScopeHit("X", "示例科技股份有限公司", "工业设备销售", 0.80),
        ]


def test_researcher_scope_mode_groups_candidates(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="工业设备制造", domain="procurement"), DOMAIN_PACK, repository
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), scope_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1
    assert updated.scope_candidates[0].unified_social_credit_code == "X"
    assert updated.scope_candidates[0].top_score == 0.95
    assert updated.retrieval_available is True


def test_researcher_scope_mode_unavailable_when_retriever_missing(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"), DOMAIN_PACK, repository
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, scope_retriever=None, scope_enabled=True
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert updated.scope_candidates == []


def test_researcher_graph_mode_builds_candidates_and_shared(tmp_path, company_database_path):
    graph = _ownership_graph(tmp_path)
    seeds = ["91110000000000111A", "91110000000000222B", "91110000000000333C"]
    searcher = lambda query: assemble_subgraph_context(graph, seeds, query=query)
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, graph_searcher=searcher, graph_enabled=True
    )
    assert updated.retrieval_mode == "graph"
    names = {c.legal_name for c in updated.graph_candidates}
    assert {"甲公司", "乙公司", "丙公司"} <= names
    shared = {s.controller_name: s for s in updated.shared_controllers}
    assert shared["共同控股集团有限公司"].via_person is False
    assert shared["张三"].via_person is True
    assert "须人工复核" in shared["张三"].note


def test_researcher_graph_mode_falls_back_to_scope_when_searcher_absent(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), scope_enabled=True,
        graph_searcher=None, graph_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1


def test_researcher_ambiguous_is_unresolved_and_does_not_retrieve(company_database_path):
    repository = _repository(company_database_path)
    state = ResearchState(question="核验示例", domain="procurement")
    state = planner_node(state, DOMAIN_PACK, repository)
    # 若该 fixture 下"核验示例"非 ambiguous，则手工置 ambiguous 以覆盖分支
    from deepresearch_agent.company_models import CompanyResolution
    if state.supplier_resolution.status != "ambiguous":
        state.supplier_resolution = CompanyResolution(status="ambiguous", candidates=[])
        state.supplier_name = None
    updated = researcher_node(state, ToolRegistry(), DOMAIN_PACK)
    assert updated.retrieval_mode == "unresolved"
    assert updated.evidence == []
    assert updated.scope_candidates == []
    assert updated.graph_candidates == []
```

在 `tests/test_nodes.py` 顶部导入区补齐（若尚未导入）：

```python
from deepresearch_agent.graph_retrieval import assemble_subgraph_context
from deepresearch_agent.ownership_graph import load_ownership_graph
```

（`_ownership_graph(tmp_path)` 辅助已在本文件底部定义，复用它；`_LINKS` 常量同上。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "researcher_scope or researcher_graph or researcher_ambiguous" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: FAIL（`researcher_node` 不接受 `scope_retriever`/`scope_enabled` 等参数）

- [ ] **Step 3: 实现 researcher 分派器**

在 `src/deepresearch_agent/agents/nodes.py`，把整个 `researcher_node` 函数（现约 68-117 行）替换为：

```python
def researcher_node(
    state: ResearchState,
    tools: ToolRegistry,
    domain_pack: DomainPack,
    scope_retriever=None,
    graph_searcher=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
) -> ResearchState:
    mode = _decide_retrieval_mode(state, scope_enabled, graph_enabled)
    state.retrieval_mode = mode
    if mode == "named":
        _research_named(state, tools, domain_pack)
    elif mode == "scope":
        _retrieve_scope(state, scope_retriever)
    elif mode == "graph":
        _retrieve_graph(state, graph_searcher)
    return state


def _decide_retrieval_mode(
    state: ResearchState, scope_enabled: bool, graph_enabled: bool
) -> str:
    resolution = state.supplier_resolution
    status = resolution.status if resolution is not None else "not_found"
    if status == "resolved":
        return "named"
    if status == "ambiguous":
        return "unresolved"
    level = state.complexity.level if state.complexity is not None else "simple"
    if level in {"medium", "complex"} and graph_enabled:
        return "graph"
    if scope_enabled:
        return "scope"
    return "unresolved"


def _research_named(state: ResearchState, tools: ToolRegistry, domain_pack: DomainPack) -> None:
    if state.supplier_name is None or state.company_credit_code is None:
        raise ValueError("planner_node must resolve a company before researcher_node")

    if "get_company_profile" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_company_profile", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_profile_evidence(state, result.data)

    if "get_company_contact" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_company_contact", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_contact_evidence(state, result.data)

    if "get_ownership_neighborhood" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_ownership_neighborhood", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_ownership_evidence(state, result.data)

    if "get_related_parties" in domain_pack.allowed_tools:
        result = _run_tool(
            state, tools, "get_related_parties", {"credit_code": state.company_credit_code}
        )
        if result is not None and result.status == "ok":
            _append_related_parties_evidence(state, result.data)

    state.iteration += 1


def _retrieve_scope(state: ResearchState, retriever) -> None:
    if retriever is None:
        state.retrieval_available = False
        return
    try:
        hits = retriever.search(state.question, SCOPE_SEARCH_K)
    except Exception:
        state.retrieval_available = False
        return
    state.scope_candidates = _group_scope_hits(hits)


def _retrieve_graph(state: ResearchState, searcher) -> None:
    if searcher is None:
        state.retrieval_available = False
        return
    try:
        context = searcher(state.question)
    except Exception:
        state.retrieval_available = False
        return
    candidates, shared = _build_graph_findings(context)
    state.graph_candidates = candidates
    state.shared_controllers = shared


def _build_graph_findings(context):
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
    return candidates, shared
```

> 说明：`SCOPE_SEARCH_K` 常量与 `_group_scope_hits` 目前定义在 `writer_node` 之后，作为模块级名字在运行期可用，位置不用动。`scope_search_node`/`graph_search_node` 暂不删除（Task 6 处理），本步不改它们。

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "researcher" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS（新增 5 项 + 既有 named researcher 测试全绿）

- [ ] **Step 5: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 全绿（旧 `scope_search_node`/`graph_search_node`/`test_graph.py` 仍走旧图，不受影响）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C2-3 researcher 重构为按复杂度分派的检索层"
```

---

### Task 4：writer 扩为唯一生成层

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`writer_node` + 新增 `_write_scope_report`/`_write_graph_report`）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `state.retrieval_mode`、`state.retrieval_available`、`state.scope_candidates`、`state.graph_candidates`、`state.shared_controllers`；复用常量 `_SCOPE_OPEN_QUESTIONS`、`_GRAPH_OPEN_QUESTIONS`。
- Produces: `writer_node(state, domain_pack)`（签名不变）依 `retrieval_mode` 生成 `SupplierReport`(named/unresolved) / `ScopeSearchReport`(scope) / `GraphSearchReport`(graph)，含不可用分支。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_writer_scope_report_from_candidates(company_database_path):
    from deepresearch_agent.state import Citation, Evidence, ScopeCandidate

    state = ResearchState(question="工业设备制造", domain="procurement")
    state.retrieval_mode = "scope"
    state.scope_candidates = [
        ScopeCandidate(
            unified_social_credit_code="X",
            legal_name="示例科技股份有限公司",
            matched_clauses=[
                Evidence(
                    claim="工业设备制造",
                    dimension="business_scope_match",
                    confidence=0.9,
                    citation=Citation(
                        source_id="company:X", title="t", url="local://companies/X", snippet="工业设备制造"
                    ),
                )
            ],
            top_score=0.9,
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report is not None
    assert updated.scope_report.recommendation == "insufficient_evidence"
    assert "候选" in updated.scope_report.summary
    assert updated.report is None


def test_writer_scope_report_unavailable(company_database_path):
    state = ResearchState(question="哪些企业能做注塑成型", domain="procurement")
    state.retrieval_mode = "scope"
    state.retrieval_available = False
    updated = writer_node(state, DOMAIN_PACK)
    assert "不可用" in updated.scope_report.summary
    assert updated.scope_report.candidates == []


def test_writer_graph_report_from_findings(company_database_path):
    from deepresearch_agent.state import GraphSearchCandidate, SharedControllerFinding

    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    state.retrieval_mode = "graph"
    state.graph_candidates = [
        GraphSearchCandidate(
            unified_social_credit_code="A", legal_name="甲公司", top_score=0.9,
            ultimate_controllers=["共同控股集团有限公司"],
        )
    ]
    state.shared_controllers = [
        SharedControllerFinding(
            controller_name="张三", controlled_companies=["甲公司", "乙公司"],
            via_person=True, note="经同名自然人推断，须人工复核",
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.graph_report is not None
    assert updated.graph_report.recommendation == "insufficient_evidence"
    assert "共享控制人" in updated.graph_report.summary
    assert any("围标" in q or "须人工复核" in q for q in updated.graph_report.open_questions)
    assert updated.report is None


def test_writer_graph_report_unavailable(company_database_path):
    state = ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement")
    state.retrieval_mode = "graph"
    state.retrieval_available = False
    updated = writer_node(state, DOMAIN_PACK)
    assert "不可用" in updated.graph_report.summary
    assert updated.graph_report.candidates == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "writer_scope or writer_graph" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: FAIL（writer 不识别 `retrieval_mode`，`scope_report`/`graph_report` 为 None）

- [ ] **Step 3: 实现 writer 分支**

在 `src/deepresearch_agent/agents/nodes.py`，把 `writer_node` 函数（现约 127-158 行）**开头**加入模式分支，其余 named 逻辑保持不变：

```python
def writer_node(state: ResearchState, domain_pack: DomainPack) -> ResearchState:
    if state.retrieval_mode == "scope":
        return _write_scope_report(state)
    if state.retrieval_mode == "graph":
        return _write_graph_report(state)
    if state.supplier_name is None:
        return _write_unresolved_supplier_report(state)

    open_questions = [
        f"补充当前数据源缺失的研究维度：{dimension}。"
        for dimension in state.missing_dimensions
    ]
    open_questions.extend(
        [
            "接入制裁和监管名单数据。",
            "接入司法案件与负面新闻数据。",
            "接入财务数据。",
            "接入产能、交期与质量认证数据。",
            "接入内部采购履约数据。",
        ]
    )
    open_questions.append(
        "股权关联方为线索级推断（尤其同名自然人），须人工复核，不构成控制关系或采购结论。"
    )
    state.report = SupplierReport(
        supplier_name=state.supplier_name,
        recommendation="insufficient_evidence",
        summary="已完成本地工商和联系方式核验；现有数据不足以作出采购批准或风险结论。",
        risks=[
            "当前数据源不包含制裁、司法、负面新闻、财务和采购履约数据，"
            "不能据此作出采购批准或风险结论。"
        ],
        evidence_table=state.evidence,
        open_questions=open_questions,
    )
    return state
```

紧接 `writer_node` 之后（`SCOPE_SEARCH_K = 10` 之前的位置附近）新增两个生成函数：

```python
def _write_scope_report(state: ResearchState) -> ResearchState:
    if not state.retrieval_available:
        state.scope_report = ScopeSearchReport(
            query=state.question,
            summary="经营范围语义检索不可用：请安装 .[rag] 可选依赖并运行 "
            "scripts/build_scope_index.py 构建索引。",
            candidates=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"],
        )
        return state
    candidates = state.scope_candidates
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


def _write_graph_report(state: ResearchState) -> ResearchState:
    if not state.retrieval_available:
        state.graph_report = GraphSearchReport(
            query=state.question,
            summary="图谱关系检索不可用：请安装 .[rag] 可选依赖并构建 FAISS 经营范围索引与公司图谱。",
            candidates=[],
            shared_controllers=[],
            open_questions=["安装 .[rag] 可选依赖并构建 FAISS 索引。"],
        )
        return state
    candidates = state.graph_candidates
    shared = state.shared_controllers
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

> 说明：`_SCOPE_OPEN_QUESTIONS`、`_GRAPH_OPEN_QUESTIONS`、`ScopeSearchReport`、`GraphSearchReport` 均已在本文件定义/导入。旧 `scope_search_node`/`graph_search_node` 仍保留（Task 6 删）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "writer" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS（新增 4 项 + 既有 `test_writer_never_approves_from_registration_data_only` 全绿）

- [ ] **Step 5: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C2-4 writer 扩为唯一生成层（scope/graph/named/unresolved）"
```

---

### Task 5：graph 线性化 + 检索器/LLM 注入 + run_research

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`（整体重写）
- Test: `tests/test_graph.py`（按线性图重写）；`tests/test_api.py`（回归验证，不改）

**Interfaces:**
- Consumes: `planner_node(..., llm)`、`researcher_node(..., scope_retriever, graph_searcher, scope_enabled, graph_enabled)`、`writer_node`、`critique_node`；`load_scope_retriever`、`hybrid_search`、`load_ownership_graph`、`build_deepseek_classifier`。
- Produces: `build_graph(domain_pack, repository, scope_retriever=None, graph_searcher=None, llm=None, scope_enabled=False, graph_enabled=False)`（线性图）；`run_research(question, domain, database_path, index_path, enable_scope=False, enable_graph=False)`（签名不变）；`_should_continue`、`run_compiled` 保留；新增 `_build_scope_retriever`、`_build_graph_searcher`、`_build_llm`。

- [ ] **Step 1: 重写 test_graph.py**

把 `tests/test_graph.py` 整体替换为：

```python
import sys
from pathlib import Path

import pytest

from deepresearch_agent.agents.graph import _should_continue, build_graph, run_compiled, run_research
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import load_domain_pack
from deepresearch_agent.state import ResearchState

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

DOMAIN_PACK = load_domain_pack(Path("domains/procurement/domain.yaml"))


def test_graph_generates_source_backed_company_report(company_database_path):
    final_state = run_research(
        "核验示例科技股份有限公司的工商和经营范围",
        database_path=company_database_path,
    )
    assert final_state.report.supplier_name == "示例科技股份有限公司"
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table
    assert {item.dimension for item in final_state.evidence} == set(DOMAIN_PACK.research_dimensions)
    assert "工业设备制造" in " ".join(item.claim for item in final_state.evidence)


def test_graph_deduplicates_evidence_and_tool_calls(company_database_path):
    final_state = run_research("核验示例科技股份有限公司", database_path=company_database_path)
    evidence_keys = [
        (item.dimension, item.citation.source_id, item.claim) for item in final_state.evidence
    ]
    trace_keys = [(item.tool_name, tuple(sorted(item.args.items()))) for item in final_state.trace]
    assert len(evidence_keys) == len(set(evidence_keys))
    assert len(trace_keys) == len(set(trace_keys))


def test_unknown_company_without_retrieval_is_unresolved_report(company_database_path):
    final_state = run_research("核验不存在企业", database_path=company_database_path)
    assert final_state.report is not None
    assert final_state.report.recommendation == "insufficient_evidence"
    assert final_state.report.evidence_table == []
    assert final_state.iteration == 0
    assert final_state.scope_report is None
    assert final_state.graph_report is None


def test_router_stops_when_iteration_budget_is_exhausted():
    state = ResearchState(
        question="核验示例科技股份有限公司",
        domain="procurement",
        missing_dimensions=["contact"],
        iteration=1,
        max_iterations=3,
    )
    assert _should_continue(state) == "researcher"
    state.iteration = 3
    assert _should_continue(state) == "writer"


class _ScopeHit:
    def __init__(self, code, name, text, score):
        self.unified_social_credit_code = code
        self.legal_name = name
        self.section_label = None
        self.text = text
        self.score = score


class _ScopeRetriever:
    def search(self, query, k):
        return [_ScopeHit("X", "示例科技股份有限公司", "工业设备制造", 0.95)]


def test_capability_question_routes_to_scope_when_retriever_injected(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, scope_retriever=_ScopeRetriever(), scope_enabled=True
    )
    state = run_compiled(app, "哪些企业能做注塑成型", "procurement")
    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert state.report is None


def test_named_company_verifies_even_with_scope_retriever(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, scope_retriever=_ScopeRetriever(), scope_enabled=True
    )
    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")
    assert state.report is not None
    assert state.report.supplier_name == "示例科技股份有限公司"
    assert state.scope_report is None


def _stub_graph_searcher(query):
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext

    return HybridContext(
        query=query,
        seeds=[SeedContext(code="X", name="示例科技股份有限公司", score=0.9, controllers=[], neighbors=[])],
        shared_controllers=[],
    )


def test_relationship_capability_routes_to_graph_when_searcher_injected(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, graph_searcher=_stub_graph_searcher, graph_enabled=True
    )
    state = run_compiled(app, "哪些做注塑的供应商互相关联", "procurement")
    assert state.graph_report is not None
    assert state.graph_report.candidates
    assert state.report is None


def test_named_company_verifies_even_with_graph_searcher(company_database_path):
    repository = CompanyRepository(company_database_path)
    app = build_graph(
        DOMAIN_PACK, repository, graph_searcher=_stub_graph_searcher, graph_enabled=True
    )
    state = run_compiled(app, "核验示例科技股份有限公司", "procurement")
    assert state.report is not None
    assert state.graph_report is None


def test_run_research_without_retrieval_keeps_supplier_report(company_database_path):
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


def test_run_research_enable_graph_without_index_degrades(company_database_path, tmp_path):
    missing_index = tmp_path / "does_not_exist.faiss"
    state = run_research(
        "哪些做注塑的供应商互相关联",
        database_path=company_database_path,
        index_path=missing_index,
        enable_graph=True,
    )
    assert state.graph_report is not None
    assert "不可用" in state.graph_report.summary
    assert state.report is None


@pytest.mark.slow
def test_run_research_scope_search_end_to_end(company_database_path, tmp_path):
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

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: FAIL（`build_graph` 尚不接受 `scope_retriever`/`scope_enabled`/`graph_searcher`/`graph_enabled`；且旧图仍把 not_found 路由到已不存在于线性图的节点）

- [ ] **Step 3: 重写 graph.py**

把 `src/deepresearch_agent/agents/graph.py` 整体替换为：

```python
from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from deepresearch_agent.agents.nodes import (
    critique_node,
    planner_node,
    researcher_node,
    writer_node,
)
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.domain import DomainPack, load_domain_pack
from deepresearch_agent.state import ResearchState
from deepresearch_agent.tools.procurement import build_procurement_tool_registry


DEFAULT_DATABASE_PATH = Path("data/procurement/derived/companies.sqlite3")
DEFAULT_INDEX_PATH = Path("data/procurement/derived/scope_index.faiss")


def _should_continue(state: ResearchState) -> str:
    if state.missing_dimensions and state.iteration < state.max_iterations:
        return "researcher"
    return "writer"


def build_graph(
    domain_pack: DomainPack,
    repository: CompanyRepository,
    scope_retriever=None,
    graph_searcher=None,
    llm=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)
    graph.add_node("planner", lambda state: planner_node(state, domain_pack, repository, llm))
    graph.add_node(
        "researcher",
        lambda state: researcher_node(
            state, tools, domain_pack, scope_retriever, graph_searcher, scope_enabled, graph_enabled
        ),
    )
    graph.add_node("critic", critique_node)
    graph.add_node("writer", lambda state: writer_node(state, domain_pack))
    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic",
        _should_continue,
        {"researcher": "researcher", "writer": "writer"},
    )
    graph.add_edge("writer", END)
    return graph.compile()


def run_compiled(compiled_graph, question: str, domain: str) -> ResearchState:
    result = compiled_graph.invoke(ResearchState(question=question, domain=domain))
    if isinstance(result, ResearchState):
        return result
    return ResearchState.model_validate(result)


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
    scope_retriever = (
        _build_scope_retriever(database_path, index_path)
        if (enable_scope or enable_graph)
        else None
    )
    graph_searcher = (
        _build_graph_searcher(database_path, scope_retriever) if enable_graph else None
    )
    app = build_graph(
        domain_pack,
        repository,
        scope_retriever=scope_retriever,
        graph_searcher=graph_searcher,
        llm=_build_llm(),
        scope_enabled=enable_scope,
        graph_enabled=enable_graph,
    )
    return run_compiled(app, question, domain)


def _build_scope_retriever(database_path: str | Path, index_path: str | Path):
    try:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever

        if Path(index_path).exists():
            return load_scope_retriever(database_path, index_path, BgeEmbedder())
    except Exception:
        return None
    return None


def _build_graph_searcher(database_path: str | Path, scope_retriever):
    if scope_retriever is None:
        return None
    try:
        from deepresearch_agent.graph_retrieval import hybrid_search
        from deepresearch_agent.ownership_graph import load_ownership_graph

        graph = load_ownership_graph(CompanyRepository(database_path))
        return lambda query: hybrid_search(query, scope_retriever, graph)
    except Exception:
        return None


def _build_llm():
    try:
        from deepresearch_agent.llm.deepseek import build_deepseek_classifier

        return build_deepseek_classifier()
    except Exception:
        return None
```

- [ ] **Step 4: 跑 test_graph.py 确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS（`slow` 用例默认不选）

- [ ] **Step 5: 回归 API（确认注入默认值兼容两参调用）**

Run: `.\.conda-env\python.exe -m pytest tests/test_api.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: PASS（`api.py` 仍以 `build_graph(domain_pack, repository)` 两参调用，新参数走默认值）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/graph.py tests/test_graph.py
git commit -m "功能：C2-5 图线性化，检索器/LLM 注入，run_research 按复杂度分流"
```

---

### Task 6：删除旧 scope/graph 节点，收口测试

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（删除 `scope_search_node`、`graph_search_node`）
- Modify: `tests/test_nodes.py`（删除引用旧节点的测试）

**Interfaces:**
- Produces: `nodes.py` 不再导出 `scope_search_node`/`graph_search_node`；检索/生成职责全部落在 `researcher_node`/`writer_node`。

- [ ] **Step 1: 删除旧节点测试**

在 `tests/test_nodes.py` 删除这 5 个函数（它们导入并调用即将删除的旧节点）：`test_scope_search_node_returns_unavailable_when_retriever_missing`、`test_scope_search_node_groups_hits_into_candidates`、`test_scope_search_node_reports_no_matches_when_empty`、`test_graph_search_node_reports_candidates_and_shared_controllers`、`test_graph_search_node_unavailable_when_searcher_missing`。

（它们的覆盖已由 Task 3 的 `test_researcher_scope_mode_*`/`test_researcher_graph_mode_*` 与 Task 4 的 `test_writer_scope_*`/`test_writer_graph_*` 接管。）

- [ ] **Step 2: 删除旧节点函数**

在 `src/deepresearch_agent/agents/nodes.py` 删除 `scope_search_node`（约 173-209 行）与 `graph_search_node`（约 251-317 行）两个函数整体。**保留** `SCOPE_SEARCH_K`、`_SCOPE_OPEN_QUESTIONS`、`_group_scope_hits`、`_GRAPH_OPEN_QUESTIONS`（被 researcher/writer 复用）。

- [ ] **Step 3: 确认无残留引用**

Run: `.\.conda-env\python.exe -m pytest --collect-only -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 收集期无 ImportError（无文件再引用 `scope_search_node`/`graph_search_node`）

若报错，用编辑器全局搜索 `scope_search_node`、`graph_search_node` 定位并清除残留引用后重试。

- [ ] **Step 4: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2`
Expected: 全绿

- [ ] **Step 5: 手动 CLI 冒烟（可选，若本地有真实库与索引则跑）**

Run: `.\.conda-env\python.exe -m deepresearch_agent.cli "核验示例科技股份有限公司" --database <db>`
Expected: 打印 SupplierReport（若无真实库则跳过此步）

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C2-6 删除 scope_search/graph_search 独立节点，职责收口到检索/生成两层"
```

---

## 收尾

全部 6 个任务完成、`.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c2` 全绿后，用 **superpowers:finishing-a-development-branch** 处理分支合并。

## Self-Review

- **Spec 覆盖**：planner 分类=Task 2；researcher 派发矩阵（named/scope/graph/unresolved + 回退）=Task 3；writer 唯一生成（四模式 + 不可用）=Task 4；图线性化 + 注入 + run_research 分流 + API 形状不变=Task 5；撤销独立节点=Task 6；state 新字段=Task 1；红线（insufficient_evidence、人工复核、只发查询文本、无 schema 变更）贯穿 Global Constraints 与各任务断言。CLI 因 `run_research` 签名不变而无需改动（spec 中"可选打印 complexity"按 YAGNI 略去）。
- **占位符**：无 TBD/TODO；每个改码步骤含完整代码。
- **类型一致**：`_decide_retrieval_mode`/`_research_named`/`_retrieve_scope`/`_retrieve_graph`/`_build_graph_findings` 在 Task 3 定义，Task 4 `_write_scope_report`/`_write_graph_report` 消费的 `scope_candidates`/`graph_candidates`/`shared_controllers` 与 Task 1 字段名一致；`build_graph` 新参数（`scope_retriever`/`graph_searcher`/`llm`/`scope_enabled`/`graph_enabled`）在 Task 5 定义并由 `run_research` 传入，与 Task 3 `researcher_node` 形参顺序一致。
