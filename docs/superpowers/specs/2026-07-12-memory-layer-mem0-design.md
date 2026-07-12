# 记忆层（mem0 语义记忆 + 会话多轮指代）设计

日期：2026-07-12
状态：设计已确认，待落实施计划

## 背景

当前 Agent 是**单发**的：CLI/API 一问一答，无会话、无跨轮上下文。用户要一个记忆层，让 Agent 能多轮对话（「查万马科技的股东」→「它的联系方式呢」）并跨会话记住用户研究过什么、关注什么。

本轮范围（用户确认）：**记忆核心 + 接入 Agent，含上下文与多轮指代**。前端聊天页留到下一轮。

## 红线豁免（用户明确决定，务必留档）

本项目核心红线是「受限工商数据不出本机、不接外部 LLM/云」。**用户在充分知情下明确决定：本条记忆线先完全走云端 API、暂时豁免该红线，但保留本地 AI 接口以便随时切回。**

- 助手已两次明示风险（mem0 默认把整段对话含报告正文发给 LLM、云端不可逆缓存），用户仍决定走云端。
- `CLAUDE.md` 的红线文本**不删**（仍是历史事实标准）；豁免只作用于本记忆线，并在此记录，便于日后收回。
- 落地要求：LLM provider 做成可插拔抽象，云端（DeepSeek）为当前默认，**本地 Ollama 配置留好，切换只改一段 config**。

## 目标

- 两层记忆：确定性会话缓冲（多轮指代）+ mem0 语义记忆（跨会话长期）。
- 接入现有图编排（图层包装为主，尽量不改 nodes 内部），`run_research` 增加会话与记忆参数，默认关。
- 交互式 `cli chat` 承载多轮对话。
- CI 零网络零 key：确定性部分与降级路径全部可测；真云端路径手验。

## 非目标（本轮不做）

- 前端聊天页（下一轮）。
- `/research` API 接记忆（API 无状态、多轮需会话；本轮记忆只经 `cli chat` 承载，API 形状不变）。
- 跨进程持久会话存储（会话缓冲为 REPL 进程内；跨会话长期由 mem0 语义记忆承担）。
- 云端嵌入（嵌入器用本地 bge，见下）。

## 核心设计

### 为什么两层记忆

多轮指代（`它/该公司/上述` → 上一轮实体）与语义召回是**两个不同问题**：

- 「它的联系方式呢」与记忆「用户研究过万马科技」的**语义相似度很弱**，mem0 语义搜索对指代不可靠。
- 指代要的是**确定性**：本会话最近解析的实体，直接取。

因此：

| 层 | 用途 | 实现 | LLM |
|---|---|---|---|
| 会话最近实体缓冲 | 本会话内指代 | 内存 `deque`，确定性 | 无 |
| mem0 语义记忆 | 跨会话长期召回 | mem0 + 云端 DeepSeek 抽取 + 本地 bge 嵌入 + 本地 Chroma | 云端 |

### 组件与接口

**`memory/config.py`** — provider 抽象与 mem0 配置构建。

- `MemoryConfig`（pydantic）：`llm_provider: Literal["deepseek","ollama"]="deepseek"`、`llm_model`、`llm_base_url`、`api_key_env="DEEPSEEK_API_KEY"`、`embedder_model="BAAI/bge-small-zh-v1.5"`、`vector_store_path`、`collection_name`。
- `MemoryConfig.deepseek(...)` / `MemoryConfig.ollama(...)` 两个工厂，体现「保留本地接口」。
- `to_mem0_config() -> dict`：构建 mem0 的 `{llm, embedder, vector_store}` 配置字典。**exact 键名按实现时安装的 mem0 版本对齐**（openai 兼容 base_url、huggingface 嵌入器、chroma 本地路径），不在设计层假定已验证。
- `build_memory_backend(config) -> MemoryBackend | None`：懒加载 mem0；缺 `.[memory]` 或缺 key → 返回 `None`（由 `MemoryService` 降级）。

**`memory/service.py`** — 记忆读写门面。

- `MemoryBackend`（Protocol）：`search(user_id, query, limit) -> list[str]`、`add(user_id, messages) -> None`。
- `Mem0Backend`：包 `mem0.Memory`，`search` → `memory.search(...)` 取 memory 文本列表；`add` → `memory.add(messages, user_id=...)`。
- `FakeMemoryBackend`：内存 list，测试用（零网络）。
- `MemoryService(backend | None)`：`recall(user_id, query, limit=5) -> list[str]`、`remember(user_id, messages) -> None`、属性 `memory_available: bool`。backend 为 None → 全部 no-op（照搬 `retrieval_available` 降级语义，不抛异常）。

**`memory/session.py`** — 确定性会话缓冲与指代解析。

