# 模块 A4 + A5：股权关联计算与 Agent 接入设计

日期：2026-06-25

本文件是路线图 **A4(关联计算)** 与 **A5(Agent 接入)** 的合并设计 spec。上游 A1–A3 已完成并合并:边数据清洗(A1)、边表入库(A2)、Repository 读层(A3)。A4 在 A3 之上算"关联供应商",A5 把"股权邻域(A3)+ 关联方(A4)"接进 LangGraph Agent。两者是生产/消费关系,合成一份 spec,实现拆两组任务。

## 背景与数据现实(真库验证)

股权数据无统一社会信用代码,公司用规范化全名连接。直接库内边稀少(股东 233 / 投资 250),但**通过共享外部节点**的间接关联大量存在(真库:1,476 个外部企业股东、1,407 个外部自然人、1,176 个外部被投资方各连接 ≥2 家库内公司)。头部外部企业节点全是托管/外资行/宽基基金(中证登 1580 家、UBS 266、Barclays 206、J.P.Morgan、Morgan Stanley、HKSCC Nominees 52 …),自然人头部(度 10–28)基本是重名碰撞。

因此 A4 的价值在于发现间接关联(围标识别、集中度、利益冲突),但必须区分**结构性噪声**(被动分散持有的基金/托管,确定无关 → 过滤)与**模糊线索**(自然人同名,可能真可能假 → 全展示 + 警示)。

## 全局约束(红线)

- **纯确定性、零 LLM**。
- **关联方是线索,不是结论**:绝不据此做控制关系认定或采购批准/拒绝。Agent 仍固定 `recommendation="insufficient_evidence"`。
- **数据缺失 ≠ 无风险**:空结果也要显式写一条"数据源未提供"的证据,不静默跳过。
- **名称匹配 ≠ 身份认定**:自然人关联一律低置信 + 须人工复核。
- **名称连接**:库内公司用 `normalize_company_name`(NFKC + casefold + 空白折叠)规范化全名匹配,与 A2 入库时一致。

---

## A4 关联计算

### 模块边界

- 新文件 `src/deepresearch_agent/ownership_links.py`:`RelatedPartyConfig` + `find_related_parties(repository, code, config=DEFAULT_CONFIG) -> list[RelatedParty]`。
- `company_models.py` 新增 `RelatedParty`、`OwnershipEdge` 两个模型。
- `company_repository.py` 新增三个批量读方法(供 A4 建反向索引):`get_all_company_names`、`iter_shareholder_edges`、`iter_investment_edges`。
- **无 schema 变更**:A4 在内存里扫一遍全部边(~93k 行 <200ms,Agent 每次研究只调一次)建反向索引。若日后成为热点再考虑物化(B 阶段)。

### 数据模型(`company_models.py`)

```python
class OwnershipEdge(BaseModel):          # Repository 批量读返回的轻量边
    company_code: str                    # 库内锚点公司代码
    node_name: str                       # 规范化后的对手方名(normalized_*)
    node_code: str | None = None         # 对手方解析到库内的代码,否则 None
    is_person: bool = False              # 仅股东边有意义;投资边恒 False

RelationType = Literal[
    "direct_shareholder",            # 库内公司 Y 是 X 的股东(Y 持有 X)
    "direct_investee",               # X 投资了库内公司 Y
    "shared_corporate_shareholder",  # X、Y 共享同一外部企业股东
    "shared_person_shareholder",     # X、Y 共享同一外部自然人(同名)
    "shared_investee",               # X、Y 共同投资同一外部实体
]

class RelatedParty(BaseModel):
    unified_social_credit_code: str      # 查询公司 X
    related_code: str                    # 关联库内公司 Y
    related_name: str                    # Y 的法定名称
    relation_type: RelationType
    via_node_name: str | None = None     # 经由的共享节点名;直接边为 None
    via_is_person: bool = False
    shared_degree: int | None = None     # 共享节点连接的库内公司总数(可靠性信号)
    confidence: float                    # 置信度
    reliability_note: str                # 可靠性/免责提示
```

### 置信度与提示分级

