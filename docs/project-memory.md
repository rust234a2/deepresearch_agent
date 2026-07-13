# 项目记忆

更新时间：2026-06-23

本文件记录已经确认的工程决策和项目状态。后续会话开始前应先阅读本文件，并以用户最新指令为准。

## 用户协作偏好

- 全程使用中文沟通。
- 每完成一个模块提交 Git，提交信息使用中文。
- 较大功能在 `feature/*` 隔离分支实施，完成、测试全绿后合并回 `master` 并删除分支（近两个功能在 `feature/rag-scope-retrieval`、`feature/agent-scope-search`）。允许直接在 `master` 做文档/小修。
- 不覆盖或回退用户未提交的文件修改。

## 当前目标和数据原则

项目面向中国制造业供应商工商研究。企查查清洗 CSV 是企业事实标准，SQLite 是可重复生成的查询产物，Agent 只陈述数据源实际提供的字段，绝不把数据缺失解释为“没有风险”。

数据本地化：跨企业语义检索使用**本地** bge-small-zh-v1.5 + 本地 FAISS，受限工商数据不出本机。当前**不**使用实时 API、网页爬虫、外部嵌入 API、Qdrant、GraphRAG 或 MCP。RAGAS、Phoenix、golden cases 和正式评估层后置。

## 已完成模块

1. FastAPI 和 CLI 入口。
2. LangGraph Planner、Researcher、Critic、Writer 编排循环。
3. Domain Pack 工具白名单和研究维度。
4. 中国制造业候选名单生成器。
5. 企查查 Excel 清洗器，输出企业、联系方式和拒绝记录。
6. 以清洗字段为标准的 `CompanyProfile` 和 `CompanyContact` 强类型模型。
7. SQLite schema 与原子数据库构建器（当前 version 2）。
8. 只读 `CompanyRepository`，支持信用代码、法定名称和曾用名查询、歧义结果，以及 chunk / 索引元数据读取。
9. `get_company_profile` 和 `get_company_contact` 两个私有数据工具。
10. 基于六个工商维度的 Agent 证据生成路径。
11. 旧能力、合规、财务、采购历史组合模型和两家英文演示供应商已删除。
12. 一组质量修复：资本金额支持“亿”单位、API 启动时单次建图与仓库、企业识别去假歧义（子串被更具体名称支配则丢弃）、`get_contact` 只查联系方式表、工具失败时保留错误信息。
13. **RAG 语义经营范围检索模块（`rag/`）**：经营范围条款感知切块 → bge-small-zh-v1.5 嵌入 → FAISS（`IndexIDMap(IndexFlatIP)`）→ `ScopeRetriever` → `search_company_scope` 工具 + 独立 CLI。schema 升到 version 2（新增 `business_scope_chunks`、`scope_index_metadata`）。依赖 `.[rag]` 可选 extra。
14. **scope 检索端到端接入 Agent（方案 A）**：planner 的 `not_found` 在 `enable_scope=True` 时路由到 `scope_search_node`，输出 `ScopeSearchReport` 候选清单（企业 + 命中条款 + 评分，`recommendation` 固定 `insufficient_evidence`）。`enable_scope` 仅 CLI 启用，`/research` API 响应形状不变；核验指定企业流程不变；缺 `.[rag]`/索引时懒加载降级为“不可用”报告。**（注：第 15 条起 `scope_search_node` 已被 C2 撤销，检索并入 researcher。）**
15. **GraphRAG 股权关系栈（A3–B7）**：股权清洗与 `graph_nodes` 表（schema 升到 version 4）→ 只读 `CompanyRepository` 股东/投资/图节点边读取 → 内存有向图 `OwnershipGraph` → 图遍历（ego / 最终控制人 / 共同控制人 / 最短路径，`fund` 类型不外扩）→ 混合检索 `hybrid_search`（scope 种子 + 子图装配 + 共享控制人）。关联方/共享控制人为**线索级**（`via_person` 低置信、标“须人工复核”），绝不作控制关系或围标认定。基金/机构噪声用 `FUND_NOISE_KEYWORDS` 过滤（已知缺口：中文名外资/国资机构漏过）。
16. **C1 查询复杂度分类器**：`classify_complexity(query, repository, llm)` → simple/medium/complex。确定性启发式（关系关键词 + 具名信号）为兜底；可选 DeepSeek 分类器（OpenAI 兼容，`.[llm]` extra，`DEEPSEEK_API_KEY`）只精修。**全项目唯一 LLM 环节，只发查询文本、只做分类**，无 key/无依赖/异常自动回退启发式。
17. **C2 查询编排（检索/生成分层）**：图收敛为纯线性 `planner → researcher → critic → writer`。planner 解析 + 分类（不检索）；**researcher = 检索层**，按 `解析状态 × 复杂度 × 是否启用` 分派 `named`(四工具) / `scope` / `graph`(缺 searcher 且 scope 可用则回退) / `unresolved`，只检索、落 state 中间态；**writer = 唯一生成层**，按 `retrieval_mode` 出 `SupplierReport`/`ScopeSearchReport`/`GraphSearchReport`，所有叙述与不可用提示在此。撤销 `scope_search_node`/`graph_search_node` 独立节点与 planner 条件路由。`--graph` 语义变为“允许图检索、由复杂度决定用不用”；`/research` API 形状不变。合并了原 C3（结构化生成即 writer 单独做）。
18. **C4 降级链 + 降级留痕**：graph **运行时抛异常**（非缺失）时——有 scope 就**降级 scope**（`retrieval_available` 重置后重试 scope）、无 scope 记“无可用降级路径”；scope 运行时异常为终点“不可用”。**只有运行时失败**追加到新字段 `state.degradations`，配置性缺失（检索器 None、LLM 回退启发式）不记；writer 把 `degradations` 插入报告 `open_questions` 最前面。不做重试（YAGNI）；`graph.py`/`cli.py`/`api.py`/schema 均不动。**至此 GraphRAG + 查询编排路线图（A–C）收尾。**

