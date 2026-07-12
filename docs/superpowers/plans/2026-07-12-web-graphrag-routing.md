# 网页端接入 scope/GraphRAG 自动路由（流式）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让网页流式端点 `/session/turn/stream` 复用 CLI 的 scope+graph 检索，由 LLM/启发式复杂度判断自动走 GraphRAG，三种报告均转文本流，graph 命中围标线索时发 `graph_viz` 事件在一侧画「候选⇔控制人」SVG 图。

**Architecture:** 后端先让 `_report_message_chunks`/端点能处理三种报告（不崩），再在 `create_app` 注入检索器（照搬 `run_research`），再加 `graph_viz` SSE 事件；前端只新增 `graph_viz` 事件处理 + 内联 SVG。流式纯文本对三报告天然通用，前端主体零改动。

**Tech Stack:** FastAPI（SSE `StreamingResponse`）、pydantic、原生 JS/SVG、pytest（TestClient `.stream()`）。环境 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **网页走流式 SSE**（`/session/turn/stream`）。接入点是 SSE 事件 + `_report_message_chunks`，**不是** JSON 响应模型。
- **不改后端报告契约**：`graph_viz` 数据由 `GraphSearchReport.shared_controllers` 现有字段构造。
- **核心数据原则**：三种报告均 writer 生成、经文本流逐字呈现；围标线索标「线索级·须人工复核」；LLM 只发查询文本、不发数据。
- **降级照搬图层**：Neo4j 没起→回退 scope；缺 `.[rag]`/索引→命名核验；全缺=等于没开。端点不额外写降级。
- `create_app` 缓存图（`compiled_graphs`），启动建一次；`_build_graph_searcher` 已 try/except→None，Neo4j 短超时快速降级。
- 无 CDN/webfont：`graph_viz` 用内联 SVG 手绘。
- 测试隔离缓存：`.\.conda-env\python.exe -m pytest <路径> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`。
- 报告字段（`state.py`）：`ScopeSearchReport{query,recommendation,summary,candidates[{legal_name,top_score,unified_social_credit_code}],open_questions}`；`GraphSearchReport{query,recommendation,summary,candidates[{legal_name,top_score,ultimate_controllers}],shared_controllers[{controller_name,controlled_companies,via_person,note,concentrated_industries}],open_questions}`。

---

### Task 1: 后端报告分派（`_resolve_report` + `_report_message_chunks` 三报告）

让端点具备处理三种报告的能力（此时尚未注入 graph，端点行为不变；纯后端函数改造，可单元测）。

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_report_chunks.py`

**Interfaces:**
- Produces: `_resolve_report(state) -> tuple[str, dict]`（按 `retrieval_mode` 取报告与类型）；`_report_message_chunks(report: dict, report_type: str)`（三报告 → 文本片段迭代器）。
- Consumes: `ResearchState`（有 `retrieval_mode`/`report`/`scope_report`/`graph_report`）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_report_chunks.py`：

