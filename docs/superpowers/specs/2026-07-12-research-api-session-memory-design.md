# /research API 接记忆（跨进程会话存储 + ownership 授权）设计

日期：2026-07-12
状态：设计已确认，待落实施计划

## 背景

记忆层已落地（`memory/`：会话缓冲 + mem0 语义记忆），但只经 `cli chat` 的**进程内**会话承载多轮。`/research` API 仍无状态。本轮给 API 接记忆，让多轮对话（含 `它/该公司` 指代）能经 HTTP 进行。

核心难点：HTTP 请求可能打到不同 worker 进程，指代所需的会话缓冲（`Session.recent_entities`）活不过请求之间，必须**跨进程持久化**。mem0 语义记忆已跨进程（Chroma 落盘），故只需补确定性会话缓冲这一层。

## 目标

- 新增 `POST /session/turn` 有状态多轮端点；`/research` 无状态一问一答保持不动。
- 会话缓冲跨进程持久化（JSON 文件每会话，原子写）。
- **ownership 授权**：session 归属 authenticated user，session_id 只做寻址不做授权（防 IDOR）。
- 防路径穿越：session_id 严格格式校验后才作文件名。
- 复用记忆编排：抽 `execute_turn`，API 用缓存图跑，不每请求重建图。
- CI 零网络零 key（FakeMemoryBackend + tmp store），真云端 mem0 标 `@pytest.mark.llm`。

## 非目标（本轮不做）

- 完整鉴权（JWT/OAuth/token→用户）。`user_id` 由请求体给，作 authenticated user 的 stand-in；真鉴权中间件是后续。ownership 绑定+校验（安全上有意义的那部分）本轮建。
- `/session/turn` 的 scope/graph 检索（`enable_scope=False`，只 named/unresolved → `SupplierReport`，形状干净）；能力检索多轮留后续。
- 前端聊天页（另一轮）。
- 会话过期/清理（TTL、GC）留后续。

## 架构决策（问答已定）

| 决策 | 选择 |
|---|---|
| 端点 | 新增 `POST /session/turn`，`/research` 不动 |
| 会话存储 | JSON 文件每会话，`data/procurement/sessions/`，原子写 |
| session_id 生成 | 缺省服务端 `uuid4()`，带上按它存取；响应始终回 session_id |
| 授权 | ownership：`存储 owner == 请求 user_id`，不符 404、绝不覆写 |
| 身份来源 | 请求体 `user_id`（无鉴权层，stand-in） |
| 记忆编排 | 抽 `execute_turn`，`run_research` 与 API 共用 |

## 组件与接口

### `memory/store.py` — 跨进程会话存储

- `SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")`；`SessionOwnershipError(Exception)`；`InvalidSessionIdError(Exception)`。
- `JsonSessionStore(root: str | Path)`：
  - `load(session_id: str, user_id: str) -> Session | None`：
    - session_id 不匹配 `SESSION_ID_PATTERN` → 抛 `InvalidSessionIdError`（防路径穿越）。
    - 文件不存在 → 返回 `None`（调用方可用此 id 新建，first-come 归属）。
    - 文件存在且 `owner == user_id` → 反序列化返回 `Session`（`recent_entities` 从 CompanyResolution dict 列表重建为 `deque(maxlen=5)`）。
    - 文件存在但 `owner != user_id` → 抛 `SessionOwnershipError`（非泄露式，API 映射 404；不覆写）。
  - `save(session: Session) -> None`：session_id 先校验格式；写 `{"session_id", "user_id", "recent_entities": [r.model_dump(mode="json") ...]}` 到临时文件 → `os.replace` 原子替换 `{root}/{session_id}.json`。root 不存在则创建。

### `agents/graph.py` — `execute_turn` 重构

