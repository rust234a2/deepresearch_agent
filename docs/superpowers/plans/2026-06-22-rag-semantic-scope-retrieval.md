# RAG 语义经营范围检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为采购研究增加“按经营内容跨企业语义检索”能力——给一段能力描述，在全库企业经营范围条款上做中文语义检索，返回企业 + 命中条款 + 评分。

**Architecture:** 新增 `rag/` 包承载检索子系统：条款感知切块 → 本地 `bge-small-zh-v1.5` 嵌入 → FAISS 进程内索引 → `ScopeRetriever` → 工具与 CLI。SQLite 升 schema v2 存 chunk 与向量，FAISS 文件为可重建派生索引。数据层（cleaning/models/repository）仅做读侧扩展，不改现有行为。

**Tech Stack:** Python 3.11、SQLite、FAISS（`faiss-cpu`）、sentence-transformers（`bge-small-zh-v1.5`）、numpy、Pydantic、pytest。

## Global Constraints

- 解释器固定用工作区 conda 环境：`.\.conda-env\python.exe`，不新建 venv。
- 测试默认不加载真模型、不触网；重依赖测试用 `pytest.mark.slow` 标记并默认排除。
- 受限工商数据本地化：嵌入用本地模型，不接外部 API，不引服务型组件（无 Qdrant）。
- `faiss-cpu` / `sentence-transformers` / `numpy` 仅放入可选 extra `[rag]`；核心建库、Repository、现有 Agent/CLI/API 路径不依赖它们。
- 经营范围条款按原文返回，不推断结构化产品、产能、认证或风险。
- 每个 Task 末尾提交一次，提交信息用中文。
- `SCHEMA_VERSION` 当前为 1，本计划升到 2；改 schema 必须同步 `SCHEMA_VERSION` 与 `_create_schema`。

---

## File Structure

新建：
- `src/deepresearch_agent/rag/__init__.py` — 空包标记。
- `src/deepresearch_agent/rag/chunking.py` — `ScopeChunk`、`chunk_business_scope`。
- `src/deepresearch_agent/rag/embedding.py` — `Embedder` 协议、`FakeEmbedder`、`BgeEmbedder`、`BGE_QUERY_INSTRUCTION`。
- `src/deepresearch_agent/rag/vector_store.py` — `VectorStore` 协议。
- `src/deepresearch_agent/rag/faiss_store.py` — `FaissVectorStore`。
- `src/deepresearch_agent/rag/retriever.py` — `ScopeHit`、`ScopeIndexMismatchError`、`ScopeRetriever`、`load_scope_retriever`。
- `src/deepresearch_agent/rag/tools.py` — `build_scope_tool_registry`。
- `src/deepresearch_agent/rag/cli.py` — `main`、`render_hits`。
- `scripts/build_scope_index.py` — `build_scope_index`、`main`。
- 测试：`tests/test_rag_chunking.py`、`tests/test_rag_embedding.py`、`tests/test_rag_faiss_store.py`、`tests/test_rag_retriever.py`、`tests/test_build_scope_index.py`、`tests/test_rag_tools.py`、`tests/test_rag_cli.py`、`tests/test_rag_integration.py`（slow）。

修改：
- `pyproject.toml` — 加 `[rag]` extra、pytest `slow` marker、默认排除 slow。
- `src/deepresearch_agent/company_database.py` — schema v2、新表、写 chunk 行、`SCHEMA_VERSION=2`。
- `src/deepresearch_agent/company_models.py` — `ScopeChunkRecord`、`ScopeIndexMetadata`。
- `src/deepresearch_agent/company_repository.py` — `get_scope_chunks`、`get_scope_index_metadata`。
- `tests/test_company_database.py`、`tests/test_company_repository.py` — 适配 v2。

删除：
- `src/deepresearch_agent/retrieval/`（`local.py` 及包目录）、`tests/test_retrieval.py`。

---

## Task 1: 依赖与 pytest 配置

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: 可选 extra `[rag]`（`faiss-cpu`、`sentence-transformers`、`numpy`）；pytest `slow` marker；默认运行排除 slow。

- [ ] **Step 1: 编辑 `pyproject.toml`**

在 `[project.optional-dependencies]` 中，于现有 `dev = [...]` 之后新增：

```toml
rag = [
  "faiss-cpu>=1.8.0",
  "sentence-transformers>=2.7.0",
  "numpy>=1.26.0",
]
```

把现有 `[tool.pytest.ini_options]` 整段替换为：

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q -m 'not slow'"
markers = [
  "slow: 需要重型 ML 依赖或模型下载，默认排除",
]
```

- [ ] **Step 2: 安装 faiss 与 numpy（slow 用的 sentence-transformers 留到 Task 10）**

Run: `.\.conda-env\python.exe -m pip install "faiss-cpu>=1.8.0" "numpy>=1.26.0"`
Expected: 安装成功，无错误。

- [ ] **Step 3: 验证可导入且现有套件仍绿**

Run: `.\.conda-env\python.exe -c "import faiss, numpy; print(faiss.__version__, numpy.__version__)"`
Expected: 打印版本号。

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t1`
Expected: PASS（现有全部测试通过，无 slow 被收集）。