19. **N1 股权图后端接口抽象**（引入 Neo4j 替换内存图的第一步，纯重构、零行为变化）：新增 `ownership_backend.py` 的 `OwnershipGraphBackend` 协议（`has_node`/`display_name`/`ultimate_controllers`/`direct_neighbors`）+ `InMemoryOwnershipBackend`；`NeighborEdge` 从 `graph_retrieval` 迁入;`hybrid_search`/`assemble_subgraph_context` 改吃 backend；`graph.py` 灌图后包 backend。`ego`/`common_controllers`/`shortest_path` 不在协议（非 Agent 热路径，保留）。**N2 待做**：`.[neo4j]` 可选 extra + 本地 Docker + SQLite→Neo4j 灌图 + Cypher 版 `Neo4jBackend` + 双实现对拍（CI 跑内存实现、真 Neo4j 测试标 slow 本地跑）；Neo4j 必须本地自建（数据本地化红线，不用云 Aura）。

20. **N2 Neo4j 股权图后端**（Neo4j 替换内存图成为生产图引擎）：新增 `neo4j_backend.py` 的 `Neo4jBackend`——用 Cypher 把 `ultimate_controllers`（变长路径 + `none(...fund)` 路径谓词 + `is_person OR 无非 fund 父` 终点判定）与邻居下推到服务端；`from_env()` 读 `NEO4J_*` 建 driver。灌图脚本 `scripts/build_ownership_neo4j.py`（SQLite→Neo4j 幂等 MERGE）。`_build_graph_searcher` 改建 `Neo4jBackend.from_env()`，连不上→None→C4 决策期回退 scope；`InMemoryOwnershipBackend` 退居测试替身 + 对拍基准。`.[neo4j]` extra、本地 `docker-compose.yml`（仅本地，不用云 Aura）、`@pytest.mark.neo4j` 对拍测试（默认排除，连不上跳过；本会话已真起 Neo4j 跑绿，Cypher 与内存实现逐条相等）。**via_person 语义**：Cypher 取"任一有效路径经自然人"（内存取 BFS 首达），fixture 上逐条相等。可视化白送：Neo4j Browser（7474）。
21. **N3 业务/行业层（已完成）**：新增 `CompanyRepository.iter_company_industries()`（读 `gb_industry_*` 四级名，`CompanyIndustry` 模型）+ 灌图脚本 `build_industry_neo4j`（加在 `build_ownership_neo4j.py`）：从登记的国标四级行业名确定性 MERGE `(:Industry {node_id="ind:{level}:{name}", name, level})` + `(:Industry)-[:SUBCLASS_OF]->(:Industry)` 层级链 + `(:Entity)-[:IN_INDUSTRY]->(:Industry)` 归属边（MATCH 已有 Entity，不造孤儿）。幂等、只清行业子图不碰股权。**全确定性、无 LLM、不结构化 `business_scope`**；关系类型用英文（与 SHAREHOLDING/INVESTMENT 一致）。对拍真 Neo4j 跑绿（节点数=distinct、归属边=有行业公司数、层级、幂等、不越界；甲乙丙同四级验证共享同一小类）。测试注意：主 procurement fixture `graph_nodes` 为 0，行业测试用 `ownership_links`（有 Entity 节点，已补相同四级行业）。**下一块 N4（业务/行业检索接入 Agent，待做）**：业务名→行业名模糊映射 + 语义 scope + 新报告，接进 `run_research`。