| relation_type | confidence | reliability_note(模板) |
|---|---|---|
| direct_shareholder | 0.9 | "登记直接持股关系:{Y} 持有 {X}。" |
| direct_investee | 0.9 | "登记直接投资关系:{X} 投资 {Y}。" |
| shared_corporate_shareholder | 0.5 | "经由共同企业股东「{S}」推断的关联,需人工核实是否构成共同控制。" |
| shared_person_shareholder | 0.2 | "经由同名自然人「{P}」关联(该姓名共连接 {N} 家库内公司),疑似重名,信息不可靠,须人工复核确认是否同一人。" |
| shared_investee | 0.25 | "经由共同对外投资「{E}」推断的弱关联,合资不等于同一控制。" |

### 噪声过滤(`RelatedPartyConfig`)

```python
class RelatedPartyConfig(BaseModel):
    corporate_degree_cap: int = 10   # 外部企业股东节点连接 > 此数 → 过滤
    investee_degree_cap: int = 10    # 共同对外投资节点 > 此数 → 过滤
    # 自然人:不设度上限(全展示 + 警示);shared_degree 照常计算并展示
    noise_keywords: tuple[str, ...] = (
        "证券投资基金", "指数", "etf", "登记结算", "中央结算", "nominees",
        "ubs", "barclays", "morgan", "goldman", "qfii",
    )
```

- **企业/投资侧**:对外部节点,先算度(连接的库内公司数)。度 > cap **或** 规范化节点名命中 `noise_keywords`(子串)→ 判为结构性噪声,剔除。命中关键词无视度数(宽基/托管即便只连 2 家也是伪关联)。PE/产业基金(有限合伙)不在关键词内 → 保留。
- **自然人侧**:**不过滤**。展示所有同名相连的库内公司,每条标 0.2 置信 + 须人工复核 + 显示 `shared_degree`(N 越大越可能重名)。
- 关键词在与节点名相同的规范化空间比较(均经 `normalize_company_name`)。

### 算法(`find_related_parties`)

1. 取锚点 X 自身边:`repository.get_shareholders(code)`、`get_investments(code)`。
2. 批量拉全部边构建反向索引(各扫一次):
   - `corp_index: node_name -> set(company_code)`(外部企业股东:`node_code is None and not is_person`)
   - `person_index: node_name -> set(company_code)`(自然人:`is_person`)
   - `investee_index: node_name -> set(company_code)`(外部被投资:`node_code is None`)
   - `names: code -> legal_name`(`get_all_company_names`)
3. **直接边**:X 的股东中 `shareholder_credit_code` 非空(库内 Y)→ `direct_shareholder`;X 的投资中 `investee_credit_code` 非空(库内 Y)→ `direct_investee`。
4. **共享企业股东**:对 X 的每个外部企业股东 S(`shareholder_credit_code is None and not is_person`),若 S 非噪声(度 ≤ cap 且不命中关键词):`corp_index[S] - {X}` 中每个 Y → `shared_corporate_shareholder`,`shared_degree=len(corp_index[S])`。
5. **共享自然人**:对 X 的每个自然人股东 P:`person_index[P] - {X}` 中每个 Y → `shared_person_shareholder`(不过滤),`shared_degree=len(person_index[P])`。
6. **共同对外投资**:对 X 的每个外部被投资 E(`investee_credit_code is None`),若 E 非噪声:`investee_index[E] - {X}` 中每个 Y → `shared_investee`,`shared_degree=len(investee_index[E])`。
7. **去重与排序**:同一 (related_code, relation_type, via_node_name) 去重;按 `(confidence 降序, related_code 升序)` 确定性排序。一家 Y 可因多条不同关系出现多次(不同 relation_type/via),保留(信息更全)。
8. 未知 code(不在库)或无关联 → 返回 `[]`。

---

## A5 Agent 接入

### 工具(`tools/procurement.py`,均 `read_private`,进白名单)

- `get_ownership_neighborhood`:`{"credit_code": code}` → `{"shareholders": [...], "investments": [...]}`(A3 两方法 `model_dump`)。
- `get_related_parties`:`{"credit_code": code}` → `{"related_parties": [...]}`(A4 `find_related_parties` 结果 `model_dump`)。

### Domain Pack(`domains/procurement/domain.yaml`)

- `research_dimensions` 追加:`ownership_structure`、`related_parties`。
- `allowed_tools` 追加:`get_ownership_neighborhood`、`get_related_parties`。
- `report_sections` 追加:`Ownership Structure`、`Related Parties`(置于 `Contact` 之后、`Evidence Table` 之前)。