- 抽出 `execute_turn(app, question, domain, session=None, memory=None, enable_memory=False, tracer=None) -> ResearchState`：含指代→`preresolved`、`recall`、`run_compiled`、`note_entity`、`remember`、`_surface_memory` 全部编排（现 `run_research` 内联逻辑原样搬出）。
- `run_research` 改为：构建 app → 取 tracer → `return execute_turn(app, question, domain, session, memory, enable_memory, tracer)`。行为不变，现有记忆/追踪测试仍绿。

### `api.py` — `/session/turn`

- `create_app(database_path=, memory=None, session_store=None)`：新增两可选注入（默认 `MemoryService(build_memory_backend())` 与 `JsonSessionStore(默认 sessions 目录)`）；测试注入 FakeMemoryBackend 与 tmp store。沿用 `graph_for(domain)` 缓存编译图（无 scope，与现 `/research` 同）。
- `SessionTurnRequest`：`question: Question`、`domain: str = "procurement"`、`session_id: str | None = None`、`user_id: Question`（非空）。
- `SessionTurnResponse`：`session_id: str`、`report: SupplierReport`。
- `POST /session/turn` 逻辑：
  1. `user_id = request.user_id`。
  2. `session_id` 缺省 → `Session(user_id, uuid4().hex)`；否则 `store.load(session_id, user_id)`（`SessionOwnershipError`→`HTTPException(404)`；`InvalidSessionIdError`→`HTTPException(400)`），`None` → `Session(user_id, session_id)`（first-come 归属）。
  3. `state = execute_turn(graph_for(domain), question, domain, session, memory, enable_memory=True)`。
  4. `store.save(session)`。
  5. 返回 `SessionTurnResponse(session_id=session.session_id, report=state.report)`。
  - `state.report` 为 None（不应发生，enable_scope=False 下 named/unresolved 必出 SupplierReport）时 `RuntimeError`。

## 数据流（一轮 HTTP）

```
POST /session/turn {question, user_id, session_id?}
  → session_id? 无→uuid4；有→store.load(校验 owner/格式)
  → execute_turn(缓存图, question, domain, session, memory, enable_memory=True)
       指代→preresolved；recall→注入；跑图；note_entity；remember；surface
  → store.save(session)（原子）
  → {session_id, report}
```

## 安全

- **IDOR 防护**：ownership 校验，session_id 泄露也读不到他人会话（owner 不符 404）。
- **路径穿越防护**：session_id 严格 `^[A-Za-z0-9_-]{1,64}$` 才作文件名。
- **不覆写**：owner 不符在任何 save 前抛错。
- 局限（本地工具、已知）：user_id 无真实鉴权、可伪造 → 后续接真 auth 中间件；JSON 多 worker 并发写同会话有竞态（原子写防半文件、不防丢更新），单用户可接受。

## 测试策略

CI 零网络零 key。

- `store.py`：load/save 往返（recent_entities 保真）；owner 不符抛 `SessionOwnershipError`；非法 id 抛 `InvalidSessionIdError`（含 `../` 穿越尝试）；不存在返 None；原子写（save 后文件完整可读）。用 `tmp_path`。
- `execute_turn`：现有 `test_memory_integration` / 追踪测试覆盖行为不变；补一条直接调用 `execute_turn` 的用例（指代生效）。
- API：`TestClient` + fixture DB + tmp store + 注入 FakeMemoryBackend：
  - 首轮无 session_id → 响应含 session_id、report 解析到实体。
  - 次轮带 session_id + `它...` → 指代到同实体。
  - 用户 B 拿 A 的 session_id → 404，且 A 的会话未被覆写。
  - 跨"请求"落盘持久（第二个 TestClient/新 store 实例仍能续接）。
  - `/research` 旧端点行为/形状不变。
- 真 mem0+DeepSeek 端到端：`@pytest.mark.llm` 手验。

## 未来扩展

- 真鉴权中间件（token→user，替换请求体 user_id）。
- 会话 TTL/GC。
- `/session/turn` 接 scope/graph 检索（响应 union）。
- 前端聊天页消费本端点。
- SQLite 会话存储（若并发写变重要）。