22. **N4 graph 报告"同行业+同控制人"围标线索**（把 N3 行业层变成 Agent 尽调信号）：后端协议加 `company_industry(node_id) -> str | None`（`Neo4jBackend` 查 `IN_INDUSTRY`；`InMemoryOwnershipBackend` 返 None → 优雅降级、不误报、N2 对拍不破）；`assemble_subgraph_context` 给每个共享控制人算 `concentrated_industries`（它控制的候选里 ≥2 家落同一行业的行业名）；字段透传 `SharedController`→`SharedControllerFinding`；writer 非空则 note 升级"同行业（X）+同控制人，疑似围标/集中度线索，须人工复核"、summary 追加计数。**仍线索级、须人工复核、绝不认定围标**（同名自然人可能非同一人；同控制人≠实际串通）；无 LLM。检测逻辑 CI 用假后端测，真 Neo4j 端到端另测（甲乙丙同四级行业+共享控制人→出线索）。业务价值：发现"看着像 N 家竞争、其实一只手"的虚假竞争/围标嫌疑。

23. **Eval v1 确定性评测机制**（新 `eval/` 包 + `eval` CLI 子命令）：只测两块真决策——**企业识别 P/R**（`resolve_supplier`，`run_entity_resolution`，零下载 CI 核心）、**scope recall@k**（`ScopeRetriever`，`run_scope_recall`，标 `@pytest.mark.slow` 需 bge）。`models.py`(GoldenEntityCase/GoldenScopeCase + 指标模型) + `metrics.py`(纯集合运算) + `runner.py`(复用 `run_research` 同源组件、不建第二条路径)。推荐准确率/风险命中率 = **N/A**（Agent 固定 insufficient_evidence）；GraphRAG 精准率后置（via_person 同名假阳性数据内无真值）。**不引入 RAGAS/LlamaIndex/Phoenix**（LLM-as-judge 撞本地化红线、顺序应在确定性基线之后；Phoenix 留作后续本地调试）。双轨 golden：合成提交（`evals/procurement/*.synthetic.yaml`，CI 跑 accuracy=1.0）+ 真实本地（`*.local.yaml` gitignore）。CLI：`python -m deepresearch_agent.cli eval entity|scope --database ... --cases ...`（手动分派，单问题路径向后兼容）。取代作废的 2026-06-18 旧 eval spec。

24. **Phoenix 本地追踪**（可观测性,只做追踪/可视化,不用 LLM-eval、不引入外部 LLM）：新 `observability.py`——`configure_tracing`(幂等,可注入 exporter,**从本模块持有的 provider 取 tracer、不走 OTel 全局 set_tracer_provider**——它进程内只可设一次无法重置) + `get_tracer`(未配置返 None → 透传零开销) + `reset_tracing` + `traced_node`(图层包装器)。`build_graph(enable_tracing=)` 用 `traced_node` 手动包 planner/researcher/critic/writer 四节点（attr_fn 从返回 state 抽标量:resolution_status/complexity_level/retrieval_mode/候选数/report_type/degradations 等），`run_research(enable_tracing=)` 配置追踪 + root span `research`；CLI `--trace`。**红线**：默认关（正常/CI/API 零影响）、仅本地 OTLP→localhost Phoenix（绝不指远程）、DeepSeek 只记 level/method 不记企业数据、`nodes.py` 不动。`.[trace]` extra（opentelemetry-sdk，轻）；Phoenix 查看器（`arize-phoenix`）本地单独 `pip install` + `phoenix serve`，不作硬依赖。测试用 `InMemorySpanExporter`（`importorskip`，本会话真跑绿,端到端断言 span 树）。

