# 模块 Eval C1/C2：扰动鲁棒性 + 混合 scope 评测设计

日期：2026-07-16

给现有 Eval v1（`2026-07-11-eval-v1-deterministic-metrics-design.md`）补两块**有意义的真实质量数字**，都长在 `eval/` 包上、复用 `models / metrics / runner / golden_gen` 四件套，不另起执行路径。

- **C1 扰动鲁棒性**：企业识别的闭环 golden 恒 `accuracy≈1.0`（真值 DB 派生、与 `resolve_text` 语义一致 → 构造性满分），是**回归护栏、不是质量度量**。C1 造一套**真实输入变形**的 golden，量化 resolver 对用户实际打法（去后缀、错字、全半角、整句包裹）的鲁棒性。
- **C2 混合 scope 评测**：Eval v1 的 `scope recall@k` 需要人工标 `expected_codes`，且词面真值系统性低估语义检索。C2 用**确定性词面层（CI 下界）+ DeepSeek 判官层（补语义命中）**两个数字一起给，诚实标注召回是词面下界。

## 背景：resolver 的真实匹配行为（C1 要测什么）

`CompanyRepository.resolve_text` 两段式（读码前已核实）：
1. **全名子串**：登记全名（`normalize_company_name` 归一化后）必须作为**子串出现在查询里**（`_contains_name(query, db_name)`，中文子串 / ASCII 词边界）。
2. **片段兜底**（第一段无命中才走 `_partial_name_matches`）：候选名去掉 `_COMPANY_SUFFIXES` 后缀取词干，词干（≥4 字）或其 ≥4 字连续片段出现在查询里即命中并按长度打分。

**关键事实：resolver 无任何模糊/编辑距离匹配。** 预判各扰动行为（C1 将量化验证）：

| 扰动 | 例 | 预判 |
|---|---|---|
| 去后缀 | 万马科技股份有限公司 → 万马科技 | 片段兜底接住，回收率高 |
| 相邻字对调（错字代理） | 万马科技 → 万科马技 | 整字破坏 + 凑不出 ≥4 字干净片段 → **崩（核心发现）** |
| 全半角/空格 | ＡＢＣ / 加空格 | `normalize` 吸收，~100%（控制项） |
| 整句包裹 | 核验 X 的工商信息 | 全名仍是子串，~100%（控制项） |

## 红线（两块共同）

- **复用同源组件**：C1 走 `resolve_supplier`，C2 走 `ScopeRetriever`，均为 `run_research` 依赖的同一批组件，不建第二条执行路径。
- **真名不出库**：所有真实 golden（`*.local.yaml`）Git 忽略（`.gitignore` 已有 `evals/procurement/*.local.yaml`，两块的 `.local.yaml` 均被覆盖）；生成脚本 stdout 与 CLI 指标**只有聚合数、无真名**。
- **C1 非循环**：扰动真值 = **来源**（这条扰动从哪家企业生成），绝不用 `resolve_text` 反推期望。种子唯一性用一个**独立的粗粒度子串扫描**判定，刻意不等于 resolver 两段式逻辑。
- **C2 判官数据外发**：DeepSeek 判官把经营范围原文发云端，是**新的数据外发面**。归入用户已明确授权的云端豁免范围（与记忆线、网页呈现层同级）；**CLAUDE.md 核心红线文本不删，仅本线豁免**，此处显式留档。CI 零网络（fake judge），真链路标 `@pytest.mark.llm`。

---

## 第 1 节：C1 扰动鲁棒性评测

### 真值（来源法）

每条扰动从已知企业 X 生成，理想答案恒为"解析到 X"。为保证"理想=X"无歧义，**生成前用独立粗粒度扫描**筛种子 X：

- X 的词干 = X 归一化法定名去掉一个尾部公司后缀（后缀常量可复用 `_COMPANY_SUFFIXES`；**独立性体现在匹配逻辑，不在后缀表**）。
- 种子资格：词干长度 ≥ 4，且该词干**不是任何其它企业**归一化法定名/别名的子串（纯子串扫描全库，粗粒度、非 resolver 两段式）。
- 生成某条扰动 P 后，若 P（归一化）里意外**包含另一家企业的完整归一化名**作子串（会引入合法竞争匹配），跳过该条，保来源纯净。

