# RAG 语义经营范围检索设计

日期：2026-06-22

## 目标

为采购研究增加一项当前没有的能力：**按经营内容跨企业语义检索**。给一段能力描述（如“注塑成型”“半导体封装”“检验检测”），在全库企业的经营范围条款上做中文语义检索，返回命中的企业、具体经营项条款和相似度评分。

语义检索基于本地嵌入模型 `bge-small-zh-v1.5` 和 FAISS 进程内索引，能跨同义匹配（如“注塑”召回“塑料成型”），这是词法检索（FTS5/BM25）做不到的。所有计算和数据在本机，受限工商数据不出库。

## 范围

### 包含

- 新增 `rag/` 包，仅承载检索子系统：切块、嵌入、向量索引、检索器、工具、最小入口。
- 经营范围条款感知切块（细粒度，每条经营项一个 chunk，段标签作元数据）。
- 本地中文嵌入（`bge-small-zh-v1.5`，sentence-transformers，归一化，查询端加指令前缀）。
- FAISS 进程内向量索引，落地为可重建的本地文件。
- `ScopeRetriever`：查询 → 企业 + 条款 + 评分。
- `search_company_scope` 工具，挂入工具注册表，为日后接 Agent 留口。
- 一个最小 CLI 入口，跑一次语义检索并打印结果。
- SQLite schema 升到 version 2，新增 chunk 表与索引元数据表。
- 删除 test-only 且被取代的 `retrieval/local.py` 及其测试。

### 不包含

- 不改 planner→researcher→critic→writer 流程去支持“筛选问答”端到端。Agent 端到端集成是独立的第二个 spec。
- 不接 Qdrant、不接外部嵌入 API、不引入服务型组件。
- 不做向量量化、近似索引（Flat 精确索引在当前规模足够）。
- 不从经营范围推断结构化产品、产能、认证或风险结论；条款按原文返回。
- 不触动数据层模块：`company_data_cleaning`、`company_database` 的现有职责、`company_models`、`company_repository`、`supplier_resolution` 行为不变（仅 `company_database` 增加 schema v2 与 chunk 行写入）。

## 数据流与目录

```text
data/procurement/processed/companies.csv（含 business_scope）
  -> build_company_database（v2：写企业/别名/联系方式 + 经营范围 chunk 文本，embedding 留空）
  -> data/procurement/derived/companies.sqlite3
  -> build_scope_index（重步骤：加载模型，嵌入 chunk，回写向量，建 FAISS）
  -> data/procurement/derived/scope_index.faiss（可重建、Git 忽略）
  -> ScopeRetriever / search_company_scope 工具 / CLI
```

SQLite 是事实源（含 chunk 文本与向量），FAISS 文件是从 SQLite 可重建的派生索引。两者都 Git 忽略，丢失可重建。

## 模块结构

```text
src/deepresearch_agent/rag/
  __init__.py
  chunking.py        # chunk_business_scope(text) -> list[ScopeChunk]，纯函数、无重依赖
  embedding.py       # Embedder 接口；BgeEmbedder；FakeEmbedder（测试用）
  vector_store.py    # VectorStore 接口
  faiss_store.py     # FaissVectorStore
  retriever.py       # ScopeRetriever，组装 ScopeHit
  tools.py           # build_scope_tool_registry / search_company_scope
  cli.py             # 最小命令行入口
```

依赖方向：`rag/` 的重组件（`embedding` / `faiss_store` / `retriever`）只通过 `company_repository` 读数据，不被数据层依赖。`rag/chunking` 是无重依赖的纯叶子模块，`build_company_database` 依赖它来生成 chunk 行——核心建库因此只引入纯函数，不拉 torch/faiss。

## 切块规则（`rag/chunking.py`）

纯函数 `chunk_business_scope(text: str | None) -> list[ScopeChunk]`，零依赖、完整 TDD。`ScopeChunk` 为不可变数据类：`{section_label: str | None, ordinal: int, text: str}`。

步骤：

1. 输入为 None 或空白 → 返回空列表。
2. 按 `***` 切成段。
3. 每段识别段标签：若段以 `<标签>：` 开头（如 `许可项目：`、`一般项目：`），取标签为 `section_label`，并从段文本剥去该前缀；否则 `section_label = None`。
4. 段内按 `、；,，。` 切成单条经营项。
5. 剥去标准免责括注（形如 `（依法须经批准的项目，经相关部门批准后方可开展经营活动，具体经营项目以审批结果为准）` 的整段括注）。**决策：剥离**——它是模板噪声，污染语义向量。
6. 去空白项、段内去重（按规范化文本）。
7. 跨段连续编号 `ordinal`，从 0 起。

