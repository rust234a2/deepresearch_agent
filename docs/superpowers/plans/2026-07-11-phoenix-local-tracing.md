# Phoenix 本地追踪 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `run_research` 加本地手动 span 追踪（图层包装四节点 + root span），在本地 Phoenix 看每次跑的检索模式/召回/降级/复杂度，默认关、仅本地、不外发企业数据。

**Architecture:** 新 `observability.py`：`configure_tracing`（幂等、可注入 exporter）+ `get_tracer`（未配置返 None → 透传）+ `traced_node` 包装器 + `reset_tracing`。`build_graph(enable_tracing=)` 用 `traced_node` 包四节点、attr_fn 从返回 state 抽标量属性；`run_research(enable_tracing=)` 配置追踪 + root span。CLI `--trace`。全用 OTel InMemorySpanExporter 测，不需起 Phoenix。

**Tech Stack:** Python、opentelemetry-sdk、pytest。复用 `build_graph`/`run_compiled`/`run_research`。

## Global Constraints

- **默认关**（`enable_tracing=False`）：正常跑 / CI / API / `/research` 不受影响、零开销；不启用时 `build_graph` 逐字不变。
- **仅本地**：OTLP exporter 只指向 localhost Phoenix（默认 `http://localhost:6006/v1/traces`），绝不指远程。
- **DeepSeek/分类只记 `level`/`method`，绝不记企业数据**（守 C1）；span 属性仅 OTel 标量（str/int/bool/float）。
- 无 LLM-eval、无外部 LLM；`arize-phoenix` 不作硬依赖（用户本地单独装 + `phoenix serve`）。
- `nodes.py`/`state.py`/`api.py`/SQLite schema/报告结构不改。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`。
- 每任务提交一次；中文提交信息。

## 文件结构

- 新 `src/deepresearch_agent/observability.py`（Task 1）。
- 改 `src/deepresearch_agent/agents/graph.py`（Task 2）、`src/deepresearch_agent/cli.py`（Task 2）。
- 改 `pyproject.toml`（`.[trace]` extra，Task 1）。
- 新 `tests/test_observability.py`（Task 1、3）；改 `tests/test_cli.py`（Task 2）。

---

### Task 1：`observability.py` + `.[trace]` 依赖

**Files:**
- Create: `src/deepresearch_agent/observability.py`
- Modify: `pyproject.toml`
- Test: `tests/test_observability.py`

**Interfaces:**
- Produces: `configure_tracing(exporter=None, endpoint=...) -> provider`（幂等）、`get_tracer() -> Tracer | None`、`reset_tracing() -> None`、`traced_node(name, node_fn, attr_fn=None) -> callable`。

- [ ] **Step 0: 装 otel（本会话一次）**

```powershell
.\.conda-env\python.exe -m pip install "opentelemetry-sdk>=1.20" "opentelemetry-exporter-otlp-proto-http>=1.20" --quiet
```

- [ ] **Step 1: 加 `.[trace]` extra**

`pyproject.toml` 的 `[project.optional-dependencies]` 里 `neo4j = [...]` 之后加：

```toml
trace = [
  "opentelemetry-sdk>=1.20",
  "opentelemetry-exporter-otlp-proto-http>=1.20",
]
```

- [ ] **Step 2: 写失败测试**

创建 `tests/test_observability.py`：

```python
import pytest

pytest.importorskip("opentelemetry")

from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: F401 —— 确认 sdk 可用
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from deepresearch_agent.observability import (
    configure_tracing,
    get_tracer,
    reset_tracing,
    traced_node,
)


@pytest.fixture(autouse=True)
def _clean_tracing():
    reset_tracing()
    yield
    reset_tracing()


def test_get_tracer_none_before_configure():
    assert get_tracer() is None


def test_traced_node_passthrough_when_unconfigured():
    calls = []

    def node(state):
        calls.append(state)
        return {"ok": state}

    wrapped = traced_node("planner", node)
    result = wrapped("S")
    assert result == {"ok": "S"} and calls == ["S"]


def test_traced_node_emits_span_with_attrs():
    mem = InMemorySpanExporter()
    configure_tracing(exporter=mem)

    def node(state):
        return {"retrieval_mode": "graph"}

    wrapped = traced_node(
        "researcher", node, attr_fn=lambda s: {"retrieval_mode": s["retrieval_mode"]}
    )
    out = wrapped("S")

    assert out == {"retrieval_mode": "graph"}
    spans = mem.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "researcher"
    assert spans[0].attributes["retrieval_mode"] == "graph"