这样每条留存扰动的理想答案都无争议地是"resolved → X"；resolver 返回 not_found / ambiguous / 别家 = 真实弱点，与"扰动怎么生成的"无关 → 非循环。

### 扰动类型集（4 类）

`eval/perturb.py`（纯逻辑、确定性、seed 驱动），每个函数吃归一化前的原名、返回扰动串或 `None`（不适用）：

- `drop_suffix(name)`：去掉尾部公司后缀（如 `股份有限公司`）。名里无已知后缀 → None。
- `transpose(name, rng)`：随机取词干内一对相邻汉字对调（错字的确定性代理，**不引混淆字典**，YAGNI）。词干 < 2 字 → None。
- `width_variant(name)`：把 ASCII 段转全角、或在字间插一个空格（`normalize` 应吸收）。无可变字符 → None。
- `noise_wrap(name)`：包成整句 `核验{name}的工商信息`。恒可用。

不做加/去省市前缀——加前缀可能误撞别家、破坏来源纯净。

### 模型（`eval/models.py`）

`GoldenEntityCase` 加可选字段（向后兼容，现有 golden 不受影响）：

```python
class GoldenEntityCase(BaseModel):
    ...
    perturbation_type: str | None = None   # C1 扰动类型；None=非扰动题
```

新指标模型：

```python
class PerturbationTypeMetrics(BaseModel):
    perturbation_type: str
    n: int
    recovery: float   # resolved 且 code==源X 的占比
    wrong: float      # resolved 但 code!=源X 的占比
    miss: float       # not_found 或 ambiguous 的占比  (recovery+wrong+miss==1)

class PerturbationRobustnessMetrics(BaseModel):
    total: int
    overall_recovery: float
    per_type: list[PerturbationTypeMetrics]   # 按 perturbation_type 排序
```

### 生成器（`eval/golden_gen.py`）

新 `generate_perturbation_golden(company_names, aliases, *, seed, per_type_n=25) -> list[GoldenEntityCase]`：

1. 建 `name_to_codes` 复用现有 `_build_name_index`。
2. 用上述独立扫描选合格种子 X（词干 ≥4 字且全库唯一）。
3. 对每个种子、每种扰动类型生成 P；跳过 None、跳过重引别家全名的 P；`expected_status="resolved"`、`expected_code=X`、`perturbation_type=T`。
4. 每类型取前 `per_type_n` 条（`sorted` 后 `rng.shuffle(seed)`，确定可复现）。
5. `category_counts` 扩展为按 `perturbation_type` 计数。

薄 CLI `scripts/generate_perturbation_golden.py`：`--database --output(默认 evals/procurement/perturbation.local.yaml) --seed --per-type-n`；**stdout 只打印各扰动类型条数**。

### 指标 + Runner

- `eval/metrics.py`：`perturbation_metrics(cases, resolutions) -> PerturbationRobustnessMetrics`，纯集合运算，按 `case.perturbation_type` 分组算 recovery/wrong/miss（`resolutions[i]` 对 `cases[i]`，源 X = `case.expected_code`）。
- `eval/runner.py`：`run_perturbation_robustness(repository, cases)` 对每 case 跑 `resolve_supplier(case.question, repository)`，交 `perturbation_metrics`。`load_entity_cases` 已能读带新字段的 YAML（Pydantic 向后兼容），无需新 loader。

### CLI

`deepresearch_agent.cli` 的 `eval` 子命令加 `perturb`：

```
python -m deepresearch_agent.cli eval perturb --database <db> --cases <yaml>
```

输出（**按类型、无真名**）：

