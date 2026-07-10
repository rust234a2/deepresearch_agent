# 模块 C4：降级链 + 降级留痕 设计

日期：2026-07-10

本文件是路线图阶段 C 最后一块 **C4** 的设计 spec。路线图原话：**"高级策略失败 → 降级传统检索；传统也失败 → 返回系统异常；重试（非流式）。"** C4 落地"降级链"并给降级留痕；**重试判为 YAGNI 不做**。完成 C4，GraphRAG + 查询编排路线图收尾。

## 背景与现状

C2 后各处已有零散兜底：`classify_complexity` LLM 异常回退启发式；`_decide_retrieval_mode` 想用 graph 但 **searcher 缺失(None)** 且 scope 可用时退 scope；`_retrieve_scope`/`_retrieve_graph` 检索器 None 或运行时抛异常 → `retrieval_available=False` → writer 出"不可用"报告。

**关键缺口（一处不对称）**：graph 的 searcher **决策时缺失** 会退到 scope；但 graph **运行时真的抛异常** 只置 `retrieval_available=False` 出"图不可用"报告，**不尝试 scope**。路线图的"高级失败→降级传统"只做了一半。

## 红线（不变）

- 报告对已解析企业固定 `insufficient_evidence`；绝不写"未发现风险"或采购结论。
- **绝不隐藏问题**：运行时失败必须留痕，不能被"不可用（请装 .[rag]）"这类文案盖过。
- 不引入外部调用、重试退避、新依赖。
- 无 SQLite schema 变更。

## 设计

### 一、补齐降级链（`researcher_node` 的 `graph` 分支 + `_retrieve_graph`）

区分**运行时失败**（检索器存在但抛异常，值得降级/留痕）与**配置性缺失**（检索器为 None，属正常配置，不留痕、行为不变）。

`_retrieve_graph` 改为返回运行时错误信息（成功/缺失返回 `None`）：

```python
def _retrieve_graph(state, searcher) -> str | None:
    if searcher is None:
        state.retrieval_available = False
        return None                      # 配置性缺失：不算失败
    try:
        context = searcher(state.question)
    except Exception as exc:
        state.retrieval_available = False
        return str(exc)                  # 运行时失败：返回错误信息
    candidates, shared = _build_graph_findings(context)
    state.graph_candidates = candidates
    state.shared_controllers = shared
    return None
```

`researcher_node` 的 `graph` 分支据返回值决定降级：

```python
    elif mode == "graph":
        graph_error = _retrieve_graph(state, graph_searcher)
        if graph_error:
            if scope_retriever is not None:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，已降级为经营范围检索。"
                )
                state.retrieval_mode = "scope"
                state.retrieval_available = True   # 关键：重置，否则 scope 成功也被误判不可用
                _retrieve_scope(state, scope_retriever)
            else:
                state.degradations.append(
                    f"图检索运行时失败：{graph_error}，无可用降级路径。"
                )
```

降级链完整行为：

```
graph 模式：
  ├─ 成功                       → graph_candidates（不变）
  ├─ 运行时抛异常 + 有 scope     → 记降级，改走 scope（retrieval_mode="scope"）
  ├─ 运行时抛异常 + 无 scope     → 记"无可用降级路径"，出 graph 不可用报告
  └─ searcher 缺失(None)        → 不可用（不记、行为不变）
scope 模式：
  ├─ 成功                       → scope_candidates（不变）
  ├─ 运行时抛异常               → 记失败，出 scope 不可用报告（"传统也失败"＝终点）
  └─ retriever 缺失(None)       → 不可用（不记、行为不变）
```

> 不变量：`_decide_retrieval_mode` 只在 `graph_searcher is not None`、或（`graph_searcher`、`scope_retriever` 均 None 且 `scope_enabled` False）时返回 `"graph"`。因此 `graph` 分支里"运行时失败 + 有 scope 降级"与"无 scope"两条都可达（后者主要出现在单测直接注入会抛的 searcher 而不给 scope）。

### 二、`scope` 运行时失败留痕（`_retrieve_scope`）

`_retrieve_scope` 在 `except` 分支自记一条降级（`retriever is None` 的缺失路径**不记**）：

