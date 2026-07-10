# 模块 N3：业务/行业层进图设计

日期：2026-07-10

N2 让 Neo4j 成为生产图引擎（股权层）。**N3 往同一张图加"行业层"**：把登记的国标行业分类做成 `(:Industry)` 节点树，公司挂上去，与股权层共图。范围 **A**（数据层进图）：只灌图 + 验证，**不碰 Agent 检索、不加 backend 方法、不加报告类型**；Agent 面向的"输入业务→公司"检索接入留作后续。

## 数据事实

`companies` 表已有登记的国标行业**四级名称**（非代码）：`gb_industry_section`（门类，如"制造业"）、`gb_industry_division`（大类，如"专用设备制造业"）、`gb_industry_group`（中类）、`gb_industry_class`（小类）。每家公司自带完整四级链，所以**层级不用查外部国标码表**——每家的四字段本身就是它那条链。字段可能为 `None`（稀疏）。

## 红线

- 全**确定性**（登记字段直接建节点），**无 LLM**、**不结构化 `business_scope`**（自由文本细粒度仍归语义 scope，不进图）。
- SQLite 是事实源；Neo4j 是可重建产物。Neo4j 仅本地、不用云。
- 报告/researcher/writer/CLI/API/`Neo4jBackend` 一律不改。

## 节点身份规则（防错撞）

- 行业节点 `(:Industry {node_id, name, level})`，`node_id = "ind:{level}:{name}"`，`level` ∈ `门类/大类/中类/小类`；`node_id` 唯一约束。
- 与 `(:Entity)` **不同标签、不同 id 方案**，公司节点与行业节点**永不相撞**。
- 按 `(level, name)` 建 id：同名不同级 → 不同节点；同名同级 → **故意合并**（国标名称同级内唯一，不会假合并）。
- 多家公司同一小类 → **共享**同一个 `(:Industry)` 节点（"重叠即共性"，是"同行业"可查的载体）。公司之间不合并（各按信用代码唯一）。

## 数据模型（图）

- `(公司:Entity)-[:属于行业]->(最深已填级 :Industry)`。
- 层级链（深→浅，方向朝更宽）：`(小类)-[:隶属]->(中类)-[:隶属]->(大类)-[:隶属]->(门类)`，只在**非空**相邻级之间建。
- 稀疏处理：某级为 `None` 就跳过，链只连非空级，公司连到最深非空级。全空则该公司不建行业边。

## 组件

### 1. 读层：`CompanyRepository.iter_company_industries()`

新增只读方法，一条 `SELECT`：

```sql
SELECT unified_social_credit_code, gb_industry_section, gb_industry_division,
       gb_industry_group, gb_industry_class FROM companies
```

返回 `list[CompanyIndustry]`（新增小模型，`company_models.py`）：

```python
class CompanyIndustry(BaseModel):
    unified_social_credit_code: str
    gb_industry_section: str | None = None
    gb_industry_division: str | None = None
    gb_industry_group: str | None = None
    gb_industry_class: str | None = None
```

空串经 `none_if_blank` 归 `None`（与既有清洗一致）。

### 2. 灌图：`build_industry_neo4j(repository, driver)`

加到 `scripts/build_ownership_neo4j.py`（与股权灌图同属"灌图"，同文件）。**幂等且只影响行业子图**：

1. `CREATE CONSTRAINT industry_node_id IF NOT EXISTS FOR (i:Industry) REQUIRE i.node_id IS UNIQUE`。
2. `MATCH (i:Industry) DETACH DELETE i` —— **只清 Industry 节点及其 `属于行业`/`隶属` 边，不碰 `:Entity` 与股权边**。
3. 遍历 `iter_company_industries()`，对每家：
   - 组装非空四级链 `levels = [("门类", section), ("大类", division), ("中类", group), ("小类", class)]` 去掉 `None`。
   - `UNWIND` 批量 `MERGE (:Industry {node_id})` `SET name/level`。
   - 相邻级 `MERGE (deep)-[:隶属]->(shallow)`。
   - `MATCH (c:Entity {node_id: code})` 再 `MERGE (c)-[:属于行业]->(最深级 Industry)` —— 用 **MATCH 已有 Entity**（股权灌图先建），**不 MERGE Entity**（避免给不在图中的公司凭空造孤儿节点）；MATCH 不到就跳过。

> 与 `build_ownership_neo4j` 独立：先跑股权灌图建 `:Entity`，再跑行业灌图挂 `:Industry`。二者各自幂等、互不清对方。

### 3. 不改动

`Neo4jBackend` 四方法仍只查 ownership；`agents/`、`run_research`、CLI、API、报告类型、SQLite schema 均不动。行业节点这一版只经 **Cypher / Neo4j Browser** 使用。

## 落地后即可用（无需新代码）

```cypher
// 输入行业名 → 该行业公司
MATCH (i:Industry {name: $行业})<-[:属于行业]-(c:Entity) RETURN c

// 同行业 + 同控制人 = 集中度线索（须人工复核，非认定）
MATCH (i:Industry)<-[:属于行业]-(c:Entity)<-[:SHAREHOLDING|INVESTMENT*1..5]-(ctrl:Entity)
WITH i, ctrl, collect(DISTINCT c) AS cs WHERE size(cs) >= 2
RETURN i.name, ctrl.display_name, cs
```

Neo4j Browser（`localhost:7474`）里股权层 + 行业层合体可视化，零额外代码。

## 测试

`@pytest.mark.neo4j`（默认排除、连不上跳过；本会话真起 Neo4j 跑绿）。用**主 procurement fixture**（`company_database_path`，含 `gb_industry_*`）；期望值从 `repository.iter_company_industries()` **算出来**、不写魔数。

- **读方法**（不需 Neo4j，普通用例）：`iter_company_industries()` 返回每家公司的四级名称；空串归 `None`；条目数 = 公司数。
- **灌图 · 节点数**：`build_industry_neo4j` 后，Neo4j `(:Industry)` 节点数 == 数据里 distinct `(level, name)` 数（从 `iter_company_industries` 算）。
- **灌图 · 归属边**：有 ≥1 非空行业级的公司都有一条 `属于行业` 边到其最深级；边数 == 这类公司数。
- **灌图 · 层级链**：任取一家有完整四级的公司，`(小类)-[:隶属]->(中类)-[:隶属]->(大类)-[:隶属]->(门类)` 链在 Neo4j 中存在。
- **共享**：若 fixture 有 ≥2 家公司同一小类，断言它们指向**同一个** `(:Industry)` 节点（`属于行业` 目标 `node_id` 相同）。
- **幂等**：连续跑两次 `build_industry_neo4j`，节点/边数不变（`DETACH DELETE` + `MERGE`）。
- **不越界**：跑行业灌图后，`(:Entity)` 节点数与股权边数不变（行业灌图不碰股权子图）。

## 改动面

- 新：`build_industry_neo4j`（加到 `scripts/build_ownership_neo4j.py`）、`CompanyIndustry` 模型（`company_models.py`）、`iter_company_industries`（`company_repository.py`）、`tests/test_industry_layer_neo4j.py`。
- 不改：`neo4j_backend.py`、`agents/`、`cli.py`、`api.py`、`state.py`、SQLite schema、依赖。
- 复用：N2 的 driver/灌图模式、`docker-compose`、`.[neo4j]`、`@pytest.mark.neo4j`、主 procurement fixture。Agent 面向的行业检索接入 = 后续单独模块。