```
Eval: perturbation robustness (procurement)
  total=80  overall_recovery=0.68
  drop_suffix   n=20  recovery=0.95  wrong=0.00  miss=0.05
  transpose     n=20  recovery=0.10  wrong=0.05  miss=0.85
  width_variant n=20  recovery=1.00  wrong=0.00  miss=0.00
  noise_wrap    n=20  recovery=1.00  wrong=0.00  miss=0.00
```

### 测试（C1）

- `tests/test_eval_perturb.py`（CI）：各扰动函数纯逻辑——去后缀正确、对调换位、全角转换、整句包裹；不适用返回 None。
- `tests/test_eval_metrics.py`（CI）：手工构造 `cases + resolutions` → 断言 per_type recovery/wrong/miss 精确值（含全回收、误解析、漏解析混合）。
- `tests/test_eval_golden_gen.py`（CI，扩展现有）：合成 fixture（含词干独特与词干互撞的企业）→ 断言只选唯一词干种子、来源纯净（无重引别家全名）、每类型条数。
- `tests/test_eval_runner.py`（CI，扩展）：现场建库跑合成扰动 golden → 断言合成集上 `drop_suffix`/`width_variant`/`noise_wrap` 高回收、`transpose` 低回收（坐实"无模糊匹配"）。
- `tests/test_cli.py`：`eval perturb` parser 路径 + 输出无真名。

### 合成 golden（提交）

`evals/procurement/perturbation.synthetic.yaml`：基于 `tests/fixtures/procurement/` 的合成企业，每类型 1–2 条，供 CI 验证指标逻辑与解析行为（真实数字由用户本地跑脚本产出、不提交）。

---

## 第 2 节：C2 混合 scope 召回/精准评测

### 查询集（可提交）

`evals/procurement/scope_queries.yaml`——**通用能力词、无企业数据，故可提交**：

```yaml
cases:
  - {case_id: q_injection, query: 注塑成型, k: 10}
  - {case_id: q_wood, query: 木材加工机械, k: 10}
  - {case_id: q_autoparts, query: 汽车零部件, k: 10}
  # ... 约 15 条，覆盖"字面易命中"与"须语义推断"两类
```

新模型 `ScopeQueryCase(case_id: str, query: str, k: int = 10)`——期望不由人标，运行时词面/判官计算。

### 确定性词面层（无 LLM，CI 安全，默认跑）

每查询 T，取 retriever top-k 的信用代码集 `retrieved`：

- **词面命中判定** `_scope_contains(scope_text, T)`：`T`（归一化）作子串出现在企业经营范围原文（归一化）中。
- `lexical_precision@k` = |{c∈retrieved : 经营范围含 T}| / |retrieved|。
- `lexical_tp_all` = **全库**经营范围含 T 的企业集合（新增只读 `CompanyRepository.iter_business_scopes() -> Iterable[tuple[code, scope]]`，读 `companies.business_scope` 列）。
- `lexical_recall@k` = |retrieved ∩ lexical_tp_all| / |lexical_tp_all|，**显式标注"词面下界代理、非真召回"**；附 `lexical_tp_count = |lexical_tp_all|` 作分母语境。

### DeepSeek 判官层（标 slow/llm，需 key）

`eval/scope_judge.py`：`build_deepseek_scope_judge()` 复用 `llm/deepseek.py` 的 OpenAI 兼容 client 模式，返回可调用 `judge(query, scope_text) -> bool`（约束式是/否："该经营范围是否实际覆盖能力 T"）。

每查询对 top-k 每家判定：

- `judged_precision@k` = |{c∈retrieved : judge 覆盖}| / |retrieved|。
- `noise@k` = 1 − `judged_precision@k`（top-k 里既非字面、也非语义相关的噪声）。
- `semantic_gain@k` = `judged_precision@k` − `lexical_precision@k`（**语义检索净价值**：真相关但不含字面词的命中占比）。

**降级**：无 `DEEPSEEK_API_KEY` → judge=None → **跳过判官层、只出词面数，不报错**（照搬 `retrieval_available` 降级风格）。

### 模型 + 指标 + Runner

`eval/models.py`：

