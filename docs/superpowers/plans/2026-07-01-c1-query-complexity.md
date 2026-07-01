# 模块 C1：查询复杂度检测实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现查询复杂度分类器：确定性启发式（核心+兜底）+ 可注入的 DeepSeek LLM 精修（只发查询、失败回退），输出 简单/中等/复杂。

**Architecture:** `query_complexity.py`（启发式 + 编排 + 模型，零 LLM 依赖）+ `llm/deepseek.py`（可选 `.[llm]` extra，懒加载 openai，客户端可注入便于测试）。

**Tech Stack:** Python 3.11、Pydantic v2、（可选）openai SDK 指向 DeepSeek、pytest。conda 解释器 `.\.conda-env\python.exe`。

## Global Constraints

- **确定性优先**：启发式永远可用即兜底；LLM 只精修，任何失败/无效/无 key → 回退启发式。
- **数据本地化**：LLM 只发查询文本，绝不发企业数据。
- **LLM 为可选 extra**：核心 `query_complexity.py` 不 import 任何 LLM 库。
- **无 schema 变更；不接编排（C2）**。
- 测试解释器：`.\.conda-env\python.exe -m pytest ... -p no:cacheprovider --basetemp=.conda-cache/pytest-c1`。每 Task 一提交，中文提交信息。

---

### Task 1: 启发式分类器 + 编排

**Files:**
- Create: `src/deepresearch_agent/query_complexity.py`
- Create: `tests/test_query_complexity.py`

**Interfaces:**
- Consumes：`CompanyRepository.resolve_text`。
- Produces：
  - `ComplexityResult(level: Literal["simple","medium","complex"], method: Literal["heuristic","llm"], reasoning: str)`。
  - `classify_heuristic(query, repository) -> ComplexityResult`。
  - `classify_complexity(query, repository, llm=None) -> ComplexityResult`（`llm: Callable[[str], str|None] | None`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_query_complexity.py`：

```python
from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.query_complexity import classify_complexity, classify_heuristic


def _repo(company_database_path):
    return CompanyRepository(company_database_path)


def test_heuristic_named_verify_is_simple(company_database_path):
    result = classify_heuristic("核验示例科技股份有限公司", _repo(company_database_path))
    assert result.level == "simple"
    assert result.method == "heuristic"


def test_heuristic_capability_is_simple(company_database_path):
    result = classify_heuristic("哪些企业能做注塑成型", _repo(company_database_path))
    assert result.level == "simple"


def test_heuristic_capability_with_relationship_is_medium(company_database_path):
    result = classify_heuristic("哪些做注塑的供应商互相关联", _repo(company_database_path))
    assert result.level == "medium"


def test_heuristic_named_with_relationship_is_complex(company_database_path):
    result = classify_heuristic(
        "示例科技股份有限公司的最终实控人是谁", _repo(company_database_path)
    )
    assert result.level == "complex"


def test_classify_complexity_uses_llm_when_valid(company_database_path):
    result = classify_complexity("随便", _repo(company_database_path), llm=lambda q: "complex")
    assert result.level == "complex"
    assert result.method == "llm"


def test_classify_complexity_falls_back_on_llm_none_invalid_or_error(company_database_path):
    repo = _repo(company_database_path)
    query = "核验示例科技股份有限公司"
    assert classify_complexity(query, repo, llm=lambda q: None).method == "heuristic"
    assert classify_complexity(query, repo, llm=lambda q: "weird").method == "heuristic"

    def boom(q):
        raise RuntimeError("llm down")

    assert classify_complexity(query, repo, llm=boom).method == "heuristic"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_query_complexity.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c1`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.query_complexity'`。

- [ ] **Step 3: 写 `query_complexity.py`**

创建 `src/deepresearch_agent/query_complexity.py`：

```python
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel

from deepresearch_agent.company_repository import CompanyRepository


RELATIONSHIP_KEYWORDS = (
    "控制人",
    "实控人",
    "实际控制",
    "控股",
    "母公司",
    "子公司",
    "股东",
    "持股",
    "持有",
    "投资",
    "关联",
    "关系",
    "围标",
    "串标",
    "穿透",
    "背后",
    "一伙",
    "同一控制",
    "共同控制",
    "最终受益",
    "谁控制",
    "谁持有",
    "路径",
)

_VALID_LEVELS = {"simple", "medium", "complex"}


class ComplexityResult(BaseModel):
    level: Literal["simple", "medium", "complex"]
    method: Literal["heuristic", "llm"]
    reasoning: str


def classify_heuristic(query: str, repository: CompanyRepository) -> ComplexityResult:
    matched = [keyword for keyword in RELATIONSHIP_KEYWORDS if keyword in query]
    has_relationship = bool(matched)
    has_entity = repository.resolve_text(query).status in {"resolved", "ambiguous"}
    if has_relationship and has_entity:
        return ComplexityResult(
            level="complex",
            method="heuristic",
            reasoning=f"含关系关键词『{matched[0]}』且指名企业，需多跳图检索",
        )
    if has_relationship:
        return ComplexityResult(
            level="medium",
            method="heuristic",
            reasoning=f"含关系关键词『{matched[0]}』但未指名企业，需能力检索+图融合",
        )
    return ComplexityResult(
        level="simple",
        method="heuristic",
        reasoning="无关系信号，纯核验或能力检索",
    )


def classify_complexity(
    query: str,
    repository: CompanyRepository,
    llm: Callable[[str], str | None] | None = None,
) -> ComplexityResult:
    if llm is not None:
        try:
            level = llm(query)
        except Exception:
            level = None
        if level in _VALID_LEVELS:
            return ComplexityResult(level=level, method="llm", reasoning="LLM 分类")
    return classify_heuristic(query, repository)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_query_complexity.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c1`
