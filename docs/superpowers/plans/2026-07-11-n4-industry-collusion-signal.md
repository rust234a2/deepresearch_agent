# N4 同行业+同控制人 围标线索 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 graph 模式的共享控制人之上，检测"同一控制人控制的候选里 ≥2 家同行业"，作为围标/集中度线索写进 `GraphSearchReport`（线索级、须人工复核）。

**Architecture:** 后端协议加 `company_industry(node_id) -> str | None`（Neo4j 查 `IN_INDUSTRY`，内存返 None 优雅降级）；`assemble_subgraph_context` 按行业给每个共享控制人算 `concentrated_industries`；字段透传到 `SharedControllerFinding`；writer 非空则把 note/summary 升级为围标叙述。

**Tech Stack:** Python、Pydantic、Neo4j 5（本地 Docker）、pytest。复用 N3 的 `IN_INDUSTRY` 边、N2 driver/对拍、`@pytest.mark.neo4j`、C4 降级链。

## Global Constraints

- **线索级**：`via_person` 低置信、标"须人工复核"；**绝不认定围标**（同名自然人可能非同一人；同控制人 ≠ 实际串通）。报告固定 `insufficient_evidence`。
- 无 LLM；不结构化 `business_scope`（行业来自 N3 登记 `IN_INDUSTRY` 边）。
- 内存后端 `company_industry` 返 `None` → 集中度自然为空、不误报；N2 对拍不受影响（不灌行业 → 全 None → 两后端仍逐条相等）。
- `cli.py`/`api.py`/`graph_traversal.py`/`ownership_graph.py`/SQLite schema/灌图脚本/依赖不改。
- Windows 测试：`.\.conda-env\python.exe -m pytest <target> -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`。Neo4j 测试加 `-m neo4j`。
- 每个任务结束提交一次；中文提交信息。

## 文件结构

- 改 `src/deepresearch_agent/ownership_backend.py` — 协议 + `InMemoryOwnershipBackend.company_industry`（Task 1）。
- 改 `src/deepresearch_agent/neo4j_backend.py` — `company_industry` Cypher（Task 1）。
- 改 `src/deepresearch_agent/graph_retrieval.py` — `SharedController.concentrated_industries` + `assemble_subgraph_context` 集中度（Task 1）。
- 改 `src/deepresearch_agent/state.py` — `SharedControllerFinding.concentrated_industries`（Task 2）。
- 改 `src/deepresearch_agent/agents/nodes.py` — `_build_graph_findings` 透传+note、`_write_graph_report` summary（Task 2）。
- 改 `tests/test_graph_retrieval.py`（Task 1）、`tests/test_nodes.py`（Task 2）、`tests/test_neo4j_backend.py`（Task 3）。

---

### Task 1：后端 `company_industry` + 集中度检测

**Files:**
- Modify: `src/deepresearch_agent/ownership_backend.py`、`src/deepresearch_agent/neo4j_backend.py`、`src/deepresearch_agent/graph_retrieval.py`
- Test: `tests/test_graph_retrieval.py`

**Interfaces:**
- Produces: `OwnershipGraphBackend.company_industry(node_id: str) -> str | None`；`InMemoryOwnershipBackend.company_industry`（返 None）；`Neo4jBackend.company_industry`（Cypher）；`SharedController.concentrated_industries: list[str] = []`；`assemble_subgraph_context` 填该字段。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_retrieval.py` 末尾追加：

```python
class _IndustryBackend:
    """假后端：显式给定 industry 映射，验证集中度检测。"""

    def __init__(self, graph, industries):
        from deepresearch_agent.ownership_backend import InMemoryOwnershipBackend

        self._mem = InMemoryOwnershipBackend(graph)
        self._industries = industries

    def has_node(self, node_id):
        return self._mem.has_node(node_id)

    def display_name(self, node_id):
        return self._mem.display_name(node_id)

    def ultimate_controllers(self, node_id, max_depth=5):
        return self._mem.ultimate_controllers(node_id, max_depth=max_depth)

    def direct_neighbors(self, node_id):
        return self._mem.direct_neighbors(node_id)

    def company_industry(self, node_id):
        return self._industries.get(node_id)


def test_shared_controller_flags_same_industry_concentration(tmp_path):
    graph = _graph(tmp_path)
    # 甲、丙 同行业"机床"，乙 不同 → 控制 {甲,丙} 的控制人应标记该行业
    backend = _IndustryBackend(graph, {A_CODE: "机床制造", C_CODE: "机床制造", B_CODE: "餐饮"})

    ctx = assemble_subgraph_context(backend, [A_CODE, B_CODE, C_CODE])

    shared = {s.node_id: s for s in ctx.shared_controllers}
    zhangsan = shared["person:张三"]  # 张三 控制 甲、丙（均"机床制造"）
    assert zhangsan.concentrated_industries == ["机床制造"]