```python
class ScopeLexicalMetrics(BaseModel):
    total: int
    mean_lexical_precision_at_k: float
    mean_lexical_recall_at_k: float     # 词面下界代理
    mean_lexical_tp_count: float

class ScopeJudgedMetrics(BaseModel):
    total: int
    mean_judged_precision_at_k: float
    mean_noise_at_k: float
    mean_semantic_gain_at_k: float
```

- `eval/metrics.py`：`scope_lexical_metrics(...)` / `scope_judged_metrics(...)`，纯函数，输入 runner 备好的 `retrieved / lexical_tp / judge 结果`。
- `eval/runner.py`：`run_scope_lexical(retriever, repository, cases)`；`run_scope_judged(retriever, repository, judge, cases)`。

### CLI

新增子命令 `eval scope-quality`（**v1 的 `eval scope` recall@k 保持不动**——两套 case schema：v1 `GoldenScopeCase`（带 `expected_codes`）走 `scope`，C2 `ScopeQueryCase`（无期望）走 `scope-quality`，不撞车）：

```
python -m deepresearch_agent.cli eval scope-quality --database <db> --index <faiss> --cases <scope_queries.yaml>          # 词面层
python -m deepresearch_agent.cli eval scope-quality --database <db> --index <faiss> --cases <scope_queries.yaml> --judge  # + 判官层（需 key）
```

输出：词面指标恒打印；`--judge` 时追加判官指标。

### 测试（C2）

- `tests/test_eval_metrics.py`（CI，扩展）：手工构造 `retrieved / lexical_tp / judge 布尔` → 断言 lexical/judged 指标精确值（含零命中、全命中、语义增益）。
- `tests/test_scope_judge.py`（CI）：fake OpenAI client（零网络）→ 判官解析是/否正确；无 key → judge 构造返回 None。
- `tests/test_eval_scope_runner.py`（`@pytest.mark.slow`，扩展）：建 FAISS 索引跑合成查询 → 词面指标；判官层用 fake judge 断言 runner 装配。
- `tests/test_cli.py`：`eval scope-quality [--judge]` parser 路径；无 key 降级只出词面；v1 `eval scope` 回归不变。

真实数字由用户本地跑（真库 + FAISS 索引 +（判官层）`DEEPSEEK_API_KEY`）。

---

## 改动面

**新增**：
- `src/deepresearch_agent/eval/perturb.py`、`scope_judge.py`
- `scripts/generate_perturbation_golden.py`
- `evals/procurement/scope_queries.yaml`（提交）、`evals/procurement/perturbation.synthetic.yaml`（提交）
- 对应 `tests/test_eval_perturb.py`、`test_scope_judge.py`（其余测试扩展现有文件）

**修改**：
- `src/deepresearch_agent/eval/{models,metrics,runner,golden_gen}.py`
- `src/deepresearch_agent/cli.py`（`eval` 加 `perturb` 与 `scope-quality`；v1 `entity`/`scope` 路径向后兼容不动）
- `src/deepresearch_agent/company_repository.py`（新增只读 `iter_business_scopes()`）
- 相关测试文件

**不改**：agent 编排、图、schema、Neo4j/记忆/网页层。`.gitignore` 无需动（`*.local.yaml` 已覆盖）。

**不引入**：RAGAS / LlamaIndex / Phoenix-LLM-eval。C2 判官是**项目自控的单一约束式是/否调用**，非通用 LLM-eval 框架，且默认关、可降级。

## 分两段实施

一份 spec，实施计划**分两段**，各自 TDD、各自合并推送（[[push-policy]]）：

- **Plan 1 = C1**：`perturb.py` + 模型/生成器/指标/runner/CLI + 合成 golden + 测试。产出：真库扰动鲁棒性表。
- **Plan 2 = C2**：查询集 + 词面层（含 `iter_business_scopes`）+ 判官层 + 模型/指标/runner/CLI + 测试。产出：词面 + 判官双指标。

C1 与 C2 无相互依赖，Plan 1 先做（纯确定性、零 key、CI 完整）。
