# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 沟通与协作约定

- 全程使用中文沟通，Git 提交信息使用中文。
- 每完成一个模块就提交一次。不覆盖或回退用户未提交的文件修改。
- `docs/project-memory.md` 记录已确认的工程决策和最新项目状态；开始工作前先读它，并以用户最新指令为准。

## 核心数据原则（最重要的约束）

这是一个面向中国制造业供应商工商研究的 Agent。**企查查清洗 CSV 是企业事实标准，SQLite 是可重复生成的查询产物。Agent 只能陈述当前数据源实际提供的字段，绝不能把数据缺失解释为“没有风险”。**

具体含义，改代码时必须遵守：

- 当前只有工商登记和联系方式数据。没有制裁、司法、负面新闻、财务、产能/交期/认证、采购履约数据。
- 因此 `writer_node` 对已解析企业**固定**返回 `recommendation="insufficient_evidence"`，并在 `open_questions` 列出尚未接入的数据源。不要写“未发现风险”或做采购批准/拒绝结论。
- 经营范围（`business_scope`）按数据源原文作为证据，**不推断**结构化产品、产能、交期、认证。
- 不接实时 API、网页爬虫、Qdrant、GraphRAG、MCP。这些是后置能力，未经用户确认不要引入。

## 常用命令

环境是工作区内的 conda 环境，直接用其解释器，不要新建 venv：

```powershell
# 跑全部测试（67 项）
.\.conda-env\python.exe -m pytest -q

# 隔离缓存目录跑测试（避免 Windows 临时目录权限/残留问题）
.\.conda-env\python.exe -m pytest -q -p no:cacheprovider --basetemp=.conda-cache/pytest-final

# 跑单个测试文件 / 单个用例
.\.conda-env\python.exe -m pytest tests/test_company_repository.py -q
.\.conda-env\python.exe -m pytest tests/test_nodes.py::test_writer_never_approves_from_registration_data_only -q
```

数据管道（真实数据本地运行，不提交 Git）：

```powershell
# 1. 清洗企查查 Excel -> processed/{companies,contacts,rejected}.csv
.\.conda-env\python.exe scripts/clean_qcc_company_data.py `
  --input data/procurement/raw/<企查查导出文件>.xlsx `
  --output-dir data/procurement/processed

# 2. 构建 SQLite（校验表头/信用代码唯一性/联系方式关联后原子替换）
.\.conda-env\python.exe scripts/build_company_database.py

# 3. 生成候选名单（独立工具脚本）
.\.conda-env\python.exe scripts/generate_china_manufacturing_candidates.py

# 4. 构建 FAISS 经营范围语义索引（需安装 .[rag] 可选依赖）
.\.conda-env\python.exe scripts/build_scope_index.py
```

运行 Agent：

```powershell
# CLI（核验指定企业，或按能力检索供应商：问题不含已知企业名时走经营范围语义检索）
.\.conda-env\python.exe -m deepresearch_agent.cli `
  "核验万马科技股份有限公司的工商和经营范围" `
  --database data/procurement/derived/companies.sqlite3

# API（POST /research，body: {"question": "...", "domain": "procurement"}）
.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload
```

语义经营范围检索（跨企业按内容找企业，需 `.[rag]` 可选依赖与已构建的 FAISS 索引）：

```powershell
.\.conda-env\python.exe -m deepresearch_agent.rag.cli "注塑成型" `
  --database data/procurement/derived/companies.sqlite3 `
  --index data/procurement/derived/scope_index.faiss
```

## 架构

### 数据管道
`raw/*.xlsx` → `company_data_cleaning.run_cleaning` → `processed/companies.csv` + `contacts.csv` (+ `rejected.csv`) → `company_database.build_company_database` → `derived/companies.sqlite3` → `CompanyRepository` → Agent。

- `raw/`、`processed/`、`derived/` 全部 Git 忽略。测试只用 `tests/fixtures/procurement/` 中字段结构相同的合成 CSV（见 `tests/conftest.py` 的 `company_database_path` fixture，它在 `tmp_path` 现场构建 SQLite）。
- 数据库构建是**原子**的：写临时文件 → 校验/事务 → `replace` 旧文件。`SCHEMA_VERSION`（当前为 2，含 `business_scope_chunks` 与 `scope_index_metadata` 表）写入 `PRAGMA user_version`；Repository 用只读连接打开，版本不匹配直接报错要求重建。改 schema 必须同步 `SCHEMA_VERSION` 和 `_create_schema`。

### LangGraph 编排（`agents/graph.py` + `agents/nodes.py`）
`StateGraph(ResearchState)`，**纯线性** `planner → researcher → critic → writer → END`（C2 起，检索/生成分层）。仅 critic 后一处条件回环。