25. **真实企业识别 golden 起草工具**（补 Eval v1 的真实 golden 缺口）：新 `eval/golden_gen.py`（纯逻辑）+ `scripts/generate_entity_golden.py`（薄 CLI）+ `CompanyRepository.iter_aliases()`（取全部 `(代码, 曾用名)`）。核心是**多重映射** `name_to_codes: 归一化名→代码集`（over 法定名 ∪ 曾用名，归一化用 `normalize_company_name`），派生四类题：**resolved 法定名/曾用名**（映射唯一 `== {code}`，天然排除同名/被 alias 撞名的）、**ambiguous**（映射 ≥2 代码，`expected_candidate_codes`=撞名集）、**not_found**（合成名，`_contains_name` 校验库中无名被其包含）。**真值全取自 DB 原始事实、绝不调 `resolve_text` 反推**（独立真值红线）；但与 `resolve_text` 语义可证明一致（`_drop_dominated_matches` 只丢真子串、等长同名都保留），闭环测试把生成题喂 `run_entity_resolution` 断言 `accuracy==1.0`、并断言 ambiguous 候选集 == `resolve_text` 真实返回。确定性：`sorted` 后再 `rng.shuffle(seed)`。**红线**：脚本 stdout 只打印各类条数，真企业名只写进 gitignored 的 `evals/procurement/*.local.yaml`（起草者不读）。逻辑对现场构建的合成 fixture 做 TDD（含预置同名对），零真数据；真实 P/R 由用户本地跑脚本产出。不改 `entity_resolution_metrics`、不做 scope、不做全量属性测试。终审（opus）真机验证子串对撞/alias 支配/英文边界/三重同名场景均一致。**Task2 修 brief 一处：fixture 读源 CSV 用 `utf-8-sig`（CSV 带 BOM，与 `company_database.py` 同约定）**。

26. **记忆层（mem0 语义记忆 + 会话多轮指代）**：新 `memory/`（session/service/config）。**两层**：①会话最近实体缓冲（`Session.recent_entities` deque(maxlen=5) + `resolve_anaphora` 识别 `它/该公司/上述` 等标记→最近 resolved 实体，确定性零 LLM）；②mem0 语义记忆（`MemoryService.recall/remember`，云端 DeepSeek 抽取+本地 bge 嵌入+本地 Chroma）。接入：`state.preresolved` + planner「直接解析 not_found 才回退指代实体」；`run_research(session=,memory=,enable_memory=)` 图层编排（指代→recall 注入 open_questions→跑图→note_entity→remember 问题+摘要），默认关、API 不动；`cli chat` REPL（`run_chat_loop` 可测核心）承载多轮。**红线：用户明确决定本线豁免数据本地化、走云端 DeepSeek**（助手两次告知不可逆风险后决定），`MemoryConfig` 留本地 Ollama 接口一段 config 可切回，CLAUDE.md 红线文本不删仅本线豁免。降级照搬 retrieval_available（缺 .[memory]/key/异常→no-op）。CI 零网络零 key（FakeMemoryBackend + 确定性会话测试，全套 224 passed），真 mem0+DeepSeek 标 `@pytest.mark.llm` 手验。`.[memory]` extra=mem0ai+chromadb。前端聊天页/API 接记忆留后续。

27. **/research API 接记忆（跨进程会话 + ownership 授权）**：新 `POST /session/turn` 有状态多轮端点（`/research` 无状态不变）。`memory/store.py` `JsonSessionStore`：会话缓冲 JSON 文件每会话（`data/procurement/sessions/`）、原子写（临时→os.replace）、跨进程；`load(session_id,user_id)` **ownership 校验**（owner≠user_id→`SessionOwnershipError`→404，非泄露式、绝不覆写，防 IDOR）+ **session_id 严格 `^[A-Za-z0-9_-]{1,64}$`**（→`InvalidSessionIdError`→400，防路径穿越）；recent_entities 用 CompanyResolution model_dump/validate 序列化。`agents/graph.py` 抽 `execute_turn(app,question,domain,session,memory,enable_memory,tracer)`（记忆编排从 run_research 搬出，两者共用；run_research 行为不变）。API `create_app(database_path, memory=, session_store=)` 可注入（测试用 FakeMemoryBackend + tmp store，零网络零 key）；`session_id` 缺省 uuid4 生成、始终回传；`enable_memory=True` 恒开、`enable_scope=False`（→SupplierReport）、用缓存图。**身份：请求体 user_id 作 authenticated user stand-in（无真鉴权，后续接 token 中间件）；ownership 绑定+校验本轮建**。测试 TestClient（首轮回 id/次轮指代/用户 B→404 且不覆写/非法 id→400/跨请求持久/旧端点不变），全套 238 passed。前端聊天页/真鉴权/会话 TTL 留后续。

