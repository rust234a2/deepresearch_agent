# C4 降级链 + 降级留痕 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 graph 检索运行时失败能降级到 scope（消除现有不对称），并把运行时失败留痕到 `state.degradations`、由 writer 并入报告 `open_questions`。

**Architecture:** researcher 的 `graph` 分支区分"运行时失败（降级/留痕）"与"配置性缺失（行为不变、不留痕）"：`_retrieve_graph` 运行时抛异常时返回错误串，researcher 据此降级到 scope 或记"无可用降级路径"；`_retrieve_scope` 运行时失败自记一条。writer 两个报告生成函数（可用 + 不可用分支）把 `state.degradations` 插到 `open_questions` 最前面。

**Tech Stack:** Python 3、Pydantic、LangGraph、pytest。复用 `_retrieve_scope`/`_group_scope_hits`/`_build_graph_findings`/`ScopeSearchReport`/`GraphSearchReport`。

## Global Constraints

- 报告对已解析企业固定 `recommendation="insufficient_evidence"`；绝不写"未发现风险"或采购结论。
- **绝不隐藏问题**：运行时失败必须留痕；配置性回退（检索器为 None、LLM 回退启发式）**不记**。
- 不引入外部调用、重试、新依赖；无 SQLite schema 变更。
- `graph.py` / `cli.py` / `api.py` 不改（`researcher_node` 签名不变）。
- Windows 测试命令：`.\.conda-env\python.exe -m pytest <target> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`（`slow` 默认不选）。
- 每个任务结束提交一次；中文提交信息。

## 文件结构

- `src/deepresearch_agent/state.py` — 加 `degradations` 字段（Task 1）。
- `src/deepresearch_agent/agents/nodes.py` — `_retrieve_graph` 返回值 + `researcher_node` graph 分支降级 + `_retrieve_scope` 留痕（Task 2）；两个 writer 并入 degradations（Task 3）。
- `tests/test_nodes.py` — 追加检索层 + writer 单元测试（Task 2、3）。
- `tests/test_graph.py` — 追加端到端降级测试（Task 4）。

---

### Task 1：state 加 `degradations` 字段

**Files:**
- Modify: `src/deepresearch_agent/state.py`
- Test: `tests/test_nodes.py`

**Interfaces:**
- Produces: `ResearchState.degradations: list[str]`（默认 `[]`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_research_state_has_degradations_field():
    state = ResearchState(question="q", domain="procurement")
    assert state.degradations == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_research_state_has_degradations_field -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: FAIL（`AttributeError: ... has no attribute 'degradations'`）

- [ ] **Step 3: 实现字段**

在 `src/deepresearch_agent/state.py` 的 `ResearchState` 里，`shared_controllers` 字段之后加：

```python
    degradations: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_research_state_has_degradations_field -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/state.py tests/test_nodes.py
git commit -m "功能：C4-1 ResearchState 加 degradations 降级留痕字段"
```

---

### Task 2：检索层降级（researcher + `_retrieve_graph` + `_retrieve_scope`）

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`_retrieve_graph`、`researcher_node` 的 graph 分支、`_retrieve_scope`）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `state.degradations`（Task 1）、已有的 `_ScopeRetriever`（test_nodes.py 中 C2 已定义的桩：`search` 返回 1 条 code="X" 的命中）、`_group_scope_hits`、`_build_graph_findings`、`SCOPE_SEARCH_K`。
- Produces: `_retrieve_graph(state, searcher) -> str | None`（运行时异常返回 `str(exc)`，成功/缺失返回 `None`）；`researcher_node` graph 分支在运行时失败时降级到 scope 或记"无可用降级路径"；`_retrieve_scope` 运行时失败追加一条 degradation。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_retrieve_graph_returns_error_string_on_exception():
    from deepresearch_agent.agents.nodes import _retrieve_graph

    state = ResearchState(question="q", domain="procurement")

    def boom(query):
        raise RuntimeError("图加载失败")

    err = _retrieve_graph(state, boom)
    assert err is not None and "图加载失败" in err
    assert state.retrieval_available is False


def test_retrieve_graph_returns_none_on_missing_and_success():
    from deepresearch_agent.agents.nodes import _retrieve_graph
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext

    missing_state = ResearchState(question="q", domain="procurement")
    assert _retrieve_graph(missing_state, None) is None
    assert missing_state.retrieval_available is False

    ok_state = ResearchState(question="q", domain="procurement")

    def searcher(query):
        return HybridContext(
            query=query,
            seeds=[SeedContext(code="X", name="示例", score=0.9, controllers=[], neighbors=[])],
            shared_controllers=[],
        )

    assert _retrieve_graph(ok_state, searcher) is None
    assert len(ok_state.graph_candidates) == 1


