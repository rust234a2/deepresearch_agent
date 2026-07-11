# 真实企业识别 Golden 生成 设计

日期：2026-07-12
状态：设计已确认，待落实施计划

## 背景

Eval v1 已落地企业识别 P/R 指标（`eval/` 包 + `cli eval entity`），但当前提交进库的 golden 只有 3 条**合成假题**（`evals/procurement/entity_resolution.synthetic.yaml`，`示例科技股份有限公司` 之类）。它只能验证「评测机制能跑」，跑出来的分数没有业务意义。

本模块补齐**真实 golden**：用真库里真企业名编题、真值取自数据库原始事实，第一次量出企业识别在 3506 家真企业上的真实召回率/精准率，作为以后改代码的回归基准。

## 目标

- 提供一个**起草脚本**，读真库、一次性扫库挑题，起草 `evals/procurement/entity_resolution.local.yaml`（已 gitignored、不出库）。
- 覆盖四类失败模式：`resolved`（法定名）、`resolved`（曾用名/alias）、`ambiguous`（歧义）、`not_found`。
- 生成逻辑与 `resolve_text` 语义**可证明一致**，真值全部取自数据库原始事实，**绝不**从 `resolve_text` 输出反推（否则是拿函数测自己，恒真无意义）。
- 守住红线：脚本只往终端回**聚合数字**（各类题条数），真企业名只写进 `.local.yaml`。

## 非目标（本轮不做）

- **scope recall 的真实 golden**：需先 `build_scope_index` 建 FAISS（bge、重、慢），留后续。本轮只做企业识别。
- **改 metrics**：`entity_resolution_metrics` 对 ambiguous 只校验 `status=="ambiguous"`，不校验候选集是否精确等于 `expected_candidate_codes`。本轮保持不变；候选集精确校验列为后续扩展。
- **全量属性测试**：不对 3506 家每次跑全量。扫库是一次性离线挑题动作，CI 只跑挑出来的几十条。
- 子串型歧义（一个查询在非嵌套位置同时命中两个更短的不同名）不在本轮生成，作为已知局限记录。

## 核心原则

### 独立真值（最重要）

真值只来自数据库原始事实（法定名、alias、信用代码），不来自被测函数 `resolve_text` 的输出。中心数据结构是一个多重映射：

```
name_to_codes: dict[normalized_name, set[code]]   # over 所有 legal_name ∪ alias
```

- 归一化用 `deepresearch_agent.company_database.normalize_company_name`（与 `resolve_text` 同一函数）。
- 映到恰好 1 个代码 → 干净的 resolved 题源。
- 映到 ≥2 个代码 → 天然 ambiguous 题源。

**与 `resolve_text` 一致性的论证**：查询 `Q = 某个原始名 N`（归一化为 `nQ`）时，`resolve_text` 命中的候选是所有满足 `_contains_name(nQ, 归一化候选名)` 的名字。
- 与 `nQ` **等长相等**的名字（即那些归一化后 == `nQ` 的名字）全部保留（`_drop_dominated_matches` 仅丢 `text != other_text and text in other_text` 的真子串）。
- 比 `nQ` **更短**且被包含的名字被支配丢弃。
- 比 `nQ` **更长**的名字不会被 `nQ` 包含，压根不命中。

因此查询 `N` 的存活集恰好 = `name_to_codes[nN]`：为 1 → resolved 到那家，为 ≥2 → ambiguous。生成器据此贴标签，无需调用 `resolve_text`。

### 红线

- 脚本 stdout **只打印各类题的条数**（`法定名=x 曾用名=y 歧义=z not_found=k`），绝不打印真企业名。
- 真企业名只写进 `.local.yaml`（`.gitignore` 已含 `evals/procurement/*.local.yaml`）。
- 起草者（Claude）不读 `.local.yaml`；由用户本地肉眼审校。

## 架构

### 文件结构

- 新增 `src/deepresearch_agent/eval/golden_gen.py`：纯生成逻辑（可测、进 CI）。
- 新增 `scripts/generate_entity_golden.py`：薄 CLI 包装（读真库 → 调 golden_gen → 写 yaml → 打印条数）。
- 修改 `src/deepresearch_agent/company_repository.py`：新增 `iter_aliases()` 方法（一次查询取全部 `(code, alias)`，镜像已有 `get_all_company_names()`）。
- 新增 `tests/test_golden_gen.py`：对生成逻辑做 TDD，用现场构建的小 sqlite fixture（含预置的 alias 与同名对）。
- 修改 `tests/test_company_repository.py`：补 `iter_aliases()` 的用例。

### 数据流

```
真库 sqlite
  → CompanyRepository.get_all_company_names()  (code → legal_name)
  → CompanyRepository.iter_aliases()           (list[(code, alias)])
  → golden_gen.generate_entity_golden(names, aliases, seed, 各类条数)
  → list[GoldenEntityCase]
  → scripts 写 evals/procurement/entity_resolution.local.yaml
  → scripts 打印 category_counts（只有数字）
```

之后用户手动：审校 yaml → `cli eval entity --database <真库> --cases evals/procurement/entity_resolution.local.yaml` → 真 P/R。