- [ ] **Step 4: 提交**

```bash
git add pyproject.toml
git commit -m "构建：新增 rag 可选依赖与 pytest slow 标记"
```

---

## Task 2: 经营范围切块（纯函数）

**Files:**
- Create: `src/deepresearch_agent/rag/__init__.py`
- Create: `src/deepresearch_agent/rag/chunking.py`
- Test: `tests/test_rag_chunking.py`

**Interfaces:**
- Produces:
  - `ScopeChunk(section_label: str | None, ordinal: int, text: str)`（frozen dataclass）
  - `chunk_business_scope(text: str | None) -> list[ScopeChunk]`

- [ ] **Step 1: 写失败测试 `tests/test_rag_chunking.py`**

```python
from deepresearch_agent.rag.chunking import ScopeChunk, chunk_business_scope


def test_chunk_splits_items_without_section_label():
    chunks = chunk_business_scope("工业设备制造；工业设备销售。")
    assert chunks == [
        ScopeChunk(section_label=None, ordinal=0, text="工业设备制造"),
        ScopeChunk(section_label=None, ordinal=1, text="工业设备销售"),
    ]


def test_chunk_handles_sections_labels_and_disclaimer():
    text = (
        "许可项目：建设工程施工；检验检测服务"
        "（依法须经批准的项目，经相关部门批准后方可开展经营活动）"
        "***一般项目：工业设备制造、机械零件加工"
    )
    chunks = chunk_business_scope(text)
    assert chunks == [
        ScopeChunk(section_label="许可项目", ordinal=0, text="建设工程施工"),
        ScopeChunk(section_label="许可项目", ordinal=1, text="检验检测服务"),
        ScopeChunk(section_label="一般项目", ordinal=2, text="工业设备制造"),
        ScopeChunk(section_label="一般项目", ordinal=3, text="机械零件加工"),
    ]


def test_chunk_dedupes_within_section_and_drops_blanks():
    chunks = chunk_business_scope("工业设备制造；工业设备制造；；")
    assert [c.text for c in chunks] == ["工业设备制造"]


def test_chunk_returns_empty_for_missing_scope():
    assert chunk_business_scope(None) == []
    assert chunk_business_scope("   ") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_chunking.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t2`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.rag.chunking`）。

- [ ] **Step 3: 创建 `src/deepresearch_agent/rag/__init__.py`（空文件）**

```python
```

- [ ] **Step 4: 实现 `src/deepresearch_agent/rag/chunking.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass


_SECTION_SEPARATOR = "***"
_ITEM_SEPARATORS = re.compile(r"[、；;，,。]")
_LABEL_PATTERN = re.compile(r"^([^：:]{1,12})[：:]")
_DISCLAIMER_PATTERN = re.compile(r"（依法须经[^）]*）")


@dataclass(frozen=True)
class ScopeChunk:
    section_label: str | None
    ordinal: int
    text: str


def _normalize(value: str) -> str:
    return " ".join(value.split())


def chunk_business_scope(text: str | None) -> list[ScopeChunk]:
    if text is None or not text.strip():
        return []
    chunks: list[ScopeChunk] = []
    ordinal = 0
    for raw_section in text.split(_SECTION_SEPARATOR):
        section = raw_section.strip()
        if not section:
            continue
        label: str | None = None
        match = _LABEL_PATTERN.match(section)
        if match:
            label = match.group(1).strip()
            section = section[match.end():]
        section = _DISCLAIMER_PATTERN.sub("", section)
        seen: set[str] = set()
        for raw_item in _ITEM_SEPARATORS.split(section):
            item = _normalize(raw_item)
            if not item:
                continue
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            chunks.append(ScopeChunk(section_label=label, ordinal=ordinal, text=item))
            ordinal += 1
    return chunks
```

- [ ] **Step 5: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_chunking.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t2`
Expected: PASS（4 passed）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/rag/__init__.py src/deepresearch_agent/rag/chunking.py tests/test_rag_chunking.py
git commit -m "功能：增加经营范围条款感知切块"
```

---

## Task 3: SQLite schema v2 与 chunk 写入

**Files:**
- Modify: `src/deepresearch_agent/company_database.py`
- Modify: `tests/test_company_database.py:37`
- Modify: `tests/test_company_repository.py:93-100`
- Test: `tests/test_company_database.py`

**Interfaces:**
- Consumes: `chunk_business_scope`（Task 2）
- Produces: `SCHEMA_VERSION == 2`；表 `business_scope_chunks(chunk_id, unified_social_credit_code, section_label, ordinal, text, embedding)` 与 `scope_index_metadata(embedding_model, embedding_dim, normalized, chunk_count, built_at)`。

- [ ] **Step 1: 改测试 `tests/test_company_database.py`**

把 `test_build_company_database_creates_schema_indexes_and_metadata` 中 `assert connection.execute("PRAGMA user_version").fetchone()[0] == 1` 改为 `== 2`，并在该 `with` 块内（`indexes = {...}` 之前）追加：

```python
        assert connection.execute(
            "SELECT COUNT(*) FROM business_scope_chunks"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT text FROM business_scope_chunks ORDER BY ordinal"
        ).fetchall() == [("工业设备制造",), ("工业设备销售",)]
        assert connection.execute(
            "SELECT embedding FROM business_scope_chunks WHERE embedding IS NULL"
        ).fetchall() == [(None,), (None,)]
        assert connection.execute("SELECT COUNT(*) FROM scope_index_metadata").fetchone()[0] == 0
