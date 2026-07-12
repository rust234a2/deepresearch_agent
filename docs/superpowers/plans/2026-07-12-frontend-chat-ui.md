# 前端聊天界面（对外演示 Demo）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已有的 `POST /session/turn` 有状态多轮端点加一个 FastAPI 托管的自包含网页聊天界面（零构建、零 npm），演示结构化报告卡、多轮指代与「证据不足 + 尚未接入数据源」的诚实叙事。

**Architecture:** 后端 `api.py` 仅加两处——`GET /` 返 `web/index.html`、`/static` 托管 `web/` 静态资源，`/session/turn` 与 `/research` 一字不改。前端三文件 `web/{index.html,style.css,app.js}`：HTML 是应用外壳，CSS 是全部令牌与组件样式，JS 持有会话状态、`fetch`、把 `SupplierReport` 渲染成报告卡、加载态与错误处理。前端纯排版，逐字渲染报告字段。

**Tech Stack:** FastAPI（`StaticFiles`/`FileResponse`，无新依赖）、原生 HTML/CSS/JS、pytest（TestClient）。环境 `.\.conda-env\python.exe`。

## Global Constraints

- 全程中文沟通与提交信息。
- **零构建零 npm、无 CDN/webfont**：CJK 用系统字体栈（`PingFang SC / Microsoft YaHei / Noto Sans SC …`），代码/数据用系统等宽栈，图标全部内联 SVG（不用 emoji 作结构标记）。
- 后端 `POST /session/turn`、`POST /research` 的**行为与形状不变**；只新增 `GET /` 与 `/static` 静态托管。
- **核心数据原则**：前端纯排版、**逐字**渲染 `SupplierReport` 字段，绝不臆造「未发现风险」；`recommendation` 只决定徽章文案与配色，不改内容。「尚未接入的数据源」提示句是界面框架文案、非结论。
- `WEB_DIR = Path(__file__).parent / "web"`（随包走，不依赖 CWD）。
- 身份：`user_id` 存 `localStorage`（authenticated-user stand-in，可改名）；`session_id` 内存变量，首轮 `null`、后端回传后复用；「新对话」重置为 `null`。
- 依赖：`StaticFiles` 来自 `fastapi.staticfiles`，`FileResponse` 来自 `fastapi.responses`——FastAPI 自带，无新依赖。
- 测试隔离缓存：`.\.conda-env\python.exe -m pytest <路径> -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webui`。
- 明确不做：流式/SSE、真鉴权、会话 TTL/历史列表、scope/graph 前端专渲染。

---

### Task 1: 后端静态托管 + 前端骨架桩 + 后端测试

**Files:**
- Modify: `src/deepresearch_agent/api.py`
- Create: `src/deepresearch_agent/web/index.html`（本任务为最小可用桩，Task 2 补全）
- Create: `src/deepresearch_agent/web/style.css`（本任务为占位，Task 2 补全）
- Create: `src/deepresearch_agent/web/app.js`（本任务为占位，Task 3 补全）
- Test: `tests/test_api_web.py`

**Interfaces:**
- Consumes: 现有 `create_app(database_path, memory=, session_store=)`（`api.py`）、`company_database_path` fixture（`tests/conftest.py`）、`FakeMemoryBackend`/`MemoryService`（`memory/service.py`）、`JsonSessionStore`（`memory/store.py`）。
- Produces: `GET /` → `text/html`（`web/index.html`）；`/static/<file>` 静态托管；`WEB_DIR` 模块常量。

- [ ] **Step 1: 建前端目录与三个桩文件**

`src/deepresearch_agent/web/index.html`（最小可用，含标识串 `DeepResearch`）：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DeepResearch · 供应商工商研究</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="app"><header class="bar"><div class="brand"><div class="name">DeepResearch</div></div></header></div>
  <script src="/static/app.js" defer></script>
</body>
</html>
```

`src/deepresearch_agent/web/style.css`：

```css
/* 占位样式，Task 2 补全为完整设计令牌与组件样式 */
:root { color-scheme: light dark; }
body { margin: 0; font-family: system-ui, sans-serif; }
```

`src/deepresearch_agent/web/app.js`：

```javascript
// 占位脚本，Task 3 补全为会话状态 / fetch / 报告卡渲染 / 加载态 / 错误处理
console.debug("DeepResearch web shell loaded");
```

- [ ] **Step 2: 写失败测试**

新建 `tests/test_api_web.py`：

```python
from fastapi.testclient import TestClient