def test_configure_tracing_idempotent():
    mem1 = InMemorySpanExporter()
    p1 = configure_tracing(exporter=mem1)
    p2 = configure_tracing(exporter=InMemorySpanExporter())
    assert p1 is p2  # 第二次不覆盖
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_observability.py -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.observability`）

- [ ] **Step 4: 实现 `observability.py`**

创建 `src/deepresearch_agent/observability.py`：

```python
from __future__ import annotations

_PROVIDER = None


def configure_tracing(exporter=None, endpoint: str = "http://localhost:6006/v1/traces"):
    """建 OTel TracerProvider 并注册 exporter。幂等：已配置则原样返回、不覆盖。"""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint)  # 仅本地 Phoenix，绝不指远程
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _PROVIDER = provider
    return provider


def get_tracer():
    """未配置 → None（调用方据此透传、零开销、也不导入 otel）。"""
    if _PROVIDER is None:
        return None
    from opentelemetry import trace

    return trace.get_tracer("deepresearch_agent")


def reset_tracing() -> None:
    """清全局，测试用，避免跨用例串。"""
    global _PROVIDER
    _PROVIDER = None


def traced_node(name: str, node_fn, attr_fn=None):
    """图层节点包装器：开 span → 跑节点 → 从返回值抽属性 → 关 span；未配置则透传。"""

    def wrapped(state):
        tracer = get_tracer()
        if tracer is None:
            return node_fn(state)
        with tracer.start_as_current_span(name) as span:
            result = node_fn(state)
            if attr_fn is not None:
                for key, value in attr_fn(result).items():
                    if value is not None:
                        span.set_attribute(key, value)
            return result

    return wrapped
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_observability.py -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: PASS（4 项）

- [ ] **Step 6: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: 全绿（observability 是新增、独立，既有不受影响）

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/observability.py tests/test_observability.py pyproject.toml
git commit -m "功能：Trace-1 observability 模块（configure/get_tracer/traced_node）与 .[trace] 依赖"
```

---

### Task 2：图层接线 + CLI `--trace`

**Files:**
- Modify: `src/deepresearch_agent/agents/graph.py`（`build_graph`/`run_research` 加 `enable_tracing` + root span）、`src/deepresearch_agent/cli.py`（`--trace`）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `traced_node`/`configure_tracing`/`get_tracer`（Task 1）。
- Produces: `build_graph(..., enable_tracing: bool = False)`、`run_research(..., enable_tracing: bool = False)`、CLI `--trace`。

- [ ] **Step 1: 写失败测试（CLI --trace 解析）**

在 `tests/test_cli.py` 末尾追加：

```python
def test_cli_trace_flag_parses_and_runs(company_database_path, tmp_path, capsys):
    # --trace 不应改变输出内容；仅验证带该 flag 时 CLI 正常跑完（追踪未起 Phoenix 时应无害）
    main(
        [
            "核验示例科技股份有限公司",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
            "--trace",
        ]
    )
    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "insufficient_evidence" in out
