# 前端聊天界面设计（对外演示 Demo）

> 状态：设计已确认（配色/布局经样机 `scratchpad/chat-ui-mockup.html` → Artifact 通过）。下一步 writing-plans 出实现计划。

## 目标

给「供应商工商研究 Agent」加一个**对外演示用**的网页聊天界面：把已有的 `POST /session/turn` 有状态多轮端点包成一个能顺滑演示的对话页，重点展示结构化报告卡、多轮指代、以及「证据不足 + 尚未接入数据源」的诚实叙事。**不上生产鉴权**。

## 已确认的三个大决策

1. **定位**：对外演示 Demo——相对精致的观感、顺滑的多轮，但不必上真鉴权（`user_id` 是 authenticated-user stand-in）。
2. **过程呈现**：`研究中…` 加载态（纯前端），**后端不动**，不做流式/SSE。发请求→思考动画→一次性渲染结构化报告。流式进度作为明确的「后续」。
3. **技术栈**：FastAPI 托管的**自包含 vanilla 页**——单 HTML + 手写 CSS + 原生 JS，**零构建、零 npm**，同一个 `uvicorn` 命令起。贴合本仓库「本地优先、最少依赖」取向。

小决策默认值：证据表保留完整不折叠；身份 chip 保留可见可改名；待解问题的锁图标用内联 SVG（非 emoji）。

## 架构

### 后端改动（最小化，`api.py`）

`create_app(database_path, memory=, session_store=)` 内新增两处，**不碰** `/session/turn` 与 `/research` 的行为与形状：

- 静态资源：`application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")`，托管 `web/` 下的 `app.js`、`style.css`。
- 首页：`GET /` → `FileResponse(WEB_DIR / "index.html")`。
- `WEB_DIR = Path(__file__).parent / "web"`（随包走，不依赖 CWD）。
- 依赖：`StaticFiles` 来自 `fastapi.staticfiles`（FastAPI 自带 starlette，无新依赖）。

### 前端目录

```
src/deepresearch_agent/web/
  index.html    # 结构（顶栏 / 聊天流 / 输入区）
  style.css     # 全部设计令牌与组件样式
  app.js        # 会话状态、fetch、报告卡渲染、加载态、错误处理
```

三文件分离（非全内联），便于阅读与后续维护；`index.html` 用 `<link href="/static/style.css">` 与 `<script src="/static/app.js">` 引入。**不引任何 CDN/webfont**：CJK 用系统字体栈（`PingFang SC / Microsoft YaHei / Noto Sans SC …`），代码/数据用等宽栈，图标用内联 SVG。

## 组件（各有单一职责）

| 单元 | 职责 | 依赖 |
|------|------|------|
| `SessionState`（app.js 内的小对象） | 持有 `userId`、`sessionId`、消息列表；`userId` 存 localStorage，`sessionId` 存内存 | localStorage |
| `api.sessionTurn(question)` | `POST /session/turn`，带上 `user_id`/`session_id`，回写 `sessionId`，返回 `report` 或抛错 | fetch |
| `renderReport(report)` | 把 `SupplierReport` 渲染成报告卡 DOM（纯函数，输入 report → 输出节点） | 无 |
| `renderBadge(recommendation)` | recommendation → 徽章文案+语义色 | 无 |
| `ui.append*` | 追加用户气泡 / 思考气泡 / 报告卡 / 错误气泡，管理滚动 | DOM |
| `composer` | 输入框自动增高、Enter 发送、发送时禁用按钮 | 无 |

`renderReport`/`renderBadge` 是纯函数（report → DOM），可单独在浏览器控制台喂样例数据肉眼验证。

## 数据流（一轮）

```
用户在输入框回车
  → SessionState 追加用户消息 + ui.appendUser 气泡
  → ui.appendThinking（研究中… 动画）
  → api.sessionTurn(question):
        POST /session/turn { question, user_id: state.userId, session_id: state.sessionId }
  → 成功 { session_id, report }:
        state.sessionId = session_id
        thinking.replaceWith( renderReport(report) )
  → 失败:
        thinking.replaceWith( errorBubble(...) )（见错误处理）
```

`session_id` 首轮为 `null`（后端 uuid4 生成并回传），此后每轮复用 → 多轮指代（`它/该公司/上述` → 最近实体）在后端 `execute_turn` 里生效。

## 报告卡渲染（Demo 核心，忠于 `SupplierReport`）

`SupplierReport` 字段：`supplier_name, recommendation, summary, risks[], evidence_table[](Evidence), open_questions[]`；`Evidence = {claim, dimension, confidence, citation{source_id,title,url,snippet}}`。

卡片结构（**前端只排版，不加任何判断**，报告字段逐字渲染）：

- **表头**：`supplier_name` + 信用代码（若报告含，取自 evidence/citation 或摘要，等宽显示）+ **recommendation 徽章**。
- **摘要**：`summary` 段落。
- **风险 / 提示**：`risks[]` 逐条列出；**为空则整节隐藏**（不显示「未发现风险」之类文案——由 writer 决定内容，前端不臆造）。
- **证据表**（横向可滚）：每行 `维度 chip(dimension) · 结论(claim) · 置信 meter(confidence) · 引用 chip(citation)`；引用 chip 显示 `citation.url`（`local://…`），`title`/`snippet` 作 `title=` 悬浮。
- **待解问题 · 尚未接入的数据源**：`open_questions[]` 渲染为虚线格，配「缺失不代表无风险」提示句（固定文案，属界面框架、非结论）。

