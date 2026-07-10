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