边界与决策：

- 段标签在数据中并不总存在；缺标签时 `section_label = None`，不报错。
- 只剥“依法须经批准/审批”这类标准免责括注；经营项内部其他括注（少见）保留。
- 切块不做语义判断，纯结构切分，确定可测。

## SQLite schema v2 与构建流程

`SCHEMA_VERSION` 从 1 升到 2，`PRAGMA user_version = 2`。Repository 仍要求版本匹配，否则提示重建。

### 新增表

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

`chunk_id` 即 FAISS 内部 id。`embedding` 存归一化后的 float32 向量字节（v2 建库时为 NULL，索引构建步骤回写）。

### 两段式构建

切块便宜、无重依赖，放进核心建库；嵌入重、拉 torch，单独成命令。核心建库保持依赖轻。

- `build_company_database`（扩展）：建 v2 schema → 写 companies/aliases/contacts（不变）→ 对每家企业调用 `chunk_business_scope`，写入 `business_scope_chunks`（`embedding` 为 NULL）→ `scope_index_metadata` 暂空 → 原子替换。仅依赖 `rag/chunking.py`（纯函数）。
- `scripts/build_scope_index.py`（新，重步骤）：打开 SQLite（读写）→ 加载 `BgeEmbedder` → 批量嵌入所有 chunk 文本 → 回写 `embedding` 列 → 用全部向量构建 `FaissVectorStore`（id = `chunk_id`）→ 写 `scope_index.faiss` → 写 `scope_index_metadata`（模型名、维度、归一化、chunk 数、构建时间）。可重复运行、幂等重建。

## 嵌入与向量存储

### Embedder（`rag/embedding.py`）

接口：

```python
class Embedder(Protocol):
    dimension: int
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...
```

- `BgeEmbedder`：包 `sentence-transformers` 的 `bge-small-zh-v1.5`，`normalize_embeddings=True`，`dimension = 512`。`embed_query` 在文本前加检索指令前缀 `为这个句子生成表示以用于检索相关文章：`；`embed_documents` 不加前缀。
- `FakeEmbedder`：确定性、低维（如 8 维）、不加载真模型，供单测。同样实现归一化，保证内积 = 余弦。

### VectorStore（`rag/vector_store.py` / `rag/faiss_store.py`）

接口：

```python
class VectorStore(Protocol):
    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...
    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "VectorStore": ...
```

- `FaissVectorStore`：`IndexIDMap(IndexFlatIP)`。向量已归一化，内积即余弦相似度；Flat 为精确检索，当前规模（约十几万 chunk）毫秒级。`add` 用显式 int64 id（= `chunk_id`）。`save`/`load` 走 `faiss.write_index`/`read_index`。
- 只实现 FAISS 一个真实后端；保留 `VectorStore` 接口是为了可测性（测试注入假后端），不为投机多后端。

## 检索器、工具与入口

### ScopeRetriever（`rag/retriever.py`）

```python
class ScopeHit(BaseModel):
    unified_social_credit_code: str
    legal_name: str
    section_label: str | None
    text: str
    score: float

class ScopeRetriever:
    def __init__(self, embedder, vector_store, repository, metadata): ...
    def search(self, query: str, k: int = 10) -> list[ScopeHit]: ...
```

流程：校验 `embedder` 的模型/维度与 `scope_index_metadata` 一致（不一致报错，提示重建索引）→ `embed_query` → `vector_store.search(vec, k)` 得 `(chunk_id, score)` → 按 `chunk_id` 从 SQLite 取 chunk 文本、段标签和企业法定名称 → 组装 `ScopeHit`，按评分降序。

### 工具（`rag/tools.py`）

`search_company_scope`：`read_private` 权限层，注册进 `ToolRegistry`，输入 `{query, k}`，输出 `ScopeHit` 列表的 JSON。复用现有工具基座（`tools/base.py`），为日后接 Agent 留口。

### 入口

最小 CLI（`python -m deepresearch_agent.rag.cli "注塑成型" --k 10 --database … --index …`），打印排序后的「企业法定名称 — 段标签 — 条款 — 评分」。不接入 planner→writer。

## Agent 集成边界

