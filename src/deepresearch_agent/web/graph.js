/* 股权图谱线索面板：确定性分层布局 + 手写 SVG，零依赖。
   只陈述 graph_subgraph 载荷里的字段；线索级证据，须人工复核。 */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const NODE_W = 150, NODE_H = 34, GAP_X = 24, ROW_GAP = 112, PAD = 48;
  const KIND_LABEL = {
    seed: "候选企业",
    shareholder: "直接股东",
    investment: "对外投资",
    controller: "最终控制人 · 线索",
  };
  const EDGE_LABEL = { shareholding: "持股", investment: "投资", control_clue: "控制线索" };

  const panel = document.getElementById("graph-panel");
  const svg = document.getElementById("graph-svg");
  const emptyEl = document.getElementById("graph-empty");
  const legendEl = document.getElementById("graph-legend");
  const footEl = document.getElementById("graph-foot");
  const tooltip = document.getElementById("graph-tooltip");
  const collapseBtn = document.getElementById("graph-collapse");
  const toggleBtn = document.getElementById("graph-toggle");

  let view = null;      // 当前 viewBox {x,y,w,h}
  let selected = null;  // 选中节点 id

  function svgEl(tag, attrs, text) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  const short = (s, max) => (s && s.length > max ? s.slice(0, max - 1) + "…" : s || "");

  // ---- 布局：kind 定行（共享控制人 / 控制人+股东 / 种子 / 对外投资），列按相连种子聚簇 ----
  function layout(payload) {
    const rowOf = (n) => {
      if (n.kind === "seed") return 2;
      if (n.kind === "investment") return 3;
      return n.is_shared_controller ? 0 : 1;
    };
    const rows = [[], [], [], []];
    payload.nodes.forEach((n) => rows[rowOf(n)].push(n));
    rows[2].sort((a, b) => (b.score - a.score) || (a.id < b.id ? -1 : 1));
    const seedCol = new Map(rows[2].map((n, i) => [n.id, i]));
    const anchors = new Map();
    payload.edges.forEach((e) => {
      const seed = seedCol.has(e.source) ? e.source : (seedCol.has(e.target) ? e.target : null);
      const other = seed === e.source ? e.target : e.source;
      if (seed == null || seedCol.has(other)) return;
      if (!anchors.has(other)) anchors.set(other, []);
      anchors.get(other).push(seedCol.get(seed));
    });
    const anchorOf = (id) => {
      const a = anchors.get(id);
      return a && a.length ? a.reduce((x, y) => x + y, 0) / a.length : Number.MAX_SAFE_INTEGER;
    };
    [0, 1, 3].forEach((r) =>
      rows[r].sort((a, b) => (anchorOf(a.id) - anchorOf(b.id)) || (a.id < b.id ? -1 : 1)));

    const liveRows = [0, 1, 2, 3].filter((r) => rows[r].length);
    const rowY = new Map(liveRows.map((r, i) => [r, PAD + i * ROW_GAP]));
    const cols = Math.max(...liveRows.map((r) => rows[r].length));
    const width = PAD * 2 + cols * NODE_W + (cols - 1) * GAP_X;
    const xy = new Map();
    liveRows.forEach((r) => {
      const rowW = rows[r].length * NODE_W + (rows[r].length - 1) * GAP_X;
      rows[r].forEach((n, i) => xy.set(n.id, {
        x: (width - rowW) / 2 + i * (NODE_W + GAP_X),
        y: rowY.get(r),
      }));
    });
    return { xy, width, height: PAD * 2 + (liveRows.length - 1) * ROW_GAP + NODE_H };
  }

  function edgePath(a, b) {
    const sx = a.x + NODE_W / 2, tx = b.x + NODE_W / 2;
    if (a.y === b.y) {  // 同行相连（如种子间投资）：上方绕行
      return `M ${sx} ${a.y} C ${sx} ${a.y - 56}, ${tx} ${b.y - 56}, ${tx} ${b.y}`;
    }
    const down = a.y < b.y;
    const sy = down ? a.y + NODE_H : a.y;
    const ty = down ? b.y : b.y + NODE_H;
    const my = (sy + ty) / 2;
    return `M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`;
  }

  // ---- tooltip ----
  function showTooltip(n, ev) {
    const lines = [n.name, (KIND_LABEL[n.kind] || n.kind) + " · " + (n.node_type === "person" ? "自然人" : "企业")];
    if (n.kind === "seed" && n.score) lines.push("检索得分 " + Number(n.score).toFixed(2));
    if (n.is_shared_controller) {
      lines.push(n.concentrated_industries && n.concentrated_industries.length
        ? "同行业+同控制人线索：" + n.concentrated_industries.join("、") + " · 须人工复核"
        : "控制多家候选企业 · 须人工复核");
    }
    tooltip.textContent = lines.join("\n");
    tooltip.hidden = false;
    moveTooltip(ev);
  }
  function moveTooltip(ev) {
    const box = svg.parentElement.getBoundingClientRect();
    tooltip.style.left = Math.max(0, Math.min(ev.clientX - box.left + 12, box.width - 180)) + "px";
    tooltip.style.top = (ev.clientY - box.top + 12) + "px";
  }
  function hideTooltip() { tooltip.hidden = true; }

  // ---- 点击高亮相邻边 ----
  function toggleSelect(id, incident) {
    if (selected === id) { clearSelect(); return; }
    selected = id;
    svg.classList.add("has-sel");
    svg.querySelectorAll(".hl, .sel").forEach((el) => el.classList.remove("hl", "sel"));
    const hit = new Set([id]);
    (incident.get(id) || []).forEach((g) => {
      g.classList.add("hl");
      hit.add(g.dataset.source); hit.add(g.dataset.target);
    });
    svg.querySelectorAll(".gnode").forEach((el) => {
      if (hit.has(el.dataset.id)) el.classList.add("sel");
    });
  }
  function clearSelect() {
    selected = null;
    svg.classList.remove("has-sel");
    svg.querySelectorAll(".hl, .sel").forEach((el) => el.classList.remove("hl", "sel"));
  }

  // ---- 渲染 ----
  function render(payload) {
    if (!payload || !Array.isArray(payload.nodes) || !payload.nodes.length) return;
    clearSelect();
    svg.replaceChildren();
    const { xy, width, height } = layout(payload);
    const root = svgEl("g", { class: "graph-root" });
    svg.appendChild(root);

    const sharedIds = new Set(
      payload.nodes.filter((n) => n.is_shared_controller).map((n) => n.id));
    const incident = new Map(); // 节点 id → 关联边 <g> 列表
    (payload.edges || []).forEach((e) => {
      const a = xy.get(e.source), b = xy.get(e.target);
      if (!a || !b) return;
      const shared = e.kind === "control_clue" && sharedIds.has(e.source);
      const g = svgEl("g", { class: "gedge " + e.kind + (shared ? " shared" : "") });
      g.dataset.source = e.source; g.dataset.target = e.target;
      const path = svgEl("path", { d: edgePath(a, b), fill: "none" });
      path.appendChild(svgEl("title", {}, e.kind === "control_clue"
        ? EDGE_LABEL[e.kind] + (e.via_person ? " · 经自然人关联 · 低置信" : "") + " · 须人工复核"
        : EDGE_LABEL[e.kind] + (e.holding_pct ? " " + e.holding_pct : "")));
      g.appendChild(path);
      if (e.holding_pct) {
        g.appendChild(svgEl("text", {
          x: (a.x + b.x) / 2 + NODE_W / 2,
          y: (Math.min(a.y, b.y) + Math.max(a.y, b.y) + NODE_H) / 2 - 4,
          class: "pct",
        }, e.holding_pct));
      }
      root.appendChild(g);
      [e.source, e.target].forEach((id) => {
        if (!incident.has(id)) incident.set(id, []);
        incident.get(id).push(g);
      });
    });

    payload.nodes.forEach((n) => {
      const p = xy.get(n.id);
      const cls = ["gnode", n.kind, n.node_type === "person" ? "person" : "company"];
      if (n.is_shared_controller) cls.push("shared");
      const g = svgEl("g", { class: cls.join(" "), transform: `translate(${p.x} ${p.y})` });
      g.dataset.id = n.id;
      g.appendChild(svgEl("rect", {
        width: NODE_W, height: NODE_H,
        rx: n.node_type === "person" ? 4 : NODE_H / 2,  // 图例：○ 企业 / □ 自然人
      }));
      g.appendChild(svgEl("text", {
        x: NODE_W / 2, y: NODE_H / 2 + 4, "text-anchor": "middle",
      }, short(n.name, 10)));
      g.addEventListener("mouseenter", (ev) => showTooltip(n, ev));
      g.addEventListener("mousemove", moveTooltip);
      g.addEventListener("mouseleave", hideTooltip);
      g.addEventListener("click", (ev) => { ev.stopPropagation(); toggleSelect(n.id, incident); });
      root.appendChild(g);
    });

    view = { x: 0, y: 0, w: width, h: height };
    applyView();
    panel.classList.add("has-data");
    legendEl.hidden = false;
    emptyEl.hidden = true;
    footEl.hidden = !payload.truncated;
    toggleBtn.hidden = false;
  }

  function clear() {
    svg.replaceChildren();
    view = null;
    clearSelect();
    hideTooltip();
    panel.classList.remove("has-data", "open");
    legendEl.hidden = true;
    emptyEl.hidden = false;
    footEl.hidden = true;
    toggleBtn.hidden = true;
  }

  // ---- 缩放 / 平移（操作 viewBox） ----
  function applyView() {
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  }
  svg.addEventListener("wheel", (ev) => {
    if (!view) return;
    ev.preventDefault();
    const factor = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
    const box = svg.getBoundingClientRect();
    const px = view.x + ((ev.clientX - box.left) / box.width) * view.w;
    const py = view.y + ((ev.clientY - box.top) / box.height) * view.h;
    const w = Math.max(120, Math.min(view.w * factor, 20000));
    const h = w * (view.h / view.w);
    view = { x: px - (px - view.x) * (w / view.w), y: py - (py - view.y) * (h / view.h), w, h };
    applyView();
  }, { passive: false });
  /* 不用 setPointerCapture：捕获会把拖后 click 重定向到 svg，破坏节点点击。
     以 3px 阈值区分点击与拖拽，拖出画布即结束拖拽。 */
  let drag = null, dragMoved = false;
  svg.addEventListener("pointerdown", (ev) => {
    if (!view) return;
    drag = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y };
    dragMoved = false;
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag || !view) return;
    if (!dragMoved && Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) <= 3) return;
    dragMoved = true;
    const box = svg.getBoundingClientRect();
    view.x = drag.vx - (ev.clientX - drag.x) * (view.w / box.width);
    view.y = drag.vy - (ev.clientY - drag.y) * (view.h / box.height);
    applyView();
  });
  svg.addEventListener("pointerup", () => { drag = null; });
  svg.addEventListener("pointerleave", () => { drag = null; });
  svg.addEventListener("click", () => {
    if (dragMoved) { dragMoved = false; return; }  // 拖拽结束的 click 不清除选中
    clearSelect();
  });

  // ---- 面板收起 / 窄屏抽屉 ----
  collapseBtn.addEventListener("click", () => {
    if (matchMedia("(max-width: 1100px)").matches) panel.classList.remove("open");
    else panel.classList.toggle("collapsed");
  });
  toggleBtn.addEventListener("click", () => panel.classList.toggle("open"));

  window.GraphPanel = { render, clear };
})();