```

- [ ] **Step 2: 改测试 `tests/test_company_repository.py`**

把 `test_repository_rejects_unsupported_schema_version` 中 `connection.execute("PRAGMA user_version = 2")` 改为 `connection.execute("PRAGMA user_version = 99")`，把 `match="expected 1"` 改为 `match="expected 2"`。

- [ ] **Step 3: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py::test_build_company_database_creates_schema_indexes_and_metadata -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t3`
Expected: FAIL（user_version 仍为 1 且无 `business_scope_chunks` 表）。

- [ ] **Step 4: 改 `src/deepresearch_agent/company_database.py`**

顶部 import 处增加：

```python
from deepresearch_agent.rag.chunking import chunk_business_scope
```

把 `SCHEMA_VERSION = 1` 改为 `SCHEMA_VERSION = 2`。

在 `_create_schema` 的 `connection.executescript(""" ... """)` 内、`CREATE INDEX idx_company_aliases_normalized ...;` 之后、字符串闭合 `"""` 之前，追加：

```sql
        CREATE TABLE business_scope_chunks (
            chunk_id INTEGER PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL
                REFERENCES companies(unified_social_credit_code),
            section_label TEXT,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB
        );
        CREATE INDEX idx_scope_chunks_company
            ON business_scope_chunks(unified_social_credit_code);
        CREATE TABLE scope_index_metadata (
            embedding_model TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            normalized INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            built_at TEXT NOT NULL
        );
```

在 `_build_atomic_database` 的事务块内，于 `_insert_contacts(connection, contacts)` 之后、`INSERT INTO import_metadata ...` 之前，加一行：

```python
            _insert_scope_chunks(connection, companies)
```

在 `_insert_contacts` 函数定义之后，新增函数：

```python
def _insert_scope_chunks(
    connection: sqlite3.Connection,
    companies: list[_CompanySourceRow],
) -> None:
    for item in companies:
        code = item.profile.unified_social_credit_code
        for chunk in chunk_business_scope(item.profile.business_scope):
            connection.execute(
                "INSERT INTO business_scope_chunks "
                "(unified_social_credit_code, section_label, ordinal, text, embedding) "
                "VALUES (?, ?, ?, ?, NULL)",
                (code, chunk.section_label, chunk.ordinal, chunk.text),
            )
```

- [ ] **Step 5: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_database.py tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t3`
Expected: PASS。

- [ ] **Step 6: 跑全套确认无回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t3b`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/deepresearch_agent/company_database.py tests/test_company_database.py tests/test_company_repository.py
git commit -m "功能：schema 升 v2 并在建库时写经营范围 chunk"
```

---

## Task 4: 嵌入接口与 FakeEmbedder

**Files:**
- Create: `src/deepresearch_agent/rag/embedding.py`
- Test: `tests/test_rag_embedding.py`

**Interfaces:**
- Produces:
  - `BGE_QUERY_INSTRUCTION: str`
  - `Embedder`（Protocol，属性 `model_name: str`、`dimension: int`，方法 `embed_documents(list[str]) -> np.ndarray`、`embed_query(str) -> np.ndarray`）
  - `FakeEmbedder`（`model_name="fake-embedder"`、`dimension=8`）
  - `BgeEmbedder`（`model_name="bge-small-zh-v1.5"`、`dimension=512`，懒加载 sentence-transformers）

- [ ] **Step 1: 写失败测试 `tests/test_rag_embedding.py`**

```python
import numpy as np

from deepresearch_agent.rag.embedding import FakeEmbedder


def test_fake_embedder_is_deterministic_and_normalized():
    embedder = FakeEmbedder()
    docs = embedder.embed_documents(["工业设备制造", "工业设备销售"])
    assert docs.shape == (2, 8)
    assert docs.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), [1.0, 1.0], rtol=1e-5)
    again = embedder.embed_documents(["工业设备制造"])
    np.testing.assert_allclose(docs[0], again[0], rtol=1e-6)


def test_fake_embedder_query_matches_same_document_text():
    embedder = FakeEmbedder()
    query = embedder.embed_query("工业设备制造")
    doc = embedder.embed_documents(["工业设备制造"])[0]
    assert float(query @ doc) > 0.999
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_embedding.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t4`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/rag/embedding.py`**

