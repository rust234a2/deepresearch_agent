# DeepResearch Agent

基于 LangGraph 的中国制造业供应商工商研究 Agent。当前版本以企查查导出的清洗 CSV 为事实标准，使用本地 SQLite 完成企业识别、工商证据收集、缺口检查和带引用报告生成。

## 当前范围

- 支持 SQLite 中全部企业的法定名称、曾用名和统一社会信用代码。
- 返回登记状态、法人、资本、成立日期、地址、国标行业、企业规模、经营范围和联系方式。
- 经营范围按数据源原文返回，不推断结构化产品、产能、交期或认证。
- 当前没有制裁、司法、新闻、财务和采购履约数据，因此报告固定使用 `insufficient_evidence`，不会据工商数据作出采购批准或风险结论。
- 不接实时 API、网页爬虫、Qdrant、GraphRAG 或 MCP。

## 数据流

```text
data/procurement/raw/*.xlsx
  -> 清洗
data/procurement/processed/companies.csv
data/procurement/processed/contacts.csv
  -> SQLite 构建器
data/procurement/derived/companies.sqlite3
  -> CompanyRepository -> Agent
```

`raw/`、`processed/` 和 `derived/` 都是本地数据目录，不提交 Git。测试使用 `tests/fixtures/procurement/` 中的合成数据。

## 安装和测试

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest -q
```

本工作区已有 conda 环境时：

```powershell
.\.conda-env\python.exe -m pytest -q
```

## 清洗与构建数据库

```powershell
.\.conda-env\python.exe scripts/clean_qcc_company_data.py `
  --input data/procurement/raw/<企查查导出文件>.xlsx `
  --output-dir data/procurement/processed

.\.conda-env\python.exe scripts/build_company_database.py
```

数据库构建器校验 CSV 表头、信用代码唯一性和联系方式关联，成功后原子替换 `data/procurement/derived/companies.sqlite3`。

## CLI

```powershell
.\.conda-env\python.exe -m deepresearch_agent.cli `
  "核验万马科技股份有限公司的工商和经营范围" `
  --database data/procurement/derived/companies.sqlite3
```

## API

```powershell
.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload
```

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/research `
  -ContentType "application/json" `
  -Body '{"question":"核验万马科技股份有限公司的工商和经营范围"}'
```

详细结构见 [docs/architecture.md](docs/architecture.md)。
