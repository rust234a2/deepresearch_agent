# SQLite 企业数据层设计

日期：2026-06-21

## 目标

以企查查清洗结果为唯一企业事实来源，重建正式企业模型和查询边界。CSV 保留为标准数据源，SQLite 作为可重复生成的本地查询产物，Agent 不再依赖两家英文演示供应商及其能力、合规、财务和采购历史字段。

## 范围

本模块包含：

- 把现有 `data/procurement/cleaned/` 迁移为 `data/procurement/processed/`，并以其中的 `companies.csv` 和 `contacts.csv` 为输入生成 SQLite。
- 让正式 Pydantic 模型覆盖清洗数据源中的工商和联系方式字段。
- 通过 Repository 按统一社会信用代码、法定名称和曾用名查询企业。
- 让供应商识别、采购工具和研究图只使用 SQLite 中真实存在的数据。
- 把采购 Domain Pack 收缩到当前数据源能够支持的研究维度。
- 删除旧的 `SupplierCapability`、`ComplianceProfile`、`FinancialProfile`、`ProcurementHistory` 和 `SupplierDueDiligenceProfile`。
- 停用 `data/procurement/suppliers.json` 及对应英文演示文档的运行时路径。

本模块不包含：

- 从经营范围推断结构化产品、产能、交期或认证。
- 制裁、司法、新闻、财务或内部采购数据。
- 经营范围分块、中文分词、FTS5、向量检索或 Qdrant。
- 把 SQLite 文件提交到 Git。

## 数据所有权和目录

数据流固定为：

```text
企查查原始 Excel（raw，本地忽略）
  -> 清洗 CSV（processed，本地忽略、事实标准）
  -> SQLite（derived，本地忽略、可重建）
  -> CompanyRepository
  -> 供应商识别 / 工具 / Agent
```

目录约定：

```text
data/procurement/raw/                 原始受限数据
data/procurement/processed/           companies.csv / contacts.csv / rejected.csv
data/procurement/derived/             companies.sqlite3
tests/fixtures/procurement/           可提交的合成测试 CSV
```

现有 `data/procurement/cleaned/` 在本模块中迁移为 `processed/`。原始和清洗后的真实企业数据继续由 `.gitignore` 排除；测试使用字段结构相同但内容完全合成的小型 fixture。

## 正式模型

### CompanyProfile

`CompanyProfile` 直接表达 `companies.csv` 的语义：

- 身份：`source_name`、`legal_name`、`unified_social_credit_code`、`aliases`、`english_name`。
- 登记：`registration_status`、`legal_representative`、`company_type`、`registration_authority`。
- 资本：注册资本和实缴资本各自保留 `amount`、`currency`、`original`。
- 日期：`established_date`、营业期限起止和是否无固定期限。
- 地址：注册地址、省、市、区县。
- 行业：国标行业门类、大类、中类、小类和企业规模。
- 经营：`business_scope`，保存完整原始经营范围。
- 补充：官网、参保人数、参保人数年报年份、最新年报年份、纳税人资质。

模型使用真实类型：金额为 `Decimal | None`，日期为 `date | None`，人数和年份为 `int | None`，无固定期限为 `bool`，别名为 `list[str]`。缺失文本统一为 `None`，不使用空字符串表达缺失。

### CompanyContact

`CompanyContact` 包含：

- `unified_social_credit_code`
- `legal_name`
- `phones: list[str]`
- `emails: list[str]`
- `mailing_address: str | None`

联系方式与企业通过统一社会信用代码关联。法定名称作为导入时的一致性校验字段，不作为关联键。

### 删除的模型

以下模型及所有字段映射全部删除，不保留空壳：

- `SupplierCapability`
- `ComplianceProfile`
- `FinancialProfile`
- `ProcurementHistory`
- `SupplierDueDiligenceProfile`

未来获得相应数据源时，再按数据源单独设计模型和表，不从经营范围推断这些字段。

## SQLite 结构

数据库路径默认为 `data/procurement/derived/companies.sqlite3`，设置 `PRAGMA user_version = 1`。

### companies

一行对应一家企业，统一社会信用代码为主键。字段覆盖 `CompanyProfile` 中除别名外的所有标量字段。数据库保留清洗 CSV 中金额原文，并将规范化金额存为十进制定点文本，避免 SQLite 浮点精度损失。

约束和索引：

- `unified_social_credit_code PRIMARY KEY`
- `legal_name NOT NULL`
- `normalized_legal_name NOT NULL`
- `UNIQUE(normalized_legal_name)`
- 登记状态、省、市、国标行业大类、企业规模普通索引

### company_aliases

每个曾用名一行：

- `unified_social_credit_code` 外键
- `alias`
- `normalized_alias`
- 企业内 `UNIQUE(unified_social_credit_code, normalized_alias)`
- `normalized_alias` 普通索引

同一个别名允许指向不同企业，查询时返回歧义结果，不擅自选择。

### company_contacts

每家企业最多一行：

- `unified_social_credit_code PRIMARY KEY` 且为外键
- `legal_name`
- `phones`，保留清洗 CSV 的管道分隔文本
- `emails`，保留清洗 CSV 的管道分隔文本
- `mailing_address`