Expected: PASS（6 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/query_complexity.py tests/test_query_complexity.py
git commit -m "功能：C1 查询复杂度启发式分类器与 LLM 兜底编排"
```

---

### Task 2: DeepSeek LLM 分类器（可选 `.[llm]`）

**Files:**
- Create: `src/deepresearch_agent/llm/__init__.py`
- Create: `src/deepresearch_agent/llm/deepseek.py`
- Create: `tests/test_deepseek_classifier.py`
- Modify: `pyproject.toml`（`.[llm]` extra）
- Modify: `.env.example`（`DEEPSEEK_API_KEY`）

**Interfaces:**
- Consumes：（可选）`openai` SDK；`DEEPSEEK_API_KEY` 环境变量。
- Produces：`build_deepseek_classifier(api_key=None, model="deepseek-chat", base_url="https://api.deepseek.com", client=None) -> Callable[[str], str|None] | None`；`_parse_level(text) -> str|None`。返回的可调用对象即 Task 1 `classify_complexity` 的 `llm` 参数。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_deepseek_classifier.py`：

```python
from deepresearch_agent.llm.deepseek import _parse_level, build_deepseek_classifier


def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_classifier() is None


def test_parse_level_extracts_or_none():
    assert _parse_level("complex") == "complex"
    assert _parse_level(" Simple ") == "simple"
    assert _parse_level("这个查询是 medium 级") == "medium"
    assert _parse_level("垃圾输出") is None
    assert _parse_level(None) is None


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content):
        self.chat = _FakeChat(content)


def test_classify_with_injected_client_parses_level():
    classify = build_deepseek_classifier(client=_FakeClient("complex"))
    assert classify is not None
    assert classify("示例查询") == "complex"


def test_classify_with_bad_response_returns_none():
    classify = build_deepseek_classifier(client=_FakeClient("我不确定"))
    assert classify("x") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_deepseek_classifier.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c1`
Expected: FAIL —`ModuleNotFoundError: No module named 'deepresearch_agent.llm'`。

- [ ] **Step 3: 写 `llm` 包**

创建空文件 `src/deepresearch_agent/llm/__init__.py`（内容为空）。

创建 `src/deepresearch_agent/llm/deepseek.py`：

```python
from __future__ import annotations

import os
from typing import Callable


_VALID_LEVELS = ("simple", "medium", "complex")

_SYSTEM_PROMPT = (
    "你是查询复杂度分类器。只输出 simple、medium、complex 三者之一，不要任何多余文字。\n"
    "simple = 核验单个具名企业，或纯能力检索；\n"
    "medium = 按能力找企业并涉及它们之间的关系；\n"
    "complex = 某个具体企业的深层股权/控制关系（多跳穿透）。"
)


def _parse_level(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.strip().lower()
    for level in _VALID_LEVELS:
        if level in lowered:
            return level
    return None


def build_deepseek_classifier(
    api_key: str | None = None,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    client=None,
) -> Callable[[str], str | None] | None:
    if client is None:
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url)

    def classify(query: str) -> str | None:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
            )
            return _parse_level(response.choices[0].message.content)
        except Exception:
            return None

    return classify
```

- [ ] **Step 4: 加 `.[llm]` extra 与 `.env.example`**

在 `pyproject.toml` 的 `[project.optional-dependencies]` 下、`rag = [...]` 之后加：

```toml
llm = [
  "openai>=1.0",
]
```

在 `.env.example` 末尾加一行：

```
DEEPSEEK_API_KEY=
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_deepseek_classifier.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-c1`
Expected: PASS（4 passed）。

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `.\.conda-env\python.exe -m pytest -p no:cacheprovider --basetemp=.conda-cache/pytest-c1-full`
Expected: PASS（138 + 本次新增，2 deselected）。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/llm pyproject.toml .env.example tests/test_deepseek_classifier.py
git commit -m "功能：C1 DeepSeek 复杂度分类器与可选 .[llm] 依赖"
```

---

## 自检

**Spec 覆盖**：
- 三级 + 启发式规则表 → Task 1 Step 3 + 4 个启发式测试。
- 编排（LLM 优先、无效/None/异常回退）→ Task 1 Step 3 + `..._falls_back...` 测试。
- 数据本地化（只发查询）→ DeepSeek `classify` 只传 query；系统提示不含企业数据。
- DeepSeek 可选、懒加载、无 key/无 openai → None → 兜底 → Task 2 Step 3 + `test_no_api_key_returns_none`。
- 解析容错 → `_parse_level` + 测试。
- `.[llm]` extra + `DEEPSEEK_API_KEY` → Task 2 Step 4。

**Placeholder 扫描**：无 TBD/TODO；每步给完整代码与命令/预期。

**类型一致性**：`classify_complexity(..., llm: Callable[[str], str|None])` 的 `llm` 与 `build_deepseek_classifier` 返回的 `classify` 签名一致（`str -> str|None`）；`_VALID_LEVELS` 在 `query_complexity`（set）与 `deepseek`（tuple）各自定义、语义一致（simple/medium/complex）；`ComplexityResult` 字段在模型、构造、测试断言一致。
```
