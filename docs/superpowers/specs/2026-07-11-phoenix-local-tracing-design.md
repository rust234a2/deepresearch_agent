# 模块：Phoenix 本地追踪设计

日期：2026-07-11

给 Agent 加**本地链路追踪**——手动 span 打点 pipeline 各阶段,在本地 Phoenix 里看清每次 `run_research` 怎么跑的（检索模式、召回数、降级、复杂度分级）。**只做追踪/可视化,不用 LLM-eval、不引入外部 LLM、不外发企业数据。**

## 定位与红线

- **默认关**（`enable_tracing=False`）：正常跑 / CI / API / `/research` 完全不受影响,关时零开销。
- **仅本地**：OTLP exporter 只指向 localhost Phoenix；**绝不可指远程**（否则 span 里的企业代码/计数随之外发）。span 含企业信息——本地无妨。
- **DeepSeek/分类只记 `level`/`method`,绝不记企业数据**（守 C1）。
- 无 LLM-eval、无外部 LLM。Phoenix 是纯追踪查看器,数据不出机器。
- Phoenix 本体（`arize-phoenix`）是用户本地单独装、单独 `phoenix serve` 起的查看器,**不作硬依赖**；发 span 只需 opentelemetry（轻）。

## 组件

### `src/deepresearch_agent/observability.py`（追踪唯一落点）

模块级 `_PROVIDER = None` 作为"是否已配置"的门。

```python
def configure_tracing(exporter=None, endpoint: str = "http://localhost:6006/v1/traces"):
    """幂等：已配置则直接返回，不覆盖（便于测试先注入 InMemorySpanExporter）。"""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    provider = TracerProvider()
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=endpoint)  # 仅本地 Phoenix
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
    """测试用：清全局，避免跨用例串。"""
    global _PROVIDER
    _PROVIDER = None


def traced_node(name: str, node_fn, attr_fn=None):
    """图层节点包装器：开 span→跑节点→从返回 state 抽属性→关 span；未配置则透传。"""
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

- 属性值仅用 OTel 兼容标量（str/int/bool/float）。
- `configure_tracing` 里 OTLP exporter 为**懒导入**：测试传 `InMemorySpanExporter` 时永不触发,故测试只需 `opentelemetry-sdk`（不需 otlp exporter）。

### `agents/graph.py`

`build_graph(..., enable_tracing: bool = False)`：`enable_tracing` 时用 `traced_node` 包每个节点 lambda，attr_fn 从返回 state 抽：

- **planner**：`resolution_status`（`state.supplier_resolution.status` 或 `"not_found"`）、`complexity_level`/`complexity_method`（`state.complexity` 有则取）。
- **researcher**：`retrieval_mode`、`retrieval_available`、`scope_candidates`=len、`graph_candidates`=len、`shared_controllers`=len。
- **critic**：`missing_dimensions`=len、`iteration`。
- **writer**：`report_type`（named/scope/graph/unresolved，据哪个 report 非空判定）、`degradations`=len。

不启用时 `build_graph` 行为与现状逐字一致（不包装）。

`run_research(..., enable_tracing: bool = False)`：启用时先 `configure_tracing()`（幂等）、`build_graph(enable_tracing=True)`，并把整次 invoke 包在 root span `research`（属性 `question`=问题文本、`domain`）下,使四个节点 span 自动嵌为子节点。未启用时走原路径。`run_compiled` 签名不变（root span 在 `run_research` 内处理,或抽 `_run_traced(app, question, domain)` 辅助）。

`/research` API 与 `run_compiled` 直连路径**不接追踪**（保持无状态、默认关）。

### CLI

`cli.py` 加 `--trace`（store_true）→ `run_research(enable_tracing=True)`。现有路径不变。启用前用户需本地 `pip install arize-phoenix` 且 `phoenix serve`（spec 给命令,不进依赖）。

### 依赖

`pyproject.toml` 加 `trace = ["opentelemetry-sdk>=1.20", "opentelemetry-exporter-otlp-proto-http>=1.20"]`。`arize-phoenix` 不列入——查看器本地单独装。

## 测试（`tests/test_observability.py`）

`pytest.importorskip("opentelemetry")`（未装 `.[trace]` 自动跳过,同 neo4j/rag 套路）。用 `InMemorySpanExporter`（`opentelemetry.sdk.trace.export`）:

- **traced_node 单元**：`reset_tracing()` → `configure_tracing(exporter=mem)` → 包一个改 state 的假节点、跑一次 → `mem.get_finished_spans()` 有该 span、属性对；`node_fn` 返回值原样透传。
- **未配置透传**：`reset_tracing()`（不 configure）→ `get_tracer() is None`；`traced_node` 包装后调用行为与裸 `node_fn` 完全一致、无 span。
- **端到端**（用 `company_database_path` fixture）：`reset_tracing()` → `configure_tracing(exporter=mem)` → `run_research("核验示例科技股份有限公司", database_path=..., enable_tracing=True)` → span 树含 `research`（root）+ `planner`/`researcher`/`critic`/`writer`；planner span 有 `resolution_status`、writer span 有 `report_type`。
- **enable_tracing=False**：跑 `run_research(..., enable_tracing=False)` → 报告与现状一致、无 span（`mem` 空 / 未配置）。
- 每个用例末尾 `reset_tracing()`（或 autouse fixture）避免全局串。

**本会话验证**：pip 装 `opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`（轻,pure-python）真跑测试；Phoenix 服务不在本会话起（可选,用户本地看 UI 时再 `phoenix serve`）。

## 改动面

- 新：`src/deepresearch_agent/observability.py`、`tests/test_observability.py`。
- 改：`src/deepresearch_agent/agents/graph.py`（`enable_tracing` + `traced_node` 包装 + root span；默认关时逐字不变）、`src/deepresearch_agent/cli.py`（`--trace`）、`pyproject.toml`（`.[trace]` extra）、`tests/test_cli.py`（`--trace` 解析回归）。
- 不改：`nodes.py`（手动 span 全在图层）、`state.py`、`api.py`、SQLite schema、报告结构。
- 不做：自动埋点（选了手动）、单工具/单命中下钻（YAGNI 后续增量）、LLM-eval、把 eval 指标接进 Phoenix Experiments（后续）。