- `ANAPHORA_MARKERS: tuple[str, ...]`：`它`、`该公司`、`该企业`、`这家`、`那家`、`上述`、`这家公司`、`该供应商`、`此公司` 等。
- `contains_anaphora(query: str) -> bool`。
- `Session`：`user_id`、`session_id`、`recent_entities: deque[CompanyResolution]`（`maxlen=5`）。
  - `note_entity(resolution: CompanyResolution) -> None`：`status=="resolved"` 才入队。
  - `resolve_anaphora(query: str) -> CompanyResolution | None`：句含指代标记且缓冲非空 → 返回最近一个 resolved 实体；否则 None。

**planner 接指代（本轮唯一改 planner 处）** — 保持 nodes 为 state 的纯函数。

- 初始 state 增加可选 `preresolved: CompanyResolution | None`。
- planner：`resolution = state.preresolved or resolve_supplier(question)`。指代解析在 `run_research` 前置步完成并注入 `preresolved`，planner 只是优先采用它。

**`run_research(..., session=None, memory=None, enable_memory=False, user_id="default")`** — 图层包装，编排记忆。

1. `enable_memory` 且有 `session`：
   - 指代：`contains_anaphora(question)` → `coref = session.resolve_anaphora(question)`。
   - 召回：`memory_context = memory.recall(user_id, question)`。
2. 构建初始 state：注入 `memory_context`、`preresolved=coref`。
3. 跑现有图 `planner→researcher→critic→writer`。
4. `session.note_entity(最终 resolution)`。
5. `memory.remember(user_id, [{"role":"user","content":question},{"role":"assistant","content":报告摘要}])`。

默认 `enable_memory=False` → 上述全跳过，行为/形状与现在一致（与 scope/graph/trace 同模式）。

**writer** — `state.memory_context` 非空时，报告前置一段「结合历史记忆」note，**明确标注为记忆、非新事实**，不与 `insufficient_evidence` 结论混淆。

**`cli chat --user <id> [--memory] [--database ...]`** — 交互式 REPL。

- 进程内持一个 `Session`；每行输入 → `run_research(..., session, memory, enable_memory=args.memory)` → 打印报告 → 循环。
- 退出词（`exit`/`quit`/空行策略）结束。这是本轮承载多轮的入口。

### 数据流（一轮）

```
用户输入
  → contains_anaphora? → Session.resolve_anaphora（最近实体）→ preresolved
  → MemoryService.recall（跨会话记忆）→ memory_context
  → 初始 state(memory_context, preresolved)
  → 图 planner(采用 preresolved 或自解析) → researcher → critic → writer(surface memory_context)
  → Session.note_entity(本轮 resolution)
  → MemoryService.remember(问题 + 报告摘要)
```

### 嵌入与存储

- 嵌入器：复用本地 `BAAI/bge-small-zh-v1.5`（已在 `.[rag]`，免费、中文强）。mem0 用 huggingface 嵌入器加载。注：bge 查询端指令前缀 mem0 不会加，记忆召回可接受，列为后续优化。
- 向量库：本地 Chroma，落盘 `data/procurement/derived/mem0_chroma/`，Git 忽略。
- 云端 LLM：复用 DeepSeek（`llm/deepseek.py` 已接、OpenAI 兼容、`DEEPSEEK_API_KEY`）。

## 依赖

- 新 `.[memory]` extra：`mem0ai`、`chromadb`（版本实现时钉）。
- 嵌入器复用 `.[rag]` 的 sentence-transformers + bge。
- 主图 import 不依赖 mem0/chroma；缺失时 `memory_available=False` 降级。

## 测试策略

CI 零网络零 key，对确定性部分与降级做 TDD；真云端路径手验（照 real golden / neo4j 对拍套路）。

- `contains_anaphora` / `Session.note_entity` / `resolve_anaphora`：纯单元测（含无标记、空缓冲、句自带实体→不指代、多轮取最近）。
- `MemoryService` 用 `FakeMemoryBackend`：`recall` 注入 `memory_context`；`remember` 收到「问题+报告摘要」；backend=None → 全 no-op 不崩。
- `run_research(enable_memory=True, session, FakeMemory)`：指代把「它」解析到上一轮实体（planner 采用 preresolved）；关闭时行为不变。
- 真 mem0 + 真 DeepSeek + 真 Chroma：标 `@pytest.mark.llm`，默认排除，用户本地手验端到端多轮。

## 风险

- mem0 与 DeepSeek 的兼容（抽取用结构化输出/JSON 模式）：DeepSeek OpenAI 兼容应可，但 mem0 config 的 exact 键名随版本变，**实现时对installed 版本核对并手验一次真链路**。
- mem0/chromadb 依赖较重、可能与现有 numpy/torch 版本冲突：装进当前 conda-env 前先验证不破坏 202 测试；若冲突，参照 Phoenix 教训用隔离手段。

## 未来扩展

- 前端聊天页（下一轮）。
- `/research` API 接记忆（需跨进程会话存储）。
- 切回本地 Ollama（`MemoryConfig.ollama` 已留，需下载 qwen2.5:3b）。
- bge 查询端指令前缀优化召回。
- 会话缓冲持久化（跨进程续接会话）。