28. **前端聊天界面（对外演示 Demo）**：新 `src/deepresearch_agent/web/{index.html,style.css,app.js}`——FastAPI 托管的自包含 vanilla 页（**零构建零 npm、无 CDN/webfont**，CJK 系统字体栈 + 等宽承载信用代码/证据）。后端 `api.py` 仅加两处：`GET /` 返 `web/index.html`（`FileResponse`）、`/static` 挂 `StaticFiles`（`WEB_DIR=Path(__file__).parent/"web"`）；`/session/turn`、`/research` 一字不改。前端走 `POST /session/turn {question,user_id,session_id?}`→`{session_id,report}`：发送→「研究中…」加载态→`renderReport` 逐字渲染 `SupplierReport`（recommendation→徽章四值映射，`insufficient_evidence`=琥珀「证据不足」**既非红也非绿**；证据表 dimension/claim/置信 meter/`local://` 引用，`deriveCode` 从 citation url 取 18 位信用代码；待解问题=尚未接入数据源 +「缺失不代表无风险」框架句）。**核心数据原则：前端纯排版、不臆造「无风险」**。身份 `user_id` 存 localStorage 可改名（authenticated-user stand-in），`session_id` 内存复用（多轮指代 `它/该公司`），「＋新对话」重置；错误兜底 400/404→自动开新会话、网络/5xx→重试。流式进度、真鉴权、会话 TTL、scope/graph 前端专渲染留后续。测试 `tests/test_api_web.py`（`GET /` HTML + `/static` css/js + `/research` 回归，全套 **242 passed**）；JS 无构建无测试框架，纯函数 `renderReport` + TestClient 驱动契约手验（含 deriveCode/指代/404/400）。设计经样机 Artifact 获用户确认。

29. **网页 LLM 流式呈现（DeepSeek）+ Neo4j 兜底**：流式端点 `/session/turn/stream` 的**呈现层**从确定性切块换成 **DeepSeek 流式生成**（`llm/deepseek.py::build_deepseek_polisher`，复用 classifier 的 OpenAI client 模式 + `stream=True` 逐 token）。三种报告（named/scope/graph）经 `_resolve_report` 定稿后交 LLM 呈现。**红线守法**：①LLM 只呈现 writer 已定稿报告，`_render_report_for_llm` 把报告转输入文本时**剔除结论**；②`recommendation` 结论句由后端 `_conclusion_line` 在 LLM 正文前**确定性硬发一次**（纵深防御，LLM 改不了结论）；③约束 `_PRESENTER_SYSTEM_PROMPT`（只复述、不推断、保留原文、围标标线索级）。**降级**：无 `DEEPSEEK_API_KEY`→polisher=None→回退 `_report_message_chunks`；LLM 一上来抛异常→回退；中途异常→保留已产出（避免重复正文）。`create_app(polisher="__default__")` 哨兵区分「测试传 None 禁用」与「默认自建」。**数据越境豁免范围扩大到呈现层**（全部检索结果进 prompt，用户明确决定，与记忆层同级；核心红线文本仍在、仅本线豁免）。**Neo4j 兜底**：`from_env` 默认密码 `""`→`devpassword`（对齐 docker-compose，仅本地），`create_app` 启动经 `logging` 打印 `[graph] Neo4j backend: connected/unavailable`（不再静默降级；此前查出裸启动 graph_searcher 恒 None、网页版 GraphRAG 从不走）。测试：`test_deepseek_polisher.py`（fake client 零网络）+ `test_api_stream_retrieval.py`（fake polisher/None/异常三路）+ `test_neo4j_backend_env.py`（fake 驱动断言密码），全套 **258 passed**；真链路标 `@pytest.mark.llm`。前端零改动（token 流形状同 `message_delta`）。graph_viz 侧边图暂缓。

## 本地数据状态

目录：

```text
data/procurement/raw/          企查查原始 Excel，Git 忽略
data/procurement/processed/    companies.csv / contacts.csv / rejected.csv，Git 忽略
data/procurement/derived/      companies.sqlite3 / scope_index.faiss，Git 忽略
tests/fixtures/procurement/    可提交的合成测试数据
```