### 编排(`agents/nodes.py`)

- `_DIMENSION_QUESTIONS` 追加两条:
  - `ownership_structure`: "What registered shareholders and outbound investments exist for {supplier_name}?"
  - `related_parties`: "What related parties can be inferred for {supplier_name} from shared ownership?"
- `researcher_node` 增两段(沿用现有 `_run_tool` + `allowed_tools` 守卫):
  - 若 `get_ownership_neighborhood` 在白名单:调用 → 对每个股东/投资各追加一条 `ownership_structure` 证据(置信 0.9);**若股东与投资都为空**,追加一条 "数据源未提供 {supplier_name} 的股东或对外投资数据。" 证据(维度算覆盖,守红线)。
  - 若 `get_related_parties` 在白名单:调用 → 对每个 `RelatedParty` 追加一条 `related_parties` 证据,claim 含关联公司名 + 关系类型(中文)+ `reliability_note`,`confidence=party.confidence`;**若为空**,追加一条 "数据源未发现 {supplier_name} 的可推断关联方。" 证据。
- 证据 `Citation` 用 `source_id=f"company:{code}"`、`url=f"local://companies/{code}"`,与现有工商证据一致。
- `critique_node` 无需改:新维度进 `plan` 后自动纳入覆盖计算;因 researcher 对空结果也产证据,维度恒被覆盖,不会触发空转。
- `writer_node`:recommendation 仍 `insufficient_evidence`;`open_questions` 追加一条 "股权关联方为线索级推断(尤其同名自然人),须人工复核,不构成控制关系或采购结论。"

### 关系类型中文标签(researcher 生成 claim 用)

`direct_shareholder`→"直接股东"、`direct_investee`→"直接被投资"、`shared_corporate_shareholder`→"共同企业股东"、`shared_person_shareholder`→"共同自然人(疑似)"、`shared_investee`→"共同对外投资"。

## 测试

**A4(`tests/test_ownership_links.py`,合成 fixture)**:扩展现有 `shareholders.csv`/`investments.csv` 或新增小 fixture,覆盖:
1. 直接边:库内 Y 持有 X → `direct_shareholder` 置信 0.9。
2. 共享企业股东:S 连 X、Y(度 2,非噪声)→ 双方互为 `shared_corporate_shareholder` 置信 0.5,`shared_degree=2`。
3. 噪声过滤:一个命中关键词的基金节点(如 "…证券投资基金")连 X、Y → **不**产生关联;一个度 > cap 的企业节点 → 不产生关联。
4. 自然人:同名 P 连 X、Y → `shared_person_shareholder` 置信 0.2、含"须人工复核"note、`shared_degree` 正确;**即使 P 的度很高也照常展示**(不过滤)。
5. 共同对外投资:E 连 X、Y(非噪声)→ `shared_investee` 置信 0.25。
6. 未知 code → `[]`;排序按 (confidence 降序, related_code 升序)。

**A5(`tests/test_nodes.py` / `tests/test_graph.py` 既有套件内)**:
1. researcher 对已解析公司追加 `ownership_structure` 与 `related_parties` 证据。
2. 空股权数据 → 两维度各有一条"数据源未提供/未发现"证据,且维度被覆盖(`missing_dimensions` 不含它们)。
3. writer 仍 `insufficient_evidence`,`open_questions` 含关联方人工复核免责。
4. 工具白名单守卫:未列入 `allowed_tools` 时不调用(沿用现有断言风格)。

**Repository(`tests/test_company_repository.py`)**:`iter_shareholder_edges`/`iter_investment_edges`/`get_all_company_names` 返回正确的边与名映射。

## 改动面汇总

- 新文件:`src/deepresearch_agent/ownership_links.py`、`tests/test_ownership_links.py`。
- 改:`company_models.py`(+`OwnershipEdge`、`RelatedParty`)、`company_repository.py`(+3 批量读)、`tools/procurement.py`(+2 工具)、`agents/nodes.py`(researcher/writer/维度问题)、`domains/procurement/domain.yaml`(维度/工具/章节)、相关测试。
- 不动:schema/`SCHEMA_VERSION`、graph 路由结构、writer 的 `insufficient_evidence` 红线。
