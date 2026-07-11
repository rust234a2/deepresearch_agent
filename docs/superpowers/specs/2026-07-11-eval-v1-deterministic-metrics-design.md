# 模块 Eval v1：确定性评测机制设计

日期：2026-07-11

给 Agent 一套**确定性、可 CI、可复现**的硬指标,回答"它到底准不准"。**只测现在真正是"决策"的两块**:企业识别 P/R、scope 检索 recall@k。测不了的诚实标 **N/A**,不伪造数字。**不引入 RAGAS / LlamaIndex / Phoenix**(它们是 LLM-as-judge / 可观测性工具,撞本地化红线、且顺序上应在确定性基线之后)。

> 旧 spec `2026-06-18-procurement-eval-v1-design.md` 已作废(假设 `suppliers.json`、approve/reject、风险维度,均与现状不符)。本 spec 取代之。

## 为什么只有两块可测

Agent 对已解析企业**固定 `insufficient_evidence`**、不出 approve/reject、未接风险数据源。所以:

| 指标 | v1 | 原因 |
|---|---|---|
| 推荐准确率 | ❌ N/A | 不出 approve/reject,无对错可评 |
| 风险命中率 | ❌ N/A | 未接制裁/司法/负面数据,无风险可命中 |
| **企业识别 P/R** | ✅ | `resolve_supplier` 是真正的分类任务,可算 P/R |
| **scope recall@k** | ✅ | FAISS 语义检索,经典 IR 指标 |
| GraphRAG 精准率 | ⏸ 后置 | via_person 同名假阳性在数据内无真值,只能人工抽检 |

## 红线

- **无 LLM**、无网络、无 LLM-as-judge。纯集合运算。
- 复用 `deepresearch_agent.agents.graph.run_research` 所依赖的同一批组件(`resolve_supplier`、`ScopeRetriever`),**不建第二条执行路径**。
- 真实 golden 数据不出库(gitignore);合成 golden 提交进库供 CI。

## 数据:双轨 golden 集

- **合成 golden(提交,CI 用)**:引用 `tests/fixtures/procurement/` 的合成企业(如 `示例科技股份有限公司` / `91330000123456789X`),验证**指标逻辑正确性 + 解析行为**。放 `evals/procurement/entity_resolution.synthetic.yaml`、`evals/procurement/scope_recall.synthetic.yaml`。
- **真实 golden(本地,不提交)**:引用真实 `derived/companies.sqlite3`,跑出**有意义的真实数字**。约定文件名 `*.local.yaml`,`.gitignore` 加 `evals/procurement/*.local.yaml`。
- runner 参数化 `database_path` + golden 文件路径,合成/真实同一套代码。

## 模型(`eval/models.py`)

```python
class GoldenEntityCase(BaseModel):
    case_id: str
    question: str
    expected_status: Literal["resolved", "ambiguous", "not_found"]
    expected_code: str | None = None            # status=resolved 时必填
    expected_candidate_codes: list[str] = []    # status=ambiguous 时可校验候选集

class GoldenScopeCase(BaseModel):
    case_id: str
    query: str
    expected_codes: list[str]                    # 应被召回的企业信用代码
    k: int = 10

class EntityResolutionMetrics(BaseModel):
    total: int
    accuracy: float          # status 匹配 + (resolved 时) code 匹配
    resolved_precision: float
    resolved_recall: float

class ScopeRecallMetrics(BaseModel):
    total: int
    mean_recall_at_k: float
    mean_precision_at_k: float
```

YAML 顶层是 `cases: [...]`,`model_validate` 逐条校验。

## 指标(`eval/metrics.py`,纯函数、无 IO)

### 企业识别
每个 case:跑 `resolve_supplier(question, repository)` 得 `CompanyResolution`。
- **正确** = `resolution.status == expected_status` 且(当 `expected_status=="resolved"`)`resolution.unified_social_credit_code == expected_code`。
- `accuracy = 正确数 / total`。
- 把"resolved"当正类算 P/R:
  - `resolved_precision = 正确 resolved 数 / 预测为 resolved 的数`(预测 resolved 数为 0 → 定义为 1.0)。
  - `resolved_recall = 正确 resolved 数 / 期望为 resolved 的数`(期望 resolved 数为 0 → 1.0)。