### recommendation → 徽章映射

| recommendation | 文案 | 语义色 |
|----------------|------|--------|
| `insufficient_evidence` | 证据不足 | 琥珀（warn）——**既非红也非绿** |
| `conditional` | 有条件 | 琥珀 |
| `approve` | 通过 | 绿（good） |
| `reject` | 不通过 | 红（bad） |

语义色与主色（登记蓝）分离。当前登记数据下 writer 固定回 `insufficient_evidence`，但映射四值全覆盖以防未来数据源接入。

## 身份与会话（Demo 无鉴权）

- `userId`：首次进页在 localStorage 生成 `demo-<随机6-8位>` 并持久化；顶栏 chip 展示，点击可改名（写回 localStorage）。它就是后端 `user_id`（authenticated-user stand-in）。
- `sessionId`：内存变量，`null` 起手，首轮响应回写后复用。
- **＋新对话**：清空消息、`sessionId=null`（保留 `userId`），回到引导态。

## 加载态

思考气泡：三点脉冲 + `研究中…`，附 `planner → researcher → critic → writer` 文案暗示多步推理。`prefers-reduced-motion` 下停动画。发送期间禁用发送按钮防重复提交。

## 错误处理

`api.sessionTurn` 按 HTTP 状态映射为可读错误气泡（写清「出了什么、怎么办」，不道歉不含糊）：

| 情况 | 处理 |
|------|------|
| 网络错误 / 5xx | 错误气泡「请求失败，请重试」+ 重试按钮（重发同一问题） |
| 400（非法 session_id） | 错误气泡「会话标识异常，已为你开新会话」+ 自动 `sessionId=null` |
| 404（ownership 不符） | 错误气泡「找不到该会话，已开新会话」+ `sessionId=null`（单人 Demo 正常不触发，仍兜底） |
| 空输入 | 前端拦截，不发请求 |

## 视觉设计语言（源自已通过样机）

- **色**：冷调石板灰纸底 + 钢青「登记蓝」主色（light `#2C5A8C` / dark `#6EA3D8`）；语义色独立（warn 琥珀、good 绿、bad 红）。令牌化 `:root` + `@media(prefers-color-scheme)` + `:root[data-theme]` 双向覆盖，明暗两套等同打磨。
- **字**：CJK 系统 sans 作正文；等宽栈承载信用代码 / 置信分 / 维度名 / eyebrow 标签，做「工商档案/终端」质感。类型级差固定，标签大写加字距。
- **版式**：应用外框满高、居中 ≤1040px；聊天流居中 792px；用户气泡右对齐实底，助手=报告卡（surface + 发丝边 + 轻投影）；输入区底部 sticky。宽内容（证据表）自带 `overflow-x:auto`。
- 图标全内联 SVG；无 emoji 作结构标记；焦点可见；`tabular-nums` 用于对齐数字。

## 测试策略

零构建、零 JS 测试框架（不为 Demo 引 node 工具链）。

- **后端**（`tests/test_api_web.py`，pytest + TestClient）：
  - `GET /` → 200，`content-type` 含 `text/html`，正文含标识串（如 `DeepResearch`）。
  - `GET /static/style.css` → 200，`content-type` 含 `text/css`。
  - `GET /static/app.js` → 200。
  - 回归：`POST /research` 与 `POST /session/turn` 形状不变（既有测试已覆盖；本文件可加一条 smoke 确认挂载静态后端点仍在）。
- **前端 JS**：逻辑保持轻薄；`renderReport`/`renderBadge` 为纯函数，靠代码审查 + 收尾手验（起 uvicorn 开浏览器走两轮 + 发送预览加载态）保证。
- 全套 `pytest` 保持绿（新增后端路由测试并入）。

## 明确不做（后续）

- 流式/SSE 步骤进度（planner→…→writer 实时）。
- 真鉴权（token 中间件）、会话 TTL/列表、历史会话侧栏。
- scope/graph 检索模式在前端的专门渲染（Demo 走 `/session/turn` 恒 named/unresolved 的 `SupplierReport`）。
- 移动端深度适配（现有响应式够 Demo 用）。

## Self-Review

- **占位符**：无 TBD；组件、数据流、字段映射、错误分支、测试项均具体。
- **一致性**：端点/字段与现有 `api.py`（`SessionTurnRequest{question,user_id,session_id?,domain}` → `SessionTurnResponse{session_id,report:SupplierReport}`）、`state.py`（`SupplierReport`/`Evidence`/`Citation`）一致；后端仅加静态托管，`/session/turn`、`/research` 不变。
- **核心数据原则**：前端纯排版、逐字渲染报告字段，不臆造「无风险」；recommendation 由 writer 定、界面只配色；「尚未接入数据源」是固定框架文案。徽章 `insufficient_evidence` 用琥珀而非绿/红。
- **范围**：单一实现计划可覆盖（后端两处 + 前端三文件 + 一个测试文件）；流式/鉴权/TTL 已切出。
- **歧义**：`user_id` 明确为 stand-in；`session_id` 生命周期、新对话语义、错误→重置逻辑均已固定。
