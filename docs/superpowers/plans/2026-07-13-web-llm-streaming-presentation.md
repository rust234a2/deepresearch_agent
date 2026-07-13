# 网页端 LLM 流式呈现实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把网页流式端点 `/session/turn/stream` 的呈现层从确定性切块换成 DeepSeek 流式生成（命名/scope/graph 三报告统一走 LLM），无 key/异常回退现有 `_report_message_chunks`，结论句后端硬发，一并修 Neo4j 裸启动静默降级。

**Architecture:** 新增 `build_deepseek_polisher`（复用现有 OpenAI client 模式，`stream=True` 逐 token）；`create_app` 建一次 polisher 并在流式 complete 分支接入（有则 LLM、无则兜底、异常回退）；结论句由后端 `_conclusion_line` 硬发不进 LLM；`Neo4jBackend.from_env` 兜底密码 + 启动日志。前端零改动。

**Tech Stack:** OpenAI SDK（DeepSeek 兼容，`stream=True`）、FastAPI SSE、pytest（fake client 零网络）。环境 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **LLM 只是呈现层**：拿 writer 已定稿的报告 JSON，只复述、不检索、不改结论、不推断产能/交期/认证、经营范围按原文、保留企业名/信用代码/控制人原文、围标线索标「线索级·须人工复核」。
- **结论纵深防御**：`recommendation` 对应结论句由后端在 LLM 正文前**确定性硬发一次**，不进 LLM。
- **降级链**：无 `DEEPSEEK_API_KEY` → polisher=None → `_report_message_chunks` 兜底；LLM 异常 → 回退 `_report_message_chunks`；均不崩、不另造兜底函数。
- **数据越境**：全部检索结果进 prompt——用户明确决定扩大豁免（与记忆层同级，核心红线文本仍在、仅本线豁免）。CI 零网络零 key（fake client / 无 key 兜底），真链路标 `@pytest.mark.llm`。
- Neo4j 默认密码 `devpassword` 仅本地（对齐 docker-compose）。启动日志用 `logging`，非 print。
- 测试隔离缓存：`.\.conda-env\python.exe -m pytest <路径> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`。
- 现有资产：`_resolve_report(state)->tuple[str,dict]` 与 `_report_message_chunks(report,report_type)` 已在 `api.py`（上一模块提交）。`build_deepseek_classifier` 在 `llm/deepseek.py`（OpenAI client 模式模板）。

---

### Task 1: `build_deepseek_polisher` + `_render_report_for_llm`（LLM 流式呈现器）

**Files:**
- Modify: `src/deepresearch_agent/llm/deepseek.py`
- Test: `tests/test_deepseek_polisher.py`

**Interfaces:**
- Produces:
  - `_render_report_for_llm(report_type: str, report: dict) -> str`（报告 JSON → 给 LLM 的输入文本，**不含结论句**）
  - `build_deepseek_polisher(api_key=None, model="deepseek-chat", base_url="https://api.deepseek.com", client=None) -> Callable[[str, dict], Iterator[str]] | None`
  - 返回的 `stream_presentation(report_type, report) -> Iterator[str]`
- Consumes: `openai.OpenAI`（已有）、`DEEPSEEK_API_KEY`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_deepseek_polisher.py`：

```python
from deepresearch_agent.llm.deepseek import build_deepseek_polisher, _render_report_for_llm


class _FakeChunk:
    def __init__(self, text): self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()]


class _FakeStream:
    def __iter__(self): return iter([_FakeChunk("甲公司"), _FakeChunk("经营范围…"), _FakeChunk("")])


class _FakeCompletions:
    def create(self, **kw): return _FakeStream()


class _FakeClient:
    chat = type("Chat", (), {"completions": _FakeCompletions()})()


def _graph_report():
    return {
        "recommendation": "insufficient_evidence", "query": "找股东有关联的供应商",
        "summary": "检索到 2 家候选。",
        "candidates": [{"legal_name": "丙公司", "top_score": 0.8, "ultimate_controllers": ["张三"]}],
        "shared_controllers": [{"controller_name": "张三", "controlled_companies": ["丙公司", "丁公司"], "note": "经企业股权链推断"}],
    }


def test_render_includes_facts_excludes_conclusion():
    text = _render_report_for_llm("graph", _graph_report())
    assert "丙公司" in text and "张三" in text
    assert "证据不足" not in text  # 结论句不进 LLM 输入


