# 网页端 LLM 流式呈现设计（检索结果交 DeepSeek 生成）

> 状态：设计已确认（三节 approve）。取代前一版「graph_viz 侧边图」计划的呈现部分；Neo4j 兜底并入本 spec。下一步 writing-plans。

## 目标

把网页流式端点 `/session/turn/stream` 的**呈现层**从确定性文本切块（`_report_message_chunks`）换成 **DeepSeek 流式生成**：检索/writer 定稿的结构化报告（命名核验 / scope / graph 三种）交 DeepSeek 逐 token 流式生成中文呈现，推给前端。无 `DEEPSEEK_API_KEY` 时回退极简兜底文本（保 CI/断网不崩）。一并修 Neo4j 裸启动连不上的静默降级。

## 核心约束（守红线）

**LLM 只是呈现层，不是事实来源、不改结论、不检索、不推断。**

- LLM 拿到的是 writer **已定稿**的结构化报告 JSON（结论 `recommendation`、候选、控制人、证据均已固定），不是原始数据。
- **结论纵深防御**：`recommendation` 对应的结论句（`_RECOMMENDATION_TEXT`）由后端在 LLM 正文前**确定性硬发一次**，不进 LLM。即使 LLM 不听 prompt，结论文字也是后端硬写的，`insufficient_evidence` 改不成「无风险」。
- system prompt 严格约束：只复述报告事实、绝不添加、绝不推断产能/交期/认证、经营范围按原文、保留企业名/信用代码/控制人原文、围标线索标「线索级·须人工复核」。
- 数据越境：全部检索结果进 prompt——**用户明确决定扩大豁免**（与记忆层同级；核心本地化红线文本仍在、仅本线豁免）。CI 零网络零 key（fake client / 无 key 兜底），真链路标 `@pytest.mark.llm`。

## 架构

### 组件 1：`llm/deepseek.py::build_deepseek_polisher`

复用现有 `build_deepseek_classifier` 的 OpenAI client 模式（同文件、同 `DEEPSEEK_API_KEY`/`base_url`）：

```python
def build_deepseek_polisher(api_key=None, model="deepseek-chat", base_url="https://api.deepseek.com", client=None):
    # client is None 且无 key/无 openai → return None（降级信号）
    def stream_presentation(report_type: str, report: dict) -> Iterator[str]:
        user_payload = _render_report_for_llm(report_type, report)   # 把报告 JSON 转成给 LLM 的结构化文本
        resp = client.chat.completions.create(
            model=model, temperature=0, stream=True,
            messages=[{"role": "system", "content": _PRESENTER_SYSTEM_PROMPT},
                      {"role": "user", "content": user_payload}],
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    return stream_presentation
```

- `_PRESENTER_SYSTEM_PROMPT`：上述约束规则（常量）。
- `_render_report_for_llm(report_type, report)`：纯函数，把三种报告的关键字段（named：supplier_name/summary/risks/evidence；scope：query/candidates；graph：query/candidates/shared_controllers）拼成给 LLM 的输入文本。**不含结论句**（结论后端硬发）。
- 异常（网络/超时）→ 生成器内 try，中断则停止 yield（前端已收到的照显示，complete 照发）。

### 组件 2：API 流式端点接入

`create_app` 建一次 `polisher = build_deepseek_polisher()`（有 key→callable，无 key→None）。改流式 complete 分支（api.py:152-162）：

```python
                store.save(session)
                report_type, report = _resolve_report(state)          # Task 1 已加
                yield _sse("report_start", {
                    "report_type": report_type,
                    "title": report.get("supplier_name") or report.get("query", ""),
                    "recommendation": report["recommendation"],
                })
                # 结论句：后端硬发，不进 LLM（纵深防御）
                yield _sse("message_delta", {"text": _conclusion_line(report)})
                if polisher is not None:
                    try:
                        for tok in polisher(report_type, report):
                            yield _sse("message_delta", {"text": tok})
                    except Exception:
                        for text in _report_message_chunks(report, report_type):
                            yield _sse("message_delta", {"text": text})
                else:
                    for text in _fallback_chunks(report, report_type):
                        yield _sse("message_delta", {"text": text})
                yield _sse("complete", {"session_id": session.session_id})
```

