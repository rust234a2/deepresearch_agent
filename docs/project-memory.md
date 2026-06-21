# 项目记忆

更新时间：2026-06-21

本文件记录已经确认的工程决策和项目状态。后续会话开始前应先阅读本文件，并以用户最新指令为准。

## 用户协作偏好

- 全程使用中文沟通。
- 每完成一个模块提交 Git，提交信息使用中文。
- 用户允许直接在 `master` 工作；SQLite 企业数据层当前在隔离分支 `feature/sqlite-company-data` 实施。
- 不覆盖或回退用户未提交的文件修改。

## 当前目标和数据原则

项目面向中国制造业供应商工商研究。企查查清洗 CSV 是企业事实标准，SQLite 是可重复生成的查询产物，Agent 只陈述数据源实际提供的字段。

当前不使用实时 API、网页爬虫、Qdrant、GraphRAG 或 MCP。RAGAS、Phoenix、golden cases 和正式评估层后置。

## 已完成模块

1. FastAPI 和 CLI 入口。
2. LangGraph Planner、Researcher、Critic、Writer 编排循环。
3. Domain Pack 工具白名单和研究维度。
4. 中国制造业候选名单生成器，3509 家企业、15 个行业。
5. 企查查 Excel 清洗器，输出企业、联系方式和拒绝记录。
6. 以清洗字段为标准的 `CompanyProfile` 和 `CompanyContact` 强类型模型。
7. SQLite schema version 1 和原子数据库构建器。
8. 只读 `CompanyRepository`，支持信用代码、法定名称和曾用名查询以及歧义结果。
9. `get_company_profile` 和 `get_company_contact` 两个私有数据工具。
10. 基于六个工商维度的 Agent 证据生成路径。
11. 旧能力、合规、财务、采购历史组合模型和两家英文演示供应商已删除。

SQLite 企业数据层相关提交：

```text
d65a94f 重构：以工商数据源重建企业模型
14d46ab 功能：增加SQLite企业数据库构建器
3a562a5 功能：增加只读企业Repository
bd7a387 功能：增加企业数据库构建命令
1620af9 重构：让企业识别和工具使用SQLite
72d4e82 重构：让研究图基于工商数据生成证据
ad5982a 文档：切换到SQLite企业数据运行路径
```

## 本地数据状态

目录：

```text
data/procurement/raw/          企查查原始 Excel，Git 忽略
data/procurement/processed/    companies.csv / contacts.csv / rejected.csv，Git 忽略
data/procurement/derived/      companies.sqlite3，Git 忽略
tests/fixtures/procurement/    可提交的合成测试数据
```

最新清洗和构建结果：

- 原始输入：3509 条。
- 企业：3506 条。
- 联系方式：3506 条。
- 未匹配：3 条。
- SQLite 信用代码主键无重复。
- 万马科技可通过法定名称、信用代码和曾用名查询。
- 万马科技经营范围原文长度为 623 字。

清洗器已把字段值完全由星号组成的脱敏占位符视为缺失值，但保留经营范围内部的 `***` 分隔符。

未匹配企业仍为：

```text
厦门建霖智慧家居股份有限公司
华虹宏力半导体有限公司
山东（原文件名称存在乱码）橡塑科技股份有限公司
```

## 正式模型和数据库

`CompanyProfile` 覆盖法定名称、信用代码、登记状态、法人、企业类型、注册/实缴资本、成立和营业期限、地址、省市区、登记机关、国标行业、企业规模、完整经营范围、曾用名、英文名、官网、参保人数、年报年份和纳税人资质。

SQLite 表：

- `companies`
- `company_aliases`
- `company_contacts`
- `import_metadata`

索引覆盖规范化法定名称、别名、登记状态、省市、国标行业大类和企业规模。运行时使用只读连接，schema 版本不匹配时要求重建。

## Agent 当前能力边界

研究维度：

```text
company_identity
registration
capital
industry_and_business_scope
enterprise_scale
contact
```

经营范围按原文作为证据，不推断产品、产能、交期、认证或风险。当前没有制裁、司法、负面新闻、财务和采购履约数据，因此已解析企业的报告固定为 `insufficient_evidence`，不得写“未发现风险”。

## 尚未实施

- 经营范围条款感知分块。
- 中文分词和 SQLite FTS5/BM25。
- 制裁、司法、新闻、财务和采购履约独立数据源。
- RAGAS、Phoenix 和 golden cases。
- 向量检索、GraphRAG、MCP 和 LangGraph checkpoint。

建议下一阶段先实现经营范围分块和中文 FTS5/BM25，再引入其他数据源。

## 常用命令

```powershell
.\.conda-env\python.exe scripts/clean_qcc_company_data.py `
  --input data/procurement/raw/<企查查导出文件>.xlsx `
  --output-dir data/procurement/processed

.\.conda-env\python.exe scripts/build_company_database.py

.\.conda-env\python.exe -m deepresearch_agent.cli `
  "核验万马科技股份有限公司的工商和经营范围" `
  --database data/procurement/derived/companies.sqlite3

.\.conda-env\python.exe -m pytest -q -p no:cacheprovider `
  --basetemp=.conda-cache/pytest-final
```

最后一次完整验证：67 项测试通过。真实 SQLite 构建结果为 3506 家企业、3506 条联系方式。