最新清洗和构建结果（参考量级，以 `import_metadata` 表为准）：

- 企业：3506 条。
- 联系方式：3506 条。
- SQLite 信用代码主键无重复。
- 万马科技可通过法定名称、信用代码和曾用名查询，经营范围原文约 623 字。

清洗器把字段值完全由星号组成的脱敏占位符视为缺失值，但保留经营范围内部的 `***` 分隔符（作为段切点：许可项目 / 一般项目）。

注：`derived/scope_index.faiss` 需 `.[rag]` 依赖、用 `scripts/build_scope_index.py` 从 SQLite 重建；尚未对真实 3506 家库验证召回质量（待办）。

## 正式模型和数据库

`CompanyProfile` 覆盖法定名称、信用代码、登记状态、法人、企业类型、注册/实缴资本、成立和营业期限、地址、省市区、登记机关、国标行业、企业规模、完整经营范围、曾用名、英文名、官网、参保人数、年报年份和纳税人资质。

SQLite schema version 2，表：

- `companies`
- `company_aliases`
- `company_contacts`
- `business_scope_chunks`（chunk_id、信用代码、段标签、序号、文本、embedding BLOB）
- `scope_index_metadata`（嵌入模型名、维度、归一化、chunk 数、构建时间）
- `import_metadata`

索引覆盖规范化法定名称、别名、登记状态、省市、国标行业大类、企业规模、以及 chunk 的信用代码。运行时使用只读连接，schema 版本不匹配时要求重建。

## Agent 当前能力边界

核验路径研究维度：

```text
company_identity
registration
capital
industry_and_business_scope
enterprise_scale
contact
```

经营范围按原文作为证据，不推断产品、产能、交期、认证或风险。当前没有制裁、司法、负面新闻、财务和采购履约数据，因此已解析企业的报告固定为 `insufficient_evidence`，不得写“未发现风险”。

scope 检索路径：能力类问题（未指名企业）返回 `ScopeSearchReport` 候选清单，同样固定 `insufficient_evidence`——按经营范围找到企业不等于采购背书。

## 环境注意（非显而易见）

工作区 conda 环境（Python 3.11）通过 `.conda-env/Lib/site-packages/python312-langgraph-bridge.pth` 桥接 Python 3.12 全局 site-packages，`langgraph`/`langchain_core` 经此共享。后果：3.12 编译的原生扩展包（torch/numpy/regex/scikit-learn/tokenizers 等）在 3.11 下加载失败。已用 `pip install --ignore-installed <pkg>` 把 3.11 版强装进 conda env 覆盖之（faiss-cpu、numpy、sentence-transformers、torch、scikit-learn、scipy、regex、socksio）。**不要删除该 .pth 桥**（现有测试依赖它）。模型下载走 `ALL_PROXY=socks5://127.0.0.1:7890`，需要 `socksio`。

## 尚未实施

- 制裁、司法、新闻、财务和采购履约独立数据源。
- 方案 B（先 scope 筛选 top-N，再对每家自动跑工商核验）——评估为便利层而非新能力，按 YAGNI 缓做。
- `/research` API 端到端暴露 scope（目前仅 CLI）。
- ruff + mypy 静态检查。
- RAGAS、Phoenix 和 golden cases。
- GraphRAG、MCP、Qdrant 和 LangGraph checkpoint。
- jieba 真分词替代 trigram（注：当前检索走语义向量，trigram 仅是 FTS5 备选，未采用）。

## 常用命令

```powershell
.\.conda-env\python.exe scripts/clean_qcc_company_data.py `
  --input data/procurement/raw/<企查查导出文件>.xlsx `
  --output-dir data/procurement/processed

.\.conda-env\python.exe scripts/build_company_database.py

# 构建 FAISS 经营范围语义索引（需 .[rag]）
.\.conda-env\python.exe scripts/build_scope_index.py

# CLI：核验指定企业，或按能力检索（未指名企业时走 scope 语义检索）
.\.conda-env\python.exe -m deepresearch_agent.cli `
  "核验万马科技股份有限公司的工商和经营范围" `
  --database data/procurement/derived/companies.sqlite3

# 默认测试（慢速真模型测试默认排除）
.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final

# 慢速测试（加载真 bge 模型）
.\.conda-env\python.exe -m pytest -m slow -q
```

最后一次完整验证：默认 93 项通过、2 项慢速（真 bge 模型）默认排除且单独验证通过。