Repository 输出模型时把电话和邮箱拆为列表。

### import_metadata

记录数据库版本、源文件 SHA-256、输入行数、导入行数和生成时间，用于判断 derived 数据是否对应当前 CSV。

## 构建流程

新增显式数据库构建命令，输入 processed 目录、输出数据库路径。流程为：

1. 校验两个 CSV 的表头与正式 schema 完全匹配。
2. 逐行解析并通过 Pydantic 模型验证类型。
3. 校验信用代码非空且唯一。
4. 校验 contacts 中的信用代码和法定名称能与 companies 对应。
5. 在同目录临时数据库中创建 schema，并在单个事务内写入。
6. 写入索引、`user_version` 和导入元数据。
7. 成功后原子替换目标数据库；任何失败都不覆盖旧数据库。

导入错误必须包含源文件名、CSV 行号、字段名和原始值。空数据集、重复信用代码、孤立联系方式、名称不一致或缺少必需列均使构建失败。

## Repository 边界

新增 `CompanyRepository`，运行时代码不直接读取 CSV 或执行散落 SQL。公开接口为：

```python
get_by_credit_code(code: str) -> CompanyRecord | None
resolve_text(text: str) -> CompanyResolution
get_contact(code: str) -> CompanyContact | None
```

`CompanyRecord` 组合 `CompanyProfile` 和可选 `CompanyContact`。名称规范化使用 NFKC、大小写折叠和空白折叠，与导入阶段保持一致。

`resolve_text` 接收完整研究问题，在规范化文本中确定性匹配全部法定名称和曾用名；英文名称使用字母数字边界，中文名称使用子串匹配。同一家企业命中多个名称时优先保留最长名称，法定名称在同长度下优先。结果只有三种：

- `resolved`：法定名称或别名唯一命中。
- `ambiguous`：同一规范化名称命中多家企业。
- `not_found`：没有命中。

## Agent 集成

### 供应商识别

`supplier_resolution.py` 改为使用 `CompanyRepository.resolve_text`，不再加载 `suppliers.json`。解析范围从两家演示供应商扩展到 SQLite 中全部企业。

### 工具

删除：

- `extract_supplier_profile`
- `check_sanctions_or_blacklist`

新增：

- `get_company_profile`：返回完整工商字段，包括原始经营范围。
- `get_company_contact`：返回数据源中的电话、邮箱和通信地址。

工具只返回数据库字段，不生成能力、认证、制裁或风险结论。

### Domain Pack 和研究节点

采购研究维度调整为当前数据源能够回答的内容：

- `company_identity`
- `registration`
- `capital`
- `industry_and_business_scope`
- `enterprise_scale`
- `contact`

研究节点按字段组生成事实性证据，citation 使用 `local://companies/<统一社会信用代码>`。`business_scope` 原文作为经营范围证据，不转换成结构化产品声明。

旧的本地英文文档检索、制裁判断和对应 Domain Pack 工具授权从当前运行路径移除。未来接入新数据源时再增加独立研究维度。

### 报告行为

保留现有 `SupplierReport` API 形状，避免无关的 API 破坏。由于单一工商数据源不足以作出采购批准、拒绝或风险结论，成功解析企业时推荐值统一为 `insufficient_evidence`。摘要说明已完成工商信息核验，开放问题明确列出尚未接入的数据类型。

报告不得使用“未发现风险”表示“没有风险数据”。

## 数据库缺失和错误处理

- SQLite 文件不存在时，启动研究返回明确错误，提示运行数据库构建命令；不静默回退到演示 fixture。
- SQLite schema 版本不支持时拒绝查询，并提示重建数据库。
- 单次查询不修改数据库；Repository 默认使用只读连接。
- 查不到企业时返回 `not_found`，同名时返回候选法定名称和信用代码。
- 联系方式缺失时返回 `None`，不影响工商信息查询。

## 测试策略

测试只使用合成 CSV 和临时 SQLite：

- 模型测试覆盖金额、日期、布尔值、列表和缺失值转换。
- 构建测试覆盖成功导入、schema、索引、元数据和原子替换。
- 构建失败测试覆盖表头错误、重复信用代码、孤立联系方式和名称不一致。
- Repository 测试覆盖信用代码、法定名称、别名、歧义和未知名称。
- 工具测试验证只返回数据源字段。
- 节点、图、API 和 CLI 测试验证 SQLite 端到端路径。
- 删除或重写所有依赖两家演示供应商、制裁 fixture 和旧模型的测试。

完整验收条件：全套测试通过；用真实 processed CSV 构建数据库后，数据库包含 3506 家企业、3506 条联系方式且信用代码无重复；万马科技可通过法定名称、统一社会信用代码和任一曾用名查询，返回完整经营范围。

## 迁移和兼容性

这是一次有意的不兼容数据模型迁移：

- 旧模型不提供弃用期。
- 旧工具名不保留别名。
- 旧 `suppliers.json` 不作为回退数据源。
- API 的报告外形保持不变，但报告内容和推荐语义改为严格受当前数据源约束。

项目文档和项目记忆必须同步说明新的数据所有权、构建命令、SQLite 路径和不支持的数据维度。
