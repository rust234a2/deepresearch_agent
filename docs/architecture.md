# 架构

## 核心循环

v1 graph 选择 LangGraph，而不是普通线性 chain。供应商尽调不是一次性问答：Agent 需要规划研究维度、收集证据、检查覆盖率，并在证据缺失时回到检索和工具调用阶段继续补证。

## 项目整体结构图

这张图展示的是项目结构，而不是实施计划。当前采用 LangGraph 做研究编排，用 Domain Pack 做领域配置，用确定性本地工具、本地检索和预设供应商数据做 v1 基线。评估层、企查查导入、B2B 采集、实时爬取和 GraphRAG 均后置。

```mermaid
flowchart TB
    subgraph Interface["入口层"]
        CLI["CLI<br/>src/deepresearch_agent/cli.py<br/>方案：命令行运行单个 research 问题"]
        API["HTTP API<br/>src/deepresearch_agent/api.py<br/>方案：FastAPI 暴露 /research"]
    end

    subgraph EvalLayer["后置评估层：当前未实现"]
        Golden["Golden Cases<br/>后续建设确定性采购评估样例"]
        EvalModels["Eval Models<br/>后续定义 case 和 result 模型"]
        Metrics["Metrics<br/>后续实现推荐准确率 / 风险命中率<br/>引用覆盖率 / 缺失数据处理 / 检索召回"]
        Runner["Eval Runner<br/>后续复用 run_research<br/>不引入第二条执行路径"]
        EvalCLI["Eval CLI<br/>后续命令"]
    end

    subgraph Core["核心 Agent 编排层：LangGraph 方案"]
        RunResearch["run_research(question, domain)<br/>src/deepresearch_agent/agents/graph.py"]
        BuildGraph["build_graph(domain_pack)<br/>方案：StateGraph(ResearchState)"]
        Planner["planner_node<br/>解析供应商并处理歧义<br/>生成维度化研究计划"]
        Researcher["researcher_node<br/>调用工具<br/>执行本地检索<br/>写入 evidence 和 trace"]
        Critic["critic_node<br/>检查 plan 维度覆盖<br/>生成 missing_dimensions"]
        Writer["writer_node<br/>生成 SupplierReport<br/>approve / conditional / reject / insufficient_evidence"]
        Continue{"是否继续研究?<br/>missing_dimensions 存在<br/>且 iteration 未超预算"}
    end

    subgraph StateLayer["状态与报告模型层：Pydantic 方案"]
        ResearchState["ResearchState<br/>question / domain / supplier_name / supplier_resolution<br/>iteration / plan / evidence<br/>missing_dimensions / report / trace"]
        PlanItem["ResearchPlanItem<br/>dimension / question / priority"]
        Evidence["Evidence + Citation<br/>claim / dimension / confidence<br/>source_id / title / url / snippet"]
        Report["SupplierReport<br/>supplier_name / recommendation<br/>summary / risks<br/>evidence_table / open_questions"]
        Trace["ToolTrace<br/>tool_name / args / status<br/>latency_ms / permission_tier"]
    end

    subgraph DomainLayer["领域包层：Domain Pack 方案"]
        DomainYaml["domains/procurement/domain.yaml<br/>研究维度 / 允许工具<br/>报告章节 / 来源优先级<br/>HITL 策略"]
        DomainLoader["load_domain_pack()<br/>src/deepresearch_agent/domain.py<br/>方案：后续扩展新领域时复用 graph"]
    end

    subgraph ProcurementLayer["采购 v1 能力层：预设数据 + 本地确定性基线"]
        SupplierResolver["Supplier Resolver<br/>src/deepresearch_agent/supplier_resolution.py<br/>法定名称 + 别名确定性识别<br/>未知或歧义时不启动研究"]
        ToolBase["Tool Registry<br/>src/deepresearch_agent/tools/base.py<br/>方案：记录工具名、描述、权限层级<br/>timeout、latency、结构化结果<br/>边界设计接近 MCP metadata"]
        ProcurementTools["Procurement Tools<br/>src/deepresearch_agent/tools/procurement.py<br/>extract_supplier_profile<br/>check_sanctions_or_blacklist"]
        Retriever["LocalDocumentRetriever<br/>src/deepresearch_agent/retrieval/local.py<br/>方案：本地 Markdown 关键词检索<br/>作为 BM25 / 向量检索前的可测基线"]
        SupplierJson["data/procurement/suppliers.json<br/>第一版预设供应商结构化数据<br/>不接实时数据源"]
        LocalDocs["data/procurement/documents/*.md<br/>第一版预设供应商文档<br/>不接 B2B 爬取"]
    end

    subgraph TestsDocs["测试与文档层"]
        Tests["tests/<br/>状态 / Domain Pack / 数据加载 / 供应商识别<br/>工具 / 检索 / 节点 / 图路由 / API / CLI"]
        Docs["docs/<br/>architecture.md / eval-plan.md<br/>superpowers/specs / superpowers/plans"]
    end

    subgraph GraphRAGFuture["后续功能：GraphRAG 方案"]
        GRIngest["GraphRAG Ingestion<br/>文档切分 / 清洗 / 去重<br/>从供应商文档和外部数据抽取实体与关系"]
        EntityExtractor["Entity & Relation Extraction<br/>供应商 / 产品 / 认证 / 风险事件<br/>制裁主体 / 司法案件 / 新闻事件"]
        GraphStore["Graph Store<br/>供应商知识图谱<br/>实体、关系、来源、时间戳、置信度"]
        BM25["BM25 Sparse Retrieval<br/>关键词召回<br/>替换当前 overlap 检索<br/>用 Eval recall 衡量效果"]
        VectorStore["Qdrant Vector Store<br/>embedding 向量检索<br/>保存 chunk 向量和元数据"]
        HybridRetriever["Hybrid Retriever<br/>BM25 + Qdrant vector<br/>alpha tuning / reranker<br/>返回 evidence candidates"]
        GraphRetriever["Graph Retriever<br/>按供应商实体扩展邻居<br/>找关联风险、关联公司、事件路径<br/>补充结构化 graph evidence"]
        GraphContext["Graph Context Builder<br/>合并文本证据和图谱证据<br/>去重、排序、保留 citation"]
        GraphRAGWriter["GraphRAG Writer<br/>基于文本 evidence + graph evidence<br/>生成更完整的 SupplierReport"]
        MCP["MCP Server<br/>把采购工具和外部数据查询<br/>迁移到 MCP 工具边界后"]
        Storage["Postgres + Checkpointing<br/>保存 run / trace / evidence / graph context<br/>支持 LangGraph checkpoint"]
        ChinaData["中国企业数据适配器<br/>工商 / 司法 / 新闻 / 公告<br/>支持公开信息缺失场景"]
        LLMJudge["LLM-as-judge Eval<br/>报告质量 / groundedness<br/>证据一致性 / 风险解释充分性<br/>确定性指标稳定后加入"]
    end

    CLI --> RunResearch
    API --> RunResearch
    EvalCLI -.后续.-> Runner
    Golden -.后续.-> Runner
    EvalModels -.后续.-> Runner
    Runner -.后续复用.-> RunResearch

    RunResearch --> BuildGraph
    BuildGraph --> Planner
    Planner --> SupplierResolver
    SupplierResolver -->|唯一命中| Researcher
    SupplierResolver -->|未知或歧义| Writer
    Researcher --> Critic
    Critic --> Continue
    Continue -->|是，继续补证| Researcher
    Continue -->|否，进入写作| Writer
    Writer --> Report

    BuildGraph -.读写.-> ResearchState
    Planner --> PlanItem
    Researcher --> Evidence
    Researcher --> Trace
    Writer --> Report

    DomainYaml --> DomainLoader
    DomainYaml -.约束领域能力.-> Planner
    DomainYaml -.约束可用工具和报告结构.-> Researcher
    DomainYaml -.约束 HITL 风险策略.-> Writer

    Researcher --> ToolBase
    ToolBase --> ProcurementTools
    ProcurementTools --> SupplierJson
    Researcher --> Retriever
    Retriever --> LocalDocs

    Runner -.后续.-> Metrics
    Report -.后续评估.-> Metrics
    Metrics -.后续测试.-> Tests

    Tests -.覆盖.-> ResearchState
    Tests -.覆盖.-> BuildGraph
    Tests -.覆盖.-> ProcurementTools
    Docs -.记录方案.-> BuildGraph
    Docs -.记录评估计划.-> Runner

    LocalDocs -.后续进入.-> GRIngest
    SupplierJson -.后续进入.-> GRIngest
    ProcurementTools -.后续接入.-> ChinaData
    ChinaData -.外部数据进入.-> GRIngest
    GRIngest --> EntityExtractor
    EntityExtractor --> GraphStore
    GRIngest --> BM25
    GRIngest --> VectorStore
    Retriever -.后续替换.-> BM25
    BM25 --> HybridRetriever
    VectorStore --> HybridRetriever
    GraphStore --> GraphRetriever
    HybridRetriever --> GraphContext
    GraphRetriever --> GraphContext
    GraphContext --> GraphRAGWriter
    GraphRAGWriter -.替换或增强.-> Writer
    ToolBase -.后续迁移.-> MCP
    RunResearch -.后续持久化.-> Storage
    Metrics -.后续增强.-> LLMJudge
    Report --> LLMJudge
```