```python
from __future__ import annotations

from typing import Protocol

import numpy as np


BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class FakeEmbedder:
    """Deterministic, dependency-free embedder for tests."""

    model_name = "fake-embedder"
    dimension = 8

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = np.array([self._vector(text) for text in texts], dtype=np.float32)
        return _l2_normalize(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for index, char in enumerate(text):
            vector[index % self.dimension] += (ord(char) % 17) + 1.0
        return vector


class BgeEmbedder:
    """Local bge-small-zh-v1.5 embedder via sentence-transformers."""

    model_name = "bge-small-zh-v1.5"
    dimension = 512

    def __init__(self, model_path: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_path)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vectors = self._model.encode(
            [BGE_QUERY_INSTRUCTION + text], normalize_embeddings=True
        )
        return np.asarray(vectors, dtype=np.float32)[0]
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_embedding.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t4`
Expected: PASS（2 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/rag/embedding.py tests/test_rag_embedding.py
git commit -m "功能：增加嵌入接口与确定性 FakeEmbedder"
```

---

## Task 5: VectorStore 接口与 FaissVectorStore

**Files:**
- Create: `src/deepresearch_agent/rag/vector_store.py`
- Create: `src/deepresearch_agent/rag/faiss_store.py`
- Test: `tests/test_rag_faiss_store.py`

**Interfaces:**
- Produces:
  - `VectorStore`（Protocol：`add(ids: list[int], vectors: np.ndarray) -> None`、`search(query: np.ndarray, k: int) -> list[tuple[int, float]]`、`save(path: Path) -> None`）
  - `FaissVectorStore(dimension: int, index=None)`；类方法 `load(path: Path, dimension: int) -> FaissVectorStore`

- [ ] **Step 1: 写失败测试 `tests/test_rag_faiss_store.py`**

```python
import numpy as np

from deepresearch_agent.rag.faiss_store import FaissVectorStore


def _unit(values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_faiss_store_returns_nearest_ids_by_inner_product():
    store = FaissVectorStore(dimension=2)
    store.add([10, 20], np.array([_unit([1, 0]), _unit([0, 1])], dtype=np.float32))

    results = store.search(_unit([1, 0]), k=2)

    assert results[0][0] == 10
    assert results[0][1] > 0.99
    assert {chunk_id for chunk_id, _ in results} == {10, 20}


def test_faiss_store_save_and_load_roundtrip(tmp_path):
    store = FaissVectorStore(dimension=2)
    store.add([7], np.array([_unit([1, 1])], dtype=np.float32))
    path = tmp_path / "index.faiss"
    store.save(path)

    loaded = FaissVectorStore.load(path, dimension=2)

    assert loaded.search(_unit([1, 1]), k=1)[0][0] == 7
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_faiss_store.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t5`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/rag/vector_store.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np


class VectorStore(Protocol):
    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]: ...

    def save(self, path: Path) -> None: ...
```

- [ ] **Step 4: 实现 `src/deepresearch_agent/rag/faiss_store.py`**

```python
from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


class FaissVectorStore:
    def __init__(self, dimension: int, index: "faiss.Index | None" = None) -> None:
        self.dimension = dimension
        self._index = (
            index
            if index is not None
            else faiss.IndexIDMap(faiss.IndexFlatIP(dimension))
        )

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        self._index.add_with_ids(
            np.ascontiguousarray(vectors, dtype=np.float32),
            np.asarray(ids, dtype=np.int64),
        )

    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]:
        query2d = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
        scores, ids = self._index.search(query2d, k)
        return [
            (int(chunk_id), float(score))
            for chunk_id, score in zip(ids[0], scores[0])
            if chunk_id != -1
        ]

    def save(self, path: Path) -> None:
        faiss.write_index(self._index, str(path))

    @classmethod
    def load(cls, path: Path, dimension: int) -> "FaissVectorStore":
        return cls(dimension=dimension, index=faiss.read_index(str(path)))
```

- [ ] **Step 5: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_faiss_store.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t5`
Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/rag/vector_store.py src/deepresearch_agent/rag/faiss_store.py tests/test_rag_faiss_store.py
git commit -m "功能：增加 VectorStore 接口与 FAISS 后端"
```

---

## Task 6: Repository 读侧扩展（chunk 与索引元数据）

**Files:**
- Modify: `src/deepresearch_agent/company_models.py`
- Modify: `src/deepresearch_agent/company_repository.py`
- Test: `tests/test_company_repository.py`

**Interfaces:**
- Produces:
  - `ScopeChunkRecord(chunk_id, unified_social_credit_code, legal_name, section_label, text)`
  - `ScopeIndexMetadata(embedding_model, embedding_dim, normalized, chunk_count, built_at)`
  - `CompanyRepository.get_scope_chunks(chunk_ids: list[int]) -> dict[int, ScopeChunkRecord]`
  - `CompanyRepository.get_scope_index_metadata() -> ScopeIndexMetadata | None`

- [ ] **Step 1: 写失败测试，追加到 `tests/test_company_repository.py` 末尾**

```python
def test_repository_returns_scope_chunks_by_id(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))
    with sqlite3.connect(_build_database(tmp_path)) as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT chunk_id FROM business_scope_chunks ORDER BY chunk_id"
        )]

    records = repository.get_scope_chunks(ids)

    assert set(records) == set(ids)
    first = records[ids[0]]
    assert first.legal_name == "示例科技股份有限公司"
    assert first.text in {"工业设备制造", "工业设备销售"}
    assert repository.get_scope_chunks([]) == {}


def test_repository_scope_index_metadata_absent_before_build(tmp_path):
    repository = CompanyRepository(_build_database(tmp_path))

    assert repository.get_scope_index_metadata() is None
```

注意：`_build_database` 每次调用都新建库；上面测试用同一个 fixture 内容，chunk_id 稳定，可分别取一次。

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py::test_repository_returns_scope_chunks_by_id tests/test_company_repository.py::test_repository_scope_index_metadata_absent_before_build -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t6`
Expected: FAIL（`AttributeError: 'CompanyRepository' object has no attribute 'get_scope_chunks'`）。

- [ ] **Step 3: 在 `src/deepresearch_agent/company_models.py` 末尾新增模型**

```python
class ScopeChunkRecord(BaseModel):
    chunk_id: int
    unified_social_credit_code: str
    legal_name: str
    section_label: str | None = None
    text: str


class ScopeIndexMetadata(BaseModel):
    embedding_model: str
    embedding_dim: int
    normalized: bool
    chunk_count: int
    built_at: str
```

- [ ] **Step 4: 在 `src/deepresearch_agent/company_repository.py` 增加方法与 import**

把顶部 `from deepresearch_agent.company_models import (...)` 中追加 `ScopeChunkRecord`、`ScopeIndexMetadata`。

在 `resolve_text` 方法之后、`CompanyRepository` 类内新增：

```python
    def get_scope_chunks(self, chunk_ids: list[int]) -> dict[int, "ScopeChunkRecord"]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunks.chunk_id, chunks.unified_social_credit_code, "
                "companies.legal_name, chunks.section_label, chunks.text "
                "FROM business_scope_chunks AS chunks "
                "JOIN companies USING (unified_social_credit_code) "
                f"WHERE chunks.chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        return {
            row["chunk_id"]: ScopeChunkRecord(
                chunk_id=row["chunk_id"],
                unified_social_credit_code=row["unified_social_credit_code"],
                legal_name=row["legal_name"],
                section_label=row["section_label"],
                text=row["text"],
            )
            for row in rows
        }

    def get_scope_index_metadata(self) -> "ScopeIndexMetadata | None":
        with self._connect() as connection:
            row = connection.execute(
                "SELECT embedding_model, embedding_dim, normalized, chunk_count, built_at "
                "FROM scope_index_metadata LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ScopeIndexMetadata(
            embedding_model=row["embedding_model"],
            embedding_dim=row["embedding_dim"],
            normalized=bool(row["normalized"]),
            chunk_count=row["chunk_count"],
            built_at=row["built_at"],
        )