def test_inmemory_backend_reports_no_industry_concentration(tmp_path):
    graph = _graph(tmp_path)

    ctx = assemble_subgraph_context(InMemoryOwnershipBackend(graph), [A_CODE, B_CODE, C_CODE])

    assert all(s.concentrated_industries == [] for s in ctx.shared_controllers)
```

（`_graph`/`A_CODE`/`B_CODE`/`C_CODE`/`InMemoryOwnershipBackend` 已在该测试文件中定义/导入。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -k "concentration" -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: FAIL（`SharedController` 无 `concentrated_industries`，或 `assemble_subgraph_context` 未填）

- [ ] **Step 3: 协议 + 内存后端加 `company_industry`**

`src/deepresearch_agent/ownership_backend.py`，`OwnershipGraphBackend` 协议加一行：

```python
    def company_industry(self, node_id: str) -> str | None: ...
```

`InMemoryOwnershipBackend` 加方法（放在 `direct_neighbors` 之后）：

```python
    def company_industry(self, node_id: str) -> str | None:
        return None  # 内存图无行业层（N3 只灌 Neo4j）；优雅降级，不误报集中度
```

- [ ] **Step 4: Neo4j 后端加 `company_industry`**

`src/deepresearch_agent/neo4j_backend.py`，在 `direct_neighbors` 之后加方法：

```python
    def company_industry(self, node_id: str) -> str | None:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (c:Entity {node_id: $id})-[:IN_INDUSTRY]->(i:Industry) "
                "RETURN i.name AS name",
                id=node_id,
            ).single()
        return rec["name"] if rec is not None else None
```

- [ ] **Step 5: `SharedController` 加字段 + `assemble_subgraph_context` 算集中度**

`src/deepresearch_agent/graph_retrieval.py`，`SharedController` 加字段：

```python
class SharedController(BaseModel):
    node_id: str
    name: str
    controlled_seeds: list[str]
    via_person: bool
    concentrated_industries: list[str] = []
```

把 `assemble_subgraph_context` 里构造 `shared` 的列表推导替换为（在推导前算集中度）：

```python
    shared: list[SharedController] = []
    for nid, codes in controlled.items():
        if len(codes) < 2:
            continue
        by_industry: dict[str, int] = {}
        for code in codes:
            industry = backend.company_industry(code)
            if industry:
                by_industry[industry] = by_industry.get(industry, 0) + 1
        concentrated = sorted(name for name, n in by_industry.items() if n >= 2)
        shared.append(
            SharedController(
                node_id=nid,
                name=meta[nid][0],
                controlled_seeds=sorted(codes),
                via_person=meta[nid][1],
                concentrated_industries=concentrated,
            )
        )
```

（`shared.sort(...)`、`seeds.sort(...)`、`return` 保持不变。）

- [ ] **Step 6: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_graph_retrieval.py -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: PASS（新增 2 项 + 既有 graph_retrieval 测试全绿）

- [ ] **Step 7: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: 全绿（`concentrated_industries` 默认 [] 向后兼容）

- [ ] **Step 8: 提交**

```bash
git add src/deepresearch_agent/ownership_backend.py src/deepresearch_agent/neo4j_backend.py src/deepresearch_agent/graph_retrieval.py tests/test_graph_retrieval.py
git commit -m "功能：N4-1 后端 company_industry 与共享控制人同行业集中度检测"
```

---

### Task 2：state 字段 + writer 围标叙述

**Files:**
- Modify: `src/deepresearch_agent/state.py`、`src/deepresearch_agent/agents/nodes.py`
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `SharedController.concentrated_industries`（Task 1）。
- Produces: `SharedControllerFinding.concentrated_industries: list[str] = []`；`_build_graph_findings` 透传 + note 升级；`_write_graph_report` summary 追加围标计数。

- [ ] **Step 1: 写失败测试**

在 `tests/test_nodes.py` 末尾追加：

```python
def test_graph_findings_flag_industry_collusion_note():
    from deepresearch_agent.agents.nodes import _build_graph_findings
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext, SharedController

    context = HybridContext(
        query="q",
        seeds=[
            SeedContext(code="A", name="甲", score=0.9, controllers=[], neighbors=[]),
            SeedContext(code="C", name="丙", score=0.8, controllers=[], neighbors=[]),
        ],
        shared_controllers=[
            SharedController(
                node_id="person:张三", name="张三", controlled_seeds=["A", "C"],
                via_person=True, concentrated_industries=["机床制造"],
            )
        ],
    )
    _candidates, shared = _build_graph_findings(context)
    finding = shared[0]
    assert finding.concentrated_industries == ["机床制造"]
    assert "同行业" in finding.note and "围标" in finding.note and "须人工复核" in finding.note


