(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const root = document.documentElement;
  const stream = $("#stream");
  const thread = $("#thread");
  const q = $("#q");
  const sendBtn = $("#send");
  const sidebar = $("#sidebar");
  const conversations = $("#conversations");
  const sessionCount = $("#session-count");
  const sidebarToggle = $("#sidebar-toggle");

  // ---- 身份（localStorage）与会话（内存） ----
  const KEY = "dr_user_id";
  let userId = localStorage.getItem(KEY);
  if (!userId) {
    userId = "demo-" + Math.random().toString(36).slice(2, 8);
    localStorage.setItem(KEY, userId);
  }
  const transcriptKey = () => "dr_session_transcripts:" + userId;
  function loadTranscripts() {
    try {
      const value = JSON.parse(localStorage.getItem(transcriptKey()) || "{}");
      return value && typeof value === "object" ? value : {};
    } catch (_) {
      return {};
    }
  }
  let sessionId = null;
  let sessions = [];
  let entries = [];
  let transcripts = loadTranscripts();
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

  function currentTitle() {
    const item = sessions.find((x) => x.session_id === sessionId);
    return item ? item.title : "历史对话";
  }
  function saveEntries() {
    if (!sessionId) return;
    transcripts[sessionId] = entries.slice(-60);
    try { localStorage.setItem(transcriptKey(), JSON.stringify(transcripts)); } catch (_) { /* 本地空间不足时仍可继续对话 */ }
  }
  function addEntry(entry) {
    entries.push(entry);
    saveEntries();
  }
  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "刚刚";
    const now = new Date();
    if (date.toDateString() === now.toDateString()) {
      return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  }
  function renderSessions() {
    sessionCount.textContent = String(sessions.length);
    conversations.replaceChildren();
    if (!sessions.length) {
      conversations.appendChild(el("p", "sidebar-empty", "还没有历史对话。开始一次核验后会显示在这里。"));
      return;
    }
    sessions.forEach((item) => {
      const row = el("div", "conversation-row" + (item.session_id === sessionId ? " active" : ""));
      const button = el("button", "conversation");
      button.type = "button";
      button.appendChild(el("span", "conversation-title", item.title));
      button.appendChild(el("span", "conversation-time", formatTime(item.updated_at)));
      button.addEventListener("click", () => openSession(item.session_id));
      const remove = el("button", "conversation-delete", "删除");
      remove.type = "button";
      remove.title = "删除此对话";
      remove.setAttribute("aria-label", "删除对话：" + item.title);
      remove.disabled = pending;
      remove.addEventListener("click", () => deleteSession(item));
      row.appendChild(button);
      row.appendChild(remove);
      conversations.appendChild(row);
    });
  }
  async function loadSessions() {
    try {
      const res = await fetch("/sessions?user_id=" + encodeURIComponent(userId));
      if (!res.ok) throw new Error("HTTP " + res.status);
      sessions = await res.json();
      renderSessions();
    } catch (_) {
      conversations.replaceChildren(el("p", "sidebar-empty", "暂时无法加载历史对话。"));
    }
  }
  function setSidebarOpen(open) {
    sidebar.classList.toggle("open", open);
    sidebarToggle.setAttribute("aria-expanded", String(open));
  }
  function openSession(id) {
    if (pending) return;
    sessionId = id;
    entries = Array.isArray(transcripts[id]) ? transcripts[id] : [];
    if (window.GraphPanel) GraphPanel.clear();
    greeting();
    renderSessions();
    setSidebarOpen(false);
    scrollDown();
  }
  function startNewConversation() {
    if (pending) return;
    sessionId = null;
    entries = [];
    if (window.GraphPanel) GraphPanel.clear();
    greeting();
    renderSessions();
    setSidebarOpen(false);
    q.focus();
    scrollDown();
  }

  function saveTranscripts() {
    try { localStorage.setItem(transcriptKey(), JSON.stringify(transcripts)); } catch (_) { /* 忽略本地存储失败 */ }
  }
  async function deleteSession(item) {
    if (pending) return;
    if (!confirm("删除“" + item.title + "”的全部对话记录？此操作无法恢复。")) return;
    try {
      const res = await fetch("/sessions/" + encodeURIComponent(item.session_id)
        + "?user_id=" + encodeURIComponent(userId), { method: "DELETE" });
      if (!res.ok) { const e = new Error("HTTP " + res.status); e.status = res.status; throw e; }
      sessions = sessions.filter((x) => x.session_id !== item.session_id);
      delete transcripts[item.session_id];
      saveTranscripts();
      if (sessionId === item.session_id) {
        sessionId = null;
        entries = [];
        if (window.GraphPanel) GraphPanel.clear();
        greeting();
        q.focus();
      }
      renderSessions();
    } catch (_) {
      alert("删除对话失败，请重试。");
    }
  }

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
    const code = report.credit_code || deriveCode(report);
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

  function createStreamingMessage() {
    const bubble = el("div", "bubble-assistant");
    let hasContent = false;
    const sections = new Set();
    function appendText(text) {
      bubble.textContent += text;
      hasContent = hasContent || Boolean(text);
    }
    return {
      node: bubble,
      hasContent() { return hasContent; },
      text() { return bubble.textContent; },
      append(event, data) {
        if (event === "message_delta" || event === "summary_delta") {
          appendText(data.text);
        } else if (event === "risk") {
          if (!sections.has("risk")) { appendText("\n\n提示："); sections.add("risk"); }
          appendText("\n- " + data.text);
        } else if (event === "evidence") {
          if (!sections.has("evidence")) { appendText("\n\n本地证据："); sections.add("evidence"); }
          appendText("\n- [" + (data.dimension || "证据") + "] " + (data.claim || ""));
        } else if (event === "open_question") {
          if (!sections.has("question")) { appendText("\n\n仍需核验："); sections.add("question"); }
          appendText("\n- " + data.text);
        }
      },
    };
  }

  // ---- 气泡 / 加载 / 错误 ----
  function appendUser(text) {
    const wrap = el("div", "msg user");
    wrap.appendChild(el("div", "avatar u", "我"));
    wrap.appendChild(el("div", "bubble-user", text));
    thread.appendChild(wrap);
  }
  function appendAssistantText(text) {
    const bubble = el("div", "bubble-assistant", text);
    appendAssistant(bubble);
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

  async function streamSessionTurn(question, onEvent) {
    const res = await fetch("/session/turn/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ question, user_id: userId, session_id: sessionId }),
    });
    if (!res.ok || !res.body) { const e = new Error("HTTP " + res.status); e.status = res.status; throw e; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const packets = buffer.split("\n\n");
      buffer = packets.pop();
      for (const packet of packets) {
        const event = /^event: (.+)$/m.exec(packet);
        const data = /^data: (.+)$/m.exec(packet);
        if (event && data) await onEvent(event[1], JSON.parse(data[1]));
      }
      if (done) break;
    }
  }

  let pending = false;
  async function submit() {
    const text = q.value.trim();
    if (!text || pending) return;
    pending = true; sendBtn.disabled = true;
    appendUser(text);
    addEntry({ type: "user", text });
    q.value = ""; autosize();
    const thinking = appendThinking();
    scrollDown();
    try {
      let streamed = null;
      await streamSessionTurn(text, async (event, data) => {
        if (event === "session") {
          sessionId = data.session_id;
          saveEntries();
          renderSessions();
        }
        else if (event === "progress") thinking.lastChild.textContent = data.message;
        else if (event === "graph_subgraph") {
          if (window.GraphPanel) GraphPanel.render(data);
        }
        else if (event === "report_start") {
          thinking.remove();
          streamed = createStreamingMessage();
          appendAssistant(streamed.node);
        } else if (streamed && event !== "complete") {
          streamed.append(event, data);
          await new Promise(requestAnimationFrame);
        } else if (event === "complete" && streamed && !streamed.hasContent()) {
          streamed.append("message_delta", { text: "服务端未返回可显示的正文。请重启本地 Uvicorn 服务后重试。" });
        }
        if (event === "complete" && streamed) {
          addEntry({ type: "assistant", text: streamed.text() });
          await loadSessions();
        }
        scrollDown();
      });
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
    if (err.status === 400 || err.status === 404) {
      entries = [];
      greeting();
      renderSessions();
    }
    appendError(msg, retry);
  }

  // ---- 外壳交互 ----
  function renderThread() {
    thread.replaceChildren();
    thread.appendChild(el("div", "day", sessionId ? "当前会话 · " + currentTitle() : "新会话 · 待生成 session_id"));
    if (entries.length) {
      entries.forEach((entry) => {
        if (entry.type === "user") appendUser(entry.text || "");
        if (entry.type === "assistant") appendAssistantText(entry.text || "");
      });
      return;
    }
    const wrap = el("div", "msg");
    wrap.appendChild(el("div", "avatar a", "DR"));
    wrap.appendChild(el("div", "thinking", sessionId
      ? "已恢复这段历史对话。你可以继续追问该供应商。"
      : "输入一家供应商名称开始核验，例如「核验示例科技股份有限公司的工商与经营范围」。"));
    thread.appendChild(wrap);
  }

  function greeting() {
    renderThread();
  }
  $("#newchat").addEventListener("click", startNewConversation);
  $("#newchat-side").addEventListener("click", startNewConversation);
  sidebarToggle.addEventListener("click", () => setSidebarOpen(!sidebar.classList.contains("open")));

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
      sessionId = null;
      entries = [];
      transcripts = loadTranscripts();
      if (window.GraphPanel) GraphPanel.clear();
      greeting();
      loadSessions();
    }
  });

  function autosize() { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 132) + "px"; }
  q.addEventListener("input", autosize);
  sendBtn.addEventListener("click", submit);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });

  greeting();
  loadSessions();
  scrollDown();
})();
