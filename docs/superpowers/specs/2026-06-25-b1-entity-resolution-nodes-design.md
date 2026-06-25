# 模块 B1：实体解析 → 节点表设计

日期：2026-06-25

本文件是路线图阶段 B（GraphRAG）第一块 **B1** 的设计 spec。阶段 A（A1–A5）已完成并合并。B1 把两份股权边里出现的所有实体合并去重成规范节点，落一张持久化 `graph_nodes` 表，作为 B2 边表 / B3 多跳 / B4 向量索引的统一节点身份地基。

## 背景与定位

A2 入库的 `company_shareholders` / `company_investments` 两表里，实体以"名称（+ 可选解析到的库内信用代码）"形式散落在多条边上：同一外部企业可能作为多家公司的股东反复出现，同名自然人散在多行。B1 把这些实体**去重成规范节点**，每个实体一行，给稳定 `node_id`，标 `in_database` / `is_person` / `node_type`，记 `mention_count`。

B1 只产节点登记，**不**建边表（B2）、不做向量（B4）、不做多跳（B3）。

## 全局约束（红线）

- **纯确定性、零 LLM**。
- **名称匹配 ≠ 身份认定**：同名自然人合并成一个节点是无奈之举（数据只有名字），节点标 `is_person=true`、`mention_count` 暴露其连接规模供下游判断重名；绝不据此认定控制关系。
- **名称连接**用 `normalize_company_name`（NFKC + casefold + 空白折叠），与 A2/A4 一致。
- **原子构建**：节点表在 `build_company_database` 同一事务内生成；schema 升 v4，`SCHEMA_VERSION` 与 `PRAGMA user_version` 同步；Repository 只读连接版本不匹配即报错要求重建。

## 节点来源与身份

**节点 = 两份边里出现过的实体**（锚点公司 + 对手方）。库内公司中完全不出现在任何边里的，不是图节点。

| 实体 | node_type | node_id | in_database | is_person |
|---|---|---|---|---|
| 库内公司（锚点或解析到的对手方，有信用代码） | `company` | 信用代码 | 1 | 0 |
| 外部企业（无码、非自然人、未命中基金关键词） | `company` | `ext:` + 规范化名 | 0 | 0 |
| 外部自然人（股东 `is_person`） | `person` | `person:` + 规范化名 | 0 | 1 |
| 外部基金/托管（无码、命中基金关键词） | `fund` | `fund:` + 规范化名 | 0 | 0 |

- **去重**：库内公司按信用代码合并；外部实体按 `(类型前缀, 规范化名)` 合并。同名自然人合并为一个节点（仅有名字，无法再分）。
- **基金判定**：规范化名命中基金关键词（复用 A4 噪声关键词，提取为 `company_models.FUND_NOISE_KEYWORDS` 共享常量：`证券投资基金/指数/etf/登记结算/中央结算/nominees/ubs/barclays/morgan/goldman/qfii`）→ `node_type="fund"`。`fund` 在此泛指被动/托管型机构（含登记结算、外资行 nominees）。
- **display_name**：库内公司取 `legal_name`；外部实体取边上原始名（`shareholder_name`/`investee_name`，按入库顺序首次出现者，确定性）。
- **mention_count**：该实体作为边端点被引用的总次数（锚点端 + 对手方端各计一次），供下游度/可靠性参考。

## 数据库

`SCHEMA_VERSION` 3 → **4**。新表（在 `_create_schema`）：

```sql
CREATE TABLE graph_nodes (
    node_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    node_type TEXT NOT NULL,            -- 'company' | 'person' | 'fund'
    in_database INTEGER NOT NULL,       -- 0/1
    unified_social_credit_code TEXT,    -- 库内公司才有
    is_person INTEGER NOT NULL,         -- 0/1
    mention_count INTEGER NOT NULL
);
CREATE INDEX idx_graph_nodes_normalized ON graph_nodes(normalized_name);
CREATE INDEX idx_graph_nodes_type ON graph_nodes(node_type);
```

`import_metadata` 不扩列（节点是派生产物，计数走构建摘要即可）。