from deepresearch_agent.api import create_app
from deepresearch_agent.memory.service import FakeMemoryBackend, MemoryService
from deepresearch_agent.memory.store import JsonSessionStore

ENTITY = "示例科技股份有限公司"


def _client(company_database_path, tmp_path):
    app = create_app(
        database_path=company_database_path,
        memory=MemoryService(FakeMemoryBackend()),
        session_store=JsonSessionStore(tmp_path),
    )
    return TestClient(app)


def test_index_served_as_html(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "DeepResearch" in r.text


def test_static_css_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/style.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_static_js_served(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).get("/static/app.js")
    assert r.status_code == 200


def test_research_endpoint_unchanged(company_database_path, tmp_path):
    r = _client(company_database_path, tmp_path).post("/research", json={"question": ENTITY})
    assert r.status_code == 200
    assert r.json()["supplier_name"] == ENTITY
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webui`
Expected: FAIL（`GET /` 与 `/static/*` 404——尚未挂载）

- [ ] **Step 4: 在 `api.py` 挂静态托管与首页**

在 import 区加：

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

在模块常量区（`DEFAULT_SESSIONS_DIR` 附近）加：

```python
WEB_DIR = Path(__file__).parent / "web"
```

在 `create_app` 内、`return application` 之前加：

```python
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webui`
Expected: PASS（4 项）

- [ ] **Step 6: 提交**

```powershell
git add src/deepresearch_agent/api.py src/deepresearch_agent/web tests/test_api_web.py
git commit -m "功能：Web 界面后端托管(GET / + /static 静态资源，端点不变)"
```

---

### Task 2: 前端外壳与视觉（`index.html` + `style.css`）

**Files:**
- Modify: `src/deepresearch_agent/web/index.html`（桩 → 完整外壳）
- Modify: `src/deepresearch_agent/web/style.css`（占位 → 完整样式）
- Test: `tests/test_api_web.py`（沿用；`GET /` 仍绿）

**Interfaces:**
- Consumes: Task 1 的 `/static` 托管与 `GET /`。
- Produces: 完整外壳，含这些 id 供 Task 3 的 `app.js` 绑定——`#identity`、`#uid`、`#theme`、`#newchat`、`#stream`、`#thread`、`#q`、`#send`；以及这些渲染用类——`card / card-head / title / code / badge(.warn/.good/.bad) / glyph / sec / eyebrow / count / summary / risk-list / table-wrap / ev / dim / conf / meter / num / cite / oq-note / oq-grid / oq / lock / thinking(.error) / dots / retry / msg(.user) / avatar(.a/.u) / bubble-user / day`。

- [ ] **Step 1: 写完整 `index.html`**

`src/deepresearch_agent/web/index.html` 全量替换为：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DeepResearch · 供应商工商研究</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="app">
    <header class="bar">
      <div class="brand">
        <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <rect x="1.2" y="1.2" width="23.6" height="23.6" rx="6.4" fill="var(--accent)"/>
          <circle cx="11.4" cy="11.4" r="5" fill="none" stroke="#fff" stroke-width="1.9"/>
          <line x1="15.2" y1="15.2" x2="19.6" y2="19.6" stroke="#fff" stroke-width="1.9" stroke-linecap="round"/>
        </svg>
        <div>
          <div class="name">DeepResearch</div>
          <div class="sub">供应商工商研究</div>
        </div>
      </div>
      <div class="spacer"></div>
      <button class="chip" id="identity" title="演示身份（无鉴权，点击可改名）">
        <span class="dot"></span><span>身份</span><span class="id" id="uid">demo</span>
      </button>
      <button class="iconbtn" id="theme" title="切换主题" aria-label="切换主题">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
      </button>
      <button class="btn-primary" id="newchat" title="清空并开新会话">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        新对话
      </button>
    </header>

    <div class="stream" id="stream">
      <div class="thread" id="thread">
        <div class="day">新会话 · 待生成 session_id</div>
        <div class="msg">
          <div class="avatar a">DR</div>
          <div class="thinking">输入一家供应商名称开始核验，例如「核验示例科技股份有限公司的工商与经营范围」。</div>
        </div>
      </div>
    </div>

    <footer class="composer">
      <div class="composer-inner">
        <textarea id="q" rows="1" placeholder="输入供应商名称或追问，例如「核验示例科技股份有限公司」…"></textarea>
        <button class="send" id="send" title="发送" aria-label="发送">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l16-8-6 16-3-6-7-2z"/></svg>
        </button>
      </div>
      <div class="hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</div>
    </footer>
  </div>
  <script src="/static/app.js" defer></script>
</body>
</html>
```

- [ ] **Step 2: 写完整 `style.css`**

`src/deepresearch_agent/web/style.css` 全量替换为：

```css
/* ---------- 设计令牌：先定 light，再两处覆盖 dark ---------- */
:root {
  --bg: #EDF0F4; --surface: #FFFFFF; --surface-2: #F6F8FB; --fg: #171C24; --fg-soft: #3A424E;
  --muted: #616B7A; --line: #DCE1E9; --line-strong: #C7CEDA; --accent: #2C5A8C; --accent-ink: #1E4066;
  --accent-soft: #E7EEF6; --warn: #8A5A0B; --warn-soft: #F6ECD6; --warn-line: #E6D3A6;
  --good: #2F7A55; --bad: #B23A3A;
  --shadow: 0 1px 2px rgba(20,28,40,.06), 0 8px 24px -12px rgba(20,28,40,.18);
  --radius: 14px;
  --mono: "SFMono-Regular", Consolas, "JetBrains Mono", "Cascadia Code", ui-monospace, monospace;
  --sans: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", "Hiragino Sans GB", system-ui, -apple-system, "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0E1219; --surface: #151B25; --surface-2: #1B2331; --fg: #E6EBF2; --fg-soft: #C2CBD8;
    --muted: #8E9BAD; --line: #26303F; --line-strong: #33404F; --accent: #6EA3D8; --accent-ink: #9FC3E8;
    --accent-soft: #1A2534; --warn: #E0B460; --warn-soft: #2E2716; --warn-line: #4A3D1E;
    --good: #6BC095; --bad: #E08585;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 30px -14px rgba(0,0,0,.6);
  }
}
:root[data-theme="light"] {
  --bg: #EDF0F4; --surface: #FFFFFF; --surface-2: #F6F8FB; --fg: #171C24; --fg-soft: #3A424E;
  --muted: #616B7A; --line: #DCE1E9; --line-strong: #C7CEDA; --accent: #2C5A8C; --accent-ink: #1E4066;
  --accent-soft: #E7EEF6; --warn: #8A5A0B; --warn-soft: #F6ECD6; --warn-line: #E6D3A6;
  --good: #2F7A55; --bad: #B23A3A;
  --shadow: 0 1px 2px rgba(20,28,40,.06), 0 8px 24px -12px rgba(20,28,40,.18);
}
:root[data-theme="dark"] {
  --bg: #0E1219; --surface: #151B25; --surface-2: #1B2331; --fg: #E6EBF2; --fg-soft: #C2CBD8;
  --muted: #8E9BAD; --line: #26303F; --line-strong: #33404F; --accent: #6EA3D8; --accent-ink: #9FC3E8;
  --accent-soft: #1A2534; --warn: #E0B460; --warn-soft: #2E2716; --warn-line: #4A3D1E;
  --good: #6BC095; --bad: #E08585;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 30px -14px rgba(0,0,0,.6);
}

* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; font-family: var(--sans); background: var(--bg); color: var(--fg); -webkit-font-smoothing: antialiased; line-height: 1.6; }
.app { display: flex; flex-direction: column; height: 100vh; max-width: 1040px; margin: 0 auto; background: var(--bg); }

/* 顶栏 */
header.bar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 14px; padding: 12px 20px; background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.brand svg { display: block; flex: none; }
.brand .name { font-weight: 650; letter-spacing: .01em; font-size: 15px; white-space: nowrap; }
.brand .sub { font-family: var(--mono); font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
.spacer { flex: 1 1 auto; }
.chip { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 11px; border: 1px solid var(--line-strong); border-radius: 999px; background: var(--surface); color: var(--fg-soft); font-size: 12.5px; cursor: pointer; white-space: nowrap; font-family: var(--sans); }
.chip:hover { border-color: var(--accent); color: var(--accent-ink); }
.chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--good); }
.chip .id { font-family: var(--mono); letter-spacing: .02em; }
.iconbtn { display: inline-grid; place-items: center; width: 34px; height: 30px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); color: var(--fg-soft); cursor: pointer; }
.iconbtn:hover { border-color: var(--accent); color: var(--accent-ink); }
.btn-primary { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 13px; border: 1px solid transparent; border-radius: 8px; background: var(--accent); color: #fff; font-size: 12.5px; font-weight: 600; cursor: pointer; font-family: var(--sans); }
.btn-primary:hover { background: var(--accent-ink); }

/* 消息流 */
.stream { flex: 1 1 auto; overflow-y: auto; padding: 26px 20px 8px; }
.thread { max-width: 792px; margin: 0 auto; display: flex; flex-direction: column; gap: 22px; }
.day { align-self: center; font-family: var(--mono); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 3px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface-2); }
.msg { display: flex; gap: 12px; }
.msg.user { flex-direction: row-reverse; }
.avatar { flex: none; width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; font-size: 12px; font-weight: 700; font-family: var(--mono); }
.avatar.a { background: var(--accent-soft); color: var(--accent-ink); border: 1px solid var(--line); }
.avatar.u { background: var(--accent); color: #fff; }
.bubble-user { max-width: 76%; background: var(--accent); color: #fff; padding: 10px 14px; border-radius: 14px 14px 4px 14px; font-size: 14.5px; box-shadow: var(--shadow); overflow-wrap: anywhere; }

/* 报告卡 */
.card { max-width: 100%; flex: 1 1 auto; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.card-head { display: flex; align-items: flex-start; gap: 12px; padding: 15px 17px 13px; border-bottom: 1px solid var(--line); background: linear-gradient(180deg, var(--surface-2), var(--surface)); }
.card-head .title { min-width: 0; flex: 1 1 auto; }
.card-head h3 { margin: 0; font-size: 16.5px; font-weight: 650; letter-spacing: .01em; text-wrap: balance; }
.card-head .code { margin-top: 4px; font-family: var(--mono); font-size: 12px; letter-spacing: .03em; color: var(--muted); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.badge { flex: none; display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 650; white-space: nowrap; border: 1px solid var(--line); }
.badge .glyph { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn-line); }
.badge.good { background: color-mix(in srgb, var(--good) 14%, var(--surface)); color: var(--good); border-color: color-mix(in srgb, var(--good) 34%, var(--line)); }
.badge.bad  { background: color-mix(in srgb, var(--bad) 14%, var(--surface)); color: var(--bad); border-color: color-mix(in srgb, var(--bad) 34%, var(--line)); }

.sec { padding: 14px 17px; border-bottom: 1px solid var(--line); }
.sec:last-child { border-bottom: 0; }
.eyebrow { font-family: var(--mono); font-size: 11px; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); margin: 0 0 8px; display: flex; align-items: center; gap: 8px; }
.eyebrow .count { font-size: 10.5px; color: var(--accent-ink); background: var(--accent-soft); border-radius: 999px; padding: 1px 7px; letter-spacing: .04em; }
.summary { margin: 0; font-size: 14px; color: var(--fg-soft); }
.risk-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.risk-list li { display: flex; gap: 9px; font-size: 13.5px; color: var(--fg-soft); padding-left: 2px; }
.risk-list li::before { content: ""; flex: none; margin-top: 8px; width: 6px; height: 6px; border-radius: 2px; background: var(--warn); transform: rotate(45deg); }

/* 证据表 */
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
table.ev { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 560px; }
table.ev th { text-align: left; font-family: var(--mono); font-size: 10.5px; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); font-weight: 600; padding: 9px 12px; background: var(--surface-2); border-bottom: 1px solid var(--line); white-space: nowrap; }
table.ev td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--fg-soft); }
table.ev tr:last-child td { border-bottom: 0; }
.dim { display: inline-block; font-family: var(--mono); font-size: 11px; letter-spacing: .02em; color: var(--accent-ink); background: var(--accent-soft); border-radius: 6px; padding: 2px 7px; white-space: nowrap; }
.conf { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.meter { width: 46px; height: 5px; border-radius: 3px; background: var(--line-strong); overflow: hidden; }
.meter > i { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.conf .num { font-family: var(--mono); font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.cite { display: inline-flex; align-items: center; gap: 5px; text-decoration: none; font-family: var(--mono); font-size: 11.5px; color: var(--accent); border: 1px solid var(--line); border-radius: 6px; padding: 2px 7px; background: var(--surface); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cite:hover { border-color: var(--accent); background: var(--accent-soft); }

/* 待解问题 */
.oq-note { font-size: 12.5px; color: var(--muted); margin: 0 0 10px; }
.oq-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(158px, 1fr)); gap: 8px; }
.oq { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--fg-soft); border: 1px dashed var(--line-strong); border-radius: 8px; padding: 8px 10px; background: var(--surface-2); }
.oq .lock { flex: none; color: var(--muted); }

/* 加载态 / 错误 */
.thinking { display: inline-flex; align-items: center; gap: 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px 14px 14px 4px; padding: 11px 15px; box-shadow: var(--shadow); color: var(--muted); font-size: 13.5px; overflow-wrap: anywhere; }
.thinking.error { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 34%, var(--line)); background: color-mix(in srgb, var(--bad) 8%, var(--surface)); gap: 12px; }
.retry { border: 1px solid currentColor; color: inherit; background: transparent; border-radius: 7px; padding: 2px 10px; font-size: 12.5px; cursor: pointer; font-family: var(--sans); }
.retry:hover { background: color-mix(in srgb, var(--bad) 12%, transparent); }
.dots { display: inline-flex; gap: 4px; }
.dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1.2s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay: .18s; }
.dots i:nth-child(3) { animation-delay: .36s; }
@keyframes pulse { 0%, 80%, 100% { opacity: .25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }

/* 输入区 */
footer.composer { position: sticky; bottom: 0; padding: 12px 20px 16px; background: linear-gradient(180deg, transparent, var(--bg) 22%); }
.composer-inner { max-width: 792px; margin: 0 auto; display: flex; align-items: flex-end; gap: 10px; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 14px; padding: 8px 8px 8px 14px; box-shadow: var(--shadow); }
.composer-inner:focus-within { border-color: var(--accent); }
textarea#q { flex: 1 1 auto; resize: none; border: 0; background: transparent; color: var(--fg); font-family: var(--sans); font-size: 14.5px; line-height: 1.5; padding: 6px 0; max-height: 132px; outline: none; }
textarea#q::placeholder { color: var(--muted); }
.send { flex: none; width: 38px; height: 38px; border-radius: 10px; border: 0; cursor: pointer; background: var(--accent); color: #fff; display: grid; place-items: center; }
.send:hover { background: var(--accent-ink); }
.send:disabled { opacity: .45; cursor: not-allowed; }
.hint { max-width: 792px; margin: 8px auto 0; text-align: center; font-size: 11.5px; color: var(--muted); }
.hint kbd { font-family: var(--mono); font-size: 10.5px; border: 1px solid var(--line-strong); border-radius: 4px; padding: 0 5px; background: var(--surface-2); color: var(--fg-soft); }

:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }

@media (prefers-reduced-motion: reduce) { .dots i { animation: none; opacity: .7; } * { scroll-behavior: auto !important; } }
@media (max-width: 560px) { .brand .sub { display: none; } .bubble-user { max-width: 84%; } .oq-grid { grid-template-columns: 1fr 1fr; } }
```

- [ ] **Step 3: 后端测试仍绿 + 人工视觉核对**

Run: `.\.conda-env\python.exe -m pytest tests/test_api_web.py -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webui`
Expected: PASS（4 项，`GET /` 仍返含 `DeepResearch` 的 HTML）

人工核对（起服务开浏览器）：
Run: `.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload`
开 `http://127.0.0.1:8000/`，确认顶栏（品牌/身份 chip/主题/新对话）、居中聊天流、底部输入区呈现，且与样机风格一致；点右上主题按钮明暗切换正常。（此时输入框尚无行为，Task 3 补。）

- [ ] **Step 4: 提交**

```powershell
git add src/deepresearch_agent/web/index.html src/deepresearch_agent/web/style.css
git commit -m "功能：Web 界面外壳与视觉(顶栏/聊天流/输入区 + 明暗令牌)"
```

---

### Task 3: 前端行为（`app.js`：会话/请求/渲染/加载/错误）

**Files:**
- Modify: `src/deepresearch_agent/web/app.js`（占位 → 完整行为）
- Test: 手动端到端（无 JS 测试框架）；全套 `pytest` 保持绿。

**Interfaces:**
- Consumes: `index.html` 元素 id（`#identity/#uid/#theme/#newchat/#stream/#thread/#q/#send`）与 `style.css` 类；后端 `POST /session/turn { question, user_id, session_id? }` → `{ session_id, report }`，其中 `report` 为 `SupplierReport = { supplier_name, recommendation, summary, risks[], evidence_table[], open_questions[] }`，`Evidence = { claim, dimension, confidence, citation:{ source_id, title, url, snippet } }`，`recommendation ∈ {insufficient_evidence, conditional, approve, reject}`。
- Produces: 完整交互（发送→加载→报告卡；多轮复用 `session_id`；身份改名；新对话；错误兜底）。

- [ ] **Step 1: 写完整 `app.js`**

`src/deepresearch_agent/web/app.js` 全量替换为：

```javascript
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const root = document.documentElement;
  const stream = $("#stream");
  const thread = $("#thread");
  const q = $("#q");
  const sendBtn = $("#send");

  // ---- 身份（localStorage）与会话（内存） ----
  const KEY = "dr_user_id";
  let userId = localStorage.getItem(KEY);
  if (!userId) {
    userId = "demo-" + Math.random().toString(36).slice(2, 8);
    localStorage.setItem(KEY, userId);
  }
  let sessionId = null;
  $("#uid").textContent = userId;

  // ---- DOM 小工具 ----
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  const scrollDown = () => { stream.scrollTop = stream.scrollHeight; };
  const NS = "http://www.w3.org/2000/svg";

  function lockIcon() {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "lock");
    svg.setAttribute("width", "13"); svg.setAttribute("height", "13");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    const rect = document.createElementNS(NS, "rect");
    rect.setAttribute("x", "5"); rect.setAttribute("y", "11"); rect.setAttribute("width", "14");
    rect.setAttribute("height", "9"); rect.setAttribute("rx", "2");
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M8 11V8a4 4 0 0 1 8 0v3");
    svg.appendChild(rect); svg.appendChild(path);
    return svg;
  }

  // ---- 报告渲染（纯函数：report → DOM，逐字渲染，不臆造） ----
  const BADGE = {
    insufficient_evidence: { text: "证据不足", cls: "warn" },
    conditional: { text: "有条件", cls: "warn" },
    approve: { text: "通过", cls: "good" },
    reject: { text: "不通过", cls: "bad" },
  };
  function renderBadge(rec) {
    const m = BADGE[rec] || { text: rec || "未知", cls: "warn" };
    const b = el("span", "badge " + m.cls);
    b.appendChild(el("span", "glyph"));
    b.appendChild(document.createTextNode(m.text));
    return b;
  }

  const CODE_RE = /companies\/([0-9A-Za-z]{18})/;
  function deriveCode(report) {
    for (const ev of report.evidence_table || []) {
      const c = ev.citation || {};
      const m = CODE_RE.exec(c.url || "");
      if (m) return m[1];
      if (/^[0-9A-Za-z]{18}$/.test(c.source_id || "")) return c.source_id;
    }
    return "";
  }

  function renderEvidenceTable(rows) {
    const wrap = el("div", "table-wrap");
    const table = el("table", "ev");
    const thead = el("thead");
    const htr = el("tr");
    ["维度", "结论", "置信", "引用"].forEach((h) => htr.appendChild(el("th", null, h)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");
    rows.forEach((ev) => {
      const tr = el("tr");
      const tdDim = el("td");
      tdDim.appendChild(el("span", "dim", ev.dimension || ""));
      tr.appendChild(tdDim);
      tr.appendChild(el("td", null, ev.claim || ""));
      const tdConf = el("td");
      const conf = el("span", "conf");
      const meter = el("span", "meter");
      const bar = el("i");
      const pct = Math.max(0, Math.min(1, Number(ev.confidence) || 0));
      bar.style.width = (pct * 100).toFixed(0) + "%";
      meter.appendChild(bar);
      conf.appendChild(meter);
      conf.appendChild(el("span", "num", pct.toFixed(2)));
      tdConf.appendChild(conf);
      tr.appendChild(tdConf);
      const tdCite = el("td");
      const c = ev.citation || {};
      const a = el("a", "cite", c.url || "");
      a.href = "#";
      a.title = [c.title, c.snippet].filter(Boolean).join(" — ");
      a.addEventListener("click", (e) => e.preventDefault());
      tdCite.appendChild(a);
      tr.appendChild(tdCite);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  const LOCKED_NOTE = "以下维度当前数据源不提供，缺失不代表无风险，须接入对应数据后另行核验。";

  function renderReport(report) {
    const card = el("article", "card");
    const head = el("div", "card-head");
    const title = el("div", "title");
    title.appendChild(el("h3", null, report.supplier_name || "解析结果"));
    const code = deriveCode(report);
    if (code) title.appendChild(el("div", "code", code));
    head.appendChild(title);
    head.appendChild(renderBadge(report.recommendation));
    card.appendChild(head);

    if (report.summary) {
      const sec = el("div", "sec");
      sec.appendChild(el("p", "eyebrow", "摘要"));
      sec.appendChild(el("p", "summary", report.summary));
      card.appendChild(sec);
    }
    if (Array.isArray(report.risks) && report.risks.length) {
      const sec = el("div", "sec");
      sec.appendChild(el("p", "eyebrow", "风险 / 提示"));
      const ul = el("ul", "risk-list");
      report.risks.forEach((r) => ul.appendChild(el("li", null, r)));
      sec.appendChild(ul);
      card.appendChild(sec);
    }
    if (Array.isArray(report.evidence_table) && report.evidence_table.length) {
      const sec = el("div", "sec");
      const eb = el("p", "eyebrow", "证据表");
      eb.appendChild(el("span", "count", report.evidence_table.length + " 条"));
      sec.appendChild(eb);
      sec.appendChild(renderEvidenceTable(report.evidence_table));
      card.appendChild(sec);
    }
    if (Array.isArray(report.open_questions) && report.open_questions.length) {
      const sec = el("div", "sec");
      sec.appendChild(el("p", "eyebrow", "待解问题 · 尚未接入的数据源"));
      sec.appendChild(el("p", "oq-note", LOCKED_NOTE));
      const grid = el("div", "oq-grid");
      report.open_questions.forEach((x) => {
        const item = el("div", "oq");
        item.appendChild(lockIcon());
        item.appendChild(el("span", null, x));
        grid.appendChild(item);
      });
      sec.appendChild(grid);
      card.appendChild(sec);
    }
    return card;
  }

  // ---- 气泡 / 加载 / 错误 ----
  function appendUser(text) {
    const wrap = el("div", "msg user");
    wrap.appendChild(el("div", "avatar u", "我"));
    wrap.appendChild(el("div", "bubble-user", text));
    thread.appendChild(wrap);
  }
  function appendThinking() {
    const wrap = el("div", "msg");
    wrap.appendChild(el("div", "avatar a", "DR"));
    const t = el("div", "thinking");
    const dots = el("span", "dots");
    dots.appendChild(el("i")); dots.appendChild(el("i")); dots.appendChild(el("i"));
    t.appendChild(dots);
    t.appendChild(document.createTextNode("研究中… planner → researcher → critic → writer"));
    wrap.appendChild(t);
    thread.appendChild(wrap);
    return wrap;
  }
  function appendAssistant(node) {
    const wrap = el("div", "msg");
    wrap.appendChild(el("div", "avatar a", "DR"));
    wrap.appendChild(node);
    thread.appendChild(wrap);
  }
  function appendError(message, retry) {
    const wrap = el("div", "msg");
    wrap.appendChild(el("div", "avatar a", "DR"));
    const box = el("div", "thinking error");
    box.appendChild(el("span", null, message));
    if (retry) {
      const b = el("button", "retry", "重试");
      b.addEventListener("click", () => { wrap.remove(); retry(); });
      box.appendChild(b);
    }
    wrap.appendChild(box);
    thread.appendChild(wrap);
  }

  // ---- 请求 ----
  async function sessionTurn(question) {
    const res = await fetch("/session/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, user_id: userId, session_id: sessionId }),
    });
    if (!res.ok) { const e = new Error("HTTP " + res.status); e.status = res.status; throw e; }
    const data = await res.json();
    sessionId = data.session_id;
    return data.report;
  }

  let pending = false;
  async function submit() {
    const text = q.value.trim();
    if (!text || pending) return;
    pending = true; sendBtn.disabled = true;
    appendUser(text);
    q.value = ""; autosize();
    const thinking = appendThinking();
    scrollDown();
    try {
      const report = await sessionTurn(text);
      thinking.remove();
      appendAssistant(renderReport(report));
    } catch (err) {
      thinking.remove();
      handleError(err, text);
    } finally {
      pending = false; sendBtn.disabled = false;
      scrollDown();
    }
  }

  function handleError(err, question) {
    let msg, retry = null;
    if (err.status === 400) { msg = "会话标识异常，已为你开新会话，请重发。"; sessionId = null; }
    else if (err.status === 404) { msg = "找不到该会话，已开新会话，请重发。"; sessionId = null; }
    else { msg = "请求失败，请重试。"; retry = () => { q.value = question; submit(); }; }
    appendError(msg, retry);
  }

  // ---- 外壳交互 ----
  function greeting() {
    thread.replaceChildren();
    thread.appendChild(el("div", "day", "新会话 · 待生成 session_id"));
    const wrap = el("div", "msg");
    wrap.appendChild(el("div", "avatar a", "DR"));
    wrap.appendChild(el("div", "thinking", "输入一家供应商名称开始核验，例如「核验示例科技股份有限公司的工商与经营范围」。"));
    thread.appendChild(wrap);
  }
  $("#newchat").addEventListener("click", () => { sessionId = null; greeting(); scrollDown(); });

  $("#theme").addEventListener("click", () => {
    const cur = root.getAttribute("data-theme")
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  });

  $("#identity").addEventListener("click", () => {
    const name = prompt("设置演示身份（user_id）：", userId);
    if (name && name.trim()) {
      userId = name.trim();
      localStorage.setItem(KEY, userId);
      $("#uid").textContent = userId;
    }
  });

  function autosize() { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 132) + "px"; }
  q.addEventListener("input", autosize);
  sendBtn.addEventListener("click", submit);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });

  scrollDown();
})();
```

- [ ] **Step 2: 手动端到端核对**

Run: `.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload`
（若默认库缺失，加 `--database data/procurement/derived/companies.sqlite3` 需先经 `create_app` 注入；本地默认路径已构建则直接可用。）

在 `http://127.0.0.1:8000/` 依次验证：
1. 首轮：输入「核验示例科技股份有限公司的工商与经营范围」→ 出现「研究中…」加载态 → 替换为报告卡（表头企业名 + 信用代码 + `证据不足` 琥珀徽章；摘要/证据表带 `local://` 引用/待解问题）。
2. 多轮指代：接着输入「它的联系方式呢」→ 报告卡仍指向同一实体（`session_id` 已复用）。
3. 新对话：点「＋新对话」→ 消息清空、回引导态；再问一句确认 `session_id` 重新生成。
4. 身份：点身份 chip 改名 → `#uid` 更新、`localStorage` 持久（刷新后仍在）。
5. 主题：右上切换明暗正常；`Enter` 发送 / `Shift+Enter` 换行；发送中按钮禁用。

- [ ] **Step 3: 全套回归**

Run: `.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-webui-full`
Expected: 全绿（后端未改动逻辑，新增 4 项 web 路由测试并入；0 失败）

- [ ] **Step 4: 提交**

```powershell
git add src/deepresearch_agent/web/app.js
git commit -m "功能：Web 界面行为(会话复用/报告卡渲染/加载态/错误兜底)"
```

---

## 收尾

三个 Task 完成后用 **superpowers:finishing-a-development-branch**：跑全套 `pytest`（应全绿）→ present 合并选项。

**真链路手验（收尾后，用户本地，可选）**：起 `uvicorn`，走上面 Task 3 Step 2 的五步；设 `DEEPSEEK_API_KEY` + `.[memory]` 后可另验 mem0 跨会话 recall 注入报告 `open_questions`。

## 文档同步（并入收尾提交，非独立 Task）

- `CLAUDE.md`「运行 Agent」的 API 行补一句：`uvicorn` 起服务后浏览器开 `http://127.0.0.1:8000/` 即为演示聊天界面。
- `docs/architecture.md`「接口」小节补：`GET /` 返 `web/index.html`、`/static` 托管前端；前端为自包含 vanilla 页，纯排版渲染 `SupplierReport`。
- `docs/project-memory.md` 追加条目 28（前端聊天界面 Demo：自包含页 + 加载态 + 报告卡 + 身份/会话/错误兜底；后端仅加静态托管）。

## Self-Review

- **Spec 覆盖**：后端静态托管（Task1）、前端外壳与视觉/明暗令牌（Task2）、会话与身份/请求/报告卡渲染/加载态/错误处理（Task3）、测试策略（Task1 后端 4 项 + Task3 手验 + 全套回归）、文档同步（收尾）均有落点。流式/鉴权/TTL/scope-graph 前端渲染按 spec 明确不做。
- **占位符**：Task1 的桩文件已标注「Task 2/3 补全」并给出完整桩内容；其余每步含完整代码与命令，无 TBD。
- **类型一致**：`create_app(database_path, memory=, session_store=)`、`WEB_DIR`、`GET /`、`/static`、`POST /session/turn {question,user_id,session_id?}`→`{session_id, report:SupplierReport}`、`SupplierReport`/`Evidence`/`Citation` 字段名跨 Task 与 `api.py`/`state.py` 一致；`index.html` 元素 id（`#identity/#uid/#theme/#newchat/#stream/#thread/#q/#send`）与 `app.js` 绑定、`style.css` 类名（含 `badge .warn/.good/.bad`）三处一致。