本模块到「检索器 + 工具 + CLI」为止。把跨企业筛选接入 Agent 端到端（planner 识别筛选类问题、新研究流程、新报告形状）与现有「核验指定企业」流程并存，是**独立的第二个 spec**，不在本模块。`search_company_scope` 工具已就绪，届时按 Domain Pack 白名单接入即可。

## 依赖

新增 `faiss-cpu`、`sentence-transformers`（含 torch）、`numpy`。放入 **可选 extra `[rag]`**，核心安装保持轻量：

```toml
[project.optional-dependencies]
rag = ["faiss-cpu>=1.8.0", "sentence-transformers>=2.7.0", "numpy>=1.26.0"]
```

`build_scope_index`、`BgeEmbedder`、`FaissVectorStore` 仅在安装 `[rag]` 后可用；核心建库、Repository、Agent 现有路径不依赖这些。

## 错误处理与重建

- FAISS 文件缺失：检索器初始化报明确错误，提示运行 `build_scope_index`。
- 模型/维度与 `scope_index_metadata` 不一致：拒绝检索，提示用同一模型重建索引。
- SQLite schema 非 v2：沿用现有版本校验，提示重建数据库。
- chunk 文本与向量始终从 SQLite 可重建；FAISS 文件可独立重建，不需重新嵌入（向量已存 SQLite，可由 `embedding` 列直接重灌 FAISS）。

## 测试策略

默认测试套件**绝不加载真模型、不下载权重**，依赖注入假实现：

- 切块：纯函数单测，覆盖段切分、段标签识别、免责括注剥离、`、；,，。` 切项、空/None、段内去重、连续编号。
- 建库：fixture `business_scope` → v2 schema、chunk 行生成、`embedding` 为 NULL、原子替换；schema 版本与索引校验。
- 索引构建：用 `FakeEmbedder` 跑 `build_scope_index`，断言 `embedding` 回写、FAISS 文件生成、`scope_index_metadata` 正确。
- `FaissVectorStore`：手造小向量 add/search/save/load（真 faiss、数据微小、快）。
- `ScopeRetriever`：`FakeEmbedder` + 临时 FAISS + fixture SQLite，断言排序、`k` 截断、`chunk_id`→条款/企业映射、模型不一致报错。
- 工具：返回结构化 `ScopeHit` 或结构化错误。
- 一个标记 `slow` 的集成测试加载真 `bge-small-zh-v1.5`，校验维度 512、归一化、且“注塑”能召回“塑料成型”类条款；默认 `-m "not slow"` 跳过。
- 删除 `retrieval/local.py` 与 `tests/test_retrieval.py`。

## 决策记录

- **语义而非词法**：用户明确要按意思检索（同义匹配），故走 embeddings + 向量检索，而非 FTS5/BM25。
- **本地模型**：受限工商数据不外发，排除外部嵌入 API。
- **`bge-small-zh-v1.5`**：短文本中文检索甜区，轻量、CPU 可跑、离线；日后精度不足可换 `bge-base-zh-v1.5`，仅改模型名与维度并重建索引，接口不变。
- **仅 FAISS**：进程内、落地为可重建文件、无服务、不给受限数据增加治理副本；当前规模 Flat 精确足够。不引 Qdrant（服务型、带运维与第二数据副本，本模块用不上）。
- **细粒度切块 + 段标签元数据**：检索单位为单条经营项，引用精确、BM 排序信号干净，段上下文作元数据保留。
- **剥离标准免责括注**：模板噪声，降低语义匹配质量。
- **删除旧 `LocalDocumentRetriever`**：test-only、从未接入、被语义检索取代。

## 验收条件

- 全套默认测试通过，且默认运行不加载真模型、不触网。
- 用真实 processed CSV 跑 `build_company_database` 后，`business_scope_chunks` 含各企业经营项 chunk，万马科技的经营范围被切成多条 chunk，`embedding` 为 NULL。
- 跑 `build_scope_index` 后，`scope_index.faiss` 生成，`scope_index_metadata` 记录 `bge-small-zh-v1.5` / 512 / 归一化 / chunk 数；`embedding` 列回写完成。
- CLI 用语义查询（如“注塑成型”）返回按评分排序的企业 + 命中条款，且能体现同义召回（“注塑”命中“塑料/塑胶成型”类条款）。
- `[rag]` extra 未安装时，核心建库、Repository、现有 Agent/CLI/API 路径不受影响。
```