- `_conclusion_line(report)`：`\n\n结论：` + `_RECOMMENDATION_TEXT[recommendation]`。
- `_fallback_chunks`：无 key 兜底——极简，`title + 候选名单`（复用现 `_report_message_chunks` 即可，无需另写；spec 采用「无 key 直接复用 `_report_message_chunks`」，不额外造函数）。
- 也删除 `if state.report is None: raise`（`_resolve_report` 已处理三报告 + None）。
- `create_app` 新增可选参数 `polisher=None`（测试注入 fake，覆盖有/无两路）。

### 组件 3：Neo4j 兜底（一并修）

- `neo4j_backend.py::from_env`：`password` 默认 `os.environ.get("NEO4J_PASSWORD", "devpassword")`（对齐 docker-compose 默认；仅本地）。
- `create_app`：注入后打印一行 `[graph] Neo4j backend: connected` / `unavailable (fallback to scope)`，不再静默。用 `logging`（非 print）。

### 前端

**零改动**。前端已消费 `message_delta` 逐字显示，LLM 的 token 流形状完全一致。命名/scope/graph 都是文本流。

## 数据流（一轮）

```
用户问题 → SSE
  → session / progress×N（planner 判复杂度 → researcher 检索）
  → report_start{report_type,title,recommendation}
  → message_delta（结论句，后端硬发）
  → [有 key] message_delta×N（DeepSeek 流式生成正文）
    [无 key] message_delta×N（_report_message_chunks 兜底）
    [LLM 异常] 回退 _report_message_chunks
  → complete
```

## 降级链

| 情况 | 行为 |
|---|---|
| 无 `DEEPSEEK_API_KEY` | polisher=None → `_report_message_chunks` 确定性兜底 |
| LLM 网络/超时异常 | 生成器内 try → 回退 `_report_message_chunks` |
| Neo4j 没起 | graph_searcher=None（启动日志提示）→ 复杂查询降级 scope |
| 缺 `.[rag]`/索引 | scope_retriever=None → 命名核验 |

结论句在任何路径都由后端硬发，不受 LLM 影响。

## 测试策略

- **`build_deepseek_polisher`**（`tests/test_deepseek_polisher.py`，fake client，零网络）：注入 fake client 返回分块 → `stream_presentation("graph", report)` yield 出内容；无 key/无 client → 返回 None。
- **`_render_report_for_llm`**（纯函数）：三报告 → 输入文本含候选名/控制人，**不含结论句**（防重复/防 LLM 改结论）。
- **API**（`tests/test_api_stream_retrieval.py` 扩展）：
  - 注入 fake polisher → 流式 body 含结论句 + polisher 生成内容 + `complete`。
  - `polisher=None` → body 含 `_report_message_chunks` 兜底文本（现有断言）。
  - polisher 抛异常 → body 仍含兜底文本、不崩、有 `complete`。
- **真链路** `@pytest.mark.llm`：设 `DEEPSEEK_API_KEY` 手验 DeepSeek 流式。
- 全套 `pytest` 保持绿（CI 零 key 走兜底）。

## 明确不做（后续）

- graph_viz 侧边 SVG（前一版计划，暂缓——先看 LLM 流式效果）。
- `/research` 端点接 LLM。
- 本地 Ollama 呈现（`config.py` 已留接口，本线走 DeepSeek）。
- LLM 参与检索或结论判定（红线，永不做）。

## Self-Review

- **占位符**：无 TBD；polisher 代码、prompt 约束、接入分支、兜底、Neo4j 兜底、测试均具体。
- **一致性**：`build_deepseek_polisher`/`stream_presentation(report_type,report)`/`_render_report_for_llm`/`_conclusion_line`/`_resolve_report`（Task 1 已存在）/`_report_message_chunks(report,report_type)`（Task 1 已改签名）/`create_app(...,polisher=)` 跨组件一致；报告字段与 `state.py` 对齐。
- **红线**：LLM 只呈现定稿报告；结论后端硬发纵深防御；prompt 严格约束；数据越境经用户明确豁免；CI 零 key 兜底。
- **范围**：单一计划可覆盖（polisher + prompt / API 接入 + 兜底 / Neo4j 兜底 / 测试）。graph_viz/`/research`/Ollama 切出。
- **歧义**：无 key 与 LLM 异常都回退 `_report_message_chunks`（不另造兜底函数）；结论句独立硬发；Neo4j 默认密码 `devpassword` 仅本地。
