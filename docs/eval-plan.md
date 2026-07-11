# 评估计划

**Eval v1 已落地**（2026-07-11）：见 `docs/superpowers/specs/2026-07-11-eval-v1-deterministic-metrics-design.md` 与 `eval/` 包。因 Agent 固定 `insufficient_evidence`、不出 approve/reject、未接风险源，只测两块真决策：**企业识别 P/R** 与 **scope recall@k**；推荐准确率/风险命中率标 N/A、GraphRAG 精准率后置。**不引入 RAGAS/LlamaIndex/Phoenix**（LLM-as-judge 撞本地化红线、且顺序应在确定性基线之后）。

后续评估阶段按以下顺序实施：

1. ✅ **已做（部分）**：建立 golden cases——合成 golden 已提交（`evals/procurement/*.synthetic.yaml`）；真实 golden 由本地补齐（`*.local.yaml`，不出库）。受限制/资料缺失等场景 case 待接入对应数据源后再加。
2. ✅ **已做（可测部分）**：确定性指标——企业识别 P/R + scope recall@k 已实现。推荐准确率/风险命中率/引用覆盖率待接入风险与推荐能力后再补。
3. 使用 RAGAS 评估 RAG 检索与回答质量。**（后置；需本地 LLM，红线敏感。）**
4. ✅ **已做（追踪部分）**：Phoenix 本地追踪已落地（`observability.py`，手动 span 在图层包四节点 + root span，`run_research(enable_tracing=True)`/CLI `--trace`）——**只做追踪/可视化,不用 LLM-eval**、仅本地、不外发企业数据。单工具/命中下钻 span、接 eval 指标进 Experiments 为后续。
5. 确定性指标稳定后，再考虑 LLM-as-judge。**（后置。）**

评估必须复用 `deepresearch_agent.agents.graph.run_research`，不得建立第二条执行路径。