```python
def _retrieve_scope(state, retriever) -> None:
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

> 若 graph 先失败降级到 scope、scope 又失败，会得到两条降级（图失败 + scope 失败），完整呈现降级链，符合预期。

### 三、新增 state 字段

```python
degradations: list[str] = Field(default_factory=list)
```

只在**运行时抛异常**时追加。配置性回退（searcher/retriever 缺失、LLM 回退启发式）**不记**——保持信号纯净，避免"正常配置选择"稀释真·失败告警。LLM 回退已由 `complexity.method` 体现，不重复记。

### 四、writer 把降级并入 `open_questions`

`_write_scope_report` / `_write_graph_report` 的**两个分支（可用 + 不可用）**都在 `open_questions` **最前面**插入 `state.degradations`：

- `_write_scope_report` 不可用分支：`open_questions=list(state.degradations) + ["安装 .[rag] …"]`
- `_write_scope_report` 可用分支：`open_questions=list(state.degradations) + list(_SCOPE_OPEN_QUESTIONS)`
- `_write_graph_report` 不可用分支：`open_questions=list(state.degradations) + ["安装 .[rag] …"]`
- `_write_graph_report` 可用分支：`open_questions=list(state.degradations) + list(_GRAPH_OPEN_QUESTIONS)`

named / unresolved 路径不会降级，其 writer 不改。

### 五、不改动

`graph.py` / `cli.py` / `api.py` 不动（`researcher_node` 签名不变，降级是内部逻辑）。不做重试、配置性回退留痕、结构化 `DegradationEvent` 模型、不改写"不可用"文案。

## 测试（`tests/test_nodes.py`，Windows：`--basetemp=.conda-cache/pytest-c4`）

- **state 字段**：`ResearchState(...).degradations == []`。
- **`_retrieve_graph` 返回值**：注入会抛的 searcher → 返回异常字符串且 `retrieval_available=False`；注入正常 searcher → 返回 `None` 且填 `graph_candidates`；`None` searcher → 返回 `None`。
- **graph 运行时失败 + 有 scope 降级**：researcher（`graph_searcher` 抛异常、`scope_retriever` 正常、`graph_enabled`、query=medium）→ `retrieval_mode=="scope"`、`scope_candidates` 非空、`degradations` 有 1 条含"已降级为经营范围检索"。
- **graph 运行时失败 + 无 scope**：researcher（`graph_searcher` 抛异常、`scope_retriever=None`）→ `retrieval_mode=="graph"`、`retrieval_available False`、`degradations` 有 1 条含"无可用降级路径"。
- **scope 运行时失败留痕**：researcher（`scope_retriever` 抛异常、`scope_enabled`、query=simple）→ `retrieval_available False`、`degradations` 有 1 条含"经营范围检索运行时失败"。
- **配置性缺失不记**：`scope_retriever=None` + `scope_enabled` → `degradations == []`（不可用但不记降级）。
- **writer 并入降级**：手工置 `state.retrieval_mode="scope"` + `state.degradations=["图检索运行时失败：X，已降级为经营范围检索。"]` + `scope_candidates` 非空 → `scope_report.open_questions[0]` 是该降级；不可用 graph 分支同理。
- **端到端**（`tests/test_graph.py`）：`build_graph` 注入会抛的 `graph_searcher` + 正常 `scope_retriever`，`graph_enabled=True`、`scope_enabled=True`，query=medium → 最终 `state.scope_report` 非空且 `open_questions` 首条为降级说明，`graph_report is None`、`report is None`。

## 改动面

- 改：`src/deepresearch_agent/state.py`（加 `degradations` 字段）、`src/deepresearch_agent/agents/nodes.py`（`_retrieve_graph` 返回值、`researcher_node` graph 分支降级、`_retrieve_scope` 留痕、两个 writer 并入 degradations）、`tests/test_nodes.py`、`tests/test_graph.py`。
- 不改：`graph.py` / `cli.py` / `api.py` / SQLite schema / 依赖。
- 复用：`_retrieve_scope`、`_group_scope_hits`、`_build_graph_findings`、`ScopeSearchReport`/`GraphSearchReport`。C4 后路线图收尾。