```

> 说明：`--trace` 会调 `configure_tracing()`（默认 OTLP→localhost）。Phoenix 未起时 OTLP 导出会在后台静默失败（SimpleSpanProcessor 吞异常），不影响 CLI 产出报告，故断言仍是报告内容。

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py::test_cli_trace_flag_parses_and_runs -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: FAIL（`--trace` 未定义 → argparse `unrecognized arguments`）

- [ ] **Step 3: `graph.py` — `build_graph` 加 `enable_tracing` + 节点包装**

在 `src/deepresearch_agent/agents/graph.py` 顶部导入区加：

```python
from deepresearch_agent.observability import configure_tracing, get_tracer, traced_node
```

把 `build_graph` 签名与四个 `add_node` 替换为：

```python
def build_graph(
    domain_pack: DomainPack,
    repository: CompanyRepository,
    scope_retriever=None,
    graph_searcher=None,
    llm=None,
    scope_enabled: bool = False,
    graph_enabled: bool = False,
    enable_tracing: bool = False,
):
    tools = build_procurement_tool_registry(repository)
    graph = StateGraph(ResearchState)

    planner_fn = lambda state: planner_node(state, domain_pack, repository, llm)
    researcher_fn = lambda state: researcher_node(
        state, tools, domain_pack, scope_retriever, graph_searcher, scope_enabled, graph_enabled
    )
    critic_fn = critique_node
    writer_fn = lambda state: writer_node(state, domain_pack)

    if enable_tracing:
        planner_fn = traced_node("planner", planner_fn, _planner_attrs)
        researcher_fn = traced_node("researcher", researcher_fn, _researcher_attrs)
        critic_fn = traced_node("critic", critic_fn, _critic_attrs)
        writer_fn = traced_node("writer", writer_fn, _writer_attrs)

    graph.add_node("planner", planner_fn)
    graph.add_node("researcher", researcher_fn)
    graph.add_node("critic", critic_fn)
    graph.add_node("writer", writer_fn)
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
```

- [ ] **Step 4: `graph.py` — 加 attr_fn 辅助**

在 `build_graph` 之前（`_should_continue` 之后）新增四个属性抽取函数：

```python
def _planner_attrs(state) -> dict:
    resolution = state.supplier_resolution
    attrs: dict = {"resolution_status": resolution.status if resolution is not None else "not_found"}
    if state.complexity is not None:
        attrs["complexity_level"] = state.complexity.level
        attrs["complexity_method"] = state.complexity.method
    return attrs


def _researcher_attrs(state) -> dict:
    return {
        "retrieval_mode": state.retrieval_mode or "",
        "retrieval_available": state.retrieval_available,
        "scope_candidates": len(state.scope_candidates),
        "graph_candidates": len(state.graph_candidates),
        "shared_controllers": len(state.shared_controllers),
    }


def _critic_attrs(state) -> dict:
    return {"missing_dimensions": len(state.missing_dimensions), "iteration": state.iteration}


def _writer_attrs(state) -> dict:
    if state.report is not None:
        report_type = "unresolved" if state.report.supplier_name == "Unknown supplier" else "named"
    elif state.scope_report is not None:
        report_type = "scope"
    elif state.graph_report is not None:
        report_type = "graph"
    else:
        report_type = "none"
    return {"report_type": report_type, "degradations": len(state.degradations)}