```

- [ ] **Step 5: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t6`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/deepresearch_agent/company_models.py src/deepresearch_agent/company_repository.py tests/test_company_repository.py
git commit -m "功能：Repository 增加 chunk 与索引元数据读取"
```

---

## Task 7: 索引构建脚本 build_scope_index

**Files:**
- Create: `scripts/build_scope_index.py`
- Test: `tests/test_build_scope_index.py`

**Interfaces:**
- Consumes: `FakeEmbedder`/`BgeEmbedder`（Task 4）、`FaissVectorStore`（Task 5）、schema v2（Task 3）
- Produces: `build_scope_index(database_path, index_path, embedder, *, now=None) -> dict`（回写 `embedding`、写 `scope_index_metadata`、生成 FAISS 文件，返回 `{"chunks": int}`）

- [ ] **Step 1: 写失败测试 `tests/test_build_scope_index.py`**

```python
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


def test_build_scope_index_writes_embeddings_metadata_and_faiss(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"

    summary = build_scope_index(
        company_database_path,
        index_path,
        FakeEmbedder(),
        now="2026-06-22T00:00:00+00:00",
    )

    assert summary == {"chunks": 2}
    assert index_path.exists()
    with sqlite3.connect(company_database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM business_scope_chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0] == 2
        meta = connection.execute(
            "SELECT embedding_model, embedding_dim, normalized, chunk_count, built_at "
            "FROM scope_index_metadata"
        ).fetchone()
        assert meta == ("fake-embedder", 8, 1, 2, "2026-06-22T00:00:00+00:00")
        ids = [row[0] for row in connection.execute(
            "SELECT chunk_id FROM business_scope_chunks ORDER BY chunk_id"
        )]

    store = FaissVectorStore.load(index_path, dimension=8)
    query = FakeEmbedder().embed_query("工业设备制造")
    assert store.search(query, k=1)[0][0] in ids
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_build_scope_index.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t7`
Expected: FAIL（`ModuleNotFoundError: build_scope_index`）。

- [ ] **Step 3: 实现 `scripts/build_scope_index.py`**

```python
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import numpy as np

from deepresearch_agent.rag.embedding import BgeEmbedder, Embedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


def build_scope_index(
    database_path: str | Path,
    index_path: str | Path,
    embedder: Embedder,
    *,
    now: str | None = None,
) -> dict[str, int]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    index_path = Path(index_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT chunk_id, text FROM business_scope_chunks ORDER BY chunk_id"
        ).fetchall()
        ids = [row["chunk_id"] for row in rows]
        texts = [row["text"] for row in rows]
        vectors = (
            embedder.embed_documents(texts)
            if texts
            else np.zeros((0, embedder.dimension), dtype=np.float32)
        )
        with connection:
            for chunk_id, vector in zip(ids, vectors):
                connection.execute(
                    "UPDATE business_scope_chunks SET embedding = ? WHERE chunk_id = ?",
                    (np.asarray(vector, dtype=np.float32).tobytes(), chunk_id),
                )
            connection.execute("DELETE FROM scope_index_metadata")
            connection.execute(
                "INSERT INTO scope_index_metadata VALUES (?, ?, ?, ?, ?)",
                (embedder.model_name, embedder.dimension, 1, len(ids), timestamp),
            )
        store = FaissVectorStore(embedder.dimension)
        if ids:
            store.add(ids, vectors)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        store.save(index_path)
        return {"chunks": len(ids)}
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the FAISS scope index from SQLite.")
    parser.add_argument("--database", default="data/procurement/derived/companies.sqlite3")
    parser.add_argument("--index", default="data/procurement/derived/scope_index.faiss")
    args = parser.parse_args(argv)
    summary = build_scope_index(Path(args.database), Path(args.index), BgeEmbedder())
    print(f"chunks={summary['chunks']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_build_scope_index.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t7`
Expected: PASS（1 passed）。

- [ ] **Step 5: 提交**

```bash
git add scripts/build_scope_index.py tests/test_build_scope_index.py
git commit -m "功能：增加 FAISS 经营范围索引构建脚本"
```

---

## Task 8: ScopeRetriever 与加载工厂

**Files:**
- Create: `src/deepresearch_agent/rag/retriever.py`
- Test: `tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: `Embedder`、`FaissVectorStore`、`CompanyRepository.get_scope_chunks`/`get_scope_index_metadata`、`build_scope_index`
- Produces:
  - `ScopeHit(unified_social_credit_code, legal_name, section_label, text, score)`（Pydantic）
  - `ScopeIndexMismatchError(RuntimeError)`
  - `ScopeRetriever(embedder, vector_store, repository)`，`search(query: str, k: int = 10) -> list[ScopeHit]`
  - `load_scope_retriever(database_path, index_path, embedder) -> ScopeRetriever`

- [ ] **Step 1: 写失败测试 `tests/test_rag_retriever.py`**

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.retriever import (
    ScopeIndexMismatchError,
    load_scope_retriever,
)


def _prepare(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")
    return index_path


def test_retriever_returns_ranked_hits(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())

    hits = retriever.search("工业设备制造", k=5)

    assert hits[0].text == "工业设备制造"
    assert hits[0].legal_name == "示例科技股份有限公司"
    assert hits[0].score > 0.99
    assert len(hits) <= 5


def test_retriever_respects_k_limit(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())

    assert len(retriever.search("工业设备", k=1)) == 1


class _OtherEmbedder(FakeEmbedder):
    model_name = "other-model"


def test_retriever_rejects_model_mismatch(company_database_path, tmp_path):
    index_path = _prepare(company_database_path, tmp_path)

    with pytest.raises(ScopeIndexMismatchError, match="rebuild"):
        load_scope_retriever(company_database_path, index_path, _OtherEmbedder())
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_retriever.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t8`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.rag.retriever`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/rag/retriever.py`**

```python
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.rag.embedding import Embedder
from deepresearch_agent.rag.faiss_store import FaissVectorStore


class ScopeHit(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    section_label: str | None
    text: str
    score: float


class ScopeIndexMismatchError(RuntimeError):
    pass


class ScopeRetriever:
    def __init__(
        self,
        embedder: Embedder,
        vector_store: FaissVectorStore,
        repository: CompanyRepository,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository

    def search(self, query: str, k: int = 10) -> list[ScopeHit]:
        query_vector = self.embedder.embed_query(query)
        matches = self.vector_store.search(query_vector, k)
        records = self.repository.get_scope_chunks([chunk_id for chunk_id, _ in matches])
        hits: list[ScopeHit] = []
        for chunk_id, score in matches:
            record = records.get(chunk_id)
            if record is None:
                continue
            hits.append(
                ScopeHit(
                    unified_social_credit_code=record.unified_social_credit_code,
                    legal_name=record.legal_name,
                    section_label=record.section_label,
                    text=record.text,
                    score=score,
                )
            )
        return hits


def load_scope_retriever(
    database_path: str | Path,
    index_path: str | Path,
    embedder: Embedder,
) -> ScopeRetriever:
    repository = CompanyRepository(database_path)
    metadata = repository.get_scope_index_metadata()
    if metadata is None:
        raise ScopeIndexMismatchError(
            "scope index metadata missing; run scripts/build_scope_index.py to rebuild"
        )
    if (
        metadata.embedding_model != embedder.model_name
        or metadata.embedding_dim != embedder.dimension
    ):
        raise ScopeIndexMismatchError(
            f"index built with {metadata.embedding_model}/{metadata.embedding_dim}, "
            f"query uses {embedder.model_name}/{embedder.dimension}; rebuild the index"
        )
    if not Path(index_path).exists():
        raise ScopeIndexMismatchError(
            f"FAISS index not found: {index_path}; run scripts/build_scope_index.py"
        )
    store = FaissVectorStore.load(Path(index_path), metadata.embedding_dim)
    return ScopeRetriever(embedder, store, repository)
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_retriever.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t8`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add src/deepresearch_agent/rag/retriever.py tests/test_rag_retriever.py
git commit -m "功能：增加经营范围语义检索器与加载工厂"
```

---

## Task 9: 检索工具与 CLI

**Files:**
- Create: `src/deepresearch_agent/rag/tools.py`
- Create: `src/deepresearch_agent/rag/cli.py`
- Test: `tests/test_rag_tools.py`
- Test: `tests/test_rag_cli.py`

**Interfaces:**
- Consumes: `ScopeRetriever`、`load_scope_retriever`、`ScopeHit`（Task 8）、`ToolRegistry`/`RegisteredTool`（`tools/base.py`）
- Produces:
  - `build_scope_tool_registry(retriever) -> ToolRegistry`（工具名 `search_company_scope`）
  - `cli.render_hits(query: str, hits: list[ScopeHit]) -> rich.table.Table`
  - `cli.main(argv=None, embedder=None) -> None`

- [ ] **Step 1: 写失败测试 `tests/test_rag_tools.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag.embedding import FakeEmbedder
from deepresearch_agent.rag.retriever import load_scope_retriever
from deepresearch_agent.rag.tools import build_scope_tool_registry


def test_scope_tool_returns_structured_hits(company_database_path, tmp_path):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")
    retriever = load_scope_retriever(company_database_path, index_path, FakeEmbedder())
    registry = build_scope_tool_registry(retriever)

    result = registry.run("search_company_scope", {"query": "工业设备制造", "k": 3})

    assert result.status == "ok"
    assert result.permission_tier == "read_private"
    assert result.data["hits"][0]["text"] == "工业设备制造"
    assert result.data["hits"][0]["legal_name"] == "示例科技股份有限公司"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_tools.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t9`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.rag.tools`）。

- [ ] **Step 3: 实现 `src/deepresearch_agent/rag/tools.py`**

```python
from __future__ import annotations

from deepresearch_agent.rag.retriever import ScopeRetriever
from deepresearch_agent.tools.base import RegisteredTool, ToolRegistry


def build_scope_tool_registry(retriever: ScopeRetriever) -> ToolRegistry:
    registry = ToolRegistry()

    def search(args: dict) -> dict:
        hits = retriever.search(args["query"], args.get("k", 10))
        return {"hits": [hit.model_dump() for hit in hits]}

    registry.register(
        RegisteredTool(
            name="search_company_scope",
            description="Semantic search over company business scope clauses.",
            permission_tier="read_private",
            handler=search,
        )
    )
    return registry
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_tools.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t9`
Expected: PASS（1 passed）。

- [ ] **Step 5: 写失败测试 `tests/test_rag_cli.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402

from deepresearch_agent.rag import cli
from deepresearch_agent.rag.embedding import FakeEmbedder


def test_cli_prints_ranked_company_and_clause(company_database_path, tmp_path, capsys):
    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, FakeEmbedder(), now="2026-06-22T00:00:00+00:00")

    cli.main(
        [
            "工业设备制造",
            "--k", "3",
            "--database", str(company_database_path),
            "--index", str(index_path),
        ],
        embedder=FakeEmbedder(),
    )

    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "工业设备制造" in out
```

- [ ] **Step 6: 运行确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t9b`
Expected: FAIL（`ModuleNotFoundError: deepresearch_agent.rag.cli`）。

- [ ] **Step 7: 实现 `src/deepresearch_agent/rag/cli.py`**

```python
from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from deepresearch_agent.rag.embedding import BgeEmbedder, Embedder
from deepresearch_agent.rag.retriever import ScopeHit, load_scope_retriever


def render_hits(query: str, hits: list[ScopeHit]) -> Table:
    table = Table(title=f"Scope search: {query}")
    table.add_column("Company")
    table.add_column("Section")
    table.add_column("Clause")
    table.add_column("Score")
    for hit in hits:
        table.add_row(hit.legal_name, hit.section_label or "", hit.text, f"{hit.score:.3f}")
    return table


def main(argv: list[str] | None = None, embedder: Embedder | None = None) -> None:
    parser = argparse.ArgumentParser(description="Semantic search over company business scope.")
    parser.add_argument("query", help="Capability description to search for.")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--database", default="data/procurement/derived/companies.sqlite3")
    parser.add_argument("--index", default="data/procurement/derived/scope_index.faiss")
    args = parser.parse_args(argv)

    used_embedder = embedder if embedder is not None else BgeEmbedder()
    retriever = load_scope_retriever(Path(args.database), Path(args.index), used_embedder)
    hits = retriever.search(args.query, args.k)
    Console().print(render_hits(args.query, hits))


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: 运行确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_cli.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t9b`
Expected: PASS（1 passed）。

- [ ] **Step 9: 提交**

```bash
git add src/deepresearch_agent/rag/tools.py src/deepresearch_agent/rag/cli.py tests/test_rag_tools.py tests/test_rag_cli.py
git commit -m "功能：增加经营范围检索工具与 CLI"
```

---

## Task 10: 清理旧检索器、慢速集成测试与文档

**Files:**
- Delete: `src/deepresearch_agent/retrieval/local.py`（及 `retrieval/` 目录与其 `__init__.py` 若存在）
- Delete: `tests/test_retrieval.py`
- Create: `tests/test_rag_integration.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `BgeEmbedder`、`build_scope_index`、`load_scope_retriever`

- [ ] **Step 1: 删除被取代的旧检索器与测试**

```bash
git rm src/deepresearch_agent/retrieval/local.py tests/test_retrieval.py
```

若 `src/deepresearch_agent/retrieval/__init__.py` 存在也一并删除：

```bash
git rm src/deepresearch_agent/retrieval/__init__.py
```

- [ ] **Step 2: 运行全套确认无残留引用**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t10`
Expected: PASS（无 `ModuleNotFoundError`；`LocalDocumentRetriever` 已无引用）。

- [ ] **Step 3: 安装慢速测试依赖**

Run: `.\.conda-env\python.exe -m pip install "sentence-transformers>=2.7.0"`
Expected: 安装成功（含 torch）。

- [ ] **Step 4: 写慢速集成测试 `tests/test_rag_integration.py`**

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_scope_index import build_scope_index  # noqa: E402


@pytest.mark.slow
def test_bge_semantic_recall_end_to_end(company_database_path, tmp_path):
    from deepresearch_agent.rag.embedding import BgeEmbedder
    from deepresearch_agent.rag.retriever import load_scope_retriever

    embedder = BgeEmbedder()
    assert embedder.dimension == 512

    index_path = tmp_path / "scope_index.faiss"
    build_scope_index(company_database_path, index_path, embedder)
    retriever = load_scope_retriever(company_database_path, index_path, embedder)

    hits = retriever.search("机械设备生产", k=2)

    assert hits
    assert hits[0].legal_name == "示例科技股份有限公司"
    assert 0.0 <= hits[0].score <= 1.0001
```

- [ ] **Step 5: 运行慢速测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_rag_integration.py -q -m slow -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t10b`
Expected: PASS（1 passed；首次会下载 bge-small-zh-v1.5 权重）。

- [ ] **Step 6: 确认默认套件排除慢速测试**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-rag-t10c`
Expected: PASS，且统计中 `test_rag_integration.py` 因 `-m 'not slow'` 被 deselect。

- [ ] **Step 7: 更新 `CLAUDE.md` 命令段**

在“数据管道”代码块的 `build_company_database.py` 之后，追加索引构建命令：

```powershell
# 4. 构建 FAISS 经营范围语义索引（需安装 .[rag] 可选依赖）
.\.conda-env\python.exe scripts/build_scope_index.py
```

在“运行 Agent”段之后新增一小节：

```markdown
语义经营范围检索（跨企业按内容找企业，需 `.[rag]` 可选依赖）：

\`\`\`powershell
.\.conda-env\python.exe -m deepresearch_agent.rag.cli "注塑成型" `
  --database data/procurement/derived/companies.sqlite3 `
  --index data/procurement/derived/scope_index.faiss
\`\`\`
```

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "功能：删除旧检索器、增加 bge 集成测试与文档"
```

---

## Self-Review

**1. Spec coverage（逐节核对）：**
- 切块规则 → Task 2 ✅
- schema v2 + 两表 + chunk 写入 → Task 3 ✅
- 两段式构建（核心建库切块、单独索引命令）→ Task 3（切块）+ Task 7（索引）✅
- 嵌入接口 + BgeEmbedder + FakeEmbedder + 查询指令前缀 → Task 4 ✅
- VectorStore 接口 + FaissVectorStore → Task 5 ✅
- Repository 读 chunk 与元数据 → Task 6 ✅
- ScopeRetriever + 模型不一致报错 + 加载工厂 → Task 8 ✅
- search_company_scope 工具 → Task 9 ✅
- 最小 CLI → Task 9 ✅
- `[rag]` extra + 依赖隔离 → Task 1 ✅
- 测试策略（默认不加载真模型、slow 集成测试）→ 各 Task + Task 10 ✅
- 删除旧 `LocalDocumentRetriever` → Task 10 ✅
- 错误处理（索引缺失/模型不一致/schema 版本）→ Task 8（前两者）+ Task 3（schema 版本沿用现有校验）✅
- 验收条件 → 由 Task 3/7/10 的断言覆盖 ✅

**2. Placeholder scan：** 无 TBD/TODO/“适当处理”；每个代码步骤含完整代码。✅

**3. Type consistency：**
- `chunk_business_scope` 返回 `list[ScopeChunk]`，Task 3/7 一致使用。
- `Embedder.model_name/dimension/embed_documents/embed_query` 在 Task 4 定义，Task 7/8/9/10 一致。
- `FaissVectorStore.add/search/save/load(path, dimension)` 在 Task 5 定义，Task 7/8 一致。
- `get_scope_chunks -> dict[int, ScopeChunkRecord]`、`get_scope_index_metadata -> ScopeIndexMetadata | None` 在 Task 6 定义，Task 8 一致。
- `ScopeHit` 字段在 Task 8 定义，Task 9 `render_hits`/工具一致。
- `build_scope_index(database_path, index_path, embedder, *, now=None)` 在 Task 7 定义，Task 8/9/10 调用签名一致。

无不一致。
```
