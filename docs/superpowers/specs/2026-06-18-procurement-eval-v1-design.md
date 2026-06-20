# 采购 Eval v1 设计规格说明（后置）

## 目的

采购领域的 DeepResearch Agent 目前已经具备一个最小可用的 LangGraph 循环、本地供应商 fixture、本地检索、确定性工具、CLI 和 API 入口。第一版明确只使用预设数据，不处理实时爬取、企查查导入或 B2B 数据接入。根据当前实施顺序，本规格保留为后续里程碑，当前版本不实现评估代码。

Eval v1 为供应商尽调提供一个确定性、适合 CI 的评估层。它衡量 Agent 是否能给出正确推荐、发现预期风险、引用证据、正确处理缺失信息，并检索到必需的证据来源。

## 问题

如果没有评估层，这个项目仍然只是一个 demo：

- 生成的报告可能看起来可信，但给出了错误的供应商推荐。
- 风险信号可能被漏掉，而没有任何指标暴露这个遗漏。
- 报告中可能有引用，但引用没有覆盖关键决策维度。
- 预设数据中的信息缺口可能被过度自信的写法掩盖。
- 检索层变更无法被量化比较。

对于一个能体现工程能力的 Agent 项目，在添加 Qdrant、MCP、数据库、reranker、企查查导入、B2B 采集或实时中国企业数据源之前，系统必须先具备可度量的行为。

## 范围

Eval v1 只覆盖现有的采购领域。

Eval v1 的数据范围固定为现有预设数据：

- `data/procurement/suppliers.json`
- `data/procurement/documents/*.md`
- `evals/procurement/golden_cases.yaml`

第一版不建设数据采集链路；真实数据源、导入器和爬虫在后续阶段单独设计。

它评估：

- 最终供应商推荐
- 预期风险检测
- 按研究维度统计的引用覆盖率
- 缺失数据处理
- 必需证据来源召回

它不评估：

- LLM 写作质量
- 长篇分析深度
- 实时网页搜索质量
- Qdrant / OpenSearch 召回率
- MCP server 行为
- 中国公开数据源适配器
- 成本或延迟优化

这些内容应在确定性基线稳定后，放到后续评估层中处理。

## Golden Cases

Golden cases 存放在：

```text
evals/procurement/golden_cases.yaml
```

每个 case 包含：

```yaml
case_id: northstar_restricted_supplier
question: Assess Northstar Components for control module procurement
expected:
  recommendation: reject
  expected_risks:
    - sanctions_or_blacklist
    - export_restriction
  required_dimensions:
    - supplier_profile
    - compliance
    - delivery_capability
    - negative_news
    - geopolitical_or_sanctions_risk
  required_source_ids:
    - supplier_profile:northstar-components
    - sanctions:northstar-components
    - doc:northstar-components
  allow_missing_data: false
```

前两个 case 应使用现有 fixture：

- `acme_low_risk_supplier`：预期推荐为 `approve`。
- `northstar_restricted_supplier`：预期推荐为 `reject`。

后续中国场景专用 case 应建模一个缺少公开财务数据的非上市民营供应商。这个 case 的预期结果应为 `conditional` 或 `insufficient_evidence`，而不是自信地批准。

## 指标

### 推荐准确率

衡量最终报告中的推荐是否与预期推荐一致。

```text
recommendation_accuracy = matching_recommendations / total_cases
```

这个指标捕捉最重要的失败类型：批准本应拒绝的供应商，或拒绝本应通过的供应商。

### 风险命中率

衡量预期风险标签是否出现在报告的风险描述中。

```text
risk_hit_rate = expected_risks_found / expected_risks
```

例如，如果某个 case 预期包含 `sanctions_or_blacklist` 和 `export_restriction`，两者都必须在报告风险文本中可见，才能拿到满分。

### 引用覆盖率

衡量必需研究维度是否有带引用的证据支撑。

```text
citation_coverage = required_dimensions_with_cited_evidence / required_dimensions
```

这个指标不评价文字质量。它只检查报告是否为关键维度提供了证据。

### 缺失数据处理率

衡量 Agent 是否能通过提出开放问题，或给出类似证据不足的推荐，来正确处理允许存在的数据缺口。

这对中国民营企业尽调尤其重要，因为完整的审计财务数据可能并不公开。

### Retrieval Recall at K

衡量预期 source ID 是否出现在最终证据表中。

```text
retrieval_recall_at_k = required_source_ids_found / required_source_ids
```

在 Eval v1 中，`k` 由当前 graph 产出的证据表表示。后续检索专项评估可以在固定 retriever limit 下测量 recall。

## 通过标准

单个 case 通过需满足：

- recommendation 完全匹配
- risk hit rate 为 `1.0`
- citation coverage 至少为 `0.75`
- missing-data handling 正确
- retrieval recall at k 至少为 `0.75`

当所有初始 golden cases 都通过时，整个 suite 通过。

## 架构

新增一个 eval package：

```text
src/deepresearch_agent/eval/
  __init__.py
  models.py
  metrics.py
  runner.py
```

职责：

- `models.py`：定义带类型的 golden-case 和结果模型。
- `metrics.py`：实现不依赖 LangGraph 的纯指标函数。
- `runner.py`：加载 cases，调用 `run_research()`，计算指标。

runner 应依赖现有 graph 入口：

```text
deepresearch_agent.agents.graph.run_research
```

这样可以让 Eval v1 专注于当前系统行为，而不引入第二条执行路径。

## CLI

新增命令：

```powershell
.conda-env\python.exe -m deepresearch_agent.cli eval procurement
```

预期输出应包含：

```text
Eval domain: procurement
Passed: 2/2
recommendation_accuracy=1.00
average_risk_hit_rate=1.00
average_citation_coverage=...
missing_data_handling_rate=...
average_retrieval_recall_at_k=...
```

当前的单问题 CLI 行为必须继续可用，以保持向后兼容。

## 测试

Eval v1 应采用测试优先：

- `tests/test_eval_models.py`：加载并校验 golden cases。
- `tests/test_eval_metrics.py`：用手工构造的 report 测试指标。
- `tests/test_eval_runner.py`：通过现有 graph 运行 golden cases。
- `tests/test_cli.py`：验证 `eval procurement` parser 路径。

完整验证命令：

```powershell
.conda-env\python.exe -m pytest -v
```

## 非目标

Eval v1 不应引入：

- Qdrant
- PostgreSQL
- Redis
- OpenSearch
- 实时网页搜索
- 企查查导入
- B2B 网站爬取
- MCP servers
- LLM-as-judge
- 中国企业数据适配器

在 Eval v1 之前加入这些能力，会让后续变更到底是改善还是退化 Agent 更难判断。

## 后续阶段

Eval v1 通过后：

1. 增加中国场景的缺失数据 golden cases。
2. 扩充预设供应商数据，先用手工整理或导出文件离线录入。
3. 再考虑企查查导入器和 B2B 数据采集适配器。
4. 将本地检索升级为 BM25，并测量 retrieval recall 的变化。
5. 加入基于 Qdrant 的 hybrid retrieval。
6. 增加 rerank 指标。
7. 将本地工具迁移到兼容 MCP 的边界后面。
8. 增加基于 Postgres 的 run storage 和 LangGraph checkpointing。
9. 在确定性指标稳定后，增加 LLM-as-judge 报告质量指标。

## 决策

当前先完成并稳定采购尽调可用版，Eval v1 后置。进入评估阶段时仍按本规格复用现有 `run_research` 路径实施。