## 构建

在 `_build_atomic_database` 的事务内、`_insert_shareholders` / `_insert_investments` 之后、写 `import_metadata` 之前，调用 `node_count = _insert_graph_nodes(connection, companies)`：

1. 由 `companies` 建 `code → legal_name` 映射。
2. `SELECT unified_social_credit_code, shareholder_name, normalized_shareholder_name, shareholder_credit_code, shareholder_is_person FROM company_shareholders`：锚点 → 库内公司节点（mention+1）；对手方有 `shareholder_credit_code` → 库内公司节点（mention+1），否则按 `shareholder_is_person` / 基金关键词归外部 person/fund/company 节点（mention+1）。
3. `SELECT unified_social_credit_code, investee_name, normalized_investee_name, investee_credit_code FROM company_investments`：同理（投资对手方恒非自然人）。
4. 把聚合后的节点逐条 `INSERT INTO graph_nodes`，返回节点数。

`build_company_database` 返回的摘要追加 `"nodes": node_count`（置于 counts 末尾，确定 CLI 打印顺序）。

## 数据模型（`company_models.py`）

```python
FUND_NOISE_KEYWORDS = (
    "证券投资基金", "指数", "etf", "登记结算", "中央结算", "nominees",
    "ubs", "barclays", "morgan", "goldman", "qfii",
)   # A4 RelatedPartyConfig.noise_keywords 默认引用此常量

class GraphNode(BaseModel):
    node_id: str
    display_name: str
    normalized_name: str
    node_type: Literal["company", "person", "fund"]
    in_database: bool
    unified_social_credit_code: str | None = None
    is_person: bool = False
    mention_count: int
```

`RelatedPartyConfig.noise_keywords` 默认改为引用 `FUND_NOISE_KEYWORDS`（行为不变，仅去重）。

## Repository 读层（`company_repository.py`）

- `SCHEMA_VERSION` 检查值随之变 4（导入常量，无需改动逻辑）。
- 新增 `get_graph_node(node_id: str) -> GraphNode | None`、`iter_graph_nodes() -> list[GraphNode]`（供 B2 消费）。

## 测试

**构建（`tests/test_company_database.py`）**：
1. 基础库（无股权）：`user_version == 4`；摘要含 `"nodes": 0`；`graph_nodes` 表存在且为空。
2. 带股权 fixture（`shareholders.csv`/`investments.csv`）：摘要 `"nodes": 3`；`graph_nodes` 含示例科技（`company`/`in_database=1`/`node_id=91330000123456789X`/`mention_count=6`）、张三（`person`/`node_id=person:张三`）、某外部子公司有限公司（`company`/`in_database=0`/`node_id=ext:...`）。
3. 用 `ownership_links` fixture 验证基金归类：`嘉实沪深300指数证券投资基金` → `node_type="fund"`、`node_id=fund:...`。
4. 新增两索引出现在 `sqlite_master`。

**CLI（`tests/test_company_database_cli.py`）**：两处摘要打印追加 ` nodes=0`。

**Repository（`tests/test_company_repository.py`）**：
1. `expected 3` → `expected 4`。
2. `get_graph_node("91330000123456789X")`（带股权库）返回 `company`、`in_database=True`；`get_graph_node("person:张三")` 返回 `person`、`is_person=True`；未知 id → `None`。
3. `iter_graph_nodes()` 返回全部节点。

## 改动面

- `company_database.py`：`SCHEMA_VERSION=4`、`_create_schema` 加 `graph_nodes` + 2 索引、`_insert_graph_nodes`、摘要加 `nodes`。
- `company_models.py`：`FUND_NOISE_KEYWORDS` 常量、`GraphNode` 模型、`RelatedPartyConfig` 默认引用常量。
- `company_repository.py`：`get_graph_node`、`iter_graph_nodes`。
- 测试：`test_company_database.py`、`test_company_database_cli.py`、`test_company_repository.py` 随 v4/摘要更新 + 新增节点用例。
- **真实库需重建**（schema v4）。不动 graph 边/向量/多跳（后续 B2+）。