```python
from deepresearch_agent.api import _report_message_chunks, _resolve_report
from deepresearch_agent.state import (
    GraphSearchCandidate, GraphSearchReport, ResearchState,
    ScopeCandidate, ScopeSearchReport, SharedControllerFinding, SupplierReport,
)


def _named_state():
    s = ResearchState(question="核验甲", domain="procurement")
    s.retrieval_mode = "named"
    s.supplier_name = "甲公司"
    s.report = SupplierReport(
        supplier_name="甲公司", recommendation="insufficient_evidence",
        summary="已核验工商。", risks=[], evidence_table=[], open_questions=[],
    )
    return s


def _scope_state():
    s = ResearchState(question="哪些能做注塑", domain="procurement")
    s.retrieval_mode = "scope"
    s.scope_report = ScopeSearchReport(
        query="哪些能做注塑", summary="检索到 1 家候选。",
        candidates=[ScopeCandidate(unified_social_credit_code="C1", legal_name="乙公司", matched_clauses=[], top_score=0.8)],
        open_questions=[],
    )
    return s


def _graph_state():
    s = ResearchState(question="找股东有关联的供应商", domain="procurement")
    s.retrieval_mode = "graph"
    s.graph_report = GraphSearchReport(
        query="找股东有关联的供应商", summary="检索到 2 家候选。",
        candidates=[GraphSearchCandidate(unified_social_credit_code="C1", legal_name="丙公司", top_score=0.8, ultimate_controllers=["张三"])],
        shared_controllers=[SharedControllerFinding(controller_name="张三", controlled_companies=["丙公司", "丁公司"], via_person=False, note="经企业股权链推断", concentrated_industries=["木材加工"])],
        open_questions=[],
    )
    return s


def test_resolve_report_picks_by_mode():
    assert _resolve_report(_named_state())[0] == "named"
    assert _resolve_report(_scope_state())[0] == "scope"
    assert _resolve_report(_graph_state())[0] == "graph"
    assert _resolve_report(_scope_state())[1]["query"] == "哪些能做注塑"


def test_chunks_named_has_supplier_and_summary():
    _, report = _resolve_report(_named_state())
    text = "".join(_report_message_chunks(report, "named"))
    assert "甲公司" in text and "已核验工商" in text


def test_chunks_scope_lists_candidates():
    _, report = _resolve_report(_scope_state())
    text = "".join(_report_message_chunks(report, "scope"))
    assert "乙公司" in text and "候选" in text


def test_chunks_graph_lists_candidates_and_collusion():
    _, report = _resolve_report(_graph_state())
    text = "".join(_report_message_chunks(report, "graph"))
    assert "丙公司" in text
    assert "张三" in text
    assert "须人工复核" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_report_chunks.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: FAIL（`ImportError: cannot import name '_resolve_report'`）

- [ ] **Step 3: 实现 `_resolve_report` 与三报告 `_report_message_chunks`**

在 `api.py` 替换现有 `_report_message_chunks`（api.py:185-198）并新增 `_resolve_report`：

```python
def _resolve_report(state) -> tuple[str, dict]:
    mode = state.retrieval_mode or "named"
    report = {"scope": state.scope_report, "graph": state.graph_report}.get(mode) or state.report
    if report is None:
        raise RuntimeError("turn completed without any report")
    return mode, report.model_dump(mode="json")


_RECOMMENDATION_TEXT = {
    "insufficient_evidence": "证据不足，不能据此作出采购批准或风险结论。",
    "conditional": "存在前提条件，须人工复核。",
    "approve": "通过。",
    "reject": "不通过。",
}