- 函数签名:`entity_resolution_metrics(cases: list[GoldenEntityCase], resolutions: list[CompanyResolution]) -> EntityResolutionMetrics`(两列表按序对应;runner 负责调用 `resolve_supplier` 产出 `resolutions`,metrics 纯算)。

### scope recall@k
每个 case:`retriever.search(query, k)` → 取 top-k 的 `unified_social_credit_code` 去重集合 `retrieved`。
- `recall_at_k = |set(expected) ∩ retrieved| / |set(expected)|`(expected 空 → 跳过该 case 或记 1.0;约定 expected 非空)。
- `precision_at_k = |set(expected) ∩ retrieved| / |retrieved|`(retrieved 空 → 0.0)。
- 聚合取均值。
- 签名:`scope_recall_metrics(cases: list[GoldenScopeCase], retrieved_per_case: list[set[str]]) -> ScopeRecallMetrics`(retriever 调用在 runner,metrics 纯算)。

## Runner(`eval/runner.py`)

- `run_entity_resolution(repository, cases) -> EntityResolutionMetrics`:对每 case 调 `resolve_supplier`,交 `entity_resolution_metrics`。**零下载、CI 核心。**
- `run_scope_recall(retriever, cases) -> ScopeRecallMetrics`:对每 case 调 `retriever.search`,交 `scope_recall_metrics`。**需 `.[rag]` + 已建索引(bge 模型),标 slow。**
- `load_entity_cases(path) -> list[GoldenEntityCase]` / `load_scope_cases(path)`:读 YAML。
- 不依赖 LangGraph;`resolve_supplier`/`ScopeRetriever` 是 `run_research` 的同源组件。

## CLI

`deepresearch_agent.cli` 加子命令(保持现有单问题 CLI 向后兼容):

```
python -m deepresearch_agent.cli eval entity --database <db> --cases <yaml>
python -m deepresearch_agent.cli eval scope  --database <db> --index <faiss> --cases <yaml>
```

输出(示例):
```
Eval: entity resolution (procurement)
  cases=5  accuracy=1.00  resolved_precision=1.00  resolved_recall=1.00
```

argparse 用子解析器;`eval` 下再分 `entity`/`scope`。现有 `cli "<question>"` 路径不变。

## 测试

- `tests/test_eval_models.py`(CI):加载合成 golden YAML,`model_validate` 通过;字段约束(resolved 必带 code)。
- `tests/test_eval_metrics.py`(CI):手工构造 `CompanyResolution` 列表 + cases → 断言 `accuracy`/`resolved_precision`/`resolved_recall` 精确值(含全对、部分错、not_found、ambiguous);手工 `retrieved_per_case` → 断言 recall/precision@k(含全召回、部分、零召回)。
- `tests/test_eval_runner.py`(CI):用 `company_database_path` fixture 建库,跑合成 entity golden → metrics 达标(如 accuracy==1.0)。
- `tests/test_eval_scope_runner.py`(**`@pytest.mark.slow`**):建 FAISS 索引(bge)后跑合成 scope golden → `mean_recall_at_k` 达标。
- `tests/test_cli.py`:`eval entity`/`eval scope` parser 路径解析正确;现有单问题路径回归。

## 合成 golden 内容(提交)

`entity_resolution.synthetic.yaml`(基于 fixture):
- `resolved`:`核验示例科技股份有限公司` → code `91330000123456789X`。
- `resolved`(别名):`核验示例设备有限公司` → 同 code(曾用名解析)。
- `not_found`:`核验不存在企业` → not_found。

`scope_recall.synthetic.yaml`:
- `工业设备制造` → expected_codes 含 `91330000123456789X`,k=10。

(真实 golden 由用户本地补,不提交。)

## 改动面

- 新:`src/deepresearch_agent/eval/{__init__,models,metrics,runner}.py`、`evals/procurement/{entity_resolution,scope_recall}.synthetic.yaml`、`tests/test_eval_{models,metrics,runner,scope_runner}.py`。
- 改:`src/deepresearch_agent/cli.py`(加 `eval` 子命令,保持向后兼容)、`tests/test_cli.py`、`.gitignore`(加 `evals/procurement/*.local.yaml`)。
- 不改:agent 编排、图、schema、依赖(`.[rag]` 已存在;scope 测试标 slow)。
- 不引入:RAGAS / LlamaIndex / Phoenix / LLM-as-judge / Qdrant。Phoenix 留作后续本地调试工具单独评估;GraphRAG 精准率与风险/推荐指标待接入对应数据源后再补。