## 生成算法

输入：`company_names: dict[code, legal_name]`、`aliases: list[tuple[code, alias]]`、`seed: int`、`n_legal`、`n_alias`、`n_not_found`、`ambiguous_cap`。

先构建：
- `name_to_codes: dict[str, set[str]]`：对每个 legal_name 和每个 alias，`name_to_codes[normalize(name)].add(code)`。
- `legal_by_code: dict[code, legal_name]`、`aliases_by_code: dict[code, list[alias]]`（保留原始拼写用于出题）。
- 复用 `from deepresearch_agent.company_repository import _contains_name` 保证 not_found 校验语义一致。

四类生成（用 `random.Random(seed)` 采样保证可复现；脚本是普通 Python，`random` 可用）：

1. **resolved 法定名**：候选 = `{code | name_to_codes[normalize(legal_by_code[code])] == {code}}`（唯一）。采样 `n_legal` 个 → `question = legal_name`，`expected_status="resolved"`，`expected_code=code`。

2. **resolved 曾用名**：候选 = `{(code, alias) | name_to_codes[normalize(alias)] == {code}}`（该 alias 归一化后只映到这一家）。采样 `n_alias` 个 → `question = alias`，`expected_status="resolved"`，`expected_code=code`。测的是 alias 匹配路径。

3. **ambiguous 歧义**：对每个 `normalized_name` 满足 `len(name_to_codes[normalized_name]) >= 2` → `question = 该名的一个原始拼写`（优先取某家的 legal_name，否则取 alias 文本），`expected_status="ambiguous"`，`expected_candidate_codes = sorted(codes)`。去重（同一 normalized_name 只出一题）。数量超过 `ambiguous_cap` 时截断并 `log` 丢弃了多少（不静默截断）。

4. **not_found**：用固定模板 + seed 合成 `n_not_found` 个名字（例 `f"核验{seed}号不存在测试企业{i}有限公司"`），并**校验**：对该合成名的归一化串 `nQ`，`name_to_codes` 中不存在任一 key `c` 使 `_contains_name(nQ, c)` 为真（即库里没有任何名字被它包含）。校验不过则换一个。`expected_status="not_found"`。

`case_id`：稳定、可读、可含名字（yaml 本地不出库）；例 `resolved_legal_{i}`、`resolved_alias_{i}`、`ambiguous_{i}`、`not_found_{i}`。

`category_counts(cases) -> dict[str, int]`：按 `(expected_status, 是否 alias 出题)` 归类计数，供脚本只打印数字。

## 边界与降级

- 真库若**没有任何同名**（ambiguous 候选为 0）：脚本如实打印 `歧义=0`，用户据此得知真库无天然歧义题（这本身是有效信息）。
- 某类候选不足请求条数：取全部并 `log` 实际条数，不报错。
- 采样确定性：固定 `seed`，同库同 seed 产出完全一致。

## 测试策略

生成逻辑对**合成 fixture** 做 TDD（可提交、进 CI，零真数据）；真 `.local.yaml` 与真 P/R 由用户本地跑脚本产出。

fixture 需现场构建一个小 sqlite（复用 `company_database.build_company_database`，仿 `tests/conftest.py`），CSV 行精心构造以覆盖四类：
- 数家名字互不包含的普通企业（resolved 法定名题源）。
- 至少一家带唯一 alias（resolved 曾用名题源）。
- 至少一对**归一化后同名**的不同企业，或「A 的 alias == B 的 legal_name」（ambiguous 题源）。

用例断言：
- `generate_entity_golden` 产出的每条 resolved 题，`expected_code` 确等于数据库里该名对应的代码，且该名唯一。
- ambiguous 题的 `expected_candidate_codes` 恰等于 fixture 里那对同名企业的代码集。
- not_found 题的 question 归一化后不含任何库中名。
- **闭环校验**：把生成的 cases 喂给真正的 `run_entity_resolution(repository, cases)`，断言 `accuracy == 1.0`（生成器与 `resolve_text` 语义一致的端到端证明）。
- 确定性：同 seed 两次产出相等。
- `iter_aliases()`：返回 fixture 里全部 `(code, alias)` 对。

## 运行方式

```powershell
# 起草（真库本地跑，只回条数）
.\.conda-env\python.exe scripts/generate_entity_golden.py `
  --database data/procurement/derived/companies.sqlite3 `
  --output evals/procurement/entity_resolution.local.yaml

# 用户审校 .local.yaml 后，跑真 P/R
.\.conda-env\python.exe -m deepresearch_agent.cli eval entity `
  --database data/procurement/derived/companies.sqlite3 `
  --cases evals/procurement/entity_resolution.local.yaml
```

## 未来扩展

- ambiguous 候选集精确校验（`entity_resolution_metrics` 增加 candidate-set 比对）。
- 归一化边界题（全半角/括号/简称）的定向生成。
- 子串型歧义生成。
- scope recall 真实 golden（需先建 FAISS 索引）。
- 真实流量挖掘：从 Phoenix 追踪捞 `not_found`/`ambiguous` 的真实 query，人工确认后回补 golden。