def _report_message_chunks(report: dict, report_type: str):
    rec = _RECOMMENDATION_TEXT.get(report["recommendation"], report["recommendation"])
    if report_type in ("named", "unresolved"):
        sections = [f"{report['supplier_name']}\n\n结论：{rec}", report.get("summary", "")]
    elif report_type == "scope":
        head = f"经营范围语义检索：{report['query']}\n\n结论：{rec}"
        lines = [f"· {c['legal_name']}（{c['top_score']:.2f}）" for c in report.get("candidates", [])]
        sections = [head, report.get("summary", ""), "候选企业：\n" + "\n".join(lines) if lines else ""]
    else:  # graph
        head = f"股权关系检索：{report['query']}\n\n结论：{rec}"
        cand = [f"· {c['legal_name']}｜最终控制人：{'、'.join(c.get('ultimate_controllers') or []) or '—'}"
                for c in report.get("candidates", [])]
        clue = [f"· {s['controller_name']} → {'、'.join(s.get('controlled_companies') or [])}（{s['note']}）"
                for s in report.get("shared_controllers", [])]
        sections = [
            head, report.get("summary", ""),
            "候选企业：\n" + "\n".join(cand) if cand else "",
            "围标线索（线索级·须人工复核）：\n" + "\n".join(clue) if clue else "",
        ]
    for section in sections:
        if section:
            yield from _text_chunks(f"\n\n{section}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_report_chunks.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: PASS（4 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/api.py tests/test_report_chunks.py
git commit -m "功能：api 报告分派 _resolve_report + _report_message_chunks 支持 scope/graph 三报告文本流"
```

---

### Task 2: 两端点用 `_resolve_report`（修 report-None 崩溃）+ 注入检索器

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_api_stream_retrieval.py`；更新 `tests/test_api_session.py`

**Interfaces:**
- Consumes: Task 1 的 `_resolve_report`/`_report_message_chunks`；`graph_module._build_scope_retriever/_build_graph_searcher/_build_llm/DEFAULT_INDEX_PATH`。
- Produces: `create_app(..., index_path=, enable_scope=True, enable_graph=True, scope_retriever=None, graph_searcher=None)`；JSON `SessionTurnResponse{session_id, report_type: str, report: dict}`；流式 `report_start{report_type,title,recommendation}`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api_stream_retrieval.py`：

```python
from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore


class _Ctrl:
    def __init__(self, name): self.display_name = name; self.via_person = False


class _Seed:
    def __init__(self, code, name): self.code = code; self.name = name; self.score = 0.8; self.controllers = [_Ctrl("张三")]


class _Shared:
    def __init__(self): self.name = "张三"; self.concentrated_industries = ["木材加工"]; self.via_person = False; self.controlled_seeds = ["C1", "C2"]


class _Ctx:
    seeds = [_Seed("C1", "丙公司"), _Seed("C2", "丁公司")]
    shared_controllers = [_Shared()]


def _client(db, tmp, **kw):
    app = create_app(
        database_path=db, memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp), **kw,
    )
    return TestClient(app)


def test_stream_graph_query_emits_text_without_crash(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, graph_searcher=lambda q: _Ctx())
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "找股东有关联的供应商", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert r.status_code == 200
    assert "event: report_start" in body
    assert "event: complete" in body
    assert "丙公司" in body  # graph 候选进文本流