def test_polisher_streams_tokens_from_client():
    polisher = build_deepseek_polisher(client=_FakeClient())
    tokens = list(polisher("graph", _graph_report()))
    assert "甲公司" in tokens
    assert "" not in tokens  # 空 delta 被过滤


def test_polisher_none_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_polisher() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_deepseek_polisher.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: FAIL（`ImportError: cannot import name 'build_deepseek_polisher'`）

- [ ] **Step 3: 实现**

在 `src/deepresearch_agent/llm/deepseek.py` 末尾追加：

```python
from typing import Iterator


_PRESENTER_SYSTEM_PROMPT = (
    "你是工商研究报告的呈现器，把给定的结构化报告改写成通顺中文，用于展示。严格规则：\n"
    "1. 只复述报告中出现的事实，绝不添加任何未在报告中的信息。\n"
    "2. 绝不推断产能、交期、质量认证或风险；经营范围按原文，不结构化为产品。\n"
    "3. 保留所有企业名、统一社会信用代码、控制人姓名的原文，不改写。\n"
    "4. 围标/共享控制人线索必须标注「线索级·须人工复核」，绝不作控制关系或围标认定。\n"
    "5. 不要复述或改写结论（结论由系统另行给出）；只输出正文，不加建议、不加评论。"
)


def _render_report_for_llm(report_type: str, report: dict) -> str:
    lines: list[str] = []
    if report_type in ("named", "unresolved"):
        lines.append(f"企业：{report.get('supplier_name', '')}")
        if report.get("summary"):
            lines.append(f"摘要：{report['summary']}")
        for ev in report.get("evidence_table", []):
            lines.append(f"证据[{ev.get('dimension', '')}]：{ev.get('claim', '')}")
        for r in report.get("risks", []):
            lines.append(f"提示：{r}")
    elif report_type == "scope":
        lines.append(f"能力检索：{report.get('query', '')}")
        if report.get("summary"):
            lines.append(f"摘要：{report['summary']}")
        for c in report.get("candidates", []):
            lines.append(f"候选：{c.get('legal_name', '')}（相关度 {c.get('top_score', 0):.2f}）")
    else:  # graph
        lines.append(f"股权关系检索：{report.get('query', '')}")
        if report.get("summary"):
            lines.append(f"摘要：{report['summary']}")
        for c in report.get("candidates", []):
            ctrl = "、".join(c.get("ultimate_controllers") or []) or "—"
            lines.append(f"候选：{c.get('legal_name', '')}｜最终控制人：{ctrl}")
        for s in report.get("shared_controllers", []):
            comp = "、".join(s.get("controlled_companies") or [])
            lines.append(f"共享控制人线索：{s.get('controller_name', '')} → {comp}（{s.get('note', '')}）")
    for q in report.get("open_questions", []):
        lines.append(f"待解问题：{q}")
    return "\n".join(lines)


def build_deepseek_polisher(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> "Callable[[str, dict], Iterator[str]] | None":
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url)

    def stream_presentation(report_type: str, report: dict) -> Iterator[str]:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            stream=True,
            messages=[
                {"role": "system", "content": _PRESENTER_SYSTEM_PROMPT},
                {"role": "user", "content": _render_report_for_llm(report_type, report)},
            ],
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return stream_presentation
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_deepseek_polisher.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: PASS（3 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/llm/deepseek.py tests/test_deepseek_polisher.py
git commit -m "功能：build_deepseek_polisher 流式呈现器(约束 prompt+report 转输入文本，无 key 返 None)"
```

---

### Task 2: API 流式端点接入 LLM 呈现 + 结论硬发

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_api_stream_retrieval.py`

**Interfaces:**
- Consumes: Task 1 `build_deepseek_polisher`；已有 `_resolve_report`/`_report_message_chunks`/`_RECOMMENDATION_TEXT`。
- Produces: `create_app(..., polisher=None)`；`_conclusion_line(report)->str`；流式 `report_start{report_type,title,recommendation}` + 结论 delta + 正文 delta + `complete`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api_stream_retrieval.py`：

