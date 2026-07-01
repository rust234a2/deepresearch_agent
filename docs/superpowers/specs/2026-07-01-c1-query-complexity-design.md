# 模块 C1：查询复杂度检测设计

日期：2026-07-01

本文件是路线图阶段 C 第一块 **C1** 的设计 spec。阶段 A、B 已完成。C1 是**全项目唯一引入 LLM 的环节**：把用户查询判成 简单/中等/复杂，供 C2 路由。**确定性优先、LLM 只做精修、带确定性兜底**。

## 背景与定位

现有检索能力：具名企业核验（A5）、经营范围语义检索（scope）、GraphRAG 能力检索 + 围标线索（B7）。C2 要按查询复杂度路由到不同策略。C1 就是那个分类器。

**红线**：LLM **只发查询文本**（绝不发企业数据，守数据本地化）；LLM 不可用/失败 → 回退确定性启发式；LLM **不**做采购结论、只做查询分类。

## 三级定义

| 级别 | 含义 | C2 将路由到（后续模块） |
|---|---|---|
| `simple` | 纯核验单个企业，或纯能力检索 | 传统检索（具名核验 / scope） |
| `medium` | 按能力找企业 **并** 涉及它们之间的关系 | scope + 图融合（≈ B7） |
| `complex` | 某具体企业的深层股权/控制关系（多跳） | GraphRAG 多跳 |

## 架构

`query_complexity.py`：

- `classify_heuristic(query, repository) -> ComplexityResult`：确定性，永远可用，即兜底。
- `classify_complexity(query, repository, llm=None) -> ComplexityResult`：编排——有 `llm` 就先试，返回合法级别则采用（`method="llm"`），否则/异常回退 `classify_heuristic`。
- `llm` 是**注入的可调用对象** `Callable[[str], str | None]`（返回 `"simple"/"medium"/"complex"` 或 None），C1 核心**不依赖任何 LLM 库**（可 stub 测）。

### 结果模型

```python
class ComplexityResult(BaseModel):
    level: Literal["simple", "medium", "complex"]
    method: Literal["heuristic", "llm"]
    reasoning: str
```

### 启发式规则（确定性）

两个信号：
- **关系信号** = 查询是否含关系/控制/多跳关键词 `RELATIONSHIP_KEYWORDS`（`控制人/实控人/实际控制/控股/母公司/子公司/股东/持股/持有/投资/关联/关系/围标/串标/穿透/背后/一伙/同一控制/共同控制/最终受益/谁控制/谁持有/路径` 等，子串匹配）。
- **具名企业信号** = `repository.resolve_text(query).status in {"resolved", "ambiguous"}`。

判级：

| 关系信号 | 具名企业 | 级别 |
|---|---|---|
| 有 | 有 | `complex` |
| 有 | 无 | `medium` |
| 无 | — | `simple` |

`reasoning` 记录命中的信号（如 "含关系关键词『实控人』且指名企业"）。

## DeepSeek LLM 分类器（可选 `.[llm]` extra）

`llm/deepseek.py`（或 `deepseek_classifier.py`）：`build_deepseek_classifier(...) -> Callable[[str], str | None] | None`。

- **懒加载 `openai` SDK**（DeepSeek 为 OpenAI 兼容），指向 `base_url="https://api.deepseek.com"`、`model="deepseek-chat"`（均可配）。
- 读 `DEEPSEEK_API_KEY`（环境变量）；无 key 或 `openai` 未装 → `build_*` 返回 `None`（即无 LLM，走兜底）。
- 返回的 `classify(query)`：用严格提示词（只输出 simple/medium/complex 之一 + 三级判据），调用 chat completion，解析出级别 token；**任何异常/无法解析 → 返回 `None`**（交给编排回退启发式）。
- **只发查询文本**，提示词里不含任何企业数据。
- 新增可选依赖组 `.[llm] = ["openai>=1.0"]`；`.env.example` 加 `DEEPSEEK_API_KEY=`。

## 范围

C1 只交付**分类器**。**不**接进 `run_research`/graph 路由（那是 C2）。C3 结构化生成、C4 降级重试是后续。

## 测试

**启发式（`tests/test_query_complexity.py`，无 LLM、无网络）**，用 `company_database_path` fixture 的 repository：
- `"核验示例科技股份有限公司"` → `simple`（具名、无关系词）。
- `"哪些企业能做注塑成型"` → `simple`（能力、无关系词）。
- `"哪些做注塑的供应商互相关联"` → `medium`（关系词、无具名）。
- `"示例科技股份有限公司的最终实控人是谁"` → `complex`（具名 + 关系词）。
- `method == "heuristic"`。

**编排回退**：
- `classify_complexity(query, repo, llm=lambda q: "complex")` → `level="complex"`、`method="llm"`。
- `llm=lambda q: None` 或 `llm` 抛异常 → 回退启发式（`method="heuristic"`）。
- `llm` 返回非法值（如 `"weird"`）→ 回退启发式。

**DeepSeek 适配器**（`tests/test_deepseek_classifier.py`，不打真实网络）：
- 无 `DEEPSEEK_API_KEY`（monkeypatch 删 env）→ `build_deepseek_classifier()` 返回 `None`。
- 解析逻辑：注入一个假的 completion 调用（monkeypatch 或依赖注入 client），返回文本 `"complex"` → `classify` 得 `"complex"`；返回垃圾 → `None`。

## 改动面

- 新文件：`src/deepresearch_agent/query_complexity.py`、`src/deepresearch_agent/llm/deepseek.py`（+ `llm/__init__.py`）、`tests/test_query_complexity.py`、`tests/test_deepseek_classifier.py`。
- `pyproject.toml`：加可选依赖 `.[llm]`；`.env.example`：加 `DEEPSEEK_API_KEY`。
- 复用 `CompanyRepository.resolve_text`。
- **无 schema 变更；LLM 依赖为可选 extra，核心不依赖它；只发查询文本。** 不接编排（C2）。