def test_stream_named_query_unchanged(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: report_start" in body and "event: complete" in body


def test_json_turn_returns_report_type(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path)
    r = client.post("/session/turn", json={"question": "示例科技股份有限公司", "user_id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["report_type"] == "named"
    assert body["report"]["supplier_name"] == "示例科技股份有限公司"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: FAIL（`create_app` 不接受 `graph_searcher`；或走 graph 时 `report is None` 崩溃）

- [ ] **Step 3: 改 `create_app` 注入 + 端点用 `_resolve_report`**

改 `create_app` 签名与 `graph_for`（api.py:69-84）：

```python
def create_app(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    memory: MemoryService | None = None,
    session_store: JsonSessionStore | None = None,
    index_path: str | Path = graph_module.DEFAULT_INDEX_PATH,
    enable_scope: bool = True,
    enable_graph: bool = True,
    scope_retriever=None,
    graph_searcher=None,
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)

    if scope_retriever is None and (enable_scope or enable_graph):
        scope_retriever = graph_module._build_scope_retriever(database_path, index_path)
    if graph_searcher is None and enable_graph:
        graph_searcher = graph_module._build_graph_searcher(database_path, scope_retriever)

    def graph_for(domain: str) -> object:
        if domain not in compiled_graphs:
            domain_pack = load_domain_pack(Path("domains") / domain / "domain.yaml")
            compiled_graphs[domain] = graph_module.build_graph(
                domain_pack, repository,
                scope_retriever=scope_retriever, graph_searcher=graph_searcher,
                llm=graph_module._build_llm(),
                scope_enabled=enable_scope, graph_enabled=enable_graph,
            )
        return compiled_graphs[domain]
```

改 `SessionTurnResponse`（api.py:52-54）：

```python
class SessionTurnResponse(BaseModel):
    session_id: str
    report_type: str
    report: dict
```

改 JSON `session_turn` 尾部（api.py:115-118）：

```python
        store.save(session)
        report_type, report = _resolve_report(state)
        return SessionTurnResponse(session_id=session.session_id, report_type=report_type, report=report)
```

改流式 complete 分支（api.py:152-162）：

```python
                store.save(session)
                report_type, report = _resolve_report(state)
                yield _sse("report_start", {
                    "report_type": report_type,
                    "title": report.get("supplier_name") or report.get("query", ""),
                    "recommendation": report["recommendation"],
                })
                for text in _report_message_chunks(report, report_type):
                    yield _sse("message_delta", {"text": text})
                yield _sse("complete", {"session_id": session.session_id})
```

（删掉旧 complete 分支里的 `if state.report is None: raise` 与旧的 report_start/chunks 调用。）

- [ ] **Step 4: 更新现有 `test_api_session.py`**

现有断言 `body["report"]["supplier_name"]` 仍可取；给首轮测试补 `report_type`。在 `test_first_turn_returns_session_id`（test_api_session.py:24-30）的 `assert body["report"]["supplier_name"] == ENTITY` 前加：

```python
    assert body["report_type"] == "named"
```

（其余用例读 `["report"]["supplier_name"]` 无需改。）

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py tests/test_api_session.py tests/test_api_stream.py tests/test_api_web.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: PASS（新 3 + session 若干 + stream 1 + web 4，全绿）

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/api.py tests/test_api_stream_retrieval.py tests/test_api_session.py
git commit -m "功能：网页端注入 scope+graph 检索(照搬 run_research)，两端点按 retrieval_mode 取报告不崩"
```

---

### Task 3: `graph_viz` SSE 事件（后端构造围标子图）

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_graph_viz.py`；扩 `tests/test_api_stream_retrieval.py`

**Interfaces:**
- Produces: `_graph_viz_payload(graph_report: dict) -> dict | None`（`shared_controllers` → `{controllers:[{name,collusion}], edges:[{controller,company}]}`；空则 None）；流式在 graph 且非空时发 `event: graph_viz`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_graph_viz.py`：

```python
from deepresearch_agent.api import _graph_viz_payload


def test_payload_from_shared_controllers():
    report = {"shared_controllers": [
        {"controller_name": "张三", "controlled_companies": ["丙公司", "丁公司"],
         "via_person": False, "note": "…", "concentrated_industries": ["木材加工"]},
    ]}
    payload = _graph_viz_payload(report)
    assert payload["controllers"] == [{"name": "张三", "collusion": True}]
    assert {"controller": "张三", "company": "丙公司"} in payload["edges"]
    assert len(payload["edges"]) == 2


def test_payload_none_when_no_shared():
    assert _graph_viz_payload({"shared_controllers": []}) is None
```

在 `tests/test_api_stream_retrieval.py` 追加：

```python
def test_stream_graph_emits_graph_viz(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, graph_searcher=lambda q: _Ctx())
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "找股东有关联的供应商", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: graph_viz" in body
    assert "张三" in body
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_viz.py "tests/test_api_stream_retrieval.py::test_stream_graph_emits_graph_viz" -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: FAIL（`ImportError: _graph_viz_payload`）

- [ ] **Step 3: 实现 + 流式发事件**

在 `api.py` 加：

```python
def _graph_viz_payload(graph_report: dict) -> dict | None:
    shared = graph_report.get("shared_controllers") or []
    if not shared:
        return None
    controllers, edges = [], []
    for item in shared:
        controllers.append({"name": item["controller_name"], "collusion": bool(item.get("concentrated_industries"))})
        for company in item.get("controlled_companies") or []:
            edges.append({"controller": item["controller_name"], "company": company})
    return {"controllers": controllers, "edges": edges}
```

在流式 complete 分支的 `for text in _report_message_chunks(...)` **之后**、`yield _sse("complete", ...)` **之前**加：

```python
                if report_type == "graph":
                    viz = _graph_viz_payload(report)
                    if viz is not None:
                        yield _sse("graph_viz", viz)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_viz.py tests/test_api_stream_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph`
Expected: PASS（2 + 4）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/api.py tests/test_graph_viz.py tests/test_api_stream_retrieval.py
git commit -m "功能：graph 命中围标线索发 graph_viz SSE 事件(共享控制人→候选子图)"
```

---

### Task 4: 前端 `graph_viz` 事件 + 侧边 SVG

**Files:**
- Modify: `src/deepresearch_agent/web/app.js`
- Modify: `src/deepresearch_agent/web/style.css`
- Test: 手动端到端 + 全套 `pytest` 保持绿。

**Interfaces:**
- Consumes: `graph_viz` 事件 `{controllers:[{name,collusion}], edges:[{controller,company}]}`。
- Produces: `renderGraphViz(data, anchorNode)`（内联 SVG 挂在报告气泡一侧）。

- [ ] **Step 1: 在 SSE 事件循环处理 `graph_viz`**

`app.js` 的 `submit` 事件回调（app.js:279-293）里，`else if (event === "report_start")` 分支后加：

```javascript
        } else if (event === "graph_viz") {
          if (streamed) renderGraphViz(data, streamed.node);
```

（插在 `else if (streamed && event !== "complete")` 之前，避免被通用分支吞掉。）

- [ ] **Step 2: 实现 `renderGraphViz`（纯函数，内联 SVG）**

在 `app.js` 的 `createStreamingMessage` 之后加：

```javascript
  function renderGraphViz(data, anchor) {
    const controllers = data.controllers || [];
    const edges = data.edges || [];
    if (!controllers.length) return;
    const companies = [...new Set(edges.map((e) => e.company))];
    const W = 300, topY = 34, botY = 150, pad = 24;
    const xs = (n, i) => n <= 1 ? W / 2 : pad + (W - 2 * pad) * i / (n - 1);
    const cx = {}, comx = {};
    controllers.forEach((c, i) => (cx[c.name] = xs(controllers.length, i)));
    companies.forEach((c, i) => (comx[c] = xs(companies.length, i)));

    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "graph-viz");
    svg.setAttribute("viewBox", `0 0 ${W} 180`);
    const line = (x1, y1, x2, y2, strong) => {
      const l = document.createElementNS(NS, "line");
      l.setAttribute("x1", x1); l.setAttribute("y1", y1);
      l.setAttribute("x2", x2); l.setAttribute("y2", y2);
      l.setAttribute("class", strong ? "gv-edge strong" : "gv-edge");
      svg.appendChild(l);
    };
    const collusion = {};
    controllers.forEach((c) => (collusion[c.name] = c.collusion));
    edges.forEach((e) => line(cx[e.controller], topY, comx[e.company], botY, collusion[e.controller]));
    const node = (x, y, label, kind) => {
      const g = document.createElementNS(NS, "g");
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 7);
      c.setAttribute("class", "gv-node " + kind);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", x); t.setAttribute("y", kind === "ctrl" ? y - 12 : y + 20);
      t.setAttribute("class", "gv-label"); t.textContent = label;
      g.appendChild(c); g.appendChild(t); svg.appendChild(g);
    };
    controllers.forEach((c) => node(cx[c.name], topY, c.name, c.collusion ? "ctrl collusion" : "ctrl"));
    companies.forEach((c) => node(comx[c], botY, c, "company"));

    const box = el("div", "graph-viz-box");
    box.appendChild(el("div", "graph-viz-cap", "股权关系（共享控制人→候选 · 线索级，须人工复核）"));
    box.appendChild(svg);
    anchor.parentNode.appendChild(box);
  }
```

- [ ] **Step 3: 加 `style.css` 样式**

在 `style.css` 末尾（`@media` 之前）加：

```css
/* graph_viz 侧边图 */
.graph-viz-box { margin-top: 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); padding: 10px 12px; max-width: min(100%, 360px); }
.graph-viz-cap { font-family: var(--mono); font-size: 10.5px; letter-spacing: .04em; color: var(--muted); margin-bottom: 6px; }
.graph-viz { width: 100%; height: auto; }
.gv-edge { stroke: var(--line-strong); stroke-width: 1.2; }
.gv-edge.strong { stroke: var(--bad); stroke-width: 2.2; }
.gv-node { stroke: var(--surface); stroke-width: 1.5; }
.gv-node.ctrl { fill: var(--accent); }
.gv-node.ctrl.collusion { fill: var(--bad); }
.gv-node.company { fill: var(--muted); }
.gv-label { font-family: var(--sans); font-size: 9px; fill: var(--fg-soft); text-anchor: middle; }
```

- [ ] **Step 4: 手动端到端核对**

Run: `docker compose up -d`（确保 Neo4j 在跑）+ `$env:NEO4J_URI=...` 等 + `.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload`

浏览器 `http://127.0.0.1:8000/`：
1. 命名核验（如「核验亚联机械股份有限公司」）→ 流式文本、体验不变。
2. 能力查询（「哪些企业能做木材加工机械」）→ 流式出候选文本、无侧边图。
3. 关系查询（「找做木材加工机械且股东有关联的供应商」）→ 流式出候选+控制人文本；**若命中共享控制人，报告气泡下方出现 SVG 关系图**（共享控制人红★、边加粗）。