```python
from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore


def _client(db, tmp, **kw):
    app = create_app(
        database_path=db, memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp), **kw,
    )
    return TestClient(app)


def _fake_polisher(report_type, report):
    yield "【LLM呈现】"
    yield report.get("supplier_name") or report.get("query", "")


def test_stream_uses_polisher_when_present(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=_fake_polisher)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body
    assert "【LLM呈现】" in body           # 走了 LLM
    assert "证据不足" in body               # 结论句后端硬发


def test_stream_falls_back_without_polisher(company_database_path, tmp_path):
    client = _client(company_database_path, tmp_path, polisher=None)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: report_start" in body and "event: complete" in body
    assert "【LLM呈现】" not in body         # 未走 LLM，走确定性兜底


def test_stream_polisher_exception_falls_back(company_database_path, tmp_path):
    def _boom(report_type, report):
        raise RuntimeError("llm down")
        yield  # pragma: no cover
    client = _client(company_database_path, tmp_path, polisher=_boom)
    with client.stream("POST", "/session/turn/stream",
                       json={"question": "示例科技股份有限公司", "user_id": "alice"}) as r:
        body = "".join(r.iter_text())
    assert "event: complete" in body        # 异常回退、不崩
    assert "证据不足" in body                # 结论句仍在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: FAIL（`create_app` 不接受 `polisher`）

- [ ] **Step 3: 实现**

在 `api.py` import 区加：

```python
from deepresearch_agent.llm.deepseek import build_deepseek_polisher
```

在 `_RECOMMENDATION_TEXT` 之后加：

```python
def _conclusion_line(report: dict) -> str:
    rec = _RECOMMENDATION_TEXT.get(report["recommendation"], report["recommendation"])
    return f"\n\n结论：{rec}"
```

改 `create_app` 签名（加 `polisher` 参数，默认建一次）：

```python
def create_app(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    memory: MemoryService | None = None,
    session_store: JsonSessionStore | None = None,
    polisher: object = "__default__",
) -> FastAPI:
    application = FastAPI(title="DeepResearch Agent", version="0.1.0")
    repository = CompanyRepository(database_path)
    compiled_graphs: dict[str, object] = {}
    memory_service = memory if memory is not None else MemoryService(build_memory_backend())
    store = session_store if session_store is not None else JsonSessionStore(DEFAULT_SESSIONS_DIR)
    if polisher == "__default__":
        polisher = build_deepseek_polisher()
```

（用哨兵 `"__default__"` 区分「测试显式传 None（禁用）」与「默认自动建」。）

改流式 complete 分支（api.py:152-162）为：

```python
                store.save(session)
                report_type, report = _resolve_report(state)
                yield _sse("report_start", {
                    "report_type": report_type,
                    "title": report.get("supplier_name") or report.get("query", ""),
                    "recommendation": report["recommendation"],
                })
                yield _sse("message_delta", {"text": _conclusion_line(report)})
                used_llm = False
                if polisher is not None:
                    try:
                        for tok in polisher(report_type, report):
                            used_llm = True
                            yield _sse("message_delta", {"text": tok})
                    except Exception:
                        used_llm = False
                if not used_llm:
                    for text in _report_message_chunks(report, report_type):
                        yield _sse("message_delta", {"text": text})
                yield _sse("complete", {"session_id": session.session_id})
```

（注：`used_llm` 仅在 polisher 真产出 token 后置 True；若 polisher 一上来就抛异常，回退确定性。若已产出部分 token 后中途抛异常，则保留已产出内容、不再补兜底——避免重复正文；本计划采用「中途异常保留已产出」，测试用「一上来就抛」覆盖回退路径。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_stream_retrieval.py tests/test_api_stream.py tests/test_api_session.py tests/test_report_chunks.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: PASS（新 3 + 现有流式/session/chunks 全绿）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/api.py tests/test_api_stream_retrieval.py
git commit -m "功能：流式端点接入 DeepSeek 呈现(结论后端硬发+无key/异常回退确定性)"
```

---

### Task 3: Neo4j 兜底密码 + 启动日志

**Files:**
- Modify: `src/deepresearch_agent/neo4j_backend.py`
- Modify: `src/deepresearch_agent/api.py`
- Test: `tests/test_neo4j_backend_env.py`

**Interfaces:**
- Modifies: `Neo4jBackend.from_env`（默认密码 `devpassword`）。
- Produces: `create_app` 启动时经 `logging` 打印 graph 后端连通性。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_neo4j_backend_env.py`：

```python
import deepresearch_agent.neo4j_backend as nb


def test_from_env_defaults_password_devpassword(monkeypatch):
    captured = {}

    class _FakeDriver:
        def verify_connectivity(self): pass

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth): captured["uri"] = uri; captured["auth"] = auth; return _FakeDriver()

    import sys, types
    fake_neo4j = types.ModuleType("neo4j")
    fake_neo4j.GraphDatabase = _FakeGraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    nb.Neo4jBackend.from_env()
    assert captured["auth"] == ("neo4j", "devpassword")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend_env.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: FAIL（默认密码为 `""`，`auth == ("neo4j", "")`）

