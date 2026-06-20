# DeepResearch Agent

基于 LangGraph 的采购供应商尽调 Agent。当前 v1 使用本地预设供应商数据和 Markdown 文档，完成供应商识别、研究规划、证据收集、缺口检查和带引用报告生成。

## 当前范围

- 支持 `ACME Sensors` 和 `Northstar Components`，以及预设别名。
- Domain Pack 驱动研究维度、工具白名单和 HITL 规则。
- 供应商名称无法识别或同时命中多个供应商时，返回 `insufficient_evidence`，不会猜测实体。
- 数据全部来自 `data/procurement/`，当前不接实时 API、网页爬取、数据库、Qdrant、GraphRAG 或 MCP。
- RAGAS、Phoenix 和 golden case 评估已后置，待可用版稳定后实施。

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

本工作区已有 conda 环境时，可直接使用：

```powershell
.\.conda-env\python.exe -m pytest -q
```

## CLI

```powershell
.\.conda-env\python.exe -m deepresearch_agent.cli "Assess ACME Sensors for industrial sensor procurement"
.\.conda-env\python.exe -m deepresearch_agent.cli "Assess Northstar Components for control module procurement"
.\.conda-env\python.exe -m deepresearch_agent.cli "Assess Missing Supplier"
```

也可以在安装项目后使用 `deepresearch` 命令。

## API

```powershell
.\.conda-env\python.exe -m uvicorn deepresearch_agent.api:app --reload
```

请求示例：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/research `
  -ContentType "application/json" `
  -Body '{"question":"Assess ACME Sensors for industrial sensor procurement"}'
```

## 核心流程

```text
Planner + Supplier Resolver
  resolved -> Researcher -> Critic -> 按缺失维度继续研究 -> Writer
  unresolved / ambiguous -> Writer(insufficient_evidence)
```

详细结构见 [docs/architecture.md](docs/architecture.md)。后置评估范围见 [docs/eval-plan.md](docs/eval-plan.md)。

## 测试

```powershell
.\.conda-env\python.exe -m pytest -q
```

测试覆盖状态模型、Domain Pack、数据加载、供应商识别、采购工具、本地检索、Agent 节点、LangGraph 路由、API 和 CLI。
