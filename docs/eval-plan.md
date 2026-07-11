# 评估计划

**Eval v1 已落地**（2026-07-11）：见 `docs/superpowers/specs/2026-07-11-eval-v1-deterministic-metrics-design.md` 与 `eval/` 包。因 Agent 固定 `insufficient_evidence`、不出 approve/reject、未接风险源，只测两块真决策：**企业识别 P/R** 与 **scope recall@k**；推荐准确率/风险命中率标 N/A、GraphRAG 精准率后置。**不引入 RAGAS/LlamaIndex/Phoenix**（LLM-as-judge 撞本地化红线、且顺序应在确定性基线之后）。

后续评估阶段按以下顺序实施：

1. ✅ **已做（部分）**：建立 golden cases——合成 golden 已提交（`evals/procurement/*.synthetic.yaml`）；真实 golden 由本地补齐（`*.local.yaml`，不出库）。受限制/资料缺失等场景 case 待接入对应数据源后再加。
2. ✅ **已做（可测部分）**：确定性指标——企业识别 P/R + scope recall@k 已实现。推荐准确率/风险命中率/引用覆盖率待接入风险与推荐能力后再补。
3. 使用 RAGAS 评估 RAG 检索与回答质量。**（后置；需本地 LLM，红线敏感。）**
4. 使用 Phoenix 调试检索、工具调用和 Agent 轨迹。**（后置；本地自建、当调试工具用。）**
5. 确定性指标稳定后，再考虑 LLM-as-judge。**（后置。）**

评估必须复用 `deepresearch_agent.agents.graph.run_research`，不得建立第二条执行路径。