## 项目思维导图

```mermaid
mindmap
  root((DeepResearch Agent 项目方案))
    当前目标
      采购供应商尽调
      多证据来源研究
      带引用报告
      可评估 Agent 行为
    当前选定方案
      LangGraph 编排
        planner 规划维度
        researcher 收集证据
        critic 检查缺口
        writer 生成报告
      Domain Pack 配置领域
        domains/procurement/domain.yaml
        研究维度
        允许工具
        报告章节
        HITL 策略
      本地确定性基线
        本地工具
        本地 Markdown 检索
        本地预设供应商数据
        第一版不做实时爬取
        第一版不做企查查导入
      评估层后置
        可用版完成后建立 golden cases
        RAGAS 用于 RAG 质量评估
        Phoenix 用于轨迹调试
    入口层
      cli.py
        命令行运行 research
        后续支持 eval procurement
      api.py
        FastAPI
        POST /research
    核心编排层
      agents/graph.py
        build_graph
        run_research
        StateGraph ResearchState
      agents/nodes.py
        planner_node
        supplier_resolution
        researcher_node
        critique_node
        writer_node
    状态模型层
      state.py
        ResearchState
        SupplierResolution
        ResearchPlanItem
        Evidence
        Citation
        ToolTrace
        SupplierReport
      domain.py
        load_domain_pack
        DomainPack
        HitlPolicy
    数据层
      结构化数据
        data/procurement/suppliers.json
        第一版预设数据
        供应商国家
        产品
        认证
        交付能力
        风险摘要
        listed 标记
      非结构化数据
        data/procurement/documents/*.md
        第一版预设文档
        供应商文档
        检索 snippet
        citation 来源
      评估数据
        后续建设 golden cases
        当前版本未实现
      运行时数据
        plan
        evidence
        trace
        missing_dimensions
        report
      后续持久化数据
        Postgres runs
        Postgres evidence
        Postgres traces
        LangGraph checkpoint
        Qdrant vectors
        Graph Store triples
    研究能力层
      tools/base.py
        ToolRegistry
        RegisteredTool
        ToolResult
        permission_tier
        latency_ms
      tools/procurement.py
        extract_supplier_profile
        check_sanctions_or_blacklist
        读取 suppliers.json
      retrieval/local.py
        LocalDocumentRetriever
        关键词 overlap 检索
        返回 source_id title url snippet score
    后置评估层
      当前版本未实现
      eval/models.py
        GoldenCase
        ExpectedOutcome
        EvalCaseResult
        EvalSummary
      eval/metrics.py
        recommendation_accuracy
        risk_hit_rate
        citation_coverage
        missing_data_handling
        retrieval_recall_at_k
      eval/runner.py
        加载 golden cases
        调用 run_research
        计算 EvalSummary
    后续 GraphRAG 方案
      数据接入
        中国企业数据适配器
        工商信息
        司法风险
        新闻公告
        供应商文档
      索引构建
        GraphRAG Ingestion
        文档切分
        清洗去重
        实体抽取
        关系抽取
      图谱层
        Graph Store
        供应商实体
        产品实体
        认证实体
        风险事件
        关系路径
        来源和置信度
      检索层
        BM25 Sparse Retrieval
        Qdrant Vector Store
        Hybrid Retriever
        alpha tuning
        reranker
        Graph Retriever
      上下文层
        Graph Context Builder
        合并文本证据
        合并图谱证据
        去重排序
        保留 citation
      生成层
        GraphRAG Writer
        文本 evidence
        graph evidence
        SupplierReport
      评估增强
        LLM-as-judge
        groundedness
        证据一致性
        风险解释充分性
        报告质量
      工具服务化
        MCP Server
        外部数据查询工具
        采购工具服务化
```

## 节点

- `planner`：通过预设法定名称和别名确定性识别供应商；唯一命中后创建研究计划，未知或歧义时直接进入证据不足报告。
- `researcher`：调用确定性采购工具和本地检索。
- `critic`：根据 plan 检查 evidence 覆盖情况。
- `writer`：生成带引用的供应商尽调报告；供应商未解析时生成 `insufficient_evidence` 报告。

## 领域包边界

采购领域包位于 `domains/procurement/domain.yaml`。后续新增领域时，应通过各自的 domain pack 定义研究维度、允许工具、报告章节、来源优先级和 HITL 规则，而不是重写 graph。

## 工具边界

v1 工具注册表记录工具名、描述、权限层级、timeout、latency 和结构化结果。这个设计有意接近 MCP tool metadata，方便在后续里程碑中把工具迁移到 MCP server 后面。
