# Agent 跨企业经营范围筛选集成设计

日期：2026-06-23

## 目标

把已建好的跨企业语义经营范围检索（`rag/`）接入 Agent 主流程，与现有“核验指定企业”流程并存。用户提“按能力找供应商”类问题（未指名某家企业）时，planner 自动路由到 scope 检索，输出候选供应商清单。延续数据纪律：按经营范围找到企业 ≠ 采购背书，推荐值固定 `insufficient_evidence`。

## 范围

### 包含

- planner 路由扩展：`not_found` 且注入了 scope 节点时 → scope 检索路径。
- 新节点 `scope_search_node`（注入式；retriever 缺失时给出“不可用”报告）。
- 新报告 `ScopeSearchReport` 与 `ScopeCandidate`，复用现有 `Evidence`/`Citation`。
- `ResearchState` 增加 `scope_report` 字段。
- `run_research` 增加 `enable_scope` 开关；CLI 启用、API 不启用。
- 依赖/索引缺失的优雅降级（懒加载 `rag`，缺失给出明确报告，核心流程不受影响）。
- 检索器在 `run_research` 内单次构建并注入。
- 主 CLI（`deepresearch_agent.cli`）渲染候选清单。

### 不包含

- 不改 `/research` API 响应形状（仍只返回 `SupplierReport`，API 不注入 scope 路由）。API 端到端暴露是后续单独决策。
- 不做“先筛选再逐个核验”（方案 B，后续 spec）。
- 不引入 LLM；路由用确定性的 `resolve_supplier` 结果。
- 不改 `rag/` 检索子系统本身。

## 路由

`planner_node` 不变（跑 `resolve_supplier`，设置 `supplier_resolution`）。planner 后的条件路由按 `resolution.status` 与“是否注入 scope 节点”决定：

- `resolved` → researcher（现有，不变）。
- `ambiguous` → writer（现有“请指定一家”，不变）。
- `not_found`：
  - 注入了 scope 节点 → `scope_search`（新）。
  - 未注入 → writer（现有“未解析”报告 = 当前行为）。

“是否注入 scope 节点”由调用方决定：**CLI 注入，API 不注入**。因此 API 的行为与响应形状完全不变。注入与否是与“retriever 是否可用”分离的两件事——CLI 始终注入 scope 节点，节点内部再处理 retriever 为 None 的情况。

## 组件

### `build_graph` 签名扩展

```python
build_graph(domain_pack, repository, scope_node=None)
```

- `scope_node: Callable[[ResearchState], ResearchState] | None`。
- 提供时：新增名为 `scope_search` 的节点，planner 的 `not_found` 路由到它，`scope_search → END`。
- 为 `None` 时：`not_found` 路由到 writer（现状）。

planner 后的路由函数是对 `scope_node is not None` 的闭包，避免散落判断。

### `scope_search_node(state, retriever)`

`retriever: ScopeRetriever | None`。

- `retriever` 为 `None`（scope 启用但 `.[rag]`/索引/模型缺失）→ 产出
  `ScopeSearchReport(query=state.question, candidates=[], summary="经营范围语义检索不可用：请安装 .[rag] 可选依赖并运行 scripts/build_scope_index.py 构建索引。", recommendation="insufficient_evidence", open_questions=["安装 .[rag] 可选依赖并构建 FAISS 经营范围索引。"])`，写入 `state.scope_report`。
- 否则：`hits = retriever.search(state.question, k=10)`，按 `unified_social_credit_code` 分组成 `ScopeCandidate`，按 `top_score` 降序；`recommendation="insufficient_evidence"`；写入 `state.scope_report`。0 命中 → `candidates=[]`，summary="未检索到经营范围匹配的企业。"。

`open_questions`（命中时）固定列出尚未接入、因而无法据经营范围作出采购结论的数据源，与 `writer_node` 一致：

```python
[
    "经营范围匹配仅为登记信息，不代表实际产能、交期或质量。",
    "接入制裁和监管名单数据。",
    "接入司法案件与负面新闻数据。",
    "接入财务数据。",
    "接入产能、交期与质量认证数据。",
    "接入内部采购履约数据。",
]
```

命中时 summary 形如：`f"按经营范围语义检索到 {len(candidates)} 家候选企业；现有数据仅工商经营范围，不足以作出采购批准或风险结论。"`
- `retriever.search` 抛异常 → 节点内 `try/except` 兜成“不可用”报告，不影响其他路径。

每条命中映射为现有 `Evidence`（复用，不另造引用系统）：

```python
Evidence(
    claim=hit.text,
    dimension="business_scope_match",
    confidence=hit.score,
    citation=Citation(
        source_id=f"company:{hit.unified_social_credit_code}",
        title=f"{hit.legal_name} 经营范围",
        url=f"local://companies/{hit.unified_social_credit_code}",
        snippet=hit.text,
    ),
)
```