def test_researcher_graph_runtime_failure_degrades_to_scope(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    def boom(query):
        raise RuntimeError("图加载失败")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_ScopeRetriever(), graph_searcher=boom,
        scope_enabled=True, graph_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert len(updated.scope_candidates) == 1
    assert updated.retrieval_available is True
    assert len(updated.degradations) == 1
    assert "已降级为经营范围检索" in updated.degradations[0]
    assert "图加载失败" in updated.degradations[0]


def test_researcher_graph_runtime_failure_without_scope_records_no_path(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些做注塑的供应商互相关联", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    def boom(query):
        raise RuntimeError("图加载失败")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=None, graph_searcher=boom,
        scope_enabled=False, graph_enabled=True,
    )
    assert updated.retrieval_mode == "graph"
    assert updated.retrieval_available is False
    assert len(updated.degradations) == 1
    assert "无可用降级路径" in updated.degradations[0]


def test_researcher_scope_runtime_failure_records_degradation(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"),
        DOMAIN_PACK, repository,
    )

    class _BoomRetriever:
        def search(self, query, k):
            raise RuntimeError("faiss 索引损坏")

    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK,
        scope_retriever=_BoomRetriever(), scope_enabled=True,
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert len(updated.degradations) == 1
    assert "经营范围检索运行时失败" in updated.degradations[0]


def test_researcher_missing_retriever_records_no_degradation(company_database_path):
    repository = _repository(company_database_path)
    state = planner_node(
        ResearchState(question="哪些企业能做注塑成型", domain="procurement"),
        DOMAIN_PACK, repository,
    )
    updated = researcher_node(
        state, ToolRegistry(), DOMAIN_PACK, scope_retriever=None, scope_enabled=True
    )
    assert updated.retrieval_mode == "scope"
    assert updated.retrieval_available is False
    assert updated.degradations == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "retrieve_graph or graph_runtime or scope_runtime or missing_retriever_records" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: FAIL（`_retrieve_graph` 现返回 `None`、不返回错误串；researcher graph 分支不降级；`_retrieve_scope` 不记 degradation）

- [ ] **Step 3: 实现 `_retrieve_graph` 返回错误串**

在 `src/deepresearch_agent/agents/nodes.py`，把 `_retrieve_graph` 替换为：

```python
def _retrieve_graph(state: ResearchState, searcher) -> str | None:
    if searcher is None:
        state.retrieval_available = False
        return None
    try:
        context = searcher(state.question)
    except Exception as exc:
        state.retrieval_available = False
        return str(exc)
    candidates, shared = _build_graph_findings(context)
    state.graph_candidates = candidates
    state.shared_controllers = shared
    return None
```

- [ ] **Step 4: 实现 `researcher_node` graph 分支降级**

把 `researcher_node` 里的 graph 分支：

```python
    elif mode == "graph":
        _retrieve_graph(state, graph_searcher)
```

替换为：

```python
    elif mode == "graph":
        graph_error = _retrieve_graph(state, graph_searcher)
        if graph_error:
            if scope_retriever is not None:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，已降级为经营范围检索。"
                )
                state.retrieval_mode = "scope"
                state.retrieval_available = True
                _retrieve_scope(state, scope_retriever)
            else:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，无可用降级路径。"
                )
```

- [ ] **Step 5: 实现 `_retrieve_scope` 留痕**

把 `_retrieve_scope` 替换为（仅 `except` 分支新增一条 degradation，`retriever is None` 分支不动）：

```python
def _retrieve_scope(state: ResearchState, retriever) -> None:
    if retriever is None:
        state.retrieval_available = False
        return
    try:
        hits = retriever.search(state.question, SCOPE_SEARCH_K)
    except Exception as exc:
        state.retrieval_available = False
        state.degradations.append(f"经营范围检索运行时失败：{exc}。")
        return
    state.scope_candidates = _group_scope_hits(hits)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "retrieve_graph or graph_runtime or scope_runtime or missing_retriever_records" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: PASS（6 项）

- [ ] **Step 7: 全量回归（确认既有检索测试不破）**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: 全绿（既有 `test_researcher_scope_mode_*`/`test_researcher_graph_mode_*` 仍通过——它们用正常检索器，不触发降级）

- [ ] **Step 8: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C4-2 graph 运行时失败降级到 scope，运行时失败留痕"
```

---

### Task 3：writer 把降级并入 `open_questions`

**Files:**
- Modify: `src/deepresearch_agent/agents/nodes.py`（`_write_scope_report`、`_write_graph_report`）
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `state.degradations`、`state.retrieval_mode`、`state.retrieval_available`、`state.scope_candidates`；`_SCOPE_OPEN_QUESTIONS`、`_GRAPH_OPEN_QUESTIONS`。
- Produces: 两个报告的 `open_questions` 以 `state.degradations` 打头。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_writer_scope_report_surfaces_degradations():
    from deepresearch_agent.state import ScopeCandidate

    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "scope"
    state.degradations = ["图检索运行时失败：X，已降级为经营范围检索。"]
    state.scope_candidates = [
        ScopeCandidate(unified_social_credit_code="X", legal_name="甲", matched_clauses=[], top_score=0.9)
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report.open_questions[0] == "图检索运行时失败：X，已降级为经营范围检索。"


def test_writer_scope_unavailable_surfaces_degradations():
    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "scope"
    state.retrieval_available = False
    state.degradations = ["经营范围检索运行时失败：Y。"]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.scope_report.open_questions[0] == "经营范围检索运行时失败：Y。"


def test_writer_graph_unavailable_surfaces_degradations():
    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "graph"
    state.retrieval_available = False
    state.degradations = ["图检索运行时失败：Z，无可用降级路径。"]
    updated = writer_node(state, DOMAIN_PACK)
    assert updated.graph_report.open_questions[0] == "图检索运行时失败：Z，无可用降级路径。"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "writer_scope_report_surfaces or writer_scope_unavailable_surfaces or writer_graph_unavailable_surfaces" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: FAIL（`open_questions[0]` 不是降级串）

- [ ] **Step 3: 实现 `_write_scope_report` 并入降级**

把 `_write_scope_report` 的两处 `open_questions=` 改为以 `state.degradations` 打头：

不可用分支：

```python
            open_questions=list(state.degradations)
            + ["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"],
```

可用分支：

```python
        open_questions=list(state.degradations) + list(_SCOPE_OPEN_QUESTIONS),
```

- [ ] **Step 4: 实现 `_write_graph_report` 并入降级**

把 `_write_graph_report` 的两处 `open_questions=` 改为以 `state.degradations` 打头：

不可用分支：

```python
            open_questions=list(state.degradations) + ["安装 .[rag] 可选依赖并构建 FAISS 索引。"],
```

可用分支：

```python
        open_questions=list(state.degradations) + list(_GRAPH_OPEN_QUESTIONS),
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "writer_scope_report_surfaces or writer_scope_unavailable_surfaces or writer_graph_unavailable_surfaces" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: PASS（3 项）

- [ ] **Step 6: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: 全绿（既有 writer 测试的 `degradations` 为空，`open_questions` 前缀无变化）

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：C4-3 writer 把 degradations 并入报告 open_questions"
```

---

### Task 4：端到端降级（`build_graph` 整链）

**Files:**
- Test: `tests/test_graph.py`（仅新增测试，无新实现）

**Interfaces:**
- Consumes: `build_graph`、`run_compiled`、test_graph.py 中已定义的 `_ScopeRetriever`（返回 1 条 code="X" 命中）与 autouse `_offline_llm` fixture（强制启发式）。

- [ ] **Step 1: 写测试**

在 `tests/test_graph.py` 末尾追加：

```python
def test_graph_runtime_failure_degrades_to_scope_end_to_end(company_database_path):
    repository = CompanyRepository(company_database_path)

    def boom(query):
        raise RuntimeError("图加载失败")

    app = build_graph(
        DOMAIN_PACK, repository,
        scope_retriever=_ScopeRetriever(), graph_searcher=boom,
        scope_enabled=True, graph_enabled=True,
    )
    state = run_compiled(app, "哪些做注塑的供应商互相关联", "procurement")
    assert state.scope_report is not None
    assert state.scope_report.candidates
    assert "已降级为经营范围检索" in state.scope_report.open_questions[0]
    assert state.graph_report is None
    assert state.report is None
```

- [ ] **Step 2: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph.py::test_graph_runtime_failure_degrades_to_scope_end_to_end -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: PASS（Task 2、3 已实现降级 + 留痕，整链应直接通过；query=medium 经启发式路由 graph → boom 抛异常 → 降级 scope → scope 报告首条 open_question 为降级说明）

> 若失败：确认 `_offline_llm` fixture 在生效（强制启发式）、`_ScopeRetriever` 在 test_graph.py 顶部已定义（C2-5 引入）。这是纯集成验证，实现应已在 Task 2/3 完成，不需改产品代码。

- [ ] **Step 3: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c4`
Expected: 全绿

- [ ] **Step 4: 提交**

```bash
git add tests/test_graph.py
git commit -m "功能：C4-4 端到端验证 graph 运行时失败降级到 scope"
```

---

## 收尾

4 个任务完成、全量绿后，用 **superpowers:finishing-a-development-branch** 处理合并；按已确认的推送习惯，模块合并 + 测试绿后自动推 master。文档（architecture / project-memory / CLAUDE.md）在收尾前同步 C4：降级链行为 + `degradations` 字段。

## Self-Review

- **Spec 覆盖**：降级链（graph 运行时失败→scope / 无 scope 记无路径）=Task 2；scope 运行时留痕=Task 2；`degradations` 字段=Task 1；writer 并入=Task 3；端到端=Task 4；"配置性缺失不记"=Task 2 的 `test_researcher_missing_retriever_records_no_degradation`；红线（insufficient_evidence 不变、不改 graph/cli/api、无 schema/依赖变更）贯穿 Global Constraints。
- **占位符**：无 TBD/TODO；每个改码步骤含完整代码。
- **类型一致**：`_retrieve_graph -> str | None` 在 Task 2 定义并被 `researcher_node` graph 分支消费；`state.degradations`（Task 1）被 Task 2 追加、Task 3 读取；`_ScopeRetriever` 在 test_nodes.py（C2-3）与 test_graph.py（C2-5）均已定义，复用不重复定义。
