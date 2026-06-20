# 项目记忆

更新时间：2026-06-20

本文件记录当前对话中已经确认的需求、工程决策和项目状态，供后续会话继续工作。开始新任务前应先阅读本文件，并以用户最新指令为准。

## 用户协作偏好

- 全程使用中文沟通。
- 每完成一个模块都要提交 Git，提交信息使用中文。
- 用户已允许直接在 `master` 分支工作。
- 用户希望按模块持续完成项目，不停留在方案层；但遇到明确中断时应停止旧任务，以最新请求为准。
- 不覆盖或回退用户未提交的文件修改。

## 当前项目目标

构建面向中国制造业供应商尽调的 DeepResearch Agent。

当前范围：

- 只处理中国企业，因此正式企业模型已删除国家字段。
- 先使用本地预设和人工收集的数据，不接实时 API、网页爬虫、Qdrant、GraphRAG 或 MCP。
- RAGAS 计划用于后续 RAG 质量评估，Phoenix 计划用于后续轨迹调试。
- Golden cases 和正式评估层后置。

## 已完成模块

1. FastAPI 和 CLI 入口。
2. LangGraph Planner、Researcher、Critic、Writer 编排循环。
3. Domain Pack 驱动研究维度、工具白名单和 HITL 规则。
4. 供应商预设数据模型、加载器和采购工具。
5. 本地供应商文档检索及供应商范围隔离。
6. 法定名称与别名确定性识别，支持未知和歧义输入。
7. 报告证据去重、工具轨迹去重和错误处理。
8. 中国制造业供应商候选名单生成器。
9. 企查查工商数据清洗器和命令行脚本。
10. 正式供应商模型、fixture 和工具输出中的国家字段已经删除。

最近相关提交：

```text
43ef172 重构：移除供应商国家字段
049dc33 功能：增加企查查数据清洗命令
750de3f 功能：增加企业工商数据清洗器
4d8ab16 数据：增加中国制造业供应商候选名单
8a81a4c 修复：提高候选企业行业分类准确性
8364ef8 功能：增加候选企业名单生成脚本
6727b8d 功能：增加制造业候选企业分类器
95ba939 文档：同步采购尽调 v1 架构与使用说明
```

## 数据状态

### 候选名单

路径：

```text
data/procurement/candidates/china_manufacturing_supplier_names.csv
```

最初生成 3509 家中国制造业企业，覆盖 15 个行业。

重要：当前该文件有用户未提交修改，表头 `supplier_name,industry` 已被删除，第一家公司被当作表头，常规 CSV 读取只得到 3508 条。不要直接覆盖；修复前应获得用户确认或明确保留用户后续编辑。

### 企查查原始数据

原始 Excel 位于 `data/procurement/candidates/`，包含 3509 条输入。原始文件带有使用和再分发限制，已通过 `.gitignore` 排除，不得提交到公开 Git。

### 清洗结果

路径：

```text
data/procurement/cleaned/companies.csv
data/procurement/cleaned/contacts.csv
data/procurement/cleaned/rejected.csv
```

结果：

- 核心企业：3506 条。
- 联系方式：3506 条。
- 未匹配：3 条。
- 统一社会信用代码重复：0。
- 注册资本解析失败：0。

清洗结果同样被 Git 忽略，只用于本地项目。

未匹配企业：

```text
厦门建霖智慧家居股份有限公司
华虹宏力半导体有限公司
山东（原文件名称存在乱码）橡塑科技股份有限公司
```

## 当前数据结构缺口

- `CompanyProfile` 仍只覆盖少量基础字段，尚未承接法定代表人、资本、成立日期、国标行业、企业规模、经营范围和年报字段。
- `data_loader.py` 仍只加载 `data/procurement/suppliers.json` 中两家演示供应商，3506 家清洗企业尚未接入 Agent。
- 当前 `LocalDocumentRetriever` 仅使用英文字符正则，不能有效检索中文经营范围。
- 尚未建立 SQLite 企业索引、别名索引或中文 BM25 索引。
- 演示 fixture、原始数据、清洗数据和未来索引产物尚未按 `fixtures/raw/staging/processed/derived` 完整重组。

## 已确认但尚未实施的分块方案

用户已同意先讨论经营范围分块，但上一轮“实行”请求被主动中断，因此当前没有分块代码或数据产物。

经营范围实际分布：

```text
总数：3506
长度中位数：235 字
P90：513 字
P95：629 字
最大：1490 字
包含分号条款：3153 条
```

拟采用条款感知动态分块：

- 不超过 600 字时保持单块。
- 超过 600 字时按 `；`、`;`、`。` 和编号条款切分。
- 目标 400 至 500 字，最小 200 字，最大 650 字。
- 超长单条款再按中文逗号切分，最后才进行硬切。
- 相邻块最多重叠一个完整条款，重叠不超过 80 字。
- 只对 `business_scope` 及未来新闻、司法、公告等长文本分块。
- 名称、信用代码、资本、状态、行业、地址和联系方式不分块。

Chunk 中应区分：

```text
content      原始文本，用于引用
search_text  企业名、行业和中文分词后的检索文本
metadata     supplier_id、source_type、field_name、chunk_index 等
```

不建议把每个分号条款独立成 chunk。产品、能力、活动等信息未来作为派生标签保存，不修改原始 `content`。

## 已讨论的索引方案

当前阶段建议：

- 统一社会信用代码唯一索引。
- 法定名称规范化索引。
- 别名独立表和别名索引。
- 状态、省市、国标行业和企业规模结构化索引。
- Chunk 表按企业 ID、来源类型和内容哈希建立索引。
- 中文使用分词加 BM25；向量索引和 Qdrant 后置。

## 建议的后续顺序

1. 处理候选 CSV 表头丢失问题，但不要覆盖用户修改。
2. 明确并实施 `fixtures/raw/staging/processed/derived` 数据目录。
3. 扩展工商企业模型，并建立清洗 CSV 到模型的映射。
4. 用 repository 边界替换只读两家 fixture 的硬编码 loader。
5. 用户重新确认后，再实现经营范围分块。
6. 建立企业结构化索引和中文 BM25 检索。

## 常用命令

```powershell
.\.conda-env\python.exe -m pytest -q --basetemp=.pytest-tmp
.\.conda-env\python.exe scripts/clean_qcc_company_data.py --input <xlsx> --output-dir data/procurement/cleaned
.\.conda-env\python.exe scripts/generate_china_manufacturing_candidates.py --limit 5000
```

最后一次完整验证：58 项测试通过。工作区除用户修改的候选 CSV 外无其他未提交代码修改。