- **planner**：`resolve_supplier` 解析企业 + `classify_complexity` 写 `state.complexity`（LLM 只发查询文本，无 key/无 `.[llm]` 走确定性启发式），不检索。
- **researcher = 检索层**：按 `解析状态 × 复杂度 × 是否启用检索` 分派并只做检索：`resolved`→`named`（调白名单私有工具）；`not_found`+`simple`→`scope`（经营范围语义检索，填 `scope_candidates`）；`not_found`+`medium/complex`→`graph`（GraphRAG 融合，填 `graph_candidates`/`shared_controllers`，缺 searcher 且 scope 可用则回退 scope）；`ambiguous` 或均未启用→`unresolved`（不检索）。检索器缺失/异常置 `retrieval_available=False`，不抛出、不写报告叙述。**降级链（C4）**：graph 运行时抛异常 → 有 scope 就降级 scope、无 scope 记“无可用降级路径”；scope 运行时异常为终点。**只有运行时失败**记入 `state.degradations`（配置性缺失不记），writer 把它插到报告 `open_questions` 最前面。不做重试。
- **critic 后**：`missing_dimensions` 非空且 `iteration < max_iterations(3)` 则回 researcher，否则进 writer（实际只有 `named` 会累积维度、可能回环）。
- **writer = 唯一生成层**：按 `retrieval_mode` 出 `SupplierReport`(named/unresolved) / `ScopeSearchReport`(scope) / `GraphSearchReport`(graph)，所有 summary/open_questions/`insufficient_evidence`/人工复核提示与“不可用”报告都在此生成。

researcher 的 `named` 路径调 Domain Pack 白名单内的私有数据工具（`get_company_profile`、`get_company_contact`、`get_ownership_neighborhood`、`get_related_parties`），把工商/联系方式/股权/关联方拆成研究维度的 `Evidence`（每条带 `local://` Citation）。critic 用“计划维度 − 已覆盖维度”算缺口。检索器与 LLM 由 `build_graph(..., scope_retriever, graph_searcher, llm, scope_enabled, graph_enabled)` 注入；`run_research(enable_scope, enable_graph)` 决定构建/注入哪个。旧的 `scope_search_node`/`graph_search_node` 独立节点与 planner 条件路由已撤销。所有状态都在 `state.py` 的 Pydantic 模型里流转。

### Domain Pack（`domain.py` + `domains/<domain>/domain.yaml`）
领域配置驱动 Agent 行为：`research_dimensions`、`allowed_tools`（工具白名单，researcher 严格据此调用）、`report_sections`、`source_priority`、`hitl_policy`。新增领域 = 新增一个 `domains/<name>/domain.yaml`，不改编排代码。

当前采购领域六个维度：`company_identity`、`registration`、`capital`、`industry_and_business_scope`、`enterprise_scale`、`contact`。

### 企业识别（`company_repository.py` + `supplier_resolution.py`）
`CompanyRepository.resolve_text` 对问题做名称匹配：NFKC + casefold + 空白折叠（`normalize_company_name`），中文用子串匹配、英文用字母数字边界（`_contains_name`）。同时匹配法定名称和曾用名（alias），多企业命中返回 `status="ambiguous"`，**绝不猜测**单一实体。

### 数据模型（`company_models.py`）
`CompanyProfile` / `CompanyContact` 对应清洗后的列。空字符串经 `none_if_blank` 转 `None`；`aliases`/`phones`/`emails` 经 `split_pipe` 用 `|` 拆成列表；金额用 `Decimal`、日期用 `date`、人数/年份用 `int`。`CORE_COLUMNS` / `CONTACT_COLUMNS`（在 `company_data_cleaning.py`）是 CSV 表头契约，构建器严格校验，改列要三处（清洗输出、列常量、模型）一起改。

旧的 `SupplierCapability` / `ComplianceProfile` / `FinancialProfile` / `ProcurementHistory` 等组合模型**已删除**，只有拿到对应数据源后才重新设计。

## 注意点

- `rag/` 是语义经营范围检索子系统（切块 → bge-small-zh-v1.5 嵌入 → FAISS → `ScopeRetriever` → `search_company_scope` 工具 + CLI）。依赖 `.[rag]` 可选 extra；FAISS 索引由 `scripts/build_scope_index.py` 从 SQLite 重建。C2 起，retriever 不再是独立节点，而是由 `run_research(enable_scope=True)` 懒加载后**注入 researcher**；缺 `.[rag]`/索引则 `retrieval_available=False`，由 writer 降级为“不可用”报告。`/research` API 不启用检索、形状不变。旧的 `retrieval/local.py` 关键词检索器已删除。
- GraphRAG 股权栈（`ownership_graph.py` / `graph_traversal.py` / `graph_retrieval.py`）：内存有向图 + ego/最终控制人/共同控制人/最短路径 + `hybrid_search` 融合。N1 起，`hybrid_search`/`assemble_subgraph_context` 走 `ownership_backend.py` 的 `OwnershipGraphBackend` 协议（`InMemoryOwnershipBackend` 为当前实现，也是 CI 测试替身）；N2 将加 Cypher 版 `Neo4jBackend` 替换内存图（Neo4j 必须本地、不用云）。经 `run_research(enable_graph=True)`（CLI `--graph`）注入 researcher 的 `graph` 模式。查询复杂度分类见 `query_complexity.py`（C1，唯一 LLM 环节，只发查询文本）。关联方/共享控制人为**线索级**（`via_person` 低置信、标“须人工复核”），绝不作控制关系或围标认定。
- `docs/architecture.md` 是架构事实标准；`docs/superpowers/` 下是历史 spec 和 plan。
- 真实最新构建结果：3506 家企业、3506 条联系方式（参考量级，以 `import_metadata` 表为准）。