- [ ] **Step 3: 实现**

改 `neo4j_backend.py` 的 `from_env`（neo4j_backend.py:25）：

```python
        password = os.environ.get("NEO4J_PASSWORD", "devpassword")
```

在 `api.py` import 区加：

```python
import logging
```

在 `create_app` 内、构建缓存图机制处（若本模块尚无 graph 注入，则在 `store = ...` 之后）加启动探测日志。**注**：本 spec 的 scope/graph 注入若尚未在 `create_app` 落地（前序模块未合并），本步只加「按环境探测 Neo4j 连通性并记日志」：

```python
    logger = logging.getLogger("deepresearch.api")
    try:
        from deepresearch_agent.neo4j_backend import Neo4jBackend
        Neo4jBackend.from_env()
        logger.info("[graph] Neo4j backend: connected")
    except Exception:
        logger.info("[graph] Neo4j backend: unavailable (fallback to scope)")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_neo4j_backend_env.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream`
Expected: PASS（1 项）

- [ ] **Step 5: 提交**

```powershell
git add src/deepresearch_agent/neo4j_backend.py src/deepresearch_agent/api.py tests/test_neo4j_backend_env.py
git commit -m "修复：Neo4j from_env 兜底密码 devpassword + create_app 启动打印连通性(不再静默降级)"
```

---

### Task 4: 全套回归 + 文档同步 + 真链路手验

**Files:**
- Modify: `CLAUDE.md`、`docs/architecture.md`、`docs/project-memory.md`

- [ ] **Step 1: 全套回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-llmstream-full`
Expected: 全绿（CI 零 key 走兜底；`@pytest.mark.llm` 默认排除）

- [ ] **Step 2: 更新文档**

- `CLAUDE.md`「运行 Agent」Web 界面注释：网页流式呈现现由 DeepSeek 生成（有 `DEEPSEEK_API_KEY` 用 LLM，无 key 回退确定性文本），结论后端硬发不受 LLM 影响；Neo4j 默认密码 `devpassword`。
- `docs/architecture.md` 接口/记忆小节：`/session/turn/stream` 呈现层走 `build_deepseek_polisher`（约束 prompt、只呈现定稿报告、结论硬发纵深防御）；`Neo4jBackend.from_env` 兜底密码 + 启动日志。
- `docs/project-memory.md` 追加条目：网页 LLM 流式呈现（DeepSeek）+ 红线豁免范围扩大（呈现层）+ Neo4j 兜底。

- [ ] **Step 3: 真链路手验（用户本地，可选）**

```powershell
docker compose up -d
$env:NEO4J_PASSWORD="devpassword"   # 兜底后可省
$env:DEEPSEEK_API_KEY="<key>"
.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload
```
浏览器 `http://127.0.0.1:8000/`：命名/能力/关系三类查询，验证 DeepSeek 流式正文 + 结论句在场；`unset DEEPSEEK_API_KEY` 重启验证兜底文本。

- [ ] **Step 4: 提交**

```powershell
git add CLAUDE.md docs/architecture.md docs/project-memory.md
git commit -m "文档：同步网页 LLM 流式呈现(DeepSeek+结论硬发+Neo4j 兜底)到架构/记忆/CLAUDE"
```

---

## 收尾

四个 Task 后用 **superpowers:finishing-a-development-branch**：全套 `pytest`（应全绿）→ present 合并选项。

## Self-Review

- **Spec 覆盖**：polisher+prompt（Task1）、API 接入+结论硬发+无key/异常回退（Task2）、Neo4j 兜底+启动日志（Task3）、回归+文档（Task4）均有落点。graph_viz/`/research`/Ollama 按 spec 不做。
- **占位符**：每步含完整代码与命令，无 TBD。
- **类型一致**：`build_deepseek_polisher(api_key,model,base_url,client)->Callable|None`、`stream_presentation(report_type,report)->Iterator[str]`、`_render_report_for_llm(report_type,report)->str`、`_conclusion_line(report)->str`、`create_app(...,polisher="__default__")`、`_resolve_report`/`_report_message_chunks(report,report_type)`/`_RECOMMENDATION_TEXT`（已存在）跨 Task 一致；报告字段与 `state.py` 对齐；`from_env` 密码默认 `devpassword`。
- **降级**：无 key（polisher=None）与 polisher 一上来抛异常都回退 `_report_message_chunks`；中途异常保留已产出（避免重复正文）；结论句任何路径都硬发。