`confidence` 取 `min(max(score, 0.0), 1.0)`（FAISS 内积在归一化向量下落在 [-1,1]，clamp 到 Evidence 的 [0,1] 约束）。

### 数据模型（`state.py`）

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

`ResearchState` 增加：`scope_report: ScopeSearchReport | None = None`。`report`（`SupplierReport | None`）保持不变；核验路径写 `report`，scope 路径写 `scope_report`，互不干扰。

### `run_research` 扩展

```python
run_research(question, domain="procurement",
             database_path=DEFAULT_DATABASE_PATH,
             index_path=DEFAULT_INDEX_PATH,
             enable_scope=False) -> ResearchState
```

- `enable_scope=False`（API 默认）：`scope_node=None`，行为与现状一致。
- `enable_scope=True`（CLI）：懒构建检索器——

```python
scope_node = None
if enable_scope:
    try:
        from deepresearch_agent.rag.embedding import BgeEmbedder
        from deepresearch_agent.rag.retriever import load_scope_retriever
        retriever = load_scope_retriever(database_path, index_path, BgeEmbedder())
    except Exception:
        retriever = None
    scope_node = lambda state: scope_search_node(state, retriever)
app = build_graph(domain_pack, repository, scope_node=scope_node)
```

`rag` 仅在 `enable_scope` 分支内 import，核心 import 不依赖 faiss/torch。捕获 `Exception` 覆盖 `ImportError`（未装 `.[rag]`）、`ScopeIndexMismatchError`/`FileNotFoundError`（索引/元数据缺失）、模型加载失败。

`DEFAULT_INDEX_PATH = Path("data/procurement/derived/scope_index.faiss")`，与 `DEFAULT_DATABASE_PATH` 并列定义于 `graph.py`。

### CLI（`deepresearch_agent/cli.py`）扩展

- 调用 `run_research(question, database_path=..., index_path=..., enable_scope=True)`。
- 新增 `--index` 参数（默认 `DEFAULT_INDEX_PATH`）。
- 渲染分流：`state.scope_report is not None` → 渲染候选清单（企业法定名称 / 命中条款 / 评分 + summary）；否则按现有 `state.report` 渲染 `SupplierReport`。

### API（`api.py`）

不变。`run_research` 默认 `enable_scope=False`，`/research` 仍 `response_model=SupplierReport`，对未解析问题继续返回现有 unresolved `SupplierReport`。

## 错误处理与降级

- `.[rag]` 未装 / FAISS 索引缺失 / 模型加载失败 → `retriever=None` → `scope_search_node` 产出“不可用”`ScopeSearchReport`，不抛异常、不影响核验路径。
- 主 graph 的 import 不引入 faiss/torch（懒加载于 `run_research` 的 `enable_scope` 分支）。
- 检索期异常被 `scope_search_node` 兜成“不可用”报告。

## 测试策略（默认不加载真模型）

- planner 路由：`resolved`→researcher（沿用现有）；`not_found` + 注入 scope 节点→`scope_search` 并产出 `scope_report`；`not_found` + 未注入→writer（API 行为不变）；`ambiguous`→writer（不变）。
- `scope_search_node`：用 `FakeEmbedder` + 临时 FAISS 索引（`build_scope_index`）+ fixture SQLite → 能力问题返回候选、按评分降序、`Evidence` 正确、`recommendation="insufficient_evidence"`；`retriever=None` → “不可用”报告；0 命中 → 空候选 + 说明。
- `run_research(enable_scope=True)` 端到端：能力问题返回 `scope_report`；指名企业问题仍返回 `report`。
- API 回归：默认 `enable_scope=False`，`/research` 对能力问题仍返回 `SupplierReport`，响应形状不变。
- CLI：能力问题打印候选清单；指名企业打印工商报告。

测试 scope 路径用 `FakeEmbedder`（需 `.[rag]` 的 faiss，已装）；`BgeEmbedder` 仅在既有 slow 集成测试触及。

## 决策记录

- 方案 A（并存），非 B/C：复用 graph/state/planner/工具/证据模型，新增最少。
- 路由用确定性 `resolve_supplier` 回退（无 LLM）。
- API 走 (b)：`/research` 形状不变，scope 仅经 CLI 暴露；scope 节点注入式，API 不注入。
- `ScopeSearchReport` 复用 `Evidence`/`Citation`，不另造引用。
- `recommendation` 固定 `insufficient_evidence`：按经营范围找到 ≠ 采购背书。
- 缺 `.[rag]`/索引 → 优雅降级为“不可用”报告，核心流程不受影响。

## 验收条件

- 默认测试全绿，默认不加载真模型。
- CLI 对“哪些企业能做 X”类问题返回按评分排序的候选清单（企业 + 命中条款 + 评分），`recommendation="insufficient_evidence"`。
- CLI 对“核验某企业”问题行为不变。
- `/research` API 响应形状与现有行为不变。
- 未装 `.[rag]` 或未建索引时，核心 import 与核验流程不受影响；能力问题经 CLI 返回明确“不可用”报告。