```

- [ ] **Step 5: `graph.py` — `run_research` 加 `enable_tracing` + root span**

把 `run_research` 替换为（新增 `enable_tracing` 形参、配置追踪、root span 包 invoke）：

```python
def run_research(
    question: str,
    domain: str = "procurement",
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    enable_scope: bool = False,
    enable_graph: bool = False,
    enable_tracing: bool = False,
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
    if enable_tracing:
        configure_tracing()
    app = build_graph(
        domain_pack,
        repository,
        scope_retriever=scope_retriever,
        graph_searcher=graph_searcher,
        llm=_build_llm(),
        scope_enabled=enable_scope,
        graph_enabled=enable_graph,
        enable_tracing=enable_tracing,
    )
    tracer = get_tracer() if enable_tracing else None
    if tracer is not None:
        with tracer.start_as_current_span("research") as span:
            span.set_attribute("question", question)
            span.set_attribute("domain", domain)
            return run_compiled(app, question, domain)
    return run_compiled(app, question, domain)
```

- [ ] **Step 6: `cli.py` — 加 `--trace`**

在 `src/deepresearch_agent/cli.py` 的 `main` 里，`--graph` 的 `add_argument` 之后加：

```python
    parser.add_argument(
        "--trace",
        action="store_true",
        help="启用本地 Phoenix 链路追踪（需本地 pip install arize-phoenix 并 phoenix serve）。",
    )
```

把 `run_research(...)` 调用加 `enable_tracing=args.trace`：

```python
    state = run_research(
        args.question,
        database_path=args.database,
        index_path=args.index,
        enable_scope=True,
        enable_graph=args.graph,
        enable_tracing=args.trace,
    )
```

- [ ] **Step 7: 跑 CLI 测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_cli.py -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: PASS（新 1 项 + 既有全绿；`--trace` 跑通、报告内容不变）

- [ ] **Step 8: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: 全绿（`enable_tracing=False` 默认路径逐字不变；API 不接追踪）

- [ ] **Step 9: 提交**

```bash
git add src/deepresearch_agent/agents/graph.py src/deepresearch_agent/cli.py tests/test_cli.py
git commit -m "功能：Trace-2 build_graph/run_research 接 enable_tracing 包四节点+root span，CLI --trace"
```

---

### Task 3：端到端 span 树验证

**Files:**
- Test: `tests/test_observability.py`（追加）

**Interfaces:**
- Consumes: `run_research(enable_tracing=True)`（Task 2）、`configure_tracing`/`reset_tracing`（Task 1）、`InMemorySpanExporter`。

- [ ] **Step 1: 写端到端测试**

在 `tests/test_observability.py` 末尾追加：

```python
def test_run_research_emits_pipeline_span_tree(company_database_path):
    from deepresearch_agent.agents.graph import run_research

    mem = InMemorySpanExporter()
    configure_tracing(exporter=mem)  # 先注入 → run_research 内 configure_tracing() 幂等不覆盖

    state = run_research(
        "核验示例科技股份有限公司",
        database_path=company_database_path,
        enable_tracing=True,
    )
    assert state.report is not None  # 行为不变

    names = {s.name for s in mem.get_finished_spans()}
    assert {"research", "planner", "researcher", "critic", "writer"} <= names

    by_name = {s.name: s for s in mem.get_finished_spans()}
    assert by_name["planner"].attributes["resolution_status"] == "resolved"
    assert by_name["writer"].attributes["report_type"] == "named"


def test_run_research_no_spans_when_tracing_disabled(company_database_path):
    from deepresearch_agent.agents.graph import run_research

    mem = InMemorySpanExporter()
    configure_tracing(exporter=mem)

    run_research(
        "核验示例科技股份有限公司",
        database_path=company_database_path,
        enable_tracing=False,
    )
    assert mem.get_finished_spans() == ()  # 未启用 → 无 span
```

（`_clean_tracing` autouse fixture 已在文件顶部定义，每例前后 `reset_tracing`。）

- [ ] **Step 2: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_observability.py -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: PASS（Task 1/2 已实现追踪，端到端 span 树 + 属性正确；disabled 无 span）。

> 若 `research` root span 缺失：确认 `run_research` 在 `enable_tracing` 且 `get_tracer()` 非 None 时用 `start_as_current_span("research")` 包了 `run_compiled`。若节点 span 缺失：确认 `build_graph(enable_tracing=True)` 走了 `traced_node` 包装分支。

- [ ] **Step 3: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-trace`
Expected: 全绿。

- [ ] **Step 4: 提交**

```bash
git add tests/test_observability.py
git commit -m "功能：Trace-3 端到端验证 run_research 发出 research/planner/researcher/critic/writer span 树"
```

---

## 收尾

三任务完成、全量绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。收尾前文档同步：`docs/architecture.md`（追踪层与 `.[trace]`）、`project-memory.md`/`CLAUDE.md`（Phoenix 本地追踪：默认关、仅本地、手动 span 在图层）、`docs/eval-plan.md`（Phoenix 步已落地为本地追踪、非 LLM-eval）；`.env.example` 可选加 Phoenix endpoint 注释；README/CLAUDE 给 `pip install arize-phoenix` + `phoenix serve` 一次性命令。

## Self-Review

- **Spec 覆盖**：`observability.py`（configure/get_tracer/reset/traced_node）=Task 1；`.[trace]` extra=Task 1；图层包四节点 + attr_fn=Task 2；`run_research` root span + `enable_tracing`=Task 2；CLI `--trace`=Task 2；端到端 span 树 + disabled 无 span=Task 3；红线（默认关、仅本地、DeepSeek 不记企业数据、API 不接、无 LLM-eval）=Global Constraints + attr_fn 只取标量/计数。
- **占位符**：无 TBD/TODO；每步含完整代码。
- **类型一致**：`traced_node(name, node_fn, attr_fn)`（Task 1）被 Task 2 以 `traced_node("planner", planner_fn, _planner_attrs)` 调用；`configure_tracing`/`get_tracer`（Task 1）被 `run_research`（Task 2）消费；`enable_tracing` 形参在 `build_graph`/`run_research`/CLI 一致；attr_fn 返回值经 `traced_node` 的 `span.set_attribute` 落属性，测试按同名 key（`resolution_status`/`report_type`）断言。