- [ ] **Step 5: 全套回归 + 提交**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-webgraph-full`
Expected: 全绿（前端无 py 测试，后端全绿）

```powershell
git add src/deepresearch_agent/web/app.js src/deepresearch_agent/web/style.css
git commit -m "功能：前端 graph_viz 事件 + 内联 SVG 侧边围标关系图"
```

---

### Task 5: 文档同步

**Files:**
- Modify: `CLAUDE.md`、`docs/architecture.md`、`docs/project-memory.md`

- [ ] **Step 1: 更新三处文档**

- `CLAUDE.md` 运行 Agent 的 Web 界面注释：网页流式端点现按 LLM/启发式复杂度自动路由 scope/graph，graph 命中围标线索出侧边关系图。
- `docs/architecture.md` 接口小节：`/session/turn/stream` 注入 scope+graph，三报告转文本流，`graph_viz` 事件画侧边围标子图；`create_app` 新增 `index_path/enable_scope/enable_graph/scope_retriever/graph_searcher` 参数。
- `docs/project-memory.md` 追加条目：网页接 GraphRAG 自动路由（流式对齐）。

- [ ] **Step 2: 提交**

```powershell
git add CLAUDE.md docs/architecture.md docs/project-memory.md
git commit -m "文档：同步网页接 scope/GraphRAG 自动路由(流式+graph_viz)到架构/记忆/CLAUDE"
```

---

## 收尾

五个 Task 后用 **superpowers:finishing-a-development-branch**：全套 `pytest`（应全绿）→ present 合并选项。

**真链路手验（收尾后，用户本地）**：`docker compose up -d` + `uvicorn` → 网页走命名/能力/关系三类查询，验证自动路由与 graph_viz 侧边图。

## Self-Review

- **Spec 覆盖**：后端注入（Task2）、三报告文本流（Task1）、修 None 崩溃（Task2）、`graph_viz` 事件（Task3）、前端 SVG（Task4）、降级（照搬，Task2 fake None 测）、LLM 复杂度（照搬 `_build_llm`，Task2）、文档（Task5）均有落点。穿透图/`/research`/鉴权/结构化卡片按 spec 不做。
- **占位符**：每步含完整代码与命令，无 TBD。
- **类型一致**：`_resolve_report(state)->tuple[str,dict]`、`_report_message_chunks(report,report_type)`、`_graph_viz_payload(report)->dict|None`、`create_app(...,index_path,enable_scope,enable_graph,scope_retriever,graph_searcher)`、`SessionTurnResponse{session_id,report_type,report}`、`renderGraphViz(data,anchor)`、`graph_viz{controllers:[{name,collusion}],edges:[{controller,company}]}` 跨 Task 与 `api.py`/`state.py`/`graph.py`（`_build_scope_retriever`/`_build_graph_searcher`/`_build_llm`/`iter_execute_turn`）一致。fake graph_searcher 契约 `searcher(q)->ctx{seeds[{code,name,score,controllers[{display_name,via_person}]}],shared_controllers[{name,concentrated_industries,via_person,controlled_seeds}]}` 与 `_build_graph_findings`（nodes.py:248）一致。