def test_graph_findings_keep_plain_note_without_concentration():
    from deepresearch_agent.agents.nodes import _build_graph_findings
    from deepresearch_agent.graph_retrieval import HybridContext, SeedContext, SharedController

    context = HybridContext(
        query="q",
        seeds=[SeedContext(code="A", name="甲", score=0.9, controllers=[], neighbors=[])],
        shared_controllers=[
            SharedController(
                node_id="ext:集团", name="集团", controlled_seeds=["A", "B"],
                via_person=False, concentrated_industries=[],
            )
        ],
    )
    _candidates, shared = _build_graph_findings(context)
    assert shared[0].concentrated_industries == []
    assert shared[0].note == "经企业股权链推断"


def test_writer_graph_summary_flags_collusion(company_database_path):
    from deepresearch_agent.state import GraphSearchCandidate, SharedControllerFinding

    state = ResearchState(question="q", domain="procurement")
    state.retrieval_mode = "graph"
    state.graph_candidates = [
        GraphSearchCandidate(
            unified_social_credit_code="A", legal_name="甲", top_score=0.9, ultimate_controllers=[]
        )
    ]
    state.shared_controllers = [
        SharedControllerFinding(
            controller_name="张三", controlled_companies=["甲", "丙"], via_person=True,
            note="同行业（机床制造）+同控制人，疑似围标/集中度线索，须人工复核",
            concentrated_industries=["机床制造"],
        )
    ]
    updated = writer_node(state, DOMAIN_PACK)
    assert "同行业+同控制人" in updated.graph_report.summary
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "collusion or plain_note" -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: FAIL（`SharedControllerFinding` 无 `concentrated_industries`；note 未升级；summary 无围标计数）

- [ ] **Step 3: `SharedControllerFinding` 加字段**

`src/deepresearch_agent/state.py`，`SharedControllerFinding` 加字段：

```python
class SharedControllerFinding(BaseModel):
    controller_name: str
    controlled_companies: list[str]
    via_person: bool
    note: str
    concentrated_industries: list[str] = []
```

- [ ] **Step 4: `_build_graph_findings` 透传 + note 升级**

`src/deepresearch_agent/agents/nodes.py`，把 `_build_graph_findings` 里构造 `shared` 的列表推导替换为：

```python
    shared = []
    for item in context.shared_controllers:
        if item.concentrated_industries:
            note = (
                f"同行业（{'、'.join(item.concentrated_industries)}）+同控制人，"
                "疑似围标/集中度线索，须人工复核"
            )
        elif item.via_person:
            note = "经同名自然人推断，须人工复核"
        else:
            note = "经企业股权链推断"
        shared.append(
            SharedControllerFinding(
                controller_name=item.name,
                controlled_companies=[name_by_code.get(code, code) for code in item.controlled_seeds],
                via_person=item.via_person,
                note=note,
                concentrated_industries=item.concentrated_industries,
            )
        )
    return candidates, shared
```

- [ ] **Step 5: `_write_graph_report` summary 追加围标计数**

`src/deepresearch_agent/agents/nodes.py`，在 `_write_graph_report` 里 `if candidates:` 分支、`middle = ...` 之后、`summary = (...)` 之前，插入围标计数并把它并进 summary。把这段：

```python
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
```

替换为：

```python
    if candidates:
        if shared:
            collusion = sum(1 for s in shared if s.concentrated_industries)
            middle = f"其中 {len(shared)} 组疑似共享控制人（围标/集中度线索，须人工复核）；"
            if collusion:
                middle += f"其中 {collusion} 组同行业+同控制人（更强围标线索，须人工复核）；"
        else:
            middle = "未发现候选间共享控制人；"
        summary = (
            f"按经营范围语义检索到 {len(candidates)} 家候选；"
            + middle
            + "现有数据不足以作出采购批准或风险结论。"
        )
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_nodes.py -k "collusion or plain_note" -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: PASS（3 项）

- [ ] **Step 7: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: 全绿（既有 graph writer 测试的 finding `concentrated_industries` 默认 [] → note/summary 走旧分支，不变）

- [ ] **Step 8: 提交**

```bash
git add src/deepresearch_agent/state.py src/deepresearch_agent/agents/nodes.py tests/test_nodes.py
git commit -m "功能：N4-2 SharedControllerFinding 加 concentrated_industries，writer 出围标叙述"
```

---

### Task 3：Neo4j 端到端验证

**Files:**
- Test: `tests/test_neo4j_backend.py`（追加）

**Interfaces:**
- Consumes: `Neo4jBackend.company_industry`（Task 1）、`build_ownership_neo4j`/`build_industry_neo4j`（N2/N3）、`assemble_subgraph_context`（Task 1）。

- [ ] **Step 0: 起 Neo4j（若未起）**

```powershell
$env:NEO4J_URI="bolt://localhost:7687"; $env:NEO4J_USER="neo4j"; $env:NEO4J_PASSWORD="devpassword"
docker compose up -d neo4j
```

- [ ] **Step 1: 写测试**

在 `tests/test_neo4j_backend.py` 末尾追加：

```python
@pytest.mark.neo4j
def test_neo4j_company_industry_and_concentration(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_ownership_neo4j import build_industry_neo4j, build_ownership_neo4j

    from deepresearch_agent.graph_retrieval import assemble_subgraph_context
    from deepresearch_agent.neo4j_backend import Neo4jBackend

    repository = _repository(tmp_path)
    driver = _driver_or_skip()
    try:
        build_ownership_neo4j(repository, driver)
        build_industry_neo4j(repository, driver)
        neo = Neo4jBackend(driver)

        # 甲乙丙 fixture 同四级行业（N3 已补），company_industry 返回小类名
        industry = neo.company_industry(A_CODE)
        assert industry == "金属切削机床制造"

        ctx = assemble_subgraph_context(neo, [A_CODE, B_CODE, C_CODE])
        flagged = [s for s in ctx.shared_controllers if s.concentrated_industries]
        assert flagged, "同行业+同控制人应产出集中度线索"
        assert all("金属切削机床制造" in s.concentrated_industries for s in flagged)
    finally:
        driver.close()
```

- [ ] **Step 2: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py::test_neo4j_company_industry_and_concentration -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: PASS（Neo4j 查到行业 + 集中度线索）。

> 若 `company_industry` 返 None：确认 `build_industry_neo4j` 已跑（IN_INDUSTRY 边存在）、`A_CODE` 有行业字段（N3 已补 `ownership_links`）。

- [ ] **Step 3: 对拍仍绿（N2 不受影响）**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend.py -m neo4j -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: PASS（N2 对拍 `test_neo4j_backend_matches_inmemory` 仍绿——不灌行业时 `company_industry` 全 None，两后端 `concentrated_industries` 都 []）。

> 注：N2 对拍测试 `test_neo4j_backend_matches_inmemory` 只跑 `build_ownership_neo4j`、不灌行业，故 Neo4j 侧 `company_industry` 也返 None，与内存侧一致。本 N4 测试单独灌行业、单独验证，二者互不干扰（各自 fixture 数据库 + 幂等灌图）。

- [ ] **Step 4: 全量回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-n4`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add tests/test_neo4j_backend.py
git commit -m "功能：N4-3 端到端验证 Neo4j 行业查询与同行业+同控制人集中度线索"
```

---

## 收尾

三任务完成、全量绿 + Neo4j 端到端绿后，用 **superpowers:finishing-a-development-branch** 合并；按推送习惯自动推 master。收尾前文档同步 N4：`docs/architecture.md` 后续能力去掉 N4、`project-memory.md`/`CLAUDE.md` 记"graph 报告已含同行业+同控制人围标线索"。

## Self-Review

- **Spec 覆盖**：`company_industry`（协议 + 内存 None + Neo4j Cypher）=Task 1；集中度检测（`assemble_subgraph_context`）=Task 1；`SharedController` 字段=Task 1、`SharedControllerFinding` 字段=Task 2；writer note/summary 升级=Task 2；单元（假后端 + 内存不误报）=Task 1、writer=Task 2；Neo4j 端到端=Task 3；对拍不受影响=Task 3 Step 3 显式验证；红线（线索级、须人工复核、无 LLM）=Global Constraints。
- **占位符**：无 TBD/TODO；每步含完整代码。
- **类型一致**：`concentrated_industries: list[str]` 在 `SharedController`（Task 1）与 `SharedControllerFinding`（Task 2）同名同型；`company_industry(node_id) -> str | None` 在协议/内存/Neo4j 三处一致；`_build_graph_findings` 透传 `item.concentrated_industries`（Task 1 产出）→ Task 2 消费。
